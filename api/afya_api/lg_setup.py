"""One-shot (service lg-init): create the LangGraph checkpoint tables in schema `lg` as afya_owner.

Default privileges set by db/schema.sql give afya_app read/write on these tables, never DDL.
"""
import os

from langgraph.checkpoint.postgres import PostgresSaver


def main() -> None:
    # the app database, and the separate test database when the compose file names one
    for var in ("OWNER_DATABASE_URL", "OWNER_TEST_DATABASE_URL"):
        if os.environ.get(var):
            with PostgresSaver.from_conn_string(os.environ[var] + "?options=-csearch_path%3Dlg") as saver:
                saver.setup()
    print("lg-init: checkpoint tables ready")


if __name__ == "__main__":
    main()
