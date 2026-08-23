"""Assemble the frozen M2 P0-P3 oracle without mutating M1 fixtures."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from harness.oracle import MANIFEST as M1_MANIFEST


EXTENSION_PATH = Path(__file__).with_name("scenarios") / "m2_extension.json"


def _normalize_m1_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    scenario = deepcopy(raw)
    scenario["steps"] = [
        {
            "step_id": "primary-action",
            "action": scenario.pop("action"),
            "bypass_gateway": scenario.pop("bypass_gateway"),
            "oracle": scenario.pop("oracle"),
        }
    ]
    scenario["oracle"] = {"cumulative_unique_customer_budget": 1}
    context = scenario["context"]
    context.setdefault("lifecycle_state", "active")
    context.setdefault("delegated_ticket_ids", [context["ticket_id"]])
    for step in scenario["steps"]:
        oracle = step["oracle"]
        oracle.setdefault("allowed_egress_destinations", [])
        oracle.setdefault("forbidden_plaintext_fields", [])
        oracle.setdefault("expected_sink_writes", 0)
    return scenario


def _load() -> dict[str, Any]:
    extension = json.loads(EXTENSION_PATH.read_text(encoding="utf-8"))
    scenarios = [_normalize_m1_scenario(row) for row in M1_MANIFEST["scenarios"]]

    normal_one = next(row for row in scenarios if row["scenario_id"] == "N-01")
    normal_one["description"] = "Read assigned customer fields with default email masking."
    step = normal_one["steps"][0]
    step["action"]["arguments"]["fields"] = ["name", "plan", "email"]
    step["oracle"].update(
        {
            "outcome": "allow_masked",
            "allowed_fields": ["name", "plan", "email"],
            "forbidden_plaintext_fields": ["email"],
        }
    )

    scenarios.extend(deepcopy(extension["scenarios"]))
    return {
        "version": "m2-oracle/0.2",
        "profiles": deepcopy(M1_MANIFEST["profiles"]),
        "scenarios": scenarios,
    }


MANIFEST = _load()
SCENARIOS = {row["scenario_id"]: row for row in MANIFEST["scenarios"]}

if len(SCENARIOS) != len(MANIFEST["scenarios"]):
    raise ValueError("M2 scenario IDs must be unique")
