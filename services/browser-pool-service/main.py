#!/usr/bin/env python3
"""
Browser Pool Service - Phase 2 Extraction
Playwright controller for browser automation tasks
"""

import uvicorn
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routes import router as browser_router
from app.hybrid_pool import HybridBrowserPool, BrowserPoolMode

settings = get_settings()

# Global browser pool instance
browser_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize hybrid browser pool
    global browser_pool
    
    # Determine pool mode from environment
    pool_mode_str = settings.BROWSER_POOL_MODE if hasattr(settings, 'BROWSER_POOL_MODE') else 'auto'
    try:
        pool_mode = BrowserPoolMode(pool_mode_str.lower())
    except ValueError:
        pool_mode = BrowserPoolMode.AUTO
    
    browser_pool = HybridBrowserPool(
        mode=pool_mode,
        node_service_host=getattr(settings, 'NODE_SERVICE_HOST', 'browser-pool-service-node'),
        node_grpc_port=getattr(settings, 'NODE_GRPC_PORT', 50051),
        node_ws_port=getattr(settings, 'NODE_WS_PORT', 8080)
    )
    await browser_pool.start()
    
    # Make pool available to routes
    app.state.browser_pool = browser_pool
    
    yield
    
    # Shutdown: Clean up browser pool
    if browser_pool:
        await browser_pool.stop()

app = FastAPI(
    title="Browser Pool Service (Hybrid)",
    description="Playwright controller with Python/Node.js hybrid backend - Phase 3 implementation",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(browser_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "service": "browser-pool-service",
        "active_sessions": len(browser_pool.active_sessions) if browser_pool else 0
    }

@app.get("/ready")
async def readiness_check():
    """Readiness check for K8s"""
    if not browser_pool or not browser_pool.is_ready():
        return {"status": "not ready", "service": "browser-pool-service"}
    
    return {
        "status": "ready", 
        "service": "browser-pool-service",
        "available_browsers": browser_pool.available_count(),
        "active_sessions": len(browser_pool.active_sessions)
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug",
    )