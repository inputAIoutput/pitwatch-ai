import pytest
from pitwatch.ingestion.source import PlaybackController, PlaybackState


def test_playback_controller_state_transitions():
    ctrl = PlaybackController(speed_multiplier=1.0)
    assert ctrl.state == PlaybackState.STOPPED

    ctrl.play()
    assert ctrl.state == PlaybackState.PLAYING

    ctrl.pause()
    assert ctrl.state == PlaybackState.PAUSED

    ctrl.set_speed(5.0)
    assert ctrl.speed_multiplier == 5.0

    ctrl.stop()
    assert ctrl.state == PlaybackState.STOPPED
    assert ctrl.current_session_time == 0.0


def test_virtual_clock_advancement():
    ctrl = PlaybackController(speed_multiplier=1.0)
    ctrl.play()
    ctrl.tick(1.5)
    assert ctrl.current_session_time == 1.5

    ctrl.seek(50.0)
    assert ctrl.current_session_time == 50.0

    ctrl.pause()
    ctrl.tick(2.0)  # should not advance when paused
    assert ctrl.current_session_time == 50.0


@pytest.mark.asyncio
async def test_replay_playback_speed_real_delta():
    import time
    from datetime import datetime, timezone
    from pitwatch.ingestion.replay import HistoricalReplaySource
    from pitwatch.models.frame import ReplayFrame

    # Construct 3 frames with 0.1s session_time difference
    t0 = 100.0
    frames = [
        ReplayFrame(session_time=t0, timestamp=datetime.now(timezone.utc)),
        ReplayFrame(session_time=t0 + 0.05, timestamp=datetime.now(timezone.utc)),
        ReplayFrame(session_time=t0 + 0.10, timestamp=datetime.now(timezone.utc)),
    ]

    source = HistoricalReplaySource(frames=frames, time_step=0.2)
    source.controller.set_speed(1.0)
    source.controller.play()

    start_wall = time.perf_counter()
    streamed = []
    async for f in source.stream_frames():
        streamed.append(f)
    elapsed = time.perf_counter() - start_wall

    assert len(streamed) == 3
    # At 1.0x speed, 0.1s delta should take ~0.1s, not 0.4s (which it would if using time_step=0.2s)
    assert 0.07 <= elapsed <= 0.25
