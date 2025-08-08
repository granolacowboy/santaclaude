"""
Audit Sink Service Routes
Provides HTTP API for audit event ingestion and querying
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from datetime import datetime

from app.audit_sink import AuditSink, AuditEvent
from app import schemas

router = APIRouter()

def get_audit_sink(request: Request) -> AuditSink:
    """Dependency to get audit sink from app state"""
    return request.app.state.audit_sink

# Event Ingestion
@router.post("/events", response_model=schemas.AuditEventResponse)
async def create_audit_event(
    event_create: schemas.AuditEventCreate,
    background_tasks: BackgroundTasks,
    sink: AuditSink = Depends(get_audit_sink)
):
    """Create a single audit event"""
    try:
        event = AuditEvent(
            event_type=event_create.event_type,
            user_id=event_create.user_id,
            resource=event_create.resource,
            action=event_create.action,
            metadata=event_create.metadata,
            request_id=event_create.request_id,
            session_id=event_create.session_id
        )
        
        # Write asynchronously in background
        background_tasks.add_task(sink.write_event, event)
        
        return schemas.AuditEventResponse(
            event_id=event.event_id,
            timestamp=event.timestamp,
            event_type=event.event_type,
            user_id=event.user_id,
            resource=event.resource,
            action=event.action,
            metadata=event.metadata,
            request_id=event.request_id,
            session_id=event.session_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/events/batch")
async def create_audit_events_batch(
    batch: schemas.AuditEventBatch,
    background_tasks: BackgroundTasks,
    sink: AuditSink = Depends(get_audit_sink)
):
    """Create multiple audit events in batch"""
    try:
        events = []
        for event_create in batch.events:
            event = AuditEvent(
                event_type=event_create.event_type,
                user_id=event_create.user_id,
                resource=event_create.resource,
                action=event_create.action,
                metadata=event_create.metadata,
                request_id=event_create.request_id,
                session_id=event_create.session_id
            )
            events.append(event)
        
        # Write asynchronously in background
        background_tasks.add_task(sink.write_events, events)
        
        return {
            "message": f"Queued {len(events)} audit events for processing",
            "event_count": len(events)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Specialized event endpoints
@router.post("/events/user", response_model=schemas.AuditEventResponse)
async def create_user_audit_event(
    event_create: schemas.UserAuditEvent,
    background_tasks: BackgroundTasks,
    sink: AuditSink = Depends(get_audit_sink)
):
    """Create a user action audit event"""
    return await create_audit_event(event_create, background_tasks, sink)

@router.post("/events/system", response_model=schemas.AuditEventResponse)
async def create_system_audit_event(
    event_create: schemas.SystemAuditEvent,
    background_tasks: BackgroundTasks,
    sink: AuditSink = Depends(get_audit_sink)
):
    """Create a system event audit"""
    return await create_audit_event(event_create, background_tasks, sink)

@router.post("/events/security", response_model=schemas.AuditEventResponse)
async def create_security_audit_event(
    event_create: schemas.SecurityAuditEvent,
    background_tasks: BackgroundTasks,
    sink: AuditSink = Depends(get_audit_sink)
):
    """Create a security event audit"""
    return await create_audit_event(event_create, background_tasks, sink)

@router.post("/events/data", response_model=schemas.AuditEventResponse)
async def create_data_audit_event(
    event_create: schemas.DataAuditEvent,
    background_tasks: BackgroundTasks,
    sink: AuditSink = Depends(get_audit_sink)
):
    """Create a data access audit event"""
    return await create_audit_event(event_create, background_tasks, sink)

# Administrative endpoints
@router.post("/flush")
async def flush_buffer(
    sink: AuditSink = Depends(get_audit_sink)
):
    """Manually flush the event buffer"""
    try:
        await sink._flush_buffer()
        return {"message": "Buffer flushed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/stats", response_model=schemas.SinkStats)
async def get_sink_stats(
    sink: AuditSink = Depends(get_audit_sink)
):
    """Get audit sink statistics"""
    stats = sink.get_stats()
    return schemas.SinkStats(**stats)

# Simple query endpoint (for debugging/monitoring)
# Note: In production, queries should go directly to ClickHouse/S3
@router.get("/events/recent")
async def get_recent_events(
    limit: int = 10,
    sink: AuditSink = Depends(get_audit_sink)
):
    """Get recent events from buffer (for debugging only)"""
    # This is just showing buffered events, not querying storage
    recent_events = list(sink.buffer)[-limit:] if sink.buffer else []
    
    return {
        "events": [
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "event_type": event.event_type,
                "user_id": event.user_id,
                "resource": event.resource,
                "action": event.action,
                "request_id": event.request_id
            }
            for event in recent_events
        ],
        "count": len(recent_events),
        "note": "These are buffered events only, not from storage"
    }

# Health and monitoring
@router.get("/metrics")
async def get_metrics(
    sink: AuditSink = Depends(get_audit_sink)
):
    """Get Prometheus-style metrics"""
    stats = sink.get_stats()
    
    return {
        "audit_sink_buffer_size": stats["buffer_size"],
        "audit_sink_buffer_max_size": stats["buffer_max_size"],
        "audit_sink_backends_count": stats["backends_count"],
        "audit_sink_running": 1 if stats["running"] else 0,
        "audit_sink_last_flush_timestamp": (
            int(datetime.fromisoformat(stats["last_flush_time"]).timestamp()) 
            if stats["last_flush_time"] else 0
        )
    }