#!/usr/bin/env python3
"""
Audit Sink Service - Phase 3 Implementation
Handles append-only audit log migration to ClickHouse/S3
Implements change-data-capture (CDC) from PostgreSQL
"""

import asyncio
import logging
import json
import gzip
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import os

import asyncpg
import boto3
from botocore.exceptions import ClientError
import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Configuration
SOURCE_DATABASE_URL = os.getenv("SOURCE_DATABASE_URL", "postgresql://user:pass@localhost:5432/projectflow")
CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://localhost:8123")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "audit")
S3_BUCKET = os.getenv("S3_BUCKET", "audit-logs-archive")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))
SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "60"))


class SinkType(Enum):
    CLICKHOUSE = "clickhouse"
    S3 = "s3"
    BOTH = "both"


@dataclass
class AuditEvent:
    """Audit event structure"""
    id: int
    user_id: Optional[str]
    action: str
    resource_type: str
    resource_id: Optional[str]
    metadata: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: datetime
    
    def to_clickhouse_dict(self) -> Dict[str, Any]:
        """Convert to ClickHouse-compatible format"""
        return {
            'id': self.id,
            'user_id': self.user_id or '',
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id or '',
            'metadata': json.dumps(self.metadata),
            'ip_address': self.ip_address or '',
            'user_agent': self.user_agent or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def to_s3_dict(self) -> Dict[str, Any]:
        """Convert to S3-compatible JSON format"""
        result = asdict(self)
        result['created_at'] = self.created_at.isoformat()
        return result


class ClickHouseSink:
    """ClickHouse audit sink implementation"""
    
    def __init__(self, url: str, database: str):
        self.url = url
        self.database = database
        self._initialized = False
    
    async def initialize(self):
        """Initialize ClickHouse database and table"""
        if self._initialized:
            return
            
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Create database
                await client.post(
                    f"{self.url}",
                    data=f"CREATE DATABASE IF NOT EXISTS {self.database}"
                )
                
                # Create audit_events table with MergeTree engine
                create_table_sql = f"""
                CREATE TABLE IF NOT EXISTS {self.database}.audit_events (
                    id UInt64,
                    user_id String,
                    action String,
                    resource_type String,
                    resource_id String,
                    metadata String,
                    ip_address String,
                    user_agent String,
                    created_at DateTime,
                    partition_date Date DEFAULT toDate(created_at)
                ) ENGINE = MergeTree()
                PARTITION BY partition_date
                ORDER BY (created_at, id)
                TTL created_at + INTERVAL 2 YEAR DELETE
                SETTINGS index_granularity = 8192
                """
                
                await client.post(f"{self.url}", data=create_table_sql)
                
                # Create materialized views for common queries
                await self._create_materialized_views(client)
                
                self._initialized = True
                logger.info("ClickHouse sink initialized successfully")
                
        except Exception as e:
            logger.error("Failed to initialize ClickHouse sink", error=str(e))
            raise
    
    async def _create_materialized_views(self, client):
        """Create materialized views for analytics"""
        # User activity summary
        user_activity_mv = f"""
        CREATE MATERIALIZED VIEW IF NOT EXISTS {self.database}.user_activity_daily
        ENGINE = SummingMergeTree()
        PARTITION BY toYYYYMM(event_date)
        ORDER BY (event_date, user_id, action)
        AS SELECT
            toDate(created_at) as event_date,
            user_id,
            action,
            count() as event_count
        FROM {self.database}.audit_events
        GROUP BY event_date, user_id, action
        """
        await client.post(f"{self.url}", data=user_activity_mv)
        
        # Resource access patterns
        resource_access_mv = f"""
        CREATE MATERIALIZED VIEW IF NOT EXISTS {self.database}.resource_access_daily  
        ENGINE = SummingMergeTree()
        PARTITION BY toYYYYMM(event_date)
        ORDER BY (event_date, resource_type, action)
        AS SELECT
            toDate(created_at) as event_date,
            resource_type,
            action,
            count() as access_count
        FROM {self.database}.audit_events
        GROUP BY event_date, resource_type, action
        """
        await client.post(f"{self.url}", data=resource_access_mv)
    
    async def insert_events(self, events: List[AuditEvent]) -> bool:
        """Insert batch of events into ClickHouse"""
        if not events:
            return True
            
        try:
            # Convert events to ClickHouse format
            rows = [event.to_clickhouse_dict() for event in events]
            
            # Prepare INSERT query
            columns = list(rows[0].keys())
            values_placeholder = ", ".join([f"'{row[col]}'" for col in columns for row in rows])
            
            insert_sql = f"""
            INSERT INTO {self.database}.audit_events ({', '.join(columns)}) 
            VALUES {', '.join([f"({', '.join([repr(row[col]) for col in columns])})" for row in rows])}
            """
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.url}", data=insert_sql)
                response.raise_for_status()
                
            logger.info("Inserted events to ClickHouse", count=len(events))
            return True
            
        except Exception as e:
            logger.error("Failed to insert events to ClickHouse", error=str(e), count=len(events))
            return False
    
    async def health_check(self) -> bool:
        """Check ClickHouse connectivity"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.url}/ping")
                return response.status_code == 200
        except:
            return False


class S3Sink:
    """S3 audit sink implementation with Parquet format"""
    
    def __init__(self, bucket: str, region: str):
        self.bucket = bucket
        self.region = region
        self.s3_client = boto3.client('s3', region_name=region)
    
    async def initialize(self):
        """Initialize S3 bucket and lifecycle policies"""
        try:
            # Create bucket if it doesn't exist
            try:
                self.s3_client.head_bucket(Bucket=self.bucket)
            except ClientError as e:
                if e.response['Error']['Code'] == '404':
                    if self.region == 'us-east-1':
                        self.s3_client.create_bucket(Bucket=self.bucket)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket,
                            CreateBucketConfiguration={'LocationConstraint': self.region}
                        )
                else:
                    raise
            
            # Set lifecycle policy for cost optimization
            lifecycle_policy = {
                'Rules': [
                    {
                        'ID': 'audit-log-lifecycle',
                        'Status': 'Enabled',
                        'Filter': {'Prefix': 'audit-events/'},
                        'Transitions': [
                            {
                                'Days': 30,
                                'StorageClass': 'STANDARD_IA'
                            },
                            {
                                'Days': 90,
                                'StorageClass': 'GLACIER'
                            },
                            {
                                'Days': 365,
                                'StorageClass': 'DEEP_ARCHIVE'
                            }
                        ]
                    }
                ]
            }
            
            self.s3_client.put_bucket_lifecycle_configuration(
                Bucket=self.bucket,
                LifecycleConfiguration=lifecycle_policy
            )
            
            logger.info("S3 sink initialized successfully", bucket=self.bucket)
            
        except Exception as e:
            logger.error("Failed to initialize S3 sink", error=str(e))
            raise
    
    async def upload_events(self, events: List[AuditEvent]) -> bool:
        """Upload batch of events to S3 as compressed JSON"""
        if not events:
            return True
            
        try:
            # Group events by date for partitioning
            events_by_date = {}
            for event in events:
                date_key = event.created_at.strftime('%Y-%m-%d')
                if date_key not in events_by_date:
                    events_by_date[date_key] = []
                events_by_date[date_key].append(event.to_s3_dict())
            
            # Upload each date partition
            for date_key, date_events in events_by_date.items():
                timestamp = datetime.now().strftime('%H-%M-%S')
                s3_key = f"audit-events/year={date_key[:4]}/month={date_key[5:7]}/day={date_key[8:10]}/events-{timestamp}.json.gz"
                
                # Compress JSON data
                json_data = json.dumps(date_events, default=str, separators=(',', ':'))
                compressed_data = gzip.compress(json_data.encode('utf-8'))
                
                # Upload to S3
                self.s3_client.put_object(
                    Bucket=self.bucket,
                    Key=s3_key,
                    Body=compressed_data,
                    ContentType='application/json',
                    ContentEncoding='gzip',
                    Metadata={
                        'event-count': str(len(date_events)),
                        'date': date_key,
                        'compressed': 'true'
                    }
                )
            
            logger.info("Uploaded events to S3", count=len(events), partitions=len(events_by_date))
            return True
            
        except Exception as e:
            logger.error("Failed to upload events to S3", error=str(e), count=len(events))
            return False
    
    async def health_check(self) -> bool:
        """Check S3 connectivity"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            return True
        except:
            return False


class AuditSinkService:
    """Main audit sink service with CDC capabilities"""
    
    def __init__(self, sink_type: SinkType = SinkType.BOTH):
        self.sink_type = sink_type
        self.db_pool = None
        self.clickhouse_sink = ClickHouseSink(CLICKHOUSE_URL, CLICKHOUSE_DATABASE)
        self.s3_sink = S3Sink(S3_BUCKET, AWS_REGION)
        
        self.last_processed_id = 0
        self.sync_task = None
        self.running = False
        
        # Metrics
        self.total_processed = 0
        self.last_sync_time = None
        self.error_count = 0
    
    async def start(self):
        """Start the audit sink service"""
        logger.info("Starting Audit Sink Service", sink_type=self.sink_type.value)
        
        # Initialize database connection
        self.db_pool = await asyncpg.create_pool(
            SOURCE_DATABASE_URL,
            min_size=2,
            max_size=5,
            command_timeout=60
        )
        
        # Initialize sinks
        if self.sink_type in [SinkType.CLICKHOUSE, SinkType.BOTH]:
            await self.clickhouse_sink.initialize()
        
        if self.sink_type in [SinkType.S3, SinkType.BOTH]:
            await self.s3_sink.initialize()
        
        # Load last processed ID from metadata
        await self._load_checkpoint()
        
        # Start sync task
        self.running = True
        self.sync_task = asyncio.create_task(self._sync_loop())
        
        logger.info("Audit Sink Service started", last_processed_id=self.last_processed_id)
    
    async def stop(self):
        """Stop the audit sink service"""
        self.running = False
        
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass
        
        if self.db_pool:
            await self.db_pool.close()
        
        logger.info("Audit Sink Service stopped")
    
    async def _load_checkpoint(self):
        """Load last processed ID from checkpoint table"""
        try:
            async with self.db_pool.acquire() as conn:
                # Create checkpoint table if it doesn't exist
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_sync_checkpoint (
                        id SERIAL PRIMARY KEY,
                        last_processed_id BIGINT NOT NULL,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                
                # Load checkpoint
                result = await conn.fetchrow("""
                    SELECT last_processed_id FROM audit_sync_checkpoint ORDER BY id DESC LIMIT 1
                """)
                
                if result:
                    self.last_processed_id = result['last_processed_id']
                else:
                    # Initialize with the latest audit log ID
                    latest_id = await conn.fetchval("""
                        SELECT COALESCE(MAX(id), 0) FROM audit_logs
                    """)
                    self.last_processed_id = latest_id
                    
                    # Insert initial checkpoint
                    await conn.execute("""
                        INSERT INTO audit_sync_checkpoint (last_processed_id) VALUES ($1)
                    """, self.last_processed_id)
                
        except Exception as e:
            logger.error("Failed to load checkpoint", error=str(e))
            self.last_processed_id = 0
    
    async def _save_checkpoint(self, processed_id: int):
        """Save checkpoint after successful processing"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute("""
                    UPDATE audit_sync_checkpoint 
                    SET last_processed_id = $1, updated_at = NOW()
                    WHERE id = (SELECT MAX(id) FROM audit_sync_checkpoint)
                """, processed_id)
                
                self.last_processed_id = processed_id
                
        except Exception as e:
            logger.error("Failed to save checkpoint", error=str(e))
    
    async def _fetch_new_events(self, limit: int = BATCH_SIZE) -> List[AuditEvent]:
        """Fetch new audit events from PostgreSQL"""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT id, user_id, action, resource_type, resource_id, 
                           metadata, ip_address, user_agent, created_at
                    FROM audit_logs 
                    WHERE id > $1 
                    ORDER BY id ASC 
                    LIMIT $2
                """, self.last_processed_id, limit)
                
                events = []
                for row in rows:
                    events.append(AuditEvent(
                        id=row['id'],
                        user_id=row['user_id'],
                        action=row['action'],
                        resource_type=row['resource_type'],
                        resource_id=row['resource_id'],
                        metadata=row['metadata'] or {},
                        ip_address=row['ip_address'],
                        user_agent=row['user_agent'],
                        created_at=row['created_at']
                    ))
                
                return events
                
        except Exception as e:
            logger.error("Failed to fetch new events", error=str(e))
            return []
    
    async def _process_events(self, events: List[AuditEvent]) -> bool:
        """Process events to configured sinks"""
        if not events:
            return True
        
        success = True
        
        # Send to ClickHouse
        if self.sink_type in [SinkType.CLICKHOUSE, SinkType.BOTH]:
            clickhouse_success = await self.clickhouse_sink.insert_events(events)
            success = success and clickhouse_success
        
        # Send to S3
        if self.sink_type in [SinkType.S3, SinkType.BOTH]:
            s3_success = await self.s3_sink.upload_events(events)
            success = success and s3_success
        
        return success
    
    async def _sync_loop(self):
        """Main synchronization loop"""
        while self.running:
            try:
                start_time = datetime.now()
                
                # Fetch new events
                events = await self._fetch_new_events()
                
                if events:
                    logger.info("Processing audit events", count=len(events))
                    
                    # Process events
                    success = await self._process_events(events)
                    
                    if success:
                        # Update checkpoint
                        await self._save_checkpoint(events[-1].id)
                        
                        self.total_processed += len(events)
                        self.last_sync_time = start_time
                        
                        logger.info("Successfully processed events", 
                                  count=len(events), 
                                  total_processed=self.total_processed)
                    else:
                        self.error_count += 1
                        logger.error("Failed to process some events", count=len(events))
                
                # Wait for next sync interval
                await asyncio.sleep(SYNC_INTERVAL_SECONDS)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.error_count += 1
                logger.error("Sync loop error", error=str(e))
                await asyncio.sleep(SYNC_INTERVAL_SECONDS)
    
    async def manual_sync(self) -> Dict[str, Any]:
        """Trigger manual synchronization"""
        try:
            events = await self._fetch_new_events()
            
            if not events:
                return {
                    "status": "no_new_events",
                    "message": "No new audit events to process"
                }
            
            success = await self._process_events(events)
            
            if success:
                await self._save_checkpoint(events[-1].id)
                self.total_processed += len(events)
                
                return {
                    "status": "success",
                    "events_processed": len(events),
                    "total_processed": self.total_processed,
                    "last_processed_id": self.last_processed_id
                }
            else:
                return {
                    "status": "partial_failure", 
                    "events_processed": len(events),
                    "message": "Some sinks failed"
                }
                
        except Exception as e:
            logger.error("Manual sync failed", error=str(e))
            return {
                "status": "error",
                "message": str(e)
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        return {
            "sink_type": self.sink_type.value,
            "running": self.running,
            "last_processed_id": self.last_processed_id,
            "total_processed": self.total_processed,
            "last_sync_time": self.last_sync_time.isoformat() if self.last_sync_time else None,
            "error_count": self.error_count,
            "sync_interval_seconds": SYNC_INTERVAL_SECONDS
        }


# FastAPI application
app = FastAPI(
    title="Audit Sink Service",
    description="Append-only audit log migration to ClickHouse/S3",
    version="1.0.0"
)

# Determine sink type from environment
sink_type_str = os.getenv("SINK_TYPE", "both").lower()
try:
    sink_type = SinkType(sink_type_str)
except ValueError:
    sink_type = SinkType.BOTH

service = AuditSinkService(sink_type)

@app.on_event("startup")
async def startup():
    await service.start()

@app.on_event("shutdown")
async def shutdown():
    await service.stop()

# API Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "audit-sink-service",
        "sink_type": service.sink_type.value,
        "running": service.running
    }

@app.post("/sync")
async def trigger_manual_sync():
    """Trigger manual synchronization"""
    result = await service.manual_sync()
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["message"])
    return result

@app.get("/stats")
async def get_stats():
    """Get service statistics"""
    return service.get_stats()

@app.get("/sinks/health")
async def check_sink_health():
    """Check health of all configured sinks"""
    health_status = {}
    
    if service.sink_type in [SinkType.CLICKHOUSE, SinkType.BOTH]:
        health_status["clickhouse"] = await service.clickhouse_sink.health_check()
    
    if service.sink_type in [SinkType.S3, SinkType.BOTH]:
        health_status["s3"] = await service.s3_sink.health_check()
    
    return {
        "sink_health": health_status,
        "overall_healthy": all(health_status.values())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)