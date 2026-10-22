# Changelog

All notable changes to this project will be documented in this format.

## [Unreleased]

### Added
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