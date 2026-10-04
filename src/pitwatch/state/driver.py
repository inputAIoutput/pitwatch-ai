from collections import deque
from enum import Enum
from typing import Deque, List, Optional, Union
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


F1_2026_GRID = {
    1: {"code": "VER", "team": "Red Bull Racing", "colour": "3671C6", "compound": TyreCompound.WET},
    4: {"code": "NOR", "team": "McLaren", "colour": "FF8000", "compound": TyreCompound.WET},
    81: {"code": "PIA", "team": "McLaren", "colour": "FF8000", "compound": TyreCompound.WET},
    44: {"code": "HAM", "team": "Ferrari", "colour": "E80020", "compound": TyreCompound.WET},
    16: {"code": "LEC", "team": "Ferrari", "colour": "E80020", "compound": TyreCompound.WET},
    63: {"code": "RUS", "team": "Mercedes", "colour": "27F4D2", "compound": TyreCompound.WET},
    12: {"code": "ANT", "team": "Mercedes", "colour": "27F4D2", "compound": TyreCompound.WET},
    14: {"code": "ALO", "team": "Aston Martin", "colour": "229971", "compound": TyreCompound.WET},
    18: {"code": "STR", "team": "Aston Martin", "colour": "229971", "compound": TyreCompound.WET},
    55: {"code": "SAI", "team": "Williams", "colour": "64C4FF", "compound": TyreCompound.WET},
    23: {"code": "ALB", "team": "Williams", "colour": "64C4FF", "compound": TyreCompound.WET},
    10: {"code": "GAS", "team": "Alpine", "colour": "0093CC", "compound": TyreCompound.WET},
    7: {"code": "DOO", "team": "Alpine", "colour": "0093CC", "compound": TyreCompound.WET},
    43: {"code": "COL", "team": "Williams", "colour": "64C4FF", "compound": TyreCompound.WET},
    27: {"code": "HUL", "team": "Sauber", "colour": "52E252", "compound": TyreCompound.WET},
    5: {"code": "BOR", "team": "Sauber", "colour": "52E252", "compound": TyreCompound.WET},
    22: {"code": "TSU", "team": "RB", "colour": "6692FF", "compound": TyreCompound.WET},
    30: {"code": "LAW", "team": "RB", "colour": "6692FF", "compound": TyreCompound.WET},
    6: {"code": "HAD", "team": "RB", "colour": "6692FF", "compound": TyreCompound.WET},
    3: {"code": "RIC", "team": "RB", "colour": "6692FF", "compound": TyreCompound.WET},
    31: {"code": "OCO", "team": "Haas", "colour": "B6BABD", "compound": TyreCompound.WET},
    87: {"code": "BEA", "team": "Haas", "colour": "B6BABD", "compound": TyreCompound.WET},
    11: {"code": "PER", "team": "Red Bull Racing", "colour": "3671C6", "compound": TyreCompound.WET},
    77: {"code": "BOT", "team": "Sauber", "colour": "52E252", "compound": TyreCompound.WET},
    24: {"code": "ZHO", "team": "Sauber", "colour": "52E252", "compound": TyreCompound.WET},
    20: {"code": "MAG", "team": "Haas", "colour": "B6BABD", "compound": TyreCompound.WET},
    2: {"code": "SAR", "team": "Williams", "colour": "64C4FF", "compound": TyreCompound.WET},
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
            interval_ahead=self.interval_ahead,
            current_lap=self.current_lap,
            current_compound=self.current_compound.value,
            tyre_age_laps=self.tyre_age_laps,
            last_lap_time=self.last_lap_time,
        )
