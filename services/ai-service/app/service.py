import uuid
import asyncio
import json
from typing import List, Optional, AsyncGenerator
from datetime import datetime
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func
import httpx

from app.core.config import get_settings
from app.models import AISession, AIMessage, AIProvider, AIModel
from app import schemas

settings = get_settings()


class AIService:
    def __init__(self, db: Session):
        self.db = db
    
    # Provider management
    async def list_providers(self) -> List[AIProvider]:
        """List all available AI providers"""
        return self.db.query(AIProvider).filter(AIProvider.is_active == True).all()
    
    async def list_models(self, provider_id: Optional[int] = None) -> List[AIModel]:
        """List all available AI models"""
        query = self.db.query(AIModel).filter(AIModel.is_active == True)
        
        if provider_id:
            query = query.filter(AIModel.provider_id == provider_id)
        
        return query.all()
    
    # Session management
    async def create_session(self, session_create: schemas.AISessionCreate, user_id: int) -> AISession:
        """Create a new AI session"""
        session_id = str(uuid.uuid4())
        
        db_session = AISession(
            session_id=session_id,
            project_id=session_create.project_id,
            card_id=session_create.card_id,
            user_id=user_id,
            provider=session_create.provider,
            model=session_create.model,
            status="active",
            context={}
        )
        
        self.db.add(db_session)
        self.db.commit()
        self.db.refresh(db_session)
        
        # Add initial system message if provided
        if hasattr(session_create, 'system_prompt') and session_create.system_prompt:
            await self.add_message(session_id, schemas.AIMessageCreate(
                role="system",
                content=session_create.system_prompt
            ))
        
        # Add initial user message
        if hasattr(session_create, 'initial_message') and session_create.initial_message:
            await self.add_message(session_id, schemas.AIMessageCreate(
                role="user", 
                content=session_create.initial_message
            ))
        
        return db_session
    
    async def get_session(self, session_id: str) -> Optional[AISession]:
        """Get an AI session with messages"""
        return (
            self.db.query(AISession)
            .options(selectinload(AISession.messages))
            .filter(AISession.session_id == session_id)
            .first()
        )
    
    async def add_message(self, session_id: str, message: schemas.AIMessageCreate) -> AIMessage:
        """Add a message to a session"""
        # Get session by session_id first
        session = await self.get_session(session_id)
        if not session:
            raise ValueError("Session not found")
        
        db_message = AIMessage(
            session_id=session.id,  # Use the internal ID, not the UUID
            role=message.role,
            content=message.content,
            tool_calls=message.tool_calls,
            tool_results=message.tool_results
        )
        
        self.db.add(db_message)
        self.db.commit()
        self.db.refresh(db_message)
        
        return db_message
    
    # Chat functionality
    async def chat(self, request: schemas.ChatRequest) -> schemas.ChatResponse:
        """Send a message and get AI response (non-streaming)"""
        # Create session if not provided
        if not request.session_id:
            session_create = schemas.AISessionCreate(
                project_id=request.project_id,
                card_id=request.card_id,
                provider=request.provider or "openai",
                model=request.model or "gpt-4",
                initial_message=request.message
            )
            session = await self.create_session(session_create, request.user_id)
            session_id = session.session_id
        else:
            session_id = request.session_id
            session = await self.get_session(session_id)
            if not session:
                raise ValueError("Session not found")
            
            # Add user message
            await self.add_message(session_id, schemas.AIMessageCreate(
                role="user",
                content=request.message
            ))
        
        # Get AI response
        ai_response = await self._generate_ai_response(session)
        
        # Add AI message
        ai_msg = await self.add_message(session_id, schemas.AIMessageCreate(
            role="assistant",
            content=ai_response["content"]
        ))
        
        return schemas.ChatResponse(
            session_id=session_id,
            message=ai_msg,
            status="completed"
        )
    
    async def chat_stream(self, request: schemas.ChatRequest) -> AsyncGenerator[schemas.StreamingChatChunk, None]:
        """Send a message and stream AI response"""
        # Create session if not provided
        if not request.session_id:
            session_create = schemas.AISessionCreate(
                project_id=request.project_id,
                card_id=request.card_id,
                provider=request.provider or "openai",
                model=request.model or "gpt-4",
                initial_message=request.message
            )
            session = await self.create_session(session_create, request.user_id)
            session_id = session.session_id
        else:
            session_id = request.session_id
            session = await self.get_session(session_id)
            if not session:
                raise ValueError("Session not found")
            
            # Add user message
            await self.add_message(session_id, schemas.AIMessageCreate(
                role="user",
                content=request.message
            ))
        
        # Stream AI response
        full_response = ""
        async for chunk in self._generate_ai_response_stream(session):
            full_response += chunk
            
            yield schemas.StreamingChatChunk(
                session_id=session_id,
                chunk=chunk,
                finished=False
            )
        
        # Add complete AI message
        ai_msg = await self.add_message(session_id, schemas.AIMessageCreate(
            role="assistant", 
            content=full_response
        ))
        
        # Final chunk with message ID
        yield schemas.StreamingChatChunk(
            session_id=session_id,
            chunk="",
            finished=True,
            message_id=ai_msg.id
        )
    
    async def _generate_ai_response(self, session: AISession) -> dict:
        """Generate AI response for a session"""
        # Get conversation history
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in session.messages
        ]
        
        if session.provider == "openai":
            return await self._call_openai(session.model, messages)
        elif session.provider == "anthropic":
            return await self._call_anthropic(session.model, messages)
        else:
            return {"content": f"AI provider '{session.provider}' not implemented yet."}
    
    async def _generate_ai_response_stream(self, session: AISession) -> AsyncGenerator[str, None]:
        """Generate streaming AI response for a session"""
        # Get conversation history
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in session.messages
        ]
        
        if session.provider == "openai":
            async for chunk in self._call_openai_stream(session.model, messages):
                yield chunk
        elif session.provider == "anthropic":
            async for chunk in self._call_anthropic_stream(session.model, messages):
                yield chunk
        else:
            yield f"AI provider '{session.provider}' not implemented yet."
    
    async def _call_openai(self, model: str, messages: list) -> dict:
        """Call OpenAI API"""
        if not settings.OPENAI_API_KEY:
            return {"content": "OpenAI API key not configured"}
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.7
                    },
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "content": data["choices"][0]["message"]["content"],
                        "tokens": data.get("usage", {})
                    }
                else:
                    return {"content": f"OpenAI API error: {response.status_code}"}
        
        except Exception as e:
            return {"content": f"Error calling OpenAI: {str(e)}"}
    
    async def _call_openai_stream(self, model: str, messages: list) -> AsyncGenerator[str, None]:
        """Call OpenAI API with streaming"""
        if not settings.OPENAI_API_KEY:
            yield "OpenAI API key not configured"
            return
        
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.7,
                        "stream": True
                    },
                    timeout=60.0
                ) as response:
                    if response.status_code != 200:
                        yield f"OpenAI API error: {response.status_code}"
                        return
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix
                            if data_str == "[DONE]":
                                break
                            
                            try:
                                data = json.loads(data_str)
                                if "choices" in data and len(data["choices"]) > 0:
                                    delta = data["choices"][0].get("delta", {})
                                    if "content" in delta:
                                        yield delta["content"]
                            except json.JSONDecodeError:
                                continue
        
        except Exception as e:
            yield f"Error calling OpenAI: {str(e)}"
    
    async def _call_anthropic(self, model: str, messages: list) -> dict:
        """Call Anthropic API"""
        if not settings.ANTHROPIC_API_KEY:
            return {"content": "Anthropic API key not configured"}
        
        # Convert messages format for Anthropic
        system_message = ""
        anthropic_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                anthropic_messages.append(msg)
        
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "model": model,
                    "max_tokens": 4096,
                    "messages": anthropic_messages
                }
                
                if system_message:
                    payload["system"] = system_message
                
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    },
                    json=payload,
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    content = ""
                    if data.get("content") and len(data["content"]) > 0:
                        content = data["content"][0].get("text", "")
                    
                    return {
                        "content": content,
                        "tokens": data.get("usage", {})
                    }
                else:
                    return {"content": f"Anthropic API error: {response.status_code}"}
        
        except Exception as e:
            return {"content": f"Error calling Anthropic: {str(e)}"}
    
    async def _call_anthropic_stream(self, model: str, messages: list) -> AsyncGenerator[str, None]:
        """Call Anthropic API with streaming"""
        if not settings.ANTHROPIC_API_KEY:
            yield "Anthropic API key not configured"
            return
        
        # Convert messages format for Anthropic
        system_message = ""
        anthropic_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                anthropic_messages.append(msg)
        
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "model": model,
                    "max_tokens": 4096,
                    "messages": anthropic_messages,
                    "stream": True
                }
                
                if system_message:
                    payload["system"] = system_message
                
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01"
                    },
                    json=payload,
                    timeout=60.0
                ) as response:
                    if response.status_code != 200:
                        yield f"Anthropic API error: {response.status_code}"
                        return
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix
                            
                            try:
                                data = json.loads(data_str)
                                if data.get("type") == "content_block_delta":
                                    delta = data.get("delta", {})
                                    if "text" in delta:
                                        yield delta["text"]
                            except json.JSONDecodeError:
                                continue
        
        except Exception as e:
            yield f"Error calling Anthropic: {str(e)}"