"""E5-1 needs a genuinely unconfirmed first visit, including a high baseline score."""
import pytest

from evals.cases import CaseError, parse_case


def test_first_visit_can_explicitly_have_no_confirmed_colour():
    raw = {"id": "first-visit", "synthetic": True, "age_years": 36, "confirmed_colour": None,
           "readings": [{"values": {"heart_rate": 135}}], "expected": {"proposal": False}}
    assert parse_case(raw).confirmed_colour is None
    del raw["confirmed_colour"]
    with pytest.raises(CaseError, match="confirmed_colour"):
        parse_case(raw)
