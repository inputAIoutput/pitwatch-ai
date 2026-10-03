import asyncio
from datetime import datetime, timezone
from typing import AsyncIterator, List, Optional
from pitwatch.ingestion.openf1_client import OpenF1Client
from pitwatch.models.frame import (
    CarPositionTick,
    ReplayFrame,
    TelemetryTick,
    WeatherTick,
)
from pitwatch.state.session import LiveSessionState


class LiveOpenF1Source:
    """Streams real-time Formula 1 session data via sub-second OpenF1 live polling."""

    def __init__(
        self,
        session_key: int,
        driver_numbers: Optional[List[int]] = None,
        client: Optional[OpenF1Client] = None,
        poll_interval_seconds: float = 0.4,
        max_polls: Optional[int] = None,
    ):
        self.session_key = session_key
        self.driver_numbers = driver_numbers
        self.client = client or OpenF1Client()
        self.poll_interval = poll_interval_seconds
        self.max_polls = max_polls
        self.state: Optional[LiveSessionState] = None
        self.last_timestamp: Optional[datetime] = None
        self.is_running = True

    def bind_state(self, state: LiveSessionState) -> None:
        self.state = state

    def stop(self) -> None:
        self.is_running = False

    async def stream_frames(self) -> AsyncIterator[ReplayFrame]:
        polls_count = 0
        session_time = 0.0

        while self.is_running:
            if self.max_polls is not None and polls_count >= self.max_polls:
                break
            polls_count += 1

            date_gt = self.last_timestamp.isoformat() if self.last_timestamp else None

            try:
                # Concurrent delta fetch for live location, car_data, weather, and position
                weather_task = self.client.get_weather(
                    self.session_key, bypass_cache=True, date_gt=date_gt
                )
                loc_tasks = [
                    self.client.get_location(
                        self.session_key, driver_number=d, bypass_cache=True, date_gt=date_gt
                    )
                    for d in (self.driver_numbers or [None])
                ]
                car_tasks = [
                    self.client.get_car_data(
                        self.session_key, driver_number=d, bypass_cache=True, date_gt=date_gt
                    )
                    for d in (self.driver_numbers or [None])
                ]
                pos_task = self.client.get_positions(
                    self.session_key, bypass_cache=True, date_gt=date_gt
                )

                results = await asyncio.gather(weather_task, pos_task, *loc_tasks, *car_tasks, return_exceptions=True)

                wx_res = results[0] if not isinstance(results[0], Exception) else []
                pos_res = results[1] if not isinstance(results[1], Exception) else []
                loc_res = []
                for r in results[2 : 2 + len(loc_tasks)]:
                    if isinstance(r, list):
                        loc_res.extend(r)
                car_res = []
                for r in results[2 + len(loc_tasks) :]:
                    if isinstance(r, list):
                        car_res.extend(r)

                if pos_res and self.state:
                    self.state.load_positions(pos_res)

                # Parse weather tick
                latest_wx = None
                if wx_res:
                    w = wx_res[-1]
                    latest_wx = WeatherTick(
                        track_temperature=float(w.get("track_temperature", 0.0)),
                        air_temperature=float(w.get("air_temperature", 0.0)),
                        rainfall=int(w.get("rainfall", 0)),
                        wind_speed=float(w.get("wind_speed", 0.0)),
                        wind_direction=int(w.get("wind_direction", 0)),
                        humidity=float(w.get("humidity", 0.0)),
                        pressure=float(w.get("pressure", 1013.25)),
                        timestamp=datetime.fromisoformat(w["date"]) if "date" in w else None,
                    )

                # Parse positions
                positions = []
                for l in loc_res:
                    if "x" in l and "y" in l and "driver_number" in l:
                        positions.append(
                            CarPositionTick(
                                driver_number=int(l["driver_number"]),
                                x=float(l["x"]),
                                y=float(l["y"]),
                                progress=None,
                            )
                        )

                # Parse telemetry
                telemetry = []
                for c in car_res:
                    if "driver_number" in c:
                        telemetry.append(
                            TelemetryTick(
                                driver_number=int(c["driver_number"]),
                                speed=int(c.get("speed", 0)),
                                rpm=int(c.get("rpm", 0)),
                                throttle=int(c.get("throttle", 0)),
                                brake=int(c.get("brake", 0)),
                                gear=int(c.get("n_gear", c.get("gear", 0))),
                                drs=int(c.get("drs", 0)),
                            )
                        )

                # Update timestamp cursor
                now_ts = datetime.now(timezone.utc)
                self.last_timestamp = now_ts
                session_time += self.poll_interval

                frame = ReplayFrame(
                    session_time=session_time,
                    timestamp=now_ts,
                    positions=positions,
                    telemetry=telemetry,
                    weather=latest_wx,
                )

                if self.state:
                    self.state.ingest_frame(frame)

                yield frame

            except Exception:
                await asyncio.sleep(self.poll_interval)
                continue

            await asyncio.sleep(self.poll_interval)
