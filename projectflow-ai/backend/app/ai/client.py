"""
HTTP client for AI service - replaces in-process AI service calls
This follows the Phase 2 service extraction pattern from the design plan.
"""

import httpx
import json
from typing import Optional, List, AsyncGenerator
from app.core.config import get_settings
from app.ai import schemas

settings = get_settings()


class AIServiceClient:
    """HTTP client for extracted AI service"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or settings.AI_SERVICE_URL
        self.timeout = httpx.Timeout(60.0, read=300.0)  # Long read timeout for streaming
    
    # Provider management
    async def list_providers(self) -> List[schemas.AIProvider]:
        """List all available AI providers"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v1/providers")
            response.raise_for_status()
            return [schemas.AIProvider(**item) for item in response.json()]
    
    async def list_models(self, provider_id: Optional[int] = None) -> List[schemas.AIModel]:
        """List all available AI models"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            params = {"provider_id": provider_id} if provider_id else {}
            response = await client.get(f"{self.base_url}/api/v1/models", params=params)
            response.raise_for_status()
            return [schemas.AIModel(**item) for item in response.json()]
    
    # Session management
    async def create_session(self, session_create: schemas.AISessionCreate, user_id: int) -> schemas.AISession:
        """Create a new AI session"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/sessions",
                json=session_create.dict(),
                params={"user_id": user_id}
            )
            response.raise_for_status()
            return schemas.AISession(**response.json())
    
    async def get_session(self, session_id: str) -> Optional[schemas.AISession]:
        """Get an AI session with messages"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v1/sessions/{session_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return schemas.AISession(**response.json())
    
    async def add_message(self, session_id: str, message: schemas.AIMessageCreate) -> schemas.AIMessage:
        """Add a message to a session"""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/sessions/{session_id}/messages",
                json=message.dict()
            )
            response.raise_for_status()
            return schemas.AIMessage(**response.json())
    
    # Chat functionality
    async def chat(self, request: schemas.ChatRequest) -> schemas.ChatResponse:
        """Send a message and get AI response (non-streaming)"""
        # Ensure streaming is disabled for this endpoint
        request.stream = False
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/chat",
                json=request.dict()
            )
            response.raise_for_status()
            return schemas.ChatResponse(**response.json())
    
    async def chat_stream(self, request: schemas.ChatRequest) -> AsyncGenerator[schemas.StreamingChatChunk, None]:
        """Send a message and stream AI response"""
        # Ensure streaming is enabled
        request.stream = True
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/v1/chat/stream",
                json=request.dict()
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]  # Remove "data: " prefix
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            data = json.loads(data_str)
                            yield schemas.StreamingChatChunk(**data)
                        except json.JSONDecodeError:
                            continue