from fastapi.testclient import TestClient
import pytest
from pitwatch.api.app import create_app
from pitwatch.state.session import LiveSessionState


@pytest.fixture
def strategy_client():
    state = LiveSessionState(session_key=9662, circuit_name="Abu Dhabi")
    state.load_drivers([
        {"driver_number": 4, "name_acronym": "NOR", "team_name": "McLaren", "team_colour": "FF8000"},
        {"driver_number": 1, "name_acronym": "VER", "team_name": "Red Bull Racing", "team_colour": "3671C6"},
    ])
    app = create_app(session_state=state)
    return TestClient(app), state


def test_get_strategy_presets_endpoint(strategy_client):
    client, _ = strategy_client
    response = client.get("/v1/strategy/presets")
    assert response.status_code == 200

    data = response.json()
    assert "Yas Marina" in data["circuit_name"] or "Abu Dhabi" in data["circuit_name"]
    assert data["pit_transit_loss_seconds"] == 22.0
    assert data["total_laps"] == 58
    assert len(data["strategies"]) >= 2
    assert data["strategies"][0]["name"] == "Pirelli Optimal (1-Stop)"


def test_get_strategy_threat_matrix_endpoint(strategy_client):
    client, _ = strategy_client
    response = client.get("/v1/strategy/threat-matrix")
    assert response.status_code == 200

    data = response.json()
    assert data["circuit_name"] == "Abu Dhabi"
    assert data["pit_transit_loss_seconds"] == 22.0
    assert "competitors" in data
    assert len(data["competitors"]) == 2

    # Check pit_rejoin simulation output
    for comp in data["competitors"]:
        assert "pit_rejoin" in comp and comp["pit_rejoin"] is not None
        rejoin = comp["pit_rejoin"]
        assert "projected_gap_to_leader" in rejoin
        assert "projected_position" in rejoin
        assert "in_traffic" in rejoin
        assert "clean_air_window_seconds" in rejoin
        # Backward compatibility clearance check
        assert "pit_window_clearance" in comp
        assert "net_margin_seconds" in comp["pit_window_clearance"]
