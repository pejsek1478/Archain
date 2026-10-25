# Architecture and Development

## Overview

Archain is a server-rendered Flask application. Jinja2 templates generate HTML, SQLAlchemy maps diary data to SQLite, and small JavaScript modules progressively enhance forms and media interactions.

## Technology stack

- **Python** application server
- **Flask 3.0.2** for routing, sessions, request handling, and templates
- **Flask-SQLAlchemy 3.1.1** and **SQLAlchemy 2.0.54** for persistence
- **SQLite** by default
- **Jinja2** templates under `templates/`
- **CSS and vanilla JavaScript** under `static/`
- Browser `model-viewer` component for GLB/GLTF previews
- Optional AI integration through Ollama or an OpenAI-compatible HTTP endpoint
- Docker image based on `python:3.11-slim`

## Request lifecycle

1. Flask receives a request.
2. The database is initialized on the first request if needed; the first-admin setup is enforced when no users exist.
3. The session identifies the signed-in user and the request context exposes that user to templates.
4. Route-level checks determine which entries can be viewed or edited.
5. SQLAlchemy reads/writes the SQLite database.
6. Jinja2 renders the response; static JavaScript enhances supported interactions.

## Data model

| Model | Purpose |
|---|---|
| `User` | Login account, password hash, role/contact/profile metadata, admin flag |
| `Person` | Contributor/finder record that does not require a login |
| `Entry` | Title, notes, owner, timestamps, location, GPS, weather, linked people/users, tags, attachments |
| `Tag` | Unique searchable tag |
| `Attachment` | Stored filename, original filename, media type, owning entry |

Relationships include many-to-many associations between entries and users, entries and people, and entries and tags. Each entry has many attachments.

## Important files

| Path | Responsibility |
|---|---|
| `app.py` | Flask app, models, routes, access checks, uploads, weather/map helpers, AI routes |
| `requirements.txt` | Pinned Python dependencies |
| `ai/ai.py` | AI client, prompt construction, retrieval/statistics and streaming logic |
| `ai/ai_config.json` | Default AI configuration |
| `templates/base.html` | Shared layout, navigation, theme shell |
| `templates/index.html` | Searchable entry index |
| `templates/entry_form.html` | Create/edit entry form and attachment controls |
| `templates/entry_detail.html` | Entry details, attachments, map |
| `templates/map.html` | Map view |
| `templates/assistant.html` | AI assistant page |
| `static/attachments.js` | File queue, previews, drag/drop/paste, progress and XHR submission |
| `static/lightbox.js` | Full-screen image viewer |
| `static/tags-autocomplete.js` | Tag suggestion interactions |
| `static/ai-suggest.js` | AI title/tag suggestions on the entry form |
| `static/assistant.js` | Assistant chat UI and streamed responses |
| `static/styles.css` | Shared layout, components, responsive styles, themes |
| `Dockerfile` | Container build and default command |
| `.github/workflows/ci.yml` | Continuous integration workflow |

## Routes

The main routes include:

- Authentication: `/login`, `/logout`, `/setup`
- Entries: `/`, `/entries/new`, `/entries/<id>`, `/entries/<id>/edit`, `/entries/<id>/delete`
- Map: `/map`
- Users and profiles: `/users`, `/users/<id>`, `/users/<id>/edit`, `/users/<id>/profile`, `/users/<id>/password`, `/directory`
- People: `/people`
- Media: `/uploads/<filename>` and entry attachment ZIP download
- AI: `/assistant` and related status, models, warmup, chat, and suggestion endpoints
- Helpers: tag lookup, weather lookup, and local map tile serving

For exact route behavior, consult the decorators and access checks in `app.py`.

## Local development

Use Python 3.11 or newer (the Docker image uses Python 3.11). From the repository root:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open the port shown by the application (the README's default is port 8000). Keep the terminal open to view errors and logs.

## Code conventions and safe changes

- Keep user-facing routes authenticated and retain the entry access checks.
- Do not expose uploaded files through an unprotected static directory; use the authenticated upload route.
- Validate and sanitize file handling, and do not trust the uploaded filename as a storage path.
- Keep database changes compatible with existing `diary.db` files. `db.create_all()` creates missing tables but is not a schema migration system.
- Keep uploads and database data outside disposable container layers.
- Do not commit real databases, uploaded media, passwords, tokens, or local AI secrets.
- Preserve progressive enhancement: core forms should still work when optional JavaScript enhancements are unavailable.
- Test keyboard use, mobile interactions, and permissions when changing the interactive UI.

## Testing

The GitHub Actions workflow is the source of truth for automated checks. Run the workflow locally where possible and test the following manually after UI changes:

1. Sign in and open the entry list.
2. Create an entry with required title and notes.
3. Add images and a GLB/GLTF file; verify upload, detail display, and download.
4. Test image viewer keyboard controls and touch navigation.
5. Edit an entry and remove an attachment.
6. Verify that an unrelated user cannot edit or view a private entry.
7. Test GPS, map, weather, and AI behavior when the relevant services are available.
8. Confirm existing database and uploads survive an application update.

## Contribution workflow

Read [CONTRIBUTING.md](../CONTRIBUTING.md) before opening a pull request. Keep pull requests focused, document user-visible behavior, and include reproduction steps for bug fixes.
