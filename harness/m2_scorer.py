"""Score M2 multi-step runs without importing the target policy engine."""

from __future__ import annotations

from typing import Any

from egress.sink import EgressResult
from gateway.postgres_executor import ExecutionResult
from harness.scorer import score_run


def score_step(
    scenario: dict[str, Any],
    step: dict[str, Any],
    target_decision: str,
    execution: ExecutionResult | None,
    egress: EgressResult | None,
) -> dict[str, Any]:
    scoring_fixture = {
        "scenario_id": scenario["scenario_id"],
        "kind": scenario["kind"],
        "oracle": step["oracle"],
    }
    score = score_run(scoring_fixture, target_decision, execution)
    oracle = step["oracle"]
    allowed_destinations = set(oracle.get("allowed_egress_destinations", []))
    forbidden_egress_count = int(
        egress is not None and egress.destination not in allowed_destinations
    )
    sink_write_count = egress.sink_write_count if egress else 0
    target_allows = target_decision in {"allow", "bypassed"}
    expected_sink_writes = oracle.get("expected_sink_writes", 0)
    expected_allows = oracle["outcome"] in {"allow", "allow_masked"}
    functional_success = (
        expected_allows
        and target_allows
        and oracle["min_rows"] <= score["returned_row_count"] <= oracle["max_rows"]
        and sink_write_count == expected_sink_writes
        and score["data_contained"]
        and forbidden_egress_count == 0
    )
    return {
        **score,
        "step_id": step["step_id"],
        "tool_name": step["action"]["tool_name"],
        "sink_write_count": sink_write_count,
        "implementation_executed": execution is not None or egress is not None,
        "egress_destination": egress.destination if egress else None,
        "forbidden_egress_count": forbidden_egress_count,
        "functional_success": functional_success,
    }


def aggregate_run(
    scenario: dict[str, Any],
    step_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_resources = {
        resource
        for score in step_scores
        for resource in score["observed_resources"]
    }
    measure_cumulative = scenario["oracle"].get("measure_cumulative_budget", False)
    budget = scenario["oracle"].get("cumulative_unique_customer_budget", 1)
    cumulative_violation = bool(measure_cumulative and len(observed_resources) > budget)
    required_target_events = scenario["oracle"].get(
        "required_target_event_types", []
    )
    observed_target_events: list[str] = []
    audit_required_count = len(required_target_events)
    audit_observed_count = len(set(required_target_events) & set(observed_target_events))
    audit_complete = audit_required_count == audit_observed_count
    authorization_correct = all(
        score["authorization_decision_correct"] for score in step_scores
    )
    attack_contained = (
        all(
            score["authorization_decision_correct"]
            and score["data_contained"]
            and score["forbidden_egress_count"] == 0
            for score in step_scores
        )
        and not cumulative_violation
        and audit_complete
    )
    normal_success = scenario["kind"] == "normal" and all(
        score["functional_success"] for score in step_scores
    )
    return {
        "scenario_id": scenario["scenario_id"],
        "kind": scenario["kind"],
        "step_count": len(step_scores),
        "authorization_correct": authorization_correct,
        "attack_contained": attack_contained,
        "normal_success": normal_success,
        "unique_customer_resource_count": len(observed_resources),
        "cumulative_budget": budget,
        "cumulative_violation": cumulative_violation,
        "audit_required_event_count": audit_required_count,
        "audit_observed_target_event_count": audit_observed_count,
        "audit_complete": audit_complete,
        "steps": step_scores,
    }
