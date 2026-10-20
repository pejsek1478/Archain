# Archain Field Diary

A lightweight archaeological field diary built for Raspberry Pi 5 deployments. Log entries with time, GPS, photos, 3D models, and collaboration metadata, then share them with teammates.

## Features
- Add diary entries with timestamp, weather, and notes.
- Capture GPS coordinates directly from a mobile browser.
- Attach photos, PDFs, and 3D models (GLB/GLTF) rendered in-browser.
- Multi-file attach: drag & drop, repeated picks add up, paste screenshots, camera button on phones, previews, per-file remove and an upload progress bar.
- Edit an entry to remove old attachments or add more; download all attachments of an entry as one ZIP.
- Click an image on an entry to open a full-screen viewer (arrow keys / swipe).
- Unsaved new entries are kept as a draft in the browser, so a reload or lost signal does not lose your notes.
- **AI assistant (optional, runs locally on the CPU):** ask questions about your entries, get statistics explained, and let the model suggest a title and tags while you write. See [AI assistant](#ai-assistant).
- Track team members and people who discovered each find.
- SQLite storage for simple multi-user access on the same network.
- Require login for all users, with an owner-admin able to manage entries and accounts.
- Search entries by title, notes, or tags, plus view shared finds on a map.
- Auto-fill weather from coordinates (via wttr.in) when the weather field is left blank.
- Toggle between light and dark themes for field conditions.
- Browse a user directory with profile details, selfies, and linked entries.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:8000` from your desktop or mobile device on the same network.

### First-time setup
If no users exist, open `/setup` to create the owner account. The owner can then create more users from the admin panel.

## Configuration
- `ARCHAIN_MAX_UPLOAD_MB` – maximum size of one upload request (all files of one entry together). Default `200`.

## AI assistant
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

**Settings** (environment variables, all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ARCHAIN_AI` | `on` | `off` hides the assistant completely. |
| `ARCHAIN_AI_BACKEND` | `ollama` | `ollama` or `openai` (OpenAI-compatible server). |
| `ARCHAIN_AI_URL` | `http://127.0.0.1:11434` | Address of the model server. In Docker use `http://host.docker.internal:11434`. |
| `ARCHAIN_AI_MODEL` | `qwen3.5:4b` | Model name. |
| `ARCHAIN_AI_THREADS` | auto | CPU threads. Auto lets Ollama choose the optimal number (physical or performance cores); set a number to override. |
| `ARCHAIN_AI_USE_GPU` | `0` | CPU only by default for maximum compatibility. `1` lets the server use a GPU if it finds one. |
| `ARCHAIN_AI_CTX` | `4096` | Context window in tokens. |
| `ARCHAIN_AI_MAX_TOKENS` | `400` | Maximum length of one answer. |
| `ARCHAIN_AI_CONTEXT_CHARS` | `3500` | How much diary text is sent with each question. Raise it on fast CPUs, lower it on a Pi. |
| `ARCHAIN_AI_KEEP_ALIVE` | `30m` | How long Ollama keeps the model in memory after the last question. |
| `ARCHAIN_AI_TIMEOUT` | `300` | Seconds to wait for the model server. |
| `ARCHAIN_AI_API_KEY` | empty | Bearer token for OpenAI-compatible servers that require one. |

**Why it stays fast on a CPU.** Reading the prompt is the slow part on a CPU, so each question sends only the diary overview plus the few most relevant entries (keyword search that ignores accents and word endings). Numbers such as counts per week are computed in Python, not guessed by the model. The model is loaded when you open the Assistant page and kept in memory, answers stream in word by word, and only one answer is generated at a time so several users do not fight for the same cores.

**Privacy and access.** With the default setup nothing leaves your machine. The prompt only contains entries the signed-in user may see (admins: all, others: their own and shared entries). If you point `ARCHAIN_AI_URL` at another computer, the diary text is sent there.

**Tuning tips.** Watch the speed shown under each answer (tokens/s). If the first answer takes very long, the model is probably still loading from a slow SD card or disk. Setting `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_MAX_LOADED_MODELS=1` for the Ollama service saves memory on small machines.

## Raspberry Pi 5 notes
- Uses only Python + SQLite, so it runs well on ARM64.
- For multi-user access, run `python app.py` and keep the Pi on your local network.
- Store the `diary.db` file in a backed-up location for long-term preservation.

## Optional Docker setup
```bash
docker build -t field-diary .
docker run -p 8000:8000 -v $(pwd)/uploads:/app/uploads -v $(pwd)/diary.db:/app/diary.db field-diary
```

## Data model
- **Users** are the shared team members you can add to entries.
- **People** represent finders or contributors.
- **Entries** capture the diary content and reference uploads stored in `/uploads`.

## Security
This demo app includes basic username/password authentication. For production use, add stronger auth and backup routines.
