from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="PitWatch AI API",
    description="Real-time multimodal radio and competitor intent intelligence engine for Formula 1.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "service": "PitWatch AI",
        "status": "operational",
        "version": "0.1.0",
        "endpoints": {
            "health": "/health",
            "stream": "/v1/stream/intents",
            "telemetry": "/v1/telemetry",
            "docs": "/docs",
        },
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
