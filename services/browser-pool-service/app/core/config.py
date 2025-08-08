import os
from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server config
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DEBUG: bool = False
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Browser Pool Settings
    MAX_BROWSERS: int = 5
    BROWSER_TIMEOUT: int = 300  # 5 minutes
    BROWSER_TYPE: str = "chromium"  # chromium, firefox, webkit
    HEADLESS: bool = True
    
    # Browser Options
    VIEWPORT_WIDTH: int = 1920
    VIEWPORT_HEIGHT: int = 1080
    USER_AGENT: str = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    
    # Security
    ENABLE_SANDBOX: bool = True  # Set to False in containers if needed
    ALLOWED_DOMAINS: List[str] = []  # Empty means all domains allowed
    
    # Redis for session state (optional)
    REDIS_URL: str = "redis://localhost:6379/2"
    
    # Observability
    OTEL_SERVICE_NAME: str = "browser-pool-service"
    JAEGER_ENDPOINT: str = ""
    
    # Performance
    SESSION_CLEANUP_INTERVAL: int = 60  # seconds
    MAX_PAGE_LOAD_TIME: int = 30  # seconds

    class Config:
        env_file = ".env"


_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings