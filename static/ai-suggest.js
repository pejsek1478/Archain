/* "Suggest title & tags" button on the entry form. */
(function () {
  'use strict';

  const box = document.getElementById('ai-suggest');
  if (!box) return;

  const button = document.getElementById('suggest-button');
  const status = document.getElementById('suggest-status');
  const results = document.getElementById('suggest-results');
  const titleInput = document.querySelector('input[name="title"]');
  const notesInput = document.querySelector('textarea[name="notes"]');
  const tagsInput = document.querySelector('input[name="tags"]');
  const idleText = status.textContent;

  function setValue(input, value) {
    input.value = value;
    input.dispatchEvent(new Event('input', { bubbles: true })); // keeps draft + unsaved-changes logic in sync
  }

  function currentTags() {
    return tagsInput.value.split(',').map((tag) => tag.trim().toLowerCase()).filter(Boolean);
  }

  function chip(label, onClick) {
    const element = document.createElement('button');
    element.type = 'button';
    element.className = 'chip';
    element.textContent = label;
    element.addEventListener('click', () => {
      onClick();
      element.disabled = true;
    });
    return element;
  }

  function show(data) {
    results.replaceChildren();
    if (data.title) {
      results.append(chip(`Use title: ${data.title}`, () => setValue(titleInput, data.title)));
    }
    data.tags.forEach((tag) => {
      const exists = currentTags().includes(tag);
      const element = chip(`+ ${tag}`, () => {
        const tags = currentTags();
        if (!tags.includes(tag)) tags.push(tag);
        setValue(tagsInput, tags.join(', '));
      });
      element.disabled = exists;
      results.append(element);
    });
    results.hidden = !results.children.length;
    status.textContent = results.children.length
      ? 'Click a suggestion to use it.'
      : 'The model had no suggestion for these notes.';
  }

  button.addEventListener('click', async () => {
    const notes = notesInput.value.trim();
    if (notes.length < 15) {
      status.textContent = 'Write a few more words of field notes first.';
      notesInput.focus();
      return;
    }
    button.disabled = true;
    results.hidden = true;
    status.textContent = 'Thinking… a local model can take a little while.';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5 * 60 * 1000);
    try {
      const response = await fetch(box.dataset.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: titleInput.value, notes }),
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
      show(data);
    } catch (error) {
      status.textContent = error.name === 'AbortError'
        ? 'The model took too long. Try again.'
        : error.message || idleText;
    } finally {
      clearTimeout(timer);
      button.disabled = false;
    }
  });
})();
