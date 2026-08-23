"""CLI validator for a hash-linked M0 JSONL artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from audit.events import read_jsonl, verify_records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    ok, reason = verify_records(read_jsonl(args.artifact))
    if not ok:
        print(f"INVALID: {reason}")
        return 1
    print(f"VALID: {args.artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
