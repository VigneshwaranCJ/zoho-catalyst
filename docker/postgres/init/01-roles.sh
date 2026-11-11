#!/bin/bash
# Runs once, when the Postgres data volume is first created (and in CI).
# POSTGRES_USER (the owner role) already exists; we add:
#   * the runtime app role (no superuser, no BYPASSRLS, so RLS applies to it)
#   * a separate test database used by pytest
#
# Values are passed as psql variables and inserted with :'var' (quoted literal)
# and :"var" (quoted identifier), so a password containing quotes or other
# special characters can't break or inject into the SQL.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_user="$POSTGRES_APP_USER" \
  -v app_password="$POSTGRES_APP_PASSWORD" \
  -v main_db="$POSTGRES_DB" \
  -v test_db="${POSTGRES_DB}_test" \
  -v owner="$POSTGRES_USER" <<-'EOSQL'
  CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  GRANT CONNECT ON DATABASE :"main_db" TO :"app_user";

  CREATE DATABASE :"test_db" OWNER :"owner";
  GRANT CONNECT ON DATABASE :"test_db" TO :"app_user";
EOSQL
