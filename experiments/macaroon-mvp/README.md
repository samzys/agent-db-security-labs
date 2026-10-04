# Macaroon delegation: a local learning experiment

A parent credential for ticket 101 is attenuated into a read-only child credential. The holder does not pass an issuer root key to the attenuation function or contact an issuer. The resource checks the actual request before touching synthetic data.

## Run

Clone the publication branch and enter this experiment directory:

```sh
git clone --branch feat/macaroon-mvp --single-branch https://github.com/samzys/agent-db-security-labs.git
cd agent-db-security-labs/experiments/macaroon-mvp
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python demo.py --output my-results.json
```

The script returns a nonzero exit status if a prediction or subset check fails. `results.json` preserves the original v1.1 run; use a different output name for a new run.

## What the 14 checks cover

- C01-C04: the parent can write, the child can read, and the child cannot write or read another ticket.
- C05-C06: appending a conflicting write condition or deleting the read condition while retaining the child MAC is rejected.
- C07: the retained parent credential remains usable.
- C08: changing an unauthenticated holder label does not prevent use of the same bearer credential.
- C09-C14: an issuer-issued read-only parent and a normal child allow read; a child with both read and write conditions permits neither operation in this test domain.

All cases check the returned data and before/after state as well as ALLOW/DENY. C01/C07 repeat the same action for different teaching purposes. The 14 checks are not 14 distinct attacks.

## Scope

Contract: `macaroon-learning-mvp-v1.1`. One process, first-party caveats, synthetic tickets. No real model, HTTP service, authenticated holder, process isolation, expiry, revocation, third-party discharge, or database authorization boundary. The harness holds all credentials and the ephemeral root key. It does not prove secret isolation.

`pymacaroons==0.13.0` is an older release selected for a small teaching example, not a production recommendation. The dependency pins used in the original run are in `requirements.txt`.

Code, experiment design and documentation were prepared with AI assistance. The saved report records actual execution rather than expected-only output.
