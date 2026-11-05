"""PostgreSQL access for afya-mcp (psycopg 3, role afya_app).

Connections follow the runtime rules from the DB audit: autocommit, dict rows, no prepared statements
(prepare_threshold=0, so a pooler in front would also work). Statements that must be atomic open an explicit
`with conn.transaction():` block. The application never creates tables: db-init and lg-init own the DDL.

`VisitStore` is the small interface the services use. `PgVisitStore` is the real one; tests inject a fake.
"""
from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

from .workflow import supersede_pending


def connect(url: str | None = None) -> psycopg.Connection:
    """One autocommit connection. DATABASE_URL points at afya_app (search_path afya, lg is set on the role)."""
    return psycopg.connect(url or os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row,
                           prepare_threshold=0)


class VisitStore(Protocol):
    def record_reading(self, visit_id: str, patient_id: str, latest_obs_id: str) -> None:
        """Upsert the visit and set latest_obs_id; older pending proposals become superseded (same transaction)."""


class PgVisitStore:
    """Opens a short-lived connection per call: afya-mcp calls are infrequent and run in worker threads."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url

    @contextlib.contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with connect(self.url) as conn:
            yield conn

    def record_reading(self, visit_id: str, patient_id: str, latest_obs_id: str) -> None:
        with self.connection() as conn:
            upsert_visit(conn, visit_id, patient_id, latest_obs_id)


def upsert_visit(conn: psycopg.Connection, visit_id: str, patient_id: str, latest_obs_id: str) -> None:
    """E4-2 (DB part): visit row and latest reading in one transaction. A visit never changes patient.

    Proposals still pending for an older reading are superseded here (reviewed stays false, so an unread one stays
    visible as "not reviewed"); the claim query already fails for commands whose reading is no longer the latest.
    """
    with conn.transaction():
        conn.execute(
            "INSERT INTO visits (id, patient_id, latest_obs_id) VALUES (%s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET latest_obs_id = EXCLUDED.latest_obs_id",
            (visit_id, patient_id, latest_obs_id))
        supersede_pending(conn, visit_id, latest_obs_id)
