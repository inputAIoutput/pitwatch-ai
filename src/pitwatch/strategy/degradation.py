from typing import Dict


class TyreDegradationModel:
    """Calculates non-linear lap time degradation penalties (seconds/lap) based on compound wear and track temperature."""

    BASE_DEG_RATES: Dict[str, float] = {
        "SOFT": 0.085,
        "MEDIUM": 0.055,
        "HARD": 0.035,
        "INTERMEDIATE": 0.070,
        "WET": 0.060,
    }

    CLIFF_THRESHOLDS: Dict[str, int] = {
        "SOFT": 18,
        "MEDIUM": 26,
        "HARD": 38,
        "INTERMEDIATE": 24,
        "WET": 28,
    }

    def calculate_lap_time_penalty(
        self,
        compound: str,
        tyre_age_laps: int,
        track_temperature: float = 32.0,
    ) -> float:
        """Computes pace penalty in seconds for a given compound and tyre age."""
        comp = compound.upper()
        rate = self.BASE_DEG_RATES.get(comp, 0.05)
        cliff_lap = self.CLIFF_THRESHOLDS.get(comp, 25)

        # 1. Linear wear phase
        penalty = min(tyre_age_laps, cliff_lap) * rate

        # 2. Non-linear cliff wear phase
        if tyre_age_laps > cliff_lap:
            excess_laps = tyre_age_laps - cliff_lap
            penalty += (excess_laps * rate) + (0.04 * (excess_laps ** 1.8))

        # 3. Thermal amplification (optimal ~30°C - 35°C)
        if track_temperature > 40.0:
            thermal_factor = 1.0 + ((track_temperature - 40.0) * 0.015)
            penalty *= thermal_factor
        elif track_temperature < 24.0:
            thermal_factor = 1.0 + ((24.0 - track_temperature) * 0.01)
            penalty *= thermal_factor

        return round(penalty, 2)
