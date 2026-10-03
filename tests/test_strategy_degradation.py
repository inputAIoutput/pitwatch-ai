import pytest
from pitwatch.strategy.degradation import TyreDegradationModel


def test_base_tyre_degradation_rates():
    model = TyreDegradationModel()

    # Soft tyre degrades faster than Medium, which degrades faster than Hard
    soft_wear = model.calculate_lap_time_penalty(compound="SOFT", tyre_age_laps=15, track_temperature=30.0)
    medium_wear = model.calculate_lap_time_penalty(compound="MEDIUM", tyre_age_laps=15, track_temperature=30.0)
    hard_wear = model.calculate_lap_time_penalty(compound="HARD", tyre_age_laps=15, track_temperature=30.0)

    assert soft_wear > medium_wear > hard_wear
    assert hard_wear >= 0.5  # At least 0.5s loss after 15 laps


def test_thermal_degradation_amplification():
    model = TyreDegradationModel()

    # Cold track (20°C) vs Extreme hot track (48°C)
    wear_normal = model.calculate_lap_time_penalty(compound="MEDIUM", tyre_age_laps=20, track_temperature=32.0)
    wear_hot = model.calculate_lap_time_penalty(compound="MEDIUM", tyre_age_laps=20, track_temperature=48.0)

    # Hot track increases thermal degradation
    assert wear_hot > wear_normal


def test_tyre_cliff_detection():
    model = TyreDegradationModel()

    # Beyond recommended stint limit, wear accelerates quadratically (the tyre cliff)
    wear_20 = model.calculate_lap_time_penalty(compound="SOFT", tyre_age_laps=20)
    wear_25 = model.calculate_lap_time_penalty(compound="SOFT", tyre_age_laps=25)

    delta_linear = wear_20 - model.calculate_lap_time_penalty(compound="SOFT", tyre_age_laps=15)
    delta_cliff = wear_25 - wear_20
    assert delta_cliff > delta_linear  # Non-linear cliff drop-off
