"""Which database the DB-backed tests may use (E12-2).

The tests write rows they cannot delete (afya_app has no DELETE), so they never run against the database the stack
uses. Order: TEST_DATABASE_URL (the `afya_test` database that db-init creates next to `afya`; evals/stack_env.sh
exports it), else DATABASE_URL when its database is not the stack's `afya`, else no database (the tests skip).
The chosen URL is put in DATABASE_URL, which is what afya_mcp.db.connect reads.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

PROTECTED = {"afya"}


def select() -> str | None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        url = os.environ.get("DATABASE_URL")
        if url and urlparse(url).path.lstrip("/").split("?")[0] in PROTECTED:
            url = None
    if url:
        os.environ["DATABASE_URL"] = url
    else:
        os.environ.pop("DATABASE_URL", None)
    return url
