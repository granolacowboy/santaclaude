"""
Browser Pool Manager
Manages a pool of Playwright browsers for efficient browser automation
"""

import asyncio
import uuid
import time
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
import logging
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class BrowserSession:
    """Represents an active browser session"""
    
    def __init__(self, session_id: str, context: BrowserContext, created_at: datetime):
        self.session_id = session_id
        self.context = context
        self.created_at = created_at
        self.last_activity = created_at
        self.pages: Dict[str, Page] = {}
        self.metadata = {}
    
    def add_page(self, page: Page) -> str:
        """Add a page to this session and return page ID"""
        page_id = str(uuid.uuid4())
        self.pages[page_id] = page
        self.last_activity = datetime.now()
        return page_id
    
    def get_page(self, page_id: str) -> Optional[Page]:
        """Get a page by ID"""
        return self.pages.get(page_id)
    
    def remove_page(self, page_id: str) -> bool:
        """Remove a page from the session"""
        if page_id in self.pages:
            del self.pages[page_id]
            self.last_activity = datetime.now()
            return True
        return False
    
    async def close(self):
        """Close the browser session"""
        try:
            await self.context.close()
        except Exception as e:
            logger.warning(f"Error closing browser session {self.session_id}: {e}")


class BrowserPool:
    """Manages a pool of browsers and sessions"""
    
    def __init__(self, max_browsers: int = 5, browser_timeout: int = 300):
        self.max_browsers = max_browsers
        self.browser_timeout = browser_timeout
        
        self._playwright: Optional[Playwright] = None
        self._browsers: List[Browser] = []
        self.active_sessions: Dict[str, BrowserSession] = {}
        
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        
    async def start(self):
        """Initialize the browser pool"""
        logger.info("Starting browser pool...")
        
        self._playwright = await async_playwright().start()
        
        # Launch initial browsers
        for i in range(self.max_browsers):
            await self._launch_browser()
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_sessions())
        
        logger.info(f"Browser pool started with {len(self._browsers)} browsers")
    
    async def stop(self):
        """Shutdown the browser pool"""
        logger.info("Stopping browser pool...")
        
        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Close all active sessions
        for session in list(self.active_sessions.values()):
            await session.close()
        self.active_sessions.clear()
        
        # Close all browsers
        for browser in self._browsers:
            try:
                await browser.close()
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
        self._browsers.clear()
        
        # Stop playwright
        if self._playwright:
            await self._playwright.stop()
            
        logger.info("Browser pool stopped")
    
    def is_ready(self) -> bool:
        """Check if the pool is ready for use"""
        return (
            self._playwright is not None and
            len(self._browsers) > 0 and
            len(self.active_sessions) < self.max_browsers
        )
    
    def available_count(self) -> int:
        """Get number of available browser slots"""
        return max(0, self.max_browsers - len(self.active_sessions))
    
    async def _launch_browser(self) -> Browser:
        """Launch a new browser instance"""
        browser_args = []
        
        if not settings.ENABLE_SANDBOX:
            browser_args.extend(['--no-sandbox', '--disable-setuid-sandbox'])
        
        browser = await getattr(self._playwright, settings.BROWSER_TYPE.lower()).launch(
            headless=settings.HEADLESS,
            args=browser_args
        )
        
        self._browsers.append(browser)
        return browser
    
    async def create_session(self, user_id: Optional[int] = None, metadata: Optional[Dict] = None) -> str:
        """Create a new browser session"""
        async with self._lock:
            if len(self.active_sessions) >= self.max_browsers:
                raise Exception("Browser pool at capacity")
            
            # Get an available browser (or launch new one)
            if not self._browsers:
                await self._launch_browser()
            
            browser = self._browsers[0]  # Simple round-robin for now
            
            # Create new context
            context = await browser.new_context(
                viewport={
                    'width': settings.VIEWPORT_WIDTH,
                    'height': settings.VIEWPORT_HEIGHT
                },
                user_agent=settings.USER_AGENT
            )
            
            # Create session
            session_id = str(uuid.uuid4())
            session = BrowserSession(session_id, context, datetime.now())
            
            if metadata:
                session.metadata.update(metadata)
            if user_id:
                session.metadata['user_id'] = user_id
                
            self.active_sessions[session_id] = session
            
            logger.info(f"Created browser session {session_id}")
            return session_id
    
    async def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """Get an existing browser session"""
        session = self.active_sessions.get(session_id)
        if session:
            session.last_activity = datetime.now()
        return session
    
    async def close_session(self, session_id: str) -> bool:
        """Close a browser session"""
        session = self.active_sessions.get(session_id)
        if session:
            await session.close()
            del self.active_sessions[session_id]
            logger.info(f"Closed browser session {session_id}")
            return True
        return False
    
    async def create_page(self, session_id: str, url: Optional[str] = None) -> Optional[str]:
        """Create a new page in a session"""
        session = await self.get_session(session_id)
        if not session:
            return None
            
        try:
            page = await session.context.new_page()
            page_id = session.add_page(page)
            
            if url:
                await page.goto(url, timeout=settings.MAX_PAGE_LOAD_TIME * 1000)
                
            return page_id
        except Exception as e:
            logger.error(f"Error creating page in session {session_id}: {e}")
            return None
    
    async def get_page(self, session_id: str, page_id: str) -> Optional[Page]:
        """Get a page from a session"""
        session = await self.get_session(session_id)
        if session:
            return session.get_page(page_id)
        return None
    
    async def close_page(self, session_id: str, page_id: str) -> bool:
        """Close a page in a session"""
        session = await self.get_session(session_id)
        if session:
            page = session.get_page(page_id)
            if page:
                try:
                    await page.close()
                    session.remove_page(page_id)
                    return True
                except Exception as e:
                    logger.error(f"Error closing page {page_id}: {e}")
        return False
    
    async def _cleanup_expired_sessions(self):
        """Cleanup expired sessions periodically"""
        while True:
            try:
                await asyncio.sleep(settings.SESSION_CLEANUP_INTERVAL)
                
                now = datetime.now()
                expired_sessions = []
                
                for session_id, session in self.active_sessions.items():
                    if (now - session.last_activity).total_seconds() > self.browser_timeout:
                        expired_sessions.append(session_id)
                
                for session_id in expired_sessions:
                    logger.info(f"Cleaning up expired session {session_id}")
                    await self.close_session(session_id)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in session cleanup: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics"""
        return {
            "total_browsers": len(self._browsers),
            "active_sessions": len(self.active_sessions),
            "available_slots": self.available_count(),
            "session_details": [
                {
                    "session_id": session.session_id,
                    "created_at": session.created_at.isoformat(),
                    "last_activity": session.last_activity.isoformat(),
                    "page_count": len(session.pages),
                    "metadata": session.metadata
                }
                for session in self.active_sessions.values()
            ]
        }