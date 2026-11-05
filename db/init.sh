#!/bin/sh
# db-init: creates roles, then runs schema.sql as the owner role.
# Runs as the superuser. Owner and superuser passwords exist only in this container.
set -eu

echo "db-init: roles"
psql -v ON_ERROR_STOP=1 \
     -v owner_pw="$AFYA_OWNER_PASSWORD" \
     -v app_pw="$AFYA_APP_PASSWORD" <<'SQL'
SELECT 'CREATE ROLE afya_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'afya_owner') \gexec
SELECT 'CREATE ROLE afya_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'afya_app') \gexec
ALTER ROLE afya_owner PASSWORD :'owner_pw';
ALTER ROLE afya_app   PASSWORD :'app_pw';
GRANT CONNECT, CREATE ON DATABASE afya TO afya_owner;
GRANT CONNECT ON DATABASE afya TO afya_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL

echo "db-init: schema (as afya_owner)"
PGUSER=afya_owner PGPASSWORD="$AFYA_OWNER_PASSWORD" \
  psql -v ON_ERROR_STOP=1 -f /db/schema.sql

echo "db-init: done"
