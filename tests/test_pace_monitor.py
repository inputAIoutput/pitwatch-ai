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


def test_root_cause_pit_stop():
    evaluator = PaceEvaluator()
    evaluator.record_lap(44, "HAM", 1, 90.0, stint_number=1, compound="HARD")
    evaluator.record_lap(44, "HAM", 2, 89.8, stint_number=1, compound="HARD")

    # In-lap / pit stop lap: 114.0s with is_pit_lap=True
    anomaly = evaluator.record_lap(
        driver_number=44,
        driver_code="HAM",
        lap_number=3,
        lap_time=114.0,
        stint_number=1,
        compound="HARD",
        is_pit_lap=True,
    )
    assert anomaly is not None
    assert anomaly.root_cause == SlowLapRootCause.PIT_STOP
    assert "pit" in anomaly.details.lower()


def test_root_cause_vsc_or_sc():
    evaluator = PaceEvaluator()
    evaluator.record_lap(4, "NOR", 1, 88.5, stint_number=1, compound="MEDIUM")
    evaluator.record_lap(4, "NOR", 2, 88.6, stint_number=1, compound="MEDIUM")

    # Lap 3 has VSC deployed
    rcms = [{"message": "VIRTUAL SAFETY CAR DEPLOYED", "flag": "YELLOW", "category": "SafetyCar"}]
    anomaly = evaluator.record_lap(
        driver_number=4,
        driver_code="NOR",
        lap_number=3,
        lap_time=110.2,
        stint_number=1,
        compound="MEDIUM",
        active_race_control_messages=rcms,
    )
    assert anomaly is not None
    assert anomaly.root_cause == SlowLapRootCause.VSC_OR_SC
    assert "safety car" in anomaly.details.lower() or "vsc" in anomaly.details.lower()


def test_root_cause_yellow_flag():
    evaluator = PaceEvaluator()
    evaluator.record_lap(16, "LEC", 1, 89.0, stint_number=1, compound="SOFT")
    evaluator.record_lap(16, "LEC", 2, 89.1, stint_number=1, compound="SOFT")

    # Lap 3 has yellow flag in sector 2
    rcms = [{"message": "YELLOW IN SECTOR 2", "flag": "YELLOW", "category": "Flag", "scope": "Sector"}]
    anomaly = evaluator.record_lap(
        driver_number=16,
        driver_code="LEC",
        lap_number=3,
        lap_time=90.2,
        stint_number=1,
        compound="SOFT",
        active_race_control_messages=rcms,
    )
    assert anomaly is not None
    assert anomaly.root_cause == SlowLapRootCause.YELLOW_FLAG
    assert "yellow flag" in anomaly.details.lower()


def test_root_cause_traffic():
    evaluator = PaceEvaluator()
    evaluator.record_lap(81, "PIA", 1, 90.0, stint_number=1, compound="HARD")
    evaluator.record_lap(81, "PIA", 2, 90.1, stint_number=1, compound="HARD")

    # Lap 3 has dirty air traffic (interval ahead 0.7s <= 1.2s)
    anomaly = evaluator.record_lap(
        driver_number=81,
        driver_code="PIA",
        lap_number=3,
        lap_time=90.9,
        stint_number=1,
        compound="HARD",
        interval_ahead=0.7,
    )
    assert anomaly is not None
    assert anomaly.root_cause == SlowLapRootCause.TRAFFIC
    assert "traffic" in anomaly.details.lower() or "dirty air" in anomaly.details.lower()


def test_root_cause_tyre_cliff():
    evaluator = PaceEvaluator()
    evaluator.record_lap(12, "ANT", 1, 90.0, stint_number=1, compound="SOFT", tyre_age_laps=1)
    evaluator.record_lap(12, "ANT", 2, 90.2, stint_number=1, compound="SOFT", tyre_age_laps=2)

    # Lap 18 on old softs: sudden 1.8s drop to 91.8s without flags or traffic
    anomaly = evaluator.record_lap(
        driver_number=12,
        driver_code="ANT",
        lap_number=18,
        lap_time=91.8,
        stint_number=1,
        compound="SOFT",
        tyre_age_laps=18,
        interval_ahead=5.5,  # clean air
    )
    assert anomaly is not None
    assert anomaly.root_cause == SlowLapRootCause.TYRE_CLIFF
    assert "cliff" in anomaly.details.lower() or "degradation" in anomaly.details.lower()


def test_session_state_pace_monitor():
    from pitwatch.state.session import LiveSessionState

    state = LiveSessionState(session_key=11731, circuit_name="Sepang")
    state.register_driver(driver_number=1, driver_code="VER")
    state.register_driver(driver_number=4, driver_code="NOR")

    # Ingest Lap 1 for VER (90.0s) and NOR (90.5s)
    state.update_timing_line("1", {"NumberOfLaps": 1, "LastLapTime": "1:30.000", "Position": "1", "GapToLeader": "LEADER"})
    state.update_timing_line("4", {"NumberOfLaps": 1, "LastLapTime": "1:30.500", "Position": "2", "GapToLeader": "+0.500", "IntervalToPositionAhead": "+0.500"})

    # Ingest Lap 2 for VER (89.8s) and NOR (90.4s)
    state.update_timing_line("1", {"NumberOfLaps": 2, "LastLapTime": "1:29.800", "Position": "1", "GapToLeader": "LEADER"})
    state.update_timing_line("4", {"NumberOfLaps": 2, "LastLapTime": "1:30.400", "Position": "2", "GapToLeader": "+1.100", "IntervalToPositionAhead": "+1.100"})

    pace_resp = state.get_pace_monitor()
    assert pace_resp.session_key == 11731
    assert len(pace_resp.drivers) == 2

    ver_status = next(d for d in pace_resp.drivers if d.driver_number == 1)
    assert ver_status.driver_code == "VER"
    assert ver_status.stint_baseline_pace == 89.8
    assert ver_status.last_lap_time == 89.8
    assert ver_status.trend in (PaceTrend.IMPROVING, PaceTrend.STABLE)

    nor_status = next(d for d in pace_resp.drivers if d.driver_number == 4)
    assert nor_status.driver_code == "NOR"
    assert nor_status.stint_baseline_pace == 90.4
    assert nor_status.trend == PaceTrend.STABLE


def test_api_pace_monitor():
    from fastapi.testclient import TestClient
    from pitwatch.api.app import create_app
    from pitwatch.state.session import LiveSessionState

    state = LiveSessionState(session_key=11731, circuit_name="Sepang")
    state.register_driver(driver_number=1, driver_code="VER")
    state.register_driver(driver_number=4, driver_code="NOR")

    state.update_timing_line("1", {"NumberOfLaps": 1, "LastLapTime": "1:30.000", "Position": "1", "GapToLeader": "LEADER"})
    state.update_timing_line("4", {"NumberOfLaps": 1, "LastLapTime": "1:30.500", "Position": "2", "GapToLeader": "+0.500"})

    app = create_app(session_state=state)
    client = TestClient(app)

    resp = client.get("/v1/strategy/pace-monitor")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_key"] == 11731
    assert "drivers" in data
    assert len(data["drivers"]) == 2
    assert data["drivers"][0]["driver_code"] == "VER"
    assert "trend" in data["drivers"][0]
    assert "trend_color" in data["drivers"][0]



