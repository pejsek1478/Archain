# Archain Field Diary — Agent Reference

## Project Overview
Lightweight archaeological field diary for Raspberry Pi 5. Flask + SQLite, optional local AI (Ollama/OpenAI-compatible). Multi-user with admin roles, GPS, attachments (photos, PDFs, GLB/GLTF), map view, AI assistant.

## Directory Structure
```
Archain/
├── app.py                   # Main Flask app (routes, models, helpers)
├── ai/                      # AI assistant package
│   ├── __init__.py
│   ├── ai.py                # AI client + prompt logic
│   └── ai_config.json       # AI configuration (all settings)
├── requirements.txt         # Flask, Flask-SQLAlchemy, SQLAlchemy
├── Dockerfile               # python:3.11-slim
├── README.md                # Project docs (config, AI, Pi notes)
├── CONTRIBUTING.md          # Contribution guidelines
├── SECURITY.md              # Security policy & vulnerability reporting
├── CHANGELOG.md             # Version history
├── LICENSE                  # MIT license
├── diary.db                 # SQLite database (gitignored)
├── uploads/                 # Attachment storage (gitignored)
├── .github/
│   ├── workflows/
│   │   └── ci.yml           # CI pipeline (lint, format, syntax check)
│   └── dependabot.yml       # Weekly dependency updates
├── templates/               # 13 Jinja2 templates
│   ├── base.html
│   ├── index.html
│   ├── map.html
│   ├── login.html
│   ├── setup.html
│   ├── entry_form.html
│   ├── entry_detail.html
│   ├── assistant.html
│   ├── users.html
│   ├── user_directory.html
│   ├── user_profile.html
│   ├── edit_user.html
│   └── edit_profile.html
└── static/
    ├── styles.css
    ├── lightbox.js
    ├── attachments.js
    ├── assistant.js
    └── ai-suggest.js
```

## Key Files & Responsibilities

### app.py
- **Models** (lines 65–135): `User`, `Person`, `Entry`, `Tag`, `Attachment` + join tables
- **Routes**:
  - `/` — entry list with search
  - `/map` — GPS entries on map
  - `/login`, `/logout`, `/setup` — auth
  - `/entries/new`, `/edit/<id>`, `/<id>`, `/delete/<id>` — CRUD
  - `/assistant`, `/assistant/chat`, `/assistant/suggest`, `/assistant/warmup`, `/assistant/status`, `/assistant/models` — AI
  - `/entries/<id>/attachments.zip` — bulk download
  - `/users`, `/directory`, `/users/<id>`, `/users/<id>/profile`, `/users/<id>/edit`, `/users/<id>/delete` — user mgmt
  - `/people` — external people mgmt
  - `/uploads/<path>` — file serving
  - `/weather` — wttr.in lookup
- **Helpers** (lines 725–946): attachment handling, permissions, tag parsing, weather fetch, AI entry filtering

### ai.py
- **AIConfig** (line 72): all settings via `ai_config.json` with `ARCHAIN_AI_*` env var overrides
- **AIClient** (line 203): HTTP to Ollama/OpenAI-compatible server, streaming, queue lock
- **Prompt building** (line 695): keyword ranking, stats, context budgeting, think-block stripping
- **Suggest** (line 745): title + tags from notes
- **Model selection**: fetches available models from Ollama if `model` not set in config
- **fetch_ollama_models()**: queries Ollama `/api/tags` for installed models

### ai_config.json
- Complete AI configuration: enabled flag, backend, URL, model, threads, context, tokens, GPU, timeouts, API key, prompts
- Environment variables (`ARCHAIN_AI_*`) override config file values
- Set `"enabled": false` to disable AI assistant entirely (hides UI, disables endpoints)

### Documentation Files
- **README.md** — Project overview, quick start, Pi deployment, Docker, data model, API endpoints, security
- **CONTRIBUTING.md** — Contribution guidelines, dev setup, testing checklist, architecture notes
- **SECURITY.md** — Supported versions, vulnerability reporting, known limitations, hardening recommendations
- **CHANGELOG.md** — Version history
- **LICENSE** — MIT license

### GitHub Configuration
- **.github/workflows/ci.yml** — CI pipeline (lint, format, syntax check)
- **.github/dependabot.yml** — Weekly dependency updates

## Database Schema (SQLAlchemy)
| Table | Purpose |
|-------|---------|
| users | team members, admin flag, profile fields |
| people | external finders/contributors |
| entries | diary records (owner, time, GPS, weather, notes) |
| tags | searchable labels |
| attachments | uploaded files (stored in `uploads/`) |
| entry_users, entry_people, entry_tags | many-to-many joins |

## Environment Variables
All AI settings are configured in `ai/ai_config.json`. Environment variables (`ARCHAIN_AI_*`) override the config file.

| Config Key | Env Var | Default | Purpose |
|------------|---------|---------|---------|
| `enabled` | `ARCHAIN_AI` | `true` | `false` disables assistant entirely |
| `backend` | `ARCHAIN_AI_BACKEND` | `ollama` | `ollama` or `openai` |
| `url` | `ARCHAIN_AI_URL` | `http://127.0.0.1:11434` | Model server |
| `model` | `ARCHAIN_AI_MODEL` | (auto from Ollama) | Model name; if empty, picks first matching `default_model` from Ollama |
| `default_model` | — | `qwen3.5:4b` | Fallback model name for Ollama auto-detection |
| `threads` | `ARCHAIN_AI_THREADS` | `null` (auto) | CPU threads (1–512) |
| `ctx` | `ARCHAIN_AI_CTX` | `4096` | Context tokens (1024–131072) |
| `max_tokens` | `ARCHAIN_AI_MAX_TOKENS` | `400` | Answer length (32–4096) |
| `context_chars` | `ARCHAIN_AI_CONTEXT_CHARS` | `3500` | Diary text per question (800–60000) |
| `use_gpu` | `ARCHAIN_AI_USE_GPU` | `false` | GPU off by default |
| `keep_alive` | `ARCHAIN_AI_KEEP_ALIVE` | `30m` | Ollama keep-alive |
| `timeout` | `ARCHAIN_AI_TIMEOUT` | `300` | Request timeout (10–3600s) |
| `queue_timeout` | `ARCHAIN_AI_QUEUE_TIMEOUT` | `90` | Queue wait timeout (1–3600s) |
| `api_key` | `ARCHAIN_AI_API_KEY` | `""` | Bearer token for OpenAI backend |
| `system_prompt` | — | (built-in) | System prompt for chat |
| `suggest_prompt` | — | (built-in) | Prompt for title/tags suggestion |

Other:
| Var | Default | Purpose |
|-----|---------|---------|
| `ARCHAIN_MAX_UPLOAD_MB` | 200 | Max upload size per entry |
| `ARCHAIN_TILE_URL` | OSM URL | Tile server template (e.g. `http://localhost:8080/{z}/{x}/{y}.png` for local tileserver-gl, or `/tiles/{z}/{x}/{y}.png` for local `tiles/` dir) |
| `ARCHAIN_TILE_ATTRIBUTION` | OSM | Attribution text for tile layer |

## Running
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py  # http://localhost:8000
```
First visit `/setup` to create admin.

## Docker
```bash
docker build -t field-diary .
docker run -p 8000:8000 -v $(pwd)/uploads:/app/uploads -v $(pwd)/diary.db:/app/diary.db field-diary
```

## AI Assistant Notes
- Runs on CPU by default (no GPU deps)
- Only entries visible to the user are sent to the model
- Streams NDJSON; one generation at a time (global lock)
- Prompt = stats overview + top-ranked entries (keyword match, accent-insensitive)
- Suggest endpoint returns `{title, tags[]}` for entry form
- Prompts configurable via `ai_config.json`
- Model auto-detected from Ollama if not explicitly set
- Frontend model selector at `/assistant/models` endpoint

## Templates (key ones)
- `base.html` — sticky nav bar with icon tabs, theme handling
- `entry_form.html` — drag-drop uploads, camera, preview, progress, GPS map, AI suggest
- `assistant.html` — chat UI, stats sidebar, model selector dropdown
- `entry_detail.html` — lightbox for images, 3D viewer for GLB
- `map.html` — Leaflet map with entry markers

## Static JS
- `attachments.js` — multi-file upload, preview, remove, progress
- `assistant.js` — chat streaming, model selector, suggest button
- `ai-suggest.js` — title/tags suggestion on entry form
- `lightbox.js` — full-screen image viewer

## Common Tasks
- **Add a route**: edit `app.py`, add template in `templates/`
- **Change AI model**: set `ARCHAIN_AI_MODEL` env var (or leave unset for auto-detection)
- **Edit AI prompts**: modify `ai_config.json`
- **Reset DB**: delete `diary.db`, restart, visit `/setup`
- **Backup**: copy `diary.db` + `uploads/`
- **Run CI locally**: `pip install ruff && ruff check . && ruff format --check . && python -m py_compile app.py`

## ⚠️ Critical Rules
- **NEVER delete or overwrite `diary.db`** — this is the user's production data. Only delete if explicitly instructed by the user.
- **NEVER run destructive DB operations** (drop tables, delete data) without explicit user confirmation.
- Map rendering: the `#entry-map` container must have explicit height (560px) and be visible when Leaflet initializes. Call `map.invalidateSize()` after any tab switch or visibility change.