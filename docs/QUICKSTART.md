# 🐝 AI Hunter - Quick Start Guide

Get up and running with AI Hunter in 5 minutes.

## Prerequisites

- **Docker Desktop** (with Docker Compose v2+)
- **Google Cloud credentials** with Vertex AI API enabled
- **Port availability**: 33001-33004

## Setup Steps

### 1. Clone the Repository

```bash
git clone https://github.com/J0n-H4rr150n/ai-hunter.git
cd ai-hunter
```

### 2. Configure Google Cloud Credentials

AI Hunter uses Google Vertex AI for LLM capabilities. You need a service account key:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **Vertex AI API**
4. Create a service account with Vertex AI User role
5. Download the JSON key file
6. Save it as `gcp-credentials.json` in the project root

```bash
# Make sure the file is in the root directory
ls gcp-credentials.json  # Should exist
```

### 3. Review Configuration (Optional)

Check `config/config.py` for default settings:
- LLM model: Gemini 2.5 Pro Preview
- Browser: Headless Chromium
- Quotas: 100 LLM calls, 500 actions per mission

### 4. Start the Application

```bash
# Build and start all services
docker compose up --build -d

# Wait ~30 seconds for all services to be healthy
docker compose ps
```

You should see 4 containers running:
- `ai-hunter-backend` (FastAPI)
- `ai-hunter-frontend` (Nginx)
- `ai-hunter-postgres` (PostgreSQL with pgvector)
- `ai-hunter-redis` (Redis)

### 5. Access the Web UI

Open your browser to: **http://localhost:33004**

You should see the AI Hunter dashboard with:
- 🐝 AI Hunter header
- "New Mission" button
- Live Activity Feed
- Settings (⚙️) and Evidence (📂) buttons

## Running Your First Mission

### 1. Start a Test Target (Optional)

If you don't have a target, use the included test app:

```bash
cd test-target
python -m http.server 8080
```

Access it at: `http://localhost:8080`

### 2. Configure Settings

1. Click **⚙️ Settings** in the top right
2. Toggle **Human-in-the-Loop (HITL)** ON for manual approval
3. Select which tools to auto-approve (optional)
4. Click **Save Settings**

### 3. Launch a Mission

1. Click **+ New Mission**
2. Enter target URL: `http://localhost:8080` (or your target)
3. (Optional) Add instructions: `Focus on testing ID parameters. Don't create accounts.`
4. Click **Start Mission**

### 4. Approve the Plan

The AI will:
1. Scan the target
2. Generate an execution plan
3. Wait for your approval

Review the plan and click **✅ Approve Plan**

### 5. Monitor Execution

Watch the Live Activity Feed for:
- 🔍 Technology stack detection (expandable details)
- 📸 Screenshots at each step
- 🧪 Fuzzing results
- 📊 Findings analysis (expandable with all details)

### 6. Review Evidence

Click **📂 Evidence** to view:
- **Screenshots**: All captured images in a grid
- **Metadata**: JSON files with request/response data
- **Findings**: Discovered vulnerabilities and insights

## Architecture Overview

```
┌─────────────────┐
│   Web Browser   │ http://localhost:33004
└────────┬────────┘
         │
    ┌────▼─────┐
    │ Frontend │ (Nginx)
    │  :3000   │
    └────┬─────┘
         │
    ┌────▼──────┐      ┌──────────┐      ┌──────────┐
    │  Backend  │◄────►│PostgreSQL│      │  Redis   │
    │  FastAPI  │      │ pgvector │      │ Pub/Sub  │
    │   :8000   │      │  :5432   │      │  :6379   │
    └───────────┘      └──────────┘      └──────────┘
         │
         ▼
    ┌───────────────────────────────────┐
    │   Autonomous Agent Loop           │
    │  ┌─────────┐  ┌────────┐         │
    │  │ Planner │  │Browser │         │
    │  └─────────┘  └────────┘         │
    │  ┌─────────┐  ┌────────┐         │
    │  │ Scanner │  │ Fuzzer │         │
    │  └─────────┘  └────────┘         │
    └───────────────────────────────────┘
```

## Key Features

### 🤖 Autonomous Execution
- AI-driven mission planning with Gemini 2.5 Pro
- Adaptive testing based on discovered technologies
- Smart payload selection for fuzzing

### 🎯 Human-in-the-Loop (HITL)
- Manual approval for every tool execution
- Edit payloads before submission
- Provide feedback to train the AI
- Vector similarity search for past decisions

### 📊 Real-Time Visibility
- Live activity feed with SSE (Server-Sent Events)
- Collapsible sections for detailed output
- Technology stack identification
- Full findings analysis with samples

### 📸 Evidence Collection
- Screenshot capture at every step
- Request/response metadata
- Organized by mission and timestamp
- Downloadable artifacts

### 💾 State Management
- PostgreSQL-backed state snapshots
- Pause/resume missions (coming soon)
- Global, mission-scoped, and agent-private state

## Common Tasks

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail=100 backend
```

### Stop the Application

```bash
# Stop containers
docker compose down

# Stop and remove volumes (clean slate)
docker compose down -v
```

### Database Migrations

Migrations run automatically on startup. To run manually:

```bash
docker compose exec backend alembic upgrade head
```

### Access PostgreSQL

```bash
docker compose exec postgres psql -U hunter -d ai_hunter

# Useful queries
SELECT * FROM missions ORDER BY created_at DESC LIMIT 5;
SELECT * FROM tool_approvals ORDER BY created_at DESC LIMIT 10;
SELECT COUNT(*) FROM state_snapshots;
```

## Troubleshooting

### Port Already in Use

If ports 33001-33004 are taken, edit `docker-compose.yml`:

```yaml
ports:
  - "YOUR_PORT:8000"  # Change YOUR_PORT
```

### GCP Authentication Error

```
Error: Could not automatically determine credentials
```

**Solution**: Make sure `gcp-credentials.json` is in the project root and properly formatted.

### Container Won't Start

```bash
# Check logs
docker compose logs backend

# Rebuild without cache
docker compose build --no-cache
docker compose up -d
```

### No Screenshots Appearing

1. Check the Evidence modal (📂)
2. Verify screenshots are being saved:
   ```bash
   ls -la hive_bucket/screenshots/$(date +%Y-%m-%d)/
   ```
3. Check browser console for image loading errors

### Database Connection Failed

```bash
# Restart postgres
docker compose restart postgres

# Wait for healthy status
docker compose ps postgres
```

## Directory Structure

```
ai-hunter/
├── agents/                 # Agent brain and planner
├── alembic/               # Database migrations
├── backend/               # FastAPI server
├── config/                # Configuration
├── core/                  # Core execution loop
├── frontend/              # Web UI
├── hive_bucket/          # Evidence storage
│   ├── findings/         # JSON findings by type
│   ├── logs/             # Application logs
│   └── screenshots/      # Captured images
├── memory/               # Finding repository
├── tools/                # Scanner, Fuzzer, Browser
├── docker-compose.yml    # Service orchestration
└── gcp-credentials.json  # Your GCP key (gitignored)
```

## Next Steps

1. **Customize Instructions**: Add domain-specific guidance for better results
2. **Train the AI**: Use HITL to approve/reject/edit actions
3. **Review Findings**: Check the Evidence modal after each mission
4. **Adjust Quotas**: Modify `config/config.py` for longer missions
5. **Explore State Management**: Use checkpoints for complex testing

## Support

- **Issues**: https://github.com/J0n-H4rr150n/ai-hunter/issues
- **Docs**: See `docs/` folder for detailed documentation
- **Architecture**: `docs/system_architecture.md`
- **LLM Observability**: `docs/llm_observability.md`

---

**Happy Hunting! 🐝🔍**
