import pytest
from pitwatch.state.geometry import (
    CoordinateNormalizer,
    CircuitBounds,
    CIRCUIT_PRESETS,
    CIRCUIT_WAYPOINTS,
    TrackCenterline,
)


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


def test_circuit_waypoints_defined_for_all_required_circuits():
    required_circuits = ["sepang", "kuala lumpur", "silverstone", "monza", "spa", "monaco"]
    for circuit in required_circuits:
        normalizer = CoordinateNormalizer.for_circuit(circuit)
        assert normalizer.centerline is not None
        assert len(normalizer.centerline.waypoints) >= 10
        assert normalizer.centerline.total_length > 0.0


def test_sepang_centerline_progress_projection():
    normalizer = CoordinateNormalizer.for_circuit("Sepang")
    centerline = normalizer.centerline
    assert centerline is not None

    # Waypoint 0 should project to 0.0 progress (Start/Finish line)
    w0_x, w0_y = centerline.waypoints[0]
    p0 = normalizer.calculate_lap_progress(w0_x, w0_y)
    assert pytest.approx(p0, abs=0.02) == 0.0

    # Test sequential waypoints along the lap advance monotonically
    progresses = []
    step = max(1, len(centerline.waypoints) // 8)
    for i in range(0, len(centerline.waypoints), step):
        wx, wy = centerline.waypoints[i]
        prog = normalizer.calculate_lap_progress(wx, wy)
        progresses.append(prog)

    # Values should be increasing up to near 1.0
    for j in range(1, len(progresses) - 1):
        assert progresses[j] > progresses[j - 1], f"Progress not increasing: {progresses}"


def test_calculate_lap_progress_with_sector_anchoring():
    normalizer = CoordinateNormalizer.for_circuit("Sepang")
    centerline = normalizer.centerline
    assert centerline is not None

    # Midpoint of Sector 1
    s1_pt = centerline.waypoints[len(centerline.waypoints) // 6]
    prog_s1 = normalizer.calculate_lap_progress(s1_pt[0], s1_pt[1], sector=1)
    assert 0.0 <= prog_s1 <= 0.40

    # Midpoint of Sector 2
    s2_pt = centerline.waypoints[len(centerline.waypoints) // 2]
    prog_s2 = normalizer.calculate_lap_progress(s2_pt[0], s2_pt[1], sector=2)
    assert 0.30 <= prog_s2 <= 0.75

    # Near end of Sector 3
    s3_pt = centerline.waypoints[int(len(centerline.waypoints) * 0.88)]
    prog_s3 = normalizer.calculate_lap_progress(s3_pt[0], s3_pt[1], sector=3)
    assert 0.65 <= prog_s3 <= 1.0


def test_calculate_lap_progress_fallback_when_no_waypoints():
    # Normalizer without centerline waypoints returns 0.0 without crashing
    normalizer = CoordinateNormalizer(bounds=CircuitBounds(min_x=-100, max_x=100, min_y=-100, max_y=100))
    prog = normalizer.calculate_lap_progress(10.0, 20.0)
    assert 0.0 <= prog <= 1.0
