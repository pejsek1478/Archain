# Archain User Guide

Archain is a browser-based field diary for recording observations, finds, locations, collaborators, and supporting files. This guide describes the features available in the repository.

## Contents

- [Signing in and first-time setup](#signing-in-and-first-time-setup)
- [The dashboard](#the-dashboard)
- [Creating an entry](#creating-an-entry)
- [Uploading and interacting with files](#uploading-and-interacting-with-files)
- [Editing and deleting entries](#editing-and-deleting-entries)
- [Search and map](#search-and-map)
- [People and profiles](#people-and-profiles)
- [AI assistant](#ai-assistant)
- [Themes and mobile use](#themes-and-mobile-use)
- [Troubleshooting](#troubleshooting)

## Signing in and first-time setup

1. Start the application (see [Deployment](DEPLOYMENT.md)).
2. Open the application URL in a browser.
3. On a new database with no users, follow the setup page to create the first owner/admin account.
4. Sign in with that account.

The application requires authentication for diary pages and uploaded files. The owner/admin can manage accounts from the user-management page. Do not expose a fresh installation to an untrusted network before changing its configuration and creating the owner account.

## The dashboard

The root URL (`/`) is the entry list. Entries are ordered newest first. Use the search field to find entries by title, notes, or tag. Open an entry to see its full notes, location, people, tags, and attachments.

The list is a searchable index of diary records, rather than a separate file manager. Large media such as 3D models are best inspected from an individual entry.

## Creating an entry

Choose **New entry** and provide:

- **Title** — required.
- **Entry time** — the time of the observation; it can be left blank.
- **Location label** — a human-readable location such as a trench or unit.
- **Latitude and longitude** — optional coordinates.
- **Field notes** — required narrative describing the find or observation.
- **Weather / conditions** — optional; when blank, Archain may try to retrieve weather for supplied coordinates.
- **Tags** — comma-separated labels. Existing tags can be suggested by the autocomplete control.
- **Team members and people** — associate logged-in users and recorded contributors/finders where applicable.
- **Attachments** — images, PDF documents, GLB/GLTF models, and other files.

### GPS and map interaction

- Select **Use GPS from device** to request the browser's current location. The browser may ask for permission, and the device needs location services.
- You can select a point on the form map to populate coordinates.
- GPS is optional. A location label can be saved without coordinates.
- Weather lookup depends on usable coordinates and network access to the configured weather service.

### Drafts

The new-entry form saves an unsent draft in the browser when draft persistence is enabled. Drafts are browser-local; they are not a substitute for saving an entry and may not follow you to another device or browser profile.

## Uploading and interacting with files

### Add files

The entry form supports multiple files. In supported browsers, you can:

- Choose files more than once; selections are accumulated.
- Drag files onto the drop area.
- Paste a screenshot or image from the clipboard with **Ctrl+V**.
- Use **Take photo** on supported touch devices to open the device camera.
- Preview selected images, inspect file names and sizes, and remove a selected file before submitting.
- Watch the upload progress indicator during submission.

The application enforces a combined request-size limit. The default is 200 MB, configurable with `ARCHAIN_MAX_UPLOAD_MB`. A reverse proxy may impose a smaller limit of its own.

### Supported previews

- **Images:** shown as thumbnails and can be opened in the full-screen image viewer where the page provides the viewer trigger.
- **3D models:** GLB and GLTF files use the browser's `model-viewer` component. The viewer supports camera interaction and automatic rotation on the entry detail page.
- **PDFs and other files:** shown as file items and can be opened directly if the browser supports the file type.

Browser support and model complexity affect whether a file can be displayed. A file that cannot be previewed may still be downloadable.

### Full-screen image viewer

When an image has a lightbox trigger, click it to open the viewer. Available controls include:

- **Close:** close button or `Escape`.
- **Previous / next:** on-screen arrows or keyboard arrow keys.
- **Touch:** swipe left or right on a touchscreen.
- **Open original:** open the underlying uploaded image in a separate tab.

The viewer keeps keyboard focus inside the dialog and returns focus to the triggering element when closed.

### Downloading attachments

Open an entry's details to access its attachments. Individual files can be opened from their file links. When an entry has multiple attachments, use **Download all (ZIP)** to download them together.

### Edit attachments

Open an editable entry and use the current-attachments list to select files for removal. You can also add more files in the same edit operation. Selected removals take effect when the entry update succeeds.

## Editing and deleting entries

The entry owner and an admin can edit or delete an entry. Editing can update notes, time, coordinates, weather, tags, linked people/users, and attachments. Other users may be able to view entries shared with them but cannot automatically edit entries they do not own.

Deletion removes the diary entry and its attachment records; the application also attempts to delete the corresponding stored files. Treat deletion as destructive and maintain backups.

## Search and map

- **Search:** matches entry title, notes, and tags.
- **Map page:** shows entries with geographic coordinates.
- **Entry location:** the detail page displays coordinates and an embedded map when coordinates are available.

The default map uses OpenStreetMap tiles and requires network access. For offline deployments, see [Offline map tiles](DEPLOYMENT.md#offline-map-tiles).

## People and profiles

Archain distinguishes between:

- **Users:** accounts that sign in to the application.
- **People:** named contributors/finders who do not need an account.

The directory lists team profiles. A profile may include role, contact details, biography, photo, and linked entries. Users can edit their own profile; administrative pages provide account and people management.

## AI assistant

The optional AI assistant can answer questions about accessible diary entries, explain computed diary statistics, and suggest titles and tags while writing an entry.

- It requires a local Ollama server by default, or a compatible OpenAI-style server.
- It is optional; core diary functions work without a running model server.
- The assistant only receives entries the signed-in user is allowed to access.
- A locally hosted model keeps diary prompts on that machine. If you configure a remote model endpoint, relevant diary text is sent to that endpoint.
- AI output can be wrong. Verify important details against the original notes.

Setup and tuning instructions are in the [main README](../README.md#ai-assistant).

## Themes and mobile use

Use the theme control in the application to switch between light and dark themes. The entry form supports touch-friendly file picking and camera capture where the browser exposes those capabilities. GPS and camera access require browser permissions.

## Troubleshooting

| Problem | Things to check |
|---|---|
| Redirected to setup | No user has been created yet; complete first-time setup. |
| Login does not work | Check the username/password and that the correct database is being used. |
| GPS does not populate | Allow location permission, enable device location, and use a supported browser context. |
| Weather is blank | Add coordinates and check outbound network access to the weather provider. |
| Upload rejected | Check the application upload limit and any reverse-proxy request-size limit. |
| Image/model preview fails | Try opening the original file; confirm the format is supported and the file is valid. |
| Map tiles are blank | Check network access to the tile server or configure local tiles. |
| AI assistant is unavailable | Check the assistant status, model server URL, and whether a model is installed. |
| Existing records appear missing | Check that the process is using the intended `diary.db` and uploads directory. Do not overwrite them during an upgrade. |

For security issues, follow [SECURITY.md](../SECURITY.md). For development changes, see [Architecture and development](ARCHITECTURE.md).
