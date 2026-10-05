from collections import deque
from enum import Enum
import statistics
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PaceTrend(str, Enum):
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    MILD_DEGRADATION = "MILD_DEGRADATION"
    CLIFF = "CLIFF"


class TrendColor(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class SlowLapRootCause(str, Enum):
    YELLOW_FLAG = "YELLOW_FLAG"
    VSC_OR_SC = "VSC_OR_SC"
    PIT_STOP = "PIT_STOP"
    TRAFFIC = "TRAFFIC"
    TYRE_CLIFF = "TYRE_CLIFF"
    NONE = "NONE"


class LapPaceRecord(BaseModel):
    lap_number: int
    lap_time: float
    stint_number: int = 1
    compound: str = "UNKNOWN"
    tyre_age_laps: int = 0
    is_pit_lap: bool = False
    flag_status: Optional[str] = None
    session_time: float = 0.0


class PaceAnomaly(BaseModel):
    lap_number: int
    lap_time: float
    pace_delta: float
    root_cause: SlowLapRootCause
    details: str
    confidence: float = 1.0


class DriverPaceStatus(BaseModel):
    driver_number: int
    driver_code: str
    current_position: int = 1
    current_compound: str = "UNKNOWN"
    tyre_age_laps: int = 0
    stint_number: int = 1
    stint_baseline_pace: Optional[float] = None
    rolling_median_pace: Optional[float] = None
    last_lap_time: Optional[float] = None
    pace_delta_to_baseline: Optional[float] = None
    pace_delta_to_rolling: Optional[float] = None
    trend: PaceTrend = PaceTrend.STABLE
    trend_color: TrendColor = TrendColor.YELLOW
    latest_anomaly: Optional[PaceAnomaly] = None
    recent_anomalies: List[PaceAnomaly] = Field(default_factory=list)


class PaceMonitorResponse(BaseModel):
    session_key: int
    session_time: float
    current_lap: int
    drivers: List[DriverPaceStatus] = Field(default_factory=list)


class PaceEvaluator:
    """Evaluates real-time driver pace degradation, rolling 3-lap median, and attributes slow lap root causes."""

    def __init__(self):
        # driver_number -> list of LapPaceRecord
        self.driver_laps: Dict[int, List[LapPaceRecord]] = {}
        # driver_number -> list of PaceAnomaly
        self.driver_anomalies: Dict[int, List[PaceAnomaly]] = {}
        # driver metadata cache
        self.driver_meta: Dict[int, dict] = {}

    def record_lap(
        self,
        driver_number: int,
        driver_code: str,
        lap_number: int,
        lap_time: float,
        stint_number: int = 1,
        compound: str = "UNKNOWN",
        tyre_age_laps: int = 0,
        is_pit_lap: bool = False,
        flag_status: Optional[str] = None,
        session_time: float = 0.0,
        current_position: int = 1,
        interval_ahead: float = 99.0,
        active_race_control_messages: Optional[List[dict]] = None,
    ) -> Optional[PaceAnomaly]:
        """Record a completed lap for a driver and evaluate pace degradation and anomalies."""
        if lap_time <= 0.0:
            return None

        if driver_number not in self.driver_laps:
            self.driver_laps[driver_number] = []
            self.driver_anomalies[driver_number] = []

        self.driver_meta[driver_number] = {
            "driver_code": driver_code,
            "current_position": current_position,
            "compound": compound,
            "tyre_age_laps": tyre_age_laps,
            "stint_number": stint_number,
        }

        record = LapPaceRecord(
            lap_number=lap_number,
            lap_time=lap_time,
            stint_number=stint_number,
            compound=compound,
            tyre_age_laps=tyre_age_laps,
            is_pit_lap=is_pit_lap,
            flag_status=flag_status,
            session_time=session_time,
        )
        self.driver_laps[driver_number].append(record)

        # Evaluate potential anomaly for this lap
        anomaly = self.attribute_slow_lap(
            driver_number=driver_number,
            record=record,
            interval_ahead=interval_ahead,
            active_race_control_messages=active_race_control_messages or [],
        )
        if anomaly and anomaly.root_cause != SlowLapRootCause.NONE:
            self.driver_anomalies[driver_number].append(anomaly)
            return anomaly
        return None

    def attribute_slow_lap(
        self,
        driver_number: int,
        record: LapPaceRecord,
        interval_ahead: float = 99.0,
        active_race_control_messages: Optional[List[dict]] = None,
    ) -> Optional[PaceAnomaly]:
        """Detect and classify root causes for slow laps or sudden pace loss."""
        stint_laps = [
            l for l in self.driver_laps.get(driver_number, [])
            if l.stint_number == record.stint_number and not l.is_pit_lap
        ]
        if not stint_laps:
            baseline = record.lap_time
        else:
            baseline = min(l.lap_time for l in stint_laps)

        delta = round(record.lap_time - baseline, 3)

        # Check threshold for slow lap / anomaly (delta > 0.4s)
        if delta <= 0.4 and not record.is_pit_lap:
            return None

        rcms = active_race_control_messages or []

        # 1. Pit stop detection
        if record.is_pit_lap or record.lap_time > (baseline * 1.35):
            return PaceAnomaly(
                lap_number=record.lap_number,
                lap_time=record.lap_time,
                pace_delta=delta,
                root_cause=SlowLapRootCause.PIT_STOP,
                details="Lap impacted by pit in/out transit",
                confidence=1.0,
            )

        # 2. VSC or Safety Car detection
        vsc_sc_msgs = [
            m for m in rcms
            if any(term in str(m.get("message") or m.get("Message", "")).upper() for term in ("SAFETY CAR", "VSC", "VIRTUAL SAFETY CAR"))
        ]
        if vsc_sc_msgs:
            latest_sc = vsc_sc_msgs[-1]
            return PaceAnomaly(
                lap_number=record.lap_number,
                lap_time=record.lap_time,
                pace_delta=delta,
                root_cause=SlowLapRootCause.VSC_OR_SC,
                details=f"Track neutralization active: {latest_sc.get('message') or latest_sc.get('Message', 'Safety Car')}",
                confidence=0.95,
            )

        # 3. Yellow Flag detection
        yellow_msgs = [
            m for m in rcms
            if str(m.get("flag") or m.get("Flag", "")).upper() in ("YELLOW", "DOUBLE YELLOW")
            or "YELLOW" in str(m.get("message") or m.get("Message", "")).upper()
        ]
        if yellow_msgs or (record.flag_status and "YELLOW" in record.flag_status.upper()):
            flag_text = record.flag_status or yellow_msgs[-1].get("message") or yellow_msgs[-1].get("Message", "Yellow Flag")
            return PaceAnomaly(
                lap_number=record.lap_number,
                lap_time=record.lap_time,
                pace_delta=delta,
                root_cause=SlowLapRootCause.YELLOW_FLAG,
                details=f"Sector yellow flag active during lap: {flag_text}",
                confidence=0.90,
            )

        # 4. Traffic / Dirty Air detection
        if interval_ahead <= 1.2:
            return PaceAnomaly(
                lap_number=record.lap_number,
                lap_time=record.lap_time,
                pace_delta=delta,
                root_cause=SlowLapRootCause.TRAFFIC,
                details=f"Running in dirty air / traffic window (+{interval_ahead:.2f}s behind competitor)",
                confidence=0.85,
            )

        # 5. Tyre Cliff detection
        if delta > 1.2:
            return PaceAnomaly(
                lap_number=record.lap_number,
                lap_time=record.lap_time,
                pace_delta=delta,
                root_cause=SlowLapRootCause.TYRE_CLIFF,
                details=f"Severe tyre degradation / thermal cliff (+{delta:.2f}s off baseline on lap {record.tyre_age_laps})",
                confidence=0.90,
            )

        return None

    def evaluate_driver(self, driver_number: int) -> Optional[DriverPaceStatus]:
        """Compute rolling 3-lap median, stint baseline, degradation trend, and current status."""
        laps = self.driver_laps.get(driver_number, [])
        if not laps:
            return None

        meta = self.driver_meta.get(driver_number, {})
        latest_lap = laps[-1]
        stint_no = latest_lap.stint_number

        # Clean laps in current stint (excluding pit in/out laps)
        stint_clean_laps = [l for l in laps if l.stint_number == stint_no and not l.is_pit_lap]

        if not stint_clean_laps:
            baseline = latest_lap.lap_time
            rolling_median = latest_lap.lap_time
        else:
            baseline = min(l.lap_time for l in stint_clean_laps)
            # Rolling 3-lap window of clean laps
            window = [l.lap_time for l in stint_clean_laps[-3:]]
            rolling_median = round(statistics.median(window), 3)

        delta_to_baseline = round(latest_lap.lap_time - baseline, 3)
        delta_to_rolling = round(latest_lap.lap_time - rolling_median, 3)

        # Classify trend based on delta to baseline:
        # < -0.2s: IMPROVING (GREEN)
        # -0.2s to +0.4s: STABLE (YELLOW)
        # +0.4s to +1.2s: MILD_DEGRADATION (ORANGE)
        # > +1.2s: CLIFF (RED)
        if delta_to_baseline < -0.2:
            trend = PaceTrend.IMPROVING
            trend_color = TrendColor.GREEN
        elif delta_to_baseline <= 0.4:
            trend = PaceTrend.STABLE
            trend_color = TrendColor.YELLOW
        elif delta_to_baseline <= 1.2:
            trend = PaceTrend.MILD_DEGRADATION
            trend_color = TrendColor.ORANGE
        else:
            trend = PaceTrend.CLIFF
            trend_color = TrendColor.RED

        anomalies = self.driver_anomalies.get(driver_number, [])
        latest_anomaly = anomalies[-1] if anomalies else None

        return DriverPaceStatus(
            driver_number=driver_number,
            driver_code=meta.get("driver_code", f"D{driver_number}"),
            current_position=meta.get("current_position", 1),
            current_compound=meta.get("compound", "UNKNOWN"),
            tyre_age_laps=meta.get("tyre_age_laps", latest_lap.tyre_age_laps),
            stint_number=stint_no,
            stint_baseline_pace=baseline,
            rolling_median_pace=rolling_median,
            last_lap_time=latest_lap.lap_time,
            pace_delta_to_baseline=delta_to_baseline,
            pace_delta_to_rolling=delta_to_rolling,
            trend=trend,
            trend_color=trend_color,
            latest_anomaly=latest_anomaly,
            recent_anomalies=anomalies[-5:],
        )

    def get_pace_monitor(
        self, session_key: int = 0, session_time: float = 0.0, current_lap: int = 1
    ) -> PaceMonitorResponse:
        """Generates comprehensive pace monitor response for all active drivers."""
        statuses = []
        for drv_num in sorted(self.driver_laps.keys()):
            st = self.evaluate_driver(drv_num)
            if st:
                statuses.append(st)

        statuses.sort(key=lambda s: s.current_position)
        return PaceMonitorResponse(
            session_key=session_key,
            session_time=session_time,
            current_lap=current_lap,
            drivers=statuses,
        )
