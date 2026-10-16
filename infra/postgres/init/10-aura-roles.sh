#!/usr/bin/env bash
# Aura database bootstrap: roles, extensions, ownership. Idempotent.
#
# Runs automatically on a fresh volume (docker-entrypoint-initdb.d, used by compose) and is
# re-run by scripts/db.ps1 on every `up`, so it must be safe to run twice.
#
#   aura_owner  owns the schema and runs Alembic. CREATEDB (the test fixture creates
#               aura_test) and BYPASSRLS (the SECURITY DEFINER wall-check functions it owns
#               read the wall tables without recursing into their own policies; the
#               SQLite import copies rows across every wall). Never used by the running app.
#   aura_app    what the API and worker connect as. Not a superuser, not BYPASSRLS, owns no
#               table: row-level security always applies to it.
set -euo pipefail

: "${AURA_PG_OWNER_PASSWORD:?AURA_PG_OWNER_PASSWORD is required}"
: "${AURA_PG_APP_PASSWORD:?AURA_PG_APP_PASSWORD is required}"
DB="${POSTGRES_DB:-aura}"

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname postgres \
     -v owner_pw="$AURA_PG_OWNER_PASSWORD" -v app_pw="$AURA_PG_APP_PASSWORD" -v db="$DB" <<'SQL'
SELECT format('CREATE ROLE aura_owner LOGIN CREATEDB BYPASSRLS PASSWORD %L', :'owner_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aura_owner') \gexec
SELECT format('ALTER ROLE aura_owner LOGIN CREATEDB BYPASSRLS NOSUPERUSER PASSWORD %L',
              :'owner_pw') \gexec
SELECT format('CREATE ROLE aura_app LOGIN PASSWORD %L', :'app_pw')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aura_app') \gexec
SELECT format('ALTER ROLE aura_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS '
              'PASSWORD %L', :'app_pw') \gexec
SELECT format('CREATE DATABASE %I OWNER aura_owner', :'db')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SELECT format('ALTER DATABASE %I OWNER TO aura_owner', :'db') \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db') \gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO aura_app', :'db') \gexec
SQL

# Extensions need a superuser. template1 too, so databases aura_owner creates later
# (the aura_test database of the test suite) start with them.
for target in "$DB" template1; do
  psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER:-postgres}" --dbname "$target" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
SQL
done
echo "aura roles and extensions ready"
