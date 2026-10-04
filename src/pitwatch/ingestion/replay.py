import asyncio
from datetime import datetime, timezone
import math
from typing import AsyncIterator, Dict, List, Optional, Union
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
        self.state = None

    def seek_to(self, target_session_time: float) -> None:
        """Fast-forwards internal frame index and controller to target session_time."""
        self.controller.seek(target_session_time)
        idx = 0
        for i, frame in enumerate(self.frames):
            if frame.session_time >= target_session_time:
                idx = i
                break
        else:
            idx = len(self.frames) - 1 if self.frames else 0
        self._current_index = idx

    def bind_state(self, state) -> None:
        self.state = state
        if hasattr(self, "session_info") and self.session_info and hasattr(state, "update_session_info"):
            state.update_session_info(self.session_info)
        if hasattr(self, "driver_list") and self.driver_list and hasattr(state, "update_driver_list"):
            state.update_driver_list(self.driver_list)

    @classmethod
    def from_frames(cls, frames: List[ReplayFrame], time_step: float = 0.2) -> "HistoricalReplaySource":
        return cls(frames=frames, time_step=time_step)

    @classmethod
    async def from_openf1(
        cls,
        session_key: int,
        driver_number: Optional[Union[int, List[int], str]] = None,
        client: Optional[OpenF1Client] = None,
        time_step: float = 0.2,
        start_lap: Optional[int] = None,
    ) -> "HistoricalReplaySource":
        client = client or OpenF1Client()
        weather_raw = await client.get_weather(session_key)
        radio_raw = await client.get_team_radio(session_key)

        # Normalize driver_number to a list if multiple are provided
        driver_list: Optional[List[int]] = None
        if isinstance(driver_number, int):
            driver_list = [driver_number]
        elif isinstance(driver_number, (list, tuple)):
            driver_list = [int(d) for d in driver_number]
        elif isinstance(driver_number, str):
            driver_list = [int(d.strip()) for d in driver_number.split(",") if d.strip().isdigit()]

        if driver_list:
            locations_raw: List[dict] = []
            car_data_raw: List[dict] = []
            laps_raw: List[dict] = []
            for d in driver_list:
                locs = await client.get_location(session_key, driver_number=d)
                locations_raw.extend(locs)
                cars = await client.get_car_data(session_key, driver_number=d)
                car_data_raw.extend(cars)
                lps = await client.get_laps(session_key, driver_number=d)
                laps_raw.extend(lps)
        else:
            locations_raw = await client.get_location(session_key)
            car_data_raw = await client.get_car_data(session_key)
            laps_raw = await client.get_laps(session_key)

        frames = cls._build_frames(
            weather_data=weather_raw,
            location_data=locations_raw,
            car_data=car_data_raw,
            radio_data=radio_raw,
            step=time_step,
            laps_data=laps_raw,
            start_lap=start_lap,
        )
        return cls(frames=frames, time_step=time_step)

    @staticmethod
    def _build_frames(
        weather_data: List[dict],
        location_data: List[dict],
        car_data: List[dict],
        radio_data: List[dict],
        step: float,
        laps_data: Optional[List[dict]] = None,
        start_lap: Optional[int] = None,
    ) -> List[ReplayFrame]:
        if not location_data:
            return []

        # Find earliest timestamp to anchor session_time 0.0
        parsed_locations = [(_parse_iso(loc["date"]), loc) for loc in location_data if "date" in loc]
        if not parsed_locations:
            return []

        parsed_locations.sort(key=lambda x: x[0])

        parsed_laps = []
        if laps_data:
            for lap in laps_data:
                if "date_start" in lap and lap.get("lap_duration") is not None:
                    l_start = _parse_iso(lap["date_start"])
                    l_dur = float(lap["lap_duration"])
                    parsed_laps.append({
                        "lap_number": int(lap.get("lap_number", 0)),
                        "driver_number": int(lap.get("driver_number", 0)),
                        "start": l_start,
                        "duration": l_dur,
                        "end_ts": l_start.timestamp() + l_dur,
                    })

        # If start_lap is requested, anchor playback start to that lap
        if start_lap is not None and parsed_laps:
            target_laps = [l for l in parsed_laps if l["lap_number"] == start_lap]
            if target_laps:
                target_start = min(l["start"] for l in target_laps)
                parsed_locations = [(dt, loc) for dt, loc in parsed_locations if dt >= target_start]
                if not parsed_locations:
                    return []

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
            offset = (dt - start_time).total_seconds()
            if offset < 0.0:
                continue
            bucket_idx = min(int(offset / step), num_buckets - 1)
            drv = int(loc["driver_number"])

            # Determine lap progress
            prog = None
            if "progress" in loc and loc["progress"] is not None:
                prog = float(loc["progress"])
            elif parsed_laps:
                dt_ts = dt.timestamp()
                for l in parsed_laps:
                    if l["driver_number"] == drv or l["driver_number"] == 0:
                        l_start_ts = l["start"].timestamp()
                        if l_start_ts <= dt_ts <= l["end_ts"]:
                            if l["duration"] > 0:
                                prog = max(0.0, min(1.0, (dt_ts - l_start_ts) / l["duration"]))
                            break

            bucket_positions[bucket_idx][drv] = CarPositionTick(
                driver_number=drv,
                x=float(loc.get("x", 0.0)),
                y=float(loc.get("y", 0.0)),
                z=float(loc.get("z", 0.0)),
                progress=prog,
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
                    gear=int(entry.get("n_gear", entry.get("gear", 0))),
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

        # 4. Map active weather chronologically
        from typing import Tuple
        parsed_weather: List[Tuple[datetime, WeatherTick]] = []
        if weather_data:
            for w in weather_data:
                if "date" in w:
                    w_dt = _parse_iso(w["date"])
                    w_tick = WeatherTick(
                        track_temperature=float(w.get("track_temperature", 0.0)),
                        air_temperature=float(w.get("air_temperature", 0.0)),
                        rainfall=int(w.get("rainfall", 0)),
                        wind_speed=float(w.get("wind_speed", 0.0)),
                        wind_direction=int(w.get("wind_direction", 0)) if "wind_direction" in w else 0,
                        humidity=float(w.get("humidity", 0.0)) if "humidity" in w else 0.0,
                        pressure=float(w.get("pressure", 0.0)) if "pressure" in w else None,
                        timestamp=w_dt,
                    )
                    parsed_weather.append((w_dt, w_tick))
                else:
                    # Weather reading without date (e.g. mock test data without date)
                    w_tick = WeatherTick(
                        track_temperature=float(w.get("track_temperature", 0.0)),
                        air_temperature=float(w.get("air_temperature", 0.0)),
                        rainfall=int(w.get("rainfall", 0)),
                        wind_speed=float(w.get("wind_speed", 0.0)),
                        wind_direction=int(w.get("wind_direction", 0)) if "wind_direction" in w else 0,
                        humidity=float(w.get("humidity", 0.0)) if "humidity" in w else 0.0,
                        pressure=float(w.get("pressure", 0.0)) if "pressure" in w else None,
                    )
                    parsed_weather.append((start_time, w_tick))
            parsed_weather.sort(key=lambda x: x[0])

        # 5. Build chronological ReplayFrame list with active weather
        frames: List[ReplayFrame] = []
        weather_idx = 0
        current_active_weather: Optional[WeatherTick] = parsed_weather[0][1] if parsed_weather else None

        for i in range(num_buckets):
            session_time = round(i * step, 3)
            frame_timestamp = datetime.fromtimestamp(start_time.timestamp() + session_time, tz=timezone.utc)

            # Advance weather pointer up to frame_timestamp
            while weather_idx < len(parsed_weather) and parsed_weather[weather_idx][0] <= frame_timestamp:
                current_active_weather = parsed_weather[weather_idx][1]
                weather_idx += 1

            frames.append(
                ReplayFrame(
                    session_time=session_time,
                    timestamp=frame_timestamp,
                    positions=list(bucket_positions[i].values()),
                    telemetry=list(bucket_telemetry[i].values()),
                    weather=current_active_weather,
                    radio_events=bucket_radio[i],
                )
            )

        return frames

    @classmethod
    async def from_livetiming(
        cls,
        session_key: int = 11731,
        session_path: Optional[str] = None,
        driver_number: Optional[Union[int, List[int], str]] = None,
        time_step: float = 0.2,
        max_frames: Optional[int] = None,
    ) -> "HistoricalReplaySource":
        """Loads historical session records directly from Formula 1 Live Timing archives and builds ReplayFrames."""
        import requests
        import zlib
        import base64
        import json

        base_url = "https://livetiming.formula1.com/static/"
        if not session_path:
            # Discover session path from SessionInfo or default for Sepang/Bahrain 2026
            if session_key == 11731:
                session_path = "2026/2026-10-04_Bahrain_Grand_Prix/2026-10-04_Race/"
            else:
                try:
                    resp = requests.get(f"{base_url}SessionInfo.json", timeout=5)
                    if resp.status_code == 200:
                        s_info = json.loads(resp.content.decode("utf-8-sig"))
                        if s_info.get("Key") == session_key and "Path" in s_info:
                            session_path = s_info["Path"]
                except Exception:
                    pass
        if not session_path:
            session_path = "2026/2026-10-04_Bahrain_Grand_Prix/2026-10-04_Race/"

        # Normalize target drivers
        driver_list: Optional[List[int]] = None
        if isinstance(driver_number, int):
            driver_list = [driver_number]
        elif isinstance(driver_number, (list, tuple)):
            driver_list = [int(d) for d in driver_number]
        elif isinstance(driver_number, str):
            driver_list = [int(d.strip()) for d in driver_number.split(",") if d.strip().isdigit()]

        print(f"[PitWatch AI] [LIVETIMING] Downloading archive feeds for {session_path}...")

        # 1. Fetch static SessionInfo & DriverList
        def _get_json(endpoint: str) -> dict:
            try:
                r = requests.get(f"{base_url}{session_path}{endpoint}", timeout=8)
                if r.status_code == 200:
                    return json.loads(r.content.decode("utf-8-sig"))
            except Exception:
                pass
            return {}

        session_info = _get_json("SessionInfo.json")
        driver_list_data = _get_json("DriverList.json")

        def _get_stream_lines(endpoint: str) -> List[str]:
            try:
                r = requests.get(f"{base_url}{session_path}{endpoint}", timeout=15)
                if r.status_code == 200:
                    return r.content.decode("utf-8-sig").splitlines()
            except Exception:
                pass
            return []

        # Download streams
        car_data_lines = _get_stream_lines("CarData.z.jsonStream")
        pos_lines = _get_stream_lines("Position.z.jsonStream")
        weather_lines = _get_stream_lines("WeatherData.jsonStream")
        if not weather_lines:
            weather_lines = _get_stream_lines("WeatherDataSeries.jsonStream")

        # Parse WeatherData lines
        parsed_weather: List[WeatherTick] = []
        for w_line in weather_lines:
            if len(w_line) > 12:
                try:
                    w_obj = json.loads(w_line[12:])
                    parsed_weather.append(
                        WeatherTick(
                            track_temperature=float(w_obj.get("TrackTemp", 28.0)),
                            air_temperature=float(w_obj.get("AirTemp", 22.0)),
                            rainfall=int(w_obj.get("Rainfall", 0)),
                            wind_speed=float(w_obj.get("WindSpeed", 0.0)),
                            wind_direction=int(float(w_obj.get("WindDirection", 0))),
                            humidity=float(w_obj.get("Humidity", 50.0)),
                            pressure=float(w_obj["Pressure"]) if "Pressure" in w_obj else None,
                        )
                    )
                except Exception:
                    pass

        # Fallback to sample ticks if streams are unreachable
        if not car_data_lines:
            car_data_lines = []

        total_lines = max(len(car_data_lines), len(pos_lines))
        if max_frames:
            total_lines = min(total_lines, max_frames)

        frames: List[ReplayFrame] = []
        base_dt = datetime.now(timezone.utc)

        current_weather_tick = parsed_weather[0] if parsed_weather else WeatherTick(track_temperature=28.0, air_temperature=22.0)

        for i in range(total_lines):
            session_time = round(i * time_step, 3)
            frame_dt = datetime.fromtimestamp(base_dt.timestamp() + session_time, tz=timezone.utc)

            # Advance weather tick proportionally if multiple available
            if parsed_weather:
                w_idx = min(len(parsed_weather) - 1, int((i / max(1, total_lines)) * len(parsed_weather)))
                current_weather_tick = parsed_weather[w_idx]

            tel_ticks: List[TelemetryTick] = []
            pos_ticks: List[CarPositionTick] = []

            # Parse CarData.z line
            if i < len(car_data_lines):
                c_line = car_data_lines[i]
                if len(c_line) > 12:
                    try:
                        raw_b64 = json.loads(c_line[12:])
                        decomp = zlib.decompress(base64.b64decode(raw_b64), -zlib.MAX_WBITS)
                        payload = json.loads(decomp.decode("utf-8-sig"))
                        for entry in payload.get("Entries", []):
                            for d_str, car_obj in entry.get("Cars", {}).items():
                                if not d_str.isdigit():
                                    continue
                                d_num = int(d_str)
                                if d_num >= 100 or (driver_list and d_num not in driver_list):
                                    continue
                                ch = car_obj.get("Channels", {})
                                rpm_val = int(ch.get("0", 0))
                                spd_val = int(ch.get("2", 0))
                                gear_val = int(ch.get("3", 0))
                                thr_val = int(ch.get("4", 0))
                                brk_val = int(ch.get("5", 0))
                                drs_val = int(ch.get("45", 0))

                                tel_ticks.append(
                                    TelemetryTick(
                                        driver_number=d_num,
                                        speed=spd_val,
                                        rpm=rpm_val,
                                        throttle=thr_val,
                                        brake=brk_val,
                                        gear=gear_val,
                                        drs=drs_val,
                                    )
                                )
                    except Exception:
                        pass

            # Parse Position.z line
            if i < len(pos_lines):
                p_line = pos_lines[i]
                if len(p_line) > 12:
                    try:
                        raw_b64 = json.loads(p_line[12:])
                        decomp = zlib.decompress(base64.b64decode(raw_b64), -zlib.MAX_WBITS)
                        payload = json.loads(decomp.decode("utf-8-sig"))
                        for entry in payload.get("Position", []):
                            for entry_data in entry.get("Entries", {}).values():
                                for d_str, p_obj in entry_data.get("Cars", {}).items():
                                    if not d_str.isdigit():
                                        continue
                                    d_num = int(d_str)
                                    if d_num >= 100 or (driver_list and d_num not in driver_list):
                                        continue
                                    pos_ticks.append(
                                        CarPositionTick(
                                            driver_number=d_num,
                                            x=float(p_obj.get("X", 0.0)),
                                            y=float(p_obj.get("Y", 0.0)),
                                            z=float(p_obj.get("Z", 0.0)),
                                        )
                                    )
                    except Exception:
                        pass

            frames.append(
                ReplayFrame(
                    session_time=session_time,
                    timestamp=frame_dt,
                    positions=pos_ticks,
                    telemetry=tel_ticks,
                    weather=current_weather_tick,
                )
            )

        print(f"[PitWatch AI] [LIVETIMING] Constructed {len(frames)} historical replay frames.")
        source = cls(frames=frames, time_step=time_step)
        source.session_info = session_info
        source.driver_list = driver_list_data
        return source

    async def stream_frames(self) -> AsyncIterator[ReplayFrame]:
        while self._current_index < len(self.frames):
            if self.controller.state == PlaybackState.STOPPED:
                break

            if self.controller.state == PlaybackState.PAUSED:
                await asyncio.sleep(0.05)
                continue

            frame = self.frames[self._current_index]
            self.controller.current_session_time = frame.session_time

            # Synchronize bound LiveSessionState if registered
            if self.state is not None:
                self.state.ingest_frame(frame)

            yield frame

            self._current_index += 1
            delay = self.time_step / self.controller.speed_multiplier
            await asyncio.sleep(delay)
