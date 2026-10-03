from datetime import datetime, timezone
import pytest
from pitwatch.models.frame import CarPositionTick, ReplayFrame
from pitwatch.state.session import LiveSessionState


def test_e2e_abu_dhabi_undercut_threat_matrix():
    # 2024 Abu Dhabi GP: Norris (4) leading Verstappen (1), pure dry tactical race
    state = LiveSessionState(session_key=9662, circuit_name="Abu Dhabi")
    state.load_drivers([
        {"driver_number": 4, "name_acronym": "NOR", "team_name": "McLaren", "team_colour": "FF8000"},
        {"driver_number": 1, "name_acronym": "VER", "team_name": "Red Bull Racing", "team_colour": "3671C6"},
    ])
    state.load_stints([
        {"driver_number": 4, "stint_number": 1, "lap_start": 1, "lap_end": 20, "compound": "MEDIUM", "tyre_age_at_start": 0},
        {"driver_number": 1, "stint_number": 1, "lap_start": 1, "lap_end": 19, "compound": "MEDIUM", "tyre_age_at_start": 0},
    ])

    # Advance drivers to lap 18 of 58
    state.drivers[4].current_lap = 18
    state.drivers[1].current_lap = 18
    state._apply_stint_for_driver(4)
    state._apply_stint_for_driver(1)

    # Lap 18 at Yas Marina: Norris leads Verstappen by ~1.2s (critical undercut window before pit stop)
    # Difference of 1.2s / 90.0s lap = 0.0133 progress delta
    frame = ReplayFrame(
        session_time=1650.0,
        timestamp=datetime(2024, 12, 8, 13, 27, 30, tzinfo=timezone.utc),
        positions=[
            CarPositionTick(driver_number=4, x=150.0, y=250.0, progress=0.88),
            CarPositionTick(driver_number=1, x=135.0, y=235.0, progress=0.8667),
        ],
    )
    state.ingest_frame(frame)

    matrix = state.get_threat_matrix()
    assert matrix["circuit_name"] == "Abu Dhabi"
    assert matrix["pit_transit_loss_seconds"] == 22.0
    assert matrix["total_laps"] == 58

    nor_threat = matrix["competitors"][0]["undercut_threat"]
    assert nor_threat is not None
    assert nor_threat["undercut_feasible"] is True
    assert nor_threat["threat_level"] in ("CRITICAL", "MODERATE")
    assert "BOX TO DEFEND" in nor_threat["recommended_action"] or "MONITOR" in nor_threat["recommended_action"]

    # Rejoin clearance check
    clearance = matrix["competitors"][0]["pit_window_clearance"]
    assert clearance["pit_loss_seconds"] == 22.0
