import pytest
from unittest.mock import AsyncMock
from pitwatch.state.session import LiveSessionState
from pitwatch.strategy.circuits import get_circuit_pit_loss
from pitwatch.strategy.pirelli import PirelliStrategyService
from pitwatch.ingestion.live import LiveOpenF1Source


def test_e2e_sepang_readiness_and_state_matrix():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    
    # Verify pit transit loss is calibrated to 22.5s and laps to 56
    assert state.strategy_engine.pit_loss == 22.5
    assert state.strategy_engine.total_laps == 56

    # Load 2026 Malaysian GP Qualifying front row
    state.load_drivers([
        {"driver_number": 1, "name_acronym": "VER", "team_name": "Red Bull Racing"},
        {"driver_number": 44, "name_acronym": "HAM", "team_name": "Ferrari"},
    ])

    summary = state.get_session_summary()
    assert summary["circuit_name"] == "Kuala Lumpur"
    assert summary["total_laps"] == 56
    assert len(summary["drivers"]) == 2

    # Verify pre-race Pirelli strategy presets
    service = PirelliStrategyService()
    cfg = service.get_strategy_for_circuit("Kuala Lumpur")
    assert cfg is not None
    assert cfg.total_laps == 56
    assert cfg.strategies[0].pit_window == (14, 18)


@pytest.mark.asyncio
async def test_e2e_sepang_live_ingestion_frame_dispatch():
    mock_client = AsyncMock()
    # High thermal track temp as observed in Sepang FP/Qualifying (58.9 C)
    mock_client.get_weather.return_value = [
        {"date": "2026-10-04T07:01:00.000000+00:00", "track_temperature": 58.9, "air_temperature": 34.2, "rainfall": 0}
    ]
    # Sepang turn 1 coordinates: X ~ 4200, Y ~ -2100
    mock_client.get_location.return_value = [
        {"driver_number": 1, "date": "2026-10-04T07:01:00.100000+00:00", "x": 4200.0, "y": -2100.0}
    ]
    mock_client.get_car_data.return_value = [
        {"driver_number": 1, "date": "2026-10-04T07:01:00.100000+00:00", "speed": 312, "gear": 7, "throttle": 100, "brake": 0, "drs": 1, "rpm": 11800}
    ]
    mock_client.get_positions.return_value = [
        {"driver_number": 1, "date": "2026-10-04T07:01:00.000000+00:00", "position": 1}
    ]

    source = LiveOpenF1Source(
        session_key=11731,
        driver_numbers=[1],
        client=mock_client,
        poll_interval_seconds=0.01,
        max_polls=1,
    )
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    state.load_drivers([{"driver_number": 1, "name_acronym": "VER", "team_name": "Red Bull Racing"}])
    source.bind_state(state)

    frames = []
    async for frame in source.stream_frames():
        frames.append(frame)

    assert len(frames) == 1
    assert state.weather is not None
    assert state.weather.track_temperature == 58.9
    driver = state.drivers[1]
    assert driver.latest_telemetry.speed == 312
    assert driver.current_position == 1

    # Check normalized coordinate inside [-1.0, 1.0] bounds for Sepang
    norm_pos = state.get_normalized_position(1)
    assert norm_pos is not None
    assert -1.0 <= norm_pos["x"] <= 1.0
    assert -1.0 <= norm_pos["y"] <= 1.0


def test_sepang_rain_delay_and_metadata_resolution():
    from pitwatch.models.frame import WeatherTick
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")

    # 1. Verify Race Director wet delay notice is evaluated
    assert state.weather_evaluator.is_track_declared_wet is True
    assert state.weather_evaluator.recommended_compound == "WET"
    assert state.weather_evaluator.crossover_status.value == "WET_OPTIMAL"

    # 2. Ingest weather tick during delay (instant rainfall=0 during lull between tropical downpours)
    state.weather_evaluator.record_weather(
        WeatherTick(track_temperature=34.0, air_temperature=25.9, rainfall=0, humidity=85.7),
        session_time=316.8,
    )
    # Must remain WET due to race director wet delay notice (standing water), NEVER premature SLICK
    assert state.weather_evaluator.recommended_compound == "WET"
    assert state.weather_evaluator.crossover_status.value == "WET_OPTIMAL"
    assert state.weather_evaluator.project_tyre_grip_loss() >= 75.0

    # 3. Register drivers dynamically without prior OpenF1 metadata
    state.register_driver(driver_number=1)
    state.register_driver(driver_number=3)

    summary = state.get_session_summary()
    drv1 = next(d for d in summary["drivers"] if d["driver_number"] == 1)
    drv3 = next(d for d in summary["drivers"] if d["driver_number"] == 3)
    assert drv1["team_name"] == "Red Bull Racing"
    assert drv1["team_colour"] == "3671C6"
    assert drv1["current_compound"] == "WET"

    assert drv3["team_name"] == "RB"
    assert drv3["team_colour"] == "6692FF"
    assert drv3["current_compound"] == "WET"

    # 4. Check live telemetry snapshot
    snap = state.get_live_telemetry_snapshot()
    v1 = next(v for v in snap["vehicles"] if v["driver_number"] == 1)
    assert v1["team_name"] == "Red Bull Racing"
    assert v1["team_colour"] == "3671C6"
    assert v1["current_compound"] == "WET"
