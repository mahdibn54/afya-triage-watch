-- Afya Triage Watch: PostgreSQL schema (architecture v4.1, Appendix A).
-- Run by db-init as afya_owner. Idempotent: safe to run on every start.
-- Append-only holds against the application role (afya_app), not against a database administrator.

CREATE SCHEMA IF NOT EXISTS afya AUTHORIZATION afya_owner;
CREATE SCHEMA IF NOT EXISTS lg   AUTHORIZATION afya_owner;
SET search_path = afya;

CREATE TABLE IF NOT EXISTS users (
  id   text PRIMARY KEY,
  name text NOT NULL,
  role text NOT NULL CHECK (role IN ('nurse', 'clinician', 'manager', 'agent', 'system'))
);

CREATE TABLE IF NOT EXISTS visits (
  id            text PRIMARY KEY,
  patient_id    text NOT NULL,
  latest_obs_id text
);

CREATE TABLE IF NOT EXISTS proposals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  visit_id      text NOT NULL REFERENCES visits,
  trigger       text NOT NULL,
  evidence_hash text NOT NULL,
  obs_id        text NOT NULL,
  payload       jsonb NOT NULL,
  status        text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected', 'superseded')),
  reviewed      boolean NOT NULL DEFAULT false,   -- superseded but never reviewed stays visible
  created_at    timestamptz NOT NULL DEFAULT now(),
  decided_by    text REFERENCES users,
  decided_at    timestamptz,
  UNIQUE (visit_id, trigger, evidence_hash)
);

CREATE TABLE IF NOT EXISTS commands (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id   uuid NOT NULL UNIQUE REFERENCES proposals,
  action_type   text NOT NULL DEFAULT 'recheck_flag',
  visit_id      text NOT NULL REFERENCES visits,
  obs_id        text NOT NULL,
  colour        text NOT NULL CHECK (colour IN ('RED', 'ORANGE', 'YELLOW', 'GREEN')),
  evidence_hash text NOT NULL,
  expires_at    timestamptz NOT NULL,
  claimed_at    timestamptz,
  attempts      int NOT NULL DEFAULT 0,
  done_at       timestamptz
);

CREATE TABLE IF NOT EXISTS audit_log (
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at       timestamptz NOT NULL DEFAULT now(),
  kind     text NOT NULL,
  actor    text NOT NULL REFERENCES users,
  auth     text NOT NULL DEFAULT 'demo_switcher',
  visit_id text,
  run_id   text,
  payload  jsonb NOT NULL
);

-- Append-only: block UPDATE, DELETE and TRUNCATE (the app role also has no grant for them).
CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$;
DROP TRIGGER IF EXISTS audit_nomod ON audit_log;
CREATE TRIGGER audit_nomod BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();
DROP TRIGGER IF EXISTS audit_notrunc ON audit_log;
CREATE TRIGGER audit_notrunc BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();

-- Demo users (synthetic). Real sign-in is a stated gap.
INSERT INTO users (id, name, role) VALUES
  ('nurse-a',    'Nurse A.',  'nurse'),
  ('clin-m',     'Dr. M',     'clinician'),
  ('mgr-k',      'Dir. K',    'manager'),
  ('agent',      'Afya agent','agent'),
  ('system',     'System',    'system')
ON CONFLICT (id) DO NOTHING;

-- Grants for the application role.
GRANT USAGE ON SCHEMA afya, lg TO afya_app;
GRANT SELECT, INSERT, UPDATE ON visits, proposals, commands TO afya_app;
GRANT SELECT ON users TO afya_app;
GRANT SELECT, INSERT ON audit_log TO afya_app;   -- no UPDATE / DELETE / TRUNCATE
-- LangGraph checkpoint tables are created later in schema lg by lg-init (as afya_owner):
ALTER DEFAULT PRIVILEGES FOR ROLE afya_owner IN SCHEMA lg
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO afya_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA lg TO afya_app;
