# M0 PostgreSQL feasibility spike

Date: 2026-07-25
Branch: `feat/postgres-m0`
Status: **core PASS; real-model execution pending**

## What was tested

- Repository-local PostgreSQL 17.10 cluster, not a Homebrew background service.
- Runtime roles are non-owner, non-superuser, and have no `BYPASSRLS`.
- `FORCE ROW LEVEL SECURITY` behavior for a broad positive-control role and
  task-bound roles.
- Transaction-local custom settings and connection/session reset behavior.
- A server-owned, no-argument capability that derives the customer from the
  task login role and masks email.
- One fixed four-tool catalog across profiles P0-P5.
- An OpenAI-compatible request/response contract using that fixed catalog.
- An independent oracle and a hash-linked synthetic JSONL deny chain.

## Main finding

`SET LOCAL` correctly clears custom settings at transaction end, but a caller
that can submit SQL can change those same settings inside the transaction. The
negative control changed the RLS scope from the alpha customer to the beta
customer and successfully returned the beta row.

Therefore an Agent-controlled SQL path must not treat model-settable custom
PostgreSQL settings as authenticated identity or authority.

The alternative M0 path connected as a task-bound login role. Its RLS policy
derived scope from `session_user` through an owner-controlled mapping. Changing
the custom settings did not change the visible row, and an attempted `SET ROLE`
to a different task role failed. The server-owned capability returned only the
bound row with a masked email.

This is a feasibility result, not yet a production credential design. A full
implementation still needs credential lifecycle, pool partitioning, concurrency
tests, revocation, and operational scaling analysis.

## Mechanical evidence

Run:

```bash
make m0-test
```

Observed checks:

- broad-reader positive control: 3 rows;
- `SET LOCAL` reset: 1 row in transaction, 0 after commit;
- GUC-tamper negative control: alpha row, then beta row;
- task-role scope: alpha row only after the same GUC tamper;
- cross-task `SET ROLE`: rejected;
- server-owned capability: `Alpha Fixture|a***@example.com|pro`;
- second task role: beta row only;
- Python unit tests: 8 passed;
- generated artifact: `artifacts/m0/a01-p3.jsonl`;
- artifact validation: passed, including a separate tamper-detection unit test.

## Runtime and safety boundary

- PostgreSQL listens only on the repository-local Unix socket.
- The cluster uses trust authentication because it is a disposable, local-only
  spike. It must not be reused as a network service or production pattern.
- `.runtime/`, artifacts, caches, and generated `demo.db` are ignored.
- The original SQLite demo remains available as the vulnerable positive control.

## Not verified

- No real local model was installed or invoked. Only the tool-call contract was
  tested with a fixture response.
- No connection pool or concurrent task switching was tested.
- The full 84 forced runs and 180 model runs were not started.
- P5 masking budgets, egress, revocation, and full causal audit are not built.
- No public push, release, or article result was produced.

## Decision

M0 core passes. Replace the Spec's GUC-only authorization assumption with an
unforgeable task-bound database principal or an equivalent database-verifiable
credential. M1 may build the independent oracle and P0-P3 forced-replay harness.
The real-model lane remains a separate prerequisite before article publication.
