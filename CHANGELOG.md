# Changelog

All notable changes to this project will be documented in this format.

## [Unreleased]

### Fixed
- Cards inside grids (team directory, admin panel) no longer get an extra top margin, so the first card no longer looks bigger
- AI assistant: the auto-picked model stays stable while installed; AI errors are logged to the server console
- Entry form: team members / finders dropdowns did not open (syntax error in multi-select.js)
- AI assistant: no hardcoded model any more; uses a model that is actually installed in Ollama, and the model picked in the UI is now used

### Added
- Tag autocomplete on the entry form (suggests existing tags while typing)
- Comprehensive GitHub documentation (README, CONTRIBUTING, SECURITY, LICENSE)

## [1.0.0] - 2025-XX-XX

### Added
- Initial release: Archain Field Diary
- Entry CRUD with title, notes, GPS, weather, tags
- Media attachments: images, PDFs, GLB/GLTF 3D models
- Multi-user support with admin/owner roles
- Person (finder) tracking separate from users
- Search by title, notes, tags
- Interactive map view (Leaflet)
- Auto weather from coordinates (wttr.in)
- Light/dark theme toggle
- User directory with profiles and selfies
- First-admin setup flow
- Docker support
- Raspberry Pi 5 optimized deployment

### Security
- Password hashing with Werkzeug
- Session-based authentication
- Owner/admin authorization checks