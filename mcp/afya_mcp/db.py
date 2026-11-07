"""PostgreSQL access for afya-mcp (psycopg 3, role afya_app).

Connections follow the runtime rules from the DB audit: autocommit, dict rows, no prepared statements
(prepare_threshold=0, so a pooler in front would also work). Statements that must be atomic open an explicit
`with conn.transaction():` block. The application never creates tables: db-init and lg-init own the DDL.

No connection pool by design (E12-2, documented): afya-mcp opens one short-lived connection per call and the api one
per request, for a handful of concurrent nurses; a pooler such as PgBouncer in transaction mode can sit in front
because no prepared statements or session state are used (advisory locks of the executor are session-level: keep it
on a direct connection). The audit log has no hash chain: append-only for the app role, not tamper-evident against a
database administrator.

`VisitStore` is the small interface the services use. `PgVisitStore` is the real one; tests inject a fake.
"""
from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from datetime import datetime
from typing import Protocol

import psycopg
from psycopg.rows import DictRow, dict_row

from .workflow import open_notifications, open_proposals, supersede_pending


def connect(url: str | None = None) -> psycopg.Connection[DictRow]:
    """One autocommit connection. DATABASE_URL points at afya_app (search_path afya, lg is set on the role)."""
    return psycopg.connect(url or os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row,
                           prepare_threshold=0)


class VisitStore(Protocol):
    def record_reading(self, visit_id: str, patient_id: str, latest_obs_id: str,
                       patient_label: str | None = None, latest_at: datetime | None = None,
                       reading_obs_id: str | None = None, complaint: str | None = None,
                       reported_worsening: bool = False) -> None:
        """ONE transaction: upsert the visit and set latest_obs_id (only forward in time when latest_at is given);
        older pending proposals become superseded; and, if there is a complaint or the worsening tick, the readings
        row of reading_obs_id (a retry keeps the first row)."""

    def save_complaint(self, visit_id: str, obs_id: str, complaint: str | None,
                       reported_worsening: bool = False) -> None:
        """Store the complaint and the reported-worsening tick of one reading (Postgres only, once: a retry keeps
        the first row)."""

    def open_proposals(self) -> list[dict]:
        """Pending proposals and superseded ones not yet reviewed (workflow.open_proposals)."""

    def open_notifications(self) -> list[dict]:
        """Notices nobody dismissed yet (workflow.open_notifications)."""


class PgVisitStore:
    """Opens a short-lived connection per call: afya-mcp calls are infrequent and run in worker threads."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url

    @contextlib.contextmanager
    def connection(self) -> Iterator[psycopg.Connection[DictRow]]:
        with connect(self.url) as conn:
            yield conn

    def record_reading(self, visit_id: str, patient_id: str, latest_obs_id: str,
                       patient_label: str | None = None, latest_at: datetime | None = None,
                       reading_obs_id: str | None = None, complaint: str | None = None,
                       reported_worsening: bool = False) -> None:
        with self.connection() as conn, conn.transaction():
            upsert_visit(conn, visit_id, patient_id, latest_obs_id, patient_label, latest_at)
            if reading_obs_id and (complaint or reported_worsening):
                _insert_reading_note(conn, visit_id, reading_obs_id, complaint, reported_worsening)

    def save_complaint(self, visit_id: str, obs_id: str, complaint: str | None,
                       reported_worsening: bool = False) -> None:
        with self.connection() as conn:
            _insert_reading_note(conn, visit_id, obs_id, complaint, reported_worsening)

    def open_proposals(self) -> list[dict]:
        with self.connection() as conn:
            return open_proposals(conn)

    def open_notifications(self) -> list[dict]:
        with self.connection() as conn:
            return open_notifications(conn)


def _insert_reading_note(conn: psycopg.Connection[DictRow], visit_id: str, obs_id: str, complaint: str | None,
                         reported_worsening: bool) -> None:
    if not complaint and not reported_worsening:
        return
    conn.execute("INSERT INTO readings (obs_id, visit_id, complaint, reported_worsening) "
                 "VALUES (%s, %s, %s, %s) ON CONFLICT (obs_id) DO NOTHING",
                 (obs_id, visit_id, complaint, reported_worsening))


def upsert_visit(conn: psycopg.Connection[DictRow], visit_id: str, patient_id: str, latest_obs_id: str,
                 patient_label: str | None = None, latest_at: datetime | None = None) -> None:
    """E4-2 (DB part): visit row and latest reading in one transaction. A visit never changes patient.

    latest_obs_id only moves FORWARD in time when `latest_at` (the reading's effectiveDateTime) is known: a slower
    concurrent call carrying an older reading leaves the newer one in place (E12-2). Proposals still pending for
    anything but the stored latest reading are superseded here (reviewed stays false, so an unread one stays visible
    as "not reviewed"); the claim query already fails for commands whose reading is no longer the latest.
    """
    with conn.transaction():
        conn.execute(
            "INSERT INTO visits (id, patient_id, latest_obs_id, patient_label, latest_obs_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET patient_label = COALESCE(EXCLUDED.patient_label, visits.patient_label), "
            "latest_obs_id = CASE WHEN visits.latest_obs_at IS NULL OR EXCLUDED.latest_obs_at IS NULL "
            "OR EXCLUDED.latest_obs_at >= visits.latest_obs_at THEN EXCLUDED.latest_obs_id "
            "ELSE visits.latest_obs_id END, "
            "latest_obs_at = CASE WHEN visits.latest_obs_at IS NULL OR EXCLUDED.latest_obs_at IS NULL "
            "OR EXCLUDED.latest_obs_at >= visits.latest_obs_at THEN COALESCE(EXCLUDED.latest_obs_at, "
            "visits.latest_obs_at) ELSE visits.latest_obs_at END",
            (visit_id, patient_id, latest_obs_id, patient_label, latest_at))
        current = conn.execute("SELECT latest_obs_id FROM visits WHERE id = %s", (visit_id,)).fetchone()
        assert current is not None   # the row was just upserted
        supersede_pending(conn, visit_id, current["latest_obs_id"])
