# ProjectFlow AI (santaclaude)

An AI-augmented project workspace with Kanban-centric interface, per-card AI control, and safe automation capabilities.

## Architecture

- **Backend**: FastAPI with modular architecture
- **Frontend**: SvelteKit + Tailwind CSS  
- **Database**: PostgreSQL with PgVector
- **Queue**: RabbitMQ/NATS JetStream
- **Workers**: Python asyncio workers
- **Browser Pool**: Node.js + Playwright microservice

## Project Structure

```
projectflow-ai/
├── backend/           # FastAPI Python backend
│   ├── app/
│   │   ├── common/    # Shared DTOs, utils
│   │   ├── auth/      # OAuth/OIDC, sessions, RBAC
│   │   ├── rbac/      # Role/permission checks + RLS
│   │   ├── projects/  # Project lifecycle + membership
│   │   ├── kanban/    # Columns/cards, CRDT docs
│   │   ├── ai/        # Model routing, sessions
│   │   ├── automation/ # Site cloner + workflows
│   │   ├── audit/     # Append-only audit sink
│   │   └── observability/ # Tracing/metrics/logs
│   ├── contracts/     # JSON Schemas by module
│   └── migrations/    # Database migrations
├── frontend/          # SvelteKit frontend
├── browser-pool/      # Node.js Playwright service
├── workers/           # Async task workers
└── desktop/           # Tauri desktop app
```

## Development

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL 14+
- RabbitMQ or NATS

### Setup

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt

# Frontend  
cd frontend
npm install

# Start development
docker-compose up -d  # Database and message queue
python backend/main.py
npm run dev --prefix frontend
```

## Phase Implementation

- **Phase 1**: MVP with FastAPI + SvelteKit, basic auth and Kanban
- **Phase 2**: CRDT collaboration, message queue, security hardening  
- **Phase 3**: Browser automation, data-plane split, desktop app

See [Design Plan](../santaclaude-DESIGN-PLAN.md) for full specifications.