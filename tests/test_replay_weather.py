import pytest
from datetime import datetime, timezone
from pitwatch.models.frame import WeatherTick
from pitwatch.ingestion.replay import HistoricalReplaySource


@pytest.mark.asyncio
async def test_historical_replay_weather_tick_assignment():
    # Verify that from_livetiming creates WeatherTick and attaches it to frames
    source = await HistoricalReplaySource.from_livetiming(
        session_key=11731,
        time_step=0.2,
        max_frames=10,
    )
    assert len(source.frames) == 10
    # Weather is attached to frames
    assert any(f.weather is not None for f in source.frames)
    first_with_weather = next(f for f in source.frames if f.weather is not None)
    assert isinstance(first_with_weather.weather, WeatherTick)
    assert first_with_weather.weather.track_temperature >= 0.0


@pytest.mark.asyncio
async def test_historical_replay_seek_to():
    source = await HistoricalReplaySource.from_livetiming(
        session_key=11731,
        time_step=0.2,
        max_frames=50,
    )
    # Seek to 5.0 seconds
    source.seek_to(5.0)
    assert source._current_index >= 20
    assert source.frames[source._current_index].session_time >= 5.0
