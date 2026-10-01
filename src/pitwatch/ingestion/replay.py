import asyncio
from datetime import datetime, timezone
import math
from typing import AsyncIterator, Dict, List, Optional
from pitwatch.ingestion.source import PlaybackController, PlaybackState, SessionSource
from pitwatch.models.frame import (
    CarPositionTick,
    ReplayFrame,
    TelemetryTick,
    WeatherTick,
    RadioEventTick,
)
from pitwatch.ingestion.openf1_client import OpenF1Client


def _parse_iso(ts_str: str) -> datetime:
    # Handles variable ISO strings from OpenF1
    dt = datetime.fromisoformat(ts_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class HistoricalReplaySource(SessionSource):
    """Loads historical F1 session data and emits sequential frames paced by a virtual clock."""

    def __init__(
        self,
        frames: List[ReplayFrame],
        time_step: float = 0.2,  # 5Hz default
    ):
        self.frames = sorted(frames, key=lambda f: f.session_time)
        self.time_step = time_step
        self.controller = PlaybackController(speed_multiplier=1.0)
        self._current_index = 0

    @classmethod
    def from_frames(cls, frames: List[ReplayFrame], time_step: float = 0.2) -> "HistoricalReplaySource":
        return cls(frames=frames, time_step=time_step)

    @classmethod
    async def from_openf1(
        cls,
        session_key: int,
        client: Optional[OpenF1Client] = None,
        time_step: float = 0.2,
    ) -> "HistoricalReplaySource":
        client = client or OpenF1Client()
        weather_raw = await client.get_weather(session_key)
        locations_raw = await client.get_location(session_key)
        car_data_raw = await client.get_car_data(session_key)
        radio_raw = await client.get_team_radio(session_key)

        frames = cls._build_frames(weather_raw, locations_raw, car_data_raw, radio_raw, time_step)
        return cls(frames=frames, time_step=time_step)

    @staticmethod
    def _build_frames(
        weather_data: List[dict],
        location_data: List[dict],
        car_data: List[dict],
        radio_data: List[dict],
        step: float,
    ) -> List[ReplayFrame]:
        if not location_data:
            return []

        # Find earliest timestamp to anchor session_time 0.0
        parsed_locations = [(_parse_iso(loc["date"]), loc) for loc in location_data if "date" in loc]
        if not parsed_locations:
            return []

        parsed_locations.sort(key=lambda x: x[0])
        start_time = parsed_locations[0][0]
        end_time = parsed_locations[-1][0]
        total_duration = max(0.0, (end_time - start_time).total_seconds())

        num_buckets = max(1, math.ceil(total_duration / step) + 1)

        # Pre-allocate buckets
        bucket_positions: List[Dict[int, CarPositionTick]] = [{} for _ in range(num_buckets)]
        bucket_telemetry: List[Dict[int, TelemetryTick]] = [{} for _ in range(num_buckets)]
        bucket_radio: List[List[RadioEventTick]] = [[] for _ in range(num_buckets)]

        # 1. Bucket locations (keep latest position per driver per bucket)
        for dt, loc in parsed_locations:
            bucket_idx = min(int((dt - start_time).total_seconds() / step), num_buckets - 1)
            drv = int(loc["driver_number"])
            bucket_positions[bucket_idx][drv] = CarPositionTick(
                driver_number=drv,
                x=float(loc.get("x", 0.0)),
                y=float(loc.get("y", 0.0)),
                z=float(loc.get("z", 0.0)),
                progress=float(loc["progress"]) if "progress" in loc and loc["progress"] is not None else None,
            )

        # 2. Bucket car telemetry (keep latest per driver per bucket)
        for entry in car_data:
            if "date" not in entry or "driver_number" not in entry:
                continue
            dt = _parse_iso(entry["date"])
            offset = (dt - start_time).total_seconds()
            if 0.0 <= offset:
                bucket_idx = min(int(offset / step), num_buckets - 1)
                drv = int(entry["driver_number"])
                bucket_telemetry[bucket_idx][drv] = TelemetryTick(
                    driver_number=drv,
                    speed=int(entry.get("speed", 0)),
                    gear=int(entry.get("gear", 0)),
                    throttle=int(entry.get("throttle", 0)),
                    brake=int(entry.get("brake", 0)),
                    drs=int(entry.get("drs", 0)),
                    rpm=int(entry.get("rpm", 0)),
                )

        # 3. Bucket radio events
        for entry in radio_data:
            if "date" not in entry or "driver_number" not in entry:
                continue
            dt = _parse_iso(entry["date"])
            offset = (dt - start_time).total_seconds()
            if 0.0 <= offset:
                bucket_idx = min(int(offset / step), num_buckets - 1)
                bucket_radio[bucket_idx].append(
                    RadioEventTick(
                        driver_number=int(entry["driver_number"]),
                        recording_url=str(entry.get("recording_url", "")),
                        transcript=entry.get("transcript"),
                    )
                )

        # 4. Map active weather
        weather_tick: Optional[WeatherTick] = None
        if weather_data:
            w = weather_data[0]
            weather_tick = WeatherTick(
                track_temperature=float(w.get("track_temperature", 0.0)),
                air_temperature=float(w.get("air_temperature", 0.0)),
                rainfall=int(w.get("rainfall", 0)),
                wind_speed=float(w.get("wind_speed", 0.0)),
                wind_direction=int(w.get("wind_direction", 0)) if "wind_direction" in w else 0,
                humidity=float(w.get("humidity", 0.0)) if "humidity" in w else 0.0,
            )

        # 5. Build chronological ReplayFrame list
        frames: List[ReplayFrame] = []
        for i in range(num_buckets):
            session_time = round(i * step, 3)
            frame_timestamp = datetime.fromtimestamp(start_time.timestamp() + session_time, tz=timezone.utc)
            frames.append(
                ReplayFrame(
                    session_time=session_time,
                    timestamp=frame_timestamp,
                    positions=list(bucket_positions[i].values()),
                    telemetry=list(bucket_telemetry[i].values()),
                    weather=weather_tick,
                    radio_events=bucket_radio[i],
                )
            )

        return frames

    async def stream_frames(self) -> AsyncIterator[ReplayFrame]:
        while self._current_index < len(self.frames):
            if self.controller.state == PlaybackState.STOPPED:
                break

            if self.controller.state == PlaybackState.PAUSED:
                await asyncio.sleep(0.05)
                continue

            frame = self.frames[self._current_index]
            self.controller.current_session_time = frame.session_time
            yield frame

            self._current_index += 1
            delay = self.time_step / self.controller.speed_multiplier
            await asyncio.sleep(delay)
