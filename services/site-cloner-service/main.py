#!/usr/bin/env python3
"""
Site Cloner Service - Phase 3 Implementation
Advanced web site cloning with cost controls, rate limiting, and automation integration
"""

import asyncio
import logging
import json
import os
import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, asdict
from enum import Enum
from urllib.parse import urljoin, urlparse
import tempfile
import zipfile
from pathlib import Path
import re

import aiohttp
import aiofiles
from bs4 import BeautifulSoup
import redis
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel, HttpUrl
import structlog

# Import our browser pool client
import sys
sys.path.append('../browser-pool-service')
from app.node_client import BrowserPoolNodeClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()

# Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BROWSER_POOL_HOST = os.getenv("BROWSER_POOL_HOST", "browser-pool-service-node")
BROWSER_POOL_GRPC_PORT = int(os.getenv("BROWSER_POOL_GRPC_PORT", "50051"))
BROWSER_POOL_WS_PORT = int(os.getenv("BROWSER_POOL_WS_PORT", "8080"))

# Storage configuration
STORAGE_PATH = os.getenv("STORAGE_PATH", "/tmp/cloned-sites")
MAX_STORAGE_GB = float(os.getenv("MAX_STORAGE_GB", "10"))

# Cost control configuration
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))
MAX_PAGES_PER_JOB = int(os.getenv("MAX_PAGES_PER_JOB", "1000"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
MAX_TOTAL_SIZE_MB = int(os.getenv("MAX_TOTAL_SIZE_MB", "1000"))
RATE_LIMIT_REQUESTS_PER_MINUTE = int(os.getenv("RATE_LIMIT_RPM", "30"))


class CloneStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed" 
    FAILED = "failed"
    CANCELLED = "cancelled"
    RATE_LIMITED = "rate_limited"
    COST_EXCEEDED = "cost_exceeded"


class ResourceType(Enum):
    HTML = "html"
    CSS = "css"
    JAVASCRIPT = "js"
    IMAGE = "image"
    FONT = "font"
    OTHER = "other"


@dataclass
class CloneJob:
    """Site clone job configuration and status"""
    id: str
    url: str
    depth: int
    include_external: bool
    include_media: bool
    custom_headers: Dict[str, str]
    user_agent: str
    delay_ms: int
    status: CloneStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # Progress tracking
    pages_discovered: int = 0
    pages_cloned: int = 0
    resources_discovered: int = 0
    resources_cloned: int = 0
    total_size_bytes: int = 0
    
    # Cost tracking
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['status'] = self.status.value
        result['created_at'] = self.created_at.isoformat()
        if self.started_at:
            result['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            result['completed_at'] = self.completed_at.isoformat()
        return result


@dataclass
class ResourceInfo:
    """Information about a discovered resource"""
    url: str
    resource_type: ResourceType
    size_bytes: int
    content_type: str
    discovered_from: str
    

class CostCalculator:
    """Calculates and enforces cost limits for cloning operations"""
    
    def __init__(self):
        # Cost per operation (simplified pricing model)
        self.cost_per_page = 0.001  # $0.001 per page
        self.cost_per_mb = 0.01     # $0.01 per MB downloaded
        self.cost_per_minute = 0.05  # $0.05 per minute of processing
        
    def estimate_job_cost(self, pages: int, estimated_size_mb: float, estimated_time_minutes: float) -> float:
        """Estimate total cost for a cloning job"""
        page_cost = pages * self.cost_per_page
        data_cost = estimated_size_mb * self.cost_per_mb
        time_cost = estimated_time_minutes * self.cost_per_minute
        
        return page_cost + data_cost + time_cost
    
    def calculate_actual_cost(self, pages_cloned: int, bytes_downloaded: int, duration_seconds: float) -> float:
        """Calculate actual cost after job completion"""
        page_cost = pages_cloned * self.cost_per_page
        data_cost = (bytes_downloaded / 1024 / 1024) * self.cost_per_mb
        time_cost = (duration_seconds / 60) * self.cost_per_minute
        
        return page_cost + data_cost + time_cost
    
    def is_cost_exceeded(self, estimated_cost: float, max_budget: float = 10.0) -> bool:
        """Check if estimated cost exceeds budget"""
        return estimated_cost > max_budget


class RateLimiter:
    """Redis-based rate limiter for cost control"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def is_rate_limited(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        """Check if key is rate limited"""
        try:
            current = await self.redis.get(key)
            if current is None:
                await self.redis.setex(key, window_seconds, 1)
                return False
            
            current_count = int(current)
            if current_count >= limit:
                return True
            
            await self.redis.incr(key)
            return False
            
        except Exception as e:
            logger.error("Rate limiter error", error=str(e))
            return False
    
    async def get_rate_limit_info(self, key: str) -> Dict[str, Any]:
        """Get rate limit information"""
        try:
            current = await self.redis.get(key)
            ttl = await self.redis.ttl(key)
            
            return {
                "current": int(current) if current else 0,
                "limit": RATE_LIMIT_REQUESTS_PER_MINUTE,
                "reset_in_seconds": ttl if ttl > 0 else 0
            }
        except Exception as e:
            logger.error("Rate limit info error", error=str(e))
            return {"current": 0, "limit": RATE_LIMIT_REQUESTS_PER_MINUTE, "reset_in_seconds": 0}


class SiteCloner:
    """Main site cloning engine with browser automation"""
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.browser_client = None
        self.rate_limiter = RateLimiter(redis_client)
        self.cost_calculator = CostCalculator()
        
        # Create storage directory
        Path(STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    
    async def initialize(self):
        """Initialize browser pool connection"""
        self.browser_client = BrowserPoolNodeClient(
            grpc_host=BROWSER_POOL_HOST,
            grpc_port=BROWSER_POOL_GRPC_PORT,
            ws_host=BROWSER_POOL_HOST,
            ws_port=BROWSER_POOL_WS_PORT
        )
        
        try:
            await self.browser_client.connect()
            logger.info("Browser pool client connected")
        except Exception as e:
            logger.error("Failed to connect to browser pool", error=str(e))
            raise
    
    async def shutdown(self):
        """Cleanup connections"""
        if self.browser_client:
            await self.browser_client.disconnect()
    
    async def clone_site(self, job: CloneJob) -> CloneJob:
        """Clone a website according to job specifications"""
        logger.info("Starting site clone job", job_id=job.id, url=job.url)
        
        try:
            job.status = CloneStatus.RUNNING
            job.started_at = datetime.now()
            await self._save_job_status(job)
            
            # Check rate limits
            rate_limit_key = f"clone_requests:{urlparse(job.url).netloc}"
            if await self.rate_limiter.is_rate_limited(rate_limit_key, RATE_LIMIT_REQUESTS_PER_MINUTE):
                job.status = CloneStatus.RATE_LIMITED
                job.error_message = "Rate limit exceeded for this domain"
                await self._save_job_status(job)
                return job
            
            # Create browser session
            session_id = await self.browser_client.create_session(
                user_id=f"clone_job_{job.id}",
                metadata={"job_id": job.id, "url": job.url}
            )
            
            try:
                # Create output directory
                output_dir = Path(STORAGE_PATH) / job.id
                output_dir.mkdir(exist_ok=True)
                
                # Crawl and download site
                await self._crawl_site(job, session_id, output_dir)
                
                # Create archive if successful
                if job.status != CloneStatus.FAILED and job.status != CloneStatus.CANCELLED:
                    await self._create_archive(job, output_dir)
                    job.status = CloneStatus.COMPLETED
                
            finally:
                # Clean up browser session
                await self.browser_client.close_session(session_id)
            
            job.completed_at = datetime.now()
            
            # Calculate final cost
            if job.started_at and job.completed_at:
                duration = (job.completed_at - job.started_at).total_seconds()
                job.actual_cost = self.cost_calculator.calculate_actual_cost(
                    job.pages_cloned, job.total_size_bytes, duration
                )
            
            await self._save_job_status(job)
            logger.info("Site clone job completed", job_id=job.id, status=job.status.value)
            
        except Exception as e:
            job.status = CloneStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.now()
            await self._save_job_status(job)
            logger.error("Site clone job failed", job_id=job.id, error=str(e))
        
        return job
    
    async def _crawl_site(self, job: CloneJob, session_id: str, output_dir: Path):
        """Crawl website and download resources"""
        visited_urls: Set[str] = set()
        url_queue: List[tuple] = [(job.url, 0)]  # (url, depth)
        
        # Create page and navigate to initial URL
        page_id = await self.browser_client.create_page(session_id, job.url)
        
        while url_queue and len(visited_urls) < MAX_PAGES_PER_JOB:
            # Check for cancellation or cost limits
            if job.status in [CloneStatus.CANCELLED, CloneStatus.COST_EXCEEDED]:
                break
            
            current_url, depth = url_queue.pop(0)
            
            if current_url in visited_urls or depth > job.depth:
                continue
            
            # Rate limiting delay
            if job.delay_ms > 0:
                await asyncio.sleep(job.delay_ms / 1000)
            
            try:
                logger.info("Crawling page", url=current_url, depth=depth)
                
                # Navigate to page
                navigate_result = await self.browser_client.navigate_page(session_id, page_id, current_url)
                
                if not navigate_result['success']:
                    logger.warning("Failed to navigate to page", url=current_url, error=navigate_result.get('error'))
                    continue
                
                visited_urls.add(current_url)
                job.pages_discovered += 1
                
                # Get page content
                html_content = await self.browser_client.get_page_content(session_id, page_id, 'html')
                
                if html_content:
                    # Save HTML file
                    await self._save_html_file(current_url, html_content, output_dir)
                    job.pages_cloned += 1
                    job.total_size_bytes += len(html_content.encode('utf-8'))
                    
                    # Parse and download resources
                    if job.include_media:
                        await self._download_page_resources(html_content, current_url, output_dir, job)
                    
                    # Find new links if we haven't reached max depth
                    if depth < job.depth:
                        new_urls = self._extract_links(html_content, current_url, job.include_external)
                        for new_url in new_urls:
                            if new_url not in visited_urls:
                                url_queue.append((new_url, depth + 1))
                
                # Check cost limits
                estimated_final_cost = self.cost_calculator.estimate_job_cost(
                    len(url_queue) + job.pages_cloned,
                    job.total_size_bytes / 1024 / 1024,
                    5  # Assume 5 more minutes
                )
                
                if self.cost_calculator.is_cost_exceeded(estimated_final_cost):
                    job.status = CloneStatus.COST_EXCEEDED
                    job.error_message = f"Estimated cost ${estimated_final_cost:.2f} exceeds budget"
                    break
                
                # Check storage limits
                if job.total_size_bytes > MAX_TOTAL_SIZE_MB * 1024 * 1024:
                    job.status = CloneStatus.COST_EXCEEDED
                    job.error_message = f"Total size exceeds {MAX_TOTAL_SIZE_MB}MB limit"
                    break
                
                # Update job progress
                await self._save_job_status(job)
                
            except Exception as e:
                logger.error("Error crawling page", url=current_url, error=str(e))
                continue
    
    def _extract_links(self, html_content: str, base_url: str, include_external: bool) -> List[str]:
        """Extract links from HTML content"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = []
        base_domain = urlparse(base_url).netloc
        
        for tag in soup.find_all(['a', 'link']):
            href = tag.get('href')
            if not href:
                continue
            
            # Resolve relative URLs
            absolute_url = urljoin(base_url, href)
            parsed_url = urlparse(absolute_url)
            
            # Skip non-HTTP URLs
            if parsed_url.scheme not in ['http', 'https']:
                continue
            
            # Check if external links should be included
            if not include_external and parsed_url.netloc != base_domain:
                continue
            
            # Skip common non-page resources
            if any(absolute_url.lower().endswith(ext) for ext in ['.pdf', '.zip', '.exe', '.dmg']):
                continue
            
            links.append(absolute_url)
        
        return list(set(links))  # Remove duplicates
    
    async def _download_page_resources(self, html_content: str, page_url: str, output_dir: Path, job: CloneJob):
        """Download CSS, JS, images and other resources"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all resource references
        resources = []
        
        # CSS files
        for tag in soup.find_all('link', rel='stylesheet'):
            href = tag.get('href')
            if href:
                resources.append((urljoin(page_url, href), ResourceType.CSS))
        
        # JavaScript files
        for tag in soup.find_all('script', src=True):
            src = tag.get('src')
            if src:
                resources.append((urljoin(page_url, src), ResourceType.JAVASCRIPT))
        
        # Images
        for tag in soup.find_all('img', src=True):
            src = tag.get('src')
            if src:
                resources.append((urljoin(page_url, src), ResourceType.IMAGE))
        
        # Download resources
        async with aiohttp.ClientSession() as session:
            for resource_url, resource_type in resources:
                try:
                    if job.total_size_bytes > MAX_TOTAL_SIZE_MB * 1024 * 1024:
                        break
                    
                    await self._download_resource(session, resource_url, resource_type, output_dir, job)
                    job.resources_discovered += 1
                    
                except Exception as e:
                    logger.warning("Failed to download resource", url=resource_url, error=str(e))
    
    async def _download_resource(self, session: aiohttp.ClientSession, url: str, 
                                resource_type: ResourceType, output_dir: Path, job: CloneJob):
        """Download a single resource"""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    return
                
                content_length = response.headers.get('content-length')
                if content_length and int(content_length) > MAX_FILE_SIZE_MB * 1024 * 1024:
                    logger.warning("Resource too large", url=url, size=content_length)
                    return
                
                content = await response.read()
                
                if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
                    logger.warning("Resource content too large", url=url, size=len(content))
                    return
                
                # Create resource file path
                parsed_url = urlparse(url)
                resource_path = self._create_resource_path(parsed_url.path, resource_type, output_dir)
                
                # Save resource
                resource_path.parent.mkdir(parents=True, exist_ok=True)
                async with aiofiles.open(resource_path, 'wb') as f:
                    await f.write(content)
                
                job.resources_cloned += 1
                job.total_size_bytes += len(content)
                
                logger.debug("Downloaded resource", url=url, path=str(resource_path), size=len(content))
                
        except Exception as e:
            logger.warning("Failed to download resource", url=url, error=str(e))
    
    def _create_resource_path(self, url_path: str, resource_type: ResourceType, output_dir: Path) -> Path:
        """Create a safe file path for a resource"""
        # Clean up the path
        clean_path = url_path.strip('/')
        if not clean_path:
            clean_path = f"index.{resource_type.value}"
        
        # Remove query parameters and fragments
        clean_path = clean_path.split('?')[0].split('#')[0]
        
        # Ensure safe filename
        clean_path = re.sub(r'[<>:"/\\|?*]', '_', clean_path)
        
        # Add extension if missing
        if not any(clean_path.endswith(ext) for ext in ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.woff', '.woff2', '.ttf']):
            extensions = {
                ResourceType.CSS: '.css',
                ResourceType.JAVASCRIPT: '.js',
                ResourceType.IMAGE: '.png',
                ResourceType.FONT: '.woff',
                ResourceType.OTHER: '.bin'
            }
            clean_path += extensions.get(resource_type, '.bin')
        
        return output_dir / 'resources' / clean_path
    
    async def _save_html_file(self, url: str, content: str, output_dir: Path):
        """Save HTML content to file"""
        parsed_url = urlparse(url)
        path = parsed_url.path.strip('/')
        
        if not path or path.endswith('/'):
            filename = 'index.html'
        else:
            filename = path.split('/')[-1]
            if not filename.endswith('.html') and not filename.endswith('.htm'):
                filename += '.html'
        
        # Create safe filename
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        file_path = output_dir / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(content)
    
    async def _create_archive(self, job: CloneJob, output_dir: Path):
        """Create ZIP archive of cloned site"""
        archive_path = Path(STORAGE_PATH) / f"{job.id}.zip"
        
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_path in output_dir.rglob('*'):
                if file_path.is_file():
                    arcname = file_path.relative_to(output_dir)
                    zipf.write(file_path, arcname)
        
        logger.info("Created archive", job_id=job.id, archive_path=str(archive_path))
    
    async def _save_job_status(self, job: CloneJob):
        """Save job status to Redis"""
        try:
            await self.redis.setex(f"clone_job:{job.id}", 86400, json.dumps(job.to_dict()))
        except Exception as e:
            logger.error("Failed to save job status", error=str(e))


class SiteClonerService:
    """Main site cloner service"""
    
    def __init__(self):
        self.redis_client = None
        self.site_cloner = None
        self.active_jobs: Dict[str, CloneJob] = {}
        
    async def start(self):
        """Start the service"""
        logger.info("Starting Site Cloner Service")
        
        # Initialize Redis
        self.redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        
        # Initialize site cloner
        self.site_cloner = SiteCloner(self.redis_client)
        await self.site_cloner.initialize()
        
        logger.info("Site Cloner Service started")
    
    async def shutdown(self):
        """Shutdown the service"""
        if self.site_cloner:
            await self.site_cloner.shutdown()
        
        logger.info("Site Cloner Service stopped")
    
    async def submit_clone_job(self, url: str, **kwargs) -> str:
        """Submit a new clone job"""
        job_id = hashlib.md5(f"{url}_{datetime.now().isoformat()}".encode()).hexdigest()
        
        job = CloneJob(
            id=job_id,
            url=url,
            depth=kwargs.get('depth', 1),
            include_external=kwargs.get('include_external', False),
            include_media=kwargs.get('include_media', True),
            custom_headers=kwargs.get('custom_headers', {}),
            user_agent=kwargs.get('user_agent', 'SiteClonerBot/1.0'),
            delay_ms=kwargs.get('delay_ms', 1000),
            status=CloneStatus.QUEUED,
            created_at=datetime.now()
        )
        
        # Estimate cost
        estimated_pages = min(100 * (job.depth + 1), MAX_PAGES_PER_JOB)  # Rough estimate
        estimated_size_mb = estimated_pages * 0.5  # Assume 500KB per page
        estimated_time_minutes = estimated_pages * 0.1  # Assume 6 seconds per page
        
        job.estimated_cost = self.site_cloner.cost_calculator.estimate_job_cost(
            estimated_pages, estimated_size_mb, estimated_time_minutes
        )
        
        # Check if cost exceeds limits
        if self.site_cloner.cost_calculator.is_cost_exceeded(job.estimated_cost):
            job.status = CloneStatus.COST_EXCEEDED
            job.error_message = f"Estimated cost ${job.estimated_cost:.2f} exceeds budget"
        
        self.active_jobs[job_id] = job
        await self.site_cloner._save_job_status(job)
        
        # Start job if within limits
        if job.status == CloneStatus.QUEUED:
            # In production, this would be queued to a background worker
            asyncio.create_task(self._run_job(job))
        
        logger.info("Clone job submitted", job_id=job_id, url=url, estimated_cost=job.estimated_cost)
        return job_id
    
    async def _run_job(self, job: CloneJob):
        """Run a clone job (background task)"""
        try:
            await self.site_cloner.clone_site(job)
        except Exception as e:
            logger.error("Job execution failed", job_id=job.id, error=str(e))
            job.status = CloneStatus.FAILED
            job.error_message = str(e)
            await self.site_cloner._save_job_status(job)
    
    async def get_job_status(self, job_id: str) -> Optional[CloneJob]:
        """Get job status"""
        if job_id in self.active_jobs:
            return self.active_jobs[job_id]
        
        # Try to load from Redis
        try:
            job_data = await self.redis_client.get(f"clone_job:{job_id}")
            if job_data:
                data = json.loads(job_data)
                return CloneJob(
                    id=data['id'],
                    url=data['url'],
                    depth=data['depth'],
                    include_external=data['include_external'],
                    include_media=data['include_media'],
                    custom_headers=data['custom_headers'],
                    user_agent=data['user_agent'],
                    delay_ms=data['delay_ms'],
                    status=CloneStatus(data['status']),
                    created_at=datetime.fromisoformat(data['created_at']),
                    started_at=datetime.fromisoformat(data['started_at']) if data.get('started_at') else None,
                    completed_at=datetime.fromisoformat(data['completed_at']) if data.get('completed_at') else None,
                    error_message=data.get('error_message'),
                    pages_discovered=data.get('pages_discovered', 0),
                    pages_cloned=data.get('pages_cloned', 0),
                    resources_discovered=data.get('resources_discovered', 0),
                    resources_cloned=data.get('resources_cloned', 0),
                    total_size_bytes=data.get('total_size_bytes', 0),
                    estimated_cost=data.get('estimated_cost', 0.0),
                    actual_cost=data.get('actual_cost', 0.0)
                )
        except Exception as e:
            logger.error("Failed to load job from Redis", job_id=job_id, error=str(e))
        
        return None
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job"""
        job = await self.get_job_status(job_id)
        if job and job.status in [CloneStatus.QUEUED, CloneStatus.RUNNING]:
            job.status = CloneStatus.CANCELLED
            job.completed_at = datetime.now()
            await self.site_cloner._save_job_status(job)
            return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        active_count = len([job for job in self.active_jobs.values() if job.status == CloneStatus.RUNNING])
        queued_count = len([job for job in self.active_jobs.values() if job.status == CloneStatus.QUEUED])
        
        return {
            "total_jobs": len(self.active_jobs),
            "active_jobs": active_count,
            "queued_jobs": queued_count,
            "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
            "rate_limit_rpm": RATE_LIMIT_REQUESTS_PER_MINUTE,
            "cost_limits": {
                "max_pages_per_job": MAX_PAGES_PER_JOB,
                "max_file_size_mb": MAX_FILE_SIZE_MB,
                "max_total_size_mb": MAX_TOTAL_SIZE_MB
            }
        }


# FastAPI application
app = FastAPI(
    title="Site Cloner Service",
    description="Advanced web site cloning with cost controls and automation integration",
    version="1.0.0"
)

service = SiteClonerService()

@app.on_event("startup")
async def startup():
    await service.start()

@app.on_event("shutdown")
async def shutdown():
    await service.shutdown()


# Request/Response models
class CloneRequest(BaseModel):
    url: HttpUrl
    depth: int = 1
    include_external: bool = False
    include_media: bool = True
    delay_ms: int = 1000
    custom_headers: Dict[str, str] = {}


# API Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "site-cloner-service",
        "active_jobs": len([job for job in service.active_jobs.values() if job.status == CloneStatus.RUNNING])
    }

@app.post("/clone")
async def clone_site(request: CloneRequest):
    """Start a new site cloning job"""
    try:
        job_id = await service.submit_clone_job(
            url=str(request.url),
            depth=request.depth,
            include_external=request.include_external,
            include_media=request.include_media,
            delay_ms=request.delay_ms,
            custom_headers=request.custom_headers
        )
        
        return {
            "job_id": job_id,
            "status": "submitted",
            "message": "Clone job has been queued"
        }
        
    except Exception as e:
        logger.error("Failed to submit clone job", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get the status of a clone job"""
    job = await service.get_job_status(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job.to_dict()

@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a clone job"""
    success = await service.cancel_job(job_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or cannot be cancelled")
    
    return {"message": "Job cancelled successfully"}

@app.get("/stats")
async def get_service_stats():
    """Get service statistics"""
    return service.get_stats()

@app.get("/rate-limit/{domain}")
async def get_rate_limit_info(domain: str):
    """Get rate limit information for a domain"""
    rate_limit_key = f"clone_requests:{domain}"
    info = await service.site_cloner.rate_limiter.get_rate_limit_info(rate_limit_key)
    return info

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)