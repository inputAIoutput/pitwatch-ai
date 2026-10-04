import pytest
from pitwatch.state.timing import (
    format_lap_time,
    format_gap,
    format_interval,
    FastestLapRecord,
)


def test_format_lap_time():
    assert format_lap_time(110.519) == "01:50.519"
    assert format_lap_time(68.204) == "01:08.204"
    assert format_lap_time(59.999) == "00:59.999"
    assert format_lap_time(125.0) == "02:05.000"
    assert format_lap_time(None) is None
    assert format_lap_time(0.0) is None
    assert format_lap_time(-5.0) is None


def test_format_gap():
    assert format_gap(0.0, position=1) == "LEADER"
    assert format_gap(None, position=1) == "LEADER"
    assert format_gap(2.438, position=2) == "+2.438"
    assert format_gap(0.5, position=3) == "+0.500"
    assert format_gap(61.929, position=5) == "+1:01.929"
    assert format_gap(125.450, position=10) == "+2:05.450"


def test_format_interval():
    assert format_interval(0.0, position=1) == "-"
    assert format_interval(None, position=1) == "-"
    assert format_interval(0.584, position=2) == "+0.584"
    assert format_interval(3.112, position=4) == "+3.112"
    assert format_interval(62.100, position=8) == "+1:02.100"


def test_fastest_lap_record_model():
    rec = FastestLapRecord(
        driver_number=12,
        driver_code="ANT",
        team_name="Mercedes",
        team_colour="00D7B6",
        lap_number=4,
        lap_time=108.702,
        lap_time_formatted="01:48.702",
        compound="INTERMEDIATE",
        recorded_at_session_time=942.5,
    )
    assert rec.driver_code == "ANT"
    assert rec.lap_time == 108.702
    assert rec.lap_time_formatted == "01:48.702"
    d = rec.model_dump()
    assert d["compound"] == "INTERMEDIATE"
    assert d["recorded_at_session_time"] == 942.5
