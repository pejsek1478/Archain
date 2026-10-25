# Contributing to Archain

Thanks for your interest in contributing! This project values simplicity and field-ready reliability over features.

## How to Contribute

### Reporting Issues
- Use the GitHub issue tracker
- Include steps to reproduce, expected vs actual behavior
- Mention your platform (Pi 5, desktop, Docker) and Python version

### Pull Requests
1. Fork the repo and create a feature branch
2. Make focused, minimal changes
3. Test locally on your target platform
4. Update docs if behavior changes
5. Submit PR with a clear description

### Code Style
- Follow existing patterns in `app.py`
- No new dependencies without discussion
- Keep templates simple; inline CSS/JS is fine for small things
- Run `ruff check .` and `ruff format .` if available

## Development Setup

```bash
git clone https://github.com/yourusername/Archain.git
cd Archain
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install ruff  # optional, for linting
python app.py
```

## Testing Checklist

Before submitting, verify:
- [ ] App starts without errors
- [ ] Login/logout works
- [ ] Create/edit/delete entries
- [ ] GPS capture works on mobile
- [ ] File uploads (image, PDF, GLB) render
- [ ] Search filters entries
- [ ] Map shows geotagged entries
- [ ] Admin can manage users/people
- [ ] Profile editing works
- [ ] Dark/light theme toggles
- [ ] Docker build succeeds

## Architecture Notes

- **Single-file app** (`app.py`) — keeps deployment simple on Pi
- **SQLite** — zero-config, portable, fine for <10 concurrent users
- **No migrations** — `db.create_all()` on startup; schema changes need manual SQL or fresh DB
- **Templates** — Jinja2, minimal JS (only for GPS, theme, 3D viewer)
- **Static files** — Served by Flask in dev; use nginx in production

## What We're Not Adding

- User registration (admin-only by design)
- Email/password reset (no SMTP in field)
- Complex permissions (owner/admin/user is enough)
- Real-time sync (offline-first by design)
- Mobile app (mobile browser works)

## Questions?

Open a discussion or issue. We prefer async text over meetings.