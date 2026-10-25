# Deployment and Operations

This document covers local installation, Docker, Raspberry Pi/Linux service operation, configuration, backups, and offline maps.

## Requirements

- Python 3.11 or newer for a direct install.
- Network access for dependency installation; internet access is optional for core operation after dependencies are installed, except for online map/weather services and any remote AI endpoint.
- Writable application directory for the SQLite database, uploads, and optional local map tiles.
- A modern browser for enhanced upload interactions and 3D model previews.

## Direct installation

```bash
git clone https://github.com/pejsek1478/Archain.git
cd Archain
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open the local address printed by Flask. The project README documents port 8000 as the default. If you are running it on another machine, use that machine's LAN address and ensure its firewall allows the chosen port only from trusted clients.

On a fresh database, visit `/setup` and create the first admin/owner account.

## Configuration

| Variable | Purpose | Default / behavior |
|---|---|---|
| `SECRET_KEY` | Flask session signing key | The source currently has a development fallback. Set a unique random value in deployments; never reuse a public example secret. |
| `ARCHAIN_MAX_UPLOAD_MB` | Maximum combined upload request size in MB | `200` |
| `ARCHAIN_TILE_URL` | Map tile URL template | OpenStreetMap tile URL |
| `ARCHAIN_TILE_ATTRIBUTION` | Map attribution text | OpenStreetMap contributors |
| `ARCHAIN_AI` | Enable/disable optional assistant | Read `ai/ai_config.json` and AI section in README |
| `ARCHAIN_AI_BACKEND` | AI backend (`ollama` or `openai`) | Config file default |
| `ARCHAIN_AI_URL` | AI server base URL | Usually local Ollama |
| `ARCHAIN_AI_MODEL` | Preferred model name | Automatic selection if unset |
| `ARCHAIN_AI_API_KEY` | Optional API bearer token | Empty |
| `ARCHAIN_AI_THREADS`, `ARCHAIN_AI_CTX`, `ARCHAIN_AI_MAX_TOKENS` | AI resource/output tuning | See README AI configuration table |

The database path is currently built in `app.py` as `diary.db` in the application directory. Do not assume setting `DATABASE_URL` changes it unless the application code is updated to read that variable.

### Generate a session secret

Generate a secret and set it in the service environment; do not paste it into source control.

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Docker

Build the image from the repository root:

```bash
docker build -t archain:local .
```

Run it with persistent database and uploads directories. Create the directories first:

```bash
mkdir -p data uploads
touch data/diary.db
docker run -d --name archain \
  -p 8000:8000 \
  -e SECRET_KEY='REPLACE_WITH_A_LONG_RANDOM_SECRET' \
  -e ARCHAIN_MAX_UPLOAD_MB=200 \
  -v "$PWD/data/diary.db:/app/diary.db" \
  -v "$PWD/uploads:/app/uploads" \
  --restart unless-stopped \
  archain:local
```

The exact host paths can be changed to suit your deployment. Verify that the container user can write to the mounted directories. Back up the mounted database and uploads together. Do not remove the volumes or directories when recreating the container.

The current Dockerfile uses Python 3.11 slim, installs `requirements.txt`, copies the project, exposes port 8000, and runs `python app.py`.

## Raspberry Pi / systemd

For a long-running Linux installation, run Archain under a dedicated unprivileged user. Adjust paths and usernames to your environment.

Create `/etc/systemd/system/archain.service`:

```ini
[Unit]
Description=Archain Field Diary
After=network.target

[Service]
Type=simple
User=archain
WorkingDirectory=/opt/Archain
EnvironmentFile=-/etc/archain.env
ExecStart=/opt/Archain/.venv/bin/python app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Create `/etc/archain.env` with restricted permissions and a unique secret:

```bash
sudo install -m 600 /dev/null /etc/archain.env
sudoedit /etc/archain.env
```

Add a line such as `SECRET_KEY=your-generated-secret` to that file. Then enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now archain
sudo systemctl status archain
journalctl -u archain -f
```

Make sure the service user can write to the application directory's database and uploads paths. If you deploy behind a reverse proxy, configure HTTPS and match its upload-size limit to Archain's limit.

## Offline map tiles

The map defaults to online OpenStreetMap tiles. For offline field use, prepare a tile set for the relevant area and configure one of these approaches.

### Local tile server

Run a tile server that serves tiles using the `/{z}/{x}/{y}.png` URL pattern, then set:

```bash
ARCHAIN_TILE_URL=http://127.0.0.1:8080/{z}/{x}/{y}.png
ARCHAIN_TILE_ATTRIBUTION="Local map data"
```

If Archain runs in Docker, `127.0.0.1` refers to the container itself. Use the correct service/container host name or network address.

### Local tile directory

Place prepared tiles in `tiles/{z}/{x}/{y}.png` and configure:

```bash
ARCHAIN_TILE_URL=/tiles/{z}/{x}/{y}.png
ARCHAIN_TILE_ATTRIBUTION="Local map data"
```

Ensure you have the right to download and redistribute the selected map data, and retain the attribution required by its license.

## Backups and upgrades

Back up both the database and uploads. They represent different parts of the same records: database rows store metadata and filenames, while the actual media files live in the uploads directory.

For a simple stopped-app backup:

```bash
# Stop the service/container first so SQLite and files are consistent.
cp diary.db diary.db.backup
cp -a uploads uploads.backup
```

Use the actual paths configured by your service/container. For live deployments, use a SQLite-aware backup method or stop the app briefly. Store backups on separate storage and test restoring them.

Before upgrading:

1. Back up the database and uploads.
2. Read the changelog and inspect code/config changes.
3. Install the pinned dependencies in the intended environment.
4. Restart the service/container.
5. Review logs and test login, entry creation, media viewing, and downloads.

The app calls `db.create_all()` to create missing tables, but this does not migrate existing table schemas. If a future release changes the schema, follow the release-specific migration instructions.

## Security checklist

- Set a unique `SECRET_KEY`; do not use the development fallback in a production deployment.
- Keep the service behind HTTPS when used across untrusted networks.
- Restrict firewall access to intended clients; do not expose the development server directly to the public internet.
- Keep the OS, Python dependencies, and reverse proxy updated.
- Restrict permissions on the database, uploads, and environment file.
- Back up data and test restoration.
- Keep AI endpoints private; diary text is sent to the configured AI server.
- Review [SECURITY.md](../SECURITY.md) before reporting a vulnerability.
