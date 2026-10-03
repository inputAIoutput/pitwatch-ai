from fastapi import APIRouter, Request
from pitwatch.strategy.pirelli import CircuitStrategyConfig
from pitwatch.strategy.engine import ThreatMatrixResponse

router = APIRouter(prefix="/v1/strategy", tags=["strategy"])


@router.get("/threat-matrix", response_model=ThreatMatrixResponse)
async def get_threat_matrix(request: Request):
    state = request.app.state.session_state
    return state.get_threat_matrix()


@router.get("/presets", response_model=CircuitStrategyConfig)
async def get_strategy_presets(request: Request):
    state = request.app.state.session_state
    return state.strategy_engine.strategy_config
