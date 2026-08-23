"""Independently verify the M2 report surface and 56 evidence chains."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from audit.events import read_jsonl, verify_records
from harness.m2_oracle import MANIFEST


EXPECTED_PROFILE_SHAPE = {
    "P0": (3, 1, 1, 0, 9, 8, 2, 1, 1, 1, 0, 14),
    "P1": (3, 1, 1, 0, 9, 8, 2, 1, 1, 1, 0, 14),
    "P2": (3, 1, 1, 0, 9, 8, 2, 1, 1, 1, 0, 14),
    "P3": (3, 1, 6, 4, 4, 3, 2, 1, 1, 1, 0, 14),
}


def _profile_shape(metrics: dict[str, Any]) -> tuple[int, ...]:
    return (
        metrics["normal"]["success_count"],
        metrics["normal"]["false_mask_count"],
        metrics["authorization"]["correct_attack_scenario_count"],
        metrics["authorization"]["contained_attack_scenario_count"],
        metrics["authorization"]["unauthorized_implementation_count"],
        metrics["query"]["unauthorized_execution_count"],
        metrics["data_context"]["forbidden_plaintext_count"],
        metrics["egress"]["forbidden_success_count"],
        metrics["lifecycle"]["revocation_failure_count"],
        metrics["lifecycle"]["cumulative_violation_count"],
        metrics["audit"]["target_event_observed_count"],
        metrics["audit"]["valid_evidence_chain_count"],
    )


def _result_index(results: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (row.get("scenario_id"), row.get("profile_id")): row for row in results
    }


def _verify_checksums(artifact_dir: Path) -> list[str]:
    errors: list[str] = []
    checksum_path = artifact_dir / "checksums.txt"
    if not checksum_path.exists():
        return ["missing checksums.txt"]
    listed: set[str] = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64:
            errors.append(f"invalid checksum line: {line}")
            continue
        listed.add(relative)
        path = artifact_dir / relative
        if not path.is_file():
            errors.append(f"checksum references missing file: {relative}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            errors.append(f"checksum mismatch: {relative}")
    expected = {
        str(path.relative_to(artifact_dir))
        for path in artifact_dir.rglob("*")
        if path.is_file() and path.name != "checksums.txt"
    }
    if listed != expected:
        errors.append(
            f"checksum coverage mismatch: missing={sorted(expected - listed)}, "
            f"unexpected={sorted(listed - expected)}"
        )
    return errors


def verify(report_path: Path) -> list[str]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if report.get("schema_version") != "agent-db-report/0.2":
        errors.append("unexpected report schema")
    if report.get("oracle_version") != MANIFEST["version"]:
        errors.append("report oracle version differs from Git-tracked oracle")
    if report.get("run_count") != 56:
        errors.append(f"expected 56 runs, got {report.get('run_count')}")
    if report.get("action_attempt_count") != 60:
        errors.append("expected 60 action attempts")
    if report.get("scenario_count") != 14:
        errors.append("expected 14 scenarios")

    expected_pairs = {
        (scenario["scenario_id"], profile_id)
        for scenario in MANIFEST["scenarios"]
        for profile_id in MANIFEST["profiles"]
    }
    results = report.get("results", [])
    actual_pairs = [
        (row.get("scenario_id"), row.get("profile_id")) for row in results
    ]
    if len(actual_pairs) != len(set(actual_pairs)):
        errors.append("report contains duplicate scenario/profile results")
    if set(actual_pairs) != expected_pairs:
        errors.append(
            f"run matrix mismatch: missing={sorted(expected_pairs - set(actual_pairs))}, "
            f"unexpected={sorted(set(actual_pairs) - expected_pairs)}"
        )

    profiles = report.get("profile_metrics", {})
    for profile_id, expected in EXPECTED_PROFILE_SHAPE.items():
        metrics = profiles.get(profile_id)
        if metrics is None:
            errors.append(f"missing metrics for {profile_id}")
            continue
        actual = _profile_shape(metrics)
        if actual != expected:
            errors.append(f"{profile_id} profile shape {actual} != {expected}")
        if metrics.get("run_count") != 14 or metrics.get("action_attempt_count") != 15:
            errors.append(f"{profile_id} denominator mismatch")

    indexed = _result_index(results)
    for profile_id in MANIFEST["profiles"]:
        normal = indexed.get(("N-01", profile_id), {})
        if (
            normal.get("normal_success")
            or normal.get("steps", [{}])[0].get("forbidden_plaintext_count") != 1
        ):
            errors.append(f"{profile_id}/N-01 did not preserve the false-mask control")
        cumulative = indexed.get(("A-09", profile_id), {})
        if (
            cumulative.get("step_count") != 2
            or cumulative.get("unique_customer_resource_count") != 2
            or not cumulative.get("cumulative_violation")
        ):
            errors.append(f"{profile_id}/A-09 did not exceed the cumulative budget")
        audit = indexed.get(("A-10", profile_id), {})
        if (
            audit.get("audit_required_event_count") != 7
            or audit.get("audit_observed_target_event_count") != 0
            or audit.get("attack_contained")
        ):
            errors.append(f"{profile_id}/A-10 did not preserve the target audit gap")

    scenarios = {row["scenario_id"]: row for row in MANIFEST["scenarios"]}
    for row in results:
        scenario = scenarios.get(row.get("scenario_id"))
        if scenario is None:
            continue
        if row.get("kind") != scenario["kind"]:
            errors.append(f"{row.get('scenario_id')} kind differs from oracle")
        expected_step_ids = [step["step_id"] for step in scenario["steps"]]
        actual_step_ids = [step.get("step_id") for step in row.get("steps", [])]
        if actual_step_ids != expected_step_ids:
            errors.append(
                f"{row.get('scenario_id')}/{row.get('profile_id')} step sequence differs"
            )

        artifact = Path(row.get("artifact", ""))
        if not artifact.is_file():
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
        finished = records[-1]
        if finished.get("event_type") != "run_finished":
            errors.append(f"artifact does not end with run_finished: {artifact}")
        elif (
            finished.get("authorization_correct") != row["authorization_correct"]
            or finished.get("attack_contained") != row["attack_contained"]
            or finished.get("normal_success") != row["normal_success"]
        ):
            errors.append(f"final result differs from report: {artifact}")

    artifact_dir = report_path.parent
    errors.extend(_verify_checksums(artifact_dir))
    manifest_path = artifact_dir / "experiment-manifest.json"
    if not manifest_path.is_file():
        errors.append("missing experiment-manifest.json")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("oracle_version") != MANIFEST["version"]:
            errors.append("experiment manifest oracle version mismatch")
        fingerprints = set(manifest.get("catalog_fingerprints", {}).values())
        if len(fingerprints) != 1:
            errors.append("tool catalog differs across profiles")
    for required in ("report.md", "limitations.md"):
        if not (artifact_dir / required).is_file():
            errors.append(f"missing {required}")
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
    print(f"VALID: {args.report} (56 runs, 60 actions, stable M2 contract)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
