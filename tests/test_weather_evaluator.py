from datetime import datetime, timezone
import pytest
from pitwatch.models.frame import WeatherTick
from pitwatch.intelligence.weather import (
    EnvironmentalEvaluator,
    CrossoverStatus,
    CrossoverAlert,
)


def test_thermal_drift_rate_calculation():
    evaluator = EnvironmentalEvaluator(window_seconds=300)

    # 1. Single reading -> drift rate is 0.0
    w0 = WeatherTick(track_temperature=30.0, air_temperature=18.0, rainfall=0)
    evaluator.record_weather(w0, session_time=0.0)
    assert evaluator.get_thermal_drift_rate() == 0.0

    # 2. Track temp drops 2.0°C over 2 minutes (120s) -> -1.0 °C/min
    w1 = WeatherTick(track_temperature=29.0, air_temperature=17.5, rainfall=0)
    evaluator.record_weather(w1, session_time=60.0)

    w2 = WeatherTick(track_temperature=28.0, air_temperature=17.0, rainfall=0)
    evaluator.record_weather(w2, session_time=120.0)

    drift_rate = evaluator.get_thermal_drift_rate()
    assert pytest.approx(drift_rate, rel=1e-2) == -1.0


def test_grip_loss_projection_dry_vs_wet():
    evaluator = EnvironmentalEvaluator()

    # Optimal dry conditions (track temp 32°C, rainfall 0) -> 0% grip loss
    w_dry = WeatherTick(track_temperature=32.0, air_temperature=20.0, rainfall=0, humidity=50.0)
    evaluator.record_weather(w_dry, session_time=0.0)
    grip_loss_dry = evaluator.project_tyre_grip_loss()
    assert grip_loss_dry == 0.0

    # Sub-optimal cold track (track temp 20°C, rainfall 0) -> thermal penalty ~9.6%
    w_cold = WeatherTick(track_temperature=20.0, air_temperature=14.0, rainfall=0, humidity=50.0)
    evaluator.record_weather(w_cold, session_time=60.0)
    grip_loss_cold = evaluator.project_tyre_grip_loss()
    assert grip_loss_cold > 0.0
    assert grip_loss_cold < 20.0

    # Rain detected -> immediate surface water penalty >= 30%
    w_wet = WeatherTick(track_temperature=20.0, air_temperature=14.0, rainfall=1, humidity=80.0)
    evaluator.record_weather(w_wet, session_time=120.0)
    grip_loss_wet = evaluator.project_tyre_grip_loss()
    assert grip_loss_wet >= 35.0


def test_crossover_detection_lifecycle():
    evaluator = EnvironmentalEvaluator(window_seconds=300)

    # 1. Dry conditions at 35°C -> MEDIUM
    w0 = WeatherTick(track_temperature=35.0, air_temperature=20.0, rainfall=0, humidity=55.0)
    alert = evaluator.record_weather(w0, session_time=0.0)
    assert evaluator.crossover_status == CrossoverStatus.DRY_OPTIMAL
    assert evaluator.recommended_compound == "MEDIUM"
    assert alert is None

    # 2. Rain starts & track cools rapidly (-1.5°C in 60s) -> Crossover to Intermediate
    w1 = WeatherTick(track_temperature=33.5, air_temperature=18.0, rainfall=1, humidity=75.0)
    alert = evaluator.record_weather(w1, session_time=60.0)
    assert evaluator.crossover_status == CrossoverStatus.SLICK_TO_INTERMEDIATE
    assert evaluator.recommended_compound == "INTERMEDIATE"
    assert alert is not None
    assert alert.severity == "CRITICAL"
    assert "INTERMEDIATE" in alert.message

    # 3. Persistent torrential rain & cold track (< 20°C, sustained rain) -> Crossover to Wet
    w2 = WeatherTick(track_temperature=18.5, air_temperature=13.0, rainfall=1, humidity=90.0)
    # Simulate multiple sustained rain ticks
    for t in range(120, 600, 60):
        alert = evaluator.record_weather(w2, session_time=float(t))
    assert evaluator.crossover_status in (CrossoverStatus.INTERMEDIATE_TO_WET, CrossoverStatus.WET_OPTIMAL)
    assert evaluator.recommended_compound == "WET"

    # 4. Rain stops, track warms up (+0.8°C/min, reaching 29°C) -> Crossover back to Slick (SOFT)
    w3 = WeatherTick(track_temperature=25.0, air_temperature=17.0, rainfall=0, humidity=60.0)
    for t in range(660, 960, 60):
        # Temp increases each minute
        temp = 25.0 + (t - 660) / 60.0 * 0.8
        w_warm = WeatherTick(track_temperature=temp, air_temperature=17.0, rainfall=0, humidity=58.0)
        alert = evaluator.record_weather(w_warm, session_time=float(t))

    assert evaluator.crossover_status in (CrossoverStatus.INTERMEDIATE_TO_SLICK, CrossoverStatus.DRY_OPTIMAL)
    assert evaluator.recommended_compound == "SOFT"


def test_wind_vector_decomposition():
    evaluator = EnvironmentalEvaluator()

    # 10 m/s North (0 deg) -> vx = 0, vy = 10
    w_north = WeatherTick(track_temperature=30.0, air_temperature=20.0, wind_speed=10.0, wind_direction=0)
    evaluator.record_weather(w_north, session_time=0.0)
    vx, vy = evaluator.get_wind_vector()
    assert pytest.approx(vx, abs=1e-2) == 0.0
    assert pytest.approx(vy, abs=1e-2) == 10.0

    # 10 m/s East (90 deg) -> vx = 10, vy = 0
    w_east = WeatherTick(track_temperature=30.0, air_temperature=20.0, wind_speed=10.0, wind_direction=90)
    evaluator.record_weather(w_east, session_time=60.0)
    vx, vy = evaluator.get_wind_vector()
    assert pytest.approx(vx, abs=1e-2) == 10.0
    assert pytest.approx(vy, abs=1e-2) == 0.0


def test_thermal_slick_recommendation():
    evaluator = EnvironmentalEvaluator()
    # < 30°C -> SOFT
    assert evaluator.get_thermal_slick_recommendation(24.5) == "SOFT"
    assert evaluator.get_thermal_slick_recommendation(29.9) == "SOFT"
    # 30°C - 45°C -> MEDIUM
    assert evaluator.get_thermal_slick_recommendation(30.0) == "MEDIUM"
    assert evaluator.get_thermal_slick_recommendation(38.0) == "MEDIUM"
    assert evaluator.get_thermal_slick_recommendation(45.0) == "MEDIUM"
    # > 45°C -> HARD
    assert evaluator.get_thermal_slick_recommendation(45.1) == "HARD"
    assert evaluator.get_thermal_slick_recommendation(52.0) == "HARD"


def test_drs_race_control_override_clears_wet_track():
    evaluator = EnvironmentalEvaluator()
    # 1. Start delayed due to rain
    rcm_wet = {"Message": "START PROCEDURE DELAYED - RAIN & STANDING WATER", "Flag": "RED"}
    evaluator.record_race_control(rcm_wet, session_time=0.0)
    assert evaluator.is_track_declared_wet is True
    assert evaluator.recommended_compound == "WET"

    # Add baseline weather observation at 34°C
    w = WeatherTick(track_temperature=34.0, air_temperature=22.0, rainfall=0, humidity=55.0)
    evaluator.record_weather(w, session_time=120.0)

    # 2. Race Director activates DRS / Overtake
    rcm_drs = {"Message": "DRS ENABLED"}
    alert = evaluator.record_race_control(rcm_drs, session_time=240.0)

    assert evaluator.is_track_declared_wet is False
    assert evaluator.race_director_notice is None
    assert evaluator.recommended_compound == "MEDIUM"  # 34°C is in 30-45°C range
    assert evaluator.crossover_status in (CrossoverStatus.DRY_OPTIMAL, CrossoverStatus.INTERMEDIATE_TO_SLICK)
    assert alert is not None
    assert "DRS ENABLED" in alert.message or "OVERTAKE" in alert.message
