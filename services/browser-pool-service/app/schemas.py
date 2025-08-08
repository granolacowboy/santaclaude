from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class BrowserSessionCreate(BaseModel):
    user_id: Optional[int] = None
    metadata: Dict[str, Any] = {}


class BrowserSession(BaseModel):
    session_id: str
    created_at: datetime
    last_activity: datetime
    page_count: int
    metadata: Dict[str, Any]

    class Config:
        from_attributes = True


class PageCreate(BaseModel):
    url: Optional[str] = None


class PageInfo(BaseModel):
    page_id: str
    url: str
    title: str
    created_at: datetime


class NavigateRequest(BaseModel):
    url: str
    wait_until: str = "load"  # load, domcontentloaded, networkidle
    timeout: int = 30000  # milliseconds


class ScreenshotRequest(BaseModel):
    full_page: bool = False
    format: str = "png"  # png, jpeg
    quality: Optional[int] = None  # For JPEG


class ElementAction(BaseModel):
    selector: str
    action: str  # click, type, select, etc.
    value: Optional[str] = None
    timeout: int = 30000


class EvaluateRequest(BaseModel):
    expression: str
    await_promise: bool = False


class WaitRequest(BaseModel):
    selector: Optional[str] = None
    url_pattern: Optional[str] = None
    timeout: int = 30000
    state: str = "visible"  # visible, hidden, attached, detached


class BrowserPoolStats(BaseModel):
    total_browsers: int
    active_sessions: int
    available_slots: int
    session_details: List[Dict[str, Any]]


# Event schemas for message queue integration
class BrowserSessionEvent(BaseModel):
    session_id: str
    event_type: str  # created, closed, expired
    user_id: Optional[int] = None
    metadata: Dict[str, Any] = {}
    timestamp: datetime


class PageEvent(BaseModel):
    session_id: str
    page_id: str
    event_type: str  # created, navigated, closed
    url: Optional[str] = None
    timestamp: datetime