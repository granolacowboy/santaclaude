from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class AuditEventCreate(BaseModel):
    event_type: str
    user_id: Optional[int] = None
    resource: str
    action: str
    metadata: Dict[str, Any] = {}
    request_id: Optional[str] = None
    session_id: Optional[str] = None


class AuditEventBatch(BaseModel):
    events: List[AuditEventCreate]


class AuditEventResponse(BaseModel):
    event_id: str
    timestamp: datetime
    event_type: str
    user_id: Optional[int]
    resource: str
    action: str
    metadata: Dict[str, Any]
    request_id: Optional[str]
    session_id: Optional[str]

    class Config:
        from_attributes = True


class AuditQuery(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    event_type: Optional[str] = None
    user_id: Optional[int] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    limit: int = 100
    offset: int = 0


class AuditQueryResult(BaseModel):
    events: List[AuditEventResponse]
    total_count: int
    has_more: bool


class SinkStats(BaseModel):
    buffer_size: int
    buffer_max_size: int
    backends_count: int
    storage_backend: str
    last_flush_time: Optional[datetime]
    running: bool


# Event schemas for different audit types
class UserAuditEvent(AuditEventCreate):
    event_type: str = "user_action"
    user_id: int
    

class SystemAuditEvent(AuditEventCreate):
    event_type: str = "system_event"
    user_id: Optional[int] = None


class SecurityAuditEvent(AuditEventCreate):
    event_type: str = "security_event"
    severity: str = "medium"  # low, medium, high, critical
    
    def __init__(self, **data):
        super().__init__(**data)
        if 'severity' in data:
            self.metadata['severity'] = data['severity']


class DataAuditEvent(AuditEventCreate):
    event_type: str = "data_event"
    data_classification: str = "internal"  # public, internal, confidential, restricted
    
    def __init__(self, **data):
        super().__init__(**data)
        if 'data_classification' in data:
            self.metadata['data_classification'] = data['data_classification']


# Webhook and streaming schemas
class WebhookConfig(BaseModel):
    url: str
    secret: Optional[str] = None
    events: List[str] = []  # Event types to send
    headers: Dict[str, str] = {}


class StreamingConfig(BaseModel):
    enabled: bool = True
    redis_stream: str = "audit-events"
    max_len: Optional[int] = 10000  # Max events in stream