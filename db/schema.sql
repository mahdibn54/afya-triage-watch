-- Afya Triage Watch: PostgreSQL schema (architecture v4.1, Appendix A).
-- Run by db-init as afya_owner. Idempotent: safe to run on every start.
-- Append-only holds against the application role (afya_app), not against a database administrator.
--
-- Existing volumes: db-init runs this file as ONE transaction (psql -1, see db/init.sh), so a volume created by an
-- earlier version is migrated in place: every statement is IF NOT EXISTS / OR REPLACE / DROP-then-CREATE, so nothing
-- is lost and no trigger is ever missing while the app runs. `schema_version` (end of file) records what was applied.
-- To migrate: `docker compose run --rm db-init`. To start empty instead: `docker compose down -v` (wipes ALL data).

CREATE SCHEMA IF NOT EXISTS afya AUTHORIZATION afya_owner;
CREATE SCHEMA IF NOT EXISTS lg   AUTHORIZATION afya_owner;
SET search_path = afya;

CREATE TABLE IF NOT EXISTS schema_version (
  version    int PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now(),
  note       text NOT NULL
);

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
-- Display label of the patient (Patient.identifier urn:afya:label, e.g. "P-014"), copied here so proposal lists need no
-- FHIR call. Never a name.
ALTER TABLE visits ADD COLUMN IF NOT EXISTS patient_label text;
-- effectiveDateTime of the reading latest_obs_id points at: latest_obs_id only moves forward in time (E12-2), so two
-- concurrent record_vitals calls cannot leave the older reading as "latest".
ALTER TABLE visits ADD COLUMN IF NOT EXISTS latest_obs_at timestamptz;

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

-- Free-text complaint entered with a reading (api.md Q1). Kept in Postgres only: it never goes into FHIR, so it never
-- reaches the model as FHIR text; only map_signs sees it. NFKC-normalised, at most 500 characters.
CREATE TABLE IF NOT EXISTS readings (
  obs_id     text PRIMARY KEY,                        -- bare Observation id
  visit_id   text NOT NULL REFERENCES visits,
  complaint  text NOT NULL CHECK (char_length(complaint) BETWEEN 1 AND 500),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS readings_visit ON readings (visit_id);
-- Patient-reported change (Deterioration Watch): the nurse ticks "patient or nurse reports worse" with the reading.
-- A coded yes/no, not free text. The row then exists even without a complaint.
ALTER TABLE readings ADD COLUMN IF NOT EXISTS reported_worsening boolean NOT NULL DEFAULT false;
ALTER TABLE readings ALTER COLUMN complaint DROP NOT NULL;
-- A readings row exists only for a complaint or a worsening tick (E12-2: now enforced).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'readings_has_content'
                 AND conrelid = 'afya.readings'::regclass) THEN
    ALTER TABLE readings ADD CONSTRAINT readings_has_content CHECK (complaint IS NOT NULL OR reported_worsening);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS audit_log (
  id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at       timestamptz NOT NULL DEFAULT now(),
  kind     text NOT NULL,
  actor    text NOT NULL REFERENCES users,
  auth     text NOT NULL,
  visit_id text,
  run_id   text,
  payload  jsonb NOT NULL
);

-- E12-2: no default for auth: the writer must say who vouched for the actor ('demo_switcher' for a signed-in nurse,
-- clinician or manager, 'service' for the agent and system). Databases created before this had a default.
ALTER TABLE audit_log ALTER COLUMN auth DROP DEFAULT;

-- Fixed-text reminders from notify_staff (E4-7) for the UI to poll. Not a clinical record; nothing here changes
-- the queue. Staff can only mark one acknowledged (column grant below).
CREATE TABLE IF NOT EXISTS notifications (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  at              timestamptz NOT NULL DEFAULT now(),
  kind            text NOT NULL
                  CHECK (kind IN ('vitals_due', 'clinician_reminder', 'model_unavailable', 'remeasure',
                                  'agent_failed', 'command_abandoned')),
  visit_id        text,
  proposal_id     uuid REFERENCES proposals,
  target_role     text NOT NULL CHECK (target_role IN ('nurse', 'clinician')),
  text            text NOT NULL,
  acknowledged_at timestamptz
);

-- Proposals are single-use: once decided they cannot change status, and only a nurse or clinician can approve or reject.
-- What the nurse saw is what gets approved: payload, obs_id, evidence_hash, visit_id and trigger never change (E12-2),
-- pending or not. (The reviewed flag may still go false -> true: a nurse acknowledges a superseded proposal.)
CREATE OR REPLACE FUNCTION proposals_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.payload IS DISTINCT FROM OLD.payload OR NEW.obs_id IS DISTINCT FROM OLD.obs_id
     OR NEW.evidence_hash IS DISTINCT FROM OLD.evidence_hash OR NEW.visit_id IS DISTINCT FROM OLD.visit_id
     OR NEW.trigger IS DISTINCT FROM OLD.trigger THEN
    RAISE EXCEPTION 'proposal % content is frozen', OLD.id USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status <> 'pending' THEN
    IF NEW.status <> OLD.status OR NEW.decided_by IS DISTINCT FROM OLD.decided_by
       OR NEW.decided_at IS DISTINCT FROM OLD.decided_at THEN
      RAISE EXCEPTION 'proposal % is already %', OLD.id, OLD.status USING ERRCODE = 'check_violation';
    END IF;
  ELSIF NEW.status IN ('approved', 'rejected') THEN
    IF NEW.decided_by IS NULL OR NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.decided_by
                                             AND role IN ('nurse', 'clinician')) THEN
      RAISE EXCEPTION 'only a nurse or clinician can approve or reject a proposal'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS proposals_guard ON proposals;
CREATE TRIGGER proposals_guard BEFORE UPDATE ON proposals
  FOR EACH ROW EXECUTE FUNCTION proposals_guard();

-- A proposal is born pending, or superseded when a newer reading already exists: never decided (E12-2).
CREATE OR REPLACE FUNCTION proposals_insert_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NEW.status NOT IN ('pending', 'superseded') OR NEW.decided_by IS NOT NULL OR NEW.decided_at IS NOT NULL THEN
    RAISE EXCEPTION 'a proposal can only be created pending or superseded' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS proposals_insert_guard ON proposals;
CREATE TRIGGER proposals_insert_guard BEFORE INSERT ON proposals
  FOR EACH ROW EXECUTE FUNCTION proposals_insert_guard();

-- Invariants between proposals and commands (E12-2):
--  * a command exists only for an approved proposal, and copies its visit, reading and evidence hash;
--  * an approved proposal has a command by the end of the transaction that approved it (deferred, so approve can
--    update the proposal and insert the command in either order).
CREATE OR REPLACE FUNCTION commands_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM proposals p WHERE p.id = NEW.proposal_id AND p.status = 'approved'
                 AND p.visit_id = NEW.visit_id AND p.obs_id = NEW.obs_id AND p.evidence_hash = NEW.evidence_hash) THEN
    RAISE EXCEPTION 'a command needs an approved proposal with the same visit, reading and evidence'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS commands_guard ON commands;
CREATE TRIGGER commands_guard BEFORE INSERT ON commands
  FOR EACH ROW EXECUTE FUNCTION commands_guard();

CREATE OR REPLACE FUNCTION proposals_need_command() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM commands WHERE proposal_id = NEW.id) THEN
    RAISE EXCEPTION 'approved proposal % has no command', NEW.id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS proposals_need_command ON proposals;
CREATE CONSTRAINT TRIGGER proposals_need_command AFTER UPDATE OF status ON proposals
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.status = 'approved')
  EXECUTE FUNCTION proposals_need_command();

-- Append-only: block UPDATE, DELETE and TRUNCATE (the app role also has no grant for them).
CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'audit_log is append-only'; END $$;
DROP TRIGGER IF EXISTS audit_nomod ON audit_log;
CREATE TRIGGER audit_nomod BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();
DROP TRIGGER IF EXISTS audit_notrunc ON audit_log;
CREATE TRIGGER audit_notrunc BEFORE TRUNCATE ON audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION audit_immutable();

-- E12-2: an approved command that can never run (approval expired, newer vitals arrived, or the executor gave up
-- after MAX_ATTEMPTS) is ABANDONED instead of retried for ever. The startup sweep sets it, in the same transaction as
-- a `command_abandoned` audit row and one open notice per visit. A nurse re-opens it by recording a new reading, which
-- gets its own proposal (an approved proposal is single-use and its dedup key stays taken).
ALTER TABLE commands ADD COLUMN IF NOT EXISTS abandoned_at timestamptz;
ALTER TABLE commands ADD COLUMN IF NOT EXISTS abandon_reason text;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'commands_abandon_consistent'
                 AND conrelid = 'afya.commands'::regclass) THEN
    ALTER TABLE commands ADD CONSTRAINT commands_abandon_consistent CHECK (
      (abandoned_at IS NULL) = (abandon_reason IS NULL)
      AND (abandon_reason IS NULL OR abandon_reason IN ('expired', 'stale', 'attempts'))
      AND (abandoned_at IS NULL OR done_at IS NULL));
  END IF;
END $$;

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
CREATE INDEX IF NOT EXISTS commands_sweep ON commands (expires_at) WHERE done_at IS NULL AND abandoned_at IS NULL;
CREATE INDEX IF NOT EXISTS audit_visit_at ON audit_log (visit_id, at);
CREATE INDEX IF NOT EXISTS audit_run ON audit_log (run_id);
CREATE INDEX IF NOT EXISTS notifications_open ON notifications (at) WHERE acknowledged_at IS NULL;
CREATE INDEX IF NOT EXISTS notifications_visit_kind ON notifications (visit_id, kind, at);
-- at most one open "command abandoned" notice per visit (the sweep inserts with ON CONFLICT DO NOTHING)
CREATE UNIQUE INDEX IF NOT EXISTS notifications_one_open_abandoned ON notifications (visit_id)
  WHERE kind = 'command_abandoned' AND acknowledged_at IS NULL;
-- E12-1 agent_failed, E12-2 command_abandoned. Re-stated for volumes created before they existed.
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_kind_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_kind_check
  CHECK (kind IN ('vitals_due', 'clinician_reminder', 'model_unavailable', 'remeasure', 'agent_failed',
                  'command_abandoned'));

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
-- visits, proposals, commands: insert, and update only the columns the workflow changes (E12-2). The decided content of
-- a proposal, a command's colour / expiry / evidence, and a visit's patient can never be rewritten by the app role.
REVOKE UPDATE ON visits, proposals, commands FROM afya_app;
GRANT SELECT, INSERT ON visits, proposals, commands TO afya_app;
GRANT UPDATE (latest_obs_id, latest_obs_at, patient_label) ON visits TO afya_app;
GRANT UPDATE (status, reviewed, decided_by, decided_at) ON proposals TO afya_app;
GRANT UPDATE (claimed_at, attempts, done_at, abandoned_at, abandon_reason) ON commands TO afya_app;
GRANT SELECT ON schema_version TO afya_app;
GRANT SELECT, INSERT ON readings TO afya_app;   -- a complaint is written once with its reading, never edited
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

-- What this file has applied. 2 = E12-2 (abandoned commands, column grants, frozen proposals, invariants); volumes
-- from before it (no row 1: the table did not exist) get row 2 on the first db-init run.
INSERT INTO schema_version (version, note) VALUES
  (2, 'E12-2: abandoned commands, column grants, proposal freeze, proposal/command invariants, latest_obs_at')
ON CONFLICT (version) DO NOTHING;
