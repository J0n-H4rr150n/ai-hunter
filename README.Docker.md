# AI Hunter - Docker Setup

## Services

All services run on ports **33000-33999** to avoid conflicts.

| Service | Port | Description |
|---------|------|-------------|
| PostgreSQL 16 + pgvector | 33001 | Database with vector search |
| Redis | 33002 | Caching and real-time updates |
| Backend API | 33003 | FastAPI + WebSocket |
| Frontend Web UI | 33004 | Node.js + Vanilla JS + Tailwind |

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose installed
- GCP Application Default Credentials (run `gcloud auth application-default login`)

### 2. Start All Services

```bash
docker-compose up -d
```

### 3. Access the Web UI

Open your browser to: **http://localhost:33004**

### 4. Stop All Services

```bash
docker-compose down
```

To also remove volumes (database data):

```bash
docker-compose down -v
```

## Development

### View Logs

All services:
```bash
docker-compose logs -f
```

Specific service:
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f postgres
docker-compose logs -f redis
```

### Rebuild After Code Changes

```bash
docker-compose up -d --build
```

### Access Database

```bash
docker exec -it ai-hunter-postgres psql -U hunter -d ai_hunter
```

### Access Redis CLI

```bash
docker exec -it ai-hunter-redis redis-cli
```

## Architecture

```
┌─────────────┐
│  Frontend   │  Port 33004
│  (Node.js)  │  Vanilla JS + Tailwind
└──────┬──────┘
       │
       │ HTTP/WebSocket
       │
┌──────▼──────┐
│   Backend   │  Port 33003
│  (FastAPI)  │  Python + Gemini
└──┬────┬─────┘
   │    │
   │    └──────┐
   │           │
┌──▼──────┐ ┌─▼───────┐
│ Postgres│ │  Redis  │
│ +pgvector│ │         │
│ 33001   │ │  33002  │
└─────────┘ └─────────┘
```

## GCP Credentials

The backend mounts your ADC credentials from:
- **Windows**: `%APPDATA%\gcloud\application_default_credentials.json`
- **Linux/Mac**: `~/.config/gcloud/application_default_credentials.json`

Make sure you've run `gcloud auth application-default login` before starting.
