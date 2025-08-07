# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Santaclaude** is a collection of AI-augmented development tools and utilities focused on enhancing Claude Code workflows. The repository contains multiple independent projects, each serving specific development needs:

- **vibe-kanban**: AI coding agent orchestration platform with task management
- **claude-code-router**: Routes Claude Code requests to different LLM providers  
- **claude-code-webui**: Web interface for Claude Code with history management
- **claude-auto-resume**: Shell script to automatically resume Claude sessions after usage limits
- **claude-squad**: Terminal UI for managing multiple Claude sessions
- **claudecodeui**: Progressive web app interface for Claude Code
- **context7**: Smart context selector for development files
- **claude-desktop-debian**: Debian packaging for Claude desktop

## Development Commands by Project

### vibe-kanban (Main Project)
```bash
# Development - run both frontend and backend with live reload
pnpm run dev

# Type checking and validation - ALWAYS run before committing
pnpm run check

# Generate TypeScript types from Rust structs (after modifying Rust types)
pnpm run generate-types

# Backend only
pnpm run backend:dev

# Frontend only  
pnpm run frontend:dev

# Build production package
./build-npm-package.sh

# Rust commands (from backend directory)
cargo test
cargo fmt
cargo clippy
```

### claude-code-router
```bash
# Build project
npm run build

# Start router server
ccr start

# Run Claude Code through router
ccr code "<your prompt>"

# Stop server
ccr stop
```

### claude-code-webui
```bash
# Development (backend)
npm run dev
npm run build

# Frontend development
cd frontend && npm run dev
```

### claude-auto-resume
```bash
# Install globally
sudo make install

# Test script syntax
make test

# Run directly
./claude-auto-resume.sh
```

### claude-squad
```bash
# Build Go binary
go build

# Install
./install.sh

# Clean build
./clean.sh
```

## Architecture Overview

### vibe-kanban Architecture
- **Backend**: Rust with Axum web framework, SQLite + SQLX, Tokio async runtime
- **Frontend**: React 18 + TypeScript, Vite, Tailwind CSS, Radix UI
- **Type Sharing**: Rust types exported to TypeScript via `ts-rs`
- **Executor System**: Multiple AI agent integrations (Claude Code, Gemini CLI, Amp, etc.)
- **Database**: SQLite with comprehensive schema for projects, tasks, processes
- **API**: RESTful endpoints with WebSocket streaming for real-time updates

### claude-code-router Architecture
- **Entry Point**: TypeScript CLI in `src/cli.ts`
- **Configuration**: JSON config at `~/.claude-code-router/config.json`
- **Routing**: Custom routing logic with provider/transformer support
- **Dependencies**: Built on Fastify with `@musistudio/llms` for LLM interactions

### claude-code-webui Architecture  
- **Backend**: Node.js/TypeScript with conversation management
- **Frontend**: React with chat interface and project management
- **Features**: History loading, conversation grouping, mobile-responsive

## Key Development Guidelines

### Type Management (vibe-kanban)
1. Always regenerate types after modifying Rust structs: `pnpm run generate-types`
2. Backend-first development: Define data structures in Rust, export to frontend
3. Use `#[derive(Serialize, Deserialize, PartialEq, Debug, Clone, TS)]` for shared types

### Code Style
- **Rust**: Use rustfmt, snake_case naming, leverage tokio for async operations
- **TypeScript**: Strict mode enabled, use `@/` path aliases for imports
- **React**: Functional components with hooks

### Testing Strategy
- Run `pnpm run check` to validate both Rust and TypeScript code (vibe-kanban)
- Use `cargo test` for backend unit tests
- Focus on component integration for frontend testing

## Project-Specific Features

### vibe-kanban Key Features
- **Executor System**: Each AI agent implemented as executor in `/backend/src/executors/`
- **Git Integration**: Automatic branch creation, worktree management, PR creation
- **Process Execution**: Managed processes with streaming logs and lifecycle management
- **MCP Server**: Built-in Model Context Protocol server for task management tools
- **Real-time Updates**: WebSocket connections for task status and git operations

### claude-code-router Key Features
- **Multi-Provider Support**: Route requests to different LLM providers
- **Custom Transformers**: Adapt request/response formats for different APIs
- **Automatic Service Management**: Auto-start router service when needed

### claude-auto-resume Key Features
- **Automatic Resumption**: Monitors Claude usage limits and auto-resumes tasks
- **Cross-Platform**: Handles Linux/macOS date command differences
- **Security Note**: Uses `--dangerously-skip-permissions` flag - use in trusted environments only

## Environment Configuration

### vibe-kanban
- Backend runs on port 3001, frontend on port 3000
- GitHub OAuth requires `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`
- Optional PostHog analytics integration
- Rust nightly toolchain required (version 2025-05-18 or later)

### claude-code-router
- Configuration via `~/.claude-code-router/config.json`
- Supports multiple provider configurations
- Custom router scripts for advanced routing logic

## Project Context

This repository represents the "santaclaude" project collection - a comprehensive suite of AI-augmented development tools. The projects range from sophisticated multi-agent orchestration platforms to simple utility scripts, all designed to enhance the Claude Code development experience.

The main documentation files (`santaclaude-DESIGN-PLAN.md`, project plans) describe a broader vision for an integrated AI project workspace, but the current implementation focuses on modular, independent tools that can be used together or separately.