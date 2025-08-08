import { WebSocketServer } from 'ws';
import { createServer } from 'http';
import logger from './logger.js';
import { config } from './config.js';

/**
 * WebSocket Server for Browser Pool real-time communication
 * Provides streaming updates and real-time control interface
 */
export class BrowserPoolWebSocketServer {
  constructor(browserPool) {
    this.browserPool = browserPool;
    this.clients = new Map(); // clientId -> { ws, subscriptions }
    this.server = null;
    this.wss = null;
  }

  async start() {
    this.server = createServer();
    this.wss = new WebSocketServer({ server: this.server });

    this.wss.on('connection', this.handleConnection.bind(this));

    return new Promise((resolve, reject) => {
      const address = config.HOST;
      const port = config.WS_PORT;

      this.server.listen(port, address, (error) => {
        if (error) {
          reject(error);
        } else {
          logger.info(`WebSocket server started on ws://${address}:${port}`);
          resolve(port);
        }
      });
    });
  }

  async stop() {
    return new Promise((resolve) => {
      // Close all client connections
      for (const [clientId, client] of this.clients) {
        try {
          client.ws.close(1012, 'Server shutting down');
        } catch (error) {
          logger.warn(`Error closing client ${clientId}:`, error);
        }
      }
      this.clients.clear();

      // Close WebSocket server
      if (this.wss) {
        this.wss.close();
      }

      // Close HTTP server
      if (this.server) {
        this.server.close(() => {
          logger.info('WebSocket server stopped');
          resolve();
        });
      } else {
        resolve();
      }
    });
  }

  handleConnection(ws, request) {
    const clientId = this.generateClientId();
    const client = {
      ws,
      subscriptions: new Set(),
      lastPing: Date.now(),
      metadata: {}
    };

    this.clients.set(clientId, client);

    logger.info(`WebSocket client connected: ${clientId}`, {
      origin: request.headers.origin,
      userAgent: request.headers['user-agent']
    });

    // Set up message handling
    ws.on('message', (data) => this.handleMessage(clientId, data));
    ws.on('close', (code, reason) => this.handleDisconnection(clientId, code, reason));
    ws.on('error', (error) => this.handleError(clientId, error));

    // Send welcome message
    this.sendMessage(clientId, {
      type: 'connection',
      payload: {
        clientId,
        serverTime: new Date().toISOString(),
        capabilities: ['browser-control', 'real-time-updates', 'session-management']
      }
    });

    // Set up heartbeat
    this.setupHeartbeat(clientId);
  }

  handleMessage(clientId, rawData) {
    const client = this.clients.get(clientId);
    if (!client) return;

    try {
      const message = JSON.parse(rawData.toString());
      logger.debug(`WebSocket message from ${clientId}:`, { type: message.type });

      switch (message.type) {
        case 'ping':
          this.handlePing(clientId);
          break;
        case 'subscribe':
          this.handleSubscribe(clientId, message.payload);
          break;
        case 'unsubscribe':
          this.handleUnsubscribe(clientId, message.payload);
          break;
        case 'browser-action':
          this.handleBrowserAction(clientId, message.payload);
          break;
        case 'get-stats':
          this.handleGetStats(clientId);
          break;
        default:
          this.sendError(clientId, `Unknown message type: ${message.type}`);
      }
    } catch (error) {
      logger.warn(`Invalid WebSocket message from ${clientId}:`, error);
      this.sendError(clientId, 'Invalid message format');
    }
  }

  handleDisconnection(clientId, code, reason) {
    const client = this.clients.get(clientId);
    if (client) {
      this.clients.delete(clientId);
      logger.info(`WebSocket client disconnected: ${clientId}`, { code, reason: reason.toString() });
    }
  }

  handleError(clientId, error) {
    logger.error(`WebSocket error for client ${clientId}:`, error);
  }

  handlePing(clientId) {
    const client = this.clients.get(clientId);
    if (client) {
      client.lastPing = Date.now();
      this.sendMessage(clientId, { type: 'pong', payload: { timestamp: Date.now() } });
    }
  }

  handleSubscribe(clientId, payload) {
    const client = this.clients.get(clientId);
    if (!client) return;

    const { topics } = payload;
    if (!Array.isArray(topics)) {
      this.sendError(clientId, 'Topics must be an array');
      return;
    }

    for (const topic of topics) {
      client.subscriptions.add(topic);
    }

    this.sendMessage(clientId, {
      type: 'subscribed',
      payload: {
        topics,
        totalSubscriptions: client.subscriptions.size
      }
    });

    logger.debug(`Client ${clientId} subscribed to topics:`, topics);
  }

  handleUnsubscribe(clientId, payload) {
    const client = this.clients.get(clientId);
    if (!client) return;

    const { topics } = payload;
    if (!Array.isArray(topics)) {
      this.sendError(clientId, 'Topics must be an array');
      return;
    }

    for (const topic of topics) {
      client.subscriptions.delete(topic);
    }

    this.sendMessage(clientId, {
      type: 'unsubscribed',
      payload: {
        topics,
        totalSubscriptions: client.subscriptions.size
      }
    });

    logger.debug(`Client ${clientId} unsubscribed from topics:`, topics);
  }

  async handleBrowserAction(clientId, payload) {
    try {
      const { action, sessionId, pageId, ...params } = payload;

      let result;
      switch (action) {
        case 'create-session':
          result = await this.browserPool.createSession(params.userId, params.metadata);
          break;
        case 'create-page':
          result = await this.browserPool.createPage(sessionId, params.url);
          break;
        case 'navigate':
          const page = this.browserPool.getPage(sessionId, pageId);
          if (page) {
            await page.goto(params.url, { waitUntil: 'domcontentloaded' });
            result = { success: true };
          } else {
            throw new Error('Page not found');
          }
          break;
        case 'click':
          const clickPage = this.browserPool.getPage(sessionId, pageId);
          if (clickPage) {
            await clickPage.click(params.selector);
            result = { success: true };
          } else {
            throw new Error('Page not found');
          }
          break;
        case 'type':
          const typePage = this.browserPool.getPage(sessionId, pageId);
          if (typePage) {
            await typePage.fill(params.selector, params.text);
            result = { success: true };
          } else {
            throw new Error('Page not found');
          }
          break;
        default:
          throw new Error(`Unknown browser action: ${action}`);
      }

      this.sendMessage(clientId, {
        type: 'browser-action-result',
        payload: {
          action,
          sessionId,
          pageId,
          result,
          success: true
        }
      });

      // Broadcast action to subscribers
      this.broadcast(`browser.${action}`, {
        clientId,
        sessionId,
        pageId,
        action,
        timestamp: new Date().toISOString()
      });

    } catch (error) {
      logger.error(`Browser action failed for client ${clientId}:`, error);
      this.sendMessage(clientId, {
        type: 'browser-action-result',
        payload: {
          action: payload.action,
          error: error.message,
          success: false
        }
      });
    }
  }

  handleGetStats(clientId) {
    const stats = this.browserPool.getStats();
    this.sendMessage(clientId, {
      type: 'stats',
      payload: stats
    });
  }

  sendMessage(clientId, message) {
    const client = this.clients.get(clientId);
    if (client && client.ws.readyState === client.ws.OPEN) {
      try {
        client.ws.send(JSON.stringify(message));
      } catch (error) {
        logger.warn(`Failed to send message to client ${clientId}:`, error);
      }
    }
  }

  sendError(clientId, errorMessage) {
    this.sendMessage(clientId, {
      type: 'error',
      payload: { message: errorMessage }
    });
  }

  broadcast(topic, payload) {
    const message = {
      type: 'broadcast',
      topic,
      payload,
      timestamp: new Date().toISOString()
    };

    let sentCount = 0;
    for (const [clientId, client] of this.clients) {
      if (client.subscriptions.has(topic) || client.subscriptions.has('*')) {
        this.sendMessage(clientId, message);
        sentCount++;
      }
    }

    logger.debug(`Broadcasted message to ${sentCount} subscribers`, { topic });
  }

  setupHeartbeat(clientId) {
    const heartbeatInterval = setInterval(() => {
      const client = this.clients.get(clientId);
      if (!client) {
        clearInterval(heartbeatInterval);
        return;
      }

      const now = Date.now();
      const timeSinceLastPing = now - client.lastPing;

      // Check if client is still responsive (60 seconds timeout)
      if (timeSinceLastPing > 60000) {
        logger.warn(`Client ${clientId} not responding, closing connection`);
        client.ws.close(1001, 'No heartbeat response');
        clearInterval(heartbeatInterval);
      } else {
        // Send heartbeat every 25 seconds
        this.sendMessage(clientId, { type: 'heartbeat', payload: { timestamp: now } });
      }
    }, 25000);
  }

  generateClientId() {
    return `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  // Public methods for broadcasting events
  broadcastSessionCreated(sessionId, metadata = {}) {
    this.broadcast('session.created', { sessionId, metadata });
  }

  broadcastSessionClosed(sessionId) {
    this.broadcast('session.closed', { sessionId });
  }

  broadcastPageCreated(sessionId, pageId, url) {
    this.broadcast('page.created', { sessionId, pageId, url });
  }

  broadcastPageClosed(sessionId, pageId) {
    this.broadcast('page.closed', { sessionId, pageId });
  }

  getConnectedClients() {
    return {
      total: this.clients.size,
      clients: Array.from(this.clients.entries()).map(([clientId, client]) => ({
        clientId,
        subscriptions: Array.from(client.subscriptions),
        lastPing: client.lastPing,
        metadata: client.metadata
      }))
    };
  }
}