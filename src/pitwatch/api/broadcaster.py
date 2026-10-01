import asyncio
from datetime import datetime, timezone
from typing import Set
from fastapi import WebSocket, WebSocketDisconnect
from pitwatch.api.schemas import PositionsStreamMessage, VehiclePositionPayload
from pitwatch.state.session import LiveSessionState


class PositionBroadcaster:
    """Manages connected WebSocket clients and emits position arrays at 2-5Hz."""

    def __init__(self, session_state: LiveSessionState):
        self.session_state = session_state
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.active_connections.discard(websocket)

    def build_positions_payload(self) -> dict:
        raw_positions = self.session_state.get_all_normalized_positions()
        payloads = [
            VehiclePositionPayload(
                driver_number=p["driver_number"],
                driver_code=p["driver_code"],
                x=round(p["x"], 4),
                y=round(p["y"], 4),
                progress=round(p["progress"], 4),
                speed=p.get("speed", 0),
            )
            for p in raw_positions
        ]
        msg = PositionsStreamMessage(
            type="positions",
            session_time=round(self.session_state.current_session_time, 3),
            timestamp=datetime.now(timezone.utc).isoformat(),
            positions=payloads,
        )
        return msg.model_dump()

    async def stream_to_client(self, websocket: WebSocket, interval: float = 0.2) -> None:
        """Emits position packets to a connected client at `interval` seconds."""
        await self.connect(websocket)
        try:
            while True:
                payload = self.build_positions_payload()
                await websocket.send_json(payload)
                await asyncio.sleep(interval)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            self.disconnect(websocket)
