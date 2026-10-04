import asyncio
import os
import threading
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
from pitwatch.models.frame import (
    CarPositionTick,
    ReplayFrame,
    TelemetryTick,
    WeatherTick,
)
from pitwatch.state.session import LiveSessionState

try:
    from livef1.adapters.realtime_client import RealF1Client
    LIVEF1_AVAILABLE = True
except ImportError:
    LIVEF1_AVAILABLE = False
    RealF1Client = None


class LiveF1Source:
    """Streams real-time Formula 1 session data using LiveF1 (official F1 SignalR feed)."""

    TOPICS = ["Position.z", "CarData.z", "WeatherData", "RaceControlMessages", "TrackStatus"]

    def __init__(
        self,
        session_key: int = 0,
        driver_numbers: Optional[List[int]] = None,
        f1_cookie: Optional[str] = None,
        poll_interval: float = 0.2,
    ):
        self.session_key = session_key
        self.driver_numbers = driver_numbers
        self.f1_cookie = f1_cookie or os.environ.get("F1_COOKIE")
        self.poll_interval = poll_interval
        self.state: Optional[LiveSessionState] = None
        self.is_running = True
        self.session_time = 0.0
        self._queue: asyncio.Queue = asyncio.Queue()
        self._client = None
        self._client_thread = None

    def bind_state(self, state: LiveSessionState) -> None:
        self.state = state

    def stop(self) -> None:
        self.is_running = False

    def enqueue_batch(self, records: Dict[str, List[Dict[str, Any]]]) -> None:
        """Enqueue parsed LiveF1 batch for asynchronous consumption."""
        self._queue.put_nowait(records)

    def process_records_batch(self, records: Dict[str, List[Dict[str, Any]]]) -> Optional[ReplayFrame]:
        """Transform LiveF1 parsed record dictionary into a PitWatch ReplayFrame."""
        positions: List[CarPositionTick] = []
        telemetry: List[TelemetryTick] = []
        latest_weather: Optional[WeatherTick] = None

        # 1. Parse Positions (Position.z)
        pos_list = records.get("Position.z", [])
        for p in pos_list:
            drv_no_str = p.get("DriverNo")
            if drv_no_str is None:
                continue
            try:
                drv_no = int(drv_no_str)
            except ValueError:
                continue

            if self.driver_numbers and drv_no not in self.driver_numbers:
                continue

            if "X" in p and "Y" in p:
                positions.append(
                    CarPositionTick(
                        driver_number=drv_no,
                        x=float(p["X"]),
                        y=float(p["Y"]),
                        z=float(p.get("Z", 0.0)),
                    )
                )

        # 2. Parse Telemetry (CarData.z)
        car_list = records.get("CarData.z", [])
        for c in car_list:
            drv_no_str = c.get("DriverNo")
            if drv_no_str is None:
                continue
            try:
                drv_no = int(drv_no_str)
            except ValueError:
                continue

            if self.driver_numbers and drv_no not in self.driver_numbers:
                continue

            telemetry.append(
                TelemetryTick(
                    driver_number=drv_no,
                    speed=int(c.get("speed", 0)),
                    rpm=int(c.get("rpm", 0)),
                    throttle=int(c.get("throttle", 0)),
                    brake=int(c.get("brake", 0)),
                    gear=int(c.get("n_gear", 0)),
                    drs=int(c.get("drs", 0)),
                )
            )

        # 3. Parse Weather (WeatherData)
        wx_list = records.get("WeatherData", [])
        if wx_list:
            w = wx_list[-1]
            rainfall_val = str(w.get("Rainfall", "0")).strip().lower()
            rainfall_int = 1 if rainfall_val in ("1", "true", "yes") else 0
            latest_weather = WeatherTick(
                track_temperature=float(w.get("TrackTemp", 0.0)),
                air_temperature=float(w.get("AirTemp", 0.0)),
                rainfall=rainfall_int,
                wind_speed=float(w.get("WindSpeed", 0.0)),
                wind_direction=int(float(w.get("WindDirection", 0))),
                humidity=float(w.get("Humidity", 0.0)),
                pressure=float(w.get("Pressure", 1013.25)),
                timestamp=datetime.now(timezone.utc),
            )

        # 4. Parse Race Control (RaceControlMessages)
        rcm_list = records.get("RaceControlMessages", [])
        if self.state and rcm_list:
            for rcm in rcm_list:
                if not hasattr(self.state, "race_control_messages"):
                    self.state.race_control_messages = []
                self.state.race_control_messages.append(rcm)

        self.session_time += self.poll_interval
        now_ts = datetime.now(timezone.utc)

        frame = ReplayFrame(
            session_time=self.session_time,
            timestamp=now_ts,
            positions=positions,
            telemetry=telemetry,
            weather=latest_weather,
        )

        if self.state:
            self.state.ingest_frame(frame)

        return frame

    def _start_signalr_client(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start RealF1Client SignalR stream in background thread."""
        if not LIVEF1_AVAILABLE:
            print("[PitWatch AI] [WARN] livef1 package is not installed.")
            return

        try:
            self._client = RealF1Client(topics=self.TOPICS)
            if self.f1_cookie:
                self._client.headers["Cookie"] = self.f1_cookie

            @self._client.callback("pitwatch_collector")
            async def on_records(records):
                loop.call_soon_threadsafe(self.enqueue_batch, records)

            print("[PitWatch AI] Connecting to official Formula 1 Live Timing SignalR stream...")
            self._client.run()
        except Exception as e:
            print(f"[PitWatch AI] [WARN] F1 Live Timing SignalR error (F1 TV authentication may be required): {e}")

    async def stream_frames(self) -> AsyncIterator[ReplayFrame]:
        """Stream frames to state and subscribers."""
        loop = asyncio.get_running_loop()

        # If running in live mode without manual batches, spawn SignalR client thread
        if LIVEF1_AVAILABLE and self._queue.empty() and self.is_running:
            self._client_thread = threading.Thread(
                target=self._start_signalr_client, args=(loop,), daemon=True
            )
            self._client_thread.start()

        while self.is_running:
            try:
                batch = await asyncio.wait_for(self._queue.get(), timeout=self.poll_interval)
                frame = self.process_records_batch(batch)
                if frame:
                    yield frame
            except asyncio.TimeoutError:
                # Still yield empty or tick frame if needed
                await asyncio.sleep(self.poll_interval)
                continue
            except Exception as e:
                await asyncio.sleep(self.poll_interval)
                continue
