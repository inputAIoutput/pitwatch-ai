from fastapi import APIRouter, Request
from pitwatch.api.schemas import SessionCurrentResponse

router = APIRouter(prefix="/v1/session", tags=["session"])


@router.get("/current", response_model=SessionCurrentResponse)
async def get_current_session(request: Request):
    state = request.app.state.session_state
    summary = state.get_session_summary()
    return SessionCurrentResponse(**summary)
