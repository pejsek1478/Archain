# Archain Field Diary

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)](https://flask.palletsprojects.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A lightweight archaeological field diary built for Raspberry Pi 5 deployments. Log entries with time, GPS, photos, 3D models, and collaboration metadata, then share them with teammates.

## Features

- **Diary Entries** — Add entries with timestamp, weather, and rich notes
- **GPS Capture** — Get coordinates directly from mobile browsers
- **Media Attachments** — Photos, PDFs, and 3D models (GLB/GLTF) rendered in-browser
- **Multi-file attach** — drag & drop, repeated picks add up, paste screenshots, camera button on phones, previews, per-file remove and an upload progress bar
- **Edit attachments** — Remove old attachments or add more; download all attachments of an entry as one ZIP
- **Image viewer** — Click an image on an entry to open a full-screen viewer (arrow keys / swipe)
- **Draft persistence** — Unsaved new entries are kept as a draft in the browser
- **AI assistant (optional, runs locally on the CPU)** — Ask questions about your entries, get statistics explained, and let the model suggest a title and tags while you write. See [AI Assistant](#ai-assistant)
- **Team Collaboration** — Track team members and discoverers for each find
- **SQLite Storage** — Simple multi-user access on the same network
- **Role-Based Auth** — Login required for all users; owner-admin manages entries and accounts
- **Search & Map** — Search by title, notes, or tags; view finds on an interactive map
- **Auto Weather** — Auto-fills weather from coordinates (via wttr.in) when blank
- **Light/Dark Themes** — Toggle for field conditions
- **User Directory** — Browse profiles with details, selfies, and linked entries

## Quick Start

### Local Development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:8000` from your desktop or mobile device on the same network.

### First-Time Setup

If no users exist, open `/setup` to create the owner account. The owner can then create more users from the admin panel.

## AI Assistant

The assistant answers questions about the entries a user may see, explains the diary statistics, and suggests a title and tags on the entry form. It is optional: if no model server is running, the rest of Archain works exactly as before and the Assistant page tells you what is missing.

**How it works.** Archain itself needs no new Python packages. It talks over HTTP to a local model server that does the heavy lifting on the CPU:

1. Install [Ollama](https://ollama.com) (Windows, macOS, Linux; x86-64 and ARM64). It detects the instruction sets of your processor at run time (Intel, AMD, ARM) and runs the model on several threads.
2. Download a model once: `ollama pull qwen3.5:4b` (about 3 GB, needs roughly 4 GB of free RAM).
3. Start Archain as usual and open **Assistant**. The banner shows whether the model server was found.

Any other OpenAI-compatible server works too, for example llama.cpp's `llama-server`:
`ARCHAIN_AI_BACKEND=openai ARCHAIN_AI_URL=http://127.0.0.1:8080 python app.py` (set threads and context on the server itself with `-t` and `-c`).

**Choosing a model for your hardware.** Use a small *instruct* model (not a "thinking" one) and set it with `ARCHAIN_AI_MODEL`:

| Hardware | Suggestion |
| --- | --- |
| Raspberry Pi 5 (8 GB), older laptops | `qwen3.5:2b` (fast) or `qwen3.5:4b` (better, a few tokens per second) |
| Modern desktop / laptop CPU, 16 GB RAM | `qwen3.5:4b` (default) or a larger 7-9B model if you accept slower answers |

Smaller models are quicker but make more mistakes, and quality in languages other than English varies, so try two or three. Answers always link to the entries they used.

**Configuration.** All AI settings are in `ai/ai_config.json`. Environment variables (`ARCHAIN_AI_*`) override the config file.

| Config Key | Env Var | Default | Meaning |
| --- | --- | --- | --- |
| `enabled` | `ARCHAIN_AI` | `true` | `false` hides the assistant completely. |
| `backend` | `ARCHAIN_AI_BACKEND` | `ollama` | `ollama` or `openai` (OpenAI-compatible server). |
| `url` | `ARCHAIN_AI_URL` | `http://127.0.0.1:11434` | Address of the model server. In Docker use `http://host.docker.internal:11434`. |
| `model` | `ARCHAIN_AI_MODEL` | (auto) | Model name. If empty, uses a model that is installed in Ollama (prefers `default_model` if set, else the first non-embedding model). |
| `default_model` | — | (empty) | Optional preferred model name (substring match against installed models). |
| `threads` | `ARCHAIN_AI_THREADS` | auto | CPU threads. Auto lets Ollama choose; set a number to override. |
| `use_gpu` | `ARCHAIN_AI_USE_GPU` | `false` | CPU only by default. `true` lets the server use a GPU if available. |
| `ctx` | `ARCHAIN_AI_CTX` | `4096` | Context window in tokens. |
| `max_tokens` | `ARCHAIN_AI_MAX_TOKENS` | `400` | Maximum length of one answer. |
| `context_chars` | `ARCHAIN_AI_CONTEXT_CHARS` | `3500` | How much diary text is sent with each question. |
| `keep_alive` | `ARCHAIN_AI_KEEP_ALIVE` | `30m` | How long Ollama keeps the model in memory after the last question. |
| `timeout` | `ARCHAIN_AI_TIMEOUT` | `300` | Seconds to wait for the model server. |
| `queue_timeout` | `ARCHAIN_AI_QUEUE_TIMEOUT` | `90` | Seconds to wait for the generation queue. |
| `api_key` | `ARCHAIN_AI_API_KEY` | empty | Bearer token for OpenAI-compatible servers that require one. |
| `system_prompt` | — | (built-in) | System prompt for chat. |
| `suggest_prompt` | — | (built-in) | Prompt for title/tags suggestion. |

**Why it stays fast on a CPU.** Reading the prompt is the slow part on a CPU, so each question sends only the diary overview plus the few most relevant entries (keyword search that ignores accents and word endings). Numbers such as counts per week are computed in Python, not guessed by the model. The model is loaded when you open the Assistant page and kept in memory, answers stream in word by word, and only one answer is generated at a time so several users do not fight for the same cores.

**Privacy and access.** With the default setup nothing leaves your machine. The prompt only contains entries the signed-in user may see (admins: all, others: their own and shared entries). If you point `ARCHAIN_AI_URL` at another computer, the diary text is sent there.

**Tuning tips.** Watch the speed shown under each answer (tokens/s). If the first answer takes very long, the model is probably still loading from a slow SD card or disk. Setting `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_MAX_LOADED_MODELS=1` for the Ollama service saves memory on small machines.

## Raspberry Pi 5 Deployment

- Uses only Python + SQLite, so it runs well on ARM64
- For multi-user access, run `python app.py` and keep the Pi on your local network
- Store the `diary.db` file in a backed-up location for long-term preservation

### Systemd Service (Recommended for Pi)

Create `/etc/systemd/system/archain.service`:

```ini
[Unit]
Description=Archain Field Diary
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Archain
Environment=PATH=/home/pi/Archain/.venv/bin
ExecStart=/home/pi/Archain/.venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable archain
sudo systemctl start archain
```

## Docker Deployment

```bash
docker build -t field-diary .
docker run -p 8000:8000 \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/diary.db:/app/diary.db \
  field-diary
```

## Project Structure

```
Archain/
├── app.py                   # Main Flask application
├── ai/                      # AI assistant package
│   ├── __init__.py
│   ├── ai.py                # AI client + prompt logic
│   └── ai_config.json       # AI configuration (all settings)
├── requirements.txt         # Python dependencies
├── Dockerfile               # Container definition
├── diary.db                 # SQLite database (created on first run)
├── uploads/                 # Attached media files
├── static/
│   └── styles.css           # Stylesheet with light/dark themes
└── templates/               # Jinja2 templates
    ├── base.html            # Base layout
    ├── index.html           # Entry list with search
    ├── entry_form.html      # Create/edit entry form
    ├── entry_detail.html    # Entry detail view
    ├── login.html           # Login page
    ├── setup.html           # First-admin setup
    ├── map.html             # Map view of entries
    ├── users.html           # Admin user management
    ├── edit_user.html       # Admin edit user
    ├── people.html          # Admin manage people
    ├── user_directory.html  # Team directory
    ├── user_profile.html    # Profile view
    └── edit_profile.html    # Profile editing
```

## Data Model

| Entity | Description |
|--------|-------------|
| **User** | Team members with login; can be admin/owner |
| **Person** | Finders/contributors (no login) |
| **Entry** | Diary content with metadata, GPS, weather, tags |
| **Tag** | Searchable tags on entries |
| **Attachment** | Uploaded files (images, PDFs, 3D models) |

Relationships:
- Entry ↔ User (many-to-many via `entry_users`)
- Entry ↔ Person (many-to-many via `entry_people`)
- Entry ↔ Tag (many-to-many via `entry_tags`)
- Entry → Attachment (one-to-many)
- Entry → User (owner, many-to-one)

## Configuration

Environment variables (optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-change-me` | Flask session secret (change in production!) |
| `DATABASE_URL` | `sqlite:///diary.db` | SQLAlchemy database URI |
| `MAX_CONTENT_LENGTH` | `52428800` (50MB) | Max upload size |
| `ARCHAIN_TILE_URL` | OSM URL | Tile server template (e.g. `http://localhost:8080/{z}/{x}/{y}.png` for local tileserver-gl, or `/tiles/{z}/{x}/{y}.png` for local `tiles/` dir) |
| `ARCHAIN_TILE_ATTRIBUTION` | OSM | Attribution text for tile layer |

## Offline Map Tiles (Pi Field Deployment)

For Raspberry Pi deployments without internet, you can use local map tiles:

**Option 1: Local tile server (tileserver-gl)**
```bash
# Install tileserver-gl
docker run -it -v $(pwd)/tiles:/data -p 8080:80 maptiler/tileserver-gl
# Set env var
ARCHAIN_TILE_URL=http://localhost:8080/{z}/{x}/{y}.png python app.py
```

**Option 2: Local tile directory**
```bash
# Create tiles directory and download tiles for your area
mkdir -p tiles
# Use a tool like maptiles or mobac to download tiles to tiles/{z}/{x}/{y}.png
# Set env var
ARCHAIN_TILE_URL=/tiles/{z}/{x}/{y}.png python app.py
```

The app serves tiles from the `tiles/` directory via `/tiles/{z}/{x}/{y}.png`.

## API Endpoints

### Authentication
- `GET/POST /login` — Sign in
- `POST /logout` — Sign out
- `GET/POST /setup` — Create first admin (only if no users exist)

### Entries
- `GET /` — List entries (searchable)
- `GET /map` — Map view of geotagged entries
- `GET/POST /entries/new` — Create entry
- `GET /entries/<id>` — View entry
- `GET/POST /entries/<id>/edit` — Edit entry
- `POST /entries/<id>/delete` — Delete entry (owner/admin)

### Users (Admin)
- `GET/POST /users` — List/create users
- `GET/POST /users/<id>/edit` — Edit user
- `POST /users/<id>/delete` — Delete user

### Profiles (Self + Admin)
- `GET /directory` — Team directory
- `GET /users/<id>` — Profile + entries
- `GET/POST /users/<id>/profile` — Edit profile
- `POST /users/<id>/password` — Change password

### People (Admin)
- `GET/POST /people` — List/create people

### Utilities
- `GET /uploads/<filename>` — Serve uploaded files (auth required)
- `GET /tiles/<path>` — Serve local map tiles (auth required)
- `GET /weather?lat=X&lon=Y` — Fetch weather for coordinates

### AI Assistant (when enabled)
- `GET /assistant` — Chat UI
- `GET /assistant/status` — Server status
- `GET /assistant/models` — Available models
- `POST /assistant/warmup` — Preload model
- `POST /assistant/chat` — Stream chat response
- `POST /assistant/suggest` — Suggest title/tags

## Security Notes

⚠️ **This is a field-tool demo.** For production use:

- Change `SECRET_KEY` to a strong random value
- Use HTTPS (reverse proxy with nginx + Let's Encrypt)
- Enable Flask's `SESSION_COOKIE_SECURE` and `SESSION_COOKIE_HTTPONLY`
- Add rate limiting on auth endpoints
- Implement automated database backups
- Consider PostgreSQL for concurrent write-heavy workloads

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

## License

MIT License — see [LICENSE](LICENSE) for details.

## Documentation

The documentation is split into focused guides:

- **[User guide](docs/USER_GUIDE.md)** — setup, creating entries, uploads, media viewing, search, maps, profiles, AI, and troubleshooting.
- **[Interactive features reference](docs/INTERACTIVE_FEATURES.md)** — keyboard shortcuts, image viewer controls, 3D model interactions, GPS, autocomplete, file picking, drag-and-drop, clipboard paste, and upload progress.
- **[Architecture and development](docs/ARCHITECTURE.md)** — stack, request lifecycle, data model, important files, routes, development workflow, and testing.
- **[Deployment and operations](docs/DEPLOYMENT.md)** — local installation, Docker, systemd, configuration, offline maps, backups, upgrades, and security checklist.
- [Contributing guidelines](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

