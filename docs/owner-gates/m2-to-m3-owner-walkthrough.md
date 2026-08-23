# M2 to M3 owner walkthrough

Status: **required owner gate; M3 remains locked**

Interactive Chinese teaching page:
[`m2-to-m3-owner-walkthrough.html`](m2-to-m3-owner-walkthrough.html).
It visualizes A-01/P0, A-01/P3, and A-05/P3, stores personal notes locally in
the browser, and can generate a draft completion record. The Markdown file
remains the canonical gate; the HTML cannot execute tests or authorize M3.

This walkthrough is the hands-on ownership check after M2 PASS. Its purpose is
to make sure the repository owner can explain and modify the evidence chain
before P4 database enforcement begins. An agent may prepare this guide, but must not complete the
gate, answer it on the repository owner's behalf, or infer M3 authorization.

Expected time: 60-90 minutes.

## 1. Establish the baseline

From the repository root:

```bash
git status --short --branch
make m1-test
make m2-test
```

Expected baseline:

- M1: 32 runs validate.
- M2: 56 runs and 60 action attempts validate.
- `docs/experiments/2026-07-25-m2-p0-p3-baseline.md` remains the governing
  experiment record.
- No M3/P4 implementation appears in the diff.

If a test fails or the source tree has unexplained changes, stop the walkthrough
and resolve that state first.

## 2. Trace one attack end to end

Use A-01, the indirect-injection bulk customer export:

1. Fixture and oracle input:
   `harness/scenarios/m1.json`, scenario `A-01`.
2. M2 oracle assembly:
   `harness/m2_oracle.py`.
3. Target policy and execution:
   `gateway/policy.py` and `gateway/postgres_executor.py`.
4. Independent scoring:
   `harness/m2_scorer.py`.
5. Aggregate report:
   `artifacts/m2/report.json`.
6. Hash-linked evidence:
   `artifacts/m2/runs/a-01-p0.jsonl` and
   `artifacts/m2/runs/a-01-p3.jsonl`.

Compare P0 and P3:

```bash
jq '.results[] |
  select(.scenario_id=="A-01" and
    (.profile_id=="P0" or .profile_id=="P3")) |
  {scenario_id,profile_id,authorization_correct,attack_contained,artifact,steps}' \
  artifacts/m2/report.json
```

Then inspect the evidence chain:

```bash
jq -c '{event_id,event_type,decision,reason_code,control_stage,
  result_row_count,forbidden_row_count,sensitive_plaintext_count,
  prev_event_hash,event_hash}' artifacts/m2/runs/a-01-p0.jsonl

jq -c '{event_id,event_type,decision,reason_code,control_stage,
  result_row_count,forbidden_row_count,sensitive_plaintext_count,
  prev_event_hash,event_hash}' artifacts/m2/runs/a-01-p3.jsonl
```

The repository owner must be able to point to the exact source line where P3 denies free SQL,
show the report field proving no query executed, and show how the JSONL chain
links that target decision to the observed result.

Use this command to locate the target decision without relying on a remembered
line number:

```bash
grep -n -C 4 'FREE_SQL_NOT_DELEGATED' gateway/policy.py
```

## 3. Compare Gateway containment with Gateway bypass

Inspect A-05 for P0 and P3:

```bash
jq '.results[] |
  select(.scenario_id=="A-05" and
    (.profile_id=="P0" or .profile_id=="P3")) |
  {scenario_id,profile_id,authorization_correct,attack_contained,artifact,steps}' \
  artifacts/m2/report.json
```

Both profiles currently leak because the fixture deliberately bypasses the
Gateway and reaches the broad database role. The repository owner must explain why this is not a
P3 regression and why P4 must make the database authorization boundary
non-bypassable even when the model, framework, tool router, or MCP Gateway is
compromised or skipped.

## 4. Run one reversible fixture experiment

This is deliberately a source change so the walkthrough proves active
understanding rather than passive reading.

1. Create a temporary local branch:

   ```bash
   git switch -c walkthrough/m2-owner
   ```

2. Record the clean M1 A-01/P0 and A-01/P3 baseline:

   ```bash
   jq '.results[] |
     select(.scenario_id=="A-01" and
       (.profile_id=="P0" or .profile_id=="P3")) |
     {scenario_id,profile_id,target_decision,query_executed,returned_row_count,
       forbidden_row_count,sensitive_plaintext_count,data_contained,artifact}' \
     artifacts/m1/report.json
   ```

3. In A-01 inside `harness/scenarios/m1.json`, append `LIMIT 1` to the attack
   SQL. Before running anything, write down the predicted changes for P0 and P3.
4. Run:

   ```bash
   make m1-test
   ```

5. Repeat the M1 report query from step 2, then inspect the changed run evidence:

   ```bash
   jq -c '{event_id,event_type,decision,reason_code,result_row_count,
     forbidden_row_count,sensitive_plaintext_count,prev_event_hash,event_hash}' \
     artifacts/m1/runs/a-01-p0.jsonl

   jq -c '{event_id,event_type,decision,reason_code,result_row_count,
     forbidden_row_count,sensitive_plaintext_count,prev_event_hash,event_hash}' \
     artifacts/m1/runs/a-01-p3.jsonl
   ```

   Confirm which row/data metrics changed and which authorization decisions did
   not. These paths deliberately point to `artifacts/m1`; do not compare the
   unchanged M2 artifacts after running only `make m1-test`.

6. Review the source diff:

   ```bash
   git diff -- harness/scenarios/m1.json
   ```

7. Restore the frozen fixture and regenerate the clean baseline:

   ```bash
   git restore harness/scenarios/m1.json
   make m1-test
   git status --short --branch
   ```

The walkthrough branch can remain local until the repository owner decides whether to delete it.
Do not commit the temporary fixture mutation to `main`.

## 5. Questions the repository owner must answer

- Why does A-01/P0 execute and expose unauthorized rows?
- Which trusted context and catalog facts make A-01/P3 deny before execution?
- Why does A-05/P3 still leak even though A-01/P3 is contained?
- What must P4 enforce inside PostgreSQL that P3 cannot guarantee at a Gateway?
- What is the difference between `authorization_correct`, `attack_contained`,
  `data_contained`, and `evidence_chain_valid`?
- Why is a valid harness-observed chain not the same as target-native audit
  completeness?
- Which result changed after `LIMIT 1`, and why did that not turn P0 into a
  secure profile?

## 6. Owner completion record

The repository owner records the following in a dated note after completing the walkthrough:

- baseline commands and PASS results;
- one A-01 P0 leak evidence pointer;
- one A-01 P3 containment evidence pointer;
- one A-05 P3 Gateway-bypass evidence pointer;
- predicted versus observed fixture-change result;
- the repository owner's own explanation of the required P4 database boundary;
- explicit decision: `M3 authorized` or `M3 remains locked`.

M3 may start only after the repository owner states that the walkthrough is complete and
explicitly authorizes M3. Test success, elapsed time, an agent summary, or a
clean repository does not satisfy this owner gate.
