from collections import deque
import pytest
from pitwatch.state.driver import DriverState, LapSummary, TyreCompound


def test_driver_state_initialization():
    driver = DriverState(
        driver_number=44,
        driver_code="HAM",
        team_name="Mercedes",
        grid_position=2,
    )
    assert driver.driver_number == 44
    assert driver.driver_code == "HAM"
    assert driver.current_lap == 1
    assert driver.current_compound == TyreCompound.UNKNOWN
    assert driver.tyre_age_laps == 0
    assert len(driver.rolling_laps) == 0


def test_rolling_10_lap_ring_buffer_eviction():
    driver = DriverState(driver_number=44, driver_code="HAM")

    # Add 12 consecutive laps
    for lap_num in range(1, 13):
        lap = LapSummary(
            lap_number=lap_num,
            lap_duration=88.5 + (lap_num * 0.1),
            sector_1_duration=28.1,
            sector_2_duration=35.2,
            sector_3_duration=25.2,
            compound="MEDIUM",
        )
        driver.record_lap(lap)

    # Buffer must strictly hold at most 10 laps
    assert len(driver.rolling_laps) == 10
    # The oldest laps (1 and 2) must be evicted; oldest in buffer is lap 3
    assert driver.rolling_laps[0].lap_number == 3
    assert driver.rolling_laps[-1].lap_number == 12
    assert driver.current_lap == 13
    assert driver.tyre_age_laps == 12


def test_tyre_stint_transition():
    driver = DriverState(driver_number=44, driver_code="HAM")
    driver.set_compound(TyreCompound.MEDIUM)
    assert driver.current_compound == TyreCompound.MEDIUM
    assert driver.tyre_age_laps == 0

    driver.increment_tyre_age()
    driver.increment_tyre_age()
    assert driver.tyre_age_laps == 2

    # Pit stop to HARD compound resets age
    driver.set_compound(TyreCompound.HARD)
    assert driver.current_compound == TyreCompound.HARD
    assert driver.tyre_age_laps == 0
