"""Deterministic cases through real MCP/FHIR and the real checkpointed agent, without a live model."""
import pytest
from conftest import BASE, ORANGE, YELLOW, run
from fake_model import ScriptedBackend, decision, signs_reply, tool_call


@pytest.mark.parametrize("name,colour,first,last,want", [
    ("stable", "GREEN", BASE, BASE, None),
    ("small rise B-B2", "GREEN", BASE, {**BASE, "heart_rate": 105}, None),
    ("mixed M1-M2", "GREEN", {**BASE, "heart_rate": 105}, {**BASE, "resp_rate": 16}, None),
    ("improvement", "ORANGE", ORANGE, BASE, None),
    ("colour rise", "YELLOW", YELLOW, ORANGE, "ORANGE"),
    ("confused sign", "GREEN", BASE, {**BASE, "consciousness": "confused"}, "ORANGE"),
    ("missing mobility", "GREEN", BASE, {k: v for k, v in BASE.items() if k != "mobility"}, None),
])
def test_fixed_cases(stack, name, colour, first, last, want):
    async def check():
        visit = await stack.visit(colour)
        await stack.record(visit, first)
        saved = await stack.record(visit, last)
        assert saved["status"] == "saved", name
        scored = await stack.gw.read("compute_tews", {"observation_id": saved["observation_id"]})
        if name == "missing mobility":
            assert scored["missing"] == ["mobility"] and not scored["complete"]
        result = await stack.run(visit, saved["observation_id"])
        assert result["status"] == ("paused" if want else "ended"), result
        props = stack.props(visit)
        assert [p["payload"]["to_colour"] for p in props] == ([want] if want else [])
        stack.untouched(visit, colour)
        audit = stack.query("SELECT kind FROM audit_log WHERE run_id=%s", (result["run_id"],))
        assert {"compute_tews", "check_deterioration"} <= {a["kind"] for a in audit}
    run(check())


def test_unconfirmed_first_visit_and_child(stack):
    async def check():
        visit = await stack.visit(None)
        saved = await stack.record(visit, {**BASE, "resp_rate": 30, "heart_rate": 135, "mobility": "with_help"})
        result = await stack.run(visit, saved["observation_id"])
        assert result["status"] == "ended" and not stack.props(visit)
        stack.untouched(visit, None)
        child = await stack.visit(age=8)
        saved = await stack.record(child, BASE)
        scored = await stack.gw.read("compute_tews", {"observation_id": saved["observation_id"]})
        assert scored["status"] == "no_chart"
        result = await stack.run(child, saved["observation_id"])
        assert result["stop"] == "no_chart"
        stack.untouched(child, "GREEN")
    run(check())


@pytest.mark.parametrize("changes", [{"heart_rate": 400}, {"temperature": 101.0}])
def test_impossible_input_saves_nothing(stack, changes):
    async def check():
        visit = await stack.visit()
        saved = await stack.record(visit, {**BASE, **changes})
        assert saved["status"] == "remeasure" and not saved["saved"]
        response = stack.fhir.get("Observation", params={"encounter": f"Encounter/{visit}"})
        assert not response.json().get("entry")
        assert not stack.props(visit)
        stack.untouched(visit, "GREEN")
    run(check())


def test_model_outage_still_proposes_and_duplicate_run_does_not_duplicate(stack):
    async def check():
        visit = await stack.visit("YELLOW")
        await stack.record(visit, YELLOW)
        saved = await stack.record(visit, ORANGE, "No new symptoms.")
        backend = ScriptedBackend()  # raises a connection error at the model boundary
        first = await stack.run(visit, saved["observation_id"], backend)
        assert first["status"] == "paused"
        props = stack.props(visit)
        assert len(props) == 1 and props[0]["payload"]["to_colour"] == "ORANGE"
        assert "model_unavailable" in {n["code"] for n in props[0]["payload"]["notices"]}
        again = await stack.run(visit, saved["observation_id"])
        assert again["status"] == "already_ran" and len(stack.props(visit)) == 1
        from afya_mcp import db, workflow
        with db.connect() as conn:
            p = props[0]
            assert workflow.insert_proposal(conn, visit, p["trigger"], p["obs_id"],
                                            p["evidence_hash"], p["payload"]) is None
        stack.untouched(visit, "YELLOW")
    run(check())


def test_forged_model_write_tool_is_refused_by_real_toolnode(stack):
    async def check():
        visit = await stack.visit("YELLOW")
        await stack.record(visit, YELLOW)
        saved = await stack.record(visit, ORANGE, "No new symptoms.")
        backend = ScriptedBackend().script("map_signs", signs_reply("none"))
        backend.script("investigate", tool_call("raise_recheck_flag", command_id="forged", actor="nurse-a"), decision())
        result = await stack.run(visit, saved["observation_id"], backend)
        assert result["status"] == "paused"
        rows = stack.query("SELECT payload FROM audit_log WHERE run_id=%s AND kind='agent_step'", (result["run_id"],))
        assert any(r["payload"]["name"] == "raise_recheck_flag"
                   and r["payload"]["result_summary"].startswith("refused") for r in rows)
        turns = [s for s in backend.seen if s["purpose"] == "investigate"]
        assert any(m["role"] == "tool" and "not a valid tool" in m["content"] for m in turns[1]["messages"])
        stack.untouched(visit, "YELLOW")
    run(check())


def test_fhir_outage_retries_three_times_warns_and_resumes(stack):
    async def check():
        visit = await stack.visit("YELLOW")
        await stack.record(visit, YELLOW)
        saved = await stack.record(visit, ORANGE)
        stack.fault("unavailable", "GET", "/fhir/" + saved["observation_id"], 3)
        result = await stack.run(visit, saved["observation_id"])
        assert result["status"] == "failed", result
        assert stack.control.get("/control").json()["matched"] == 3
        assert stack.query("SELECT id FROM notifications WHERE visit_id=%s AND kind='agent_failed'", (visit,))
        assert not stack.props(visit)
        stack.fault()
        resumed = await stack.run(visit, saved["observation_id"])
        assert resumed["status"] == "paused" and resumed["resumed"]
        stack.untouched(visit, "YELLOW")
    run(check())
