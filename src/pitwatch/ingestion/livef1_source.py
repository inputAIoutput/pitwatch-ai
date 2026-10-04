import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional
import requests

from pitwatch.models.frame import (
    CarPositionTick,
    ReplayFrame,
    TelemetryTick,
    WeatherTick,
)
from pitwatch.state.session import LiveSessionState

try:
    from livef1.adapters.realtime_client import RealF1Client
    from livef1.data_processing.etl import function_map
    LIVEF1_AVAILABLE = True
except ImportError:
    LIVEF1_AVAILABLE = False
    RealF1Client = None
    function_map = {}

try:
    from signalrcore.hub_connection_builder import HubConnectionBuilder
    SIGNALRCORE_AVAILABLE = True
except ImportError:
    SIGNALRCORE_AVAILABLE = False
    HubConnectionBuilder = None


class LiveF1Source:
    """Streams real-time Formula 1 session data using official F1 SignalR Core / LiveF1 feed."""

    TOPICS = [
        "Position.z",
        "CarData.z",
        "WeatherData",
        "RaceControlMessages",
        "TrackStatus",
        "TeamRadio",
        "SessionInfo",
        "DriverList",
    ]

    def __init__(
        self,
        session_key: int = 0,
        driver_numbers: Optional[List[int]] = None,
        token: Optional[str] = None,
        f1_cookie: Optional[str] = None,
        poll_interval: float = 0.2,
    ):
        self.session_key = session_key
        self.driver_numbers = driver_numbers
        self.token = token
        self.f1_cookie = f1_cookie or os.environ.get("F1_COOKIE")
        self.poll_interval = poll_interval
        self.state: Optional[LiveSessionState] = None
        self.is_running = True
        self.session_time = 0.0
        self.session_path: str = ""
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

    def resolve_auth_token(self) -> Optional[str]:
        """Resolves the F1 TV subscription JWT token from CLI, env vars, cookies, or FastF1 store."""
        # 1. Explicit token
        if self.token and self.token.strip():
            return self.token.strip()

        # 2. Environment variables
        for env_k in ("F1_TOKEN", "F1_SUBSCRIPTION_TOKEN"):
            val = os.environ.get(env_k)
            if val and val.strip():
                return val.strip()

        # 3. Extract from cookie if provided
        cookie_str = self.f1_cookie or os.environ.get("F1_COOKIE")
        if cookie_str:
            extracted = self._extract_token_from_cookie(cookie_str)
            if extracted:
                return extracted

        # 4. Check FastF1 stored authentication token (~/AppData/Local/fastf1/f1auth.json)
        try:
            from fastf1.internals.f1auth import AUTH_DATA_FILE
            if AUTH_DATA_FILE.exists():
                stored = AUTH_DATA_FILE.read_text(encoding="utf-8").strip()
                if stored:
                    return stored
        except Exception:
            pass

        return None

    @staticmethod
    def _extract_token_from_cookie(cookie_str: str) -> Optional[str]:
        """Extract subscription JWT token from raw string or loginSession cookie."""
        clean = cookie_str.strip()
        if clean.startswith("ey") and clean.count(".") == 2:
            return clean

        import urllib.parse
        for part in clean.split(";"):
            part = part.strip()
            if part.startswith("loginSession="):
                val = part[len("loginSession="):]
                try:
                    decoded = urllib.parse.unquote(val)
                    data = json.loads(decoded)
                    tok = data.get("data", {}).get("subscriptionToken")
                    if tok:
                        return tok
                except Exception:
                    pass
            elif part.startswith("subscriptionToken="):
                return part[len("subscriptionToken="):]
        return None

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

        # 5. Parse Team Radio (TeamRadio)
        radio_list = records.get("TeamRadio", [])
        if radio_list:
            for r in radio_list:
                drv_no_str = r.get("RacingNumber") or r.get("DriverNo")
                path = r.get("Path", "")
                utc = r.get("Utc", "")
                if self.state and path:
                    if not hasattr(self.state, "team_radios"):
                        self.state.team_radios = []
                    self.state.team_radios.append({
                        "driver_number": int(drv_no_str) if drv_no_str and str(drv_no_str).isdigit() else None,
                        "path": path,
                        "utc": utc,
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                    })
                    print(f"[PitWatch AI] [RADIO] Driver #{drv_no_str} Team Radio captured: {path}")

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

    def _start_signalrcore_client(self, loop: asyncio.AbstractEventLoop, token: Optional[str]) -> None:
        """Connects directly to F1 SignalR Core endpoint using websockets with session stickiness and authToken."""
        import websockets

        s = requests.Session()
        negotiate_params = {}
        if token:
            negotiate_params["authToken"] = token

        negotiate_url = "https://livetiming.formula1.com/signalrcore/negotiate"
        headers = {
            "User-Agent": "BestHTTP",
            "Accept-Encoding": "gzip, identity",
        }
        if self.f1_cookie:
            headers["Cookie"] = self.f1_cookie

        try:
            r = s.post(negotiate_url, params=negotiate_params, headers=headers, timeout=10)
            if r.status_code != 200:
                print(f"[PitWatch AI] [WARN] SignalR Core negotiate returned HTTP {r.status_code}: {r.text}")
                return
            data = r.json()
            conn_id = data.get("connectionId")
        except Exception as e:
            print(f"[PitWatch AI] [WARN] Failed to negotiate with F1 SignalR Core: {e}")
            return

        cookie_str = "; ".join(f"{k}={v}" for k, v in s.cookies.items())
        ws_headers = {
            "User-Agent": "BestHTTP",
        }
        if cookie_str:
            ws_headers["Cookie"] = cookie_str

        ws_url = f"wss://livetiming.formula1.com/signalrcore?id={conn_id}"
        if token:
            ws_url += f"&authToken={token}"

        print("[PitWatch AI] Connecting to official Formula 1 Live Timing SignalR Core stream...")

        async def _ws_loop():
            async with websockets.connect(ws_url, additional_headers=ws_headers) as ws:
                # 1. Send protocol handshake
                await ws.send(json.dumps({"protocol": "json", "version": 1}) + chr(0x1e))
                await asyncio.wait_for(ws.recv(), timeout=5.0)

                # 2. Subscribe to topics
                sub_msg = json.dumps({
                    "type": 1,
                    "target": "Subscribe",
                    "arguments": [self.TOPICS]
                }) + chr(0x1e)
                await ws.send(sub_msg)
                print("[PitWatch AI] [CONNECTED] Connected to Formula 1 Live Timing SignalR Core stream!")

                # 3. Message loop
                while self.is_running:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=self.poll_interval)
                        for part in raw.split(chr(0x1e)):
                            if not part.strip():
                                continue
                            try:
                                msg = json.loads(part)
                            except Exception:
                                continue

                            # Handle ping
                            if msg.get("type") == 6:
                                await ws.send(json.dumps({"type": 6}) + chr(0x1e))
                                continue

                            # Handle initial snapshot
                            if msg.get("type") == 3:
                                result = msg.get("result", {})
                                if isinstance(result, dict):
                                    for t, p in result.items():
                                        self._parse_and_enqueue_topic(loop, t, p, None)

                            # Handle live invocation feed
                            elif msg.get("type") == 1 and msg.get("target") == "feed":
                                args = msg.get("arguments", [])
                                if isinstance(args, list) and len(args) >= 2:
                                    t = args[0]
                                    p = args[1]
                                    ts = args[2] if len(args) > 2 else None
                                    self._parse_and_enqueue_topic(loop, t, p, ts)
                    except asyncio.TimeoutError:
                        continue

        try:
            asyncio.run(_ws_loop())
        except Exception as e:
            if not token:
                print(f"[PitWatch AI] [WARN] F1 Live Timing SignalR error (F1 TV authentication required): {e}")
                print("  Authenticate with your F1 TV account:")
                print("    1) Pass --token with authToken from Chrome DevTools")
                print("    2) Or pass --f1-cookie")
            else:
                print(f"[PitWatch AI] [WARN] F1 Live Timing SignalR Core error: {e}")

    def _parse_and_enqueue_topic(self, loop: asyncio.AbstractEventLoop, topic: str, payload: Any, ts: Any) -> None:
        """Parses raw SignalR payload for a given topic using LiveF1 ETL function_map."""
        if topic == "SessionInfo" and isinstance(payload, dict):
            if "Path" in payload:
                self.session_path = payload["Path"]

        if function_map and topic in function_map:
            try:
                recs = list(function_map[topic]([(ts, payload)], sessionKey=self.session_key, session_path=self.session_path))
                if recs:
                    loop.call_soon_threadsafe(self.enqueue_batch, {topic: recs})
            except Exception:
                pass

    def _start_legacy_client(self, loop: asyncio.AbstractEventLoop) -> None:
        """Fallback to RealF1Client legacy SignalR client."""
        try:
            self._client = RealF1Client(topics=self.TOPICS)
            if self.f1_cookie:
                self._client.headers["Cookie"] = self.f1_cookie

            @self._client.callback("pitwatch_collector")
            async def on_records(records):
                loop.call_soon_threadsafe(self.enqueue_batch, records)

            print("[PitWatch AI] Connecting to legacy Formula 1 SignalR stream...")
            self._client.run()
        except Exception as e:
            print(f"[PitWatch AI] [WARN] Legacy SignalR error: {e}")

    def _start_signalr_client(self, loop: asyncio.AbstractEventLoop) -> None:
        """Start SignalR client in background thread (SignalR Core preferred)."""
        token = self.resolve_auth_token()
        if not token:
            print(
                "[PitWatch AI] [INFO] No F1 TV subscription token found.\n"
                "  To authenticate with F1 TV:\n"
                "    1) Run: .\\.venv\\Scripts\\python.exe -m fastf1 auth f1tv --authenticate\n"
                "    2) Or pass --f1-cookie / --token on CLI.\n"
                "  Attempting connection..."
            )

        if SIGNALRCORE_AVAILABLE:
            self._start_signalrcore_client(loop, token)
        elif LIVEF1_AVAILABLE:
            self._start_legacy_client(loop)
        else:
            print("[PitWatch AI] [WARN] Neither signalrcore nor livef1 packages are installed.")

    async def stream_frames(self) -> AsyncIterator[ReplayFrame]:
        """Stream frames to state and subscribers."""
        loop = asyncio.get_running_loop()

        # If running in live mode without manual batches, spawn SignalR client thread
        if (SIGNALRCORE_AVAILABLE or LIVEF1_AVAILABLE) and self._queue.empty() and self.is_running:
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
                await asyncio.sleep(self.poll_interval)
                continue
            except Exception:
                await asyncio.sleep(self.poll_interval)
                continue

