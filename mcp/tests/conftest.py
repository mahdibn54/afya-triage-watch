"""DB-backed tests use the separate test database (see dbselect.py).

E13-3: afya-mcp's mounts accept tokens of the test issuer only, verified with a local key (oauth_fixture.py): no
authorization server and no network are needed (the model-off, offline test path)."""
import os

import dbselect

import oauth_fixture

dbselect.select()

os.environ["AFYA_AUTH_ISSUER"] = oauth_fixture.ISSUER
os.environ["AFYA_MCP_RESOURCE_BASE"] = oauth_fixture.BASE
os.environ.pop("AFYA_AUTH_CA_FILE", None)

from afya_mcp import auth  # noqa: E402  (after the environment above: settings() is read once)

auth.settings.cache_clear()
auth._keys = lambda: oauth_fixture.LocalKeys()
