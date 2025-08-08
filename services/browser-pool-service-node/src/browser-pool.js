import { chromium, firefox, webkit } from 'playwright';
import { v4 as uuidv4 } from 'uuid';
import logger from './logger.js';
import { config } from './config.js';

/**
 * Browser Session class
 * Represents an active browser session with context and pages
 */
export class BrowserSession {
  constructor(sessionId, context, createdAt) {
    this.sessionId = sessionId;
    this.context = context;
    this.createdAt = createdAt;
    this.lastActivity = createdAt;
    this.pages = new Map(); // pageId -> Page
    this.metadata = new Map();
  }

  addPage(page) {
    const pageId = uuidv4();
    this.pages.set(pageId, page);
    this.lastActivity = new Date();
    
    // Set up page error handling
    page.on('error', (error) => {
      logger.error(`Page error in session ${this.sessionId}, page ${pageId}:`, error);
    });
    
    page.on('pageerror', (error) => {
      logger.error(`Page script error in session ${this.sessionId}, page ${pageId}:`, error);
    });
    
    return pageId;
  }

  getPage(pageId) {
    return this.pages.get(pageId);
  }

  removePage(pageId) {
    const removed = this.pages.delete(pageId);
    if (removed) {
      this.lastActivity = new Date();
    }
    return removed;
  }

  async close() {
    try {
      // Close all pages first
      for (const [pageId, page] of this.pages) {
        try {
          await page.close();
        } catch (error) {
          logger.warn(`Error closing page ${pageId}:`, error);
        }
      }
      this.pages.clear();
      
      // Close the context
      await this.context.close();
    } catch (error) {
      logger.warn(`Error closing browser session ${this.sessionId}:`, error);
    }
  }

  isExpired(timeoutSeconds) {
    const now = new Date();
    return (now - this.lastActivity) / 1000 > timeoutSeconds;
  }

  getStats() {
    return {
      sessionId: this.sessionId,
      createdAt: this.createdAt.toISOString(),
      lastActivity: this.lastActivity.toISOString(),
      pageCount: this.pages.size,
      metadata: Object.fromEntries(this.metadata)
    };
  }
}

/**
 * Browser Pool Manager
 * Manages a pool of browsers and sessions for efficient browser automation
 */
export class BrowserPool {
  constructor() {
    this.maxBrowsers = config.MAX_BROWSERS;
    this.browserTimeout = config.BROWSER_TIMEOUT;
    
    this.browsers = [];
    this.activeSessions = new Map(); // sessionId -> BrowserSession
    
    this.cleanupTask = null;
    this.startTime = new Date();
    
    // Browser type mapping
    this.browserTypes = {
      chromium,
      firefox,
      webkit
    };
    
    logger.info('Browser pool initialized', {
      maxBrowsers: this.maxBrowsers,
      browserTimeout: this.browserTimeout,
      browserType: config.BROWSER_TYPE
    });
  }

  async start() {
    logger.info('Starting browser pool...');
    
    // Validate browser type
    if (!this.browserTypes[config.BROWSER_TYPE]) {
      throw new Error(`Unsupported browser type: ${config.BROWSER_TYPE}`);
    }

    // Launch initial browsers
    for (let i = 0; i < this.maxBrowsers; i++) {
      await this._launchBrowser();
    }

    // Start cleanup task
    this.cleanupTask = setInterval(
      () => this._cleanupExpiredSessions(), 
      config.SESSION_CLEANUP_INTERVAL * 1000
    );

    logger.info(`Browser pool started with ${this.browsers.length} browsers`);
  }

  async stop() {
    logger.info('Stopping browser pool...');

    // Cancel cleanup task
    if (this.cleanupTask) {
      clearInterval(this.cleanupTask);
      this.cleanupTask = null;
    }

    // Close all active sessions
    const sessionPromises = [];
    for (const session of this.activeSessions.values()) {
      sessionPromises.push(session.close());
    }
    await Promise.allSettled(sessionPromises);
    this.activeSessions.clear();

    // Close all browsers
    const browserPromises = this.browsers.map(async (browser) => {
      try {
        await browser.close();
      } catch (error) {
        logger.warn('Error closing browser:', error);
      }
    });
    await Promise.allSettled(browserPromises);
    this.browsers = [];

    logger.info('Browser pool stopped');
  }

  isReady() {
    return (
      this.browsers.length > 0 &&
      this.activeSessions.size < this.maxBrowsers
    );
  }

  availableCount() {
    return Math.max(0, this.maxBrowsers - this.activeSessions.size);
  }

  async _launchBrowser() {
    const browserType = this.browserTypes[config.BROWSER_TYPE];
    const args = config.getBrowserArgs();

    try {
      const browser = await browserType.launch({
        headless: config.HEADLESS,
        args
      });

      this.browsers.push(browser);
      
      // Set up browser error handling
      browser.on('disconnected', () => {
        logger.warn('Browser disconnected, removing from pool');
        const index = this.browsers.indexOf(browser);
        if (index > -1) {
          this.browsers.splice(index, 1);
        }
      });

      return browser;
    } catch (error) {
      logger.error('Failed to launch browser:', error);
      throw error;
    }
  }

  async createSession(userId = null, metadata = {}) {
    if (this.activeSessions.size >= this.maxBrowsers) {
      throw new Error('Browser pool at capacity');
    }

    // Get an available browser (or launch new one)
    if (this.browsers.length === 0) {
      await this._launchBrowser();
    }

    const browser = this.browsers[0]; // Simple round-robin for now

    try {
      // Create new context
      const context = await browser.newContext({
        viewport: {
          width: config.VIEWPORT_WIDTH,
          height: config.VIEWPORT_HEIGHT
        },
        userAgent: config.USER_AGENT
      });

      // Create session
      const sessionId = uuidv4();
      const session = new BrowserSession(sessionId, context, new Date());

      if (metadata) {
        for (const [key, value] of Object.entries(metadata)) {
          session.metadata.set(key, value);
        }
      }
      if (userId) {
        session.metadata.set('user_id', userId);
      }

      this.activeSessions.set(sessionId, session);

      logger.info(`Created browser session ${sessionId}`, {
        userId,
        metadata,
        activeSessionCount: this.activeSessions.size
      });

      return sessionId;
    } catch (error) {
      logger.error('Failed to create browser session:', error);
      throw error;
    }
  }

  getSession(sessionId) {
    const session = this.activeSessions.get(sessionId);
    if (session) {
      session.lastActivity = new Date();
    }
    return session;
  }

  async closeSession(sessionId) {
    const session = this.activeSessions.get(sessionId);
    if (session) {
      await session.close();
      this.activeSessions.delete(sessionId);
      logger.info(`Closed browser session ${sessionId}`, {
        activeSessionCount: this.activeSessions.size
      });
      return true;
    }
    return false;
  }

  async createPage(sessionId, url = null) {
    const session = this.getSession(sessionId);
    if (!session) {
      throw new Error(`Session ${sessionId} not found`);
    }

    try {
      const page = await session.context.newPage();
      const pageId = session.addPage(page);

      if (url) {
        await page.goto(url, { 
          timeout: config.MAX_PAGE_LOAD_TIME * 1000,
          waitUntil: 'domcontentloaded'
        });
      }

      logger.debug(`Created page ${pageId} in session ${sessionId}`, { url });
      return pageId;
    } catch (error) {
      logger.error(`Error creating page in session ${sessionId}:`, error);
      throw error;
    }
  }

  getPage(sessionId, pageId) {
    const session = this.getSession(sessionId);
    return session ? session.getPage(pageId) : null;
  }

  async closePage(sessionId, pageId) {
    const session = this.getSession(sessionId);
    if (session) {
      const page = session.getPage(pageId);
      if (page) {
        try {
          await page.close();
          session.removePage(pageId);
          logger.debug(`Closed page ${pageId} in session ${sessionId}`);
          return true;
        } catch (error) {
          logger.error(`Error closing page ${pageId}:`, error);
        }
      }
    }
    return false;
  }

  async _cleanupExpiredSessions() {
    const now = new Date();
    const expiredSessions = [];

    for (const [sessionId, session] of this.activeSessions) {
      if (session.isExpired(this.browserTimeout)) {
        expiredSessions.push(sessionId);
      }
    }

    for (const sessionId of expiredSessions) {
      logger.info(`Cleaning up expired session ${sessionId}`);
      await this.closeSession(sessionId);
    }

    if (expiredSessions.length > 0) {
      logger.debug(`Cleaned up ${expiredSessions.length} expired sessions`);
    }
  }

  getStats() {
    const uptime = Math.floor((new Date() - this.startTime) / 1000);
    
    return {
      totalBrowsers: this.browsers.length,
      activeSessions: this.activeSessions.size,
      availableSlots: this.availableCount(),
      uptimeSeconds: uptime,
      sessionStats: Array.from(this.activeSessions.values()).map(session => session.getStats())
    };
  }

  getHealthStatus() {
    const stats = this.getStats();
    return {
      ready: this.isReady(),
      status: this.isReady() ? 'healthy' : 'degraded',
      ...stats
    };
  }
}