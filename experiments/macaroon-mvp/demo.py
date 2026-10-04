#!/usr/bin/env python3
"""A local Macaroon teaching experiment, not an HTTP service or identity system."""

import argparse
import hashlib
import json
import platform
import secrets
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from pymacaroons import Macaroon, Verifier
from pymacaroons.exceptions import MacaroonException


def issue(root_key, *, read_only=False):
    """The issuer sets resource/action limits BEFORE handing the parent out."""
    token = Macaroon(
        location="local-ticket-demo", identifier="demo-grant-101", key=root_key
    )
    token.add_first_party_caveat("ticket = 101")
    if read_only:
        token.add_first_party_caveat("operation = read")
    return token.serialize()


def attenuate(serialized, caveat):
    """Holder-side operation: receives only a token and a new restriction."""
    token = Macaroon.deserialize(serialized)
    token.add_first_party_caveat(caveat)
    return token.serialize()


def access(serialized, root_key, ticket, operation, store):
    """The resource checks the actual requested action before touching data."""
    if operation not in {"read", "write"} or ticket not in store:
        return {"decision": "DENY", "reason": "BAD_REQUEST", "data": None}
    try:
        token = Macaroon.deserialize(serialized)
        if token.identifier != "demo-grant-101":
            return {"decision": "DENY", "reason": "UNKNOWN_GRANT", "data": None}
        verifier = Verifier()
        # These are facts about THIS request, not a list of every permitted action.
        verifier.satisfy_exact(f"ticket = {ticket}")
        verifier.satisfy_exact(f"operation = {operation}")
        verifier.verify(token, root_key)
    except MacaroonException:
        # The library can use the same exception for tampering and unmet caveats.
        return {"decision": "DENY", "reason": "VERIFICATION_FAILED", "data": None}
    if operation == "write":
        store[ticket] = "closed"
    return {
        "decision": "ALLOW",
        "reason": "VERIFIED",
        "data": {"id": ticket, "status": store[ticket]},
    }


def run():
    # Ephemeral synthetic key: no environment credentials or saved secrets.
    root_key = secrets.token_bytes(32)
    parent = issue(root_key)
    child = attenuate(parent, "operation = read")
    contradictory = attenuate(child, "operation = write")

    # Simulate a child-only holder removing the last caveat without the root key.
    tampered = Macaroon.deserialize(child)
    tampered.caveats.pop()
    tampered = tampered.serialize()  # Retains the child's now-invalid signature.

    # Separate scenario: the issuer hands this Agent a read-only parent.
    # The Agent's attenuation function never receives the root key.
    read_only_parent = issue(root_key, read_only=True)
    read_only_child = attenuate(read_only_parent, "operation = read")
    attempted_write_child = attenuate(read_only_parent, "operation = write")

    cases = [
        ("C01", "父凭据写入 101", parent, "parent", "agent-a", "101", "write", "ALLOW"),
        ("C02", "子凭据读取 101", child, "child", "worker-b", "101", "read", "ALLOW"),
        ("C03", "子凭据尝试写入", child, "child", "worker-b", "101", "write", "DENY"),
        ("C04", "子凭据改读 102", child, "child", "worker-b", "102", "read", "DENY"),
        ("C05", "追加 write 想覆盖 read", contradictory, "contradictory", "worker-b", "101", "write", "DENY"),
        ("C06", "删掉 read 限制后写入", tampered, "tampered", "worker-b", "101", "write", "DENY"),
        ("C07", "保留父凭据仍可写入", parent, "parent", "agent-a", "101", "write", "ALLOW"),
        ("C08", "他人拿到相同子凭据读取", child, "child-copy", "holder-x", "101", "read", "ALLOW"),
        ("C09", "最初只读的父凭据：读", read_only_parent, "read-only-parent", "readonly-agent", "101", "read", "ALLOW"),
        ("C10", "最初只读的父凭据：写", read_only_parent, "read-only-parent", "readonly-agent", "101", "write", "DENY"),
        ("C11", "正常只读子凭据：读", read_only_child, "read-only-child", "readonly-worker", "101", "read", "ALLOW"),
        ("C12", "正常只读子凭据：写", read_only_child, "read-only-child", "readonly-worker", "101", "write", "DENY"),
        ("C13", "父只读却给子追加 write：读", attempted_write_child, "attempted-write-child", "readonly-worker", "101", "read", "DENY"),
        ("C14", "父只读却给子追加 write：写", attempted_write_child, "attempted-write-child", "readonly-worker", "101", "write", "DENY"),
    ]
    results = []
    for case_id, label, token, variant, holder, ticket, operation, expected in cases:
        before = {"101": "open", "102": "open"}
        store = dict(before)  # Every case starts from an independent fixture.
        actual = access(token, root_key, ticket, operation, store)
        expected_store = dict(before)
        expected_data = None
        if expected == "ALLOW":
            if operation == "write":
                expected_store[ticket] = "closed"
            expected_data = {"id": ticket, "status": expected_store[ticket]}
        matched = (
            actual["decision"] == expected
            and actual["data"] == expected_data
            and store == expected_store
        )
        results.append({
            "case_id": case_id,
            "description": label,
            "token_variant": variant,
            "holder_label_not_authenticated": holder,
            "request": {"ticket": ticket, "operation": operation},
            "expected": {"decision": expected, "data": expected_data, "state_after": expected_store},
            "actual": actual,
            "state_before": before,
            "state_after": store,
            "matches_prediction": matched,
        })
    # Derive permission sets from OBSERVED decisions, not the expected table.
    groups = {
        "parent": {"C09", "C10"},
        "normal_child": {"C11", "C12"},
        "attempted_write_child": {"C13", "C14"},
    }
    allowed = {
        name: {r["request"]["operation"] for r in results
               if r["case_id"] in ids and r["actual"]["decision"] == "ALLOW"}
        for name, ids in groups.items()
    }
    subset = all(allowed[name] <= allowed["parent"]
                 for name in ("normal_child", "attempted_write_child"))
    return {
        "contract": "macaroon-learning-mvp-v1.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "dependencies": {name: version(name) for name in ("pymacaroons", "PyNaCl", "cffi", "pycparser", "six")},
        "scope": "single-process, first-party caveats, synthetic data; no identity proof",
        "parent_caveats": ["ticket = 101"],
        "child_caveats": ["ticket = 101", "operation = read"],
        "read_only_parent_delegation": {
            "tested_domain": {"ticket": "101", "operations": ["read", "write"]},
            "parent_issued_read_only": True,
            "parent_caveats": ["ticket = 101", "operation = read"],
            "normal_child_caveats": ["ticket = 101", "operation = read", "operation = read"],
            "attempted_write_child_caveats": ["ticket = 101", "operation = read", "operation = write"],
            "observed_allowed_operations": {name: sorted(ops) for name, ops in allowed.items()},
            "both_children_are_subsets_in_tested_domain": subset,
        },
        "cases": results,
        "summary": {"total": len(results), "matched": sum(r["matches_prediction"] for r in results)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON evidence file; excludes keys/tokens")
    args = parser.parse_args()
    report = run()
    print("Macaroon MVP: 真正的 MAC 验证 + 每条限制均须满足\n")
    print("父凭据: ticket = 101")
    print("子凭据: ticket = 101 AND operation = read\n")
    for result in report["cases"]:
        verdict = "符合预期" if result["matches_prediction"] else "不符合预期"
        print(f"{result['case_id']}  {result['actual']['decision']:5}  {result['description']}  [{verdict}]")
    total, matched = report["summary"]["total"], report["summary"]["matched"]
    print(f"\n机制观察: {matched}/{total} 符合预期（不等于生产安全认证）。")
    print("C07: 子凭据变窄，不会撤销原来的父凭据。")
    print("C08: bearer credential 被复制后仍可用；这里没有认证持有人身份。")
    delegation = report["read_only_parent_delegation"]
    print("C09-C14: 父 Agent 从签发时就只有只读权限。")
    for name, operations in delegation["observed_allowed_operations"].items():
        print(f"  {name}: {operations}")
    subset = delegation["both_children_are_subsets_in_tested_domain"]
    print(f"  工单 101 的 read/write 测试域内，子权限均为父权限子集: {subset}")
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"证据已保存: {args.output}")
    return 0 if matched == total and subset else 1


if __name__ == "__main__":
    raise SystemExit(main())
