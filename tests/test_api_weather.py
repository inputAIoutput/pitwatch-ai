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
    assert data["slick_ratio"] == 0.0
    assert data["is_track_declared_wet"] is False


def test_get_weather_current_with_drs_override(test_client):
    client, state = test_client
    now = datetime(2026, 10, 4, 15, 0, 0, tzinfo=timezone.utc)

    # 1. Start delayed due to rain
    state.add_race_control_message({
        "Message": "START PROCEDURE DELAYED - RAIN & STANDING WATER",
        "Flag": "RED",
    })
    # Weather observation: track at 38°C (Medium window)
    frame = ReplayFrame(
        session_time=120.0,
        timestamp=now,
        weather=WeatherTick(track_temperature=38.0, air_temperature=24.0, rainfall=0),
    )
    state.ingest_frame(frame)

    res_wet = client.get("/v1/weather/current").json()
    assert res_wet["is_track_declared_wet"] is True
    assert res_wet["recommended_compound"] == "WET"

    # 2. Race Director enables DRS
    state.add_race_control_message({"Message": "DRS ENABLED"})

    res_dry = client.get("/v1/weather/current").json()
    assert res_dry["is_track_declared_wet"] is False
    assert res_dry["recommended_compound"] == "MEDIUM"
    assert res_dry["crossover_status"] == "DRY_OPTIMAL"
    assert res_dry["active_alert"] is not None


def test_get_weather_current_with_grid_slick_adoption(test_client):
    client, state = test_client
    now = datetime(2026, 10, 4, 15, 2, 0, tzinfo=timezone.utc)

    # Track initially declared wet
    state.weather_evaluator.is_track_declared_wet = True
    state.weather_evaluator.crossover_status = state.weather_evaluator.crossover_status.WET_OPTIMAL
    state.weather_evaluator.recommended_compound = "WET"

    frame = ReplayFrame(
        session_time=150.0,
        timestamp=now,
        weather=WeatherTick(track_temperature=26.0, air_temperature=19.0, rainfall=0),
    )
    state.ingest_frame(frame)

    # 20 drivers registered: 12 on SOFT, 8 on INTERMEDIATE (60% slicks)
    for i in range(1, 21):
        drv = state.register_driver(driver_number=i)
        if i <= 12:
            drv.set_compound("SOFT", tyre_age_at_start=1)
        else:
            drv.set_compound("INTERMEDIATE", tyre_age_at_start=1)

    res = client.get("/v1/weather/current").json()
    assert res["slick_ratio"] == 0.6
    assert res["is_track_declared_wet"] is False
    assert res["recommended_compound"] == "SOFT"  # 26°C is < 30°C -> SOFT
    assert res["crossover_status"] == "DRY_OPTIMAL"

