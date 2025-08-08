#!/usr/bin/env python3
"""
Unified Desktop Update Service - Phase 3 Implementation
Manages desktop application updates with Vault-backed signing
Supports multiple OS platforms and secure update delivery
"""

import asyncio
import logging
import json
import hashlib
import hmac
import base64
import os
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import zipfile

import httpx
import boto3
from botocore.exceptions import ClientError
import hvac  # HashiCorp Vault client
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import RedirectResponse, FileResponse
from pydantic import BaseModel
import structlog
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()

# Configuration
VAULT_URL = os.getenv("VAULT_URL", "http://vault:8200")
VAULT_TOKEN = os.getenv("VAULT_TOKEN")
VAULT_MOUNT_PATH = os.getenv("VAULT_MOUNT_PATH", "secret")
SIGNING_KEY_PATH = os.getenv("SIGNING_KEY_PATH", "desktop-updates/signing-key")

S3_BUCKET = os.getenv("UPDATE_S3_BUCKET", "santaclaude-updates")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CDN_BASE_URL = os.getenv("CDN_BASE_URL", f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com")

# Update channels
UPDATE_CHANNELS = ["stable", "beta", "alpha", "canary"]
SUPPORTED_PLATFORMS = ["windows-x86_64", "darwin-x86_64", "darwin-aarch64", "linux-x86_64", "linux-aarch64"]


class UpdateChannel(Enum):
    STABLE = "stable"
    BETA = "beta" 
    ALPHA = "alpha"
    CANARY = "canary"


class Platform(Enum):
    WINDOWS_X64 = "windows-x86_64"
    MACOS_X64 = "darwin-x86_64"
    MACOS_ARM64 = "darwin-aarch64"
    LINUX_X64 = "linux-x86_64"
    LINUX_ARM64 = "linux-aarch64"


@dataclass
class UpdatePackage:
    """Update package information"""
    version: str
    channel: str
    platform: str
    file_name: str
    file_size: int
    sha256_hash: str
    signature: str
    download_url: str
    release_notes: str
    created_at: datetime
    
    def to_client_dict(self) -> Dict[str, Any]:
        """Convert to client-compatible format"""
        return {
            "version": self.version,
            "platform": self.platform,
            "url": self.download_url,
            "signature": self.signature,
            "length": self.file_size,
            "hash": self.sha256_hash,
            "releaseDate": self.created_at.isoformat(),
            "releaseNotes": self.release_notes
        }


class VaultKeyManager:
    """Manages signing keys in HashiCorp Vault"""
    
    def __init__(self, vault_url: str, vault_token: str, mount_path: str):
        self.vault_url = vault_url
        self.vault_token = vault_token
        self.mount_path = mount_path
        self.client = None
        
    async def initialize(self):
        """Initialize Vault client"""
        try:
            self.client = hvac.Client(url=self.vault_url, token=self.vault_token)
            
            if not self.client.is_authenticated():
                raise Exception("Vault authentication failed")
                
            # Ensure signing key exists
            await self._ensure_signing_key()
            
            logger.info("Vault key manager initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize Vault", error=str(e))
            raise
    
    async def _ensure_signing_key(self):
        """Ensure signing key exists in Vault, create if not"""
        try:
            # Check if key exists
            response = self.client.secrets.kv.v2.read_secret_version(
                path=SIGNING_KEY_PATH,
                mount_point=self.mount_path
            )
            
            if response and response.get('data', {}).get('data', {}).get('private_key'):
                logger.info("Signing key found in Vault")
                return
                
        except Exception:
            # Key doesn't exist, create it
            pass
        
        logger.info("Creating new signing key in Vault")
        
        # Generate RSA key pair
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend()
        )
        
        public_key = private_key.public_key()
        
        # Serialize keys
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')
        
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
        # Store in Vault
        self.client.secrets.kv.v2.create_or_update_secret(
            path=SIGNING_KEY_PATH,
            secret={
                'private_key': private_pem,
                'public_key': public_pem,
                'created_at': datetime.now().isoformat(),
                'algorithm': 'RSA-4096-SHA256'
            },
            mount_point=self.mount_path
        )
        
        logger.info("Signing key created and stored in Vault")
    
    async def get_private_key(self) -> str:
        """Get private key from Vault"""
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=SIGNING_KEY_PATH,
                mount_point=self.mount_path
            )
            
            return response['data']['data']['private_key']
            
        except Exception as e:
            logger.error("Failed to retrieve private key from Vault", error=str(e))
            raise
    
    async def get_public_key(self) -> str:
        """Get public key from Vault"""
        try:
            response = self.client.secrets.kv.v2.read_secret_version(
                path=SIGNING_KEY_PATH,
                mount_point=self.mount_path
            )
            
            return response['data']['data']['public_key']
            
        except Exception as e:
            logger.error("Failed to retrieve public key from Vault", error=str(e))
            raise
    
    async def rotate_key(self) -> Dict[str, str]:
        """Rotate signing key"""
        logger.info("Rotating signing key")
        
        # Backup old key
        try:
            old_response = self.client.secrets.kv.v2.read_secret_version(
                path=SIGNING_KEY_PATH,
                mount_point=self.mount_path
            )
            
            # Store backup
            self.client.secrets.kv.v2.create_or_update_secret(
                path=f"{SIGNING_KEY_PATH}-backup-{int(datetime.now().timestamp())}",
                secret=old_response['data']['data'],
                mount_point=self.mount_path
            )
        except Exception as e:
            logger.warning("Failed to backup old key", error=str(e))
        
        # Create new key (this will overwrite the old one)
        await self._ensure_signing_key()
        
        return {"status": "rotated", "timestamp": datetime.now().isoformat()}


class UpdateStorage:
    """Manages update file storage in S3"""
    
    def __init__(self, bucket: str, region: str):
        self.bucket = bucket
        self.region = region
        self.s3_client = boto3.client('s3', region_name=region)
    
    async def initialize(self):
        """Initialize S3 bucket"""
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
            
            # Set CORS policy for update downloads
            cors_policy = {
                'CORSRules': [
                    {
                        'AllowedOrigins': ['*'],
                        'AllowedMethods': ['GET', 'HEAD'],
                        'AllowedHeaders': ['*'],
                        'MaxAgeSeconds': 3600
                    }
                ]
            }
            
            self.s3_client.put_bucket_cors(Bucket=self.bucket, CORSConfiguration=cors_policy)
            
            logger.info("Update storage initialized", bucket=self.bucket)
            
        except Exception as e:
            logger.error("Failed to initialize update storage", error=str(e))
            raise
    
    async def upload_update_package(self, file_path: str, s3_key: str, metadata: Dict[str, str] = None) -> str:
        """Upload update package to S3"""
        try:
            extra_args = {
                'ContentType': 'application/octet-stream',
                'Metadata': metadata or {}
            }
            
            self.s3_client.upload_file(file_path, self.bucket, s3_key, ExtraArgs=extra_args)
            
            download_url = f"{CDN_BASE_URL}/{s3_key}"
            logger.info("Update package uploaded", s3_key=s3_key, url=download_url)
            
            return download_url
            
        except Exception as e:
            logger.error("Failed to upload update package", error=str(e))
            raise
    
    async def generate_presigned_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for secure downloads"""
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': s3_key},
                ExpiresIn=expires_in
            )
            return url
        except Exception as e:
            logger.error("Failed to generate presigned URL", error=str(e))
            raise


class DesktopUpdateService:
    """Main desktop update service"""
    
    def __init__(self):
        self.vault_manager = VaultKeyManager(VAULT_URL, VAULT_TOKEN, VAULT_MOUNT_PATH)
        self.storage = UpdateStorage(S3_BUCKET, AWS_REGION)
        
        # In-memory update registry (in production, use Redis/DB)
        self.updates_registry: Dict[str, Dict[str, UpdatePackage]] = {
            channel: {} for channel in UPDATE_CHANNELS
        }
        
        # Metrics
        self.total_uploads = 0
        self.total_downloads = 0
        
    async def start(self):
        """Start the update service"""
        logger.info("Starting Desktop Update Service")
        
        # Initialize components
        await self.vault_manager.initialize()
        await self.storage.initialize()
        
        # Load existing updates from storage (simplified - would use DB in production)
        await self._load_existing_updates()
        
        logger.info("Desktop Update Service started")
    
    async def _load_existing_updates(self):
        """Load existing update metadata"""
        # In production, this would load from a database
        # For now, we'll just log that we're ready to accept new updates
        logger.info("Ready to accept update packages")
    
    async def sign_file(self, file_path: str) -> str:
        """Sign a file using the private key from Vault"""
        try:
            # Get private key
            private_key_pem = await self.vault_manager.get_private_key()
            private_key = serialization.load_pem_private_key(
                private_key_pem.encode('utf-8'),
                password=None,
                backend=default_backend()
            )
            
            # Read file and compute hash
            with open(file_path, 'rb') as f:
                file_data = f.read()
            
            # Sign the file hash
            signature = private_key.sign(
                file_data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            return base64.b64encode(signature).decode('utf-8')
            
        except Exception as e:
            logger.error("Failed to sign file", error=str(e))
            raise
    
    async def upload_update(self, 
                          file: UploadFile,
                          version: str,
                          channel: str,
                          platform: str,
                          release_notes: str = "") -> UpdatePackage:
        """Upload and process a new update package"""
        if channel not in UPDATE_CHANNELS:
            raise ValueError(f"Invalid channel: {channel}")
        
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Invalid platform: {platform}")
        
        try:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file.filename.split('.')[-1]}") as tmp_file:
                content = await file.read()
                tmp_file.write(content)
                tmp_file_path = tmp_file.name
            
            try:
                # Calculate file hash
                sha256_hash = hashlib.sha256(content).hexdigest()
                file_size = len(content)
                
                # Sign the file
                signature = await self.sign_file(tmp_file_path)
                
                # Generate S3 key
                s3_key = f"updates/{channel}/{platform}/{version}/{file.filename}"
                
                # Upload to S3
                download_url = await self.storage.upload_update_package(
                    tmp_file_path,
                    s3_key,
                    metadata={
                        'version': version,
                        'channel': channel,
                        'platform': platform,
                        'sha256': sha256_hash,
                        'signature': signature
                    }
                )
                
                # Create update package
                update_package = UpdatePackage(
                    version=version,
                    channel=channel,
                    platform=platform,
                    file_name=file.filename,
                    file_size=file_size,
                    sha256_hash=sha256_hash,
                    signature=signature,
                    download_url=download_url,
                    release_notes=release_notes,
                    created_at=datetime.now()
                )
                
                # Store in registry
                platform_key = f"{platform}-{version}"
                self.updates_registry[channel][platform_key] = update_package
                
                self.total_uploads += 1
                
                logger.info("Update package processed successfully",
                           version=version,
                           channel=channel,
                           platform=platform,
                           file_size=file_size)
                
                return update_package
                
            finally:
                # Clean up temp file
                os.unlink(tmp_file_path)
                
        except Exception as e:
            logger.error("Failed to upload update", error=str(e))
            raise
    
    async def get_latest_update(self, channel: str, platform: str, current_version: str = None) -> Optional[UpdatePackage]:
        """Get the latest update for a platform/channel"""
        if channel not in self.updates_registry:
            return None
        
        channel_updates = self.updates_registry[channel]
        
        # Find latest update for platform
        latest_update = None
        for key, update in channel_updates.items():
            if update.platform == platform:
                if latest_update is None or self._version_compare(update.version, latest_update.version) > 0:
                    # Skip if current version is same or newer
                    if current_version and self._version_compare(update.version, current_version) <= 0:
                        continue
                    latest_update = update
        
        return latest_update
    
    def _version_compare(self, version1: str, version2: str) -> int:
        """Compare two version strings (simplified semantic versioning)"""
        def parse_version(v):
            return [int(x) for x in v.split('.')]
        
        v1_parts = parse_version(version1)
        v2_parts = parse_version(version2)
        
        # Pad shorter version with zeros
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts.extend([0] * (max_len - len(v1_parts)))
        v2_parts.extend([0] * (max_len - len(v2_parts)))
        
        for a, b in zip(v1_parts, v2_parts):
            if a < b:
                return -1
            elif a > b:
                return 1
        
        return 0
    
    async def generate_update_manifest(self, channel: str) -> Dict[str, Any]:
        """Generate update manifest for a channel"""
        if channel not in self.updates_registry:
            return {"updates": {}}
        
        manifest = {"updates": {}}
        
        for platform in SUPPORTED_PLATFORMS:
            latest_update = await self.get_latest_update(channel, platform)
            if latest_update:
                manifest["updates"][platform] = latest_update.to_client_dict()
        
        manifest["generated_at"] = datetime.now().isoformat()
        manifest["channel"] = channel
        
        return manifest
    
    def get_stats(self) -> Dict[str, Any]:
        """Get service statistics"""
        total_updates = sum(len(channel_updates) for channel_updates in self.updates_registry.values())
        
        channel_stats = {}
        for channel, updates in self.updates_registry.items():
            platform_counts = {}
            for update in updates.values():
                platform_counts[update.platform] = platform_counts.get(update.platform, 0) + 1
            channel_stats[channel] = {
                "total_updates": len(updates),
                "platforms": platform_counts
            }
        
        return {
            "total_updates": total_updates,
            "total_uploads": self.total_uploads,
            "total_downloads": self.total_downloads,
            "channels": channel_stats,
            "supported_platforms": SUPPORTED_PLATFORMS,
            "vault_connected": self.vault_manager.client.is_authenticated() if self.vault_manager.client else False
        }


# FastAPI application
app = FastAPI(
    title="Desktop Update Service",
    description="Unified desktop application update system with Vault-backed signing",
    version="1.0.0"
)

service = DesktopUpdateService()

@app.on_event("startup")
async def startup():
    await service.start()

# API Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "desktop-update-service",
        "vault_connected": service.vault_manager.client.is_authenticated() if service.vault_manager.client else False
    }

# Update check endpoint (used by desktop clients)
@app.get("/updates/{channel}/{platform}")
async def check_for_updates(channel: str, platform: str, current_version: str = None):
    """Check for available updates"""
    try:
        if channel not in UPDATE_CHANNELS:
            raise HTTPException(status_code=400, detail="Invalid channel")
        
        if platform not in SUPPORTED_PLATFORMS:
            raise HTTPException(status_code=400, detail="Invalid platform")
        
        latest_update = await service.get_latest_update(channel, platform, current_version)
        
        if not latest_update:
            return {"update_available": False}
        
        service.total_downloads += 1
        
        return {
            "update_available": True,
            "update": latest_update.to_client_dict()
        }
        
    except Exception as e:
        logger.error("Update check failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Update manifest endpoint (Tauri auto-updater format)
@app.get("/manifest/{channel}")
async def get_update_manifest(channel: str):
    """Get update manifest for a channel (Tauri format)"""
    try:
        if channel not in UPDATE_CHANNELS:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        manifest = await service.generate_update_manifest(channel)
        return manifest
        
    except Exception as e:
        logger.error("Manifest generation failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Upload endpoint (for CI/CD systems)
@app.post("/upload")
async def upload_update_package(
    file: UploadFile = File(...),
    version: str = Form(...),
    channel: str = Form(...),
    platform: str = Form(...),
    release_notes: str = Form("")
):
    """Upload a new update package"""
    try:
        update_package = await service.upload_update(
            file, version, channel, platform, release_notes
        )
        
        return {
            "status": "uploaded",
            "update": asdict(update_package)
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Upload failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

# Key management endpoints
@app.get("/public-key")
async def get_public_key():
    """Get public key for signature verification"""
    try:
        public_key = await service.vault_manager.get_public_key()
        return {"public_key": public_key}
    except Exception as e:
        logger.error("Public key retrieval failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/rotate-key")
async def rotate_signing_key():
    """Rotate signing key (admin endpoint)"""
    try:
        result = await service.vault_manager.rotate_key()
        return result
    except Exception as e:
        logger.error("Key rotation failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
async def get_service_stats():
    """Get service statistics"""
    return service.get_stats()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)