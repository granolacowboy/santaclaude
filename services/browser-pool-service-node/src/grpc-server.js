import grpc from '@grpc/grpc-js';
import protoLoader from '@grpc/proto-loader';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import logger from './logger.js';
import { config } from './config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * gRPC Service Implementation for Browser Pool
 */
export class BrowserPoolGrpcServer {
  constructor(browserPool) {
    this.browserPool = browserPool;
    this.server = new grpc.Server();
    this.setupProtoDefinition();
    this.registerServices();
  }

  setupProtoDefinition() {
    const PROTO_PATH = join(__dirname, '..', 'proto', 'browser_pool.proto');
    
    const packageDefinition = protoLoader.loadSync(PROTO_PATH, {
      keepCase: true,
      longs: String,
      enums: String,
      defaults: true,
      oneofs: true,
    });

    this.proto = grpc.loadPackageDefinition(packageDefinition).browser_pool;
  }

  registerServices() {
    this.server.addService(this.proto.BrowserPool.service, {
      // Session Management
      Acquire: this.acquire.bind(this),
      Release: this.release.bind(this),
      GetSession: this.getSession.bind(this),
      
      // Page Operations
      CreatePage: this.createPage.bind(this),
      NavigatePage: this.navigatePage.bind(this),
      ExecuteScript: this.executeScript.bind(this),
      ClosePage: this.closePage.bind(this),
      
      // Browser Actions
      Click: this.click.bind(this),
      Type: this.type.bind(this),
      Screenshot: this.screenshot.bind(this),
      GetContent: this.getContent.bind(this),
      
      // Pool Management
      GetStats: this.getStats.bind(this),
      HealthCheck: this.healthCheck.bind(this),
    });
  }

  // Session Management
  async acquire(call, callback) {
    try {
      const { user_id, options, metadata } = call.request;
      
      const sessionId = await this.browserPool.createSession(
        user_id || null, 
        metadata || {}
      );
      
      callback(null, { session_id: sessionId });
      
      logger.debug(`gRPC: Acquired session ${sessionId}`, { user_id });
    } catch (error) {
      logger.error('gRPC: Failed to acquire session:', error);
      callback({
        code: grpc.status.RESOURCE_EXHAUSTED,
        message: error.message
      });
    }
  }

  async release(call, callback) {
    try {
      const { session_id } = call.request;
      const success = await this.browserPool.closeSession(session_id);
      
      callback(null, { 
        success, 
        message: success ? 'Session released' : 'Session not found' 
      });
      
      logger.debug(`gRPC: Released session ${session_id}`, { success });
    } catch (error) {
      logger.error('gRPC: Failed to release session:', error);
      callback({
        code: grpc.status.INTERNAL,
        message: error.message
      });
    }
  }

  async getSession(call, callback) {
    try {
      const { session_id } = call.request;
      const session = this.browserPool.getSession(session_id);
      
      if (!session) {
        callback({
          code: grpc.status.NOT_FOUND,
          message: 'Session not found'
        });
        return;
      }

      const sessionInfo = {
        session_id: session.sessionId,
        created_at: session.createdAt.toISOString(),
        last_activity: session.lastActivity.toISOString(),
        page_ids: Array.from(session.pages.keys()),
        metadata: Object.fromEntries(session.metadata)
      };

      callback(null, sessionInfo);
    } catch (error) {
      logger.error('gRPC: Failed to get session:', error);
      callback({
        code: grpc.status.INTERNAL,
        message: error.message
      });
    }
  }

  // Page Operations
  async createPage(call, callback) {
    try {
      const { session_id, url, timeout_ms } = call.request;
      const pageId = await this.browserPool.createPage(session_id, url);
      
      callback(null, { 
        session_id, 
        page_id: pageId 
      });
      
      logger.debug(`gRPC: Created page ${pageId} in session ${session_id}`, { url });
    } catch (error) {
      logger.error('gRPC: Failed to create page:', error);
      callback({
        code: grpc.status.INTERNAL,
        message: error.message
      });
    }
  }

  async navigatePage(call, callback) {
    try {
      const { session_id, page_id, url, timeout_ms } = call.request;
      const page = this.browserPool.getPage(session_id, page_id);
      
      if (!page) {
        callback({
          code: grpc.status.NOT_FOUND,
          message: 'Page not found'
        });
        return;
      }

      const response = await page.goto(url, { 
        timeout: timeout_ms || config.MAX_PAGE_LOAD_TIME * 1000,
        waitUntil: 'domcontentloaded'
      });

      const title = await page.title();
      
      callback(null, {
        success: true,
        final_url: response.url(),
        title,
        error: ''
      });
      
      logger.debug(`gRPC: Navigated page ${page_id} to ${url}`, { session_id, title });
    } catch (error) {
      logger.error('gRPC: Failed to navigate page:', error);
      callback(null, {
        success: false,
        final_url: '',
        title: '',
        error: error.message
      });
    }
  }

  async executeScript(call, callback) {
    try {
      const { session_id, page_id, script, args } = call.request;
      const page = this.browserPool.getPage(session_id, page_id);
      
      if (!page) {
        callback({
          code: grpc.status.NOT_FOUND,
          message: 'Page not found'
        });
        return;
      }

      // Execute script with arguments
      const result = await page.evaluate(
        new Function('args', script), 
        args || []
      );

      callback(null, {
        success: true,
        result: JSON.stringify(result),
        error: ''
      });
      
      logger.debug(`gRPC: Executed script in page ${page_id}`, { session_id });
    } catch (error) {
      logger.error('gRPC: Failed to execute script:', error);
      callback(null, {
        success: false,
        result: '',
        error: error.message
      });
    }
  }

  async closePage(call, callback) {
    try {
      const { session_id, page_id } = call.request;
      const success = await this.browserPool.closePage(session_id, page_id);
      
      callback(null, { 
        success, 
        message: success ? 'Page closed' : 'Page not found' 
      });
      
      logger.debug(`gRPC: Closed page ${page_id} in session ${session_id}`, { success });
    } catch (error) {
      logger.error('gRPC: Failed to close page:', error);
      callback({
        code: grpc.status.INTERNAL,
        message: error.message
      });
    }
  }

  // Browser Actions
  async click(call, callback) {
    try {
      const { session_id, page_id, selector, timeout_ms } = call.request;
      const page = this.browserPool.getPage(session_id, page_id);
      
      if (!page) {
        callback({
          code: grpc.status.NOT_FOUND,
          message: 'Page not found'
        });
        return;
      }

      await page.click(selector, { 
        timeout: timeout_ms || 30000 
      });
      
      callback(null, { 
        success: true, 
        message: 'Click executed' 
      });
      
      logger.debug(`gRPC: Clicked ${selector} in page ${page_id}`, { session_id });
    } catch (error) {
      logger.error('gRPC: Failed to click:', error);
      callback(null, {
        success: false,
        message: error.message
      });
    }
  }

  async type(call, callback) {
    try {
      const { session_id, page_id, selector, text, timeout_ms } = call.request;
      const page = this.browserPool.getPage(session_id, page_id);
      
      if (!page) {
        callback({
          code: grpc.status.NOT_FOUND,
          message: 'Page not found'
        });
        return;
      }

      await page.fill(selector, text, { 
        timeout: timeout_ms || 30000 
      });
      
      callback(null, { 
        success: true, 
        message: 'Text typed' 
      });
      
      logger.debug(`gRPC: Typed text into ${selector} in page ${page_id}`, { session_id });
    } catch (error) {
      logger.error('gRPC: Failed to type:', error);
      callback(null, {
        success: false,
        message: error.message
      });
    }
  }

  async screenshot(call, callback) {
    try {
      const { session_id, page_id, full_page, format } = call.request;
      const page = this.browserPool.getPage(session_id, page_id);
      
      if (!page) {
        callback({
          code: grpc.status.NOT_FOUND,
          message: 'Page not found'
        });
        return;
      }

      const imageData = await page.screenshot({
        fullPage: full_page || false,
        type: format || 'png'
      });
      
      callback(null, {
        success: true,
        image_data: imageData,
        error: ''
      });
      
      logger.debug(`gRPC: Took screenshot of page ${page_id}`, { session_id, full_page, format });
    } catch (error) {
      logger.error('gRPC: Failed to take screenshot:', error);
      callback(null, {
        success: false,
        image_data: Buffer.alloc(0),
        error: error.message
      });
    }
  }

  async getContent(call, callback) {
    try {
      const { session_id, page_id, content_type } = call.request;
      const page = this.browserPool.getPage(session_id, page_id);
      
      if (!page) {
        callback({
          code: grpc.status.NOT_FOUND,
          message: 'Page not found'
        });
        return;
      }

      let content;
      switch (content_type) {
        case 'html':
          content = await page.content();
          break;
        case 'text':
          content = await page.innerText('body');
          break;
        case 'pdf':
          const pdfBuffer = await page.pdf();
          content = pdfBuffer.toString('base64');
          break;
        default:
          content = await page.content();
      }
      
      callback(null, {
        success: true,
        content,
        error: ''
      });
      
      logger.debug(`gRPC: Got ${content_type} content from page ${page_id}`, { session_id });
    } catch (error) {
      logger.error('gRPC: Failed to get content:', error);
      callback(null, {
        success: false,
        content: '',
        error: error.message
      });
    }
  }

  // Pool Management
  async getStats(call, callback) {
    try {
      const stats = this.browserPool.getStats();
      
      callback(null, {
        total_browsers: stats.totalBrowsers,
        active_sessions: stats.activeSessions,
        available_slots: stats.availableSlots,
        session_stats: stats.sessionStats.map(stat => ({
          session_id: stat.sessionId,
          created_at: stat.createdAt,
          last_activity: stat.lastActivity,
          page_count: stat.pageCount,
          metadata: stat.metadata
        }))
      });
    } catch (error) {
      logger.error('gRPC: Failed to get stats:', error);
      callback({
        code: grpc.status.INTERNAL,
        message: error.message
      });
    }
  }

  async healthCheck(call, callback) {
    try {
      const health = this.browserPool.getHealthStatus();
      
      callback(null, {
        ready: health.ready,
        status: health.status,
        uptime_seconds: health.uptimeSeconds
      });
    } catch (error) {
      logger.error('gRPC: Failed to check health:', error);
      callback({
        code: grpc.status.INTERNAL,
        message: error.message
      });
    }
  }

  async start() {
    return new Promise((resolve, reject) => {
      const address = `${config.HOST}:${config.GRPC_PORT}`;
      
      this.server.bindAsync(
        address,
        grpc.ServerCredentials.createInsecure(),
        (error, port) => {
          if (error) {
            reject(error);
            return;
          }
          
          this.server.start();
          logger.info(`gRPC server started on ${address}`);
          resolve(port);
        }
      );
    });
  }

  async stop() {
    return new Promise((resolve) => {
      this.server.tryShutdown((error) => {
        if (error) {
          logger.warn('gRPC server shutdown with error:', error);
        } else {
          logger.info('gRPC server stopped gracefully');
        }
        resolve();
      });
    });
  }
}