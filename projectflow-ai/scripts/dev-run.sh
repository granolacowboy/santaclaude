#!/bin/bash

# ProjectFlow AI Development Runner

set -e

echo "🚀 Starting ProjectFlow AI development environment..."

# Check if setup has been run
if [[ ! -f "backend/.env" ]]; then
    echo "❌ Please run scripts/dev-setup.sh first"
    exit 1
fi

# Start background services if not running
echo "📦 Ensuring services are running..."
docker compose up -d postgres redis rabbitmq

# Function to cleanup on exit
cleanup() {
    echo "🧹 Cleaning up..."
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
}

trap cleanup EXIT

# Start backend
echo "🐍 Starting backend server..."
cd backend
source venv/bin/activate
python main.py &
BACKEND_PID=$!

# Give backend time to start
sleep 3

# Start frontend
echo "🌐 Starting frontend server..."
cd ../frontend
npm run dev &
FRONTEND_PID=$!

# Wait for user to stop
echo ""
echo "✅ Development servers started!"
echo ""
echo "🌍 Access points:"
echo "  - Frontend: http://localhost:5173"
echo "  - Backend API: http://localhost:8000"
echo "  - API Docs: http://localhost:8000/docs"
echo ""
echo "👀 Logs will appear below. Press Ctrl+C to stop."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Wait for processes
wait