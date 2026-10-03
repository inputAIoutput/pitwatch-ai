from fastapi import APIRouter, Request
from pitwatch.api.schemas import CurrentWeatherResponse

router = APIRouter(prefix="/v1/weather", tags=["weather"])


@router.get("/current", response_model=CurrentWeatherResponse)
async def get_current_weather(request: Request):
    state = request.app.state.session_state
    weather_summary = state.get_current_weather()
    return CurrentWeatherResponse(**weather_summary)
