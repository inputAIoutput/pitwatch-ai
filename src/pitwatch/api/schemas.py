from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class DriverMeta(BaseModel):
    driver_number: int
    driver_code: str
    team_name: str
    current_position: int
    current_compound: str = "UNKNOWN"
    tyre_age_laps: int = 0


class SessionCurrentResponse(BaseModel):
    session_key: int
    circuit_name: str
    year: int = 2024
    session_name: str = "Grand Prix"
    status: str = "active"
    current_session_time: float
    total_drivers: int
    drivers: List[DriverMeta]


class VehicleTelemetrySnapshot(BaseModel):
    driver_number: int
    driver_code: str
    team_name: str
    position: int
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
    interval_ahead: float = 0.0


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
