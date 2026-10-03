from datetime import datetime, timezone
import pytest
from pitwatch.ingestion.replay import HistoricalReplaySource


def test_replay_frames_dynamic_weather_bucketing():
    # Construct 3 weather ticks spaced 60s apart
    weather_data = [
        {
            "date": "2024-07-07T14:00:00+00:00",
            "track_temperature": 35.0,
            "air_temperature": 20.0,
            "rainfall": 0,
            "wind_speed": 2.0,
            "humidity": 50.0,
        },
        {
            "date": "2024-07-07T14:01:00+00:00",
            "track_temperature": 32.0,
            "air_temperature": 18.0,
            "rainfall": 1,
            "wind_speed": 3.0,
            "humidity": 70.0,
        },
        {
            "date": "2024-07-07T14:02:00+00:00",
            "track_temperature": 26.0,
            "air_temperature": 16.0,
            "rainfall": 1,
            "wind_speed": 4.0,
            "humidity": 85.0,
        },
    ]

    location_data = [
        {"date": "2024-07-07T14:00:00+00:00", "driver_number": 44, "x": 100.0, "y": 200.0, "z": 0.0},
        {"date": "2024-07-07T14:02:00+00:00", "driver_number": 44, "x": 150.0, "y": 250.0, "z": 0.0},
    ]

    frames = HistoricalReplaySource._build_frames(
        location_data=location_data,
        car_data=[],
        radio_data=[],
        weather_data=weather_data,
        step=60.0,  # 1-minute steps -> bucket 0 (14:00), bucket 1 (14:01), bucket 2 (14:02)
    )

    assert len(frames) >= 3
    # Bucket 0: dry 35.0°C
    assert frames[0].weather is not None
    assert frames[0].weather.track_temperature == 35.0
    assert frames[0].weather.rainfall == 0

    # Bucket 1: rain starts, 32.0°C
    assert frames[1].weather is not None
    assert frames[1].weather.track_temperature == 32.0
    assert frames[1].weather.rainfall == 1

    # Bucket 2: heavy rain, 26.0°C
    assert frames[2].weather is not None
    assert frames[2].weather.track_temperature == 26.0
    assert frames[2].weather.rainfall == 1
