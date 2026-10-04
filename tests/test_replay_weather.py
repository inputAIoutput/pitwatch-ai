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
    # Seek to frame 25's session time
    target_time = source.frames[25].session_time
    source.seek_to(target_time)
    assert source._current_index >= 20
    assert source.frames[source._current_index].session_time >= target_time


@pytest.mark.asyncio
async def test_historical_replay_livetiming_positions_and_rcm_ingestion():
    from pitwatch.state.session import LiveSessionState
    state = LiveSessionState(session_key=11731, circuit_name="Bahrain")
    source = await HistoricalReplaySource.from_livetiming(
        session_key=11731,
        time_step=0.2,
        max_frames=60,
    )
    source.bind_state(state)

    # Verify positions are parsed from Position.z
    assert any(len(f.positions) > 0 for f in source.frames)
    first_with_pos = next(f for f in source.frames if f.positions)
    assert first_with_pos.positions[0].driver_number > 0

    # Fast-forward to frame 30
    target_time = source.frames[30].session_time
    source.seek_to(target_time)

    # State should have registered drivers and ingested positions
    assert len(state.drivers) > 0
    drv = next(iter(state.drivers.values()))
    assert drv.driver_number > 0

