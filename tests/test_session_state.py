from datetime import datetime, timezone
import pytest
from pitwatch.models.frame import (
    CarPositionTick,
    TelemetryTick,
    WeatherTick,
    ReplayFrame,
)
from pitwatch.state.session import LiveSessionState
from pitwatch.state.geometry import CircuitBounds


def test_session_state_initialization():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    assert state.session_key == 9558
    assert state.circuit_name == "Silverstone"
    assert len(state.drivers) == 0
    assert len(state.leaderboard) == 0


def test_frame_ingestion_and_normalized_coordinates():
    state = LiveSessionState(
        session_key=9558,
        circuit_name="Silverstone",
        bounds=CircuitBounds(min_x=-100.0, max_x=100.0, min_y=-100.0, max_y=100.0),
    )
    # Register drivers
    state.register_driver(driver_number=44, driver_code="HAM", team_name="Mercedes")
    state.register_driver(driver_number=1, driver_code="VER", team_name="Red Bull")

    frame = ReplayFrame(
        session_time=0.2,
        timestamp=datetime.now(timezone.utc),
        positions=[
            CarPositionTick(driver_number=44, x=50.0, y=50.0, progress=0.25),
            CarPositionTick(driver_number=1, x=-50.0, y=-50.0, progress=0.22),
        ],
        telemetry=[
            TelemetryTick(driver_number=44, speed=310, gear=7, throttle=100, brake=0, drs=1),
            TelemetryTick(driver_number=1, speed=312, gear=7, throttle=100, brake=0, drs=1),
        ],
        weather=WeatherTick(track_temperature=32.0, air_temperature=20.0, rainfall=0),
    )

    state.ingest_frame(frame)

    assert state.weather is not None
    assert state.weather.track_temperature == 32.0

    # Coordinates must be strictly in [-1.0, 1.0]
    ham_pos = state.get_normalized_position(44)
    assert ham_pos is not None
    assert ham_pos["x"] == 0.5
    assert ham_pos["y"] == 0.5
    assert ham_pos["progress"] == 0.25


def test_leaderboard_sorting_and_interval_deltas():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    state.register_driver(driver_number=44, driver_code="HAM")
    state.register_driver(driver_number=1, driver_code="VER")
    state.register_driver(driver_number=4, driver_code="NOR")

    # Set lap progress metrics: HAM ahead of VER ahead of NOR
    frame = ReplayFrame(
        session_time=1.0,
        timestamp=datetime.now(timezone.utc),
        positions=[
            CarPositionTick(driver_number=44, x=10.0, y=10.0, progress=0.85),
            CarPositionTick(driver_number=1, x=5.0, y=5.0, progress=0.82),
            CarPositionTick(driver_number=4, x=0.0, y=0.0, progress=0.79),
        ],
    )
    state.ingest_frame(frame)

    leaderboard = state.get_leaderboard()
    assert len(leaderboard) == 3
    # P1: HAM, P2: VER, P3: NOR
    assert leaderboard[0].driver_number == 44
    assert leaderboard[0].position == 1
    assert leaderboard[0].gap_to_leader == 0.0

    assert leaderboard[1].driver_number == 1
    assert leaderboard[1].position == 2
    assert leaderboard[1].gap_to_leader > 0.0

    assert leaderboard[2].driver_number == 4
    assert leaderboard[2].position == 3
    assert leaderboard[2].interval_ahead > 0.0
