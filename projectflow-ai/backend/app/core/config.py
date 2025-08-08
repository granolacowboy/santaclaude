from functools import lru_cache
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Basic app settings
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost/projectflow_ai"
    
    # Redis for caching and message queue
    REDIS_URL: str = "redis://localhost:6379"
    
    # OAuth providers
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    
    # External services (Phase 2: moved to AI service)
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    
    # Microservices (Phase 2 service extraction)
    AI_SERVICE_URL: str = "http://localhost:8001"
    
    # Security
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()