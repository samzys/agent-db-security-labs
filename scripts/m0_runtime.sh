#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
RUNTIME_DIR="${M0_RUNTIME_DIR:-${REPO_ROOT}/.runtime/postgres}"
PGDATA="${RUNTIME_DIR}/data"
PGSOCKET="${RUNTIME_DIR}/socket"
PGLOG="${RUNTIME_DIR}/postgres.log"
PGPORT="${M0_PGPORT:-55432}"
PGUSER="lab_admin"
PGDATABASE="agent_db_m0"

require_binary() {
  if [[ ! -x "${PG_BIN}/$1" ]]; then
    echo "missing ${PG_BIN}/$1; install PostgreSQL 17 or set PG_BIN" >&2
    exit 1
  fi
}

is_running() {
  [[ -f "${PGDATA}/PG_VERSION" ]] &&
    "${PG_BIN}/pg_ctl" -D "${PGDATA}" status >/dev/null 2>&1
}

up() {
  require_binary initdb
  require_binary pg_ctl
  require_binary psql
  require_binary createdb

  mkdir -p "${PGSOCKET}"
  if [[ ! -f "${PGDATA}/PG_VERSION" ]]; then
    "${PG_BIN}/initdb" \
      -D "${PGDATA}" \
      -A trust \
      -U "${PGUSER}" \
      --no-locale \
      --encoding=UTF8 >/dev/null
  fi

  if ! is_running; then
    "${PG_BIN}/pg_ctl" \
      -D "${PGDATA}" \
      -l "${PGLOG}" \
      -o "-p ${PGPORT} -k ${PGSOCKET} -h ''" \
      -w start >/dev/null
  fi

  if ! "${PG_BIN}/psql" -XAtq \
      -h "${PGSOCKET}" -p "${PGPORT}" -U "${PGUSER}" -d postgres \
      -c "SELECT 1 FROM pg_database WHERE datname='${PGDATABASE}'" | grep -qx 1; then
    "${PG_BIN}/createdb" \
      -h "${PGSOCKET}" -p "${PGPORT}" -U "${PGUSER}" "${PGDATABASE}"
  fi

  echo "M0 PostgreSQL ready: socket=${PGSOCKET} port=${PGPORT} db=${PGDATABASE}"
}

down() {
  require_binary pg_ctl
  if is_running; then
    "${PG_BIN}/pg_ctl" -D "${PGDATA}" -m fast -w stop >/dev/null
    echo "M0 PostgreSQL stopped"
  else
    echo "M0 PostgreSQL already stopped"
  fi
}

clean() {
  down
  case "${RUNTIME_DIR}" in
    "${REPO_ROOT}/.runtime/"*) rm -rf "${RUNTIME_DIR}" ;;
    *) echo "refusing to remove unexpected runtime path: ${RUNTIME_DIR}" >&2; exit 1 ;;
  esac
  echo "M0 runtime removed: ${RUNTIME_DIR}"
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  clean) clean ;;
  *) echo "usage: $0 {up|down|clean}" >&2; exit 2 ;;
esac
