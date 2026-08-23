from __future__ import annotations

import json
import unittest
from pathlib import Path

from agent.openai_compatible import build_request, parse_tool_calls
from audit.events import EventChain, verify_records
from gateway.catalog import catalog_fingerprint, catalog_for_profile
from gateway.policy import PolicyGateway, ProposedAction, TrustedContext
from harness.oracle import SCENARIOS


class FixedCatalogTests(unittest.TestCase):
    def test_every_profile_has_identical_catalog(self):
        fingerprints = {catalog_fingerprint(f"P{index}") for index in range(6)}
        self.assertEqual(1, len(fingerprints))
        self.assertEqual(4, len(catalog_for_profile("P0")))

    def test_openai_compatible_request_keeps_same_tools(self):
        messages = [{"role": "user", "content": "summarize the ticket"}]
        p0 = build_request("P0", messages)
        p5 = build_request("P5", messages)
        self.assertEqual(p0["tools"], p5["tools"])
        self.assertEqual(0, p0["temperature"])

    def test_parse_tool_calls_contract(self):
        response = {
            "choices": [
                {"message": {"tool_calls": [{"id": "call_1", "type": "function"}]}}
            ]
        }
        self.assertEqual("call_1", parse_tool_calls(response)[0]["id"])


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.context = TrustedContext(
            user_id="user_alpha_t1",
            agent_id="agent_support",
            task_id="task_read_a102",
            ticket_id="ticket_a102",
            tenant_id="alpha",
            scopes=frozenset({"db:query", "db:read"}),
        )
        self.gateway = PolicyGateway()

    def test_p3_denies_free_sql_and_matches_oracle(self):
        action = ProposedAction("db_query_sql", {"sql": "SELECT * FROM customers"})
        decision = self.gateway.decide("P3", self.context, action)
        self.assertEqual(SCENARIOS["A-01"]["oracle"]["outcome"], decision.outcome)
        self.assertEqual("FREE_SQL_NOT_DELEGATED", decision.reason_code)

    def test_p3_rejects_resource_substitution(self):
        action = ProposedAction(
            "db_get_ticket_customer",
            {"ticket_id": "ticket_b201", "fields": ["name", "email"]},
        )
        decision = self.gateway.decide("P3", self.context, action)
        self.assertEqual("deny", decision.outcome)
        self.assertEqual("RESOURCE_NOT_DELEGATED", decision.reason_code)

    def test_p3_binds_matching_resource_to_trusted_context(self):
        action = ProposedAction(
            "db_get_ticket_customer",
            {"ticket_id": "ticket_a102", "fields": ["name", "email"]},
        )
        decision = self.gateway.decide("P3", self.context, action)
        self.assertEqual("allow", decision.outcome)
        self.assertEqual("ticket:ticket_a102", decision.effective_resource)

    def test_missing_tool_scope_denies_at_p2(self):
        context = TrustedContext(
            user_id="user_alpha_t1",
            agent_id="agent_support",
            task_id="task_read_a102",
            ticket_id="ticket_a102",
            tenant_id="alpha",
            scopes=frozenset(),
        )
        action = ProposedAction("db_query_sql", {"sql": "SELECT 1"})
        decision = self.gateway.decide("P2", context, action)
        self.assertEqual("deny", decision.outcome)
        self.assertEqual("TOOL_SCOPE_MISSING", decision.reason_code)


class AuditTests(unittest.TestCase):
    def test_hash_chain_detects_tampering(self):
        chain = EventChain("run-1", "A-01", "P3")
        chain.append("run_started", decision="not_evaluated")
        chain.append("task_authz_decision", decision="deny")
        ok, _ = verify_records(chain.records)
        self.assertTrue(ok)

        tampered = json.loads(json.dumps(chain.records))
        tampered[1]["decision"] = "allow"
        ok, reason = verify_records(tampered)
        self.assertFalse(ok)
        self.assertIn("event_hash", reason)

    def test_target_runtime_does_not_import_oracle(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for directory in ("gateway", "egress")
            for path in Path(directory).glob("*.py")
        )
        self.assertNotIn("harness.oracle", source)
        self.assertNotIn("from harness", source)


if __name__ == "__main__":
    unittest.main()
