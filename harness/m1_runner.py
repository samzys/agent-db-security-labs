"""Run the 8-scenario x 4-profile M1 forced-replay matrix."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from audit.events import EventChain, verify_records
from gateway.policy import Decision, PolicyGateway, ProposedAction, TrustedContext
from gateway.postgres_executor import ExecutionResult, PostgresExecutor
from harness.oracle import MANIFEST
from harness.scorer import score_run


ARTIFACT_DIR = Path("artifacts/m1")


def _context(raw: dict[str, Any]) -> TrustedContext:
    return TrustedContext(
        user_id=raw["user_id"],
        agent_id=raw["agent_id"],
        task_id=raw["task_id"],
        ticket_id=raw["ticket_id"],
        tenant_id=raw["tenant_id"],
        scopes=frozenset(raw["scopes"]),
        allow_email_plaintext=raw["allow_email_plaintext"],
    )


def _action(raw: dict[str, Any]) -> ProposedAction:
    return ProposedAction(raw["tool_name"], raw["arguments"])


def _fingerprint(action: ProposedAction) -> str:
    encoded = json.dumps(
        {"tool_name": action.tool_name, "arguments": action.arguments},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _event_chain(
    scenario: dict[str, Any],
    profile_id: str,
    context: TrustedContext,
    action: ProposedAction,
    decision: Decision,
    execution: ExecutionResult | None,
    score: dict[str, Any],
) -> EventChain:
    run_id = f"m1-{scenario['scenario_id'].lower()}-{profile_id.lower()}"
    chain = EventChain(run_id, scenario["scenario_id"], profile_id)
    chain.append("run_started", producer="harness_observer", decision="not_evaluated")
    chain.append(
        "trusted_context_received",
        producer="harness_observer",
        user_id=context.user_id,
        agent_id=context.agent_id,
        task_id=context.task_id,
        tenant_id=context.tenant_id,
        decision="not_evaluated",
    )
    chain.append(
        "tool_proposed",
        producer="harness_observer",
        tool_name=action.tool_name,
        query_fingerprint=_fingerprint(action),
        decision="not_evaluated",
    )
    if scenario["bypass_gateway"]:
        chain.append(
            "gateway_bypassed",
            producer="harness_observer",
            control_stage="fault_injection",
            decision="bypassed",
            reason_code=decision.reason_code,
        )
    else:
        chain.append(
            "tool_authz_decision",
            producer="harness_observer",
            control_stage=f"profile_{profile_id.lower()}",
            decision=decision.outcome,
            reason_code=decision.reason_code,
            effective_resource=decision.effective_resource,
        )
    if execution is not None:
        chain.append(
            "db_query_executed",
            producer="harness_observer",
            query_kind=execution.query_kind,
            decision="executed",
        )
        chain.append(
            "db_result_received",
            producer="harness_observer",
            result_row_count=execution.row_count,
            sensitive_plaintext_count=execution.sensitive_plaintext_count,
            decision="observed",
        )
        chain.append(
            "context_admitted",
            producer="harness_observer",
            result_row_count=execution.row_count,
            forbidden_row_count=score["forbidden_row_count"],
            forbidden_field_count=score["forbidden_field_count"],
            decision="observed",
        )
    chain.append(
        "run_finished",
        producer="harness_observer",
        decision=decision.outcome,
        authorization_decision_correct=score["authorization_decision_correct"],
        data_contained=score["data_contained"],
    )
    return chain


def _profile_metrics(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    metrics: dict[str, dict[str, int]] = {}
    for profile_id in MANIFEST["profiles"]:
        profile_results = [row for row in results if row["profile_id"] == profile_id]
        normal = [row for row in profile_results if row["kind"] == "normal"]
        attacks = [row for row in profile_results if row["kind"] == "attack"]
        metrics[profile_id] = {
            "run_count": len(profile_results),
            "normal_success_count": sum(row["normal_success"] for row in normal),
            "normal_count": len(normal),
            "attack_authorization_correct_count": sum(
                row["authorization_decision_correct"] for row in attacks
            ),
            "attack_data_contained_count": sum(
                row["data_contained"] for row in attacks
            ),
            "attack_count": len(attacks),
            "unauthorized_execution_count": sum(
                row["query_executed"] and row["oracle_outcome"] == "deny"
                for row in attacks
            ),
            "forbidden_row_count": sum(row["forbidden_row_count"] for row in attacks),
            "forbidden_field_count": sum(
                row["forbidden_field_count"] for row in attacks
            ),
        }
    return metrics


def run() -> Path:
    if ARTIFACT_DIR.exists():
        shutil.rmtree(ARTIFACT_DIR)
    runs_dir = ARTIFACT_DIR / "runs"
    runs_dir.mkdir(parents=True)

    gateway = PolicyGateway()
    executor = PostgresExecutor()
    results: list[dict[str, Any]] = []
    for scenario in MANIFEST["scenarios"]:
        context = _context(scenario["context"])
        action = _action(scenario["action"])
        for profile_id in MANIFEST["profiles"]:
            if scenario["bypass_gateway"]:
                decision = Decision("bypassed", "GATEWAY_BYPASS_FIXTURE")
            else:
                decision = gateway.decide(profile_id, context, action)
            execution = None
            if decision.outcome in {"allow", "bypassed"}:
                execution = executor.execute(
                    profile_id,
                    context,
                    action,
                    decision,
                )
            score = score_run(scenario, decision.outcome, execution)
            result = {
                "profile_id": profile_id,
                "decision_reason": decision.reason_code,
                **score,
            }
            chain = _event_chain(
                scenario,
                profile_id,
                context,
                action,
                decision,
                execution,
                score,
            )
            valid, reason = verify_records(chain.records)
            if not valid:
                raise RuntimeError(reason)
            artifact_path = runs_dir / f"{scenario['scenario_id'].lower()}-{profile_id.lower()}.jsonl"
            chain.write(artifact_path)
            result["artifact"] = str(artifact_path)
            results.append(result)

    report = {
        "schema_version": "m1-report/0.1",
        "oracle_version": MANIFEST["version"],
        "run_count": len(results),
        "scenario_count": len(MANIFEST["scenarios"]),
        "profiles": MANIFEST["profiles"],
        "profile_metrics": _profile_metrics(results),
        "results": results,
        "limitations": [
            "forced replay only; no real model was invoked",
            "P4/P5 database and lifecycle controls are not evaluated",
            "events are harness observations, not target-native audit completeness",
        ],
    }
    report_path = ARTIFACT_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"M1 report written: {report_path} ({len(results)} runs)")
    return report_path


if __name__ == "__main__":
    run()
