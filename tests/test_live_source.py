import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock
from pitwatch.ingestion.live import LiveOpenF1Source
from pitwatch.state.session import LiveSessionState


@pytest.mark.asyncio
async def test_live_source_streams_frames_into_state():
    mock_client = AsyncMock()
    mock_client.get_weather.return_value = [
        {"date": "2026-10-04T07:05:00.000000+00:00", "track_temperature": 54.0, "air_temperature": 33.0, "rainfall": 0}
    ]
    mock_client.get_location.return_value = [
        {"driver_number": 1, "date": "2026-10-04T07:05:00.100000+00:00", "x": 100.0, "y": 200.0}
    ]
    mock_client.get_car_data.return_value = [
        {"driver_number": 1, "date": "2026-10-04T07:05:00.100000+00:00", "speed": 280, "gear": 6, "throttle": 98, "brake": 0, "drs": 1, "rpm": 11500}
    ]
    mock_client.get_positions.return_value = [
        {"driver_number": 1, "date": "2026-10-04T07:05:00.000000+00:00", "position": 1}
    ]

    source = LiveOpenF1Source(
        session_key=11731,
        driver_numbers=[1],
        client=mock_client,
        poll_interval_seconds=0.01,
        max_polls=2,
    )
    state = LiveSessionState(session_key=11731, circuit_name="Kuala Lumpur")
    source.bind_state(state)

    frames = []
    async for frame in source.stream_frames():
        frames.append(frame)

    assert len(frames) >= 1
    assert state.weather is not None
    assert state.weather.track_temperature == 54.0
    assert 1 in state.drivers
    assert state.drivers[1].latest_telemetry.speed == 280
