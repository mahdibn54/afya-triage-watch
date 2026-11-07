"""E13-1: error text survives the mcp 2.x SDK (it keeps the text of a ToolError only)."""
import pytest


def test_anticipated_failures_keep_their_text_for_the_api():
    """E13-1: mcp 2.x hides every exception but ToolError; the api maps 'may not run' to 403 and 'HTTP 404' to 404."""
    import anyio
    from mcp.server.mcpserver.exceptions import ToolError

    from afya_mcp import audit
    from afya_mcp.fhir import FhirNotFound, FhirUnavailable
    from afya_mcp.server import _run

    def failing(exc):
        def fn():
            raise exc
        return fn

    async def text(exc):
        with pytest.raises(ToolError) as e:
            await _run(failing(exc))
        return str(e.value)

    assert "may not run" in anyio.run(text, audit.ActorRefused("actor 'x' may not run record_vitals"))
    assert anyio.run(text, FhirNotFound("GET Observation/1: HTTP 404 diagnostics with record text")) == \
        "FhirNotFound: GET Observation/1: HTTP 404"
    assert anyio.run(text, FhirUnavailable("timeout")).startswith("FhirUnavailable")

    async def crash():
        with pytest.raises(RuntimeError):      # not anticipated: passes through, the SDK keeps its text opaque
            await _run(failing(RuntimeError("secret detail")))
    anyio.run(crash)
