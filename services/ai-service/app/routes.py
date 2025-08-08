from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json

from app.core.database import get_db
from app.service import AIService
from app import schemas
from app.models import AIProvider, AIModel

router = APIRouter()

def get_ai_service(db: Session = Depends(get_db)) -> AIService:
    return AIService(db)

# Provider management endpoints
@router.get("/providers", response_model=List[schemas.AIProvider])
async def list_providers(
    ai_service: AIService = Depends(get_ai_service)
):
    """List all available AI providers"""
    return await ai_service.list_providers()

@router.get("/models", response_model=List[schemas.AIModel])
async def list_models(
    provider_id: int = None,
    ai_service: AIService = Depends(get_ai_service)
):
    """List all available AI models"""
    return await ai_service.list_models(provider_id)

# Session management endpoints
@router.post("/sessions", response_model=schemas.AISession)
async def create_session(
    session_create: schemas.AISessionCreate,
    user_id: int,  # In a real implementation, this would come from JWT auth
    ai_service: AIService = Depends(get_ai_service)
):
    """Create a new AI session"""
    try:
        return await ai_service.create_session(session_create, user_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/sessions/{session_id}", response_model=schemas.AISession)
async def get_session(
    session_id: str,
    ai_service: AIService = Depends(get_ai_service)
):
    """Get an AI session with messages"""
    session = await ai_service.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    return session

@router.post("/sessions/{session_id}/messages", response_model=schemas.AIMessage)
async def add_message(
    session_id: str,
    message: schemas.AIMessageCreate,
    ai_service: AIService = Depends(get_ai_service)
):
    """Add a message to a session"""
    try:
        return await ai_service.add_message(session_id, message)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# Chat endpoints
@router.post("/chat", response_model=schemas.ChatResponse)
async def chat(
    request: schemas.ChatRequest,
    ai_service: AIService = Depends(get_ai_service)
):
    """Send a message and get AI response (non-streaming)"""
    if request.stream:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /chat/stream for streaming responses"
        )
    
    try:
        return await ai_service.chat(request)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.post("/chat/stream")
async def chat_stream(
    request: schemas.ChatRequest,
    ai_service: AIService = Depends(get_ai_service)
):
    """Send a message and stream AI response"""
    try:
        async def stream_generator():
            async for chunk in ai_service.chat_stream(request):
                yield f"data: {json.dumps(chunk.dict())}\n\n"
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(
            stream_generator(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )