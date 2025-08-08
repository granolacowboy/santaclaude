#!/usr/bin/env python3
"""
Audit Sink Service - Phase 2 Extraction
Append-only audit sink with ClickHouse and S3 backends
"""

import uvicorn
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routes import router as audit_router
from app.audit_sink import AuditSink

settings = get_settings()

# Global audit sink instance
audit_sink = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize audit sink
    global audit_sink
    audit_sink = AuditSink()
    await audit_sink.start()
    
    # Make sink available to routes
    app.state.audit_sink = audit_sink
    
    yield
    
    # Shutdown: Clean up audit sink
    if audit_sink:
        await audit_sink.stop()

app = FastAPI(
    title="Audit Sink Service",
    description="Append-only audit sink with ClickHouse/S3 storage - Phase 2 extracted service",
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

app.include_router(audit_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "service": "audit-sink-service",
        "storage_backend": settings.STORAGE_BACKEND,
        "buffer_size": len(audit_sink.buffer) if audit_sink else 0
    }

@app.get("/ready")
async def readiness_check():
    """Readiness check for K8s"""
    if not audit_sink or not audit_sink.is_ready():
        return {"status": "not ready", "service": "audit-sink-service"}
    
    return {
        "status": "ready", 
        "service": "audit-sink-service",
        "storage_backend": settings.STORAGE_BACKEND,
        "buffer_size": len(audit_sink.buffer),
        "last_flush": audit_sink.last_flush_time.isoformat() if audit_sink.last_flush_time else None
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug",
    )