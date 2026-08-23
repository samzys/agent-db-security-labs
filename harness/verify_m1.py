"""Mechanical acceptance checks for the M1 report and run artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit.events import read_jsonl, verify_records
from harness.oracle import MANIFEST


EXPECTED_METRICS = {
    "P0": (3, 0, 0, 5),
    "P1": (3, 0, 0, 5),
    "P2": (3, 0, 0, 5),
    "P3": (3, 4, 4, 1),
}


def verify(report_path: Path) -> list[str]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if report.get("run_count") != 32:
        errors.append(f"expected 32 runs, got {report.get('run_count')}")
    if report.get("scenario_count") != 8:
        errors.append("expected 8 scenarios")
    if report.get("oracle_version") != MANIFEST["version"]:
        errors.append("report oracle version differs from Git-tracked manifest")

    metrics = report.get("profile_metrics", {})
    for profile_id, expected in EXPECTED_METRICS.items():
        row = metrics.get(profile_id, {})
        actual = (
            row.get("normal_success_count"),
            row.get("attack_authorization_correct_count"),
            row.get("attack_data_contained_count"),
            row.get("unauthorized_execution_count"),
        )
        if actual != expected:
            errors.append(f"{profile_id} metrics {actual} != {expected}")

    results = report.get("results", [])
    expected_pairs = {
        (scenario["scenario_id"], profile_id)
        for scenario in MANIFEST["scenarios"]
        for profile_id in MANIFEST["profiles"]
    }
    actual_pairs = [
        (row.get("scenario_id"), row.get("profile_id")) for row in results
    ]
    if len(actual_pairs) != len(set(actual_pairs)):
        errors.append("report contains duplicate scenario/profile results")
    if set(actual_pairs) != expected_pairs:
        missing = sorted(expected_pairs - set(actual_pairs))
        unexpected = sorted(set(actual_pairs) - expected_pairs)
        errors.append(f"run matrix mismatch: missing={missing}, unexpected={unexpected}")

    scenarios = {
        scenario["scenario_id"]: scenario for scenario in MANIFEST["scenarios"]
    }
    for row in results:
        scenario = scenarios.get(row.get("scenario_id"))
        if scenario is None:
            continue
        if row.get("kind") != scenario["kind"]:
            errors.append(f"{row.get('scenario_id')} kind differs from oracle")
        if row.get("oracle_outcome") != scenario["oracle"]["outcome"]:
            errors.append(f"{row.get('scenario_id')} outcome differs from oracle")

    for profile_id, expected in EXPECTED_METRICS.items():
        profile_results = [
            row for row in results if row.get("profile_id") == profile_id
        ]
        normal = [row for row in profile_results if row.get("kind") == "normal"]
        attacks = [row for row in profile_results if row.get("kind") == "attack"]
        recomputed = (
            sum(bool(row.get("normal_success")) for row in normal),
            sum(bool(row.get("authorization_decision_correct")) for row in attacks),
            sum(bool(row.get("data_contained")) for row in attacks),
            sum(
                bool(row.get("query_executed"))
                and row.get("oracle_outcome") == "deny"
                for row in attacks
            ),
        )
        if recomputed != expected:
            errors.append(
                f"{profile_id} recomputed result metrics {recomputed} != {expected}"
            )

    positive = next(
        (
            row
            for row in results
            if row["scenario_id"] == "A-01" and row["profile_id"] == "P0"
        ),
        None,
    )
    if not positive or positive["forbidden_row_count"] < 1:
        errors.append("P0/A-01 positive control did not expose forbidden rows")

    p3_block = next(
        (
            row
            for row in results
            if row["scenario_id"] == "A-01" and row["profile_id"] == "P3"
        ),
        None,
    )
    if not p3_block or not p3_block["data_contained"] or p3_block["query_executed"]:
        errors.append("P3/A-01 did not contain the free-SQL attack")

    p3_bypass = next(
        (
            row
            for row in results
            if row["scenario_id"] == "A-05" and row["profile_id"] == "P3"
        ),
        None,
    )
    if not p3_bypass or p3_bypass["data_contained"]:
        errors.append("P3/A-05 did not preserve the gateway-bypass counterexample")

    for row in results:
        artifact = Path(row["artifact"])
        if not artifact.exists():
            errors.append(f"missing artifact {artifact}")
            continue
        records = read_jsonl(artifact)
        valid, reason = verify_records(records)
        if not valid:
            errors.append(f"invalid artifact {artifact}: {reason}")
            continue
        if any(record.get("producer") != "harness_observer" for record in records):
            errors.append(f"unexpected producer in {artifact}")
        if any(
            record.get("scenario_id") != row["scenario_id"]
            or record.get("profile_id") != row["profile_id"]
            for record in records
        ):
            errors.append(f"artifact identity differs from report: {artifact}")
        event_types = {record["event_type"] for record in records}
        if ("db_query_executed" in event_types) != row["query_executed"]:
            errors.append(f"execution fact differs from report: {artifact}")
        finished = records[-1]
        if finished.get("event_type") != "run_finished":
            errors.append(f"artifact does not end with run_finished: {artifact}")
        elif (
            finished.get("authorization_decision_correct")
            != row["authorization_decision_correct"]
            or finished.get("data_contained") != row["data_contained"]
        ):
            errors.append(f"final score differs from report: {artifact}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    errors = verify(args.report)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"VALID: {args.report} (32 runs, expected P0-P3 separation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
