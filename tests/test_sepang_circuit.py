import pytest
from pitwatch.strategy.circuits import get_circuit_pit_loss
from pitwatch.state.geometry import CoordinateNormalizer, CIRCUIT_PRESETS
from pitwatch.strategy.pirelli import PirelliStrategyService


def test_sepang_pit_loss_lookup():
    assert get_circuit_pit_loss("Sepang") == 22.5
    assert get_circuit_pit_loss("Kuala Lumpur") == 22.5
    assert get_circuit_pit_loss("Sepang International Circuit") == 22.5


def test_f1_calendar_pit_losses():
    assert get_circuit_pit_loss("Bahrain") == 23.0
    assert get_circuit_pit_loss("Silverstone") == 21.5
    assert get_circuit_pit_loss("Monaco") == 19.5
    assert get_circuit_pit_loss("Marina Bay") == 28.0
    assert get_circuit_pit_loss("Circuit of the Americas") == 21.0
    assert get_circuit_pit_loss("Albert Park") == 20.0
    assert get_circuit_pit_loss("Unknown Track") == 22.0


def test_sepang_coordinate_bounds():
    norm = CoordinateNormalizer.for_circuit("Kuala Lumpur")
    assert "kuala lumpur" in CIRCUIT_PRESETS or "sepang" in CIRCUIT_PRESETS
    
    # Test normalization of extreme corners measured from 2026 Qualifying
    nx1, ny1 = norm.normalize_point(-5128.0, -5510.0)
    nx2, ny2 = norm.normalize_point(6429.0, 3874.0)

    assert -1.0 <= nx1 <= 1.0
    assert -1.0 <= ny1 <= 1.0
    assert -1.0 <= nx2 <= 1.0
    assert -1.0 <= ny2 <= 1.0


def test_sepang_pirelli_presets_service():
    service = PirelliStrategyService()
    config = service.get_strategy_for_circuit("Kuala Lumpur")

    assert config is not None
    assert config.total_laps == 56
    assert config.pit_transit_loss_seconds == 22.5
    assert len(config.strategies) >= 2

    # Optimal 2-stop baseline for high thermal wear
    optimal = config.strategies[0]
    assert optimal.stops in (1, 2)
