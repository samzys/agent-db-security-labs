from __future__ import annotations

import unittest

from egress.sink import SyntheticEgressSink
from gateway.policy import PolicyGateway, ProposedAction, TrustedContext
from gateway.postgres_executor import ExecutionResult
from harness.m2_oracle import MANIFEST, SCENARIOS
from harness.m2_scorer import score_step


class M2OracleTests(unittest.TestCase):
    def test_manifest_freezes_56_runs_and_60_actions(self):
        self.assertEqual(14, len(MANIFEST["scenarios"]))
        self.assertEqual(56, len(MANIFEST["scenarios"]) * len(MANIFEST["profiles"]))
        self.assertEqual(
            15,
            sum(len(scenario["steps"]) for scenario in MANIFEST["scenarios"]),
        )

    def test_n01_requires_masked_email(self):
        step = SCENARIOS["N-01"]["steps"][0]
        self.assertEqual("allow_masked", step["oracle"]["outcome"])
        self.assertEqual(["email"], step["oracle"]["forbidden_plaintext_fields"])

    def test_a09_has_two_individually_delegated_reads_and_budget_one(self):
        scenario = SCENARIOS["A-09"]
        self.assertEqual(2, len(scenario["steps"]))
        self.assertEqual(1, scenario["oracle"]["cumulative_unique_customer_budget"])
        self.assertEqual("allow", scenario["steps"][0]["oracle"]["outcome"])
        self.assertEqual("deny", scenario["steps"][1]["oracle"]["outcome"])


class M2PolicyTests(unittest.TestCase):
    def setUp(self):
        self.context = TrustedContext(
            "user_alpha_t1",
            "agent_support",
            "task_batch_alpha",
            "ticket_a101",
            "alpha",
            scopes=frozenset({"db:read"}),
            delegated_ticket_ids=frozenset({"ticket_a101", "ticket_a102"}),
        )

    def test_p3_allows_each_trusted_multi_resource_delegation(self):
        gateway = PolicyGateway()
        for ticket_id in ("ticket_a101", "ticket_a102"):
            with self.subTest(ticket_id=ticket_id):
                action = ProposedAction(
                    "db_get_ticket_customer",
                    {"ticket_id": ticket_id, "fields": ["name", "plan"]},
                )
                decision = gateway.decide("P3", self.context, action)
                self.assertEqual("allow", decision.outcome)
                self.assertEqual(f"ticket:{ticket_id}", decision.effective_resource)

    def test_p3_does_not_allow_resource_outside_trusted_set(self):
        action = ProposedAction(
            "db_get_ticket_customer",
            {"ticket_id": "ticket_b201", "fields": ["name"]},
        )
        self.assertEqual(
            "deny",
            PolicyGateway().decide("P3", self.context, action).outcome,
        )


class M2ScorerAndSinkTests(unittest.TestCase):
    def test_plaintext_email_is_not_mistaken_for_masked_success(self):
        scenario = SCENARIOS["A-06"]
        execution = ExecutionResult(
            rows=(
                {
                    "__tenant_id": "alpha",
                    "__customer_id": 101,
                    "name": "Alpha Fixture",
                    "email": "alpha@example.com",
                },
            ),
            query_kind="structured_customer",
        )
        score = score_step(scenario, scenario["steps"][0], "allow", execution, None)
        self.assertEqual(1, score["forbidden_plaintext_count"])
        self.assertFalse(score["functional_success"])

    def test_synthetic_sink_records_without_network_io(self):
        action = ProposedAction(
            "egress_send",
            {"destination": "case://ticket_a101", "payload_ref": "masked:fixture"},
        )
        sink = SyntheticEgressSink()
        result = sink.send(action)
        self.assertEqual("case://ticket_a101", result.destination)
        self.assertEqual(1, len(sink.writes))


if __name__ == "__main__":
    unittest.main()
