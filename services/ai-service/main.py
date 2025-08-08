#!/usr/bin/env python3

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routes import router as ai_router

settings = get_settings()

app = FastAPI(
    title="AI Service",
    description="Microservice for AI model routing and session management",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ai-service"}

@app.get("/ready")
async def readiness_check():
    """Readiness check for K8s"""
    # Check database connection, external APIs, etc.
    return {"status": "ready", "service": "ai-service"}

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug",
    )