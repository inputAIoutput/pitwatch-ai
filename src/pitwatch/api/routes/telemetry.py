from fastapi import APIRouter, Request
from pitwatch.api.schemas import LiveTelemetryResponse

router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])


@router.get("/live", response_model=LiveTelemetryResponse)
async def get_live_telemetry(request: Request):
    state = request.app.state.session_state
    snapshot = state.get_live_telemetry_snapshot()
    return LiveTelemetryResponse(**snapshot)
