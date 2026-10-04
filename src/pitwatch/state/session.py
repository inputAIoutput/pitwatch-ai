from datetime import datetime, timezone
from typing import Dict, List, Optional
from pitwatch.models.frame import ReplayFrame, WeatherTick
from pitwatch.state.driver import DriverState, LeaderboardEntry
from pitwatch.state.geometry import CoordinateNormalizer, CircuitBounds
from pitwatch.intelligence.weather import EnvironmentalEvaluator
from pitwatch.strategy.engine import DeterministicStrategyEngine


class LiveSessionState:
    """Maintains real-time in-memory state of the session, normalized positions, and leaderboard."""

    def __init__(
        self,
        session_key: int,
        circuit_name: str = "Unknown",
        year: int = 2026,
        session_name: str = "Grand Prix",
        bounds: Optional[CircuitBounds] = None,
    ):
        self.session_key = session_key
        self.circuit_name = circuit_name
        self.year = year
        self.session_name = session_name
        self.normalizer = (
            CoordinateNormalizer(bounds=bounds)
            if bounds
            else CoordinateNormalizer.for_circuit(circuit_name)
        )
        self.drivers: Dict[int, DriverState] = {}
        self.weather: Optional[WeatherTick] = None
        self.weather_evaluator = EnvironmentalEvaluator()
        self.strategy_engine = DeterministicStrategyEngine(circuit_name=circuit_name)
        self.current_session_time: float = 0.0
        self.leaderboard: List[LeaderboardEntry] = []
        self.drivers_meta_lookup: Dict[int, dict] = {}
        self.stints_by_driver: Dict[int, List[dict]] = {}
        self.laps_by_driver: Dict[int, List[dict]] = {}
        self.positions_by_driver: Dict[int, List[dict]] = {}
        self.team_radios: List[dict] = []
        self.race_control_messages: List[dict] = []

    def update_session_info(self, session_info: dict) -> None:
        """Update session name, circuit, and year from F1 official SessionInfo."""
        meeting = session_info.get("Meeting", {})
        if "Circuit" in meeting and "ShortName" in meeting["Circuit"]:
            self.circuit_name = meeting["Circuit"]["ShortName"]
        elif "Name" in meeting:
            self.circuit_name = meeting["Name"]

        if "Name" in session_info:
            self.session_name = session_info["Name"]

        start_date = session_info.get("StartDate", "")
        if start_date and len(start_date) >= 4 and start_date[:4].isdigit():
            self.year = int(start_date[:4])

    def update_driver_list(self, driver_list: dict) -> None:
        """Populate or update drivers from F1 official DriverList."""
        for drv_no_str, info in driver_list.items():
            if not str(drv_no_str).isdigit():
                continue
            drv_no = int(drv_no_str)
            tla = info.get("Tla", f"D{drv_no}")
            team = info.get("TeamName", "Unknown")
            colour = info.get("TeamColour", "FFFFFF")
            if drv_no in self.drivers:
                self.drivers[drv_no].driver_code = tla
                self.drivers[drv_no].team_name = team
                self.drivers[drv_no].team_colour = colour
            else:
                self.register_driver(
                    driver_number=drv_no,
                    driver_code=tla,
                    team_name=team,
                    team_colour=colour,
                )

    def register_driver(
        self,
        driver_number: int,
        driver_code: str = "DRV",
        team_name: Optional[str] = None,
        team_colour: Optional[str] = None,
        grid_position: Optional[int] = None,
    ) -> DriverState:
        if driver_number not in self.drivers:
            meta = self.drivers_meta_lookup.get(driver_number, {})
            resolved_code = meta.get("driver_code") if driver_code == "DRV" else driver_code
            resolved_team = meta.get("team_name") if (team_name is None or team_name == "Unknown") else team_name
            resolved_colour = meta.get("team_colour") if team_colour is None else team_colour
            pos = (
                self.positions_by_driver[driver_number][0]["position"]
                if (driver_number in self.positions_by_driver and self.positions_by_driver[driver_number])
                else (grid_position or 1)
            )
            self.drivers[driver_number] = DriverState(
                driver_number=driver_number,
                driver_code=resolved_code or driver_code,
                team_name=resolved_team or "Unknown",
                team_colour=resolved_colour,
                grid_position=grid_position,
            )
            self.drivers[driver_number].current_position = pos
            self._apply_stint_for_driver(driver_number)
        return self.drivers[driver_number]

    def load_positions(self, positions_data: List[dict]) -> None:
        """Loads official real-time race position transitions per driver."""
        self.positions_by_driver = {}
        for p in positions_data:
            drv = int(p.get("driver_number", 0))
            if drv <= 0 or "date" not in p or p.get("position") is None:
                continue
            if drv not in self.positions_by_driver:
                self.positions_by_driver[drv] = []

            dt = datetime.fromisoformat(p["date"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            self.positions_by_driver[drv].append({
                "date": dt,
                "timestamp": dt.timestamp(),
                "position": int(p["position"]),
            })
        for drv, p_list in self.positions_by_driver.items():
            p_list.sort(key=lambda x: x["timestamp"])
            if drv in self.drivers and p_list:
                self.drivers[drv].current_position = p_list[0]["position"]

    def load_drivers(self, drivers_data: List[dict], active_driver_numbers: Optional[List[int]] = None) -> None:
        """Loads driver metadata (name acronym, team name, team colour) and registers them.
        If active_driver_numbers is specified, only registers those drivers.
        """
        for d in drivers_data:
            drv_num = int(d.get("driver_number", 0))
            if drv_num <= 0:
                continue
            code = d.get("name_acronym") or d.get("driver_code") or "DRV"
            team = d.get("team_name") or "Unknown"
            colour = d.get("team_colour")
            self.drivers_meta_lookup[drv_num] = {
                "driver_code": code,
                "team_name": team,
                "team_colour": colour,
            }
            if active_driver_numbers is not None and drv_num not in active_driver_numbers:
                continue
            if drv_num in self.drivers:
                self.drivers[drv_num].driver_code = code
                self.drivers[drv_num].team_name = team
                self.drivers[drv_num].team_colour = colour
            else:
                self.register_driver(
                    driver_number=drv_num,
                    driver_code=code,
                    team_name=team,
                    team_colour=colour,
                )

    def load_stints(self, stints_data: List[dict]) -> None:
        """Loads tyre stint records per driver."""
        self.stints_by_driver = {}
        for s in stints_data:
            drv = int(s.get("driver_number", 0))
            if drv <= 0:
                continue
            if drv not in self.stints_by_driver:
                self.stints_by_driver[drv] = []
            self.stints_by_driver[drv].append(s)

        for drv, s_list in self.stints_by_driver.items():
            s_list.sort(key=lambda x: x.get("stint_number", 1))
            if drv in self.drivers:
                self._apply_stint_for_driver(drv)

    def load_laps(self, laps_data: List[dict]) -> None:
        """Loads lap timing records per driver."""
        for lap in laps_data:
            drv = int(lap.get("driver_number", 0))
            if drv <= 0 or "date_start" not in lap or lap.get("lap_duration") is None:
                continue
            if drv not in self.laps_by_driver:
                self.laps_by_driver[drv] = []

            dt = datetime.fromisoformat(lap["date_start"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dur = float(lap["lap_duration"])
            self.laps_by_driver[drv].append({
                "lap_number": int(lap.get("lap_number", 1)),
                "date_start": dt,
                "end_ts": dt.timestamp() + dur,
                "lap_duration": dur,
            })
        for drv, l_list in self.laps_by_driver.items():
            l_list.sort(key=lambda x: x["lap_number"])

    def _apply_stint_for_driver(self, driver_number: int) -> None:
        drv = self.drivers.get(driver_number)
        if not drv:
            return
        stints = self.stints_by_driver.get(driver_number, [])
        if not stints:
            return

        curr_lap = drv.current_lap
        active_stint = None
        for s in stints:
            lap_start = s.get("lap_start") or 1
            lap_end = s.get("lap_end") or 999
            if lap_start <= curr_lap <= lap_end:
                active_stint = s
                break

        if not active_stint and stints:
            active_stint = stints[0]

        if active_stint:
            compound = active_stint.get("compound", "UNKNOWN")
            tyre_age_at_start = int(active_stint.get("tyre_age_at_start", 0))
            lap_start = active_stint.get("lap_start") or 1
            laps_on_tyre = max(0, curr_lap - lap_start)
            drv.set_compound(compound, tyre_age_at_start=tyre_age_at_start + laps_on_tyre)

    def ingest_frame(self, frame: ReplayFrame) -> None:
        self.current_session_time = frame.session_time

        if frame.weather is not None:
            self.weather = frame.weather
            self.weather_evaluator.record_weather(
                tick=frame.weather,
                session_time=frame.session_time,
                timestamp=frame.timestamp,
            )

        # Ingest positions
        for pos in frame.positions:
            drv = self.register_driver(pos.driver_number)
            drv.update_position(pos)

        # Ingest telemetry
        for tel in frame.telemetry:
            drv = self.register_driver(tel.driver_number)
            drv.update_telemetry(tel)

        # Update lap tracking and tyre stints for active drivers
        if frame.timestamp is not None and self.laps_by_driver:
            frame_ts = frame.timestamp.timestamp()
            for drv_num, drv in self.drivers.items():
                laps = self.laps_by_driver.get(drv_num, [])
                if not laps:
                    continue
                completed_laps = [l for l in laps if l["end_ts"] <= frame_ts]
                if completed_laps:
                    last_completed = completed_laps[-1]
                    drv.last_lap_time = last_completed["lap_duration"]
                    drv.current_lap = last_completed["lap_number"] + 1
                else:
                    drv.current_lap = laps[0]["lap_number"]
                self._apply_stint_for_driver(drv_num)

        # Update official race positions if available
        if frame.timestamp is not None and self.positions_by_driver:
            frame_ts = frame.timestamp.timestamp()
            for drv_num, drv in self.drivers.items():
                pos_list = self.positions_by_driver.get(drv_num, [])
                if pos_list:
                    applicable = [p for p in pos_list if p["timestamp"] <= frame_ts]
                    if applicable:
                        drv.current_position = applicable[-1]["position"]

        self._recalculate_leaderboard()

    def _recalculate_leaderboard(self) -> None:
        active_drivers = list(self.drivers.values())
        if not active_drivers:
            self.leaderboard = []
            return

        def sort_key(d: DriverState):
            prog = d.latest_position.progress if d.latest_position and d.latest_position.progress is not None else 0.0
            return (d.current_lap, prog)

        if self.positions_by_driver:
            sorted_drivers = sorted(active_drivers, key=lambda d: d.current_position)
        else:
            sorted_drivers = sorted(active_drivers, key=sort_key, reverse=True)

        leader_progress = sort_key(sorted_drivers[0])[1] if sorted_drivers else 0.0
        prev_progress = leader_progress

        updated_entries: List[LeaderboardEntry] = []
        for i, drv in enumerate(sorted_drivers):
            if not self.positions_by_driver:
                drv.current_position = i + 1
            curr_progress = sort_key(drv)[1]

            LAP_TIME_ESTIMATE = 90.0
            if i == 0:
                drv.gap_to_leader = 0.0
                drv.interval_ahead = 0.0
            else:
                drv.gap_to_leader = round(max(0.0, (leader_progress - curr_progress) * LAP_TIME_ESTIMATE), 3)
                drv.interval_ahead = round(max(0.0, (prev_progress - curr_progress) * LAP_TIME_ESTIMATE), 3)

            prev_progress = curr_progress
            updated_entries.append(drv.to_leaderboard_entry())

        self.leaderboard = updated_entries

    def get_normalized_position(self, driver_number: int) -> Optional[dict]:
        drv = self.drivers.get(driver_number)
        if not drv or not drv.latest_position:
            return None

        nx, ny = self.normalizer.normalize_point(drv.latest_position.x, drv.latest_position.y)
        prog = self.normalizer.normalize_progress(drv.latest_position.progress)
        speed = drv.latest_telemetry.speed if drv.latest_telemetry else 0
        return {
            "driver_number": driver_number,
            "driver_code": drv.driver_code,
            "x": nx,
            "y": ny,
            "progress": prog,
            "speed": speed,
        }

    def get_leaderboard(self) -> List[LeaderboardEntry]:
        return self.leaderboard

    def get_all_normalized_positions(self) -> List[dict]:
        """Returns normalized positions and progress for all registered drivers ordered by race position."""
        positions = []
        if self.leaderboard:
            for entry in self.leaderboard:
                pos = self.get_normalized_position(entry.driver_number)
                if pos is not None:
                    positions.append(pos)
        else:
            for drv_num in sorted(self.drivers.keys()):
                pos = self.get_normalized_position(drv_num)
                if pos is not None:
                    positions.append(pos)
        return positions

    def get_session_summary(self) -> dict:
        """Returns high-level session status and driver metadata."""
        drivers_meta = []
        session_lap = 1
        if self.leaderboard:
            session_lap = self.leaderboard[0].current_lap
            for entry in self.leaderboard:
                drv = self.drivers.get(entry.driver_number)
                drivers_meta.append({
                    "driver_number": entry.driver_number,
                    "driver_code": entry.driver_code,
                    "team_name": drv.team_name if drv else "Unknown",
                    "team_colour": drv.team_colour if drv else None,
                    "current_position": entry.position,
                    "current_lap": entry.current_lap,
                    "current_compound": entry.current_compound,
                    "tyre_age_laps": entry.tyre_age_laps,
                    "last_lap_time": entry.last_lap_time,
                })
        else:
            if self.drivers:
                session_lap = max((d.current_lap for d in self.drivers.values()), default=1)
            for drv_num in sorted(self.drivers.keys()):
                drv = self.drivers[drv_num]
                drivers_meta.append({
                    "driver_number": drv.driver_number,
                    "driver_code": drv.driver_code,
                    "team_name": drv.team_name,
                    "team_colour": drv.team_colour,
                    "current_position": drv.current_position,
                    "current_lap": drv.current_lap,
                    "current_compound": drv.current_compound.value,
                    "tyre_age_laps": drv.tyre_age_laps,
                    "last_lap_time": drv.last_lap_time,
                })
        return {
            "session_key": self.session_key,
            "circuit_name": self.circuit_name,
            "year": self.year,
            "session_name": self.session_name,
            "status": "active",
            "current_session_time": self.current_session_time,
            "current_lap": session_lap,
            "total_laps": self.strategy_engine.total_laps,
            "total_drivers": len(self.drivers),
            "drivers": drivers_meta,
        }

    def get_live_telemetry_snapshot(self) -> dict:
        """Returns instantaneous snapshot of all vehicles with telemetry and coordinates."""
        vehicles = []
        for entry in self.leaderboard:
            drv = self.drivers.get(entry.driver_number)
            if not drv:
                continue
            norm_pos = self.get_normalized_position(entry.driver_number)
            tel = drv.latest_telemetry
            vehicles.append({
                "driver_number": entry.driver_number,
                "driver_code": entry.driver_code,
                "team_name": drv.team_name,
                "team_colour": drv.team_colour,
                "position": entry.position,
                "speed": tel.speed if tel else 0,
                "gear": tel.gear if tel else 0,
                "throttle": tel.throttle if tel else 0,
                "brake": tel.brake if tel else 0,
                "drs": tel.drs if tel else 0,
                "rpm": tel.rpm if tel else 0,
                "x": norm_pos["x"] if norm_pos else 0.0,
                "y": norm_pos["y"] if norm_pos else 0.0,
                "progress": norm_pos["progress"] if norm_pos else 0.0,
                "gap_to_leader": entry.gap_to_leader,
                "interval_ahead": entry.interval_ahead,
            })
        return {
            "session_key": self.session_key,
            "session_time": self.current_session_time,
            "timestamp": datetime.now(timezone.utc),
            "track_temperature": self.weather.track_temperature if self.weather else None,
            "air_temperature": self.weather.air_temperature if self.weather else None,
            "rainfall": self.weather.rainfall if self.weather else 0,
            "vehicles": vehicles,
        }

    def get_current_weather(self) -> dict:
        latest = self.weather or WeatherTick(track_temperature=0.0, air_temperature=0.0)
        vx, vy = self.weather_evaluator.get_wind_vector()
        drift = self.weather_evaluator.get_thermal_drift_rate()
        grip_loss = self.weather_evaluator.project_tyre_grip_loss()
        alert = self.weather_evaluator.active_alert

        return {
            "session_key": self.session_key,
            "session_time": self.current_session_time,
            "timestamp": latest.timestamp,
            "track_temperature": latest.track_temperature,
            "air_temperature": latest.air_temperature,
            "rainfall": latest.rainfall,
            "wind_speed": latest.wind_speed,
            "wind_direction": latest.wind_direction or 0,
            "wind_x": vx,
            "wind_y": vy,
            "humidity": latest.humidity or 0.0,
            "pressure": latest.pressure,
            "thermal_drift_rate": drift,
            "grip_loss_projection": grip_loss,
            "crossover_status": self.weather_evaluator.crossover_status.value,
            "recommended_compound": self.weather_evaluator.recommended_compound,
            "active_alert": alert.model_dump() if alert else None,
        }

    def get_threat_matrix(self) -> dict:
        ordered = []
        if self.leaderboard:
            for entry in self.leaderboard:
                drv = self.drivers.get(entry.driver_number)
                if drv:
                    ordered.append((drv, entry.position, entry.interval_ahead, entry.gap_to_leader))
        else:
            for i, drv_num in enumerate(sorted(self.drivers.keys())):
                drv = self.drivers[drv_num]
                pos = drv.current_position if drv.current_position > 0 else (i + 1)
                ordered.append((drv, pos, drv.interval_ahead, drv.gap_to_leader))

        competitors = []
        track_temp = self.weather.track_temperature if self.weather else 32.0

        for i, (drv, pos, interval_ahead, gap_to_leader) in enumerate(ordered):
            threat = None
            if i < len(ordered) - 1:
                chaser_drv, chaser_pos, chaser_interval, chaser_gap = ordered[i + 1]
                gap = chaser_interval if chaser_interval > 0 else max(0.0, chaser_gap - gap_to_leader)
                threat = self.strategy_engine.assess_undercut_threat(
                    gap_to_chaser_seconds=gap,
                    leader_tyre_age=drv.tyre_age_laps,
                    leader_compound=drv.current_compound.value,
                    track_temperature=track_temp,
                ).model_dump()

            clearance = self.strategy_engine.calculate_rejoin_clearance(
                gap_to_rejoin_car=gap_to_leader + 25.0
            ).model_dump()

            competitors.append({
                "driver_number": drv.driver_number,
                "driver_code": drv.driver_code,
                "position": pos,
                "interval_ahead": interval_ahead,
                "gap_to_leader": gap_to_leader,
                "tyre_compound": drv.current_compound.value,
                "tyre_age_laps": drv.tyre_age_laps,
                "undercut_threat": threat,
                "pit_window_clearance": clearance,
            })

        curr_lap = max((d.current_lap for d in self.drivers.values()), default=1)
        return {
            "session_key": self.session_key,
            "circuit_name": self.circuit_name,
            "pit_transit_loss_seconds": self.strategy_engine.pit_loss,
            "current_lap": curr_lap,
            "total_laps": self.strategy_engine.total_laps,
            "competitors": competitors,
        }


