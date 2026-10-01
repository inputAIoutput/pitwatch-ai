from typing import Dict, Optional, Tuple
from pydantic import BaseModel


class CircuitBounds(BaseModel):
    min_x: float
    max_x: float
    min_y: float
    max_y: float


# Calibrated coordinate bounds for popular Formula 1 circuits
CIRCUIT_PRESETS: Dict[str, CircuitBounds] = {
    "silverstone": CircuitBounds(min_x=-3500.0, max_x=3500.0, min_y=-2500.0, max_y=2500.0),
    "monza": CircuitBounds(min_x=-4500.0, max_x=4500.0, min_y=-2000.0, max_y=2000.0),
    "monaco": CircuitBounds(min_x=-1500.0, max_x=1500.0, min_y=-1500.0, max_y=1500.0),
    "spa": CircuitBounds(min_x=-5000.0, max_x=5000.0, min_y=-4000.0, max_y=4000.0),
}


class CoordinateNormalizer:
    """Normalizes raw F1 Cartesian track coordinates into [-1.0, 1.0] and progress into [0.0, 1.0]."""

    def __init__(self, bounds: Optional[CircuitBounds] = None):
        self.bounds = bounds or CircuitBounds(
            min_x=-5000.0,
            max_x=5000.0,
            min_y=-5000.0,
            max_y=5000.0,
        )

    @classmethod
    def for_circuit(cls, circuit_name: str) -> "CoordinateNormalizer":
        key = circuit_name.lower().strip()
        bounds = CIRCUIT_PRESETS.get(key, CircuitBounds(
            min_x=-5000.0, max_x=5000.0, min_y=-5000.0, max_y=5000.0
        ))
        return cls(bounds=bounds)

    def normalize_point(self, x: float, y: float) -> Tuple[float, float]:
        dx = self.bounds.max_x - self.bounds.min_x
        dy = self.bounds.max_y - self.bounds.min_y

        if dx <= 0.0:
            norm_x = 0.0
        else:
            norm_x = 2.0 * ((x - self.bounds.min_x) / dx) - 1.0

        if dy <= 0.0:
            norm_y = 0.0
        else:
            norm_y = 2.0 * ((y - self.bounds.min_y) / dy) - 1.0

        # Strict clamping within [-1.0, 1.0]
        clamped_x = max(-1.0, min(1.0, norm_x))
        clamped_y = max(-1.0, min(1.0, norm_y))
        return clamped_x, clamped_y

    def normalize_progress(self, progress: Optional[float]) -> float:
        if progress is None:
            return 0.0
        return max(0.0, min(1.0, float(progress)))
