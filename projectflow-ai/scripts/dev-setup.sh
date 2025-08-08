#!/bin/bash

# ProjectFlow AI Development Setup Script

set -e

echo "🚀 Setting up ProjectFlow AI development environment..."

# Check if we're in the right directory
if [[ ! -f "docker-compose.yml" ]]; then
    echo "❌ Please run this script from the projectflow-ai root directory"
    exit 1
fi

# Start background services
echo "📦 Starting database and message queue services..."
docker compose up -d postgres redis rabbitmq

# Wait for services to be ready
echo "⏳ Waiting for services to start..."
sleep 10

# Check if services are healthy
echo "🔍 Checking service health..."
docker compose exec -T postgres pg_isready -U postgres || {
    echo "❌ PostgreSQL is not ready"
    exit 1
}

docker compose exec -T redis redis-cli ping || {
    echo "❌ Redis is not ready"
    exit 1
}

# Setup backend
echo "🐍 Setting up Python backend..."
cd backend

# Create virtual environment if it doesn't exist
if [[ ! -d "venv" ]]; then
    python -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [[ ! -f ".env" ]]; then
    echo "📝 Creating .env file from example..."
    cp .env.example .env
    echo "⚠️  Please update .env file with your API keys"
fi

# Initialize database
echo "🗄️  Setting up database..."
alembic upgrade head || {
    echo "📝 Creating initial migration..."
    alembic revision --autogenerate -m "Initial migration"
    alembic upgrade head
}

# Go back to root
cd ..

# Setup frontend
echo "🌐 Setting up SvelteKit frontend..."
cd frontend

# Install dependencies
npm install

# Go back to root
cd ..

echo "✅ Setup complete!"
echo ""
echo "🎯 To start development:"
echo "  1. Backend: cd backend && source venv/bin/activate && python main.py"
echo "  2. Frontend: cd frontend && npm run dev"
echo ""
echo "🌍 Access points:"
echo "  - Frontend: http://localhost:5173"
echo "  - Backend API: http://localhost:8000"
echo "  - API Docs: http://localhost:8000/docs"
echo "  - RabbitMQ Management: http://localhost:15672 (rabbitmq/rabbitmq)"
echo ""
echo "⚙️  Make sure to update backend/.env with your API keys!"