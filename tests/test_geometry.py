import pytest
from pitwatch.state.geometry import CoordinateNormalizer, CircuitBounds


def test_circuit_bounds_normalization():
    # Bounds for a sample circuit
    bounds = CircuitBounds(min_x=-1000.0, max_x=1000.0, min_y=-500.0, max_y=500.0)
    normalizer = CoordinateNormalizer(bounds=bounds)

    # Center should normalize to (0.0, 0.0)
    nx, ny = normalizer.normalize_point(0.0, 0.0)
    assert pytest.approx(nx, abs=1e-3) == 0.0
    assert pytest.approx(ny, abs=1e-3) == 0.0

    # Min corner should normalize to (-1.0, -1.0)
    nx, ny = normalizer.normalize_point(-1000.0, -500.0)
    assert pytest.approx(nx, abs=1e-3) == -1.0
    assert pytest.approx(ny, abs=1e-3) == -1.0

    # Max corner should normalize to (1.0, 1.0)
    nx, ny = normalizer.normalize_point(1000.0, 500.0)
    assert pytest.approx(nx, abs=1e-3) == 1.0
    assert pytest.approx(ny, abs=1e-3) == 1.0


def test_coordinate_clamping_to_boundaries():
    # Verify values outside bounds strictly clamp to [-1.0, 1.0]
    bounds = CircuitBounds(min_x=-100.0, max_x=100.0, min_y=-100.0, max_y=100.0)
    normalizer = CoordinateNormalizer(bounds=bounds)

    nx, ny = normalizer.normalize_point(500.0, -999.0)
    assert nx == 1.0
    assert ny == -1.0


def test_lap_progress_clamping():
    normalizer = CoordinateNormalizer()
    assert normalizer.normalize_progress(0.45) == 0.45
    assert normalizer.normalize_progress(-0.1) == 0.0
    assert normalizer.normalize_progress(1.25) == 1.0
    assert normalizer.normalize_progress(None) == 0.0


def test_silverstone_preset_bounds():
    normalizer = CoordinateNormalizer.for_circuit("Silverstone")
    # Silverstone raw coordinates fall within known bounds
    nx, ny = normalizer.normalize_point(120.0, -45.0)
    assert -1.0 <= nx <= 1.0
    assert -1.0 <= ny <= 1.0
