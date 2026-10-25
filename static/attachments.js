/*
 * Attachment picker for the entry form.
 *
 * - Files from several picks, drops and pastes accumulate in one list.
 * - Images get a preview, every file has a remove button and a size readout.
 * - The form is posted with XHR so a progress bar can be shown.
 *
 * Without DataTransfer support (very old browsers) nothing is enhanced and the
 * plain <input type="file" multiple> keeps working.
 */
(function () {
  'use strict';

  const form = document.querySelector('form[data-upload-form]');
  if (!form) return;

  let supported = true;
  try {
    new DataTransfer();
  } catch (error) {
    supported = false;
  }
  if (!supported || !window.FormData || !window.XMLHttpRequest) return;

  const maxBytes = Number(form.dataset.maxBytes) || 0;
  const realInput = form.querySelector('#attachments-input');
  const pickInput = form.querySelector('#pick-input');
  const cameraInput = form.querySelector('#camera-input');
  const pickButton = form.querySelector('#pick-button');
  const cameraButton = form.querySelector('#camera-button');
  const dropzone = form.querySelector('#dropzone');
  const list = form.querySelector('#file-list');
  const summary = form.querySelector('#file-summary');
  const notice = form.querySelector('#file-notice');
  const saveButton = form.querySelector('#save-button');
  const progress = form.querySelector('#upload-progress');
  const progressBar = form.querySelector('#progress-bar');
  const progressText = form.querySelector('#progress-text');
  const cancelButton = form.querySelector('#cancel-upload');
  const formError = form.querySelector('#form-error');

  form.classList.add('enhanced');

  // Only offer the camera button on touch devices, where it opens the camera directly.
  if (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) {
    cameraButton.hidden = false;
  }

  let files = [];
  let busy = false;
  let currentRequest = null;
  const previewUrls = new Map();

  const fileKey = (file) => [file.name, file.size, file.lastModified].join('|');
  const totalSize = () => files.reduce((sum, file) => sum + file.size, 0);

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function showNotice(message) {
    notice.textContent = message;
    notice.hidden = !message;
  }

  function showFormError(message) {
    formError.textContent = message;
    formError.hidden = !message;
  }

  function kindOf(file) {
    const name = file.name.toLowerCase();
    if (file.type.startsWith('image/')) return 'image';
    if (name.endsWith('.glb') || name.endsWith('.gltf')) return '3D';
    if (file.type === 'application/pdf' || name.endsWith('.pdf')) return 'PDF';
    return 'FILE';
  }

  function previewFor(file) {
    if (!previewUrls.has(file)) previewUrls.set(file, URL.createObjectURL(file));
    return previewUrls.get(file);
  }

  function syncInput() {
    const transfer = new DataTransfer();
    files.forEach((file) => transfer.items.add(file));
    realInput.files = transfer.files;
  }

  function removeFile(file) {
    files = files.filter((candidate) => candidate !== file);
    if (previewUrls.has(file)) {
      URL.revokeObjectURL(previewUrls.get(file));
      previewUrls.delete(file);
    }
    showNotice('');
    render();
    document.dispatchEvent(new CustomEvent('archain:files-changed'));
  }

  function render() {
    syncInput();
    list.replaceChildren();

    files.forEach((file) => {
      const item = document.createElement('li');
      item.className = 'file-item';

      const thumb = document.createElement('div');
      thumb.className = 'file-thumb';
      thumb.setAttribute('aria-hidden', 'true');
      const kind = kindOf(file);
      if (kind === 'image') {
        const image = document.createElement('img');
        image.src = previewFor(file);
        image.alt = '';
        image.loading = 'lazy';
        image.decoding = 'async';
        thumb.append(image);
      } else {
        thumb.textContent = kind;
      }

      const meta = document.createElement('div');
      meta.className = 'file-meta';
      const name = document.createElement('span');
      name.className = 'file-name';
      name.textContent = file.name;
      const size = document.createElement('span');
      size.className = 'file-size';
      size.textContent = formatSize(file.size);
      meta.append(name, size);

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'icon-button';
      remove.setAttribute('aria-label', `Remove ${file.name}`);
      remove.textContent = '✕';
      remove.disabled = busy;
      remove.addEventListener('click', () => removeFile(file));

      item.append(thumb, meta, remove);
      list.append(item);
    });

    const over = maxBytes && totalSize() > maxBytes;
    summary.classList.toggle('over-limit', Boolean(over));
    if (!files.length) {
      summary.textContent = '';
    } else {
      const limit = maxBytes ? ` of ${Math.round(maxBytes / (1024 * 1024))} MB limit` : '';
      summary.textContent =
        `${files.length} new ${files.length === 1 ? 'file' : 'files'} · ${formatSize(totalSize())}${limit}` +
        (over ? ' — too large, remove some files.' : '');
    }
  }

  function addFiles(incoming, extraNotice) {
    let duplicates = 0;
    let added = 0;
    Array.from(incoming).forEach((file) => {
      if (files.some((existing) => fileKey(existing) === fileKey(file))) {
        duplicates += 1;
        return;
      }
      files.push(file);
      added += 1;
    });

    const parts = [];
    if (extraNotice) parts.push(extraNotice);
    if (duplicates) parts.push(`${duplicates} duplicate ${duplicates === 1 ? 'file was' : 'files were'} skipped.`);
    showNotice(parts.join(' '));

    if (added || duplicates) {
      render();
      if (added) document.dispatchEvent(new CustomEvent('archain:files-changed'));
    }
  }

  // ---- Buttons ------------------------------------------------------------
  pickButton.addEventListener('click', () => pickInput.click());
  cameraButton.addEventListener('click', () => cameraInput.click());
  [pickInput, cameraInput].forEach((input) => {
    input.addEventListener('change', () => {
      addFiles(input.files);
      input.value = ''; // lets the same file be picked again after removal
    });
  });

  // ---- Drag & drop (anywhere on the page, so a miss never opens the file) ---
  const hasFiles = (event) =>
    event.dataTransfer && Array.from(event.dataTransfer.types || []).includes('Files');
  let dragDepth = 0;

  document.addEventListener('dragenter', (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth += 1;
    dropzone.classList.add('is-dragging');
  });
  document.addEventListener('dragover', (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = busy ? 'none' : 'copy';
  });
  document.addEventListener('dragleave', (event) => {
    if (!hasFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropzone.classList.remove('is-dragging');
  });
  document.addEventListener('drop', (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    dragDepth = 0;
    dropzone.classList.remove('is-dragging');
    if (busy) return;

    const dropped = [];
    let folders = 0;
    const items = event.dataTransfer.items;
    if (items && items.length) {
      Array.from(items).forEach((item) => {
        if (item.kind !== 'file') return;
        const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
        if (entry && entry.isDirectory) {
          folders += 1;
          return;
        }
        const file = item.getAsFile();
        if (file) dropped.push(file);
      });
    } else {
      dropped.push(...Array.from(event.dataTransfer.files));
    }
    addFiles(dropped, folders ? 'Folders cannot be attached — select the files inside instead.' : '');
  });

  // ---- Paste screenshots / copied images -------------------------------------
  document.addEventListener('paste', (event) => {
    const pasted = event.clipboardData && event.clipboardData.files;
    if (!pasted || !pasted.length || busy) return;
    const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
    const named = Array.from(pasted).map((file, index) => {
      if (file.name && !/^image\.\w+$/i.test(file.name)) return file;
      const extension = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
      return new File([file], `pasted-${stamp}-${index + 1}.${extension}`, {
        type: file.type,
        lastModified: Date.now() + index,
      });
    });
    event.preventDefault();
    addFiles(named);
  });

  // ---- Submit with progress -----------------------------------------------------
  function setBusy(isBusy) {
    busy = isBusy;
    saveButton.disabled = isBusy;
    pickButton.disabled = isBusy;
    cameraButton.disabled = isBusy;
    saveButton.dataset.label = saveButton.dataset.label || saveButton.textContent;
    saveButton.textContent = isBusy ? 'Saving…' : saveButton.dataset.label;
    list.querySelectorAll('.icon-button').forEach((button) => { button.disabled = isBusy; });
  }

  function fail(message) {
    currentRequest = null;
    setBusy(false);
    progress.hidden = true;
    showFormError(message);
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (busy) return;
    showFormError('');

    if (maxBytes && totalSize() > maxBytes) {
      showNotice('The selected files are over the upload limit. Remove some files and try again.');
      summary.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    setBusy(true);
    const hasUploads = files.length > 0;
    progress.hidden = !hasUploads;
    progressBar.style.width = '0%';
    progressText.textContent = 'Uploading…';

    const request = new XMLHttpRequest();
    currentRequest = request;
    request.open('POST', form.action);
    request.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    request.setRequestHeader('Accept', 'application/json');

    request.upload.addEventListener('progress', (progressEvent) => {
      if (!progressEvent.lengthComputable) return;
      const ratio = progressEvent.loaded / progressEvent.total;
      progressBar.style.width = `${Math.round(ratio * 100)}%`;
      progressText.textContent = ratio >= 1
        ? 'Upload finished, saving…'
        : `Uploading ${Math.round(ratio * 100)}% (${formatSize(progressEvent.loaded)} of ${formatSize(progressEvent.total)})`;
    });

    request.addEventListener('load', () => {
      let data = null;
      try {
        data = JSON.parse(request.responseText);
      } catch (error) {
        data = null;
      }
      if (request.status >= 200 && request.status < 300 && data && data.redirect) {
        document.dispatchEvent(new CustomEvent('archain:saved'));
        window.location.assign(data.redirect);
        return;
      }
      if (request.status === 401 || request.status === 403) {
        fail('Your session has expired. Sign in again in another tab, then press Save once more.');
        return;
      }
      fail((data && data.error) || `Saving failed (error ${request.status}). Please try again.`);
    });
    request.addEventListener('error', () => {
      fail('Connection lost while saving. Your text and files are still here — try again when you have signal.');
    });
    request.addEventListener('abort', () => fail('Upload cancelled.'));

    request.send(new FormData(form));
  });

  cancelButton.addEventListener('click', () => {
    if (currentRequest) currentRequest.abort();
  });

  render();
})();
