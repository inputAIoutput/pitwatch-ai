from typing import Optional
from fastapi import APIRouter, Query, Request
from pitwatch.api.schemas import RaceControlMessagesResponse, SessionCurrentResponse

router = APIRouter(prefix="/v1/session", tags=["session"])


@router.get("/current", response_model=SessionCurrentResponse)
async def get_current_session(request: Request):
    state = request.app.state.session_state
    summary = state.get_session_summary()
    return SessionCurrentResponse(**summary)


@router.get("/race-control", response_model=RaceControlMessagesResponse)
async def get_race_control_messages(
    request: Request,
    category: Optional[str] = Query(default=None, description="Filter by category (Flag, Drs, SafetyCar, Other)"),
    flag: Optional[str] = Query(default=None, description="Filter by flag (YELLOW, GREEN, RED, BLUE, CHEQUERED)"),
    limit: Optional[int] = Query(default=None, ge=1, description="Limit number of recent messages returned"),
):
    """Retrieve official FIA Race Director and Race Control notices for the active session."""
    state = request.app.state.session_state
    msgs = state.get_race_control_messages(category=category, flag=flag, limit=limit)
    return RaceControlMessagesResponse(
        session_key=state.session_key,
        current_session_time=state.current_session_time,
        total_messages=len(msgs),
        messages=msgs,
    )


@router.get("/messages", response_model=RaceControlMessagesResponse)
async def get_session_messages(
    request: Request,
    category: Optional[str] = Query(default=None, description="Filter by category (Flag, Drs, SafetyCar, Other)"),
    flag: Optional[str] = Query(default=None, description="Filter by flag (YELLOW, GREEN, RED, BLUE, CHEQUERED)"),
    limit: Optional[int] = Query(default=None, ge=1, description="Limit number of recent messages returned"),
):
    """Convenience alias for /v1/session/race-control."""
    return await get_race_control_messages(request, category=category, flag=flag, limit=limit)
