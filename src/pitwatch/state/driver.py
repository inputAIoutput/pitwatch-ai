from collections import deque
from enum import Enum
from typing import Deque, List, Optional
from pydantic import BaseModel, Field
from pitwatch.models.frame import CarPositionTick, TelemetryTick


class TyreCompound(str, Enum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    UNKNOWN = "UNKNOWN"


class LapSummary(BaseModel):
    lap_number: int
    lap_duration: float
    sector_1_duration: Optional[float] = None
    sector_2_duration: Optional[float] = None
    sector_3_duration: Optional[float] = None
    compound: Optional[str] = "UNKNOWN"


class LeaderboardEntry(BaseModel):
    position: int
    driver_number: int
    driver_code: str
    gap_to_leader: float = 0.0
    interval_ahead: float = 0.0
    current_lap: int = 1
    current_compound: str = "UNKNOWN"
    tyre_age_laps: int = 0
    last_lap_time: Optional[float] = None


class DriverState:
    """Tracks dynamic state, normalized position, and rolling 10-lap history per driver."""

    def __init__(
        self,
        driver_number: int,
        driver_code: str = "DRV",
        team_name: Optional[str] = None,
        grid_position: Optional[int] = None,
    ):
        self.driver_number = driver_number
        self.driver_code = driver_code
        self.team_name = team_name or "Unknown"
        self.grid_position = grid_position or 0
        self.current_position = grid_position or 1
        self.current_lap = 1
        self.current_compound = TyreCompound.UNKNOWN
        self.tyre_age_laps = 0

        self.gap_to_leader = 0.0
        self.interval_ahead = 0.0
        self.last_lap_time: Optional[float] = None

        self.latest_position: Optional[CarPositionTick] = None
        self.latest_telemetry: Optional[TelemetryTick] = None

        # Fixed rolling 10-lap ring buffer
        self.rolling_laps: Deque[LapSummary] = deque(maxlen=10)

    def set_compound(self, compound: TyreCompound) -> None:
        self.current_compound = compound
        self.tyre_age_laps = 0

    def increment_tyre_age(self) -> None:
        self.tyre_age_laps += 1

    def record_lap(self, lap: LapSummary) -> None:
        self.rolling_laps.append(lap)
        self.last_lap_time = lap.lap_duration
        self.current_lap = lap.lap_number + 1
        self.increment_tyre_age()

    def update_telemetry(self, tick: TelemetryTick) -> None:
        self.latest_telemetry = tick

    def update_position(self, tick: CarPositionTick) -> None:
        self.latest_position = tick

    def to_leaderboard_entry(self) -> LeaderboardEntry:
        return LeaderboardEntry(
            position=self.current_position,
            driver_number=self.driver_number,
            driver_code=self.driver_code,
            gap_to_leader=self.gap_to_leader,
            interval_ahead=self.interval_ahead,
            current_lap=self.current_lap,
            current_compound=self.current_compound.value,
            tyre_age_laps=self.tyre_age_laps,
            last_lap_time=self.last_lap_time,
        )
