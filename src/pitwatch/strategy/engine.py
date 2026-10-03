from enum import Enum
from typing import Dict, List, Optional
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


class CompetitorThreatSnapshot(BaseModel):
    driver_number: int
    driver_code: str
    position: int
    interval_ahead: float
    gap_to_leader: float
    tyre_compound: str
    tyre_age_laps: int
    undercut_threat: Optional[UndercutAssessment] = None
    pit_window_clearance: RejoinClearance


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
