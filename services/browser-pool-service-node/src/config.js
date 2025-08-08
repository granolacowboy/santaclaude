import { readFileSync } from 'fs';

/**
 * Configuration management for Browser Pool Service
 */
export class Config {
  constructor() {
    // Server Configuration
    this.GRPC_PORT = parseInt(process.env.GRPC_PORT || '50051');
    this.WS_PORT = parseInt(process.env.WS_PORT || '8080');
    this.HOST = process.env.HOST || '0.0.0.0';
    
    // Browser Pool Configuration
    this.MAX_BROWSERS = parseInt(process.env.MAX_BROWSERS || '5');
    this.BROWSER_TIMEOUT = parseInt(process.env.BROWSER_TIMEOUT || '300'); // seconds
    this.SESSION_CLEANUP_INTERVAL = parseInt(process.env.SESSION_CLEANUP_INTERVAL || '60'); // seconds
    this.MAX_PAGE_LOAD_TIME = parseInt(process.env.MAX_PAGE_LOAD_TIME || '30'); // seconds
    
    // Browser Options
    this.BROWSER_TYPE = process.env.BROWSER_TYPE || 'chromium'; // chromium, firefox, webkit
    this.HEADLESS = process.env.HEADLESS !== 'false';
    this.ENABLE_SANDBOX = process.env.ENABLE_SANDBOX !== 'false';
    
    // Default Viewport
    this.VIEWPORT_WIDTH = parseInt(process.env.VIEWPORT_WIDTH || '1280');
    this.VIEWPORT_HEIGHT = parseInt(process.env.VIEWPORT_HEIGHT || '720');
    
    // Security & Resource Limits
    this.MAX_CONCURRENT_OPERATIONS = parseInt(process.env.MAX_CONCURRENT_OPERATIONS || '10');
    this.MEMORY_LIMIT_MB = parseInt(process.env.MEMORY_LIMIT_MB || '2048');
    this.CPU_LIMIT_PERCENT = parseInt(process.env.CPU_LIMIT_PERCENT || '80');
    
    // Default User Agent
    this.USER_AGENT = process.env.USER_AGENT || 
      'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';
      
    // Logging
    this.LOG_LEVEL = process.env.LOG_LEVEL || 'info';
    
    // Development
    this.DEBUG = process.env.NODE_ENV === 'development';
  }
  
  /**
   * Get browser launch arguments based on configuration
   */
  getBrowserArgs() {
    const args = [];
    
    if (!this.ENABLE_SANDBOX) {
      args.push('--no-sandbox', '--disable-setuid-sandbox');
    }
    
    // Memory and performance optimizations
    args.push(
      '--disable-dev-shm-usage',
      '--disable-background-timer-throttling',
      '--disable-backgrounding-occluded-windows',
      '--disable-renderer-backgrounding',
      `--max_old_space_size=${this.MEMORY_LIMIT_MB}`
    );
    
    // Additional security hardening
    if (!this.DEBUG) {
      args.push(
        '--disable-extensions',
        '--disable-plugins',
        '--disable-default-apps'
      );
    }
    
    return args;
  }
  
  /**
   * Validate configuration
   */
  validate() {
    const errors = [];
    
    if (this.MAX_BROWSERS < 1 || this.MAX_BROWSERS > 50) {
      errors.push('MAX_BROWSERS must be between 1 and 50');
    }
    
    if (this.BROWSER_TIMEOUT < 30) {
      errors.push('BROWSER_TIMEOUT must be at least 30 seconds');
    }
    
    if (this.VIEWPORT_WIDTH < 320 || this.VIEWPORT_HEIGHT < 240) {
      errors.push('Viewport dimensions too small (min 320x240)');
    }
    
    if (!['chromium', 'firefox', 'webkit'].includes(this.BROWSER_TYPE)) {
      errors.push('BROWSER_TYPE must be one of: chromium, firefox, webkit');
    }
    
    if (errors.length > 0) {
      throw new Error(`Configuration validation failed:\n${errors.join('\n')}`);
    }
  }
}

export const config = new Config();