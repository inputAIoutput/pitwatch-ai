from collections import deque
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Deque, List, Optional, Tuple
from pydantic import BaseModel
from pitwatch.models.frame import WeatherTick


class CrossoverStatus(str, Enum):
    DRY_OPTIMAL = "DRY_OPTIMAL"
    SLICK_TO_INTERMEDIATE = "SLICK_TO_INTERMEDIATE"
    INTERMEDIATE_OPTIMAL = "INTERMEDIATE_OPTIMAL"
    INTERMEDIATE_TO_WET = "INTERMEDIATE_TO_WET"
    WET_OPTIMAL = "WET_OPTIMAL"
    WET_TO_INTERMEDIATE = "WET_TO_INTERMEDIATE"
    INTERMEDIATE_TO_SLICK = "INTERMEDIATE_TO_SLICK"


class CrossoverAlert(BaseModel):
    alert_id: str
    timestamp: datetime
    session_time: float
    severity: str  # "INFO", "WARNING", "CRITICAL"
    transition: CrossoverStatus
    current_track_temp: float
    thermal_drift_rate: float
    grip_loss_projection: float
    recommended_compound: str
    message: str


class WeatherObservation(BaseModel):
    session_time: float
    timestamp: datetime
    tick: WeatherTick


class EnvironmentalEvaluator:
    """Evaluates track thermal drift, surface water grip loss, and tyre compound crossover windows."""

    def __init__(self, window_seconds: float = 300.0):
        self.window_seconds = window_seconds
        self.history: Deque[WeatherObservation] = deque()
        self.crossover_status: CrossoverStatus = CrossoverStatus.DRY_OPTIMAL
        self.recommended_compound: str = "SLICK"
        self.active_alert: Optional[CrossoverAlert] = None
        self._consecutive_rain_ticks: int = 0
        self._consecutive_dry_ticks: int = 0
        self._alert_counter: int = 0
        self.is_track_declared_wet: bool = False
        self.race_director_notice: Optional[str] = None

    @staticmethod
    def get_thermal_slick_recommendation(track_temperature: float) -> str:
        """Determines optimal dry compound based on Pirelli thermal operating windows:
        - T < 30.0°C: SOFT (warm-up priority)
        - 30.0°C <= T <= 45.0°C: MEDIUM (optimal degradation balance)
        - T > 45.0°C: HARD (high thermal blistering resistance)
        """
        if track_temperature < 30.0:
            return "SOFT"
        elif track_temperature <= 45.0:
            return "MEDIUM"
        else:
            return "HARD"

    def record_race_control(self, rcm: Any, session_time: float) -> Optional[CrossoverAlert]:
        """Ingests and evaluates official FIA Race Control and Race Director notifications."""
        if isinstance(rcm, str):
            rcm = {"Message": rcm}
        elif not isinstance(rcm, dict):
            return None

        msg = str(rcm.get("Message") or rcm.get("message") or rcm.get("Description") or rcm.get("text") or "").upper()
        flag = str(rcm.get("Flag") or rcm.get("flag") or "").upper()
        raw_msg = rcm.get("Message") or rcm.get("message") or msg

        # DRS / Overtake Enabled Notice: Immediately cancels wet status and transitions to slick
        if "DRS ENABLED" in msg or "DRS ACTIVE" in msg or "OVERTAKE ENABLED" in msg:
            self.is_track_declared_wet = False
            self.race_director_notice = None
            t_track = self.history[-1].tick.track_temperature if self.history else 30.0
            slick_rec = self.get_thermal_slick_recommendation(t_track)
            self.recommended_compound = slick_rec
            self.crossover_status = CrossoverStatus.DRY_OPTIMAL
            self._alert_counter += 1
            self.active_alert = CrossoverAlert(
                alert_id=f"RCM-{int(session_time)}-{self._alert_counter}",
                timestamp=datetime.now(timezone.utc),
                session_time=session_time,
                severity="INFO",
                transition=CrossoverStatus.DRY_OPTIMAL,
                current_track_temp=t_track,
                thermal_drift_rate=self.get_thermal_drift_rate(),
                grip_loss_projection=self.project_tyre_grip_loss(),
                recommended_compound=slick_rec,
                message=f"RACE DIRECTOR NOTICE: '{raw_msg}'. Track dried sufficiently for DRS. Recommended compound: {slick_rec}.",
            )
            return self.active_alert

        # DRS / Overtake Disabled Notice: Track getting wet / low visibility
        if ("DRS DISABLED" in msg or "OVERTAKE DISABLED" in msg) and any(w in msg for w in ("WET", "RAIN", "WEATHER")):
            self.is_track_declared_wet = True
            self.race_director_notice = raw_msg
            self.crossover_status = CrossoverStatus.INTERMEDIATE_OPTIMAL
            self.recommended_compound = "INTERMEDIATE"
            self._alert_counter += 1
            self.active_alert = CrossoverAlert(
                alert_id=f"RCM-{int(session_time)}-{self._alert_counter}",
                timestamp=datetime.now(timezone.utc),
                session_time=session_time,
                severity="WARNING",
                transition=CrossoverStatus.INTERMEDIATE_OPTIMAL,
                current_track_temp=self.history[-1].tick.track_temperature if self.history else 26.0,
                thermal_drift_rate=self.get_thermal_drift_rate(),
                grip_loss_projection=50.0,
                recommended_compound="INTERMEDIATE",
                message=f"RACE DIRECTOR NOTICE: '{raw_msg}'. DRS disabled due to wet track.",
            )
            return self.active_alert

        wet_delay_keywords = [
            "START PROCEDURE DELAYED",
            "PROCEDURE DELAYED",
            "START DELAYED",
            "DELAYED",
            "DELAY",
            "STANDING WATER",
            "AQUAPLANING",
            "TORRENTIAL",
            "HEAVY RAIN",
            "EXTREME WET",
            "RED FLAG",
            "SUSPENDED",
        ]
        wet_track_keywords = [
            "TRACK WET",
            "WET TRACK",
            "LOW GRIP",
            "RAIN EXPECTED",
            "SAFETY CAR START",
            "RISK OF RAIN",
            "RAIN",
            "INTERMEDIATE",
        ]

        if any(kw in msg for kw in wet_delay_keywords) or (flag == "RED" and "RAIN" in msg):
            self.is_track_declared_wet = True
            self.race_director_notice = raw_msg
            self.crossover_status = CrossoverStatus.WET_OPTIMAL
            self.recommended_compound = "WET"
            self._alert_counter += 1
            self.active_alert = CrossoverAlert(
                alert_id=f"RCM-{int(session_time)}-{self._alert_counter}",
                timestamp=datetime.now(timezone.utc),
                session_time=session_time,
                severity="CRITICAL",
                transition=CrossoverStatus.WET_OPTIMAL,
                current_track_temp=self.history[-1].tick.track_temperature if self.history else 26.0,
                thermal_drift_rate=self.get_thermal_drift_rate(),
                grip_loss_projection=85.0,
                recommended_compound="WET",
                message=f"RACE DIRECTOR NOTICE: '{raw_msg}'. Standing water / start delayed. Recommended compound: WET.",
            )
            return self.active_alert

        elif any(kw in msg for kw in wet_track_keywords):
            self.is_track_declared_wet = True
            self.race_director_notice = raw_msg
            self.crossover_status = CrossoverStatus.INTERMEDIATE_OPTIMAL
            self.recommended_compound = "INTERMEDIATE"
            self._alert_counter += 1
            self.active_alert = CrossoverAlert(
                alert_id=f"RCM-{int(session_time)}-{self._alert_counter}",
                timestamp=datetime.now(timezone.utc),
                session_time=session_time,
                severity="WARNING",
                transition=CrossoverStatus.INTERMEDIATE_OPTIMAL,
                current_track_temp=self.history[-1].tick.track_temperature if self.history else 28.0,
                thermal_drift_rate=self.get_thermal_drift_rate(),
                grip_loss_projection=55.0,
                recommended_compound="INTERMEDIATE",
                message=f"RACE DIRECTOR NOTICE: '{raw_msg}'. Wet track declared. Recommended compound: INTERMEDIATE.",
            )
            return self.active_alert

        elif any(kw in msg for kw in ["TRACK DECLARED DRY", "TRACK DRY", "DECLARED DRY", "DRY TRACK"]) or (
            "CLEAR" in msg and flag == "GREEN" and self.is_track_declared_wet
        ):
            self.is_track_declared_wet = False
            self.race_director_notice = None

        return None

    def record_weather(
        self,
        tick: WeatherTick,
        session_time: float,
        timestamp: Optional[datetime] = None,
    ) -> Optional[CrossoverAlert]:
        """Ingests a new weather tick, updates rolling window, and evaluates crossover state."""
        ts = timestamp or datetime.now(timezone.utc)
        obs = WeatherObservation(session_time=session_time, timestamp=ts, tick=tick)
        self.history.append(obs)

        # Evict observations outside rolling window
        cutoff_time = session_time - self.window_seconds
        while len(self.history) > 2 and self.history[0].session_time < cutoff_time:
            self.history.popleft()

        # Update rain/dry streaks
        if tick.rainfall == 1:
            self._consecutive_rain_ticks += 1
            self._consecutive_dry_ticks = 0
        else:
            self._consecutive_dry_ticks += 1
            self._consecutive_rain_ticks = 0

        # Evaluate crossover
        alert = self._evaluate_crossover(session_time, ts, tick)
        return alert

    def get_latest_weather(self) -> Optional[WeatherTick]:
        return self.history[-1].tick if self.history else None

    def get_thermal_drift_rate(self) -> float:
        """Calculates dT/dt in °C per minute using linear regression over the rolling window."""
        if len(self.history) < 2:
            return 0.0

        n = len(self.history)
        t0 = self.history[0].session_time
        times = [(obs.session_time - t0) / 60.0 for obs in self.history]
        temps = [obs.tick.track_temperature for obs in self.history]

        mean_t = sum(times) / n
        mean_temp = sum(temps) / n

        denom = sum((t - mean_t) ** 2 for t in times)
        if denom == 0.0:
            return 0.0

        numer = sum((t - mean_t) * (temp - mean_temp) for t, temp in zip(times, temps))
        return round(numer / denom, 2)

    def project_tyre_grip_loss(self) -> float:
        """Projects tyre grip loss percentage (0.0 to 100.0%) for slick tyres under active conditions."""
        if not self.history:
            return 0.0

        latest = self.history[-1].tick
        drift = self.get_thermal_drift_rate()

        grip_loss = 0.0

        # 0. Race Director wet track declaration penalty
        if self.is_track_declared_wet:
            grip_loss += 75.0 if self.recommended_compound == "WET" else 50.0

        # 1. Surface moisture & rainfall impact
        if latest.rainfall == 1:
            # Base 30% instant loss on slicks + time accumulation + humidity factor
            rain_accumulation = min(25.0, self._consecutive_rain_ticks * 3.0)
            humidity_factor = max(0.0, ((latest.humidity or 50.0) - 70.0) * 0.5)
            grip_loss += 30.0 + rain_accumulation + humidity_factor
        elif self._consecutive_dry_ticks < 5 and self.crossover_status in (
            CrossoverStatus.SLICK_TO_INTERMEDIATE,
            CrossoverStatus.INTERMEDIATE_OPTIMAL,
            CrossoverStatus.WET_OPTIMAL,
        ):
            # Track is drying, residual moisture penalty
            grip_loss += max(0.0, 20.0 - (self._consecutive_dry_ticks * 4.0))

        # 2. Thermal divergence impact (Pirelli slicks optimal window: 28°C - 45°C)
        t_track = latest.track_temperature
        if t_track < 28.0:
            grip_loss += (28.0 - t_track) * 1.2
        elif t_track > 45.0:
            grip_loss += (t_track - 45.0) * 0.8

        # 3. Dynamic cooling penalty
        if drift < -1.0:
            grip_loss += min(10.0, abs(drift) * 2.0)

        return round(min(100.0, max(0.0, grip_loss)), 1)

    def get_wind_vector(self) -> Tuple[float, float]:
        """Calculates (vx, vy) wind components in m/s (vx = Eastward, vy = Northward)."""
        if not self.history:
            return (0.0, 0.0)
        latest = self.history[-1].tick
        speed = latest.wind_speed
        direction_deg = latest.wind_direction or 0
        rad = math.radians(direction_deg)
        # 0 deg = North (vy > 0), 90 deg = East (vx > 0)
        vx = round(speed * math.sin(rad), 2)
        vy = round(speed * math.cos(rad), 2)
        return (vx, vy)

    def _evaluate_crossover(
        self, session_time: float, timestamp: datetime, tick: WeatherTick
    ) -> Optional[CrossoverAlert]:
        drift = self.get_thermal_drift_rate()
        grip_loss = self.project_tyre_grip_loss()
        prev_status = self.crossover_status
        new_status = prev_status
        new_compound = self.recommended_compound
        alert: Optional[CrossoverAlert] = None

        # Logic transitions:
        # 0. Enforce Race Director wet track declarations
        if self.is_track_declared_wet:
            if self.recommended_compound == "WET" or grip_loss >= 65.0:
                new_status = CrossoverStatus.WET_OPTIMAL
                new_compound = "WET"
            else:
                new_status = CrossoverStatus.INTERMEDIATE_OPTIMAL
                new_compound = "INTERMEDIATE"

        # A. Transition to WET
        elif tick.rainfall == 1 and (
            (self._consecutive_rain_ticks >= 6 and tick.track_temperature < 21.0)
            or grip_loss >= 65.0
        ):
            new_status = CrossoverStatus.INTERMEDIATE_TO_WET
            new_compound = "WET"

        # B. Transition to INTERMEDIATE
        elif tick.rainfall == 1 or grip_loss >= 25.0 or (drift <= -1.5 and (tick.humidity or 0) >= 70):
            if prev_status in (CrossoverStatus.WET_OPTIMAL, CrossoverStatus.INTERMEDIATE_TO_WET):
                new_status = CrossoverStatus.WET_TO_INTERMEDIATE
            else:
                new_status = CrossoverStatus.SLICK_TO_INTERMEDIATE
            new_compound = "INTERMEDIATE"

        # C. Transition to SLICK (Drying track - only when not declared wet by Race Control)
        elif not self.is_track_declared_wet and tick.rainfall == 0 and self._consecutive_dry_ticks >= 3 and grip_loss < 15.0 and tick.track_temperature >= 22.0:
            if prev_status in (
                CrossoverStatus.SLICK_TO_INTERMEDIATE,
                CrossoverStatus.INTERMEDIATE_OPTIMAL,
                CrossoverStatus.WET_OPTIMAL,
                CrossoverStatus.WET_TO_INTERMEDIATE,
            ):
                new_status = CrossoverStatus.INTERMEDIATE_TO_SLICK
            else:
                new_status = CrossoverStatus.DRY_OPTIMAL
            new_compound = self.get_thermal_slick_recommendation(tick.track_temperature)

        # D. Steady states
        elif not self.is_track_declared_wet and tick.rainfall == 0 and grip_loss < 10.0:
            new_status = CrossoverStatus.DRY_OPTIMAL
            new_compound = self.get_thermal_slick_recommendation(tick.track_temperature)
        elif tick.rainfall == 1 and new_compound == "INTERMEDIATE":
            new_status = CrossoverStatus.INTERMEDIATE_OPTIMAL
        elif tick.rainfall == 1 and new_compound == "WET":
            new_status = CrossoverStatus.WET_OPTIMAL

        # Trigger alert on status transition
        if new_status != prev_status:
            self._alert_counter += 1
            severity = "CRITICAL" if "TO" in new_status.value and new_compound in ("INTERMEDIATE", "WET") else "WARNING"
            if new_status == CrossoverStatus.DRY_OPTIMAL:
                severity = "INFO"

            msg = (
                f"Track crossover alert: {prev_status.value} -> {new_status.value}. "
                f"Track Temp: {tick.track_temperature}°C (dT/dt: {drift:+.2f}°C/min). "
                f"Projected slick grip loss: {grip_loss}%. Recommended compound: {new_compound}."
            )
            alert = CrossoverAlert(
                alert_id=f"WX-{int(session_time)}-{self._alert_counter}",
                timestamp=timestamp,
                session_time=session_time,
                severity=severity,
                transition=new_status,
                current_track_temp=tick.track_temperature,
                thermal_drift_rate=drift,
                grip_loss_projection=grip_loss,
                recommended_compound=new_compound,
                message=msg,
            )
            self.active_alert = alert

        self.crossover_status = new_status
        self.recommended_compound = new_compound
        return alert
