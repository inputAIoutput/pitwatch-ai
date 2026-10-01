from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pitwatch.api.app import create_app
from pitwatch.models.frame import CarPositionTick, TelemetryTick, ReplayFrame
from pitwatch.state.session import LiveSessionState


@pytest.fixture
def active_state():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    state.register_driver(driver_number=44, driver_code="HAM", team_name="Mercedes")
    state.register_driver(driver_number=1, driver_code="VER", team_name="Red Bull")

    frame = ReplayFrame(
        session_time=2.0,
        timestamp=datetime(2024, 7, 7, 14, 3, 14, tzinfo=timezone.utc),
        positions=[
            CarPositionTick(driver_number=44, x=-1095.0, y=2081.0, progress=0.02),
            CarPositionTick(driver_number=1, x=-1182.0, y=1962.0, progress=0.02),
        ],
        telemetry=[
            TelemetryTick(driver_number=44, speed=300, gear=7, throttle=100, brake=0, drs=1),
            TelemetryTick(driver_number=1, speed=298, gear=7, throttle=100, brake=0, drs=1),
        ],
    )
    state.ingest_frame(frame)
    return state


def test_websocket_stream_positions_connect_and_receive(active_state):
    app = create_app(session_state=active_state)
    client = TestClient(app)

    with client.websocket_connect("/v1/stream/positions?interval=0.05") as ws:
        # First message emitted immediately
        data = ws.receive_json()
        assert data["type"] == "positions"
        assert data["session_time"] == 2.0
        assert "timestamp" in data
        assert len(data["positions"]) == 2

        ham = [p for p in data["positions"] if p["driver_number"] == 44][0]
        assert ham["driver_code"] == "HAM"
        assert -1.0 <= ham["x"] <= 1.0
        assert -1.0 <= ham["y"] <= 1.0
        assert ham["progress"] == 0.02
        assert ham["speed"] == 300


def test_websocket_client_disconnect_handling(active_state):
    app = create_app(session_state=active_state)
    client = TestClient(app)

    # Verify connecting and immediate graceful closing does not throw unhandled exceptions
    with client.websocket_connect("/v1/stream/positions?interval=0.05") as ws:
        _ = ws.receive_json()
        ws.close()
