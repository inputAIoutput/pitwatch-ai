import asyncio
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from pitwatch.api.app import create_app
from pitwatch.models.frame import CarPositionTick, TelemetryTick, WeatherTick, ReplayFrame
from pitwatch.ingestion.replay import HistoricalReplaySource
from pitwatch.state.session import LiveSessionState


@pytest.mark.asyncio
async def test_end_to_end_replay_and_websocket_streaming():
    frames = [
        ReplayFrame(
            session_time=round(i * 0.2, 3),
            timestamp=datetime(2024, 7, 7, 14, 3, 12 + int(i * 0.2), tzinfo=timezone.utc),
            positions=[
                CarPositionTick(driver_number=44, x=-1000.0 + (i * 20.0), y=2000.0 + (i * 10.0), progress=0.01 * (i + 1)),
                CarPositionTick(driver_number=1, x=-1100.0 + (i * 15.0), y=1900.0 + (i * 12.0), progress=0.01 * i),
            ],
            telemetry=[
                TelemetryTick(driver_number=44, speed=250 + i * 5, gear=6, throttle=100, brake=0, drs=1),
                TelemetryTick(driver_number=1, speed=245 + i * 5, gear=6, throttle=100, brake=0, drs=1),
            ],
            weather=WeatherTick(track_temperature=28.5 + (i * 0.1), air_temperature=16.5, rainfall=0),
        )
        for i in range(5)
    ]

    state = LiveSessionState(session_key=9558, circuit_name="Silverstone")
    source = HistoricalReplaySource.from_frames(frames, time_step=0.01)
    source.bind_state(state)
    source.controller.play()

    app = create_app(session_state=state)
    client = TestClient(app)

    # Ingest frames asynchronously
    async def play_replay():
        async for _ in source.stream_frames():
            await asyncio.sleep(0.01)

    replay_task = asyncio.create_task(play_replay())
    await asyncio.sleep(0.05)  # Allow initial frames to ingest

    # 1. Query REST session snapshot
    res_session = client.get("/v1/session/current")
    assert res_session.status_code == 200
    assert res_session.json()["circuit_name"] == "Silverstone"
    assert res_session.json()["total_drivers"] == 2

    # 2. Query REST live telemetry snapshot
    res_tel = client.get("/v1/telemetry/live")
    assert res_tel.status_code == 200
    assert len(res_tel.json()["vehicles"]) == 2

    # 3. Connect WebSocket and read streamed frames
    with client.websocket_connect("/v1/stream/positions?interval=0.02") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "positions"
        assert len(msg["positions"]) == 2
        p44 = [p for p in msg["positions"] if p["driver_number"] == 44][0]
        assert -1.0 <= p44["x"] <= 1.0
        assert p44["speed"] >= 250

    await replay_task
