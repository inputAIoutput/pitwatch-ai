from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pitwatch.api.routes import session, telemetry, stream
from pitwatch.state.session import LiveSessionState


def create_app(session_state: Optional[LiveSessionState] = None) -> FastAPI:
    app = FastAPI(
        title="PitWatch AI Intelligence API",
        version="0.1.0",
        description="Real-time multimodal ingestion and intelligence API for Formula 1.",
    )

    # Allow frontend clients to connect locally
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Attach LiveSessionState
    app.state.session_state = (
        session_state if session_state is not None else LiveSessionState(session_key=9558, circuit_name="Silverstone")
    )

    # Include routers
    app.include_router(session.router)
    app.include_router(telemetry.router)
    app.include_router(stream.router)

    return app
