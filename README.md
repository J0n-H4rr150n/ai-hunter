# AI Hunter

Autonomous web application security testing agent. It drives a real browser, reasons about
what it sees with a **locally hosted LLM**, and reports findings with screenshots and
request/response evidence. Nothing is sent to a cloud model provider.

The agent runs missions against a target in one of three modes:

- **Autonomous** — scan the target, write its own plan, then execute it under resource caps.
- **Runbook-guided** — follow a declarative YAML runbook (recon, IDOR, CTF) while adapting
  each step to what it actually observes.
- **Playbook** — chain several runbooks into a longer campaign with checkpoints.

A human-in-the-loop mode can gate every tool call for approval, payload editing, or rejection,
and that feedback is stored and retrieved on later missions.

> Intended for targets you own or are explicitly authorized to test.

---

## Requirements

- **Python 3.12+**
- **Docker** (for PostgreSQL + Redis)
- **A local OpenAI-compatible LLM server** — llama.cpp's `llama-server` is what this is built
  against. A vision-capable model is strongly recommended because the agent reasons over
  screenshots.

### Model server

Screenshots are a first-class input, so serve a model with a multimodal projector:

```sh
llama-server \
  --model  ~/models/Qwen3.8-27B-MTP-GGUF/Qwen3.8-27B-MTP-Q8_0.gguf \
  --mmproj ~/models/Qwen3.8-27B-MTP-GGUF/mmproj-F32.gguf \
  --host 0.0.0.0 --port 30087 --alias qwen38-27b-q8 \
  --ctx-size 32768 --n-gpu-layers 99 --jinja
```

Any OpenAI-compatible endpoint works — point `LLM_BASE_URL` at it. Without a projector, set
`LLM_SUPPORTS_VISION=false` and the agent falls back to DOM and source text only.

---

## Install

```sh
git clone https://github.com/J0n-H4rr150n/ai-hunter.git
cd ai-hunter
cp .env.example .env          # review the LLM and database settings

# Dependencies: PostgreSQL 16 + pgvector on :33001, Redis on :33002
docker compose up -d postgres redis

pip install fastapi 'uvicorn[standard]' asyncpg psycopg2-binary redis \
            requests pillow numpy pyyaml alembic playwright
playwright install chromium

alembic upgrade head          # creates the schema
```

---

## Run

### Single port (recommended — works from a phone over Tailscale)

`serve.py` hosts the SPA and the API on **one TLS origin**, so every API call is same-origin
and the UI is usable from a phone browser without mixed-content errors.

```sh
PORT=30170 python3 serve.py
```

Then open `https://<your-tailscale-host>:30170/`. TLS uses the shared dev cert at
`~/models/spa/certs/server.{crt,key}` when present and falls back to plain HTTP otherwise.
The page ships a web manifest and icons, so it can be installed to a phone home screen.

To run it as a managed service:

```sh
cp ai-hunter.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-hunter
```

### Split ports (Docker)

The original layout, with the UI and API on separate origins over plain HTTP:

```sh
docker compose up -d --build
```

| Service | Port | Notes |
|---|---|---|
| Frontend (Express) | 33004 | Vanilla JS + Tailwind |
| Backend (FastAPI) | 33003 | REST + SSE |
| PostgreSQL + pgvector | 33001 | Missions, findings, traces, snapshots |
| Redis | 33002 | Pub/sub for the live feed |

The backend container reaches the host's model server via `host.docker.internal`.

### CLI

`main.py` is a terminal entrypoint that bypasses the web UI entirely:

```sh
python3 main.py
# auto <url> [instructions]   scan <url>   fuzz <url>   search <text>   status
```

---

## Using it

1. Open the UI and click **New Mission**.
2. Enter a target URL, and optionally instructions (`Focus on ID parameters. Don't create accounts.`).
3. The agent scans the target, drafts a plan, and waits for approval.
4. Approve the plan and watch the live feed: tech fingerprinting, screenshots, fuzz results,
   and findings as they land.
5. Open **Evidence** for screenshots, request/response metadata, and confirmed findings.

Turn on **HITL** in Settings to approve or edit every individual tool call.

---

## Layout

```
agents/      planner (strategy), agent_brain (per-step decisions), analyst (triage), scorekeeper
core/        autonomous_loop, runbook_engine, playbook_executor, tool_mapper (action dispatch),
             llm_client (local model transport), state_manager, quota_manager, llm_tracer
tools/       som_browser (Playwright set-of-marks), tech_scanner, fuzzer, report_generator
memory/      finding_repository, feedback_memory — HITL decisions and past findings
runbooks/    declarative test procedures (recon, IDOR, CTF, brainstorm, learn, report)
playbooks/   runbook chains
backend/     FastAPI app, database, redis, websockets
frontend/    vanilla-JS SPA served from frontend/public
serve.py     single-port TLS host for the SPA + API
hive_bucket/ evidence output: screenshots, findings, logs (gitignored)
```

## Safety limits

`config/safety.py` holds caps the model **cannot** override — the LLM proposes actions, but the
engine enforces the ceiling:

- Fuzzing: max 50 IDs per batch, 5 concurrent, 0.5s between batches, 5s timeout
- Navigation: 10s page-load timeout
- Context: DOM and source truncated to 20,000 characters before reaching the model
- Per-phase hard caps on every action type, with conservative defaults if the planner omits a budget

With a 32k context window, the 20,000-character truncation plus a screenshot is a meaningful
share of the budget — lower `MAX_DOM_CHARS` if you see context overflows.

## Configuration

Everything is environment-driven; see `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` | `http://127.0.0.1:30087/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `qwen38-27b-q8` | Served model alias |
| `LLM_SUPPORTS_VISION` | `true` | Send screenshots to the model |
| `LLM_TIMEOUT` | `300` | Seconds; a 27B at Q8 with an image is not fast |
| `PORT` | `30170` | Single-port host |
| `DATABASE_URL` | `…@127.0.0.1:33001/ai_hunter` | PostgreSQL |
| `REDIS_URL` | `redis://127.0.0.1:33002` | Redis |
| `DISABLE_EMBEDDINGS` | `true` | pgvector semantic search over past findings |

Semantic search over past findings is off by default because it pulls in TensorFlow. Enable
with `poetry install -E embeddings` and `DISABLE_EMBEDDINGS=false`.

## Operations

```sh
docker compose logs -f postgres redis           # dependency logs
tail -f hive_bucket/logs/backend.log            # application log
docker compose exec postgres psql -U hunter -d ai_hunter
alembic upgrade head                            # apply migrations
./scripts/reset_database.sh                     # wipe and recreate
```

Further documentation is in `docs/` — `system_architecture.md`, `llm_observability.md`,
`EMBEDDINGS.md`, `DATABASE_RESET.md`.
