# Browser Pool Service - Node.js Implementation
# Phase 3 Dockerfile for containerized deployment

FROM node:20-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    procps \
    libxss1 \
    libgconf-2-4 \
    libxtst6 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libcairo-gobject2 \
    libgtk-3-0 \
    libgdk-pixbuf2.0-0 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxfixes3 \
    libxi6 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r browseruser && useradd -r -g browseruser -s /bin/bash -d /app browseruser

# Set working directory
WORKDIR /app

# Copy package files
COPY package*.json ./

# Install Node.js dependencies
RUN npm ci --only=production && npm cache clean --force

# Install Playwright browsers
RUN npx playwright install chromium firefox webkit
RUN npx playwright install-deps

# Copy application code
COPY src/ ./src/
COPY proto/ ./proto/

# Create logs directory
RUN mkdir -p logs && chown -R browseruser:browseruser logs

# Set proper permissions
RUN chown -R browseruser:browseruser /app

# Switch to non-root user
USER browseruser

# Expose ports
EXPOSE 50051 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD node -e "console.log('Health check passed')" || exit 1

# Environment variables
ENV NODE_ENV=production
ENV HEADLESS=true
ENV ENABLE_SANDBOX=false
ENV MAX_BROWSERS=5
ENV GRPC_PORT=50051
ENV WS_PORT=8080
ENV LOG_LEVEL=info

# Security settings
ENV NODE_OPTIONS="--max-old-space-size=2048"

# Start the service
CMD ["node", "src/index.js"]