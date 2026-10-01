from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pitwatch.api.app import create_app
from pitwatch.models.frame import CarPositionTick, TelemetryTick, WeatherTick, ReplayFrame
from pitwatch.state.session import LiveSessionState


@pytest.fixture
def populated_state():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    state.register_driver(driver_number=44, driver_code="HAM", team_name="Mercedes")
    state.register_driver(driver_number=1, driver_code="VER", team_name="Red Bull")

    frame = ReplayFrame(
        session_time=5.2,
        timestamp=datetime(2024, 7, 7, 14, 3, 17, tzinfo=timezone.utc),
        positions=[
            CarPositionTick(driver_number=44, x=-1000.0, y=2000.0, progress=0.06),
            CarPositionTick(driver_number=1, x=-1100.0, y=1900.0, progress=0.05),
        ],
        telemetry=[
            TelemetryTick(driver_number=44, speed=302, gear=7, throttle=100, brake=0, drs=1, rpm=11400),
            TelemetryTick(driver_number=1, speed=298, gear=7, throttle=100, brake=0, drs=1, rpm=11200),
        ],
        weather=WeatherTick(track_temperature=29.4, air_temperature=17.2, rainfall=0),
    )
    state.ingest_frame(frame)
    return state


def test_get_session_current(populated_state):
    app = create_app(session_state=populated_state)
    client = TestClient(app)

    response = client.get("/v1/session/current")
    assert response.status_code == 200
    data = response.json()
    assert data["session_key"] == 9558
    assert data["circuit_name"] == "Silverstone"
    assert data["total_drivers"] == 2
    assert len(data["drivers"]) == 2
    assert data["drivers"][0]["driver_code"] == "HAM"


def test_get_telemetry_live(populated_state):
    app = create_app(session_state=populated_state)
    client = TestClient(app)

    response = client.get("/v1/telemetry/live")
    assert response.status_code == 200
    data = response.json()
    assert data["session_key"] == 9558
    assert data["session_time"] == 5.2
    assert data["track_temperature"] == 29.4
    assert len(data["vehicles"]) == 2

    leader = data["vehicles"][0]
    assert leader["driver_number"] == 44
    assert leader["speed"] == 302
    assert leader["position"] == 1
    assert leader["gap_to_leader"] == 0.0


def test_session_current_empty_state():
    empty_state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    app = create_app(session_state=empty_state)
    client = TestClient(app)

    response = client.get("/v1/session/current")
    assert response.status_code == 200
    assert response.json()["total_drivers"] == 0
