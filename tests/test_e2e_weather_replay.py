import json
from pathlib import Path
from datetime import datetime
import pytest
from pitwatch.models.frame import ReplayFrame, WeatherTick
from pitwatch.state.session import LiveSessionState


def test_silverstone_rain_transition_triggers_crossover_alert():
    cache_path = Path("data/cache/openf1/weather_session_key-9558.json")
    if not cache_path.exists():
        pytest.skip("Cached weather file not present")

    with open(cache_path, "r", encoding="utf-8") as f:
        weather_raw = json.load(f)

    # Ingest weather observations chronologically into state
    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")

    alerts_triggered = []
    for i, w in enumerate(weather_raw):
        # 60s step between weather ticks
        session_time = float(i * 60)
        dt = datetime.fromisoformat(w["date"])
        frame = ReplayFrame(
            session_time=session_time,
            timestamp=dt,
            weather=WeatherTick(
                track_temperature=float(w["track_temperature"]),
                air_temperature=float(w["air_temperature"]),
                rainfall=int(w["rainfall"]),
                wind_speed=float(w["wind_speed"]),
                wind_direction=int(w.get("wind_direction", 0)),
                humidity=float(w.get("humidity", 0)),
                pressure=float(w.get("pressure", 0)),
                timestamp=dt,
            ),
        )
        state.ingest_frame(frame)
        cur = state.get_current_weather()
        if cur["active_alert"] and (
            not alerts_triggered or alerts_triggered[-1]["alert_id"] != cur["active_alert"]["alert_id"]
        ):
            alerts_triggered.append(cur["active_alert"])

    # Verify that during the session, crossover alerts occurred (at least SLICK_TO_INTERMEDIATE when rain struck)
    transitions = [a["transition"] for a in alerts_triggered]
    assert "SLICK_TO_INTERMEDIATE" in transitions
