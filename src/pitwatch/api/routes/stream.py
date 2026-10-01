from fastapi import APIRouter, Query, WebSocket
from pitwatch.api.broadcaster import PositionBroadcaster

router = APIRouter(prefix="/v1/stream", tags=["stream"])


@router.websocket("/positions")
async def websocket_positions_stream(
    websocket: WebSocket,
    interval: float = Query(default=0.2, ge=0.01, le=1.0, description="Broadcast interval in seconds (0.2s = 5Hz)"),
):
    state = websocket.app.state.session_state
    broadcaster = PositionBroadcaster(session_state=state)
    await broadcaster.stream_to_client(websocket, interval=interval)
