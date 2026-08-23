"""A fixed tool catalog shared by every experimental profile."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy


TOOL_CATALOG = (
    {
        "name": "db_query_sql",
        "description": "Propose a read-only SQL query.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
    {
        "name": "db_get_ticket_customer",
        "description": "Read the customer bound to the current support task.",
        "parameters": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["ticket_id", "fields"],
            "additionalProperties": False,
        },
    },
    {
        "name": "db_list_open_tickets",
        "description": "List open tickets in the current task scope.",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 5}},
            "required": ["limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "egress_send",
        "description": "Write a payload reference to the synthetic egress sink.",
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {"type": "string"},
                "payload_ref": {"type": "string"},
            },
            "required": ["destination", "payload_ref"],
            "additionalProperties": False,
        },
    },
)


def catalog_for_profile(profile_id: str) -> list[dict]:
    if profile_id not in {f"P{index}" for index in range(6)}:
        raise ValueError(f"unknown profile: {profile_id}")
    return deepcopy(list(TOOL_CATALOG))


def catalog_fingerprint(profile_id: str) -> str:
    encoded = json.dumps(
        catalog_for_profile(profile_id),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
