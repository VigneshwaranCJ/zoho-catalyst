#!/bin/bash
# Runs once, when the Postgres data volume is first created.
# POSTGRES_USER (the owner role) already exists; we add:
#   * the runtime app role (no superuser, no BYPASSRLS, so RLS applies to it)
#   * a separate test database used by pytest
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE ROLE ${POSTGRES_APP_USER} LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${POSTGRES_APP_USER};

  CREATE DATABASE ${POSTGRES_DB}_test OWNER ${POSTGRES_USER};
  GRANT CONNECT ON DATABASE ${POSTGRES_DB}_test TO ${POSTGRES_APP_USER};
EOSQL
