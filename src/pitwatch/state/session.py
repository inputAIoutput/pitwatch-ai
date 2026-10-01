from datetime import datetime, timezone
from typing import Dict, List, Optional
from pitwatch.models.frame import ReplayFrame, WeatherTick
from pitwatch.state.driver import DriverState, LeaderboardEntry
from pitwatch.state.geometry import CoordinateNormalizer, CircuitBounds


class LiveSessionState:
    """Maintains real-time in-memory state of the session, normalized positions, and leaderboard."""

    def __init__(
        self,
        session_key: int,
        circuit_name: str = "Unknown",
        bounds: Optional[CircuitBounds] = None,
    ):
        self.session_key = session_key
        self.circuit_name = circuit_name
        self.normalizer = (
            CoordinateNormalizer(bounds=bounds)
            if bounds
            else CoordinateNormalizer.for_circuit(circuit_name)
        )
        self.drivers: Dict[int, DriverState] = {}
        self.weather: Optional[WeatherTick] = None
        self.current_session_time: float = 0.0
        self.leaderboard: List[LeaderboardEntry] = []

    def register_driver(
        self,
        driver_number: int,
        driver_code: str = "DRV",
        team_name: Optional[str] = None,
        grid_position: Optional[int] = None,
    ) -> DriverState:
        if driver_number not in self.drivers:
            self.drivers[driver_number] = DriverState(
                driver_number=driver_number,
                driver_code=driver_code,
                team_name=team_name,
                grid_position=grid_position,
            )
        return self.drivers[driver_number]

    def ingest_frame(self, frame: ReplayFrame) -> None:
        self.current_session_time = frame.session_time

        if frame.weather is not None:
            self.weather = frame.weather

        # Ingest positions
        for pos in frame.positions:
            drv = self.register_driver(pos.driver_number)
            drv.update_position(pos)

        # Ingest telemetry
        for tel in frame.telemetry:
            drv = self.register_driver(tel.driver_number)
            drv.update_telemetry(tel)

        self._recalculate_leaderboard()

    def _recalculate_leaderboard(self) -> None:
        active_drivers = list(self.drivers.values())
        if not active_drivers:
            self.leaderboard = []
            return

        def sort_key(d: DriverState):
            prog = d.latest_position.progress if d.latest_position and d.latest_position.progress is not None else 0.0
            return (d.current_lap, prog)

        sorted_drivers = sorted(active_drivers, key=sort_key, reverse=True)

        leader_progress = sort_key(sorted_drivers[0])[1] if sorted_drivers else 0.0
        prev_progress = leader_progress

        updated_entries: List[LeaderboardEntry] = []
        for i, drv in enumerate(sorted_drivers):
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
        for entry in self.leaderboard:
            drv = self.drivers.get(entry.driver_number)
            drivers_meta.append({
                "driver_number": entry.driver_number,
                "driver_code": entry.driver_code,
                "team_name": drv.team_name if drv else "Unknown",
                "current_position": entry.position,
                "current_compound": entry.current_compound,
                "tyre_age_laps": entry.tyre_age_laps,
            })
        return {
            "session_key": self.session_key,
            "circuit_name": self.circuit_name,
            "year": 2024,
            "session_name": "Grand Prix",
            "status": "active",
            "current_session_time": self.current_session_time,
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

