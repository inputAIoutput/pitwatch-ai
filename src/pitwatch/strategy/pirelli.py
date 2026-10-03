import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel
from pitwatch.strategy.circuits import get_circuit_pit_loss


class StintPlan(BaseModel):
    stint_index: int
    compound: str  # "SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"
    start_lap: int
    end_lap: int


class RecommendedStrategy(BaseModel):
    strategy_id: str
    name: str
    stops: int
    is_fastest: bool = False
    delta_seconds: float = 0.0
    pit_window: Tuple[int, int]
    stints: List[StintPlan]


class CircuitStrategyConfig(BaseModel):
    circuit_name: str
    circuit_key: str
    total_laps: int
    pit_transit_loss_seconds: float
    strategies: List[RecommendedStrategy]


class PirelliStrategyService:
    """Manages pre-race Pirelli strategy presets, local cache, and fallback presets."""

    def __init__(self, preset_path: Optional[Path] = None):
        if preset_path:
            self.preset_path = preset_path
        else:
            default_path = Path("data/presets/pirelli_strategies.json")
            if default_path.exists():
                self.preset_path = default_path
            else:
                # Also try relative to project root
                module_root = Path(__file__).resolve().parents[3]
                self.preset_path = module_root / "data" / "presets" / "pirelli_strategies.json"
        self._presets: Dict[str, CircuitStrategyConfig] = {}
        self._load_presets()

    def _load_presets(self) -> None:
        if self.preset_path.exists():
            with open(self.preset_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for c_name, data in raw.items():
                self._presets[c_name.strip().lower()] = CircuitStrategyConfig(**data)

    def get_strategy_for_circuit(self, circuit_name: str, total_laps: int = 58) -> CircuitStrategyConfig:
        clean = circuit_name.strip().lower()
        for k, cfg in self._presets.items():
            if k in clean or clean in k:
                return cfg

        # Generate a default 1-stop strategy config if not present in presets
        pit_loss = get_circuit_pit_loss(circuit_name)
        midpoint = total_laps // 2
        return CircuitStrategyConfig(
            circuit_name=circuit_name,
            circuit_key=clean.replace(" ", "_"),
            total_laps=total_laps,
            pit_transit_loss_seconds=pit_loss,
            strategies=[
                RecommendedStrategy(
                    strategy_id=f"{clean.upper()}_DEFAULT_1STOP",
                    name="Default Baseline (1-Stop)",
                    stops=1,
                    is_fastest=True,
                    delta_seconds=0.0,
                    pit_window=(max(1, midpoint - 4), min(total_laps, midpoint + 4)),
                    stints=[
                        StintPlan(stint_index=1, compound="MEDIUM", start_lap=1, end_lap=midpoint),
                        StintPlan(stint_index=2, compound="HARD", start_lap=midpoint + 1, end_lap=total_laps),
                    ],
                )
            ],
        )
