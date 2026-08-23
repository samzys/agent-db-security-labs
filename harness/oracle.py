"""Load and validate the independent, Git-tracked M1 truth manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MANIFEST_PATH = Path(__file__).with_name("scenarios") / "m1.json"


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("version") != "m1-oracle/0.1":
        raise ValueError("unsupported M1 oracle version")
    profiles = manifest.get("profiles")
    if profiles != ["P0", "P1", "P2", "P3"]:
        raise ValueError("M1 profiles must be exactly P0-P3")
    scenarios = manifest.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != 8:
        raise ValueError("M1 oracle must define exactly 8 scenarios")
    scenario_ids = [scenario.get("scenario_id") for scenario in scenarios]
    if len(set(scenario_ids)) != len(scenario_ids):
        raise ValueError("M1 scenario IDs must be unique")
    return manifest


MANIFEST = load_manifest()
SCENARIOS = {scenario["scenario_id"]: scenario for scenario in MANIFEST["scenarios"]}
