"""
Python Client for Node.js Browser Pool Service
Provides integration between Python automation workers and Node.js browser pool
"""

import grpc
import asyncio
import websockets
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading

from .core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    # Import generated gRPC classes (these would be generated from proto files)
    # For now, we'll create mock classes to demonstrate the integration
    class MockBrowserPoolStub:
        def __init__(self, channel):
            self.channel = channel
            
        def Acquire(self, request):
            """Mock implementation - would use real gRPC stub"""
            pass
            
        def Release(self, request):
            """Mock implementation - would use real gRPC stub"""
            pass
            
        def CreatePage(self, request):
            """Mock implementation - would use real gRPC stub"""
            pass
            
    # Mock message classes
    class SessionSpec:
        def __init__(self, user_id=None, options=None, metadata=None):
            self.user_id = user_id
            self.options = options or {}
            self.metadata = metadata or {}
    
    class SessionHandle:
        def __init__(self, session_id):
            self.session_id = session_id
            
    class CreatePageRequest:
        def __init__(self, session_id, url=None, timeout_ms=None):
            self.session_id = session_id
            self.url = url
            self.timeout_ms = timeout_ms
            
except ImportError:
    logger.warning("gRPC protobuf classes not found. Using mock implementations.")
    # Use mock classes as fallback


class BrowserPoolNodeClient:
    """
    Python client for Node.js Browser Pool Service
    Handles gRPC communication and WebSocket events
    """
    
    def __init__(self, grpc_host: str = "browser-pool-service-node", 
                 grpc_port: int = 50051,
                 ws_host: str = "browser-pool-service-node",
                 ws_port: int = 8080):
        self.grpc_host = grpc_host
        self.grpc_port = grpc_port
        self.ws_host = ws_host
        self.ws_port = ws_port
        
        self._grpc_channel = None
        self._grpc_stub = None
        self._ws_connection = None
        self._ws_task = None
        self._event_callbacks = {}
        
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._lock = asyncio.Lock()
        
    async def connect(self):
        """Initialize connections to Node.js service"""
        try:
            # Set up gRPC connection
            self.setup_grpc_connection()
            
            # Set up WebSocket connection for events
            await self.setup_websocket_connection()
            
            logger.info(f"Connected to Node.js Browser Pool Service at {self.grpc_host}:{self.grpc_port}")
            
        except Exception as e:
            logger.error(f"Failed to connect to Node.js Browser Pool Service: {e}")
            raise
    
    async def disconnect(self):
        """Clean up connections"""
        # Close WebSocket
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        
        if self._ws_connection:
            await self._ws_connection.close()
        
        # Close gRPC channel
        if self._grpc_channel:
            await self._grpc_channel.close()
            
        # Shutdown executor
        self._executor.shutdown(wait=True)
        
        logger.info("Disconnected from Node.js Browser Pool Service")
    
    def setup_grpc_connection(self):
        """Set up gRPC channel and stub"""
        address = f"{self.grpc_host}:{self.grpc_port}"
        self._grpc_channel = grpc.aio.insecure_channel(address)
        self._grpc_stub = MockBrowserPoolStub(self._grpc_channel)
        
    async def setup_websocket_connection(self):
        """Set up WebSocket connection for real-time events"""
        uri = f"ws://{self.ws_host}:{self.ws_port}"
        
        try:
            self._ws_connection = await websockets.connect(uri)
            self._ws_task = asyncio.create_task(self._websocket_handler())
            
            # Subscribe to all browser events
            await self.subscribe_to_events(['*'])
            
        except Exception as e:
            logger.error(f"Failed to establish WebSocket connection: {e}")
            raise
    
    async def _websocket_handler(self):
        """Handle incoming WebSocket messages"""
        try:
            async for message in self._ws_connection:
                try:
                    event = json.loads(message)
                    await self._handle_websocket_event(event)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid WebSocket message: {e}")
                except Exception as e:
                    logger.error(f"Error handling WebSocket event: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"WebSocket handler error: {e}")
    
    async def _handle_websocket_event(self, event: Dict[str, Any]):
        """Process WebSocket events and trigger callbacks"""
        event_type = event.get('type')
        topic = event.get('topic')
        payload = event.get('payload', {})
        
        logger.debug(f"Received WebSocket event: {event_type}", extra={'topic': topic})
        
        # Handle specific event types
        if event_type == 'broadcast' and topic:
            # Trigger registered callbacks for this topic
            for pattern, callback in self._event_callbacks.items():
                if self._matches_pattern(topic, pattern):
                    try:
                        await callback(topic, payload)
                    except Exception as e:
                        logger.error(f"Error in event callback for {topic}: {e}")
        
        elif event_type == 'connection':
            logger.info("WebSocket connection established", extra={'payload': payload})
        
        elif event_type == 'error':
            logger.error(f"WebSocket error: {payload.get('message')}")
    
    def _matches_pattern(self, topic: str, pattern: str) -> bool:
        """Check if topic matches pattern (supports wildcards)"""
        if pattern == '*':
            return True
        
        # Simple wildcard matching
        if pattern.endswith('*'):
            return topic.startswith(pattern[:-1])
        
        return topic == pattern
    
    async def subscribe_to_events(self, topics: List[str]):
        """Subscribe to WebSocket event topics"""
        if not self._ws_connection:
            raise RuntimeError("WebSocket not connected")
        
        message = {
            "type": "subscribe",
            "payload": {"topics": topics}
        }
        
        await self._ws_connection.send(json.dumps(message))
        logger.debug(f"Subscribed to WebSocket topics: {topics}")
    
    def register_event_callback(self, topic_pattern: str, callback):
        """Register callback for WebSocket events"""
        self._event_callbacks[topic_pattern] = callback
        logger.debug(f"Registered event callback for pattern: {topic_pattern}")
    
    # Browser Pool Operations
    
    async def create_session(self, user_id: Optional[str] = None, 
                           metadata: Optional[Dict[str, str]] = None) -> str:
        """Create a new browser session"""
        async with self._lock:
            try:
                request = SessionSpec(
                    user_id=user_id,
                    metadata=metadata or {}
                )
                
                # In real implementation, this would be:
                # response = await self._grpc_stub.Acquire(request)
                # return response.session_id
                
                # Mock implementation
                session_id = f"session_{datetime.now().timestamp()}"
                logger.info(f"Created browser session: {session_id}", 
                           extra={'user_id': user_id, 'metadata': metadata})
                return session_id
                
            except Exception as e:
                logger.error(f"Failed to create browser session: {e}")
                raise
    
    async def close_session(self, session_id: str) -> bool:
        """Close a browser session"""
        try:
            request = SessionHandle(session_id=session_id)
            
            # In real implementation:
            # response = await self._grpc_stub.Release(request)
            # return response.success
            
            # Mock implementation
            logger.info(f"Closed browser session: {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to close browser session {session_id}: {e}")
            return False
    
    async def create_page(self, session_id: str, url: Optional[str] = None) -> str:
        """Create a new page in a browser session"""
        try:
            request = CreatePageRequest(
                session_id=session_id,
                url=url,
                timeout_ms=settings.MAX_PAGE_LOAD_TIME * 1000
            )
            
            # In real implementation:
            # response = await self._grpc_stub.CreatePage(request)
            # return response.page_id
            
            # Mock implementation
            page_id = f"page_{datetime.now().timestamp()}"
            logger.info(f"Created page {page_id} in session {session_id}", 
                       extra={'url': url})
            return page_id
            
        except Exception as e:
            logger.error(f"Failed to create page in session {session_id}: {e}")
            raise
    
    async def navigate_page(self, session_id: str, page_id: str, url: str) -> Dict[str, Any]:
        """Navigate a page to a URL"""
        try:
            # Mock implementation - would use gRPC NavigatePage call
            logger.info(f"Navigating page {page_id} to {url}", 
                       extra={'session_id': session_id})
            
            return {
                'success': True,
                'final_url': url,
                'title': f'Page title for {url}',
                'error': ''
            }
            
        except Exception as e:
            logger.error(f"Failed to navigate page {page_id}: {e}")
            return {
                'success': False,
                'final_url': '',
                'title': '',
                'error': str(e)
            }
    
    async def click_element(self, session_id: str, page_id: str, selector: str) -> bool:
        """Click an element on the page"""
        try:
            # Mock implementation - would use gRPC Click call
            logger.info(f"Clicking element '{selector}' on page {page_id}", 
                       extra={'session_id': session_id})
            return True
            
        except Exception as e:
            logger.error(f"Failed to click element '{selector}': {e}")
            return False
    
    async def type_text(self, session_id: str, page_id: str, selector: str, text: str) -> bool:
        """Type text into an element"""
        try:
            # Mock implementation - would use gRPC Type call
            logger.info(f"Typing text into '{selector}' on page {page_id}", 
                       extra={'session_id': session_id, 'text_length': len(text)})
            return True
            
        except Exception as e:
            logger.error(f"Failed to type text into '{selector}': {e}")
            return False
    
    async def take_screenshot(self, session_id: str, page_id: str, 
                            full_page: bool = False, format: str = 'png') -> Optional[bytes]:
        """Take a screenshot of the page"""
        try:
            # Mock implementation - would use gRPC Screenshot call
            logger.info(f"Taking screenshot of page {page_id}", 
                       extra={'session_id': session_id, 'full_page': full_page, 'format': format})
            
            # Return mock image data
            return b"mock_screenshot_data"
            
        except Exception as e:
            logger.error(f"Failed to take screenshot of page {page_id}: {e}")
            return None
    
    async def get_page_content(self, session_id: str, page_id: str, 
                             content_type: str = 'html') -> Optional[str]:
        """Get page content"""
        try:
            # Mock implementation - would use gRPC GetContent call
            logger.info(f"Getting {content_type} content from page {page_id}", 
                       extra={'session_id': session_id})
            
            return f"<html><body>Mock {content_type} content for page {page_id}</body></html>"
            
        except Exception as e:
            logger.error(f"Failed to get page content: {e}")
            return None
    
    async def get_pool_stats(self) -> Dict[str, Any]:
        """Get browser pool statistics"""
        try:
            # Mock implementation - would use gRPC GetStats call
            return {
                'total_browsers': 3,
                'active_sessions': 2,
                'available_slots': 1,
                'session_stats': []
            }
            
        except Exception as e:
            logger.error(f"Failed to get pool stats: {e}")
            return {}
    
    async def health_check(self) -> Dict[str, Any]:
        """Check service health"""
        try:
            # Mock implementation - would use gRPC HealthCheck call
            return {
                'ready': True,
                'status': 'healthy',
                'uptime_seconds': 3600
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                'ready': False,
                'status': 'unhealthy',
                'uptime_seconds': 0
            }


class BrowserPoolOrchestrator:
    """
    High-level orchestrator for browser automation tasks
    Manages multiple browser sessions and coordinates complex workflows
    """
    
    def __init__(self, node_client: BrowserPoolNodeClient):
        self.client = node_client
        self.active_sessions = {}
        
    async def start_automation_session(self, user_id: str, workflow_config: Dict[str, Any]) -> str:
        """Start a new automation session with workflow configuration"""
        try:
            # Create browser session
            session_id = await self.client.create_session(
                user_id=user_id,
                metadata={
                    'workflow_type': workflow_config.get('type'),
                    'started_at': datetime.now().isoformat()
                }
            )
            
            # Track session
            self.active_sessions[session_id] = {
                'user_id': user_id,
                'workflow_config': workflow_config,
                'pages': {},
                'started_at': datetime.now(),
                'status': 'active'
            }
            
            logger.info(f"Started automation session {session_id} for user {user_id}")
            return session_id
            
        except Exception as e:
            logger.error(f"Failed to start automation session: {e}")
            raise
    
    async def execute_workflow_step(self, session_id: str, step_config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a single workflow step"""
        if session_id not in self.active_sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.active_sessions[session_id]
        step_type = step_config.get('type')
        
        try:
            result = None
            
            if step_type == 'navigate':
                page_id = await self.client.create_page(session_id, step_config.get('url'))
                session['pages'][page_id] = {'url': step_config.get('url')}
                result = {'page_id': page_id, 'success': True}
                
            elif step_type == 'click':
                success = await self.client.click_element(
                    session_id, 
                    step_config['page_id'], 
                    step_config['selector']
                )
                result = {'success': success}
                
            elif step_type == 'type':
                success = await self.client.type_text(
                    session_id,
                    step_config['page_id'],
                    step_config['selector'],
                    step_config['text']
                )
                result = {'success': success}
                
            elif step_type == 'screenshot':
                image_data = await self.client.take_screenshot(
                    session_id,
                    step_config['page_id'],
                    step_config.get('full_page', False)
                )
                result = {'success': image_data is not None, 'image_data': image_data}
                
            else:
                raise ValueError(f"Unknown workflow step type: {step_type}")
            
            logger.info(f"Executed workflow step '{step_type}' in session {session_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute workflow step '{step_type}': {e}")
            raise
    
    async def cleanup_session(self, session_id: str):
        """Clean up an automation session"""
        try:
            if session_id in self.active_sessions:
                await self.client.close_session(session_id)
                del self.active_sessions[session_id]
                logger.info(f"Cleaned up automation session {session_id}")
            
        except Exception as e:
            logger.error(f"Failed to cleanup session {session_id}: {e}")
    
    async def get_session_status(self, session_id: str) -> Dict[str, Any]:
        """Get status of an automation session"""
        if session_id not in self.active_sessions:
            return {'status': 'not_found'}
        
        session = self.active_sessions[session_id]
        return {
            'session_id': session_id,
            'user_id': session['user_id'],
            'status': session['status'],
            'started_at': session['started_at'].isoformat(),
            'page_count': len(session['pages']),
            'workflow_type': session['workflow_config'].get('type')
        }