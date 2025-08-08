#!/usr/bin/env python3
"""
Message Queue Service - Phase 2 Implementation
Redis Streams-based event distribution for microservices
"""

import uvicorn
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routes import router as mq_router
from app.event_dispatcher import EventDispatcher

settings = get_settings()

# Global event dispatcher instance
event_dispatcher = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize event dispatcher
    global event_dispatcher
    event_dispatcher = EventDispatcher()
    await event_dispatcher.start()
    
    # Make dispatcher available to routes
    app.state.event_dispatcher = event_dispatcher
    
    yield
    
    # Shutdown: Clean up event dispatcher
    if event_dispatcher:
        await event_dispatcher.stop()

app = FastAPI(
    title="Message Queue Service",
    description="Redis Streams-based event distribution for microservices - Phase 2",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mq_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "service": "message-queue-service",
        "active_streams": len(event_dispatcher.streams) if event_dispatcher else 0,
        "active_consumers": len(event_dispatcher.consumers) if event_dispatcher else 0
    }

@app.get("/ready")
async def readiness_check():
    """Readiness check for K8s"""
    if not event_dispatcher or not event_dispatcher.is_ready():
        return {"status": "not ready", "service": "message-queue-service"}
    
    return {
        "status": "ready", 
        "service": "message-queue-service",
        "redis_connected": event_dispatcher.redis.ping() if event_dispatcher.redis else False
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug",
    )