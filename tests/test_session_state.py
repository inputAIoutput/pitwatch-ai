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


def test_load_drivers_and_stints():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    drivers_data = [
        {
            "driver_number": 44,
            "name_acronym": "HAM",
            "team_name": "Mercedes",
            "team_colour": "27F4D2",
        },
        {
            "driver_number": 1,
            "name_acronym": "VER",
            "team_name": "Red Bull Racing",
            "team_colour": "3671C6",
        },
    ]
    stints_data = [
        {
            "driver_number": 44,
            "stint_number": 1,
            "lap_start": 1,
            "lap_end": 27,
            "compound": "MEDIUM",
            "tyre_age_at_start": 0,
        },
        {
            "driver_number": 1,
            "stint_number": 1,
            "lap_start": 1,
            "lap_end": 26,
            "compound": "MEDIUM",
            "tyre_age_at_start": 0,
        },
    ]
    state.load_drivers(drivers_data)
    state.load_stints(stints_data)

    assert len(state.drivers) == 2
    ham = state.drivers[44]
    assert ham.driver_code == "HAM"
    assert ham.team_name == "Mercedes"
    assert ham.team_colour == "27F4D2"
    assert ham.current_compound.value == "MEDIUM"
    assert ham.tyre_age_laps == 0


def test_lap_completion_updates_last_lap_and_tyre_age():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    state.load_drivers([
        {"driver_number": 44, "name_acronym": "HAM", "team_name": "Mercedes", "team_colour": "27F4D2"}
    ])
    state.load_stints([
        {"driver_number": 44, "stint_number": 1, "lap_start": 1, "lap_end": 2, "compound": "MEDIUM", "tyre_age_at_start": 0},
        {"driver_number": 44, "stint_number": 2, "lap_start": 3, "lap_end": 10, "compound": "INTERMEDIATE", "tyre_age_at_start": 0},
    ])
    state.load_laps([
        {
            "driver_number": 44,
            "lap_number": 1,
            "date_start": "2024-07-07T14:00:00.000000+00:00",
            "lap_duration": 90.0,
        },
        {
            "driver_number": 44,
            "lap_number": 2,
            "date_start": "2024-07-07T14:01:30.000000+00:00",
            "lap_duration": 92.0,
        },
    ])

    # 1. Frame during Lap 1 (at 14:00:45 -> before lap 1 end)
    frame_mid_lap1 = ReplayFrame(
        session_time=45.0,
        timestamp=datetime(2024, 7, 7, 14, 0, 45, tzinfo=timezone.utc),
        positions=[CarPositionTick(driver_number=44, x=0.0, y=0.0, progress=0.5)],
    )
    state.ingest_frame(frame_mid_lap1)
    ham = state.drivers[44]
    assert ham.current_lap == 1
    assert ham.last_lap_time is None
    assert ham.tyre_age_laps == 0
    assert ham.current_compound.value == "MEDIUM"

    # 2. Frame during Lap 2 (at 14:01:35 -> Lap 1 is completed)
    frame_lap2 = ReplayFrame(
        session_time=95.0,
        timestamp=datetime(2024, 7, 7, 14, 1, 35, tzinfo=timezone.utc),
        positions=[CarPositionTick(driver_number=44, x=10.0, y=10.0, progress=0.1)],
    )
    state.ingest_frame(frame_lap2)
    assert ham.current_lap == 2
    assert ham.last_lap_time == 90.0
    assert ham.tyre_age_laps == 1
    assert ham.current_compound.value == "MEDIUM"

    # 3. Frame during Lap 3 (at 14:03:05 -> Lap 2 is completed, stint 2 INTERMEDIATE active)
    frame_lap3 = ReplayFrame(
        session_time=185.0,
        timestamp=datetime(2024, 7, 7, 14, 3, 5, tzinfo=timezone.utc),
        positions=[CarPositionTick(driver_number=44, x=20.0, y=20.0, progress=0.05)],
    )
    state.ingest_frame(frame_lap3)
    assert ham.current_lap == 3
    assert ham.last_lap_time == 92.0
    assert ham.tyre_age_laps == 0  # Lap 3 is stint 2 start lap (3 - 3 + 0 = 0)
    assert ham.current_compound.value == "INTERMEDIATE"
