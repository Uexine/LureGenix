#!/bin/sh
set -eu
export PGHOST=postgres PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD" PGDATABASE="$DB_NAME"

# A session lock protects the whole migration batch, including role grants.
{
    printf 'SELECT pg_advisory_lock(71024002);\n'
    for migration in /migrations/[0-9][0-9]_*.sql; do
        printf '\\i %s\n' "$migration"
    done
    printf '\\i /migrations/app_role.sql\n'
    printf 'SELECT pg_advisory_unlock(71024002);\n'
} | psql -X -v ON_ERROR_STOP=1 -v app_user="$APP_DB_USER" -v app_password="$APP_DB_PASSWORD"
