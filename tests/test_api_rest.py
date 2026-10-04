from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pitwatch.api.app import create_app
from pitwatch.models.frame import CarPositionTick, TelemetryTick, WeatherTick, ReplayFrame
from pitwatch.state.session import LiveSessionState


@pytest.fixture
def populated_state():
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    state.register_driver(driver_number=44, driver_code="HAM", team_name="Mercedes", team_colour="27F4D2")
    state.register_driver(driver_number=1, driver_code="VER", team_name="Red Bull", team_colour="3671C6")

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
    assert data["current_lap"] == 1
    assert data["total_laps"] == 52
    assert data["total_drivers"] == 2
    assert len(data["drivers"]) == 2
    assert data["drivers"][0]["driver_code"] == "HAM"
    assert data["drivers"][0]["team_colour"] == "27F4D2"
    assert data["drivers"][0]["current_lap"] == 1
    assert "last_lap_time" in data["drivers"][0]
    assert "tyre_age_laps" in data["drivers"][0]


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
    assert leader["team_colour"] == "27F4D2"
    assert leader["gap_to_leader"] == 0.0


def test_session_current_empty_state():
    empty_state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    app = create_app(session_state=empty_state)
    client = TestClient(app)

    response = client.get("/v1/session/current")
    assert response.status_code == 200
    assert response.json()["total_drivers"] == 0


def test_get_telemetry_live_contains_continuous_lap_progress():
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    app = create_app(session_state=state)

    # Ingest position with progress=None
    frame = ReplayFrame(
        session_time=30.0,
        timestamp=datetime.now(timezone.utc),
        positions=[
            CarPositionTick(driver_number=12, x=-1400.0, y=-1100.0, progress=None),
        ],
        telemetry=[
            TelemetryTick(driver_number=12, speed=245, gear=5, throttle=80, brake=0, drs=0, rpm=11200),
        ],
    )
    state.ingest_frame(frame)

    client = TestClient(app)
    response = client.get("/v1/telemetry/live")
    assert response.status_code == 200
    data = response.json()
    assert len(data["vehicles"]) >= 1

    ant = next(v for v in data["vehicles"] if v["driver_number"] == 12)
    assert ant["progress"] is not None
    assert 0.15 <= ant["progress"] <= 0.35


def test_get_session_current_includes_fastest_lap_and_formatted_strings(populated_state):
    # Set fastest lap on populated_state
    populated_state.drivers[44].last_lap_time = 92.519
    populated_state._check_update_fastest_lap(driver_number=44, lap_time=92.519, lap_number=3)

    app = create_app(session_state=populated_state)
    client = TestClient(app)

    response = client.get("/v1/session/current")
    assert response.status_code == 200
    data = response.json()

    assert data["fastest_lap"] is not None
    assert data["fastest_lap"]["driver_code"] == "HAM"
    assert data["fastest_lap"]["lap_time"] == 92.519
    assert data["fastest_lap"]["lap_time_formatted"] == "01:32.519"

    ham = data["drivers"][0]
    assert ham["last_lap_time_formatted"] == "01:32.519"
    assert ham["gap_to_leader_formatted"] == "LEADER"
    assert ham["interval_ahead_formatted"] == "-"


def test_get_session_race_control_endpoints(populated_state):
    # Add race control messages
    populated_state.add_race_control_message({
        "Utc": "2024-07-07T14:15:00",
        "Category": "Flag",
        "Flag": "YELLOW",
        "Message": "YELLOW FLAG IN SECTOR 2",
        "Scope": "Sector",
    })
    populated_state.add_race_control_message({
        "Utc": "2024-07-07T14:18:00",
        "Category": "Drs",
        "Message": "DRS ENABLED",
    })
    populated_state.add_race_control_message({
        "Utc": "2024-07-07T14:22:00",
        "Category": "Flag",
        "Flag": "GREEN",
        "Message": "CLEAR IN SECTOR 2",
        "Scope": "Sector",
    })

    app = create_app(session_state=populated_state)
    client = TestClient(app)

    # 1. GET /v1/session/race-control (all messages)
    res_all = client.get("/v1/session/race-control")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert data_all["session_key"] == 9558
    assert data_all["total_messages"] >= 3
    msgs = data_all["messages"]
    assert any("YELLOW FLAG" in m["message"] for m in msgs)
    assert any("DRS ENABLED" in m["message"] for m in msgs)

    # 2. Filter by category
    res_flags = client.get("/v1/session/race-control?category=Flag")
    assert res_flags.status_code == 200
    data_flags = res_flags.json()
    assert all(m["category"] == "Flag" for m in data_flags["messages"])

    # 3. Filter by flag
    res_yellow = client.get("/v1/session/race-control?flag=YELLOW")
    assert res_yellow.status_code == 200
    data_yellow = res_yellow.json()
    assert len(data_yellow["messages"]) == 1
    assert data_yellow["messages"][0]["flag"] == "YELLOW"

    # 4. Limit parameter
    res_limit = client.get("/v1/session/race-control?limit=2")
    assert res_limit.status_code == 200
    assert len(res_limit.json()["messages"]) == 2


