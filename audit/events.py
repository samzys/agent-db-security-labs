"""Small hash-linked JSONL event chain used by the M0 feasibility spike."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "agent-db-evidence/0.1"


def _canonical(record: dict[str, Any]) -> bytes:
    material = {key: value for key, value in record.items() if key != "event_hash"}
    return json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(record: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(record)).hexdigest()


@dataclass
class EventChain:
    run_id: str
    scenario_id: str
    profile_id: str
    records: list[dict[str, Any]] = field(default_factory=list)

    def append(self, event_type: str, **payload: Any) -> dict[str, Any]:
        parent = self.records[-1]["event_id"] if self.records else None
        previous_hash = self.records[-1]["event_hash"] if self.records else None
        event_index = len(self.records) + 1
        record = {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"{self.run_id}:evt:{event_index:03d}",
            "parent_event_id": parent,
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "profile_id": self.profile_id,
            "event_type": event_type,
            "occurred_at": "2026-07-25T00:00:00Z",
            "prev_event_hash": previous_hash,
            **payload,
        }
        record["event_hash"] = _hash(record)
        self.records.append(record)
        return record

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in self.records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")


def verify_records(records: list[dict[str, Any]]) -> tuple[bool, str]:
    previous_hash = None
    previous_event_id = None
    for index, record in enumerate(records, start=1):
        if record.get("prev_event_hash") != previous_hash:
            return False, f"event {index} has invalid prev_event_hash"
        if record.get("parent_event_id") != previous_event_id:
            return False, f"event {index} has invalid parent_event_id"
        if record.get("event_hash") != _hash(record):
            return False, f"event {index} has invalid event_hash"
        previous_hash = record["event_hash"]
        previous_event_id = record["event_id"]
    return True, "ok"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
