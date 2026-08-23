"""Minimal M0 policy decisions. This is not the complete P0-P5 implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gateway.catalog import catalog_for_profile


@dataclass(frozen=True)
class TrustedContext:
    user_id: str
    agent_id: str
    task_id: str
    ticket_id: str
    tenant_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    allow_email_plaintext: bool = False
    lifecycle_state: str = "active"
    delegated_ticket_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ProposedAction:
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason_code: str
    effective_resource: str | None = None


TOOL_SCOPES = {
    "db_query_sql": "db:query",
    "db_get_ticket_customer": "db:read",
    "db_list_open_tickets": "db:read",
    "egress_send": "egress:send",
}


class PolicyGateway:
    def decide(
        self,
        profile_id: str,
        context: TrustedContext,
        action: ProposedAction,
    ) -> Decision:
        catalog_names = {tool["name"] for tool in catalog_for_profile(profile_id)}
        if action.tool_name not in catalog_names:
            return Decision("deny", "UNKNOWN_TOOL")

        profile_number = int(profile_id[1:])
        if profile_number >= 2:
            required_scope = TOOL_SCOPES[action.tool_name]
            if required_scope not in context.scopes:
                return Decision("deny", "TOOL_SCOPE_MISSING")

        if profile_number >= 3 and action.tool_name == "db_query_sql":
            return Decision("deny", "FREE_SQL_NOT_DELEGATED")

        if profile_number >= 3 and action.tool_name == "db_get_ticket_customer":
            requested_ticket_id = action.arguments.get("ticket_id")
            delegated_ticket_ids = context.delegated_ticket_ids or frozenset(
                {context.ticket_id}
            )
            if requested_ticket_id not in delegated_ticket_ids:
                return Decision("deny", "RESOURCE_NOT_DELEGATED")
            requested_fields = set(action.arguments.get("fields", []))
            if not requested_fields <= {"name", "plan", "email"}:
                return Decision("deny", "FIELD_NOT_DELEGATED")
            return Decision(
                "allow",
                "TASK_CAPABILITY_BOUND",
                effective_resource=f"ticket:{requested_ticket_id}",
            )

        if profile_number >= 3 and action.tool_name == "db_list_open_tickets":
            limit = action.arguments.get("limit")
            if not isinstance(limit, int) or not 1 <= limit <= 5:
                return Decision("deny", "RESULT_LIMIT_EXCEEDED")
            return Decision(
                "allow",
                "TASK_CAPABILITY_BOUND",
                effective_resource=f"user:{context.user_id}",
            )

        return Decision("allow", "PROFILE_ALLOWS_TOOL")
