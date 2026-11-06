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
  done_at       timestamptz,
  CONSTRAINT commands_done_needs_claim CHECK (done_at IS NULL OR claimed_at IS NOT NULL)
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

-- Fixed-text reminders from notify_staff (E4-7) for the UI to poll. Not a clinical record; nothing here changes
-- the queue. Staff can only mark one acknowledged (column grant below).
CREATE TABLE IF NOT EXISTS notifications (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  at              timestamptz NOT NULL DEFAULT now(),
  kind            text NOT NULL
                  CHECK (kind IN ('vitals_due', 'clinician_reminder', 'model_unavailable', 'remeasure')),
  visit_id        text,
  proposal_id     uuid REFERENCES proposals,
  target_role     text NOT NULL CHECK (target_role IN ('nurse', 'clinician')),
  text            text NOT NULL,
  acknowledged_at timestamptz
);

-- Proposals are single-use: once decided they cannot change status, and only a nurse or clinician can approve.
-- (The reviewed flag may still go false -> true: a nurse acknowledges a superseded proposal.)
CREATE OR REPLACE FUNCTION proposals_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF OLD.status <> 'pending' THEN
    IF NEW.status <> OLD.status OR NEW.decided_by IS DISTINCT FROM OLD.decided_by
       OR NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN
      RAISE EXCEPTION 'proposal % is already %', OLD.id, OLD.status USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.status = 'approved' THEN
    IF NEW.decided_by IS NULL OR NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.decided_by
                                             AND role IN ('nurse', 'clinician')) THEN
      RAISE EXCEPTION 'only a nurse or clinician can approve a proposal' USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS proposals_guard ON proposals;
CREATE TRIGGER proposals_guard BEFORE UPDATE ON proposals
  FOR EACH ROW EXECUTE FUNCTION proposals_guard();

-- Append-only: block UPDATE, DELETE and TRUNCATE (the app role also has no grant for them).
CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$;
DROP TRIGGER IF EXISTS audit_nomod ON audit_log;
CREATE TRIGGER audit_nomod BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();
DROP TRIGGER IF EXISTS audit_notrunc ON audit_log;
CREATE TRIGGER audit_notrunc BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();

-- Databases created before the inline CHECK above existed get it here (a no-op on fresh ones).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'commands_done_needs_claim'
                 AND conrelid = 'afya.commands'::regclass) THEN
    ALTER TABLE commands ADD CONSTRAINT commands_done_needs_claim CHECK (done_at IS NULL OR claimed_at IS NOT NULL);
  END IF;
END $$;

-- Indexes for the queue, sweep and audit lookups.
CREATE INDEX IF NOT EXISTS proposals_pending_created ON proposals (created_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS commands_open_claimed ON commands (claimed_at) WHERE done_at IS NULL;
CREATE INDEX IF NOT EXISTS commands_visit ON commands (visit_id);
CREATE INDEX IF NOT EXISTS audit_visit_at ON audit_log (visit_id, at);
CREATE INDEX IF NOT EXISTS audit_run ON audit_log (run_id);
CREATE INDEX IF NOT EXISTS notifications_open ON notifications (at) WHERE acknowledged_at IS NULL;

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
-- notifications: staff only mark one acknowledged; kind, text and targets never change after insert.
REVOKE ALL ON notifications FROM afya_app;
GRANT SELECT, INSERT ON notifications TO afya_app;
GRANT UPDATE (acknowledged_at) ON notifications TO afya_app;
-- audit_log: read everything, insert only the columns the app supplies (id and at always come from defaults).
REVOKE ALL ON audit_log FROM afya_app;
GRANT SELECT ON audit_log TO afya_app;
GRANT INSERT (kind, actor, auth, visit_id, run_id, payload) ON audit_log TO afya_app;   -- no UPDATE / DELETE / TRUNCATE
-- LangGraph checkpoint tables are created later in schema lg by lg-init (as afya_owner):
ALTER DEFAULT PRIVILEGES FOR ROLE afya_owner IN SCHEMA lg
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO afya_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA lg TO afya_app;
-- Sequences created later in lg (none today; keeps a future serial/identity column usable).
ALTER DEFAULT PRIVILEGES FOR ROLE afya_owner IN SCHEMA lg GRANT USAGE, SELECT ON SEQUENCES TO afya_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA lg TO afya_app;
