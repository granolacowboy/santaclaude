from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json

from app.core.database import get_db
from app.auth.service import AuthService
from app.projects.service import ProjectService
from app.ai import schemas
from app.ai.service import AIService

router = APIRouter()
security = HTTPBearer()


async def get_current_user(token: str = Depends(security), db: Session = Depends(get_db)):
    """Dependency to get current authenticated user"""
    auth_service = AuthService(db)
    user = await auth_service.get_current_user(token.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    return user


# Provider management routes
@router.get("/providers", response_model=List[schemas.AIProvider])
async def list_providers(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all available AI providers"""
    ai_service = AIService(db)
    return await ai_service.list_providers()


@router.get("/models", response_model=List[schemas.AIModel])
async def list_models(
    provider_id: int = None,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all available AI models, optionally filtered by provider"""
    ai_service = AIService(db)
    return await ai_service.list_models(provider_id)


# Session management routes
@router.post("/sessions", response_model=schemas.AISession)
async def create_session(
    session_create: schemas.AISessionCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new AI session"""
    project_service = ProjectService(db)
    
    # Check project access
    project_role = project_service._check_project_permission(
        session_create.project_id, current_user.id
    )
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    ai_service = AIService(db)
    return await ai_service.create_session(session_create, current_user.id)


@router.get("/sessions/{session_id}", response_model=schemas.AISession)
async def get_session(
    session_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get an AI session with messages"""
    ai_service = AIService(db)
    project_service = ProjectService(db)
    
    session = await ai_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check project access
    project_role = project_service._check_project_permission(
        session.project_id, current_user.id
    )
    if not project_role:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return session


# Chat routes
@router.post("/chat")
async def chat(
    chat_request: schemas.ChatRequest,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send a message to an AI session"""
    ai_service = AIService(db)
    project_service = ProjectService(db)
    
    # Get or create session
    if chat_request.session_id:
        session = await ai_service.get_session(chat_request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        # Need to create a new session - require project context
        if not chat_request.card_id:
            raise HTTPException(status_code=400, detail="Either session_id or card_id required")
        
        # Get card to determine project
        from app.kanban.service import KanbanService
        kanban_service = KanbanService(db)
        card = await kanban_service.get_card(chat_request.card_id)
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        
        column = await kanban_service.get_column(card.column_id)
        board = await kanban_service.get_board(column.board_id)
        
        # Create new session
        session_create = schemas.AISessionCreate(
            project_id=board.project_id,
            card_id=chat_request.card_id,
            provider="openai",  # Default provider
            model="gpt-4",      # Default model
            initial_message=chat_request.message
        )
        
        session = await ai_service.create_session(session_create, current_user.id)
    
    # Check project access
    project_role = project_service._check_project_permission(session.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Handle streaming vs non-streaming response
    if chat_request.stream:
        async def generate_stream():
            async for chunk in ai_service.chat_stream(session.session_id, chat_request.message):
                yield f"data: {json.dumps(chunk.model_dump())}\n\n"
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(
            generate_stream(),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache"}
        )
    else:
        response = await ai_service.chat(session.session_id, chat_request.message)
        return response


@router.post("/sessions/{session_id}/messages", response_model=schemas.AIMessage)
async def add_message(
    session_id: str,
    message: schemas.AIMessageCreate,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a message to a session"""
    ai_service = AIService(db)
    project_service = ProjectService(db)
    
    session = await ai_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check project access
    project_role = project_service._check_project_permission(session.project_id, current_user.id)
    can_edit, _ = project_service._get_user_role_permissions(project_role)
    
    if not can_edit:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return await ai_service.add_message(session_id, message)