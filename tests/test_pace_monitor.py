import pytest
from pitwatch.intelligence.pace import (
    PaceEvaluator,
    PaceTrend,
    TrendColor,
    SlowLapRootCause,
    LapPaceRecord,
    PaceAnomaly,
    DriverPaceStatus,
    PaceMonitorResponse,
)


def test_pace_evaluator_models_and_enums():
    assert PaceTrend.IMPROVING == "IMPROVING"
    assert PaceTrend.STABLE == "STABLE"
    assert PaceTrend.MILD_DEGRADATION == "MILD_DEGRADATION"
    assert PaceTrend.CLIFF == "CLIFF"

    assert TrendColor.GREEN == "GREEN"
    assert TrendColor.YELLOW == "YELLOW"
    assert TrendColor.ORANGE == "ORANGE"
    assert TrendColor.RED == "RED"

    assert SlowLapRootCause.YELLOW_FLAG == "YELLOW_FLAG"
    assert SlowLapRootCause.VSC_OR_SC == "VSC_OR_SC"
    assert SlowLapRootCause.PIT_STOP == "PIT_STOP"
    assert SlowLapRootCause.TRAFFIC == "TRAFFIC"
    assert SlowLapRootCause.TYRE_CLIFF == "TYRE_CLIFF"


def test_pace_evaluator_delta_and_trend_classification():
    evaluator = PaceEvaluator()

    # Lap 1: Stint initial lap - establishes baseline
    # E.g. Driver 1 starts stint on mediums, laps at 90.0s
    evaluator.record_lap(
        driver_number=1,
        driver_code="VER",
        lap_number=1,
        lap_time=90.0,
        stint_number=1,
        compound="MEDIUM",
        tyre_age_laps=1,
    )

    status = evaluator.evaluate_driver(driver_number=1)
    assert status is not None
    assert status.driver_number == 1
    assert status.driver_code == "VER"
    assert status.stint_baseline_pace == 90.0
    assert status.rolling_median_pace == 90.0
    assert status.trend == PaceTrend.STABLE
    assert status.trend_color == TrendColor.YELLOW

    # Lap 2: Improving lap at 89.6s (delta = -0.4s < -0.2s)
    evaluator.record_lap(
        driver_number=1,
        driver_code="VER",
        lap_number=2,
        lap_time=89.6,
        stint_number=1,
        compound="MEDIUM",
        tyre_age_laps=2,
    )
    status2 = evaluator.evaluate_driver(driver_number=1)
    assert status2.stint_baseline_pace == 89.6  # new best clean lap becomes baseline
    assert status2.last_lap_time == 89.6
    # Against previous baseline or self:
    assert status2.trend in (PaceTrend.IMPROVING, PaceTrend.STABLE)

    # Lap 3: 89.7s (stable degradation relative to 89.6s, delta = +0.1s)
    evaluator.record_lap(
        driver_number=1,
        driver_code="VER",
        lap_number=3,
        lap_time=89.7,
        stint_number=1,
        compound="MEDIUM",
        tyre_age_laps=3,
    )
    status3 = evaluator.evaluate_driver(driver_number=1)
    assert status3.stint_baseline_pace == 89.6
    # Rolling median of [90.0, 89.6, 89.7] -> 89.7
    assert status3.rolling_median_pace == 89.7
    # Delta to baseline = 89.7 - 89.6 = +0.10s -> STABLE, YELLOW
    assert status3.trend == PaceTrend.STABLE
    assert status3.trend_color == TrendColor.YELLOW

    # Lap 4: 90.3s (delta to baseline 89.6s = +0.70s -> MILD_DEGRADATION, ORANGE)
    evaluator.record_lap(
        driver_number=1,
        driver_code="VER",
        lap_number=4,
        lap_time=90.3,
        stint_number=1,
        compound="MEDIUM",
        tyre_age_laps=4,
    )
    status4 = evaluator.evaluate_driver(driver_number=1)
    assert status4.trend == PaceTrend.MILD_DEGRADATION
    assert status4.trend_color == TrendColor.ORANGE

    # Lap 5: 91.2s (delta to baseline 89.6s = +1.60s -> CLIFF, RED)
    evaluator.record_lap(
        driver_number=1,
        driver_code="VER",
        lap_number=5,
        lap_time=91.2,
        stint_number=1,
        compound="MEDIUM",
        tyre_age_laps=5,
    )
    status5 = evaluator.evaluate_driver(driver_number=1)
    assert status5.trend == PaceTrend.CLIFF
    assert status5.trend_color == TrendColor.RED
