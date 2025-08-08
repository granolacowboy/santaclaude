from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class AISession(Base):
    __tablename__ = "ai_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    
    # External references (stored as IDs since we don't own these entities)
    project_id = Column(Integer, nullable=False)
    card_id = Column(Integer, nullable=True)
    user_id = Column(Integer, nullable=False)
    
    # AI provider and model
    provider = Column(String, nullable=False)  # 'openai', 'anthropic', 'local'
    model = Column(String, nullable=False)     # 'gpt-4', 'claude-3', etc.
    
    # Session state
    status = Column(String, default="active")   # active, completed, failed, cancelled
    context = Column(JSON, default=dict)        # session context/memory
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    messages = relationship("AIMessage", back_populates="session", cascade="all, delete-orphan")


class AIMessage(Base):
    __tablename__ = "ai_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, nullable=False)
    
    # Message content
    role = Column(String, nullable=False)        # 'user', 'assistant', 'system'
    content = Column(Text, nullable=False)
    
    # Tool/function call support
    tool_calls = Column(JSON, nullable=True)     # function calls made by AI
    tool_results = Column(JSON, nullable=True)   # results from tool calls
    
    # Metadata
    tokens_used = Column(Integer, nullable=True)
    cost = Column(String, nullable=True)         # cost in USD (as string for precision)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("AISession", back_populates="messages")


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)    # 'openai', 'anthropic'
    display_name = Column(String, nullable=False)         # 'OpenAI', 'Anthropic'
    
    # Configuration
    api_key = Column(Text, nullable=True)                 # encrypted API key
    base_url = Column(String, nullable=True)              # for custom/local models
    config = Column(JSON, default=dict)                   # provider-specific config
    
    # Status
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships  
    models = relationship("AIModel", back_populates="provider", cascade="all, delete-orphan")


class AIModel(Base):
    __tablename__ = "ai_models"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(Integer, nullable=False)
    
    # Model info
    name = Column(String, nullable=False)                 # 'gpt-4-turbo'
    display_name = Column(String, nullable=False)         # 'GPT-4 Turbo'
    description = Column(Text, nullable=True)
    
    # Capabilities
    supports_functions = Column(Boolean, default=False)
    supports_vision = Column(Boolean, default=False)
    max_tokens = Column(Integer, nullable=True)
    context_window = Column(Integer, nullable=True)
    
    # Pricing (per 1K tokens)
    input_cost = Column(String, nullable=True)            # USD per 1K input tokens
    output_cost = Column(String, nullable=True)           # USD per 1K output tokens
    
    # Status
    is_active = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    provider = relationship("AIProvider", back_populates="models")