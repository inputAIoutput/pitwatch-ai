from datetime import datetime, timezone
import pytest
from pitwatch.models.frame import (
    CarPositionTick,
    WeatherTick,
    ReplayFrame,
    TelemetryTick,
    RadioEventTick,
)
from pitwatch.ingestion.replay import HistoricalReplaySource


@pytest.mark.asyncio
async def test_historical_replay_generator_playback():
    test_frames = [
        ReplayFrame(
            session_time=0.0,
            timestamp=datetime(2024, 7, 7, 14, 0, 0, tzinfo=timezone.utc),
            positions=[CarPositionTick(driver_number=44, x=100.0, y=200.0, progress=0.01)],
            weather=WeatherTick(track_temperature=28.0, air_temperature=16.0, rainfall=0),
        ),
        ReplayFrame(
            session_time=0.2,
            timestamp=datetime(2024, 7, 7, 14, 0, 0, 200000, tzinfo=timezone.utc),
            positions=[CarPositionTick(driver_number=44, x=105.0, y=202.0, progress=0.02)],
            weather=WeatherTick(track_temperature=28.0, air_temperature=16.0, rainfall=0),
        ),
        ReplayFrame(
            session_time=0.4,
            timestamp=datetime(2024, 7, 7, 14, 0, 0, 400000, tzinfo=timezone.utc),
            positions=[CarPositionTick(driver_number=44, x=110.0, y=205.0, progress=0.03)],
            weather=WeatherTick(track_temperature=28.0, air_temperature=16.0, rainfall=0),
        ),
    ]

    source = HistoricalReplaySource.from_frames(test_frames, time_step=0.01)
    source.controller.play()

    received_frames = []
    async for frame in source.stream_frames():
        received_frames.append(frame)

    assert len(received_frames) == 3
    assert received_frames[0].session_time == 0.0
    assert received_frames[1].session_time == 0.2
    assert received_frames[2].session_time == 0.4


def test_build_frames_time_bucketing():
    locations_raw = [
        {"date": "2024-07-07T14:00:00.000+00:00", "driver_number": 44, "x": 10.0, "y": 20.0, "z": 0.0},
        {"date": "2024-07-07T14:00:00.050+00:00", "driver_number": 1, "x": 12.0, "y": 22.0, "z": 0.0},
        {"date": "2024-07-07T14:00:00.250+00:00", "driver_number": 44, "x": 30.0, "y": 40.0, "z": 0.0},
        {"date": "2024-07-07T14:00:00.450+00:00", "driver_number": 44, "x": 50.0, "y": 60.0, "z": 0.0},
    ]
    car_data_raw = [
        {"date": "2024-07-07T14:00:00.000+00:00", "driver_number": 44, "speed": 280, "gear": 6, "throttle": 100, "brake": 0, "drs": 1, "rpm": 11000},
        {"date": "2024-07-07T14:00:00.250+00:00", "driver_number": 44, "speed": 290, "gear": 7, "throttle": 100, "brake": 0, "drs": 1, "rpm": 11200},
    ]
    weather_raw = [
        {"date": "2024-07-07T14:00:00.000+00:00", "track_temperature": 32.0, "air_temperature": 20.0, "rainfall": 0, "wind_speed": 4.1}
    ]
    radio_raw = [
        {"date": "2024-07-07T14:00:00.250+00:00", "driver_number": 44, "recording_url": "https://example.com/radio.mp3"}
    ]

    frames = HistoricalReplaySource._build_frames(
        weather_data=weather_raw,
        location_data=locations_raw,
        car_data=car_data_raw,
        radio_data=radio_raw,
        step=0.2,
    )

    # Spans from 0.000 to 0.450 with 0.2s steps -> at least 3 frames (0.0, 0.2, 0.4)
    assert len(frames) >= 3
    # Frame 0 has positions for 44 and 1, telemetry for 44, weather
    assert len(frames[0].positions) == 2
    assert len(frames[0].telemetry) == 1
    assert frames[0].weather is not None
    assert frames[0].weather.track_temperature == 32.0

    # Frame 1 (time 0.2) has the radio event
    assert len(frames[1].radio_events) == 1
    assert frames[1].radio_events[0].recording_url == "https://example.com/radio.mp3"


def test_build_frames_with_laps_and_start_lap():
    locations_raw = [
        {"date": "2024-07-07T13:50:00.000+00:00", "driver_number": 44, "x": 0.0, "y": 0.0, "z": 0.0},
        {"date": "2024-07-07T14:00:00.000+00:00", "driver_number": 44, "x": 100.0, "y": 200.0, "z": 0.0},
        {"date": "2024-07-07T14:00:50.000+00:00", "driver_number": 44, "x": 300.0, "y": 400.0, "z": 0.0},
    ]
    laps_raw = [
        {
            "lap_number": 1,
            "driver_number": 44,
            "date_start": "2024-07-07T14:00:00.000+00:00",
            "lap_duration": 100.0,
        }
    ]

    frames = HistoricalReplaySource._build_frames(
        weather_data=[],
        location_data=locations_raw,
        car_data=[],
        radio_data=[],
        step=10.0,
        laps_data=laps_raw,
        start_lap=1,
    )

    # Frame at 13:50 should be discarded because start_lap=1 begins at 14:00
    assert frames[0].session_time == 0.0
    assert frames[0].positions[0].progress == pytest.approx(0.0, abs=1e-3)

    # Frame at 50s into 100s lap should have ~0.5 progress
    frame_50s = [f for f in frames if pytest.approx(f.session_time, abs=0.1) == 50.0][0]
    assert frame_50s.positions[0].progress == pytest.approx(0.5, abs=1e-2)
