from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pitwatch.models.frame import ReplayFrame, WeatherTick
from pitwatch.state.driver import DriverState, LeaderboardEntry, TyreCompound, F1_2026_GRID
from pitwatch.state.geometry import CoordinateNormalizer, CircuitBounds
from pitwatch.state.timing import format_lap_time, format_gap, format_interval, FastestLapRecord
from pitwatch.intelligence.weather import EnvironmentalEvaluator
from pitwatch.intelligence.pace import PaceEvaluator, PaceMonitorResponse
from pitwatch.strategy.engine import DeterministicStrategyEngine


def parse_lap_time(val: Any) -> Optional[float]:
    """Parse lap time string (e.g. '1:50.519' or '58.123') to seconds as float."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val) if float(val) > 0 else None
    if isinstance(val, dict):
        val = val.get("Value")
        if not val:
            return None
    s = str(val).strip()
    if not s or s in ("-", "NO TIME", "IN PIT", "OUT", "DNF", "DNS"):
        return None
    try:
        if ":" in s:
            parts = s.split(":")
            mins = float(parts[0])
            secs = float(parts[1])
            return round(mins * 60.0 + secs, 3)
        return round(float(s), 3)
    except Exception:
        return None


def parse_gap_or_interval(val: Any) -> Optional[float]:
    """Parse gap or interval string (e.g. '+0.967', '+1:01.929', '1 LAP', 'LEADER') to seconds.
    Returns None if missing, blank, unmeasured, or non-numeric placeholder.
    Returns 0.0 only for explicit leader designations.
    """
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return max(0.0, float(val))
    if isinstance(val, dict):
        val = val.get("Value")
        if val is None or val == "":
            return None
    s = str(val).strip()
    if not s or s in ("-", "IN PIT", "OUT", "DNF", "DNS", "PIT", "STOP"):
        return None
    upper = s.upper()
    if upper == "LEADER" or upper == "LAP" or (upper.startswith("LAP ") and not "LAPS" in upper):
        return 0.0
    if "LAP" in upper:
        try:
            cleaned = upper.replace("LAPS", "").replace("LAP", "").replace("+", "").strip()
            if cleaned.isdigit():
                laps = int(cleaned)
                return float(laps * 90.0)
        except Exception:
            pass
        return None

    s_clean = s.lstrip("+").strip()
    if s_clean.startswith("-"):
        s_clean = s_clean.lstrip("-").strip()

    try:
        if ":" in s_clean:
            parts = s_clean.split(":")
            mins = float(parts[0])
            secs = float(parts[1])
            return round(mins * 60.0 + secs, 3)
        return round(float(s_clean), 3)
    except Exception:
        return None


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
        self.pace_evaluator = PaceEvaluator()
        self.strategy_engine = DeterministicStrategyEngine(circuit_name=circuit_name)
        self.current_session_time: float = 0.0
        self.current_lap: int = 1
        self.total_laps: int = self.strategy_engine.total_laps
        self.has_live_timing: bool = False
        self.leaderboard: List[LeaderboardEntry] = []
        self.drivers_meta_lookup: Dict[int, dict] = {}
        self.stints_by_driver: Dict[int, List[dict]] = {}
        self.laps_by_driver: Dict[int, List[dict]] = {}
        self.positions_by_driver: Dict[int, List[dict]] = {}
        self.team_radios: List[dict] = []
        self.race_control_messages: List[dict] = []
        self.fastest_lap: Optional[FastestLapRecord] = None
        self.overtake_enabled: bool = False

        if circuit_name.lower() in ("kuala lumpur", "sepang") or session_key in (11730, 11731):
            self.weather_evaluator.record_race_control(
                {"Message": "START PROCEDURE DELAYED - RAIN & STANDING WATER", "Flag": "RED"},
                0.0,
            )

    def _check_update_fastest_lap(
        self, driver_number: int, lap_time: float, lap_number: Optional[int] = None
    ) -> None:
        """Evaluates whether lap_time beats current session fastest lap benchmark and updates if faster."""
        if lap_time <= 0.0:
            return
        if self.fastest_lap is None or lap_time < self.fastest_lap.lap_time:
            drv = self.drivers.get(driver_number)
            preset = F1_2026_GRID.get(driver_number, {})
            code = drv.driver_code if drv else preset.get("code", f"D{driver_number}")
            team = (drv.team_name if drv and drv.team_name != "Unknown" else None) or preset.get("team", "Formula 1")
            colour = (drv.team_colour if drv else None) or preset.get("colour", "E10600")
            cmp_val = drv.current_compound.value if drv and drv.current_compound != TyreCompound.UNKNOWN else preset.get("compound", TyreCompound.UNKNOWN).value
            lap_num = lap_number or (drv.current_lap if drv else 1)

            self.fastest_lap = FastestLapRecord(
                driver_number=driver_number,
                driver_code=code,
                team_name=team,
                team_colour=colour,
                lap_number=lap_num,
                lap_time=round(lap_time, 3),
                lap_time_formatted=format_lap_time(lap_time) or "",
                compound=cmp_val,
                recorded_at_session_time=self.current_session_time,
            )

    def add_race_control_message(self, rcm: dict) -> None:
        """Appends race control message and evaluates it against weather/track conditions."""
        msg_dict = dict(rcm)
        if "session_time" not in msg_dict:
            msg_dict["session_time"] = self.current_session_time

        msg_text = str(rcm.get("Message") or rcm.get("message") or "")
        cat_text = rcm.get("Category") or rcm.get("category")
        flag_text = rcm.get("Flag") or rcm.get("flag")
        scope_text = rcm.get("Scope") or rcm.get("scope")
        status_text = rcm.get("Status") or rcm.get("status")
        utc_text = rcm.get("Utc") or rcm.get("utc")
        lap_val = rcm.get("Lap") if "Lap" in rcm else rcm.get("lap")

        msg_dict["message"] = msg_text
        if cat_text:
            msg_dict["category"] = cat_text
        if flag_text:
            msg_dict["flag"] = flag_text
        if scope_text:
            msg_dict["scope"] = scope_text
        if status_text:
            msg_dict["status"] = status_text
        if utc_text:
            msg_dict["utc"] = utc_text
        if lap_val is not None:
            msg_dict["lap"] = lap_val

        self.race_control_messages.append(msg_dict)
        self.weather_evaluator.record_race_control(msg_dict, self.current_session_time)

        # Detect Overtake / DRS enabling / disabling from race director
        msg_upper = msg_text.upper()
        if "OVERTAKE ENABLED" in msg_upper or "DRS ENABLED" in msg_upper:
            self.overtake_enabled = True
        elif "OVERTAKE DISABLED" in msg_upper or "DRS DISABLED" in msg_upper:
            self.overtake_enabled = False

    def get_race_control_messages(
        self,
        category: Optional[str] = None,
        flag: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[dict]:
        """Returns chronological list of race control messages up to the current session time."""
        msgs = self.race_control_messages
        if category:
            cat_upper = category.upper()
            msgs = [
                m for m in msgs
                if str(m.get("Category") or m.get("category", "")).upper() == cat_upper
            ]
        if flag:
            flag_upper = flag.upper()
            msgs = [
                m for m in msgs
                if str(m.get("Flag") or m.get("flag", "")).upper() == flag_upper
            ]
        if limit and limit > 0:
            return msgs[-limit:]
        return list(msgs)

    def update_timing_app_data(self, timing_app_data: dict) -> None:
        """Update tyre compound and accurate tyre age (TotalLaps / StartLaps) from TimingAppData."""
        lines = timing_app_data.get("Lines", {})
        if not isinstance(lines, dict):
            return
        for d_no, l_data in lines.items():
            if not str(d_no).isdigit() or not isinstance(l_data, dict):
                continue
            num = int(d_no)
            if num >= 100:
                continue
            drv = self.register_driver(driver_number=num)
            line_val = l_data.get("Line")
            if line_val is not None and str(line_val).isdigit():
                l_pos = int(line_val)
                if l_pos > 0:
                    drv.current_position = l_pos

            stints_raw = l_data.get("Stints")
            if stints_raw:
                if isinstance(stints_raw, dict):
                    for k, s_dict in stints_raw.items():
                        if isinstance(s_dict, dict) and str(k).isdigit():
                            s_idx = int(k)
                            if s_idx not in drv.stints:
                                drv.stints[s_idx] = {}
                            drv.stints[s_idx].update(s_dict)
                elif isinstance(stints_raw, list):
                    for s_idx, s_dict in enumerate(stints_raw):
                        if isinstance(s_dict, dict):
                            if s_idx not in drv.stints:
                                drv.stints[s_idx] = {}
                            drv.stints[s_idx].update(s_dict)

            if drv.stints:
                # Max stint index represents current active stint
                max_stint_idx = max(drv.stints.keys())
                if max_stint_idx > 0:
                    if max_stint_idx > drv.pit_stops:
                        drv.pit_stops = max_stint_idx
                        drv.tyre_age_laps = 0
                    else:
                        drv.pit_stops = max(drv.pit_stops, max_stint_idx)

                curr_stint = drv.stints[max_stint_idx]
                cmp = curr_stint.get("Compound")
                if cmp:
                    drv.set_compound(cmp)

                total_laps = curr_stint.get("TotalLaps")
                start_laps = curr_stint.get("StartLaps")
                if total_laps is not None and str(total_laps).isdigit():
                    drv.tyre_age_laps = int(total_laps)
                elif start_laps is not None and str(start_laps).isdigit() and drv.tyre_age_laps == 0:
                    drv.tyre_age_laps = int(start_laps)

        self._update_grid_slick_ratio()

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

        if not self.weather_evaluator.is_track_declared_wet and (
            any(w in self.circuit_name.lower() for w in ("sepang", "kuala lumpur", "malaysia"))
            or self.session_key in (11730, 11731)
        ):
            self.weather_evaluator.record_race_control(
                {"Message": "START PROCEDURE DELAYED - RAIN & STANDING WATER", "Flag": "RED", "Category": "Flag"},
                self.current_session_time,
            )

    def update_driver_list(self, driver_list: Any) -> None:
        """Populate or update drivers from F1 official DriverList (accepts list of records or dict mapping)."""
        items = []
        if isinstance(driver_list, dict):
            for k, v in driver_list.items():
                if isinstance(v, dict):
                    item = dict(v)
                    item.setdefault("RacingNumber", k)
                    items.append(item)
        elif isinstance(driver_list, list):
            items = driver_list

        for info in items:
            drv_no_val = info.get("RacingNumber") or info.get("DriverNo") or info.get("driver_number")
            if not drv_no_val or not str(drv_no_val).isdigit():
                continue
            drv_no = int(drv_no_val)
            tla = info.get("Tla") or info.get("NameAcronym") or info.get("driver_code")
            team = info.get("TeamName") or info.get("team_name")
            colour = info.get("TeamColour") or info.get("team_colour")

            preset = F1_2026_GRID.get(drv_no, {})
            resolved_tla = tla or preset.get("code") or f"D{drv_no}"
            resolved_team = team if (team and team != "Unknown") else preset.get("team", "Formula 1")
            resolved_colour = colour or preset.get("colour", "E10600")

            self.drivers_meta_lookup[drv_no] = {
                "driver_code": resolved_tla,
                "team_name": resolved_team,
                "team_colour": resolved_colour,
            }
            if drv_no in self.drivers:
                self.drivers[drv_no].driver_code = resolved_tla
                self.drivers[drv_no].team_name = resolved_team
                self.drivers[drv_no].team_colour = resolved_colour
            else:
                self.register_driver(
                    driver_number=drv_no,
                    driver_code=resolved_tla,
                    team_name=resolved_team,
                    team_colour=resolved_colour,
                )

    def update_lap_count(self, lap_count_data: dict) -> None:
        """Update current lap and total laps from F1 LapCount topic."""
        curr = lap_count_data.get("CurrentLap")
        total = lap_count_data.get("TotalLaps")
        if curr is not None:
            try:
                c = int(curr)
                if c > 0:
                    self.current_lap = max(self.current_lap, c)
            except Exception:
                pass
        if total is not None:
            try:
                t = int(total)
                if t > 0:
                    self.total_laps = t
                    self.strategy_engine.total_laps = t
            except Exception:
                pass

    def update_timing_line(self, driver_number_str: str, data: dict) -> None:
        """Update timing metrics (position, gap, interval, lap, lap time) for a driver line."""
        if not str(driver_number_str).isdigit():
            return
        d_no = int(driver_number_str)
        if d_no >= 100:
            return
        drv = self.register_driver(d_no)
        self.has_live_timing = True

        # Position (support string, int, and {"Value": "..."})
        pos_val = data.get("Position") or data.get("Line")
        if pos_val is not None:
            if isinstance(pos_val, dict):
                pos_val = pos_val.get("Value")
            pos_str = str(pos_val).strip()
            if pos_str.isdigit():
                pos_int = int(pos_str)
                if pos_int > 0:
                    drv.current_position = pos_int
                    if pos_int == 1:
                        for other_num, other_drv in self.drivers.items():
                            if other_num != d_no and other_drv.current_position == 1:
                                other_drv.current_position = 0

        # Check retirement / stopped status
        if data.get("Retired") or data.get("Stopped") or data.get("DNF"):
            drv.is_retired = True
            drv.status = "retired" if (data.get("Retired") or data.get("DNF")) else "stopped"
        status_val = str(data.get("Status") or "").upper()
        if status_val in ("RETIRED", "STOPPED", "DNF", "OUT"):
            drv.is_retired = True
            drv.status = status_val.lower()

        # Gap to leader
        if "GapToLeader" in data:
            raw_gap = data["GapToLeader"]
            raw_gap_str = str(raw_gap.get("Value") if isinstance(raw_gap, dict) else raw_gap).upper().strip()
            if any(k in raw_gap_str for k in ("DNF", "OUT", "STOP", "RETIRED")):
                drv.is_retired = True
                drv.status = "retired"
            gap_val = parse_gap_or_interval(raw_gap)
            is_leader_msg = (
                "LEADER" in raw_gap_str
                or (raw_gap_str.startswith("LAP ") and not "LAPS" in raw_gap_str)
                or raw_gap_str == "LAP"
            )
            if is_leader_msg or (gap_val == 0.0 and drv.current_position == 1):
                drv.gap_to_leader = 0.0
                drv.last_known_gap_to_leader = 0.0
                drv.current_position = 1
                for other_num, other_drv in self.drivers.items():
                    if other_num != d_no and other_drv.current_position == 1:
                        other_drv.current_position = 0
            elif gap_val is not None and gap_val > 0.0:
                drv.gap_to_leader = gap_val
                drv.last_known_gap_to_leader = gap_val
                if drv.current_position == 1:
                    drv.current_position = 0
            elif drv.current_position > 1 and drv.last_known_gap_to_leader is not None:
                drv.gap_to_leader = drv.last_known_gap_to_leader

        # Interval to position ahead
        if "IntervalToPositionAhead" in data:
            raw_int = data["IntervalToPositionAhead"]
            inter_val = parse_gap_or_interval(raw_int)
            if drv.current_position == 1:
                drv.interval_ahead = 0.0
                drv.last_known_interval_ahead = 0.0
            elif inter_val is not None and inter_val > 0.0:
                drv.interval_ahead = inter_val
                drv.last_known_interval_ahead = inter_val
                if drv.current_position == 2 and (drv.gap_to_leader == 0.0 or drv.gap_to_leader is None):
                    drv.gap_to_leader = inter_val
                    drv.last_known_gap_to_leader = inter_val
            elif drv.current_position > 1 and drv.last_known_interval_ahead is not None:
                drv.interval_ahead = drv.last_known_interval_ahead

        # Number of laps
        if "NumberOfLaps" in data:
            try:
                nl = int(data["NumberOfLaps"])
                if nl > 0:
                    if nl > drv.current_lap:
                        drv.tyre_age_laps += (nl - drv.current_lap)
                    drv.current_lap = nl
                    self.current_lap = max(self.current_lap, nl)
            except Exception:
                pass

        # Pit tracking & autonomous tyre age reset
        was_in_pit = drv.in_pit
        if "InPit" in data:
            drv.in_pit = bool(data["InPit"])
        if data.get("PitOut"):
            drv.in_pit = False

        if was_in_pit and not drv.in_pit:
            drv.tyre_age_laps = 0

        if "NumberOfPitStops" in data:
            try:
                new_stops = int(data["NumberOfPitStops"])
                if new_stops > drv.pit_stops:
                    drv.pit_stops = new_stops
                    drv.tyre_age_laps = 0
            except Exception:
                pass

        # Last lap time
        if "LastLapTime" in data:
            parsed_ll = parse_lap_time(data["LastLapTime"])
            if parsed_ll is not None:
                drv.last_lap_time = parsed_ll
                if drv.best_lap_time is None or parsed_ll < drv.best_lap_time:
                    drv.best_lap_time = parsed_ll
                self._check_update_fastest_lap(d_no, parsed_ll, drv.current_lap)

                stint_no = drv.pit_stops + 1
                self.pace_evaluator.record_lap(
                    driver_number=d_no,
                    driver_code=drv.driver_code,
                    lap_number=drv.current_lap,
                    lap_time=parsed_ll,
                    stint_number=stint_no,
                    compound=drv.current_compound.value,
                    tyre_age_laps=drv.tyre_age_laps,
                    is_pit_lap=drv.in_pit,
                    session_time=self.current_session_time,
                    current_position=drv.current_position,
                    interval_ahead=drv.interval_ahead,
                    active_race_control_messages=self.race_control_messages,
                )

        # Best lap time
        if "BestLapTime" in data:
            bl_raw = data["BestLapTime"]
            parsed_bl = parse_lap_time(bl_raw)
            lap_num = bl_raw.get("Lap") if isinstance(bl_raw, dict) else drv.current_lap
            if parsed_bl is not None:
                if drv.last_lap_time is None:
                    drv.last_lap_time = parsed_bl
                if drv.best_lap_time is None or parsed_bl < drv.best_lap_time:
                    drv.best_lap_time = parsed_bl
                self._check_update_fastest_lap(d_no, parsed_bl, lap_num)

    def update_timing_record(self, record: dict) -> None:
        """Update timing metrics from a flattened record (e.g. from livef1 function_map)."""
        d_val = record.get("DriverNo") or record.get("RacingNumber")
        if not d_val or not str(d_val).isdigit():
            return
        d_no = int(d_val)
        if d_no >= 100:
            return
        drv = self.register_driver(d_no)
        self.has_live_timing = True

        # Position (support string, int, and {"Value": "..."})
        pos_val = record.get("Position") or record.get("Line")
        if pos_val is not None:
            if isinstance(pos_val, dict):
                pos_val = pos_val.get("Value")
            pos_str = str(pos_val).strip()
            if pos_str.isdigit():
                pos_int = int(pos_str)
                if pos_int > 0:
                    drv.current_position = pos_int

        # Check retirement / stopped status
        if record.get("Retired") or record.get("Stopped") or record.get("DNF"):
            drv.is_retired = True
            drv.status = "retired" if (record.get("Retired") or record.get("DNF")) else "stopped"
        status_val = str(record.get("Status") or "").upper()
        if status_val in ("RETIRED", "STOPPED", "DNF", "OUT"):
            drv.is_retired = True
            drv.status = status_val.lower()

        # Gap to leader
        if "GapToLeader" in record:
            raw_gap = record["GapToLeader"]
            raw_gap_str = str(raw_gap.get("Value") if isinstance(raw_gap, dict) else raw_gap).upper().strip()
            if any(k in raw_gap_str for k in ("DNF", "OUT", "STOP", "RETIRED")):
                drv.is_retired = True
                drv.status = "retired"
            gap_val = parse_gap_or_interval(raw_gap)
            is_leader_msg = (
                "LEADER" in raw_gap_str
                or (raw_gap_str.startswith("LAP ") and not "LAPS" in raw_gap_str)
                or raw_gap_str == "LAP"
            )
            if is_leader_msg or (gap_val == 0.0 and drv.current_position == 1):
                drv.gap_to_leader = 0.0
                drv.last_known_gap_to_leader = 0.0
                drv.current_position = 1
                for other_num, other_drv in self.drivers.items():
                    if other_num != d_no and other_drv.current_position == 1:
                        other_drv.current_position = 0
            elif gap_val is not None and gap_val > 0.0:
                drv.gap_to_leader = gap_val
                drv.last_known_gap_to_leader = gap_val
                if drv.current_position == 1:
                    drv.current_position = 0
            elif drv.current_position > 1 and drv.last_known_gap_to_leader is not None:
                drv.gap_to_leader = drv.last_known_gap_to_leader

        # Interval ahead
        inter_val = record.get("IntervalToPositionAhead_Value") or record.get("IntervalToPositionAhead")
        if inter_val is not None:
            parsed_inter = parse_gap_or_interval(inter_val)
            if drv.current_position == 1:
                drv.interval_ahead = 0.0
                drv.last_known_interval_ahead = 0.0
            elif parsed_inter is not None and parsed_inter > 0.0:
                drv.interval_ahead = parsed_inter
                drv.last_known_interval_ahead = parsed_inter
                if drv.current_position == 2 and (drv.gap_to_leader == 0.0 or drv.gap_to_leader is None):
                    drv.gap_to_leader = parsed_inter
                    drv.last_known_gap_to_leader = parsed_inter
            elif drv.current_position > 1 and drv.last_known_interval_ahead is not None:
                drv.interval_ahead = drv.last_known_interval_ahead

        # Number of laps
        if "NumberOfLaps" in record:
            try:
                nl = int(record["NumberOfLaps"])
                if nl > 0:
                    if nl > drv.current_lap:
                        drv.tyre_age_laps += (nl - drv.current_lap)
                    drv.current_lap = nl
                    self.current_lap = max(self.current_lap, nl)
            except Exception:
                pass

        # Pit tracking & autonomous tyre age reset
        was_in_pit = drv.in_pit
        if "InPit" in record:
            drv.in_pit = bool(record["InPit"])
        if record.get("PitOut"):
            drv.in_pit = False

        if was_in_pit and not drv.in_pit:
            drv.tyre_age_laps = 0

        if "NumberOfPitStops" in record:
            try:
                new_stops = int(record["NumberOfPitStops"])
                if new_stops > drv.pit_stops:
                    drv.pit_stops = new_stops
                    drv.tyre_age_laps = 0
            except Exception:
                pass

        # Last lap time
        ll_val = record.get("LastLapTime_Value") or record.get("LastLapTime")
        if ll_val is not None:
            parsed_ll = parse_lap_time(ll_val)
            if parsed_ll is not None:
                drv.last_lap_time = parsed_ll
                if drv.best_lap_time is None or parsed_ll < drv.best_lap_time:
                    drv.best_lap_time = parsed_ll
                self._check_update_fastest_lap(d_no, parsed_ll, drv.current_lap)

                stint_no = drv.pit_stops + 1
                self.pace_evaluator.record_lap(
                    driver_number=d_no,
                    driver_code=drv.driver_code,
                    lap_number=drv.current_lap,
                    lap_time=parsed_ll,
                    stint_number=stint_no,
                    compound=drv.current_compound.value,
                    tyre_age_laps=drv.tyre_age_laps,
                    is_pit_lap=drv.in_pit,
                    session_time=self.current_session_time,
                    current_position=drv.current_position,
                    interval_ahead=drv.interval_ahead,
                    active_race_control_messages=self.race_control_messages,
                )

        bl_val = record.get("BestLapTime_Value") or record.get("BestLapTime")
        if bl_val is not None:
            parsed_bl = parse_lap_time(bl_val)
            if parsed_bl is not None:
                if drv.last_lap_time is None:
                    drv.last_lap_time = parsed_bl
                if drv.best_lap_time is None or parsed_bl < drv.best_lap_time:
                    drv.best_lap_time = parsed_bl
                self._check_update_fastest_lap(d_no, parsed_bl, drv.current_lap)

    def register_driver(
        self,
        driver_number: int,
        driver_code: str = "DRV",
        team_name: Optional[str] = None,
        team_colour: Optional[str] = None,
        grid_position: Optional[int] = None,
    ) -> DriverState:
        if driver_number >= 100:
            if not hasattr(self, "course_vehicles"):
                self.course_vehicles = {}
            if driver_number not in self.course_vehicles:
                self.course_vehicles[driver_number] = DriverState(
                    driver_number=driver_number,
                    driver_code=f"SC{driver_number}",
                    team_name="Course Safety Car",
                )
            return self.course_vehicles[driver_number]

        if driver_number not in self.drivers:
            preset = F1_2026_GRID.get(driver_number, {})
            meta = self.drivers_meta_lookup.get(driver_number, {})
            resolved_code = (
                meta.get("driver_code")
                or (driver_code if driver_code != "DRV" else None)
                or preset.get("code")
                or f"D{driver_number}"
            )
            resolved_team = (
                meta.get("team_name")
                or (team_name if (team_name and team_name != "Unknown") else None)
                or preset.get("team")
                or "Formula 1"
            )
            resolved_colour = (
                meta.get("team_colour")
                or team_colour
                or preset.get("colour")
                or "E10600"
            )
            pos = (
                self.positions_by_driver[driver_number][0]["position"]
                if (driver_number in self.positions_by_driver and self.positions_by_driver[driver_number])
                else (grid_position or 1)
            )
            compound = preset.get("compound", TyreCompound.WET)
            if self.weather_evaluator.is_track_declared_wet or self.weather_evaluator.recommended_compound in ("WET", "INTERMEDIATE"):
                compound = TyreCompound.WET if self.weather_evaluator.recommended_compound == "WET" else TyreCompound.INTERMEDIATE

            self.drivers[driver_number] = DriverState(
                driver_number=driver_number,
                driver_code=resolved_code,
                team_name=resolved_team,
                team_colour=resolved_colour,
                grid_position=grid_position,
                compound=compound,
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
        self._update_grid_slick_ratio()

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
            stint_idx = int(active_stint.get("stint_number", 1))
            drv.pit_stops = max(drv.pit_stops, max(0, stint_idx - 1))
            drv.stints[stint_idx] = active_stint

    def _update_grid_slick_ratio(self) -> None:
        """Sync active grid tyre compounds into the weather evaluator to trigger slick crossover if >= 50%."""
        active_compounds = [
            d.current_compound.value
            for d in self.drivers.values()
            if d.driver_number < 100
            and not d.is_retired
            and d.current_compound != TyreCompound.UNKNOWN
        ]
        if active_compounds:
            self.weather_evaluator.update_grid_compounds(active_compounds, self.current_session_time)

    def ingest_frame(self, frame: ReplayFrame) -> None:
        self.current_session_time = frame.session_time

        if frame.weather is not None:
            self.weather = frame.weather
            self.weather_evaluator.record_weather(
                tick=frame.weather,
                session_time=frame.session_time,
                timestamp=frame.timestamp,
            )

        # Ingest timing app data (stints & compounds)
        if getattr(frame, "timing_app_data", None):
            self.update_timing_app_data(frame.timing_app_data)

        # Ingest timing data lines (positions, gaps, intervals, lap times)
        if getattr(frame, "timing_data", None):
            lines = frame.timing_data.get("Lines", {})
            if isinstance(lines, dict):
                for d_no, l_data in lines.items():
                    if isinstance(l_data, dict):
                        self.update_timing_line(d_no, l_data)

        # Ingest race control messages
        if getattr(frame, "race_control_messages", None):
            for rcm in frame.race_control_messages:
                self.add_race_control_message(rcm)

        # Ingest positions
        for pos in frame.positions:
            if pos.progress is None:
                pos.progress = self.normalizer.calculate_lap_progress(pos.x, pos.y)
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
                    self._check_update_fastest_lap(drv_num, drv.last_lap_time, last_completed["lap_number"])
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
        active_drivers = [d for d in self.drivers.values() if d.driver_number < 100]
        if not active_drivers:
            self.leaderboard = []
            return

        def sort_key(d: DriverState):
            prog = d.latest_position.progress if d.latest_position and d.latest_position.progress is not None else 0.0
            return (0 if not d.is_retired else 1, d.current_lap, prog)

        has_explicit_positions = any(
            d.current_position > 1 or d.gap_to_leader > 0.0 or d.interval_ahead > 0.0
            for d in active_drivers
        )
        for d in active_drivers:
            if d.current_position == 2 and d.gap_to_leader == 0.0 and d.interval_ahead > 0.0:
                d.gap_to_leader = d.interval_ahead
                d.last_known_gap_to_leader = d.interval_ahead

        has_gaps = any(d.gap_to_leader > 0.0 for d in active_drivers if not d.is_retired)

        if self.has_live_timing or self.positions_by_driver or has_explicit_positions:
            if has_gaps:
                sorted_drivers = sorted(
                    active_drivers,
                    key=lambda d: (
                        1 if d.is_retired else 0,
                        -d.current_lap,
                        d.gap_to_leader if (d.gap_to_leader > 0.0 or d.current_position == 1) else (
                            d.last_known_gap_to_leader if (d.last_known_gap_to_leader and d.last_known_gap_to_leader > 0.0) else (
                                float(d.current_position) if d.current_position > 0 else (
                                    float(d.grid_position) if d.grid_position > 0 else 999.0
                                )
                            )
                        ),
                        d.current_position if d.current_position > 0 else (d.grid_position if d.grid_position > 0 else 999),
                        d.driver_number,
                    ),
                )
            else:
                sorted_drivers = sorted(
                    active_drivers,
                    key=lambda d: (
                        1 if d.is_retired else 0,
                        d.current_position if d.current_position > 0 else (d.grid_position if d.grid_position > 0 else 999),
                        -d.current_lap,
                        d.gap_to_leader if d.gap_to_leader > 0 else 0.0,
                        d.driver_number,
                    ),
                )

            updated_entries: List[LeaderboardEntry] = []
            prev_drv: Optional[DriverState] = None
            is_full_grid = len(active_drivers) >= 15

            for i, drv in enumerate(sorted_drivers):
                if is_full_grid or drv.current_position <= 0:
                    drv.current_position = i + 1

                if i == 0 or drv.current_position == 1:
                    drv.gap_to_leader = 0.0
                    drv.last_known_gap_to_leader = 0.0
                    drv.interval_ahead = 0.0
                    drv.last_known_interval_ahead = 0.0
                else:
                    if drv.gap_to_leader <= 0.0:
                        if drv.last_known_gap_to_leader and drv.last_known_gap_to_leader > 0.0:
                            drv.gap_to_leader = drv.last_known_gap_to_leader

                    if drv.gap_to_leader > 0.0:
                        drv.last_known_gap_to_leader = drv.gap_to_leader

                    if prev_drv:
                        if drv.interval_ahead <= 0.0:
                            if drv.last_known_interval_ahead and drv.last_known_interval_ahead > 0.0:
                                drv.interval_ahead = drv.last_known_interval_ahead
                            elif drv.gap_to_leader > prev_drv.gap_to_leader and drv.current_lap == prev_drv.current_lap:
                                drv.interval_ahead = max(0.001, round(drv.gap_to_leader - prev_drv.gap_to_leader, 3))
                                drv.last_known_interval_ahead = drv.interval_ahead
                            else:
                                drv.interval_ahead = 0.2
                        elif drv.gap_to_leader > 0.0 and prev_drv.gap_to_leader >= 0.0:
                            if drv.current_lap == prev_drv.current_lap and drv.gap_to_leader >= prev_drv.gap_to_leader:
                                drv.interval_ahead = max(0.001, round(drv.gap_to_leader - prev_drv.gap_to_leader, 3))
                                drv.last_known_interval_ahead = drv.interval_ahead

                # Compute DRS / Overtake boost deployment:
                # Driver gets boost if:
                # 1) Race Control enabled Overtake / DRS
                # 2) Interval to car directly ahead on track <= 1.0s (or chasing a lapped car under blue flag)
                # 3) Driver is accelerating (throttle >= 95%, gear >= 6)
                if drv.latest_telemetry:
                    is_in_detection_window = (
                        drv.interval_ahead > 0.0 and drv.interval_ahead <= 1.0
                    ) or (
                        prev_drv and prev_drv.current_lap < drv.current_lap and drv.interval_ahead <= 1.0
                    )
                    is_accelerating = drv.latest_telemetry.throttle >= 95 and drv.latest_telemetry.gear >= 6

                    if self.overtake_enabled and is_in_detection_window and is_accelerating:
                        drv.latest_telemetry.drs = 1
                    elif not self.overtake_enabled:
                        drv.latest_telemetry.drs = 0

                prev_drv = drv
                updated_entries.append(drv.to_leaderboard_entry())

            self.leaderboard = updated_entries
            self._update_grid_slick_ratio()
            return

        sorted_drivers = sorted(
            active_drivers,
            key=lambda d: (
                0 if not d.is_retired else 1,
                -d.current_lap,
                -(d.latest_position.progress if d.latest_position and d.latest_position.progress is not None else 0.0),
                d.driver_number,
            ),
        )
        leader_progress = sort_key(sorted_drivers[0])[2] if sorted_drivers else 0.0
        prev_progress = leader_progress

        updated_entries = []
        for i, drv in enumerate(sorted_drivers):
            drv.current_position = i + 1
            curr_progress = sort_key(drv)[2]

            LAP_TIME_ESTIMATE = 90.0
            if i == 0:
                drv.gap_to_leader = 0.0
                drv.last_known_gap_to_leader = 0.0
                drv.interval_ahead = 0.0
                drv.last_known_interval_ahead = 0.0
            else:
                drv.gap_to_leader = round(max(0.001, (leader_progress - curr_progress) * LAP_TIME_ESTIMATE), 3)
                drv.last_known_gap_to_leader = drv.gap_to_leader
                drv.interval_ahead = round(max(0.001, (prev_progress - curr_progress) * LAP_TIME_ESTIMATE), 3)
                drv.last_known_interval_ahead = drv.interval_ahead

            prev_progress = curr_progress

            # Compute DRS / Overtake boost deployment:
            if drv.latest_telemetry:
                is_in_detection_window = (
                    drv.interval_ahead > 0.0 and drv.interval_ahead <= 1.0
                ) or (
                    i > 0 and sorted_drivers[i - 1].current_lap < drv.current_lap and drv.interval_ahead <= 1.0
                )
                is_accelerating = drv.latest_telemetry.throttle >= 95 and drv.latest_telemetry.gear >= 6

                if self.overtake_enabled and is_in_detection_window and is_accelerating:
                    drv.latest_telemetry.drs = 1
                elif not self.overtake_enabled:
                    drv.latest_telemetry.drs = 0

            updated_entries.append(drv.to_leaderboard_entry())

        self.leaderboard = updated_entries
        self._update_grid_slick_ratio()

    def get_normalized_position(self, driver_number: int) -> Optional[dict]:
        drv = self.drivers.get(driver_number)
        if not drv or not drv.latest_position:
            return None

        nx, ny = self.normalizer.normalize_point(drv.latest_position.x, drv.latest_position.y)
        if drv.latest_position.progress is not None:
            prog = self.normalizer.normalize_progress(drv.latest_position.progress)
        else:
            prog = self.normalizer.calculate_lap_progress(drv.latest_position.x, drv.latest_position.y)
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
        session_lap = self.current_lap

        # Safety net: evaluate fastest_lap if not set
        if self.fastest_lap is None and self.drivers:
            valid_candidates = []
            for d in self.drivers.values():
                if d.driver_number >= 100:
                    continue
                t = getattr(d, "best_lap_time", None) or d.last_lap_time
                if t and t > 0.0:
                    valid_candidates.append((d, t))
            if valid_candidates:
                best_drv, best_t = min(valid_candidates, key=lambda x: x[1])
                self._check_update_fastest_lap(best_drv.driver_number, best_t, best_drv.current_lap)

        if self.leaderboard:
            session_lap = max(self.current_lap, self.leaderboard[0].current_lap, max((e.current_lap for e in self.leaderboard), default=1))
            for entry in self.leaderboard:
                if entry.driver_number >= 100:
                    continue
                drv = self.drivers.get(entry.driver_number)
                preset = F1_2026_GRID.get(entry.driver_number, {})
                team = (drv.team_name if drv and drv.team_name != "Unknown" else None) or preset.get("team", "Formula 1")
                colour = (drv.team_colour if drv else None) or preset.get("colour", "E10600")
                cmp = entry.current_compound
                if cmp in ("UNKNOWN", None, ""):
                    if drv and drv.current_compound != TyreCompound.UNKNOWN:
                        cmp = drv.current_compound.value
                    elif self.weather_evaluator.is_track_declared_wet or self.weather_evaluator.recommended_compound in ("WET", "INTERMEDIATE"):
                        cmp = self.weather_evaluator.recommended_compound
                    else:
                        cmp = preset.get("compound", TyreCompound.WET).value

                ll_time = drv.last_lap_time if (drv and drv.last_lap_time is not None) else entry.last_lap_time
                drivers_meta.append({
                    "driver_number": entry.driver_number,
                    "driver_code": entry.driver_code,
                    "team_name": team,
                    "team_colour": colour,
                    "current_position": entry.position,
                    "current_lap": entry.current_lap,
                    "current_compound": cmp,
                    "tyre_age_laps": drv.tyre_age_laps if drv else entry.tyre_age_laps,
                    "in_pit": drv.in_pit if drv else getattr(entry, "in_pit", False),
                    "pit_stops": drv.pit_stops if drv else getattr(entry, "pit_stops", 0),
                    "last_lap_time": ll_time,
                    "last_lap_time_formatted": format_lap_time(ll_time),
                    "gap_to_leader": entry.gap_to_leader,
                    "gap_to_leader_formatted": entry.gap_to_leader_formatted or format_gap(entry.gap_to_leader, entry.position),
                    "interval_ahead": entry.interval_ahead,
                    "interval_ahead_formatted": entry.interval_ahead_formatted or format_interval(entry.interval_ahead, entry.position),
                })
        else:
            if self.drivers:
                session_lap = max(self.current_lap, max((d.current_lap for d in self.drivers.values()), default=1))
            for drv_num in sorted(self.drivers.keys(), key=lambda n: (self.drivers[n].current_position if self.drivers[n].current_position > 0 else 999, n)):
                if drv_num >= 100:
                    continue
                drv = self.drivers[drv_num]
                preset = F1_2026_GRID.get(drv_num, {})
                team = drv.team_name if drv.team_name != "Unknown" else preset.get("team", "Formula 1")
                colour = drv.team_colour or preset.get("colour", "E10600")
                cmp = (
                    drv.current_compound.value
                    if drv.current_compound != TyreCompound.UNKNOWN
                    else (
                        self.weather_evaluator.recommended_compound
                        if (self.weather_evaluator.is_track_declared_wet or self.weather_evaluator.recommended_compound in ("WET", "INTERMEDIATE"))
                        else preset.get("compound", TyreCompound.WET).value
                    )
                )
                drivers_meta.append({
                    "driver_number": drv.driver_number,
                    "driver_code": drv.driver_code,
                    "team_name": team,
                    "team_colour": colour,
                    "current_position": drv.current_position,
                    "current_lap": drv.current_lap,
                    "current_compound": cmp,
                    "tyre_age_laps": drv.tyre_age_laps,
                    "in_pit": drv.in_pit,
                    "pit_stops": drv.pit_stops,
                    "last_lap_time": drv.last_lap_time,
                    "last_lap_time_formatted": format_lap_time(drv.last_lap_time),
                    "gap_to_leader": drv.gap_to_leader,
                    "gap_to_leader_formatted": format_gap(drv.gap_to_leader, drv.current_position),
                    "interval_ahead": drv.interval_ahead,
                    "interval_ahead_formatted": format_interval(drv.interval_ahead, drv.current_position),
                })

        # Count only active, competing F1 drivers (< 100 and not retired)
        active_f1_drivers = [d for d in self.drivers.values() if d.driver_number < 100 and not d.is_retired]
        total_drivers_count = len(active_f1_drivers) if active_f1_drivers else len([d for d in self.drivers.values() if d.driver_number < 100])

        return {
            "session_key": self.session_key,
            "circuit_name": self.circuit_name,
            "year": self.year,
            "session_name": self.session_name,
            "status": "active",
            "current_session_time": self.current_session_time,
            "current_lap": session_lap,
            "total_laps": self.total_laps or self.strategy_engine.total_laps,
            "total_drivers": total_drivers_count,
            "fastest_lap": self.fastest_lap.model_dump() if self.fastest_lap else None,
            "drivers": drivers_meta,
        }

    def get_live_telemetry_snapshot(self) -> dict:
        """Returns instantaneous snapshot of all vehicles with telemetry, compounds, and coordinates."""
        vehicles = []
        if self.leaderboard:
            for entry in self.leaderboard:
                if entry.driver_number >= 100:
                    continue
                drv = self.drivers.get(entry.driver_number)
                if not drv:
                    continue
                preset = F1_2026_GRID.get(entry.driver_number, {})
                norm_pos = self.get_normalized_position(entry.driver_number)
                tel = drv.latest_telemetry
                team = (drv.team_name if drv.team_name != "Unknown" else None) or preset.get("team", "Formula 1")
                colour = drv.team_colour or preset.get("colour", "E10600")
                cmp = (
                    drv.current_compound.value
                    if drv.current_compound != TyreCompound.UNKNOWN
                    else (
                        self.weather_evaluator.recommended_compound
                        if (self.weather_evaluator.is_track_declared_wet or self.weather_evaluator.recommended_compound in ("WET", "INTERMEDIATE"))
                        else preset.get("compound", TyreCompound.WET).value
                    )
                )
                vehicles.append({
                    "driver_number": entry.driver_number,
                    "driver_code": entry.driver_code,
                    "team_name": team,
                    "team_colour": colour,
                    "current_compound": cmp,
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
                    "gap_to_leader_formatted": entry.gap_to_leader_formatted or format_gap(entry.gap_to_leader, entry.position),
                    "interval_ahead": entry.interval_ahead,
                    "interval_ahead_formatted": entry.interval_ahead_formatted or format_interval(entry.interval_ahead, entry.position),
                    "in_pit": drv.in_pit if drv else getattr(entry, "in_pit", False),
                    "pit_stops": drv.pit_stops if drv else getattr(entry, "pit_stops", 0),
                    "last_lap_time": drv.last_lap_time if drv.last_lap_time is not None else entry.last_lap_time,
                    "last_lap_time_formatted": format_lap_time(drv.last_lap_time if drv.last_lap_time is not None else entry.last_lap_time),
                })
        else:
            for i, drv_num in enumerate(sorted(self.drivers.keys())):
                if drv_num >= 100:
                    continue
                drv = self.drivers[drv_num]
                preset = F1_2026_GRID.get(drv_num, {})
                norm_pos = self.get_normalized_position(drv_num)
                tel = drv.latest_telemetry
                pos = drv.current_position if drv.current_position > 0 else (i + 1)
                team = drv.team_name if drv.team_name != "Unknown" else preset.get("team", "Formula 1")
                colour = drv.team_colour or preset.get("colour", "E10600")
                cmp = (
                    drv.current_compound.value
                    if drv.current_compound != TyreCompound.UNKNOWN
                    else (
                        self.weather_evaluator.recommended_compound
                        if (self.weather_evaluator.is_track_declared_wet or self.weather_evaluator.recommended_compound in ("WET", "INTERMEDIATE"))
                        else preset.get("compound", TyreCompound.WET).value
                    )
                )
                vehicles.append({
                    "driver_number": drv.driver_number,
                    "driver_code": drv.driver_code,
                    "team_name": team,
                    "team_colour": colour,
                    "current_compound": cmp,
                    "position": pos,
                    "speed": tel.speed if tel else 0,
                    "gear": tel.gear if tel else 0,
                    "throttle": tel.throttle if tel else 0,
                    "brake": tel.brake if tel else 0,
                    "drs": tel.drs if tel else 0,
                    "rpm": tel.rpm if tel else 0,
                    "x": norm_pos["x"] if norm_pos else 0.0,
                    "y": norm_pos["y"] if norm_pos else 0.0,
                    "progress": norm_pos["progress"] if norm_pos else 0.0,
                    "gap_to_leader": drv.gap_to_leader,
                    "gap_to_leader_formatted": format_gap(drv.gap_to_leader, pos),
                    "interval_ahead": drv.interval_ahead,
                    "interval_ahead_formatted": format_interval(drv.interval_ahead, pos),
                    "in_pit": drv.in_pit,
                    "pit_stops": drv.pit_stops,
                    "last_lap_time": drv.last_lap_time,
                    "last_lap_time_formatted": format_lap_time(drv.last_lap_time),
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
        self._update_grid_slick_ratio()
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
            "slick_ratio": self.weather_evaluator.slick_ratio,
            "is_track_declared_wet": self.weather_evaluator.is_track_declared_wet,
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

        # Build running order for pit rejoin simulation
        running_order = [
            {
                "driver_number": drv.driver_number,
                "driver_code": drv.driver_code,
                "gap_to_leader": gap_to_leader,
                "position": pos,
                "is_retired": drv.is_retired,
                "in_pit": drv.in_pit,
                "status": drv.status,
            }
            for drv, pos, interval_ahead, gap_to_leader in ordered
        ]

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

            rejoin_sim = self.strategy_engine.simulate_pit_rejoin(
                driver_number=drv.driver_number,
                current_gap_to_leader=gap_to_leader,
                running_order=running_order,
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
                "pit_rejoin": rejoin_sim,
                "pit_window_clearance": rejoin_sim,
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

    def get_pace_monitor(self) -> PaceMonitorResponse:
        """Returns structured pace degradation and anomaly monitor response for active drivers."""
        return self.pace_evaluator.get_pace_monitor(
            session_key=self.session_key,
            session_time=self.current_session_time,
            current_lap=self.current_lap,
        )


