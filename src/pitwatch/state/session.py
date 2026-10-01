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
