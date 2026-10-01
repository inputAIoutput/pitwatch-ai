from datetime import datetime, timezone
import pytest
from pitwatch.api.schemas import (
    DriverMeta,
    SessionCurrentResponse,
    VehicleTelemetrySnapshot,
    LiveTelemetryResponse,
    VehiclePositionPayload,
    PositionsStreamMessage,
)
from pitwatch.models.frame import CarPositionTick, TelemetryTick, WeatherTick, ReplayFrame
from pitwatch.state.session import LiveSessionState
from pitwatch.state.driver import TyreCompound


def test_session_state_query_helpers():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    state.register_driver(driver_number=44, driver_code="HAM", team_name="Mercedes")
    state.register_driver(driver_number=1, driver_code="VER", team_name="Red Bull")

    frame = ReplayFrame(
        session_time=1.4,
        timestamp=datetime(2024, 7, 7, 14, 3, 14, tzinfo=timezone.utc),
        positions=[
            CarPositionTick(driver_number=44, x=100.0, y=200.0, progress=0.05),
            CarPositionTick(driver_number=1, x=80.0, y=180.0, progress=0.04),
        ],
        telemetry=[
            TelemetryTick(driver_number=44, speed=295, gear=7, throttle=100, brake=0, drs=1, rpm=11200),
            TelemetryTick(driver_number=1, speed=292, gear=7, throttle=100, brake=0, drs=1, rpm=11100),
        ],
        weather=WeatherTick(track_temperature=28.1, air_temperature=16.4, rainfall=0),
    )
    state.ingest_frame(frame)

    # 1. Test get_all_normalized_positions
    positions = state.get_all_normalized_positions()
    assert len(positions) == 2
    assert positions[0]["driver_number"] == 44
    assert "x" in positions[0]
    assert "y" in positions[0]
    assert positions[0]["progress"] == 0.05

    # 2. Test get_session_summary
    summary = state.get_session_summary()
    assert summary["session_key"] == 9558
    assert summary["circuit_name"] == "Silverstone"
    assert len(summary["drivers"]) == 2

    # 3. Test get_live_telemetry_snapshot
    telemetry_snap = state.get_live_telemetry_snapshot()
    assert telemetry_snap["session_time"] == 1.4
    assert len(telemetry_snap["vehicles"]) == 2
    assert telemetry_snap["vehicles"][0]["driver_code"] == "HAM"
    assert telemetry_snap["vehicles"][0]["speed"] == 295


def test_pydantic_schema_validation():
    # Verify Pydantic serialization
    pos_msg = PositionsStreamMessage(
        session_time=1.4,
        timestamp="2024-07-07T14:03:14+00:00",
        positions=[
            VehiclePositionPayload(driver_number=44, driver_code="HAM", x=-0.31, y=0.83, progress=0.05, speed=295)
        ],
    )
    json_data = pos_msg.model_dump()
    assert json_data["type"] == "positions"
    assert len(json_data["positions"]) == 1
    assert json_data["positions"][0]["driver_number"] == 44
