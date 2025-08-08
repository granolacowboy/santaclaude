"""
Hybrid Browser Pool Service
Supports both Python (legacy) and Node.js (Phase 3) implementations
Provides seamless migration path and fallback capabilities
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from enum import Enum

from app.browser_pool import BrowserPool as PythonBrowserPool, BrowserSession as PythonBrowserSession
from app.node_client import BrowserPoolNodeClient, BrowserPoolOrchestrator
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class BrowserPoolMode(Enum):
    PYTHON_ONLY = "python_only"
    NODE_ONLY = "node_only" 
    HYBRID = "hybrid"
    AUTO = "auto"


class HybridBrowserSession:
    """
    Unified session interface for both Python and Node.js implementations
    """
    
    def __init__(self, session_id: str, backend: str, created_at: datetime, 
                 python_session: Optional[PythonBrowserSession] = None,
                 node_session_id: Optional[str] = None):
        self.session_id = session_id
        self.backend = backend  # "python" or "node"
        self.created_at = created_at
        self.last_activity = created_at
        self.metadata = {}
        
        # Backend-specific session references
        self._python_session = python_session
        self._node_session_id = node_session_id
        
        # Unified page tracking
        self.pages = {}
    
    @property
    def page_count(self) -> int:
        if self.backend == "python" and self._python_session:
            return len(self._python_session.pages)
        return len(self.pages)
    
    def is_python_backend(self) -> bool:
        return self.backend == "python"
    
    def is_node_backend(self) -> bool:
        return self.backend == "node"
    
    def get_python_session(self) -> Optional[PythonBrowserSession]:
        return self._python_session
    
    def get_node_session_id(self) -> Optional[str]:
        return self._node_session_id


class HybridBrowserPool:
    """
    Hybrid Browser Pool that supports both Python and Node.js implementations
    Provides unified interface with automatic backend selection and fallback
    """
    
    def __init__(self, mode: BrowserPoolMode = BrowserPoolMode.AUTO,
                 node_service_host: str = "browser-pool-service-node",
                 node_grpc_port: int = 50051,
                 node_ws_port: int = 8080):
        self.mode = mode
        self.node_service_host = node_service_host
        self.node_grpc_port = node_grpc_port
        self.node_ws_port = node_ws_port
        
        # Backend implementations
        self._python_pool: Optional[PythonBrowserPool] = None
        self._node_client: Optional[BrowserPoolNodeClient] = None
        self._node_orchestrator: Optional[BrowserPoolOrchestrator] = None
        
        # Session management
        self.active_sessions: Dict[str, HybridBrowserSession] = {}
        self._session_counter = 0
        
        # Backend availability
        self._python_available = False
        self._node_available = False
        
        logger.info(f"Initialized hybrid browser pool in {mode.value} mode")
    
    async def start(self):
        """Initialize the hybrid browser pool"""
        logger.info("Starting hybrid browser pool...")
        
        # Initialize Python pool
        if self.mode in [BrowserPoolMode.PYTHON_ONLY, BrowserPoolMode.HYBRID, BrowserPoolMode.AUTO]:
            try:
                self._python_pool = PythonBrowserPool(
                    max_browsers=settings.MAX_BROWSERS,
                    browser_timeout=settings.BROWSER_TIMEOUT
                )
                await self._python_pool.start()
                self._python_available = True
                logger.info("Python browser pool initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Python browser pool: {e}")
                if self.mode == BrowserPoolMode.PYTHON_ONLY:
                    raise
        
        # Initialize Node.js client
        if self.mode in [BrowserPoolMode.NODE_ONLY, BrowserPoolMode.HYBRID, BrowserPoolMode.AUTO]:
            try:
                self._node_client = BrowserPoolNodeClient(
                    grpc_host=self.node_service_host,
                    grpc_port=self.node_grpc_port,
                    ws_host=self.node_service_host,
                    ws_port=self.node_ws_port
                )
                await self._node_client.connect()
                
                self._node_orchestrator = BrowserPoolOrchestrator(self._node_client)
                self._node_available = True
                
                # Register event callbacks
                self._setup_node_event_handlers()
                
                logger.info("Node.js browser pool client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Node.js browser pool client: {e}")
                if self.mode == BrowserPoolMode.NODE_ONLY:
                    raise
        
        # Verify at least one backend is available
        if not self._python_available and not self._node_available:
            raise RuntimeError("No browser pool backends are available")
        
        # Set default mode based on availability
        if self.mode == BrowserPoolMode.AUTO:
            if self._node_available:
                logger.info("Auto mode: Using Node.js backend as primary")
            else:
                logger.info("Auto mode: Using Python backend as fallback")
        
        logger.info(f"Hybrid browser pool started (Python: {self._python_available}, Node.js: {self._node_available})")
    
    async def stop(self):
        """Shutdown the hybrid browser pool"""
        logger.info("Stopping hybrid browser pool...")
        
        # Close all active sessions
        session_ids = list(self.active_sessions.keys())
        for session_id in session_ids:
            try:
                await self.close_session(session_id)
            except Exception as e:
                logger.warning(f"Error closing session {session_id}: {e}")
        
        # Stop Node.js client
        if self._node_client:
            try:
                await self._node_client.disconnect()
            except Exception as e:
                logger.warning(f"Error stopping Node.js client: {e}")
        
        # Stop Python pool
        if self._python_pool:
            try:
                await self._python_pool.stop()
            except Exception as e:
                logger.warning(f"Error stopping Python pool: {e}")
        
        logger.info("Hybrid browser pool stopped")
    
    def _setup_node_event_handlers(self):
        """Set up event handlers for Node.js backend"""
        if not self._node_client:
            return
        
        # Register callbacks for browser events
        self._node_client.register_event_callback(
            'session.created',
            self._on_node_session_created
        )
        
        self._node_client.register_event_callback(
            'session.closed', 
            self._on_node_session_closed
        )
        
        self._node_client.register_event_callback(
            'page.*',
            self._on_node_page_event
        )
    
    async def _on_node_session_created(self, topic: str, payload: Dict[str, Any]):
        """Handle Node.js session creation events"""
        logger.debug(f"Node.js session created: {payload}")
    
    async def _on_node_session_closed(self, topic: str, payload: Dict[str, Any]):
        """Handle Node.js session closure events"""
        logger.debug(f"Node.js session closed: {payload}")
    
    async def _on_node_page_event(self, topic: str, payload: Dict[str, Any]):
        """Handle Node.js page events"""
        logger.debug(f"Node.js page event {topic}: {payload}")
    
    def _select_backend(self, preference: Optional[str] = None) -> str:
        """Select appropriate backend based on mode and availability"""
        if preference == "python" and self._python_available:
            return "python"
        elif preference == "node" and self._node_available:
            return "node"
        
        # Auto selection based on mode
        if self.mode == BrowserPoolMode.PYTHON_ONLY:
            if self._python_available:
                return "python"
            raise RuntimeError("Python backend not available")
        
        elif self.mode == BrowserPoolMode.NODE_ONLY:
            if self._node_available:
                return "node"
            raise RuntimeError("Node.js backend not available")
        
        elif self.mode == BrowserPoolMode.HYBRID or self.mode == BrowserPoolMode.AUTO:
            # Prefer Node.js for new sessions (Phase 3 goal)
            if self._node_available:
                return "node"
            elif self._python_available:
                return "python"
            else:
                raise RuntimeError("No backends available")
        
        raise RuntimeError(f"Unable to select backend for mode {self.mode}")
    
    async def create_session(self, user_id: Optional[int] = None, 
                           metadata: Optional[Dict] = None,
                           backend_preference: Optional[str] = None) -> str:
        """Create a new browser session using the appropriate backend"""
        try:
            backend = self._select_backend(backend_preference)
            session_id = f"hybrid_{self._session_counter}_{backend}"
            self._session_counter += 1
            
            if backend == "python":
                python_session_id = await self._python_pool.create_session(user_id, metadata)
                python_session = await self._python_pool.get_session(python_session_id)
                
                hybrid_session = HybridBrowserSession(
                    session_id=session_id,
                    backend="python",
                    created_at=python_session.created_at,
                    python_session=python_session
                )
                
            elif backend == "node":
                node_session_id = await self._node_client.create_session(
                    user_id=str(user_id) if user_id else None,
                    metadata=metadata
                )
                
                hybrid_session = HybridBrowserSession(
                    session_id=session_id,
                    backend="node",
                    created_at=datetime.now(),
                    node_session_id=node_session_id
                )
            
            # Store unified session
            self.active_sessions[session_id] = hybrid_session
            
            if metadata:
                hybrid_session.metadata.update(metadata)
            if user_id:
                hybrid_session.metadata['user_id'] = user_id
            
            logger.info(f"Created hybrid session {session_id} using {backend} backend")
            return session_id
            
        except Exception as e:
            logger.error(f"Failed to create hybrid session: {e}")
            raise
    
    async def get_session(self, session_id: str) -> Optional[HybridBrowserSession]:
        """Get a hybrid browser session"""
        session = self.active_sessions.get(session_id)
        if session:
            session.last_activity = datetime.now()
        return session
    
    async def close_session(self, session_id: str) -> bool:
        """Close a hybrid browser session"""
        session = self.active_sessions.get(session_id)
        if not session:
            return False
        
        try:
            if session.is_python_backend():
                python_session = session.get_python_session()
                if python_session:
                    await python_session.close()
            
            elif session.is_node_backend():
                node_session_id = session.get_node_session_id()
                if node_session_id:
                    await self._node_client.close_session(node_session_id)
            
            # Remove from active sessions
            del self.active_sessions[session_id]
            
            logger.info(f"Closed hybrid session {session_id} ({session.backend} backend)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to close hybrid session {session_id}: {e}")
            return False
    
    async def create_page(self, session_id: str, url: Optional[str] = None) -> Optional[str]:
        """Create a new page in a session"""
        session = await self.get_session(session_id)
        if not session:
            return None
        
        try:
            if session.is_python_backend():
                python_session = session.get_python_session()
                if not python_session:
                    return None
                
                page_id = await self._python_pool.create_page(
                    python_session.session_id, url
                )
                
            elif session.is_node_backend():
                node_session_id = session.get_node_session_id()
                if not node_session_id:
                    return None
                
                page_id = await self._node_client.create_page(node_session_id, url)
            
            # Track page in hybrid session
            if page_id:
                session.pages[page_id] = {'url': url, 'created_at': datetime.now()}
            
            return page_id
            
        except Exception as e:
            logger.error(f"Failed to create page in session {session_id}: {e}")
            return None
    
    async def get_page(self, session_id: str, page_id: str):
        """Get a page from a session (returns backend-specific page object)"""
        session = await self.get_session(session_id)
        if not session:
            return None
        
        if session.is_python_backend():
            python_session = session.get_python_session()
            if python_session:
                return python_session.get_page(page_id)
        
        elif session.is_node_backend():
            # For Node.js backend, we don't return the actual page object
            # Instead, operations are performed via the client
            if page_id in session.pages:
                return {"page_id": page_id, "backend": "node"}
        
        return None
    
    async def close_page(self, session_id: str, page_id: str) -> bool:
        """Close a page in a session"""
        session = await self.get_session(session_id)
        if not session:
            return False
        
        try:
            if session.is_python_backend():
                python_session = session.get_python_session()
                if python_session:
                    page = python_session.get_page(page_id)
                    if page:
                        await page.close()
                        python_session.remove_page(page_id)
                        return True
            
            elif session.is_node_backend():
                node_session_id = session.get_node_session_id()
                if node_session_id and page_id in session.pages:
                    # Would call Node.js service to close page
                    # For now, just remove from tracking
                    del session.pages[page_id]
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to close page {page_id} in session {session_id}: {e}")
            return False
    
    def is_ready(self) -> bool:
        """Check if the hybrid pool is ready for use"""
        if self.mode == BrowserPoolMode.PYTHON_ONLY:
            return self._python_available and self._python_pool and self._python_pool.is_ready()
        
        elif self.mode == BrowserPoolMode.NODE_ONLY:
            return self._node_available
        
        else:  # HYBRID or AUTO
            return self._python_available or self._node_available
    
    def available_count(self) -> int:
        """Get number of available browser slots across all backends"""
        count = 0
        
        if self._python_available and self._python_pool:
            count += self._python_pool.available_count()
        
        if self._node_available:
            # Would query Node.js service for availability
            # For now, assume some capacity
            count += max(0, settings.MAX_BROWSERS - len([s for s in self.active_sessions.values() if s.is_node_backend()]))
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics from both backends"""
        stats = {
            "mode": self.mode.value,
            "backends": {
                "python": {
                    "available": self._python_available,
                    "sessions": len([s for s in self.active_sessions.values() if s.is_python_backend()])
                },
                "node": {
                    "available": self._node_available, 
                    "sessions": len([s for s in self.active_sessions.values() if s.is_node_backend()])
                }
            },
            "total_sessions": len(self.active_sessions),
            "available_slots": self.available_count(),
            "session_details": []
        }
        
        # Add session details
        for session in self.active_sessions.values():
            stats["session_details"].append({
                "session_id": session.session_id,
                "backend": session.backend,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "page_count": session.page_count,
                "metadata": session.metadata
            })
        
        return stats
    
    async def migrate_session_to_node(self, session_id: str) -> bool:
        """Migrate a Python session to Node.js backend (for Phase 3 transition)"""
        session = await self.get_session(session_id)
        if not session or not session.is_python_backend():
            return False
        
        if not self._node_available:
            logger.warning("Cannot migrate session: Node.js backend not available")
            return False
        
        try:
            # Create new Node.js session
            node_session_id = await self._node_client.create_session(
                user_id=session.metadata.get('user_id'),
                metadata=session.metadata
            )
            
            # Close Python session
            python_session = session.get_python_session()
            if python_session:
                await python_session.close()
            
            # Update hybrid session to point to Node.js backend
            session.backend = "node"
            session._python_session = None
            session._node_session_id = node_session_id
            
            logger.info(f"Successfully migrated session {session_id} from Python to Node.js")
            return True
            
        except Exception as e:
            logger.error(f"Failed to migrate session {session_id} to Node.js: {e}")
            return False