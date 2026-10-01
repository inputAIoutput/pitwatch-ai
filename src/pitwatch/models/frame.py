from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class CarPositionTick(BaseModel):
    driver_number: int
    x: float
    y: float
    z: Optional[float] = 0.0
    progress: Optional[float] = None


class TelemetryTick(BaseModel):
    driver_number: int
    speed: int
    gear: int
    throttle: int
    brake: int
    drs: int
    rpm: Optional[int] = 0


class WeatherTick(BaseModel):
    track_temperature: float
    air_temperature: float
    rainfall: int = 0
    wind_speed: float = 0.0
    wind_direction: Optional[int] = 0
    humidity: Optional[float] = 0.0


class RadioEventTick(BaseModel):
    driver_number: int
    recording_url: str
    transcript: Optional[str] = None


class ReplayFrame(BaseModel):
    session_time: float
    timestamp: datetime
    positions: List[CarPositionTick] = Field(default_factory=list)
    telemetry: List[TelemetryTick] = Field(default_factory=list)
    weather: Optional[WeatherTick] = None
    radio_events: List[RadioEventTick] = Field(default_factory=list)
