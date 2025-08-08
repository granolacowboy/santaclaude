import os
from typing import List, Dict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server config
    HOST: str = "0.0.0.0"
    PORT: int = 8004
    DEBUG: bool = False
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Redis Configuration
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_RETRY_ON_TIMEOUT: bool = True
    
    # Stream Configuration
    DEFAULT_MAX_LEN: int = 10000  # Max messages per stream
    CONSUMER_BLOCK_TIME: int = 1000  # milliseconds
    CONSUMER_COUNT: int = 2  # Default consumer group size
    
    # Event Types and Routing
    EVENT_STREAMS: Dict[str, str] = {
        "user.created": "user-events",
        "user.updated": "user-events", 
        "user.deleted": "user-events",
        "project.created": "project-events",
        "project.archived": "project-events",
        "card.created": "kanban-events",
        "card.moved": "kanban-events",
        "ai.job.queued": "ai-events",
        "ai.job.updated": "ai-events",
        "automation.job.started": "automation-events",
        "automation.job.completed": "automation-events",
        "browser.session.created": "browser-events",
        "browser.session.closed": "browser-events",
        "audit.event": "audit-events"
    }
    
    # Dead Letter Queue
    DLQ_ENABLED: bool = True
    DLQ_MAX_RETRIES: int = 3
    DLQ_STREAM_SUFFIX: str = "-dlq"
    
    # Observability
    OTEL_SERVICE_NAME: str = "message-queue-service"
    JAEGER_ENDPOINT: str = ""
    
    # Performance
    BATCH_SIZE: int = 100
    PROCESSING_TIMEOUT: int = 30  # seconds

    class Config:
        env_file = ".env"


_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings