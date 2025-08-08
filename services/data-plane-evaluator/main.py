#!/usr/bin/env python3
"""
Data-Plane Split Evaluator Service
Monitors database performance and triggers migrations based on thresholds

Phase 3 Implementation for:
- PgVector → Qdrant/Weaviate migration monitoring
- Audit log migration to ClickHouse/S3 
- Performance threshold evaluation
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
import json
import os

import asyncpg
import psutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/projectflow")
CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "http://localhost:8123")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "http://localhost:8080")

# Thresholds from design plan
VECTOR_ROW_THRESHOLD = int(os.getenv("VECTOR_ROW_THRESHOLD", "50000000"))  # 50M rows
VECTOR_P95_THRESHOLD_MS = int(os.getenv("VECTOR_P95_THRESHOLD_MS", "150"))  # 150ms p95
AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "90"))  # 90-day online
MIN_EVALUATION_INTERVAL = int(os.getenv("MIN_EVALUATION_INTERVAL", "300"))  # 5 minutes


@dataclass
class VectorPerformanceMetrics:
    """Vector database performance metrics"""
    total_rows: int
    search_p95_ms: float
    storage_size_gb: float
    queries_per_second: float
    avg_embedding_dimension: int
    memory_usage_gb: float
    last_updated: datetime


@dataclass  
class AuditLogMetrics:
    """Audit log performance metrics"""
    total_events: int
    storage_size_gb: float
    oldest_event_age_days: int
    ingestion_rate_per_sec: float
    query_p95_ms: float
    retention_violations: int
    last_updated: datetime


@dataclass
class MigrationRecommendation:
    """Migration recommendation with rationale"""
    component: str  # "vector" or "audit"
    action: str  # "migrate", "optimize", "no_action"
    target_system: str  # "qdrant", "weaviate", "clickhouse", "s3"
    priority: str  # "critical", "high", "medium", "low"
    rationale: List[str]
    estimated_downtime_minutes: int
    cost_impact: str
    performance_improvement: str
    created_at: datetime


class DataPlaneEvaluator:
    """Evaluates data-plane performance and migration thresholds"""
    
    def __init__(self):
        self.db_pool = None
        self.last_evaluation = None
        self.current_metrics = {}
        self.migration_history = []
        
    async def start(self):
        """Initialize database connections and start monitoring"""
        logger.info("Starting Data-Plane Evaluator...")
        
        # Initialize PostgreSQL connection pool
        self.db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        
        logger.info("Database connection pool initialized")
        
    async def stop(self):
        """Cleanup connections"""
        if self.db_pool:
            await self.db_pool.close()
        logger.info("Data-Plane Evaluator stopped")
    
    async def evaluate_vector_performance(self) -> VectorPerformanceMetrics:
        """Evaluate vector database performance metrics"""
        try:
            async with self.db_pool.acquire() as conn:
                # Query vector table statistics
                vector_stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_rows,
                        pg_size_pretty(pg_total_relation_size('ai_embeddings'))::text as size_text,
                        pg_total_relation_size('ai_embeddings') as size_bytes
                    FROM ai_embeddings
                """)
                
                # Measure vector search performance
                search_times = []
                for _ in range(5):  # Sample 5 queries
                    start_time = time.time()
                    await conn.fetchrow("""
                        SELECT id, embedding <-> $1::vector as distance 
                        FROM ai_embeddings 
                        ORDER BY embedding <-> $1::vector 
                        LIMIT 10
                    """, [0.0] * 1536)  # Sample embedding
                    search_times.append((time.time() - start_time) * 1000)
                
                # Calculate p95
                search_times.sort()
                p95_index = int(len(search_times) * 0.95)
                search_p95_ms = search_times[p95_index] if search_times else 0
                
                # Get embedding dimension
                embedding_dim_result = await conn.fetchrow("""
                    SELECT array_length(embedding, 1) as dimension
                    FROM ai_embeddings 
                    LIMIT 1
                """)
                
                avg_dimension = embedding_dim_result['dimension'] if embedding_dim_result else 1536
                
                return VectorPerformanceMetrics(
                    total_rows=vector_stats['total_rows'] or 0,
                    search_p95_ms=search_p95_ms,
                    storage_size_gb=vector_stats['size_bytes'] / (1024**3) if vector_stats['size_bytes'] else 0,
                    queries_per_second=1000 / search_p95_ms if search_p95_ms > 0 else 0,
                    avg_embedding_dimension=avg_dimension,
                    memory_usage_gb=psutil.virtual_memory().used / (1024**3),
                    last_updated=datetime.now()
                )
                
        except Exception as e:
            logger.error(f"Failed to evaluate vector performance: {e}")
            # Return default metrics on error
            return VectorPerformanceMetrics(
                total_rows=0,
                search_p95_ms=999.0,
                storage_size_gb=0.0,
                queries_per_second=0.0,
                avg_embedding_dimension=1536,
                memory_usage_gb=0.0,
                last_updated=datetime.now()
            )
    
    async def evaluate_audit_performance(self) -> AuditLogMetrics:
        """Evaluate audit log performance metrics"""
        try:
            async with self.db_pool.acquire() as conn:
                # Query audit log statistics  
                audit_stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_events,
                        pg_size_pretty(pg_total_relation_size('audit_logs'))::text as size_text,
                        pg_total_relation_size('audit_logs') as size_bytes,
                        EXTRACT(DAYS FROM (NOW() - MIN(created_at))) as oldest_age_days
                    FROM audit_logs
                """)
                
                # Calculate ingestion rate (events per second over last hour)
                recent_events = await conn.fetchval("""
                    SELECT COUNT(*) 
                    FROM audit_logs 
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """)
                ingestion_rate = recent_events / 3600  # per second
                
                # Measure audit query performance
                query_times = []
                for _ in range(3):  # Sample 3 queries
                    start_time = time.time()
                    await conn.fetch("""
                        SELECT * FROM audit_logs 
                        WHERE created_at > NOW() - INTERVAL '1 day'
                        ORDER BY created_at DESC
                        LIMIT 100
                    """)
                    query_times.append((time.time() - start_time) * 1000)
                
                # Calculate p95
                query_times.sort()
                p95_index = int(len(query_times) * 0.95)
                query_p95_ms = query_times[p95_index] if query_times else 0
                
                # Check retention policy violations
                retention_violations = await conn.fetchval("""
                    SELECT COUNT(*) 
                    FROM audit_logs 
                    WHERE created_at < NOW() - INTERVAL '%s days'
                """, AUDIT_RETENTION_DAYS)
                
                return AuditLogMetrics(
                    total_events=audit_stats['total_events'] or 0,
                    storage_size_gb=audit_stats['size_bytes'] / (1024**3) if audit_stats['size_bytes'] else 0,
                    oldest_event_age_days=int(audit_stats['oldest_age_days'] or 0),
                    ingestion_rate_per_sec=ingestion_rate,
                    query_p95_ms=query_p95_ms,
                    retention_violations=retention_violations or 0,
                    last_updated=datetime.now()
                )
                
        except Exception as e:
            logger.error(f"Failed to evaluate audit performance: {e}")
            return AuditLogMetrics(
                total_events=0,
                storage_size_gb=0.0,
                oldest_event_age_days=0,
                ingestion_rate_per_sec=0.0,
                query_p95_ms=999.0,
                retention_violations=0,
                last_updated=datetime.now()
            )
    
    async def generate_vector_recommendations(self, metrics: VectorPerformanceMetrics) -> Optional[MigrationRecommendation]:
        """Generate recommendations for vector database migration"""
        rationale = []
        priority = "low"
        action = "no_action"
        target_system = "pgvector"
        
        # Check row count threshold
        if metrics.total_rows > VECTOR_ROW_THRESHOLD:
            rationale.append(f"Vector row count ({metrics.total_rows:,}) exceeds threshold ({VECTOR_ROW_THRESHOLD:,})")
            priority = "high"
            action = "migrate"
        
        # Check performance threshold
        if metrics.search_p95_ms > VECTOR_P95_THRESHOLD_MS:
            rationale.append(f"Vector search p95 ({metrics.search_p95_ms:.1f}ms) exceeds threshold ({VECTOR_P95_THRESHOLD_MS}ms)")
            if priority == "low":
                priority = "medium"
                action = "optimize"
        
        # Check storage size (>100GB should consider migration)
        if metrics.storage_size_gb > 100:
            rationale.append(f"Vector storage size ({metrics.storage_size_gb:.1f}GB) is significant")
            if action == "no_action":
                action = "optimize"
        
        # Determine target system based on use case
        if action == "migrate":
            if metrics.queries_per_second > 1000:
                target_system = "qdrant"  # High-performance vector search
                rationale.append("High QPS workload suits Qdrant")
            else:
                target_system = "weaviate"  # More feature-rich for complex queries
                rationale.append("Complex query patterns suit Weaviate")
        
        if action == "no_action":
            return None
            
        return MigrationRecommendation(
            component="vector",
            action=action,
            target_system=target_system,
            priority=priority,
            rationale=rationale,
            estimated_downtime_minutes=30 if action == "migrate" else 5,
            cost_impact="medium" if action == "migrate" else "low",
            performance_improvement="50-80% search improvement" if action == "migrate" else "10-20% improvement",
            created_at=datetime.now()
        )
    
    async def generate_audit_recommendations(self, metrics: AuditLogMetrics) -> Optional[MigrationRecommendation]:
        """Generate recommendations for audit log migration"""
        rationale = []
        priority = "low"
        action = "no_action"
        target_system = "postgresql"
        
        # Check retention violations
        if metrics.retention_violations > 0:
            rationale.append(f"Audit retention violations: {metrics.retention_violations} old records")
            priority = "high"
            action = "migrate"
            target_system = "s3"
        
        # Check storage size (>50GB should consider archival)
        if metrics.storage_size_gb > 50:
            rationale.append(f"Audit storage size ({metrics.storage_size_gb:.1f}GB) requires archival")
            if priority == "low":
                priority = "medium"
                action = "migrate"
                target_system = "clickhouse"
        
        # Check query performance
        if metrics.query_p95_ms > 500:  # 500ms threshold for audit queries
            rationale.append(f"Audit query p95 ({metrics.query_p95_ms:.1f}ms) is slow")
            if action == "no_action":
                action = "optimize"
                target_system = "clickhouse"
        
        # High ingestion rate should use specialized system
        if metrics.ingestion_rate_per_sec > 100:
            rationale.append(f"High audit ingestion rate ({metrics.ingestion_rate_per_sec:.1f}/sec)")
            priority = "high"
            action = "migrate"
            target_system = "clickhouse"
        
        if action == "no_action":
            return None
            
        return MigrationRecommendation(
            component="audit",
            action=action,
            target_system=target_system,
            priority=priority,
            rationale=rationale,
            estimated_downtime_minutes=60 if target_system == "clickhouse" else 15,
            cost_impact="low" if target_system == "s3" else "medium",
            performance_improvement="90% query improvement" if target_system == "clickhouse" else "archival benefits",
            created_at=datetime.now()
        )
    
    async def perform_full_evaluation(self) -> Dict[str, Any]:
        """Perform complete data-plane evaluation"""
        logger.info("Starting full data-plane evaluation...")
        
        # Collect metrics
        vector_metrics = await self.evaluate_vector_performance()
        audit_metrics = await self.evaluate_audit_performance()
        
        # Generate recommendations
        vector_recommendation = await self.generate_vector_recommendations(vector_metrics)
        audit_recommendation = await self.generate_audit_recommendations(audit_metrics)
        
        # Store current metrics
        self.current_metrics = {
            'vector': asdict(vector_metrics),
            'audit': asdict(audit_metrics),
            'evaluation_time': datetime.now().isoformat()
        }
        
        # Store recommendations
        recommendations = []
        if vector_recommendation:
            recommendations.append(asdict(vector_recommendation))
        if audit_recommendation:
            recommendations.append(asdict(audit_recommendation))
        
        self.last_evaluation = datetime.now()
        
        evaluation_result = {
            'status': 'completed',
            'evaluation_time': self.last_evaluation.isoformat(),
            'metrics': self.current_metrics,
            'recommendations': recommendations,
            'thresholds': {
                'vector_row_threshold': VECTOR_ROW_THRESHOLD,
                'vector_p95_threshold_ms': VECTOR_P95_THRESHOLD_MS,
                'audit_retention_days': AUDIT_RETENTION_DAYS
            }
        }
        
        # Log critical recommendations
        for rec in recommendations:
            if rec['priority'] in ['critical', 'high']:
                logger.warning(f"HIGH PRIORITY: {rec['component']} {rec['action']} to {rec['target_system']}: {'; '.join(rec['rationale'])}")
        
        logger.info("Data-plane evaluation completed")
        return evaluation_result
    
    async def check_external_services(self) -> Dict[str, bool]:
        """Check availability of external data services"""
        services = {}
        
        # Check Qdrant
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{QDRANT_URL}/collections")
                services['qdrant'] = response.status_code == 200
        except:
            services['qdrant'] = False
        
        # Check Weaviate
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{WEAVIATE_URL}/v1/meta")
                services['weaviate'] = response.status_code == 200
        except:
            services['weaviate'] = False
        
        # Check ClickHouse
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{CLICKHOUSE_URL}/ping")
                services['clickhouse'] = response.status_code == 200
        except:
            services['clickhouse'] = False
        
        return services


# FastAPI application
app = FastAPI(
    title="Data-Plane Split Evaluator",
    description="Monitors database performance and evaluates migration thresholds",
    version="1.0.0"
)

evaluator = DataPlaneEvaluator()

@app.on_event("startup")
async def startup():
    await evaluator.start()

@app.on_event("shutdown") 
async def shutdown():
    await evaluator.stop()

# API Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "data-plane-evaluator",
        "last_evaluation": evaluator.last_evaluation.isoformat() if evaluator.last_evaluation else None
    }

@app.get("/evaluate")
async def trigger_evaluation():
    """Trigger a full data-plane evaluation"""
    try:
        # Check minimum interval
        if evaluator.last_evaluation:
            seconds_since_last = (datetime.now() - evaluator.last_evaluation).total_seconds()
            if seconds_since_last < MIN_EVALUATION_INTERVAL:
                raise HTTPException(
                    status_code=429, 
                    detail=f"Evaluation too frequent. Wait {MIN_EVALUATION_INTERVAL - seconds_since_last:.0f}s"
                )
        
        result = await evaluator.perform_full_evaluation()
        return result
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metrics/vector")
async def get_vector_metrics():
    """Get current vector database metrics"""
    metrics = await evaluator.evaluate_vector_performance()
    return asdict(metrics)

@app.get("/metrics/audit")
async def get_audit_metrics():
    """Get current audit log metrics"""
    metrics = await evaluator.evaluate_audit_performance()
    return asdict(metrics)

@app.get("/services/status")
async def get_service_status():
    """Check status of external data services"""
    services = await evaluator.check_external_services()
    return {
        "external_services": services,
        "migration_ready": {
            "vector_to_qdrant": services.get('qdrant', False),
            "vector_to_weaviate": services.get('weaviate', False), 
            "audit_to_clickhouse": services.get('clickhouse', False),
            "audit_to_s3": True  # S3 always available via boto3
        }
    }

@app.get("/recommendations")
async def get_current_recommendations():
    """Get current migration recommendations"""
    if not evaluator.current_metrics:
        raise HTTPException(status_code=404, detail="No evaluation data available. Run /evaluate first")
    
    # Regenerate recommendations from current metrics
    vector_metrics = VectorPerformanceMetrics(**evaluator.current_metrics['vector'])
    audit_metrics = AuditLogMetrics(**evaluator.current_metrics['audit'])
    
    recommendations = []
    
    vector_rec = await evaluator.generate_vector_recommendations(vector_metrics)
    if vector_rec:
        recommendations.append(asdict(vector_rec))
    
    audit_rec = await evaluator.generate_audit_recommendations(audit_metrics)
    if audit_rec:
        recommendations.append(asdict(audit_rec))
    
    return {
        "recommendations": recommendations,
        "based_on_evaluation": evaluator.current_metrics['evaluation_time']
    }

@app.get("/thresholds")
async def get_thresholds():
    """Get current migration thresholds"""
    return {
        "vector": {
            "max_rows": VECTOR_ROW_THRESHOLD,
            "max_p95_search_ms": VECTOR_P95_THRESHOLD_MS,
            "max_storage_gb": 100
        },
        "audit": {
            "retention_days": AUDIT_RETENTION_DAYS,
            "max_storage_gb": 50,
            "max_query_p95_ms": 500,
            "max_ingestion_rate_per_sec": 100
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)