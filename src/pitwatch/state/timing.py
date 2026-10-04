from typing import Optional
from pydantic import BaseModel


class FastestLapRecord(BaseModel):
    driver_number: int
    driver_code: str
    team_name: str
    team_colour: Optional[str] = None
    lap_number: int
    lap_time: float
    lap_time_formatted: str
    compound: str = "UNKNOWN"
    recorded_at_session_time: Optional[float] = None


def format_lap_time(seconds: Optional[float]) -> Optional[str]:
    """Converts lap time in seconds (e.g. 110.519) to broadcast MM:SS.mmm format (e.g. '01:50.519')."""
    if seconds is None or seconds <= 0.0:
        return None
    mins = int(seconds // 60)
    rem_secs = seconds - (mins * 60)
    return f"{mins:02d}:{rem_secs:06.3f}"


def format_gap(gap: Optional[float], position: int = 1) -> str:
    """Formats gap to leader as 'LEADER', '+SS.mmm', or '+M:SS.mmm'."""
    if position == 1 or gap is None or gap <= 0.0:
        return "LEADER"
    if gap >= 60.0:
        mins = int(gap // 60)
        rem_secs = gap - (mins * 60)
        return f"+{mins}:{rem_secs:06.3f}"
    return f"+{gap:.3f}"


def format_interval(interval: Optional[float], position: int = 1) -> str:
    """Formats interval to position ahead as '-', '+SS.mmm', or '+M:SS.mmm'."""
    if position == 1 or interval is None or interval <= 0.0:
        return "-"
    if interval >= 60.0:
        mins = int(interval // 60)
        rem_secs = interval - (mins * 60)
        return f"+{mins}:{rem_secs:06.3f}"
    return f"+{interval:.3f}"
