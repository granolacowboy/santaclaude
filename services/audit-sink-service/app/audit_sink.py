"""
Audit Sink - High-performance audit log processing
Supports ClickHouse and S3 backends with buffering and compression
"""

import asyncio
import json
import gzip
import zstd
import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from collections import deque
import logging

from clickhouse_driver import Client as ClickHouseClient
import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class PIIMasker:
    """Handles PII masking and data sanitization"""
    
    def __init__(self):
        # Common PII patterns
        self.patterns = {
            'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            'phone': re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
            'ssn': re.compile(r'\b\d{3}[-.]?\d{2}[-.]?\d{4}\b'),
            'credit_card': re.compile(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b'),
            'ip_address': re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')
        }
    
    def mask_pii(self, data: Any) -> Any:
        """Recursively mask PII in data structures"""
        if isinstance(data, dict):
            return {key: self.mask_pii(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self.mask_pii(item) for item in data]
        elif isinstance(data, str):
            return self._mask_string(data)
        else:
            return data
    
    def _mask_string(self, text: str) -> str:
        """Mask PII in a string"""
        for field_name, pattern in self.patterns.items():
            if field_name in settings.PII_FIELDS:
                text = pattern.sub(lambda m: self._mask_match(m.group()), text)
        return text
    
    def _mask_match(self, match: str) -> str:
        """Replace matched text with masked version"""
        if len(match) <= 4:
            return '*' * len(match)
        else:
            return match[:2] + '*' * (len(match) - 4) + match[-2:]


class AuditEvent:
    """Represents an audit event"""
    
    def __init__(self, event_type: str, user_id: Optional[int], resource: str, 
                 action: str, metadata: Dict[str, Any] = None, 
                 request_id: Optional[str] = None, session_id: Optional[str] = None):
        self.event_id = hashlib.sha256(f"{datetime.utcnow().isoformat()}-{user_id}-{action}".encode()).hexdigest()[:16]
        self.timestamp = datetime.utcnow()
        self.event_type = event_type
        self.user_id = user_id
        self.resource = resource
        self.action = action
        self.metadata = metadata or {}
        self.request_id = request_id
        self.session_id = session_id
        
        # Add contextual information
        self.metadata['timestamp_iso'] = self.timestamp.isoformat()
        self.metadata['service_version'] = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'event_id': self.event_id,
            'timestamp': self.timestamp,
            'event_type': self.event_type,
            'user_id': self.user_id,
            'resource': self.resource,
            'action': self.action,
            'metadata': self.metadata,
            'request_id': self.request_id,
            'session_id': self.session_id
        }


class ClickHouseBackend:
    """ClickHouse storage backend for audit events"""
    
    def __init__(self):
        self.client = ClickHouseClient(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            database=settings.CLICKHOUSE_DATABASE,
            user=settings.CLICKHOUSE_USERNAME,
            password=settings.CLICKHOUSE_PASSWORD,
            secure=settings.CLICKHOUSE_SECURE
        )
        self._initialized = False
    
    async def initialize(self):
        """Initialize ClickHouse tables"""
        if self._initialized:
            return
            
        try:
            # Create database if not exists
            self.client.execute(f"CREATE DATABASE IF NOT EXISTS {settings.CLICKHOUSE_DATABASE}")
            
            # Create audit events table
            create_table_query = """
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id String,
                timestamp DateTime64(3),
                event_type String,
                user_id Nullable(UInt64),
                resource String,
                action String,
                metadata String,
                request_id Nullable(String),
                session_id Nullable(String),
                date Date MATERIALIZED toDate(timestamp)
            ) ENGINE = MergeTree()
            PARTITION BY date
            ORDER BY (timestamp, event_type, user_id)
            SETTINGS index_granularity = 8192
            """
            self.client.execute(create_table_query)
            
            # Create TTL for data retention
            if settings.RETENTION_DAYS > 0:
                ttl_query = f"""
                ALTER TABLE audit_events MODIFY TTL 
                timestamp + INTERVAL {settings.RETENTION_DAYS} DAY
                """
                self.client.execute(ttl_query)
            
            self._initialized = True
            logger.info("ClickHouse backend initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize ClickHouse: {e}")
            raise
    
    async def write_batch(self, events: List[AuditEvent]):
        """Write a batch of events to ClickHouse"""
        if not events:
            return
            
        try:
            data = []
            for event in events:
                data.append([
                    event.event_id,
                    event.timestamp,
                    event.event_type,
                    event.user_id,
                    event.resource,
                    event.action,
                    json.dumps(event.metadata),
                    event.request_id,
                    event.session_id
                ])
            
            self.client.execute(
                "INSERT INTO audit_events VALUES",
                data
            )
            logger.info(f"Wrote {len(events)} events to ClickHouse")
            
        except Exception as e:
            logger.error(f"Failed to write to ClickHouse: {e}")
            raise


class S3Backend:
    """S3 storage backend for audit events"""
    
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            endpoint_url=settings.S3_ENDPOINT_URL
        )
        self._bucket_exists = False
    
    async def initialize(self):
        """Initialize S3 bucket"""
        if self._bucket_exists:
            return
            
        try:
            # Check if bucket exists
            self.s3_client.head_bucket(Bucket=settings.S3_BUCKET)
            self._bucket_exists = True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                # Create bucket
                self.s3_client.create_bucket(
                    Bucket=settings.S3_BUCKET,
                    CreateBucketConfiguration={
                        'LocationConstraint': settings.S3_REGION
                    }
                )
                self._bucket_exists = True
                logger.info(f"Created S3 bucket: {settings.S3_BUCKET}")
            else:
                logger.error(f"Failed to initialize S3: {e}")
                raise
    
    async def write_batch(self, events: List[AuditEvent]):
        """Write a batch of events to S3"""
        if not events:
            return
            
        try:
            # Group events by hour for efficient storage
            timestamp = datetime.utcnow()
            year = timestamp.year
            month = timestamp.month
            day = timestamp.day
            hour = timestamp.hour
            
            # Create JSON Lines format
            lines = []
            for event in events:
                lines.append(json.dumps(event.to_dict(), default=str))
            
            content = '\n'.join(lines)
            
            # Compress if enabled
            if settings.COMPRESSION_ENABLED:
                if settings.COMPRESSION_CODEC == 'gzip':
                    content = gzip.compress(content.encode('utf-8'))
                    extension = '.jsonl.gz'
                elif settings.COMPRESSION_CODEC == 'zstd':
                    content = zstd.compress(content.encode('utf-8'))
                    extension = '.jsonl.zst'
                else:
                    content = content.encode('utf-8')
                    extension = '.jsonl'
            else:
                content = content.encode('utf-8')
                extension = '.jsonl'
            
            # S3 key with partitioning
            key = f"{settings.S3_PREFIX}/year={year}/month={month:02d}/day={day:02d}/hour={hour:02d}/events-{timestamp.timestamp()}{extension}"
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=settings.S3_BUCKET,
                Key=key,
                Body=content,
                ContentType='application/json' if extension.endswith('.jsonl') else 'application/octet-stream'
            )
            
            logger.info(f"Wrote {len(events)} events to S3: {key}")
            
        except Exception as e:
            logger.error(f"Failed to write to S3: {e}")
            raise


class AuditSink:
    """Main audit sink coordinator"""
    
    def __init__(self):
        self.buffer: deque = deque(maxlen=settings.BUFFER_SIZE * 2)  # Allow some overflow
        self.pii_masker = PIIMasker() if settings.ENABLE_PII_MASKING else None
        
        self.backends = []
        if settings.STORAGE_BACKEND in ['clickhouse', 'both']:
            self.backends.append(ClickHouseBackend())
        if settings.STORAGE_BACKEND in ['s3', 'both']:
            self.backends.append(S3Backend())
        
        self.last_flush_time: Optional[datetime] = None
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Start the audit sink"""
        logger.info("Starting audit sink...")
        
        # Initialize backends
        for backend in self.backends:
            await backend.initialize()
        
        # Start flush task
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        
        logger.info("Audit sink started")
    
    async def stop(self):
        """Stop the audit sink"""
        logger.info("Stopping audit sink...")
        
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush
        await self._flush_buffer()
        
        logger.info("Audit sink stopped")
    
    def is_ready(self) -> bool:
        """Check if sink is ready"""
        return self._running and len(self.backends) > 0
    
    async def write_event(self, event: AuditEvent):
        """Write a single audit event"""
        # Apply PII masking if enabled
        if self.pii_masker:
            event.metadata = self.pii_masker.mask_pii(event.metadata)
        
        # Add to buffer
        self.buffer.append(event)
        
        # Flush if buffer is full
        if len(self.buffer) >= settings.BUFFER_SIZE:
            await self._flush_buffer()
    
    async def write_events(self, events: List[AuditEvent]):
        """Write multiple audit events"""
        for event in events:
            await self.write_event(event)
    
    async def _flush_loop(self):
        """Periodic flush loop"""
        while self._running:
            try:
                await asyncio.sleep(settings.FLUSH_INTERVAL)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
    
    async def _flush_buffer(self):
        """Flush buffered events to storage backends"""
        if not self.buffer:
            return
        
        try:
            # Get events from buffer
            events = []
            while self.buffer and len(events) < settings.BATCH_SIZE:
                events.append(self.buffer.popleft())
            
            if not events:
                return
            
            # Write to all backends concurrently
            tasks = []
            for backend in self.backends:
                tasks.append(backend.write_batch(events))
            
            await asyncio.gather(*tasks, return_exceptions=True)
            
            self.last_flush_time = datetime.utcnow()
            logger.debug(f"Flushed {len(events)} events")
            
        except Exception as e:
            logger.error(f"Failed to flush buffer: {e}")
            # Put events back in buffer for retry
            for event in reversed(events):
                self.buffer.appendleft(event)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get sink statistics"""
        return {
            "buffer_size": len(self.buffer),
            "buffer_max_size": settings.BUFFER_SIZE,
            "backends_count": len(self.backends),
            "storage_backend": settings.STORAGE_BACKEND,
            "last_flush_time": self.last_flush_time.isoformat() if self.last_flush_time else None,
            "running": self._running
        }