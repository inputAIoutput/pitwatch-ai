from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest
from pitwatch.api.app import create_app
from pitwatch.models.frame import ReplayFrame, WeatherTick
from pitwatch.state.session import LiveSessionState


@pytest.fixture
def test_client():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    app = create_app(session_state=state)
    return TestClient(app), state


def test_get_weather_current_endpoint(test_client):
    client, state = test_client

    # Ingest weather tick
    frame = ReplayFrame(
        session_time=120.0,
        timestamp=datetime(2024, 7, 7, 14, 2, 0, tzinfo=timezone.utc),
        weather=WeatherTick(
            track_temperature=28.5,
            air_temperature=16.5,
            rainfall=1,
            wind_speed=3.5,
            wind_direction=225,
            humidity=72.0,
            pressure=992.1,
        ),
    )
    state.ingest_frame(frame)

    response = client.get("/v1/weather/current")
    assert response.status_code == 200

    data = response.json()
    assert data["session_key"] == 9558
    assert data["session_time"] == 120.0
    assert data["track_temperature"] == 28.5
    assert data["air_temperature"] == 16.5
    assert data["rainfall"] == 1
    assert data["wind_speed"] == 3.5
    assert data["wind_direction"] == 225
    assert "wind_x" in data and "wind_y" in data
    assert data["humidity"] == 72.0
    assert data["pressure"] == 992.1
    assert "thermal_drift_rate" in data
    assert "grip_loss_projection" in data
    assert data["recommended_compound"] == "INTERMEDIATE"
    assert data["crossover_status"] == "SLICK_TO_INTERMEDIATE"
    assert data["active_alert"] is not None
    assert data["active_alert"]["severity"] == "CRITICAL"


def test_get_weather_current_empty_state():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    app = create_app(session_state=state)
    client = TestClient(app)

    response = client.get("/v1/weather/current")
    assert response.status_code == 200
    data = response.json()
    assert data["track_temperature"] == 0.0
    assert data["recommended_compound"] == "SLICK"
    assert data["crossover_status"] == "DRY_OPTIMAL"
    assert data["active_alert"] is None
