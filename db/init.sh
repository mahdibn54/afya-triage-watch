#!/bin/sh
# db-init: creates roles, then runs schema.sql as the owner role in the app database (afya) and in a separate
# database for the automated tests (afya_test, same roles and schema): tests never touch the data the stack uses.
# Runs as the superuser. Owner and superuser passwords exist only here and in lg-init.
set -eu

until pg_isready -q; do sleep 1; done

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
SELECT 'CREATE DATABASE afya_test' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'afya_test') \gexec
SQL

for db in afya afya_test; do
  echo "db-init: database $db"
  psql -v ON_ERROR_STOP=1 -v db="$db" <<'SQL'
ALTER ROLE afya_app IN DATABASE :"db" SET search_path = afya, lg;
GRANT CONNECT, CREATE ON DATABASE :"db" TO afya_owner;
GRANT CONNECT ON DATABASE :"db" TO afya_app;
REVOKE TEMP ON DATABASE :"db" FROM PUBLIC;
SQL
  psql -d "$db" -v ON_ERROR_STOP=1 -c 'REVOKE CREATE ON SCHEMA public FROM PUBLIC'
  echo "db-init: schema in $db (as afya_owner)"
  PGDATABASE="$db" PGUSER=afya_owner PGPASSWORD="$AFYA_OWNER_PASSWORD" \
    psql -1 -v ON_ERROR_STOP=1 -f /db/schema.sql
done

echo "db-init: done"
