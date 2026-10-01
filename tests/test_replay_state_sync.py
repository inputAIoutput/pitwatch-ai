from datetime import datetime, timezone
import pytest
from pitwatch.models.frame import CarPositionTick, ReplayFrame
from pitwatch.ingestion.replay import HistoricalReplaySource
from pitwatch.state.session import LiveSessionState


@pytest.mark.asyncio
async def test_replay_source_syncs_with_live_session_state():
    test_frames = [
        ReplayFrame(
            session_time=0.0,
            timestamp=datetime(2024, 7, 7, 14, 0, 0, tzinfo=timezone.utc),
            positions=[CarPositionTick(driver_number=44, x=100.0, y=200.0, progress=0.01)],
        ),
        ReplayFrame(
            session_time=0.2,
            timestamp=datetime(2024, 7, 7, 14, 0, 0, 200000, tzinfo=timezone.utc),
            positions=[CarPositionTick(driver_number=44, x=150.0, y=250.0, progress=0.02)],
        ),
    ]

    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    source = HistoricalReplaySource.from_frames(test_frames, time_step=0.01)
    source.bind_state(state)
    source.controller.play()

    frames = []
    async for frame in source.stream_frames():
        frames.append(frame)

    assert len(frames) == 2
    # Verify state updated automatically
    assert state.current_session_time == 0.2
    assert 44 in state.drivers
    assert state.drivers[44].latest_position.progress == 0.02
