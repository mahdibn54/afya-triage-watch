"""E2-4: native WSO2 projection stays minimal and preserves quantity associations."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from afya_api.fhir_projection import FHIRPATHS, PANEL_PATH, quantity_path, restore_response
from afya_api.investigate import trim_observation
from afya_api.mcp_client import McpGateway


def projected():
    return {"resourceType": "Observation", "id": "7", "encounter.reference": "Encounter/v1",
            "effectiveDateTime": "2000-01-01T00:00:00Z", PANEL_PATH: "85353-1",
            quantity_path("8867-4", "value"): [105],
            quantity_path("8867-4", "system"): ["http://unitsofmeasure.org"],
            quantity_path("8867-4", "code"): ["/min"],
            quantity_path("8310-5", "value"): [37.2],
            quantity_path("8310-5", "system"): ["http://unitsofmeasure.org"],
            quantity_path("8310-5", "code"): ["Cel"]}


def test_projection_restores_search_and_read_without_free_text():
    row = projected()
    row.update(note=[{"text": "DO NOT PASS"}], text={"div": "DO NOT PASS"},
               **{"component.valueQuantity.unit": ["DO NOT PASS"]})
    read = restore_response("read", row)
    search = restore_response("search", {"type": "searchset", "entry": [row]})
    assert search == {"resourceType": "Bundle", "entry": [{"resource": read}]}
    assert read["encounter"] == {"reference": "Encounter/v1"}
    assert trim_observation(read) == {"id": "Observation/7", "time": "2000-01-01T00:00:00Z",
                                      "values": [{"code": "8867-4", "value": 105, "unit": "/min"},
                                                 {"code": "8310-5", "value": 37.2, "unit": "Cel"}]}
    assert "DO NOT PASS" not in str(read)


def test_partial_quantities_never_shift_a_value_onto_another_code():
    row = projected()
    del row[quantity_path("8867-4", "code")]
    row[quantity_path("9279-1", "code")] = ["/min"]  # a different component with no value
    values = trim_observation(restore_response("read", row))["values"]
    assert values == [{"code": "8867-4", "value": 105, "unit": None},
                      {"code": "8310-5", "value": 37.2, "unit": "Cel"}]


@pytest.mark.parametrize("bad", [[True], ["105 bpm"], ["NaN"], [" 105"], ["1e999"],
                                [float("nan")], [float("inf")], [105, 106]])
def test_non_numeric_or_ambiguous_quantities_are_not_reconstructed(bad):
    row = projected()
    row[quantity_path("8867-4", "value")] = bad
    assert [v["code"] for v in trim_observation(restore_response("read", row))["values"]] == ["8310-5"]


def test_pinned_wso2_decimal_strings_are_restored_to_numeric_values():
    row = projected()
    row[quantity_path("8867-4", "value")] = ["105.0"]
    row[quantity_path("8310-5", "value")] = ["37.2"]
    values = trim_observation(restore_response("read", row))["values"]
    assert values == [{"code": "8867-4", "value": 105.0, "unit": "/min"},
                      {"code": "8310-5", "value": 37.2, "unit": "Cel"}]


def test_filter_errors_and_unfiltered_payloads_fail_closed():
    with pytest.raises(ValueError):
        restore_response("read", {**projected(), "_errors": ["Observation.bad()"]})
    with pytest.raises(ValueError):
        restore_response("read", {"resourceType": "Observation", "id": "7", "component": [{"note": "raw"}]})
    assert restore_response("search", {"type": "searchset", "entry": []})["entry"] == []
    assert restore_response("search", {"type": "searchset"})["entry"] == []


def test_gateway_enforces_native_filter_for_both_tools():
    async def check():
        gw = McpGateway()
        for tool, args, response in [
            ("read", {"type": "Observation", "id": "7"}, projected()),
            ("search", {"type": "Observation", "searchParam": {"_count": "1"}},
             {"type": "searchset", "entry": [projected()]}),
        ]:
            gw._call = AsyncMock(return_value=response)
            supplied = {**args, "response_filter_fhirpaths": ["Observation.note"]}
            await gw.wso2(tool, supplied)
            gw._call.assert_awaited_once_with("wso2", tool, {**args, "response_filter_fhirpaths": list(FHIRPATHS)})
            assert supplied["response_filter_fhirpaths"] == ["Observation.note"]
    asyncio.run(check())
