from datetime import datetime, timezone
import pytest
from pitwatch.models.frame import (
    CarPositionTick,
    TelemetryTick,
    WeatherTick,
    RadioEventTick,
    ReplayFrame,
)


def test_car_position_tick_validation():
    tick = CarPositionTick(
        driver_number=44,
        x=120.5,
        y=-45.2,
        z=10.0,
        progress=0.45,
    )
    assert tick.driver_number == 44
    assert tick.x == 120.5
    assert tick.progress == 0.45


def test_telemetry_tick_validation():
    tick = TelemetryTick(
        driver_number=44,
        speed=312,
        gear=7,
        throttle=100,
        brake=0,
        drs=1,
        rpm=11500,
    )
    assert tick.speed == 312
    assert tick.rpm == 11500


def test_replay_frame_composition():
    now = datetime.now(timezone.utc)
    frame = ReplayFrame(
        session_time=123.4,
        timestamp=now,
        positions=[
            CarPositionTick(driver_number=44, x=10.0, y=20.0, progress=0.1)
        ],
        telemetry=[
            TelemetryTick(driver_number=44, speed=312, gear=7, throttle=100, brake=0, drs=1)
        ],
        weather=WeatherTick(track_temperature=32.5, air_temperature=21.0, rainfall=0, wind_speed=3.2),
        radio_events=[
            RadioEventTick(
                driver_number=44,
                recording_url="https://audio.example.com/radio.mp3",
                transcript=None,
            )
        ],
    )
    assert frame.session_time == 123.4
    assert len(frame.positions) == 1
    assert len(frame.telemetry) == 1
    assert len(frame.radio_events) == 1
    assert frame.radio_events[0].recording_url == "https://audio.example.com/radio.mp3"
    assert frame.weather is not None
    assert frame.weather.track_temperature == 32.5
