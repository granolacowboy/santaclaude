import os
from typing import List, Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server config
    HOST: str = "0.0.0.0"
    PORT: int = 8003
    DEBUG: bool = False
    
    # CORS
    CORS_ORIGINS: List[str] = ["*"]
    
    # Storage Backend Configuration
    STORAGE_BACKEND: str = "clickhouse"  # clickhouse, s3, both
    
    # ClickHouse Configuration
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 9000
    CLICKHOUSE_DATABASE: str = "audit"
    CLICKHOUSE_USERNAME: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_SECURE: bool = False
    
    # S3 Configuration
    S3_BUCKET: str = "audit-logs"
    S3_REGION: str = "us-west-2"
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None  # For MinIO or other S3-compatible
    S3_PREFIX: str = "audit-events"
    
    # Buffering and Flushing
    BUFFER_SIZE: int = 1000  # Number of events before flush
    FLUSH_INTERVAL: int = 30  # Seconds between forced flushes
    BATCH_SIZE: int = 100    # Events per batch insert
    
    # Event Retention
    RETENTION_DAYS: int = 365
    
    # Redis for event streaming (optional)
    REDIS_URL: str = "redis://localhost:6379/3"
    REDIS_STREAM_NAME: str = "audit-events"
    
    # Security and Privacy
    ENABLE_PII_MASKING: bool = True
    PII_FIELDS: List[str] = ["email", "phone", "ssn", "credit_card"]
    
    # Observability
    OTEL_SERVICE_NAME: str = "audit-sink-service"
    JAEGER_ENDPOINT: str = ""
    
    # Performance
    COMPRESSION_ENABLED: bool = True
    COMPRESSION_CODEC: str = "zstd"  # gzip, zstd, lz4

    class Config:
        env_file = ".env"


_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings