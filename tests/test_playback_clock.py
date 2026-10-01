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
