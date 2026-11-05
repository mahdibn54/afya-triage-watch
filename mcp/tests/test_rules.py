"""Fixtures from architecture v4.1 section 11, checked by hand against the SATS 2012 adult chart."""
import pytest

from afya_mcp.rules import (
    NoChartForPatient, band_points, is_colour_rise, load_chart, load_registry, score, select_chart,
)

CHART = load_chart()
BASE = dict(resp_rate=14, heart_rate=80, systolic_bp=120, temperature=37.0,
            mobility="walking", consciousness="alert", trauma="no")


def s(**changes):
    return score({**BASE, **changes}, CHART)


@pytest.mark.parametrize("name, changes, tews, colour", [
    ("B baseline", {}, 0, "GREEN"),
    ("B2 small rise", dict(heart_rate=105), 1, "GREEN"),
    ("M1", dict(heart_rate=105, resp_rate=14), 1, "GREEN"),
    ("M2", dict(heart_rate=80, resp_rate=16), 1, "GREEN"),
    ("Y yellow", dict(mobility="with_help", resp_rate=22), 3, "YELLOW"),
    ("O orange", dict(mobility="with_help", resp_rate=30, heart_rate=115), 6, "ORANGE"),
    ("R red", dict(mobility="with_help", resp_rate=30, heart_rate=135), 7, "RED"),
    ("T trauma", dict(trauma="yes"), 1, "GREEN"),
    ("P-014 before", dict(resp_rate=22, heart_rate=105, temperature=37.2), 3, "YELLOW"),
    ("P-014 after", dict(resp_rate=26, heart_rate=112, temperature=38.6), 6, "ORANGE"),
])
def test_fixtures(name, changes, tews, colour):
    result = s(**changes)
    assert (result.tews, result.colour) == (tews, colour), name
    assert result.complete


def test_confused_is_orange_by_sign():
    result = s(consciousness="confused")
    assert result.tews == 1
    assert result.colour_by_tews == "GREEN"
    assert result.signs == ["LOC_REDUCED_CONFUSED"]
    assert result.colour == "ORANGE"


# Band edges, written from a second, independent reading of the chart (not generated from the YAML).
@pytest.mark.parametrize("name, value, expected", [
    ("resp_rate", 8, 2), ("resp_rate", 9, 0), ("resp_rate", 14, 0), ("resp_rate", 15, 1),
    ("resp_rate", 20, 1), ("resp_rate", 21, 2), ("resp_rate", 29, 2), ("resp_rate", 30, 3),
    ("heart_rate", 40, 2), ("heart_rate", 41, 1), ("heart_rate", 50, 1), ("heart_rate", 51, 0),
    ("heart_rate", 100, 0), ("heart_rate", 101, 1), ("heart_rate", 110, 1), ("heart_rate", 111, 2),
    ("heart_rate", 129, 2), ("heart_rate", 130, 3),
    ("systolic_bp", 70, 3), ("systolic_bp", 71, 2), ("systolic_bp", 80, 2), ("systolic_bp", 81, 1),
    ("systolic_bp", 100, 1), ("systolic_bp", 101, 0), ("systolic_bp", 199, 0), ("systolic_bp", 200, 2),
    ("temperature", 34.9, 2), ("temperature", 35.0, 0), ("temperature", 38.4, 0), ("temperature", 38.5, 2),
])
def test_band_edges(name, value, expected):
    assert band_points(value, CHART["numeric"][name]["bands"]) == expected


def test_missing_value_is_never_guessed():
    values = dict(BASE)
    del values["mobility"]
    result = score(values, CHART)
    assert not result.complete
    assert result.missing == ["mobility"]
    assert "mobility" not in result.points


def test_chart_selection_adult_and_child():
    registry = load_registry()
    assert select_chart(30, None, registry)["chart_id"] == "sats_adult_2012"
    assert select_chart(None, 160, registry)["chart_id"] == "sats_adult_2012"
    with pytest.raises(NoChartForPatient):
        select_chart(8, 120, registry)


def test_colour_rise():
    assert is_colour_rise("YELLOW", "ORANGE")
    assert not is_colour_rise("ORANGE", "YELLOW")
    assert not is_colour_rise("GREEN", "GREEN")
