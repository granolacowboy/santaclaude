from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class AIMessageBase(BaseModel):
    role: str  # 'user', 'assistant', 'system'
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None


class AIMessageCreate(AIMessageBase):
    pass


class AIMessage(AIMessageBase):
    id: int
    session_id: int
    tokens_used: Optional[int] = None
    cost: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AISessionBase(BaseModel):
    project_id: int
    card_id: Optional[int] = None
    provider: str
    model: str


class AISessionCreate(AISessionBase):
    initial_message: str
    system_prompt: Optional[str] = None


class AISessionUpdate(BaseModel):
    status: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class AISession(AISessionBase):
    id: int
    session_id: str
    user_id: int
    status: str
    context: Dict[str, Any]
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    messages: List[AIMessage] = []

    class Config:
        from_attributes = True


class AIProviderBase(BaseModel):
    name: str
    display_name: str
    base_url: Optional[str] = None
    config: Dict[str, Any] = {}


class AIProviderCreate(AIProviderBase):
    api_key: Optional[str] = None


class AIProviderUpdate(BaseModel):
    display_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None


class AIProvider(AIProviderBase):
    id: int
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AIModelBase(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    supports_functions: bool = False
    supports_vision: bool = False
    max_tokens: Optional[int] = None
    context_window: Optional[int] = None


class AIModelCreate(AIModelBase):
    provider_id: int
    input_cost: Optional[str] = None
    output_cost: Optional[str] = None


class AIModel(AIModelBase):
    id: int
    provider_id: int
    input_cost: Optional[str] = None
    output_cost: Optional[str] = None
    is_active: bool
    is_default: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    message: str
    project_id: int
    user_id: int  # Added since we now need to track this for the microservice
    session_id: Optional[str] = None
    card_id: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    stream: bool = True


class ChatResponse(BaseModel):
    session_id: str
    message: AIMessage
    status: str


class StreamingChatChunk(BaseModel):
    session_id: str
    chunk: str
    finished: bool = False
    message_id: Optional[int] = None


# Event schemas for message queue integration
class AIJobQueued(BaseModel):
    job_id: str
    session_id: str
    project_id: int
    user_id: int
    priority: str = "normal"
    created_at: datetime


class AIJobUpdated(BaseModel):
    job_id: str
    session_id: str
    status: str
    progress: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    updated_at: datetime