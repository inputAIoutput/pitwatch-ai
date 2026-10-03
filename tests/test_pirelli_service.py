import pytest
from pitwatch.strategy.circuits import get_circuit_pit_loss, CIRCUIT_PIT_LOSSES
from pitwatch.strategy.pirelli import PirelliStrategyService, CircuitStrategyConfig


def test_circuit_pit_loss_lookup():
    # Known benchmark pit transit loss values
    assert get_circuit_pit_loss("Abu Dhabi") == 22.0
    assert get_circuit_pit_loss("Yas Marina") == 22.0
    assert get_circuit_pit_loss("Silverstone") == 21.5
    assert get_circuit_pit_loss("Monaco") == 19.5
    assert get_circuit_pit_loss("Monza") == 24.0
    # Unknown circuit fallback to standard 22.0s
    assert get_circuit_pit_loss("NonExistentCircuit") == 22.0


def test_pirelli_presets_service_loads_abu_dhabi():
    service = PirelliStrategyService()
    config = service.get_strategy_for_circuit("Abu Dhabi")

    assert config is not None
    assert "Yas Marina" in config.circuit_name or "Abu Dhabi" in config.circuit_name
    assert config.total_laps == 58
    assert config.pit_transit_loss_seconds == 22.0
    assert len(config.strategies) >= 2

    # Fastest strategy: Medium to Hard (1-stop)
    fastest = config.strategies[0]
    assert fastest.is_fastest is True
    assert fastest.stops == 1
    assert len(fastest.stints) == 2
    assert fastest.stints[0].compound == "MEDIUM"
    assert fastest.stints[1].compound == "HARD"
    assert fastest.pit_window == (16, 22)


def test_pirelli_presets_service_loads_by_alias_yas_marina():
    service = PirelliStrategyService()
    config = service.get_strategy_for_circuit("Yas Marina")
    assert config is not None
    assert config.total_laps == 58


def test_pirelli_presets_service_unknown_circuit_generates_default():
    service = PirelliStrategyService()
    config = service.get_strategy_for_circuit("UnknownTrack", total_laps=50)

    assert config.circuit_name == "UnknownTrack"
    assert len(config.strategies) >= 1
    assert config.strategies[0].stops == 1
