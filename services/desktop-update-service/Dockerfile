FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r updateservice && useradd -r -g updateservice updateservice

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .

# Set proper permissions
RUN chown -R updateservice:updateservice /app

# Switch to non-root user
USER updateservice

# Environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8002/health')" || exit 1

# Expose port
EXPOSE 8002

# Start the service
CMD ["python", "main.py"]