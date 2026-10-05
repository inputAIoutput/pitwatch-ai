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


def test_live_session_state_weather_evaluator_integration():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")

    # Ingest dry frame
    frame_dry = ReplayFrame(
        session_time=100.0,
        timestamp=datetime(2024, 7, 7, 14, 0, 0, tzinfo=timezone.utc),
        weather=WeatherTick(track_temperature=34.0, air_temperature=18.0, rainfall=0, humidity=50.0),
    )
    state.ingest_frame(frame_dry)
    current_wx = state.get_current_weather()
    assert current_wx["track_temperature"] == 34.0
    assert current_wx["crossover_status"] == "DRY_OPTIMAL"
    assert current_wx["recommended_compound"] == "MEDIUM"
    assert current_wx["thermal_drift_rate"] == 0.0

    # Ingest cooling + wet frame
    frame_rain = ReplayFrame(
        session_time=160.0,
        timestamp=datetime(2024, 7, 7, 14, 1, 0, tzinfo=timezone.utc),
        weather=WeatherTick(track_temperature=31.0, air_temperature=17.0, rainfall=1, humidity=75.0),
    )
    state.ingest_frame(frame_rain)
    updated_wx = state.get_current_weather()
    assert updated_wx["rainfall"] == 1
    assert updated_wx["thermal_drift_rate"] < 0.0
    assert updated_wx["crossover_status"] == "SLICK_TO_INTERMEDIATE"
    assert updated_wx["recommended_compound"] == "INTERMEDIATE"
    assert updated_wx["active_alert"] is not None


def test_load_positions_and_real_race_position_tracking():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    state.load_drivers([
        {"driver_number": 4, "name_acronym": "NOR", "team_name": "McLaren"},
        {"driver_number": 81, "name_acronym": "PIA", "team_name": "McLaren"},
    ])
    positions_data = [
        {"session_key": 9558, "driver_number": 4, "date": "2024-07-07T14:03:00+00:00", "position": 3},
        {"session_key": 9558, "driver_number": 81, "date": "2024-07-07T14:03:00+00:00", "position": 5},
        # Lap 1 transition: Norris drops to 4, Piastri drops to 6
        {"session_key": 9558, "driver_number": 4, "date": "2024-07-07T14:04:30+00:00", "position": 4},
        {"session_key": 9558, "driver_number": 81, "date": "2024-07-07T14:04:30+00:00", "position": 6},
    ]
    state.load_positions(positions_data)

    assert state.drivers[4].current_position == 3
    assert state.drivers[81].current_position == 5

    # Ingest frame at 14:05:00
    frame = ReplayFrame(
        session_time=120.0,
        timestamp=datetime(2024, 7, 7, 14, 5, 0, tzinfo=timezone.utc),
        positions=[
            CarPositionTick(driver_number=4, x=100.0, y=100.0, progress=0.85),
            CarPositionTick(driver_number=81, x=80.0, y=80.0, progress=0.80),
        ],
    )
    state.ingest_frame(frame)

    assert state.drivers[4].current_position == 4
    assert state.drivers[81].current_position == 6

    summary = state.get_session_summary()
    assert summary["drivers"][0]["driver_code"] == "NOR"
    assert summary["drivers"][0]["current_position"] == 4
    assert summary["drivers"][1]["driver_code"] == "PIA"
    assert summary["drivers"][1]["current_position"] == 6


def test_live_position_progress_auto_calculated_from_coordinates():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")

    # Ingest a position tick without progress (progress=None)
    frame1 = ReplayFrame(
        session_time=10.0,
        timestamp=datetime.now(timezone.utc),
        positions=[
            CarPositionTick(driver_number=3, x=0.0, y=-5200.0, progress=None),  # S/F straight
        ],
    )
    state.ingest_frame(frame1)

    norm_pos1 = state.get_normalized_position(3)
    assert norm_pos1 is not None
    assert norm_pos1["progress"] is not None
    assert 0.0 <= norm_pos1["progress"] <= 0.05

    # Move forward down the track towards Turn 4
    frame2 = ReplayFrame(
        session_time=15.0,
        timestamp=datetime.now(timezone.utc),
        positions=[
            CarPositionTick(driver_number=3, x=-1400.0, y=-1100.0, progress=None),  # Turn 4
        ],
    )
    state.ingest_frame(frame2)

    norm_pos2 = state.get_normalized_position(3)
    assert norm_pos2 is not None
    assert norm_pos2["progress"] > norm_pos1["progress"]
    assert 0.15 <= norm_pos2["progress"] <= 0.35


def test_centralized_fastest_lap_tracking_and_formatting():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.register_driver(driver_number=12, driver_code="ANT", team_name="Mercedes", team_colour="00D7B6")
    state.register_driver(driver_number=3, driver_code="VER", team_name="Red Bull Racing", team_colour="4781D7")

    # Lap 1: Verstappen sets 112.500
    state.drivers[3].set_compound("INTERMEDIATE")
    state._check_update_fastest_lap(driver_number=3, lap_time=112.500, lap_number=1)
    assert state.fastest_lap is not None
    assert state.fastest_lap.driver_number == 3
    assert state.fastest_lap.driver_code == "VER"
    assert state.fastest_lap.lap_time == 112.500
    assert state.fastest_lap.lap_time_formatted == "01:52.500"

    # Lap 2: Antonelli beats it with 108.702 (Session benchmark)
    state.drivers[12].set_compound("INTERMEDIATE")
    state._check_update_fastest_lap(driver_number=12, lap_time=108.702, lap_number=4)
    assert state.fastest_lap.driver_number == 12
    assert state.fastest_lap.driver_code == "ANT"
    assert state.fastest_lap.lap_time == 108.702
    assert state.fastest_lap.lap_time_formatted == "01:48.702"
    assert state.fastest_lap.lap_number == 4

    # Lap 3: Slower lap does not overwrite
    state._check_update_fastest_lap(driver_number=3, lap_time=109.100, lap_number=5)
    assert state.fastest_lap.driver_number == 12

    # Check summary contains fastest_lap and formatted driver strings
    summary = state.get_session_summary()
    assert summary["fastest_lap"] is not None
    assert summary["fastest_lap"]["driver_code"] == "ANT"
    assert summary["fastest_lap"]["lap_time_formatted"] == "01:48.702"

    ant_meta = next(d for d in summary["drivers"] if d["driver_number"] == 12)
    assert "last_lap_time_formatted" in ant_meta
    assert "gap_to_leader_formatted" in ant_meta
    assert "interval_ahead_formatted" in ant_meta


def test_safety_car_and_medical_car_not_registered_as_drivers():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.register_driver(driver_number=3, driver_code="VER")

    # Ingest frame containing Safety Car (243) and Medical Car (242)
    frame = ReplayFrame(
        session_time=200.0,
        timestamp=datetime.now(timezone.utc),
        positions=[
            CarPositionTick(driver_number=3, x=100.0, y=100.0, progress=0.50),
            CarPositionTick(driver_number=243, x=95.0, y=95.0, progress=0.49),
            CarPositionTick(driver_number=242, x=90.0, y=90.0, progress=0.48),
        ],
    )
    state.ingest_frame(frame)

    assert 3 in state.drivers
    assert 243 not in state.drivers
    assert 242 not in state.drivers
    assert len(state.leaderboard) == 1
    assert state.leaderboard[0].driver_number == 3

    summary = state.get_session_summary()
    assert summary["total_drivers"] == 1
    assert all(d["driver_number"] < 100 for d in summary["drivers"])


def test_total_drivers_and_retirement_tracking():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    for d_no in (3, 12, 63, 6, 44, 16, 81, 4, 30, 14, 27, 41, 18, 87, 43, 31, 10, 5, 23, 11, 77, 55):
        state.register_driver(driver_number=d_no)

    assert len(state.drivers) == 22
    assert state.get_session_summary()["total_drivers"] == 22

    # Albon (23) stops, Bottas (77) retires
    state.update_timing_line("23", {"Status": "Stopped", "Stopped": True})
    state.update_timing_line("77", {"Status": "Retired", "Retired": True})

    assert state.drivers[23].is_retired is True
    assert state.drivers[77].is_retired is True

    summary = state.get_session_summary()
    assert summary["total_drivers"] == 20

    # In leaderboard, retired drivers are sorted to the back
    state._recalculate_leaderboard()
    assert state.leaderboard[-2].driver_number in (23, 77)
    assert state.leaderboard[-1].driver_number in (23, 77)


def test_fastest_lap_safety_net_fallback():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.register_driver(driver_number=3, driver_code="VER")
    state.register_driver(driver_number=44, driver_code="HAM")

    # Set lap times on drivers without calling _check_update_fastest_lap
    state.drivers[3].last_lap_time = 100.275
    state.drivers[44].last_lap_time = 99.178
    assert state.fastest_lap is None

    # Calling get_session_summary triggers safety net
    summary = state.get_session_summary()
    assert summary["fastest_lap"] is not None
    assert summary["fastest_lap"]["driver_code"] == "HAM"
    assert summary["fastest_lap"]["lap_time"] == 99.178
    assert summary["fastest_lap"]["lap_time_formatted"] == "01:39.178"


def test_timing_data_dict_position_and_ordering():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.register_driver(driver_number=81, driver_code="PIA", grid_position=4)
    state.register_driver(driver_number=4, driver_code="NOR", grid_position=5)

    assert state.drivers[81].current_position == 4
    assert state.drivers[4].current_position == 5

    # LiveF1 delivers position as {"Value": "7"}
    state.update_timing_line("81", {"Position": {"Value": "7"}})
    state.update_timing_line("4", {"Position": {"Value": "8"}})

    assert state.drivers[81].current_position == 7
    assert state.drivers[4].current_position == 8


def test_tyre_age_total_laps_parsing():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.register_driver(driver_number=81, driver_code="PIA")

    assert state.drivers[81].tyre_age_laps == 0

    # TimingAppData format with Stints containing TotalLaps
    payload = {
        "Lines": {
            "81": {
                "Stints": [
                    {
                        "Compound": "MEDIUM",
                        "TotalLaps": 12,
                        "StartLaps": 0,
                    },
                    {
                        "Compound": "HARD",
                        "TotalLaps": 24,
                        "StartLaps": 0,
                    }
                ]
            }
        }
    }
    state.update_timing_app_data(payload)

    assert state.drivers[81].current_compound.value == "HARD"
    assert state.drivers[81].tyre_age_laps == 24


def test_drs_overtake_logic_and_delta_detection():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.register_driver(driver_number=1, driver_code="VER")
    state.register_driver(driver_number=44, driver_code="HAM")

    # Both drivers active, HAM behind VER with delta 0.8s
    state.drivers[1].current_position = 1
    state.drivers[44].current_position = 2
    state.drivers[44].interval_ahead = 0.8
    state.drivers[44].gap_to_leader = 0.8

    # HAM telemetry: full throttle and high gear
    state.drivers[44].latest_telemetry = TelemetryTick(
        driver_number=44, speed=320, gear=7, throttle=98, brake=0, drs=0
    )

    # 1. Before Overtake enabled by Race Director
    state._recalculate_leaderboard()
    assert state.drivers[44].latest_telemetry.drs == 0

    # 2. Race Director enables Overtake
    state.add_race_control_message({"Message": "OVERTAKE ENABLED"})
    assert state.overtake_enabled is True

    state._recalculate_leaderboard()
    assert state.drivers[44].latest_telemetry.drs == 1

    # 3. Race Director disables Overtake (e.g. Safety Car or Yellow flag)
    state.add_race_control_message({"Message": "OVERTAKE DISABLED"})
    assert state.overtake_enabled is False

    state._recalculate_leaderboard()
    assert state.drivers[44].latest_telemetry.drs == 0


def test_piastri_p6_leaderboard_sorting_accuracy():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.register_driver(driver_number=1, driver_code="VER")
    state.register_driver(driver_number=81, driver_code="PIA")
    state.register_driver(driver_number=4, driver_code="NOR")

    # Live timing assigns official positions: VER P1, NOR P5, PIA P6
    state.update_timing_line("1", {"Position": "1", "GapToLeader": "LEADER", "NumberOfLaps": 55})
    state.update_timing_line("4", {"Position": "5", "GapToLeader": "+8.571", "NumberOfLaps": 55})
    state.update_timing_line("81", {"Position": "6", "GapToLeader": "+9.454", "NumberOfLaps": 55})

    state._recalculate_leaderboard()
    codes = [entry.driver_code for entry in state.leaderboard]
    assert codes == ["VER", "NOR", "PIA"]
    assert state.leaderboard[2].driver_code == "PIA"
    assert state.leaderboard[2].position == 6


@pytest.mark.asyncio
async def test_historical_replay_from_livetiming_construct():
    from pitwatch.ingestion.replay import HistoricalReplaySource
    # Test constructing replay source with max_frames limit
    source = await HistoricalReplaySource.from_livetiming(session_key=11731, max_frames=5)
    assert source is not None
    assert len(source.frames) <= 5
    assert source.time_step == 0.2


def test_pit_stop_tracking_and_monotonic_gap_sorting():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    for d in (3, 12, 63, 1, 6, 44, 81):
        state.register_driver(d)

    # Ingest TimingData with pit stop and in-pit status
    state.update_timing_line("1", {"NumberOfLaps": 33, "GapToLeader": "+23.832", "InPit": True, "NumberOfPitStops": 2})
    state.update_timing_line("3", {"NumberOfLaps": 33, "GapToLeader": "LEADER", "Position": "1"})
    state.update_timing_line("12", {"NumberOfLaps": 33, "GapToLeader": "+10.981", "Position": "2"})
    state.update_timing_line("63", {"NumberOfLaps": 33, "GapToLeader": "+14.105", "Position": "3"})
    state.update_timing_line("6", {"NumberOfLaps": 33, "GapToLeader": "+24.416", "Position": "4"})
    state.update_timing_line("44", {"NumberOfLaps": 33, "GapToLeader": "+24.881", "Position": "5"})
    state.update_timing_line("81", {"NumberOfLaps": 33, "GapToLeader": "+47.525", "Position": "6"})

    state._recalculate_leaderboard()

    # Check driver 1 pit status
    assert state.drivers[1].in_pit is True
    assert state.drivers[1].pit_stops == 2

    # Check leaderboard order follows gap to leader
    driver_order = [e.driver_number for e in state.leaderboard]
    assert driver_order == [3, 12, 63, 1, 6, 44, 81]

    # Verify positions and gaps in session summary
    summary = state.get_session_summary()
    d_map = {d["driver_number"]: d for d in summary["drivers"]}
    assert d_map[1]["in_pit"] is True
    assert d_map[1]["pit_stops"] == 2
    assert d_map[81]["in_pit"] is False

    gaps = [d["gap_to_leader"] for d in summary["drivers"] if d["driver_number"] in driver_order]
    assert gaps == sorted(gaps)


def test_tyre_age_accumulation_across_laps_and_stints():
    state = LiveSessionState(session_key=11731, circuit_name="Sepang")
    state.register_driver(driver_number=1, driver_code="VER")

    # 1. Starting stint on INTERMEDIATE, TotalLaps: 0
    state.update_timing_app_data({
        "Lines": {
            "1": {
                "Stints": {
                    "0": {"Compound": "INTERMEDIATE", "TotalLaps": 0, "StartLaps": 0}
                }
            }
        }
    })
    assert state.drivers[1].current_compound.value == "INTERMEDIATE"
    assert state.drivers[1].tyre_age_laps == 0

    # 2. TimingData reports lap 1, lap 2, lap 3 completion
    state.update_timing_line("1", {"NumberOfLaps": 1})
    assert state.drivers[1].current_lap == 1

    state.update_timing_line("1", {"NumberOfLaps": 2})
    assert state.drivers[1].current_lap == 2
    assert state.drivers[1].tyre_age_laps == 1  # 1 completed lap on this set

    state.update_timing_line("1", {"NumberOfLaps": 3})
    assert state.drivers[1].current_lap == 3
    assert state.drivers[1].tyre_age_laps == 2

    # 3. TimingAppData micro-update arrives with official TotalLaps: 2
    state.update_timing_app_data({
        "Lines": {
            "1": {
                "Stints": {
                    "0": {"TotalLaps": 2}
                }
            }
        }
    })
    assert state.drivers[1].current_compound.value == "INTERMEDIATE"
    assert state.drivers[1].tyre_age_laps == 2

    # 4. Driver pits for HARD tyres (Stint 1)
    state.update_timing_app_data({
        "Lines": {
            "1": {
                "Stints": {
                    "1": {"Compound": "HARD", "TotalLaps": 0, "StartLaps": 0}
                }
            }
        }
    })
    assert state.drivers[1].pit_stops == 1
    assert state.drivers[1].current_compound.value == "HARD"
    assert state.drivers[1].tyre_age_laps == 0

    # 5. Subsequent micro-update sends LapTime without TotalLaps — tyre age must NOT be wiped!
    state.update_timing_app_data({
        "Lines": {
            "1": {
                "Stints": {
                    "1": {"LapTime": "1:40.123"}
                }
            }
        }
    })
    assert state.drivers[1].current_compound.value == "HARD"
    assert state.drivers[1].tyre_age_laps == 0

    # 6. Official TotalLaps updates to 1
    state.update_timing_app_data({
        "Lines": {
            "1": {
                "Stints": {
                    "1": {"TotalLaps": 1}
                }
            }
        }
    })
    assert state.drivers[1].tyre_age_laps == 1






