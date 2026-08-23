"""PostgreSQL-backed execution for the P0-P3 M1 forced-replay matrix."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gateway.policy import Decision, ProposedAction, TrustedContext


SUPPORTED_CUSTOMER_FIELDS = {
    "name": "customer.name",
    "email": "customer.email",
    "plan": "customer.plan",
    "lifetime_value": "customer.lifetime_value",
}


@dataclass(frozen=True)
class ExecutionResult:
    rows: tuple[dict[str, Any], ...]
    query_kind: str

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def sensitive_plaintext_count(self) -> int:
        count = 0
        for row in self.rows:
            email = row.get("email")
            if isinstance(email, str) and "***@" not in email:
                count += 1
            if row.get("lifetime_value") is not None:
                count += 1
        return count


class PostgresExecutor:
    def __init__(self, repo_root: Path | None = None):
        self.repo_root = repo_root or Path(__file__).resolve().parents[1]
        self.pg_bin = Path(
            os.environ.get("PG_BIN", "/opt/homebrew/opt/postgresql@17/bin")
        )
        runtime_dir = Path(
            os.environ.get(
                "M0_RUNTIME_DIR",
                str(self.repo_root / ".runtime" / "postgres"),
            )
        )
        self.socket_dir = runtime_dir / "socket"
        self.port = os.environ.get("M0_PGPORT", "55432")
        self.database = "agent_db_m0"

    def execute(
        self,
        profile_id: str,
        context: TrustedContext,
        action: ProposedAction,
        decision: Decision,
    ) -> ExecutionResult:
        if action.tool_name == "db_query_sql":
            return self._execute_free_sql(action)
        if action.tool_name == "db_get_ticket_customer":
            return self._execute_customer(profile_id, context, action, decision)
        if action.tool_name == "db_list_open_tickets":
            return self._execute_ticket_list(context, action)
        raise ValueError(f"M1 executor does not implement {action.tool_name}")

    def _execute_free_sql(self, action: ProposedAction) -> ExecutionResult:
        raw_sql = str(action.arguments.get("sql", "")).strip()
        if not raw_sql.lower().startswith("select "):
            raise ValueError("M1 free-SQL fixtures must be SELECT statements")
        if ";" in raw_sql:
            raise ValueError("M1 free-SQL fixtures must contain exactly one statement")
        wrapped = (
            "SELECT COALESCE(jsonb_agg(to_jsonb(result_row)), '[]'::jsonb) "
            f"FROM ({raw_sql}) AS result_row"
        )
        return ExecutionResult(tuple(self._run_json(wrapped)), "free_sql")

    def _execute_customer(
        self,
        profile_id: str,
        context: TrustedContext,
        action: ProposedAction,
        decision: Decision,
    ) -> ExecutionResult:
        requested_fields = action.arguments.get("fields")
        if not isinstance(requested_fields, list) or not requested_fields:
            raise ValueError("customer fields must be a non-empty list")
        if len(set(requested_fields)) != len(requested_fields):
            raise ValueError("customer fields must not contain duplicates")
        unknown = set(requested_fields) - set(SUPPORTED_CUSTOMER_FIELDS)
        if unknown:
            raise ValueError(f"unsupported customer fields: {sorted(unknown)}")

        if int(profile_id[1:]) >= 3:
            resource_prefix = "ticket:"
            if not (decision.effective_resource or "").startswith(resource_prefix):
                raise ValueError("P3 structured execution lacks a bound resource")
            ticket_id = decision.effective_resource[len(resource_prefix) :]
        else:
            ticket_id = str(action.arguments.get("ticket_id", ""))

        selected = ", ".join(
            f"{SUPPORTED_CUSTOMER_FIELDS[field_name]} AS {field_name}"
            for field_name in requested_fields
        )
        query = f"""
          SELECT COALESCE(jsonb_agg(to_jsonb(result_row)), '[]'::jsonb)
          FROM (
            SELECT
              customer.tenant_id AS __tenant_id,
              customer.customer_id AS __customer_id,
              {selected}
            FROM lab.tickets AS ticket
            JOIN lab.customers AS customer
              ON customer.tenant_id = ticket.tenant_id
             AND customer.customer_id = ticket.customer_id
            WHERE ticket.ticket_id = :'ticket_id'
          ) AS result_row
        """
        rows = self._run_json(query, {"ticket_id": ticket_id})
        return ExecutionResult(tuple(rows), "structured_customer")

    def _execute_ticket_list(
        self,
        context: TrustedContext,
        action: ProposedAction,
    ) -> ExecutionResult:
        limit = action.arguments.get("limit")
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("ticket-list limit must be between 1 and 500")
        query = """
          SELECT COALESCE(jsonb_agg(to_jsonb(result_row)), '[]'::jsonb)
          FROM (
            SELECT ticket_id, subject, status
            FROM lab.tickets
            WHERE tenant_id = :'tenant_id'
              AND assigned_user_id = :'user_id'
            ORDER BY ticket_id
            LIMIT :limit
          ) AS result_row
        """
        rows = self._run_json(
            query,
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "limit": str(limit),
            },
        )
        return ExecutionResult(tuple(rows), "structured_ticket_list")

    def _run_json(
        self,
        sql: str,
        variables: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        command = [
            str(self.pg_bin / "psql"),
            "-XAtq",
            "-h",
            str(self.socket_dir),
            "-p",
            self.port,
            "-U",
            "app_broad_reader",
            "-d",
            self.database,
            "-v",
            "ON_ERROR_STOP=1",
        ]
        for name, value in sorted((variables or {}).items()):
            command.extend(["-v", f"{name}={value}"])
        # psql intentionally does not perform variable interpolation in text
        # passed with -c. Feed the statement over stdin so :'name' remains a
        # psql-escaped literal rather than becoming invalid SQL.
        completed = subprocess.run(
            command,
            input=sql,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = completed.stdout.strip() or "[]"
        decoded = json.loads(payload)
        if not isinstance(decoded, list):
            raise ValueError("PostgreSQL executor expected a JSON array")
        return decoded
