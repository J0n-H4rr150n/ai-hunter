# AI Hunter

Autonomous web application reconnaissance agent. It drives a real browser, reasons about
what it sees with a **locally hosted LLM**, and records everything it does — every tool
call, every model call, every screenshot — against a Postgres store. Nothing is sent to a
cloud model provider.

> Intended for targets you own or are explicitly authorized to test.

## What it does, and what it does not

Being specific, because the gap matters:

**It does** fingerprint a target, inspect its TLS certificate, map interactive elements,
capture screenshots at every step, write a tactical plan with an LLM, pause for your
approval, and record the whole run so it can be replayed and audited afterwards.

**It does not** yet carry out the plan it writes. The execution loop implements three task
types — `scan`, `fuzz`, `analyze` — so a plan step like *"POST role=admin to /api/v1/profile"*
becomes a generic scan of the base URL. `agents/agent_brain.py` contains `SecurityAgent`, the
step-by-step reasoner that would close this gap by choosing concrete `navigate`/`click`/`type`
actions from a screenshot; **it is not wired into anything yet.**

Measured against a purpose-built benchmark with twelve planted access-control
vulnerabilities, it currently finds **0 of 12**. That is the number to move. Treat this as a
reconnaissance and observability platform with a planner attached, not a scanner that finds
bugs.

## Modes

- **Autonomous** — scan the target, write a plan, wait for approval, execute under resource caps.
- **Playbook** — chain YAML runbooks into a longer campaign with checkpoints and pause/resume.

A human-in-the-loop mode gates every tool call for approval, payload editing or rejection,
and those decisions are stored for later missions.

---

## Requirements

- **Python 3.12+**
- **Docker** — for PostgreSQL 16 + pgvector, the only infrastructure dependency
- **A local OpenAI-compatible LLM server.** Built against llama.cpp's `llama-server`. A
  vision-capable model is strongly recommended: screenshots are a primary input.

### Model server

```sh
llama-server \
  --model  ~/models/Qwen3.8-27B-MTP-GGUF/Qwen3.8-27B-MTP-Q8_0.gguf \
  --mmproj ~/models/Qwen3.8-27B-MTP-GGUF/mmproj-F32.gguf \
  --host 0.0.0.0 --port 30087 --alias qwen38-27b-q8 \
  --ctx-size 32768 --n-gpu-layers 99 --jinja
```

Any OpenAI-compatible endpoint works — point `LLM_BASE_URL` at it. Without a vision
projector set `LLM_SUPPORTS_VISION=false`; the agent falls back to DOM and source text.

Responses are streamed, so a slow model is fine. On a 27B at Q8 (~8-12 tok/s measured) a
plan takes about 30 seconds. See *Timeouts* below.

---

## Install

```sh
git clone https://github.com/J0n-H4rr150n/ai-hunter.git
cd ai-hunter
cp .env.example .env

docker compose up -d postgres          # PostgreSQL + pgvector on :33001

pip install fastapi 'uvicorn[standard]' asyncpg psycopg2-binary \
            requests pillow numpy pyyaml alembic playwright
playwright install chromium

alembic upgrade head
```

## Run

### Single port (recommended — works from a phone over Tailscale)

`serve.py` hosts the SPA and the API on **one TLS origin**, so API calls are same-origin and
the UI works from a phone browser with no mixed-content problems.

```sh
PORT=30170 python3 serve.py
```

Open `https://<your-tailscale-host>:30170/`. TLS uses the shared dev cert at
`~/models/spa/certs/server.{crt,key}` when present, otherwise plain HTTP. The page ships a
web manifest and icons, so it installs to a phone home screen.

As a service:

```sh
cp ai-hunter.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now ai-hunter
```

### Split ports (Docker)

```sh
docker compose up -d --build
```

| Service | Port |
|---|---|
| Frontend (Express) | 33004 |
| Backend (FastAPI) | 33003 |
| PostgreSQL + pgvector | 33001 |

The backend container reaches the host's model server via `host.docker.internal`.

### CLI

```sh
python3 main.py
# auto <url> [instructions]   scan <url>   fuzz <url>   search <text>   status
```

---

## The interface

Seven tabs, mobile-first, usable from a phone over Tailscale:

| Tab | Shows |
|---|---|
| **Feed** | live activity; every entry expands to the full event with raw JSON |
| **Findings** | grouped by type, summarised inline, severity-accented |
| **Evidence** | screenshot grid with full-size view |
| **Tools** | every tool call with inputs, outputs, status and duration |
| **Model** | every LLM call with prompt, response, tokens and tok/s |
| **Plan** | the current plan and iteration history |
| **Missions** | all sessions; select one to scope the whole UI to it |

On desktop, clicking a record opens a resizable panel beside the list rather than over it,
so you can click through a set of records without dismissing anything. Every record is
presented the same way: readable key/value pairs, then the raw JSON with a copy button.

Missions can be named, and the feed is scoped to the selected session.

---

## Observability

Every run is fully recorded, which is what makes a mission auditable after the fact:

- **`tool_executions`** — each call's inputs, outputs, status, error and timing
- **`llm_traces`** — each model call's prompts, response, token counts, latency and tok/s
- **`activity_logs`** — every event, persisted *before* it is broadcast, so the feed replays
  losslessly even if no browser was connected while the mission ran
- **`hive_bucket/`** — screenshots and findings on disk

All timestamps are stored as `TIMESTAMPTZ` in UTC and rendered in Eastern time.

---

## Safety limits

`config/safety.py` holds caps the model **cannot** override — the LLM proposes actions, the
engine enforces the ceiling:

- Fuzzing: max 50 ids per batch, 5 concurrent, 0.5s between batches
- Navigation: 45s page-load timeout (`NAV_TIMEOUT_MS`)
- Context: DOM and source truncated to 20,000 characters before reaching the model
- Per-phase hard caps on every action type, with conservative defaults

With a 32k context window, 20,000 characters plus a screenshot is a large share of the
budget — lower `MAX_DOM_CHARS` if you see overflows.

## Target TLS

Targets routinely present expired, self-signed or mismatched certificates. For a security
tool that is a finding, not a reason to refuse to connect, so **certificate verification is
off for targets by default** and the certificate is inspected instead: subject, issuer, SANs,
validity window, self-signed status and whether it covers the host requested. Anything wrong
is recorded as a `tls_certificate` finding.

Set `VERIFY_TLS=true` to enforce verification, or `TARGET_CA_BUNDLE` to validate against a
specific CA.

## Configuration

Everything is environment-driven; see `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_BASE_URL` | `http://127.0.0.1:30087/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `qwen38-27b-q8` | served model alias |
| `LLM_API_KEY` | `local` | sent as a bearer token |
| `LLM_SUPPORTS_VISION` | `true` | send screenshots to the model |
| `LLM_TEMPERATURE` | `0.4` | |
| `LLM_MAX_TOKENS` | `4096` | reasoning models need headroom before the answer starts |
| `LLM_STREAM` | `true` | stream responses; what makes a slow model safe |
| `LLM_ENABLE_THINKING` | `true` | allow the model's thinking phase |
| `LLM_THINK_ON_JSON` | `false` | skip thinking for strict-JSON calls (measured 2.4x faster) |
| `VERIFY_TLS` | `false` | verify target certificates |
| `TARGET_CA_BUNDLE` | — | CA to validate targets against |
| `PORT` | `30170` | single-port host |
| `DATABASE_URL` | `…@127.0.0.1:33001/ai_hunter` | PostgreSQL |
| `HIVE_BUCKET_PATH` | `./hive_bucket` | evidence output |
| `DISABLE_EMBEDDINGS` | `true` | pgvector semantic search over past findings |
| `LOG_LEVEL` | `INFO` | |

### Timeouts

Derived from the served model rather than guessed, so a slow model is accommodated and a
dead one is still detected:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_CONNECT_TIMEOUT` | `15` | connecting; localhost should be instant |
| `LLM_FIRST_TOKEN_TIMEOUT` | `300` | prompt ingestion plus queueing |
| `LLM_STALL_TIMEOUT` | `60` | silence *between* tokens once generation starts |
| `LLM_MIN_TOKENS_PER_SEC` | `4` | pessimistic floor used to derive the ceiling |
| `LLM_TOTAL_TIMEOUT` | computed | `MAX_TOKENS / MIN_TOKENS_PER_SEC + FIRST_TOKEN_TIMEOUT` (~1324s) |

Semantic search over past findings is off by default because it pulls in TensorFlow. Enable
with `poetry install -E embeddings` and `DISABLE_EMBEDDINGS=false`.

---

## Layout

```
agents/      planner (strategy), agent_brain (step reasoning, not yet wired in), analyst
core/        autonomous_loop, playbook_executor, tool_mapper, llm_client, event_bus,
             tool_recorder, llm_recorder, mission_control, browser_thread
tools/       som_browser (Playwright set-of-marks), tech_scanner (+TLS), fuzzer
memory/      finding_repository, feedback_memory
runbooks/    declarative procedures   playbooks/  runbook chains
backend/     FastAPI app and database      frontend/  vanilla-JS SPA
serve.py     single-port TLS host
```

## Operations

```sh
docker compose logs -f postgres
tail -f hive_bucket/logs/ai-hunter.log
docker compose exec postgres psql -U hunter -d ai_hunter
alembic upgrade head
./scripts/reset_database.sh
```

Further notes in `docs/`.
