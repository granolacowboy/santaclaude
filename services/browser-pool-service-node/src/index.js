#!/usr/bin/env node

import { BrowserPool } from './browser-pool.js';
import { BrowserPoolGrpcServer } from './grpc-server.js';
import { BrowserPoolWebSocketServer } from './websocket-server.js';
import { config } from './config.js';
import logger from './logger.js';

/**
 * Main Entry Point for Browser Pool Service
 * Phase 3 - Node.js Microservice Implementation
 */
class BrowserPoolService {
  constructor() {
    this.browserPool = null;
    this.grpcServer = null;
    this.wsServer = null;
    this.shutdownInProgress = false;
  }

  async start() {
    try {
      logger.info('Starting Browser Pool Service (Node.js)...', {
        version: '1.0.0',
        nodeVersion: process.version,
        config: {
          maxBrowsers: config.MAX_BROWSERS,
          browserType: config.BROWSER_TYPE,
          headless: config.HEADLESS,
          grpcPort: config.GRPC_PORT,
          wsPort: config.WS_PORT
        }
      });

      // Validate configuration
      config.validate();

      // Initialize browser pool
      this.browserPool = new BrowserPool();
      await this.browserPool.start();

      // Start gRPC server
      this.grpcServer = new BrowserPoolGrpcServer(this.browserPool);
      await this.grpcServer.start();

      // Start WebSocket server
      this.wsServer = new BrowserPoolWebSocketServer(this.browserPool);
      await this.wsServer.start();

      // Wire up event broadcasting from browser pool to WebSocket
      this.setupEventBroadcasting();

      logger.info('Browser Pool Service started successfully', {
        grpcPort: config.GRPC_PORT,
        wsPort: config.WS_PORT,
        browserCount: this.browserPool.browsers.length
      });

      // Set up graceful shutdown
      this.setupGracefulShutdown();

      // Health monitoring
      this.startHealthMonitoring();

    } catch (error) {
      logger.error('Failed to start Browser Pool Service:', error);
      await this.shutdown();
      process.exit(1);
    }
  }

  async shutdown() {
    if (this.shutdownInProgress) {
      return;
    }

    this.shutdownInProgress = true;
    logger.info('Shutting down Browser Pool Service...');

    const shutdownPromises = [];

    // Stop WebSocket server
    if (this.wsServer) {
      shutdownPromises.push(
        this.wsServer.stop().catch(error => 
          logger.warn('Error stopping WebSocket server:', error)
        )
      );
    }

    // Stop gRPC server
    if (this.grpcServer) {
      shutdownPromises.push(
        this.grpcServer.stop().catch(error => 
          logger.warn('Error stopping gRPC server:', error)
        )
      );
    }

    // Stop browser pool
    if (this.browserPool) {
      shutdownPromises.push(
        this.browserPool.stop().catch(error => 
          logger.warn('Error stopping browser pool:', error)
        )
      );
    }

    await Promise.allSettled(shutdownPromises);
    logger.info('Browser Pool Service shutdown complete');
  }

  setupEventBroadcasting() {
    // This would typically be done with event emitters or observers
    // For now, we'll manually wire up key events

    // Intercept browser pool methods to trigger WebSocket broadcasts
    const originalCreateSession = this.browserPool.createSession.bind(this.browserPool);
    this.browserPool.createSession = async (...args) => {
      const sessionId = await originalCreateSession(...args);
      this.wsServer.broadcastSessionCreated(sessionId, args[1] || {});
      return sessionId;
    };

    const originalCloseSession = this.browserPool.closeSession.bind(this.browserPool);
    this.browserPool.closeSession = async (sessionId) => {
      const result = await originalCloseSession(sessionId);
      if (result) {
        this.wsServer.broadcastSessionClosed(sessionId);
      }
      return result;
    };

    const originalCreatePage = this.browserPool.createPage.bind(this.browserPool);
    this.browserPool.createPage = async (sessionId, url) => {
      const pageId = await originalCreatePage(sessionId, url);
      this.wsServer.broadcastPageCreated(sessionId, pageId, url);
      return pageId;
    };

    const originalClosePage = this.browserPool.closePage.bind(this.browserPool);
    this.browserPool.closePage = async (sessionId, pageId) => {
      const result = await originalClosePage(sessionId, pageId);
      if (result) {
        this.wsServer.broadcastPageClosed(sessionId, pageId);
      }
      return result;
    };
  }

  setupGracefulShutdown() {
    const signals = ['SIGTERM', 'SIGINT', 'SIGUSR2'];
    
    signals.forEach(signal => {
      process.on(signal, async () => {
        logger.info(`Received ${signal}, initiating graceful shutdown...`);
        await this.shutdown();
        process.exit(0);
      });
    });

    // Handle uncaught exceptions
    process.on('uncaughtException', async (error) => {
      logger.error('Uncaught exception:', error);
      await this.shutdown();
      process.exit(1);
    });

    // Handle unhandled rejections
    process.on('unhandledRejection', async (reason, promise) => {
      logger.error('Unhandled rejection at:', promise, 'reason:', reason);
      await this.shutdown();
      process.exit(1);
    });
  }

  startHealthMonitoring() {
    // Periodically log health metrics
    setInterval(() => {
      if (this.browserPool) {
        const stats = this.browserPool.getStats();
        const wsClients = this.wsServer.getConnectedClients();
        
        logger.info('Health check', {
          browserPool: {
            totalBrowsers: stats.totalBrowsers,
            activeSessions: stats.activeSessions,
            availableSlots: stats.availableSlots,
            uptimeSeconds: stats.uptimeSeconds
          },
          websocket: {
            connectedClients: wsClients.total
          },
          memory: {
            heapUsed: Math.round(process.memoryUsage().heapUsed / 1024 / 1024) + 'MB',
            heapTotal: Math.round(process.memoryUsage().heapTotal / 1024 / 1024) + 'MB'
          }
        });
      }
    }, 60000); // Every minute
  }
}

// Start the service
const service = new BrowserPoolService();
service.start().catch(error => {
  logger.error('Failed to start service:', error);
  process.exit(1);
});