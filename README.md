# Archain Field Diary

A lightweight archaeological field diary built for Raspberry Pi 5 deployments. Log entries with time, GPS, photos, 3D models, and collaboration metadata, then share them with teammates.

## Features
- Add diary entries with timestamp, context, weather, and notes.
- Capture GPS coordinates directly from a mobile browser.
- Attach photos, PDFs, and 3D models (GLB/GLTF) rendered in-browser.
- Track team members and people who discovered each find.
- SQLite storage for simple multi-user access on the same network.

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:8000` from your desktop or mobile device on the same network.

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
This demo app does not include authentication. For production use, add login and backup routines.
