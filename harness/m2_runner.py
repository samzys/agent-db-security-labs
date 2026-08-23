"""Run the complete 14-scenario P0-P3 M2 forced-replay baseline."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from audit.events import EventChain, verify_records
from egress.sink import EgressResult, SyntheticEgressSink
from gateway.catalog import catalog_fingerprint
from gateway.policy import Decision, PolicyGateway, ProposedAction, TrustedContext
from gateway.postgres_executor import ExecutionResult, PostgresExecutor
from harness.m2_oracle import MANIFEST
from harness.m2_scorer import aggregate_run, score_step


ARTIFACT_DIR = Path("artifacts/m2")
REPORT_SCHEMA = "agent-db-report/0.2"


def _context(raw: dict[str, Any]) -> TrustedContext:
    return TrustedContext(
        user_id=raw["user_id"],
        agent_id=raw["agent_id"],
        task_id=raw["task_id"],
        ticket_id=raw["ticket_id"],
        tenant_id=raw["tenant_id"],
        scopes=frozenset(raw["scopes"]),
        allow_email_plaintext=raw["allow_email_plaintext"],
        lifecycle_state=raw["lifecycle_state"],
        delegated_ticket_ids=frozenset(raw["delegated_ticket_ids"]),
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


def _tool_stage(profile_id: str, decision: Decision) -> tuple[str, str]:
    if int(profile_id[1:]) < 2:
        return "not_evaluated", "PROFILE_HAS_NO_TOOL_AUTHZ"
    if decision.reason_code == "TOOL_SCOPE_MISSING":
        return "deny", decision.reason_code
    return "allow", "TOOL_SCOPE_PRESENT"


def _task_stage(
    profile_id: str,
    action: ProposedAction,
    decision: Decision,
) -> tuple[str, str]:
    if int(profile_id[1:]) < 3 or action.tool_name == "egress_send":
        return "not_evaluated", "PROFILE_HAS_NO_TASK_AUTHZ_FOR_ACTION"
    return decision.outcome, decision.reason_code


def _append_step_events(
    chain: EventChain,
    scenario: dict[str, Any],
    step: dict[str, Any],
    profile_id: str,
    context: TrustedContext,
    action: ProposedAction,
    decision: Decision,
    execution: ExecutionResult | None,
    egress: EgressResult | None,
    score: dict[str, Any],
) -> None:
    common = {"producer": "harness_observer", "step_id": step["step_id"]}
    source_hash = "sha256:" + hashlib.sha256(
        f"{scenario['scenario_id']}:{step['step_id']}".encode("utf-8")
    ).hexdigest()
    chain.append(
        "untrusted_source_read",
        **common,
        fixture_id=scenario["scenario_id"],
        source_hash=source_hash,
        decision="observed",
    )
    chain.append(
        "tool_proposed",
        **common,
        tool_name=action.tool_name,
        query_fingerprint=_fingerprint(action),
        decision="not_evaluated",
    )
    tool_outcome, tool_reason = _tool_stage(profile_id, decision)
    chain.append(
        "tool_authz_decision",
        **common,
        control_stage="tool_authorization",
        decision=tool_outcome,
        reason_code=tool_reason,
    )
    task_outcome, task_reason = _task_stage(profile_id, action, decision)
    chain.append(
        "task_authz_decision",
        **common,
        control_stage="task_capability",
        decision=task_outcome,
        reason_code=task_reason,
        effective_resource=decision.effective_resource,
    )
    chain.append(
        "revocation_checked",
        **common,
        control_stage="lifecycle",
        lifecycle_state=context.lifecycle_state,
        decision="not_evaluated",
        reason_code="PROFILE_HAS_NO_LIFECYCLE_CONTROL",
    )

    if action.tool_name == "egress_send":
        chain.append(
            "egress_attempted",
            **common,
            destination=action.arguments["destination"],
            payload_ref=action.arguments["payload_ref"],
            decision="observed",
        )
        chain.append(
            "egress_decision",
            **common,
            control_stage="egress_policy",
            decision=decision.outcome,
            reason_code=decision.reason_code,
        )
        if egress is not None:
            chain.append(
                "egress_sink_written",
                **common,
                destination=egress.destination,
                sink_write_count=egress.sink_write_count,
                forbidden_egress_count=score["forbidden_egress_count"],
                decision="written",
            )
        return

    if execution is None:
        return
    chain.append(
        "db_query_prepared",
        **common,
        query_kind=execution.query_kind,
        decision="prepared",
    )
    chain.append(
        "db_query_executed",
        **common,
        query_kind=execution.query_kind,
        decision="executed",
    )
    chain.append(
        "db_result_received",
        **common,
        result_row_count=execution.row_count,
        sensitive_plaintext_count=execution.sensitive_plaintext_count,
        decision="observed",
    )
    chain.append(
        "result_policy_decision",
        **common,
        control_stage="result_policy",
        decision="not_evaluated",
        reason_code="PROFILE_HAS_NO_RESULT_LIFECYCLE_CONTROL",
    )
    chain.append(
        "context_admitted",
        **common,
        result_row_count=execution.row_count,
        forbidden_row_count=score["forbidden_row_count"],
        forbidden_field_count=score["forbidden_field_count"],
        forbidden_plaintext_count=score["forbidden_plaintext_count"],
        decision="admitted",
    )


def _execute_step(
    gateway: PolicyGateway,
    db: PostgresExecutor,
    sink: SyntheticEgressSink,
    scenario: dict[str, Any],
    step: dict[str, Any],
    profile_id: str,
    context: TrustedContext,
) -> tuple[Decision, ExecutionResult | None, EgressResult | None]:
    action = _action(step["action"])
    if step["bypass_gateway"]:
        decision = Decision("bypassed", "GATEWAY_BYPASS_FIXTURE")
    else:
        decision = gateway.decide(profile_id, context, action)
    execution = None
    egress = None
    if decision.outcome in {"allow", "bypassed"}:
        if action.tool_name == "egress_send":
            egress = sink.send(action)
        else:
            execution = db.execute(profile_id, context, action, decision)
    return decision, execution, egress


def _profile_metrics(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for profile_id in MANIFEST["profiles"]:
        runs = [row for row in results if row["profile_id"] == profile_id]
        normal = [row for row in runs if row["kind"] == "normal"]
        attacks = [row for row in runs if row["kind"] == "attack"]
        steps = [step for row in runs for step in row["steps"]]
        attack_steps = [step for row in attacks for step in row["steps"]]
        forbidden_attempts = [
            step for step in attack_steps if step["oracle_outcome"] == "deny"
        ]
        forbidden_queries = [
            step
            for step in forbidden_attempts
            if step["tool_name"].startswith("db_")
        ]
        forbidden_egress = [
            step for step in forbidden_attempts if step["tool_name"] == "egress_send"
        ]
        revoked = [
            row for row in attacks if row["lifecycle_state"] in {"revoked", "expired"}
        ]
        cumulative = [
            row for row in attacks if row["scenario_id"] == "A-09"
        ]
        audit = [row for row in attacks if row["audit_required_event_count"] > 0]
        metrics[profile_id] = {
            "run_count": len(runs),
            "action_attempt_count": len(steps),
            "normal": {
                "success_count": sum(row["normal_success"] for row in normal),
                "total": len(normal),
                "false_block_count": sum(
                    any(
                        step["oracle_outcome"] in {"allow", "allow_masked"}
                        and step["target_decision"] == "deny"
                        for step in row["steps"]
                    )
                    for row in normal
                ),
                "false_mask_count": sum(
                    any(step["forbidden_plaintext_count"] > 0 for step in row["steps"])
                    for row in normal
                ),
            },
            "authorization": {
                "correct_attack_scenario_count": sum(
                    row["authorization_correct"] for row in attacks
                ),
                "attack_scenario_count": len(attacks),
                "contained_attack_scenario_count": sum(
                    row["attack_contained"] for row in attacks
                ),
                "unauthorized_implementation_count": sum(
                    step["implementation_executed"] for step in forbidden_attempts
                ),
                "unauthorized_attempt_count": len(forbidden_attempts),
            },
            "query": {
                "unauthorized_execution_count": sum(
                    step["query_executed"] for step in forbidden_queries
                ),
                "unauthorized_attempt_count": len(forbidden_queries),
            },
            "data_context": {
                "forbidden_row_count": sum(
                    step["forbidden_row_count"] for step in steps
                ),
                "forbidden_field_count": sum(
                    step["forbidden_field_count"] for step in steps
                ),
                "forbidden_plaintext_count": sum(
                    step["forbidden_plaintext_count"] for step in steps
                ),
            },
            "egress": {
                "forbidden_success_count": sum(
                    step["sink_write_count"] for step in forbidden_egress
                ),
                "forbidden_attempt_count": len(forbidden_egress),
            },
            "lifecycle": {
                "revocation_failure_count": sum(
                    any(step["implementation_executed"] for step in row["steps"])
                    for row in revoked
                ),
                "revocation_replay_count": len(revoked),
                "cumulative_violation_count": sum(
                    row["cumulative_violation"] for row in cumulative
                ),
                "cumulative_task_count": len(cumulative),
            },
            "audit": {
                "target_event_observed_count": sum(
                    row["audit_observed_target_event_count"] for row in audit
                ),
                "target_event_required_count": sum(
                    row["audit_required_event_count"] for row in audit
                ),
                "valid_evidence_chain_count": sum(row["evidence_chain_valid"] for row in runs),
                "evidence_chain_count": len(runs),
            },
        }
    return metrics


def _write_report_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# M2 P0-P3 forced-replay report",
        "",
        "Generated only from `report.json`.",
        "",
        "| Profile | Normal success | Attack auth correct | Attacks contained | Unauthorized impl |",
        "|---|---:|---:|---:|---:|",
    ]
    for profile_id in report["profiles"]:
        row = report["profile_metrics"][profile_id]
        lines.append(
            "| {profile} | {normal}/{normal_total} | {auth}/{attack_total} | "
            "{contained}/{attack_total} | {unauthorized}/{attempts} |".format(
                profile=profile_id,
                normal=row["normal"]["success_count"],
                normal_total=row["normal"]["total"],
                auth=row["authorization"]["correct_attack_scenario_count"],
                attack_total=row["authorization"]["attack_scenario_count"],
                contained=row["authorization"]["contained_attack_scenario_count"],
                unauthorized=row["authorization"]["unauthorized_implementation_count"],
                attempts=row["authorization"]["unauthorized_attempt_count"],
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git_value(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_release_surface(report: dict[str, Any]) -> None:
    manifest = {
        "schema_version": "experiment-manifest/0.1",
        "source_revision": _git_value("rev-parse", "HEAD"),
        "working_tree_dirty": bool(_git_value("status", "--porcelain")),
        "postgresql_version": subprocess.run(
            ["/opt/homebrew/opt/postgresql@17/bin/psql", "--version"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "planner": {"mode": "forced_replay", "model_id": None, "digest": None},
        "profiles": report["profiles"],
        "policy_version": "p0-p3/0.2",
        "oracle_version": report["oracle_version"],
        "evidence_schema_version": "agent-db-evidence/0.1",
        "report_schema_version": REPORT_SCHEMA,
        "catalog_fingerprints": {
            profile_id: catalog_fingerprint(profile_id)
            for profile_id in report["profiles"]
        },
        "seed": "synthetic-postgres-fixture/0.2",
    }
    (ARTIFACT_DIR / "experiment-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_report_markdown(report, ARTIFACT_DIR / "report.md")
    (ARTIFACT_DIR / "limitations.md").write_text(
        "# M2 limitations\n\n"
        "- Deterministic forced replay only; no real model was invoked.\n"
        "- P4 database enforcement and P5 lifecycle controls are absent.\n"
        "- Target-native audit events are not implemented; harness observations are separate.\n"
        "- Local latency, concurrency, pool isolation, and credential lifecycle are unmeasured.\n",
        encoding="utf-8",
    )
    artifact_files = sorted(
        path for path in ARTIFACT_DIR.rglob("*") if path.is_file()
    )
    checksums = []
    for path in artifact_files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        checksums.append(f"{digest}  {path.relative_to(ARTIFACT_DIR)}")
    (ARTIFACT_DIR / "checksums.txt").write_text(
        "\n".join(checksums) + "\n",
        encoding="utf-8",
    )


def run() -> Path:
    if ARTIFACT_DIR.exists():
        shutil.rmtree(ARTIFACT_DIR)
    runs_dir = ARTIFACT_DIR / "runs"
    runs_dir.mkdir(parents=True)

    gateway = PolicyGateway()
    db = PostgresExecutor()
    results: list[dict[str, Any]] = []
    for scenario in MANIFEST["scenarios"]:
        context = _context(scenario["context"])
        for profile_id in MANIFEST["profiles"]:
            sink = SyntheticEgressSink()
            run_id = f"m2-{scenario['scenario_id'].lower()}-{profile_id.lower()}"
            chain = EventChain(run_id, scenario["scenario_id"], profile_id)
            chain.append(
                "run_started",
                producer="harness_observer",
                decision="not_evaluated",
            )
            chain.append(
                "trusted_context_received",
                producer="harness_observer",
                user_id=context.user_id,
                agent_id=context.agent_id,
                task_id=context.task_id,
                tenant_id=context.tenant_id,
                lifecycle_state=context.lifecycle_state,
                decision="observed",
            )
            step_scores = []
            for step in scenario["steps"]:
                action = _action(step["action"])
                decision, execution, egress = _execute_step(
                    gateway,
                    db,
                    sink,
                    scenario,
                    step,
                    profile_id,
                    context,
                )
                score = score_step(
                    scenario,
                    step,
                    decision.outcome,
                    execution,
                    egress,
                )
                score["decision_reason"] = decision.reason_code
                _append_step_events(
                    chain,
                    scenario,
                    step,
                    profile_id,
                    context,
                    action,
                    decision,
                    execution,
                    egress,
                    score,
                )
                step_scores.append(score)
            result = {
                "profile_id": profile_id,
                "lifecycle_state": context.lifecycle_state,
                **aggregate_run(scenario, step_scores),
            }
            chain.append(
                "run_finished",
                producer="harness_observer",
                decision="observed",
                authorization_correct=result["authorization_correct"],
                attack_contained=result["attack_contained"],
                normal_success=result["normal_success"],
            )
            valid, reason = verify_records(chain.records)
            if not valid:
                raise RuntimeError(reason)
            result["evidence_chain_valid"] = True
            artifact_path = (
                runs_dir
                / f"{scenario['scenario_id'].lower()}-{profile_id.lower()}.jsonl"
            )
            chain.write(artifact_path)
            result["artifact"] = str(artifact_path)
            results.append(result)

    report = {
        "schema_version": REPORT_SCHEMA,
        "oracle_version": MANIFEST["version"],
        "run_count": len(results),
        "action_attempt_count": sum(row["step_count"] for row in results),
        "scenario_count": len(MANIFEST["scenarios"]),
        "profiles": MANIFEST["profiles"],
        "profile_metrics": _profile_metrics(results),
        "results": results,
        "metric_json_pointers": {
            "profile_metrics": "/profile_metrics/{profile_id}",
            "run_result": "/results/{run_index}",
        },
        "limitations": [
            "forced replay only; no real model was invoked",
            "P4/P5 controls are not evaluated",
            "target-native audit is not implemented",
        ],
    }
    report_path = ARTIFACT_DIR / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_release_surface(report)
    print(
        f"M2 report written: {report_path} "
        f"({len(results)} runs, {report['action_attempt_count']} actions)"
    )
    return report_path


if __name__ == "__main__":
    run()
