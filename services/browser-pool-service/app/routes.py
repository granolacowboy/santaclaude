"""
Browser Pool Service Routes
Provides HTTP/WebSocket API for browser automation
"""

import base64
import json
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import Response

from app.browser_pool import BrowserPool
from app import schemas

router = APIRouter()

def get_browser_pool(request: Request) -> BrowserPool:
    """Dependency to get browser pool from app state"""
    return request.app.state.browser_pool

# Session Management
@router.post("/sessions", response_model=schemas.BrowserSession)
async def create_session(
    session_create: schemas.BrowserSessionCreate,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Create a new browser session"""
    try:
        session_id = await pool.create_session(
            user_id=session_create.user_id,
            metadata=session_create.metadata
        )
        
        session = await pool.get_session(session_id)
        if not session:
            raise HTTPException(status_code=500, detail="Failed to create session")
        
        return schemas.BrowserSession(
            session_id=session.session_id,
            created_at=session.created_at,
            last_activity=session.last_activity,
            page_count=len(session.pages),
            metadata=session.metadata
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/sessions/{session_id}", response_model=schemas.BrowserSession)
async def get_session(
    session_id: str,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Get browser session information"""
    session = await pool.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return schemas.BrowserSession(
        session_id=session.session_id,
        created_at=session.created_at,
        last_activity=session.last_activity,
        page_count=len(session.pages),
        metadata=session.metadata
    )

@router.delete("/sessions/{session_id}")
async def close_session(
    session_id: str,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Close a browser session"""
    success = await pool.close_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"message": "Session closed successfully"}

@router.get("/sessions", response_model=List[schemas.BrowserSession])
async def list_sessions(
    pool: BrowserPool = Depends(get_browser_pool)
):
    """List all active sessions"""
    sessions = []
    for session in pool.active_sessions.values():
        sessions.append(schemas.BrowserSession(
            session_id=session.session_id,
            created_at=session.created_at,
            last_activity=session.last_activity,
            page_count=len(session.pages),
            metadata=session.metadata
        ))
    return sessions

# Page Management
@router.post("/sessions/{session_id}/pages")
async def create_page(
    session_id: str,
    page_create: schemas.PageCreate,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Create a new page in a session"""
    page_id = await pool.create_page(session_id, page_create.url)
    if not page_id:
        raise HTTPException(status_code=400, detail="Failed to create page")
    
    return {"page_id": page_id, "session_id": session_id}

@router.get("/sessions/{session_id}/pages/{page_id}")
async def get_page_info(
    session_id: str,
    page_id: str,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Get page information"""
    page = await pool.get_page(session_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    try:
        return {
            "page_id": page_id,
            "url": page.url,
            "title": await page.title(),
            "session_id": session_id
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/sessions/{session_id}/pages/{page_id}")
async def close_page(
    session_id: str,
    page_id: str,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Close a page"""
    success = await pool.close_page(session_id, page_id)
    if not success:
        raise HTTPException(status_code=404, detail="Page not found")
    
    return {"message": "Page closed successfully"}

# Browser Actions
@router.post("/sessions/{session_id}/pages/{page_id}/navigate")
async def navigate_page(
    session_id: str,
    page_id: str,
    navigate_req: schemas.NavigateRequest,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Navigate page to URL"""
    page = await pool.get_page(session_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    try:
        await page.goto(
            navigate_req.url,
            wait_until=navigate_req.wait_until,
            timeout=navigate_req.timeout
        )
        return {
            "message": "Navigation successful",
            "url": page.url,
            "title": await page.title()
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/sessions/{session_id}/pages/{page_id}/screenshot")
async def take_screenshot(
    session_id: str,
    page_id: str,
    screenshot_req: schemas.ScreenshotRequest,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Take a screenshot of the page"""
    page = await pool.get_page(session_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    try:
        screenshot_options = {
            "full_page": screenshot_req.full_page,
            "type": screenshot_req.format
        }
        
        if screenshot_req.format == "jpeg" and screenshot_req.quality:
            screenshot_options["quality"] = screenshot_req.quality
        
        screenshot_bytes = await page.screenshot(**screenshot_options)
        
        # Return as base64 encoded string
        screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
        
        return {
            "screenshot": screenshot_b64,
            "format": screenshot_req.format,
            "page_id": page_id
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/sessions/{session_id}/pages/{page_id}/action")
async def perform_action(
    session_id: str,
    page_id: str,
    action: schemas.ElementAction,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Perform an action on page element"""
    page = await pool.get_page(session_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    try:
        element = page.locator(action.selector)
        
        if action.action == "click":
            await element.click(timeout=action.timeout)
        elif action.action == "type":
            if not action.value:
                raise HTTPException(status_code=400, detail="Value required for type action")
            await element.fill(action.value, timeout=action.timeout)
        elif action.action == "select":
            if not action.value:
                raise HTTPException(status_code=400, detail="Value required for select action")
            await element.select_option(action.value, timeout=action.timeout)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported action: {action.action}")
        
        return {"message": f"Action '{action.action}' performed successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/sessions/{session_id}/pages/{page_id}/evaluate")
async def evaluate_expression(
    session_id: str,
    page_id: str,
    evaluate_req: schemas.EvaluateRequest,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Evaluate JavaScript expression on page"""
    page = await pool.get_page(session_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    try:
        if evaluate_req.await_promise:
            result = await page.evaluate(f"async () => {{ return await ({evaluate_req.expression}); }}")
        else:
            result = await page.evaluate(evaluate_req.expression)
        
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/sessions/{session_id}/pages/{page_id}/wait")
async def wait_for_condition(
    session_id: str,
    page_id: str,
    wait_req: schemas.WaitRequest,
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Wait for a condition on the page"""
    page = await pool.get_page(session_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    try:
        if wait_req.selector:
            await page.wait_for_selector(
                wait_req.selector,
                state=wait_req.state,
                timeout=wait_req.timeout
            )
        elif wait_req.url_pattern:
            await page.wait_for_url(wait_req.url_pattern, timeout=wait_req.timeout)
        else:
            raise HTTPException(status_code=400, detail="Either selector or url_pattern required")
        
        return {"message": "Wait condition satisfied"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Pool Management
@router.get("/stats", response_model=schemas.BrowserPoolStats)
async def get_pool_stats(
    pool: BrowserPool = Depends(get_browser_pool)
):
    """Get browser pool statistics"""
    stats = pool.get_stats()
    return schemas.BrowserPoolStats(**stats)