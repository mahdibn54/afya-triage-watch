"""One-shot (service lg-init): create the LangGraph checkpoint tables in schema `lg` as afya_owner.

Default privileges set by db/schema.sql give afya_app read/write on these tables, never DDL.
"""
import os

from langgraph.checkpoint.postgres import PostgresSaver


def main() -> None:
    url = os.environ["OWNER_DATABASE_URL"] + "?options=-csearch_path%3Dlg"
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
    print("lg-init: checkpoint tables ready")


if __name__ == "__main__":
    main()
