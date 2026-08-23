#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
PGSOCKET="${M0_RUNTIME_DIR:-${REPO_ROOT}/.runtime/postgres}/socket"
PGPORT="${M0_PGPORT:-55432}"
PGDATABASE="agent_db_m0"
ADMIN="lab_admin"
PSQL="${PG_BIN}/psql"

psql_as() {
  local role="$1"
  local sql="$2"
  "${PSQL}" -XAtq \
    -h "${PGSOCKET}" -p "${PGPORT}" -U "${role}" -d "${PGDATABASE}" \
    -v ON_ERROR_STOP=1 -c "${sql}"
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local label="$3"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "FAIL ${label}: expected=${expected@Q} actual=${actual@Q}" >&2
    exit 1
  fi
  echo "PASS ${label}: ${actual}"
}

load_schema() {
  "${PSQL}" -X \
    -h "${PGSOCKET}" -p "${PGPORT}" -U "${ADMIN}" -d "${PGDATABASE}" \
    -v ON_ERROR_STOP=1 -f "${REPO_ROOT}/db/m0_schema.sql" >/dev/null
  echo "M0 schema loaded"
}

run_tests() {
  load_schema

  local attrs
  attrs="$(psql_as "${ADMIN}" "
    SELECT string_agg(rolname || ':' || rolsuper || ':' || rolbypassrls, ',' ORDER BY rolname)
    FROM pg_roles
    WHERE rolname IN ('app_agent_rls','app_broad_reader','task_alpha_a101','task_beta_b201');")"
  assert_eq \
    "app_agent_rls:false:false,app_broad_reader:false:false,task_alpha_a101:false:false,task_beta_b201:false:false" \
    "${attrs}" \
    "runtime roles are non-superuser and cannot BYPASSRLS"

  local owner
  owner="$(psql_as "${ADMIN}" "SELECT tableowner FROM pg_tables WHERE schemaname='lab' AND tablename='customers';")"
  assert_eq "lab_owner" "${owner}" "runtime role does not own protected table"

  local broad_count
  broad_count="$(psql_as app_broad_reader "SELECT count(*) FROM lab.customers;")"
  assert_eq "3" "${broad_count}" "broad-reader positive control sees all rows"

  local local_reset
  local_reset="$(psql_as app_agent_rls "
    BEGIN;
    SET LOCAL app.tenant_id='alpha';
    SET LOCAL app.customer_id='101';
    SELECT count(*) FROM lab.customers;
    COMMIT;
    SELECT count(*) FROM lab.customers;")"
  assert_eq $'1\n0' "${local_reset}" "SET LOCAL context clears after transaction"

  local guc_tamper
  guc_tamper="$(psql_as app_agent_rls "
    BEGIN;
    SET LOCAL app.tenant_id='alpha';
    SET LOCAL app.customer_id='101';
    SELECT name FROM lab.customers;
    SET LOCAL app.tenant_id='beta';
    SET LOCAL app.customer_id='201';
    SELECT name FROM lab.customers;
    COMMIT;")"
  assert_eq $'Alpha Fixture\nBeta Fixture' "${guc_tamper}" \
    "negative control proves model-settable GUC can retarget RLS"

  local task_scope
  task_scope="$(psql_as task_alpha_a101 "SELECT name FROM lab.customers;")"
  assert_eq "Alpha Fixture" "${task_scope}" "task login role sees only bound row"

  local task_tamper
  task_tamper="$(psql_as task_alpha_a101 "
    BEGIN;
    SET LOCAL app.tenant_id='beta';
    SET LOCAL app.customer_id='201';
    SELECT name FROM lab.customers;
    COMMIT;")"
  assert_eq "Alpha Fixture" "${task_tamper}" "GUC tamper cannot change task-role scope"

  if psql_as task_alpha_a101 "SET ROLE task_beta_b201; SELECT 1;" >/dev/null 2>&1; then
    echo "FAIL task role unexpectedly switched to another task role" >&2
    exit 1
  fi
  echo "PASS task role cannot switch to another task role"

  local capability
  capability="$(psql_as task_alpha_a101 "
    SELECT name || '|' || email_masked || '|' || plan
    FROM lab.get_task_customer();")"
  assert_eq "Alpha Fixture|a***@example.com|pro" "${capability}" \
    "server-owned capability binds resource and masks email"

  local beta_scope
  beta_scope="$(psql_as task_beta_b201 "SELECT name FROM lab.customers;")"
  assert_eq "Beta Fixture" "${beta_scope}" "second task role sees only its tenant row"

  echo "M0 database checks passed"
}

case "${1:-}" in
  schema) load_schema ;;
  test) run_tests ;;
  *) echo "usage: $0 {schema|test}" >&2; exit 2 ;;
esac
