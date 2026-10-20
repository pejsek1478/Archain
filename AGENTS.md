# Archain Field Diary — Agent Reference

## Project Overview
Lightweight archaeological field diary for Raspberry Pi 5. Flask + SQLite, optional local AI (Ollama/OpenAI-compatible). Multi-user with admin roles, GPS, attachments (photos, PDFs, GLB/GLTF), map view, AI assistant.

## Directory Structure
```
Archain-main/
├── app.py           # Main Flask app (950 lines) — routes, models, helpers
├── ai.py            # AI assistant client + prompt logic (706 lines)
├── ai_config.json   # AI prompts & default model configuration
├── requirements.txt # Flask, Flask-SQLAlchemy, SQLAlchemy
├── Dockerfile       # python:3.11-slim
├── README.md        # Full docs (config, AI, Pi notes)
├── diary.db         # SQLite database (gitignored)
├── uploads/         # Attachment storage (gitignored)
├── templates/       # 13 Jinja2 templates
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
- **AIConfig** (line 58): all settings via `ARCHAIN_AI_*` env vars
- **AIClient** (line 165): HTTP to Ollama/OpenAI-compatible server, streaming, queue lock
- **Prompt building** (line 615): keyword ranking, stats, context budgeting, think-block stripping
- **Suggest** (line 665): title + tags from notes
- **Model selection**: fetches available models from Ollama if `ARCHAIN_AI_MODEL` not set
- **fetch_ollama_models()**: queries Ollama `/api/tags` for installed models

### ai_config.json
- AI prompts and default model configuration (system_prompt, suggest_prompt, default_model)

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
| Var | Default | Purpose |
|-----|---------|---------|
| `ARCHAIN_MAX_UPLOAD_MB` | 200 | Max upload size per entry |
| `ARCHAIN_AI` | on | `off` disables assistant |
| `ARCHAIN_AI_BACKEND` | ollama | `ollama` or `openai` |
| `ARCHAIN_AI_URL` | http://127.0.0.1:11434 | Model server |
| `ARCHAIN_AI_MODEL` | (auto from Ollama) | Model name; if unset, picks first matching default_model from Ollama |
| `ARCHAIN_AI_THREADS` | auto | CPU threads |
| `ARCHAIN_AI_USE_GPU` | 0 | GPU off by default |
| `ARCHAIN_AI_CTX` | 4096 | Context tokens |
| `ARCHAIN_AI_MAX_TOKENS` | 400 | Answer length |
| `ARCHAIN_AI_CONTEXT_CHARS` | 3500 | Diary text per question |
| `ARCHAIN_AI_KEEP_ALIVE` | 30m | Ollama keep-alive |
| `ARCHAIN_AI_TIMEOUT` | 300 | Request timeout |
| `ARCHAIN_AI_API_KEY` | "" | Bearer token for OpenAI backend |

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