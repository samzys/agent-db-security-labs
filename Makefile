PYTHON ?= python3

.PHONY: m0-up m0-down m0-clean m0-schema m0-db-test m0-unit m0-artifact m0-test
.PHONY: m1-run m1-verify m1-test
.PHONY: m2-run m2-verify m2-test

m0-up:
	./scripts/m0_runtime.sh up

m0-down:
	./scripts/m0_runtime.sh down

m0-clean:
	./scripts/m0_runtime.sh clean

m0-schema: m0-up
	./scripts/m0_verify.sh schema

m0-db-test: m0-up
	./scripts/m0_verify.sh test

m0-unit:
	$(PYTHON) -m unittest discover -s tests -v

m0-artifact:
	$(PYTHON) -m harness.m0_spike
	$(PYTHON) -m audit.verify_artifact artifacts/m0/a01-p3.jsonl

m0-test: m0-db-test m0-unit m0-artifact

m1-run: m0-schema
	$(PYTHON) -m harness.m1_runner

m1-verify:
	$(PYTHON) -m harness.verify_m1 artifacts/m1/report.json

m1-test: m0-db-test m0-unit m1-run m1-verify

m2-run: m0-schema
	$(PYTHON) -m harness.m2_runner

m2-verify:
	$(PYTHON) -m harness.verify_m2 artifacts/m2/report.json

m2-test: m0-db-test m0-unit m2-run m2-verify
