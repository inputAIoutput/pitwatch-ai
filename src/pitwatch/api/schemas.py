from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field
from pitwatch.state.timing import FastestLapRecord


class DriverMeta(BaseModel):
    driver_number: int
    driver_code: str
    team_name: str
    team_colour: Optional[str] = None
    current_position: int
    current_lap: int = 1
    current_compound: str = "WET"
    tyre_age_laps: int = 0
    last_lap_time: Optional[float] = None
    last_lap_time_formatted: Optional[str] = None
    gap_to_leader: float = 0.0
    gap_to_leader_formatted: str = "LEADER"
    interval_ahead: float = 0.0
    interval_ahead_formatted: str = "-"


class SessionCurrentResponse(BaseModel):
    session_key: int
    circuit_name: str
    year: int = 2024
    session_name: str = "Grand Prix"
    status: str = "active"
    current_session_time: float
    current_lap: int = 1
    total_laps: int = 52
    total_drivers: int
    fastest_lap: Optional[FastestLapRecord] = None
    drivers: List[DriverMeta]


class VehicleTelemetrySnapshot(BaseModel):
    driver_number: int
    driver_code: str
    team_name: str
    team_colour: Optional[str] = None
    position: int
    current_compound: str = "WET"
    speed: int = 0
    gear: int = 0
    throttle: int = 0
    brake: int = 0
    drs: int = 0
    rpm: int = 0
    x: float = 0.0
    y: float = 0.0
    progress: float = 0.0
    gap_to_leader: float = 0.0
    gap_to_leader_formatted: str = "LEADER"
    interval_ahead: float = 0.0
    interval_ahead_formatted: str = "-"
    last_lap_time: Optional[float] = None
    last_lap_time_formatted: Optional[str] = None


class LiveTelemetryResponse(BaseModel):
    session_key: int
    session_time: float
    timestamp: Optional[datetime] = None
    track_temperature: Optional[float] = None
    air_temperature: Optional[float] = None
    rainfall: int = 0
    vehicles: List[VehicleTelemetrySnapshot]


class VehiclePositionPayload(BaseModel):
    driver_number: int
    driver_code: str
    x: float
    y: float
    progress: float
    speed: int = 0


class PositionsStreamMessage(BaseModel):
    type: Literal["positions"] = "positions"
    session_time: float
    timestamp: str
    positions: List[VehiclePositionPayload]


class CrossoverAlertSchema(BaseModel):
    alert_id: str
    timestamp: datetime
    session_time: float
    severity: str
    transition: str
    current_track_temp: float
    thermal_drift_rate: float
    grip_loss_projection: float
    recommended_compound: str
    message: str


class CurrentWeatherResponse(BaseModel):
    session_key: int
    session_time: float
    timestamp: Optional[datetime] = None
    track_temperature: float
    air_temperature: float
    rainfall: int
    wind_speed: float
    wind_direction: int
    wind_x: float
    wind_y: float
    humidity: float
    pressure: Optional[float] = None
    thermal_drift_rate: float
    grip_loss_projection: float
    crossover_status: str
    recommended_compound: str
    slick_ratio: Optional[float] = 0.0
    is_track_declared_wet: Optional[bool] = False
    active_alert: Optional[CrossoverAlertSchema] = None


from pitwatch.strategy.engine import (
    UndercutThreatLevel,
    UndercutAssessment,
    RejoinClearance,
    CompetitorThreatSnapshot,
    ThreatMatrixResponse,
)
from pitwatch.strategy.pirelli import (
    StintPlan,
    RecommendedStrategy,
    CircuitStrategyConfig,
)

