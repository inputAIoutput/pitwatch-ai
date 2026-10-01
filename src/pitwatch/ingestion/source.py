from enum import Enum
from typing import AsyncIterator, Protocol
from pitwatch.models.frame import ReplayFrame


class PlaybackState(str, Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


class PlaybackController:
    """Manages virtual playback time, play/pause state, and speed acceleration."""

    def __init__(self, speed_multiplier: float = 1.0):
        self.state = PlaybackState.STOPPED
        self.speed_multiplier = max(0.1, min(speed_multiplier, 20.0))
        self.current_session_time: float = 0.0

    def play(self) -> None:
        self.state = PlaybackState.PLAYING

    def pause(self) -> None:
        self.state = PlaybackState.PAUSED

    def stop(self) -> None:
        self.state = PlaybackState.STOPPED
        self.current_session_time = 0.0

    def set_speed(self, multiplier: float) -> None:
        self.speed_multiplier = max(0.1, min(multiplier, 20.0))

    def seek(self, session_time: float) -> None:
        self.current_session_time = max(0.0, session_time)

    def tick(self, delta_seconds: float) -> None:
        if self.state == PlaybackState.PLAYING:
            self.current_session_time += delta_seconds


class SessionSource(Protocol):
    """Abstract protocol for live and replay Formula 1 session streams."""

    async def stream_frames(self) -> AsyncIterator[ReplayFrame]:
        """Yields sequential or real-time session frames."""
        ...
