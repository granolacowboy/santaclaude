import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server config
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    DEBUG: bool = False
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Database
    DATABASE_URL: str = "sqlite:///./ai_service.db"
    
    # AI Provider APIs
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    
    # Message Queue (Redis)
    REDIS_URL: str = "redis://localhost:6379/0"
    MQ_ENABLED: bool = True
    
    # Observability
    OTEL_SERVICE_NAME: str = "ai-service"
    JAEGER_ENDPOINT: str = ""
    
    # Security
    SECRET_KEY: str = "change-this-in-production"
    
    # Feature Flags
    ASYNC_PROCESSING: bool = True
    STREAMING_ENABLED: bool = True

    class Config:
        env_file = ".env"


_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings