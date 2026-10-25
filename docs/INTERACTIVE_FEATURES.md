# Interactive Features Reference

This page documents the browser interactions implemented by Archain's templates and JavaScript.

## Entry form

| Interaction | How it works |
|---|---|
| GPS capture | The **Use GPS from device** control asks the browser for the current coordinates. Permission and device support are required. |
| Map pin | Selecting a point on the form map updates the latitude and longitude fields. |
| Tag autocomplete | Typing suggests existing tags. Use the up/down arrow keys and Enter or Tab to select a suggestion. |
| AI suggestions | When the AI feature is enabled, **Suggest title & tags** asks the configured model to propose metadata from the current notes. Review suggestions before applying them. |
| Multi-file picker | Repeated selections accumulate in the pending file list rather than replacing the previous selection. |
| Drag and drop | Drop files on the drop zone to add them to the pending list. |
| Clipboard paste | Paste a copied image/screenshot with Ctrl+V where the browser provides clipboard data. |
| Camera | On touch-oriented devices, **Take photo** is shown and can invoke the device's file/camera picker. Actual camera behavior depends on browser and operating system. |
| File preview/removal | Pending images show local previews. Each pending file can be removed before upload. |
| Upload progress | Supported browsers submit the form using XHR and display progress. If the required browser APIs are unavailable, the standard multi-file form remains available. |
| Draft recovery | The new-entry form uses browser-local draft persistence. It is not server-side autosave. |

## Entry detail

### Images

The full-screen viewer supports close, previous/next navigation, keyboard shortcuts, touch swipes, an image counter, and opening the original file. Keyboard focus is kept inside the viewer while it is open and restored when closed.

### 3D models

GLB and GLTF attachments are rendered with the web component `model-viewer`. The detail template enables camera controls and automatic rotation. Drag/pointer and touch gestures are handled by the component; exact performance depends on the browser, GPU, and model size.

The dashboard should remain a lightweight index. Open an entry to inspect its attached media in detail rather than relying on a full 3D viewer in every entry card.

### Other attachments

PDF and generic file attachments use file links. Browser behavior varies by file type. For entries with multiple attachments, the detail page provides a ZIP download.

## Keyboard reference

| Context | Key / gesture | Action |
|---|---|---|
| Image viewer | `Escape` | Close viewer |
| Image viewer | `←` / `→` | Previous / next image |
| Image viewer | Swipe left / right | Previous / next image on touchscreens |
| Tag autocomplete | `↑` / `↓` | Move through suggestions |
| Tag autocomplete | `Enter` or `Tab` | Select suggestion |

## Accessibility and compatibility notes

- The image viewer uses dialog semantics, an accessible label, focus management, and keyboard navigation.
- File previews use browser APIs such as `DataTransfer`, `FormData`, `XMLHttpRequest`, and object URLs when available.
- Very old browsers may fall back to the normal HTML file input without the enhanced queue/progress behavior.
- Large models may take time to load and may be slow on mobile hardware.
- Browser permissions for GPS, clipboard, and camera are controlled by the browser/operating system.
