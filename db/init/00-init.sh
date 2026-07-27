#!/bin/bash
# Runs once, as the Postgres superuser, on first cluster init.
# Creates the pgvector extension and a NON-superuser app role so that
# Row-Level Security is actually enforced (superusers & BYPASSRLS roles skip RLS).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS vector;

  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'valor_app') THEN
      CREATE ROLE valor_app LOGIN PASSWORD '${APP_DB_PASSWORD}'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
  END
  \$\$;

  GRANT ALL ON SCHEMA public TO valor_app;
  GRANT ALL PRIVILEGES ON DATABASE valor TO valor_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO valor_app;
  ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO valor_app;
EOSQL

echo "valor-ops: db init complete (vector extension + valor_app role)"
