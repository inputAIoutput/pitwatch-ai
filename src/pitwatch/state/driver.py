from collections import deque
from enum import Enum
from typing import Deque, List, Optional, Union
from pydantic import BaseModel, Field
from pitwatch.models.frame import CarPositionTick, TelemetryTick
from pitwatch.state.timing import format_lap_time, format_gap, format_interval


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
    gap_to_leader_formatted: str = "LEADER"
    interval_ahead: float = 0.0
    interval_ahead_formatted: str = "-"
    current_lap: int = 1
    current_compound: str = "UNKNOWN"
    tyre_age_laps: int = 0
    last_lap_time: Optional[float] = None
    last_lap_time_formatted: Optional[str] = None


F1_2026_GRID = {
    3: {"code": "VER", "team": "Red Bull Racing", "colour": "4781D7", "compound": TyreCompound.INTERMEDIATE},
    1: {"code": "NOR", "team": "McLaren", "colour": "F47600", "compound": TyreCompound.MEDIUM},
    44: {"code": "HAM", "team": "Ferrari", "colour": "ED1131", "compound": TyreCompound.SOFT},
    16: {"code": "LEC", "team": "Ferrari", "colour": "ED1131", "compound": TyreCompound.SOFT},
    81: {"code": "PIA", "team": "McLaren", "colour": "F47600", "compound": TyreCompound.MEDIUM},
    12: {"code": "ANT", "team": "Mercedes", "colour": "00D7B6", "compound": TyreCompound.INTERMEDIATE},
    63: {"code": "RUS", "team": "Mercedes", "colour": "00D7B6", "compound": TyreCompound.INTERMEDIATE},
    6: {"code": "HAD", "team": "Red Bull Racing", "colour": "4781D7", "compound": TyreCompound.INTERMEDIATE},
    10: {"code": "GAS", "team": "Alpine", "colour": "00A1E8", "compound": TyreCompound.SOFT},
    43: {"code": "COL", "team": "Alpine", "colour": "00A1E8", "compound": TyreCompound.SOFT},
    5: {"code": "BOR", "team": "Audi", "colour": "F50537", "compound": TyreCompound.SOFT},
    27: {"code": "HUL", "team": "Audi", "colour": "F50537", "compound": TyreCompound.SOFT},
    30: {"code": "LAW", "team": "Racing Bulls", "colour": "6C98FF", "compound": TyreCompound.INTERMEDIATE},
    41: {"code": "LIN", "team": "Racing Bulls", "colour": "6C98FF", "compound": TyreCompound.INTERMEDIATE},
    14: {"code": "ALO", "team": "Aston Martin", "colour": "229971", "compound": TyreCompound.MEDIUM},
    18: {"code": "STR", "team": "Aston Martin", "colour": "229971", "compound": TyreCompound.MEDIUM},
    55: {"code": "SAI", "team": "Williams", "colour": "1868DB", "compound": TyreCompound.INTERMEDIATE},
    23: {"code": "ALB", "team": "Williams", "colour": "1868DB", "compound": TyreCompound.INTERMEDIATE},
    87: {"code": "BEA", "team": "Haas F1 Team", "colour": "9C9FA2", "compound": TyreCompound.SOFT},
    31: {"code": "OCO", "team": "Haas F1 Team", "colour": "9C9FA2", "compound": TyreCompound.INTERMEDIATE},
    77: {"code": "BOT", "team": "Cadillac", "colour": "909090", "compound": TyreCompound.SOFT},
    11: {"code": "PER", "team": "Cadillac", "colour": "909090", "compound": TyreCompound.INTERMEDIATE},
}


class DriverState:
    """Tracks dynamic state, normalized position, and rolling 10-lap history per driver."""

    def __init__(
        self,
        driver_number: int,
        driver_code: str = "DRV",
        team_name: Optional[str] = None,
        team_colour: Optional[str] = None,
        grid_position: Optional[int] = None,
        compound: TyreCompound = TyreCompound.UNKNOWN,
    ):
        preset = F1_2026_GRID.get(driver_number, {})
        self.driver_number = driver_number
        self.driver_code = driver_code if driver_code != "DRV" else preset.get("code", f"D{driver_number}")
        self.team_name = team_name if (team_name and team_name != "Unknown") else preset.get("team", "Formula 1")
        self.team_colour = team_colour or preset.get("colour", "E10600")
        self.grid_position = grid_position or 0
        self.current_position = grid_position or 1
        self.current_lap = 1
        self.current_compound = compound
        self.tyre_age_laps = 0

        self.gap_to_leader = 0.0
        self.interval_ahead = 0.0
        self.last_lap_time: Optional[float] = None
        self.best_lap_time: Optional[float] = None
        self.is_retired: bool = False
        self.in_pit: bool = False
        self.status: str = "active"

        self.latest_position: Optional[CarPositionTick] = None
        self.latest_telemetry: Optional[TelemetryTick] = None

        # Fixed rolling 10-lap ring buffer
        self.rolling_laps: Deque[LapSummary] = deque(maxlen=10)

    def set_compound(self, compound: Union[TyreCompound, str], tyre_age_at_start: int = 0) -> None:
        if isinstance(compound, str):
            try:
                self.current_compound = TyreCompound(compound.upper())
            except ValueError:
                self.current_compound = TyreCompound.UNKNOWN
        else:
            self.current_compound = compound
        self.tyre_age_laps = tyre_age_at_start

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
            gap_to_leader_formatted=format_gap(self.gap_to_leader, self.current_position),
            interval_ahead=self.interval_ahead,
            interval_ahead_formatted=format_interval(self.interval_ahead, self.current_position),
            current_lap=self.current_lap,
            current_compound=self.current_compound.value,
            tyre_age_laps=self.tyre_age_laps,
            last_lap_time=self.last_lap_time,
            last_lap_time_formatted=format_lap_time(self.last_lap_time),
        )
