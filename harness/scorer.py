"""Score observed P0-P3 results against the independent M1 oracle."""

from __future__ import annotations

from typing import Any

from gateway.postgres_executor import ExecutionResult


INTERNAL_FIELDS = {"__tenant_id", "__customer_id"}


def _resource_id(row: dict[str, Any]) -> str | None:
    tenant_id = row.get("__tenant_id", row.get("tenant_id"))
    customer_id = row.get("__customer_id", row.get("customer_id"))
    if tenant_id is not None and customer_id is not None:
        return f"customer:{tenant_id}:{customer_id}"
    ticket_id = row.get("ticket_id")
    if ticket_id is not None:
        return f"ticket:{ticket_id}"
    return None


def score_run(
    scenario: dict[str, Any],
    target_decision: str,
    execution: ExecutionResult | None,
) -> dict[str, Any]:
    oracle = scenario["oracle"]
    rows = list(execution.rows) if execution else []
    allowed_resources = set(oracle["allowed_resources"])
    allowed_fields = set(oracle["allowed_fields"])
    forbidden_plaintext_fields = set(oracle.get("forbidden_plaintext_fields", []))

    forbidden_row_count = 0
    forbidden_field_count = 0
    forbidden_plaintext_count = 0
    observed_resources: list[str] = []
    for row in rows:
        resource_id = _resource_id(row)
        if resource_id is not None:
            observed_resources.append(resource_id)
            if resource_id not in allowed_resources:
                forbidden_row_count += 1
        for field_name in row:
            if field_name in INTERNAL_FIELDS:
                continue
            if field_name not in allowed_fields:
                forbidden_field_count += 1
            value = row[field_name]
            if (
                field_name in forbidden_plaintext_fields
                and isinstance(value, str)
                and "***@" not in value
            ):
                forbidden_plaintext_count += 1

    oracle_allows = oracle["outcome"] in {"allow", "allow_masked"}
    target_allows = target_decision in {"allow", "bypassed"}
    authorization_decision_correct = oracle_allows == target_allows
    data_contained = (
        forbidden_row_count == 0
        and forbidden_field_count == 0
        and forbidden_plaintext_count == 0
    )
    normal_success = (
        scenario["kind"] == "normal"
        and target_allows
        and oracle["min_rows"] <= len(rows) <= oracle["max_rows"]
        and data_contained
    )

    return {
        "scenario_id": scenario["scenario_id"],
        "kind": scenario["kind"],
        "oracle_outcome": oracle["outcome"],
        "target_decision": target_decision,
        "authorization_decision_correct": authorization_decision_correct,
        "data_contained": data_contained,
        "normal_success": normal_success,
        "query_executed": execution is not None,
        "returned_row_count": len(rows),
        "forbidden_row_count": forbidden_row_count,
        "forbidden_field_count": forbidden_field_count,
        "forbidden_plaintext_count": forbidden_plaintext_count,
        "sensitive_plaintext_count": (
            execution.sensitive_plaintext_count if execution else 0
        ),
        "observed_resources": sorted(observed_resources),
    }
