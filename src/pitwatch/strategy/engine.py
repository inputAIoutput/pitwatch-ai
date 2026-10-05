from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union
from pydantic import BaseModel
from pitwatch.strategy.circuits import get_circuit_pit_loss
from pitwatch.strategy.degradation import TyreDegradationModel
from pitwatch.strategy.pirelli import PirelliStrategyService, CircuitStrategyConfig


class UndercutThreatLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    CRITICAL = "CRITICAL"


class UndercutAssessment(BaseModel):
    gap_seconds: float
    projected_outlap_gain: float
    undercut_feasible: bool
    threat_level: UndercutThreatLevel
    recommended_action: str


class RejoinClearance(BaseModel):
    pit_loss_seconds: float
    gap_to_rejoin_car: float
    net_margin_seconds: float
    rejoin_ahead: bool


class PitRejoinSimulation(BaseModel):
    pit_loss_seconds: float
    projected_gap_to_leader: float
    projected_position: int
    rejoin_behind_driver: Optional[int] = None
    rejoin_behind_code: Optional[str] = None
    gap_ahead: Optional[float] = None
    rejoin_ahead_of_driver: Optional[int] = None
    rejoin_ahead_of_code: Optional[str] = None
    margin_behind: Optional[float] = None
    in_traffic: bool = False
    clean_air_window_seconds: float = 0.0
    # Backward-compatibility fields with RejoinClearance
    gap_to_rejoin_car: float = 0.0
    net_margin_seconds: float = 0.0
    rejoin_ahead: bool = True


class CompetitorThreatSnapshot(BaseModel):
    driver_number: int
    driver_code: str
    position: int
    interval_ahead: float
    gap_to_leader: float
    tyre_compound: str
    tyre_age_laps: int
    undercut_threat: Optional[UndercutAssessment] = None
    pit_rejoin: Optional[PitRejoinSimulation] = None
    pit_window_clearance: Union[PitRejoinSimulation, RejoinClearance]


class ThreatMatrixResponse(BaseModel):
    session_key: int
    circuit_name: str
    pit_transit_loss_seconds: float
    current_lap: int
    total_laps: int
    competitors: List[CompetitorThreatSnapshot]


class DeterministicStrategyEngine:
    """Calculates pit transit loss windows, tyre degradation, and competitor undercut threats."""

    def __init__(
        self,
        circuit_name: str,
        total_laps: int = 58,
        pirelli_service: Optional[PirelliStrategyService] = None,
    ):
        self.circuit_name = circuit_name
        self.pit_loss = get_circuit_pit_loss(circuit_name)
        self.degradation_model = TyreDegradationModel()
        self.pirelli_service = pirelli_service or PirelliStrategyService()
        self.strategy_config = self.pirelli_service.get_strategy_for_circuit(circuit_name, total_laps)
        self.total_laps = self.strategy_config.total_laps

    def assess_undercut_threat(
        self,
        gap_to_chaser_seconds: float,
        leader_tyre_age: int,
        leader_compound: str = "MEDIUM",
        chaser_compound: str = "HARD",
        track_temperature: float = 32.0,
    ) -> UndercutAssessment:
        """Evaluates whether a rival pitting 1 lap earlier will gain track position."""
        leader_penalty = self.degradation_model.calculate_lap_time_penalty(
            compound=leader_compound,
            tyre_age_laps=leader_tyre_age,
            track_temperature=track_temperature,
        )
        fresh_tyre_penalty = 0.0

        projected_gain = round(max(0.4, leader_penalty - fresh_tyre_penalty + 0.5), 2)
        feasible = gap_to_chaser_seconds <= projected_gain

        if feasible and gap_to_chaser_seconds <= 1.5:
            level = UndercutThreatLevel.CRITICAL
            action = f"BOX TO DEFEND: Chaser within {gap_to_chaser_seconds}s can undercut with projected {projected_gain}s gain."
        elif feasible:
            level = UndercutThreatLevel.MODERATE
            action = f"MONITOR: Chaser in undercut window ({gap_to_chaser_seconds}s gap vs {projected_gain}s gain)."
        else:
            level = UndercutThreatLevel.LOW
            action = f"SAFE: Gap of {gap_to_chaser_seconds}s exceeds projected {projected_gain}s out-lap advantage."

        return UndercutAssessment(
            gap_seconds=gap_to_chaser_seconds,
            projected_outlap_gain=projected_gain,
            undercut_feasible=feasible,
            threat_level=level,
            recommended_action=action,
        )

    def calculate_rejoin_clearance(self, gap_to_rejoin_car: float) -> RejoinClearance:
        """Determines if pitting now allows rejoining ahead of the specified rival."""
        margin = round(gap_to_rejoin_car - self.pit_loss, 2)
        return RejoinClearance(
            pit_loss_seconds=self.pit_loss,
            gap_to_rejoin_car=gap_to_rejoin_car,
            net_margin_seconds=margin,
            rejoin_ahead=margin > 0.0,
        )

    def simulate_pit_rejoin(
        self,
        driver_number: int,
        current_gap_to_leader: float,
        running_order: Sequence[Any],
        pit_transit_loss: Optional[float] = None,
    ) -> PitRejoinSimulation:
        """Calculates projected rejoin gap, position, neighbors, and traffic threat window."""
        loss = pit_transit_loss if pit_transit_loss is not None else self.pit_loss
        return simulate_pit_rejoin(
            driver_number=driver_number,
            current_gap_to_leader=current_gap_to_leader,
            pit_transit_loss=loss,
            running_order=running_order,
        )


def simulate_pit_rejoin(
    driver_number: int,
    current_gap_to_leader: float,
    pit_transit_loss: float,
    running_order: Sequence[Any],
) -> PitRejoinSimulation:
    """Calculates projected pit exit position, gap to leader, surrounding competitors, and traffic status.

    Args:
        driver_number: The car number of the driver making the simulated pit stop.
        current_gap_to_leader: Current gap to race leader in seconds (0.0 for leader).
        pit_transit_loss: Pit lane delta loss in seconds for this circuit.
        running_order: Collection of competitors (dicts or objects with driver_number/gap_to_leader).

    Returns:
        PitRejoinSimulation with projected position, neighbors, clean air window, and traffic flags.
    """
    competitors = []
    for item in running_order:
        if isinstance(item, dict):
            num = item.get("driver_number")
            code = item.get("driver_code") or item.get("name_acronym")
            gap = float(item.get("gap_to_leader", 0.0))
            is_retired = bool(item.get("is_retired", False))
            status = str(item.get("status", "")).lower()
            pos = int(item.get("position", 0))
        else:
            num = getattr(item, "driver_number", None)
            code = getattr(item, "driver_code", getattr(item, "name_acronym", None))
            gap = float(getattr(item, "gap_to_leader", 0.0))
            is_retired = bool(getattr(item, "is_retired", False))
            status = str(getattr(item, "status", "")).lower()
            pos = int(getattr(item, "position", getattr(item, "current_position", 0)))

        if num is None or int(num) == int(driver_number):
            continue
        if is_retired or status in ("retired", "stopped", "dnf", "out"):
            continue
        if gap <= 0.0 and pos > 1:
            continue

        competitors.append({
            "driver_number": int(num),
            "driver_code": str(code) if code else None,
            "gap_to_leader": gap,
            "position": pos,
        })

    competitors.sort(key=lambda c: c["gap_to_leader"])

    projected_gap = round(float(current_gap_to_leader) + float(pit_transit_loss), 3)

    ahead_cars = [c for c in competitors if c["gap_to_leader"] < projected_gap]
    behind_cars = [c for c in competitors if c["gap_to_leader"] >= projected_gap]

    projected_pos = len(ahead_cars) + 1

    rejoin_behind_driver = None
    rejoin_behind_code = None
    gap_ahead = None
    if ahead_cars:
        car_ahead = ahead_cars[-1]
        rejoin_behind_driver = car_ahead["driver_number"]
        rejoin_behind_code = car_ahead["driver_code"]
        gap_ahead = round(projected_gap - car_ahead["gap_to_leader"], 2)

    rejoin_ahead_of_driver = None
    rejoin_ahead_of_code = None
    margin_behind = None
    if behind_cars:
        car_behind = behind_cars[0]
        rejoin_ahead_of_driver = car_behind["driver_number"]
        rejoin_ahead_of_code = car_behind["driver_code"]
        margin_behind = round(car_behind["gap_to_leader"] - projected_gap, 2)

    in_traffic = bool(gap_ahead is not None and gap_ahead < 1.2)
    clean_air_window = round(gap_ahead, 2) if gap_ahead is not None else 99.0

    compat_gap_to_rejoin = gap_ahead if gap_ahead is not None else 0.0
    compat_net_margin = margin_behind if margin_behind is not None else (gap_ahead if gap_ahead is not None else 0.0)
    rejoin_ahead = bool(projected_pos == 1 or margin_behind is not None)

    return PitRejoinSimulation(
        pit_loss_seconds=round(float(pit_transit_loss), 2),
        projected_gap_to_leader=projected_gap,
        projected_position=projected_pos,
        rejoin_behind_driver=rejoin_behind_driver,
        rejoin_behind_code=rejoin_behind_code,
        gap_ahead=gap_ahead,
        rejoin_ahead_of_driver=rejoin_ahead_of_driver,
        rejoin_ahead_of_code=rejoin_ahead_of_code,
        margin_behind=margin_behind,
        in_traffic=in_traffic,
        clean_air_window_seconds=clean_air_window,
        gap_to_rejoin_car=compat_gap_to_rejoin,
        net_margin_seconds=compat_net_margin,
        rejoin_ahead=rejoin_ahead,
    )
