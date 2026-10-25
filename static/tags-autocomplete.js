/* Autocomplete for the comma separated "Tags" input on the entry form.
   Type "ir" and existing tags starting with it (e.g. "iron") are offered. */
(function () {
  'use strict';

  const input = document.getElementById('tags');
  const box = input && input.closest('.tag-ac');
  if (!input || !box) return;

  const MAX_ITEMS = 8;
  const list = document.createElement('ul');
  list.className = 'tag-ac-list';
  list.id = 'tag-ac-list';
  list.setAttribute('role', 'listbox');
  list.hidden = true;
  box.append(list);

  input.setAttribute('autocomplete', 'off');
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-controls', list.id);
  input.setAttribute('aria-expanded', 'false');

  let allTags = [];
  let matches = [];
  let active = -1;

  fetch(box.dataset.url, { headers: { Accept: 'application/json' } })
    .then((response) => (response.ok ? response.json() : { tags: [] }))
    .then((data) => { allTags = Array.isArray(data.tags) ? data.tags : []; })
    .catch(() => {});

  // The comma separated token the caret is currently in.
  function currentToken() {
    const value = input.value;
    const caret = input.selectionStart ?? value.length;
    const start = value.lastIndexOf(',', caret - 1) + 1;
    let end = value.indexOf(',', caret);
    if (end === -1) end = value.length;
    return { start, end, text: value.slice(start, end).trim().toLowerCase() };
  }

  function enteredTags(exceptStart) {
    const done = new Set();
    let offset = 0;
    input.value.split(',').forEach((part) => {
      if (offset !== exceptStart) {
        const name = part.trim().toLowerCase();
        if (name) done.add(name);
      }
      offset += part.length + 1;
    });
    return done;
  }

  function close() {
    list.hidden = true;
    list.replaceChildren();
    matches = [];
    active = -1;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }

  function setActive(index) {
    active = index;
    Array.from(list.children).forEach((item, i) => {
      const on = i === index;
      item.classList.toggle('active', on);
      item.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) {
        input.setAttribute('aria-activedescendant', item.id);
        item.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  function render() {
    const token = currentToken();
    if (!token.text) { close(); return; }
    const taken = enteredTags(token.start);
    const prefix = allTags.filter((tag) => tag.startsWith(token.text) && !taken.has(tag));
    const inside = allTags.filter((tag) => !tag.startsWith(token.text) && tag.includes(token.text) && !taken.has(tag));
    matches = prefix.concat(inside).slice(0, MAX_ITEMS);
    // Fully typed an existing tag: nothing to suggest, Enter should save the form as usual.
    if (!matches.length || (matches.length === 1 && matches[0] === token.text)) { close(); return; }

    list.replaceChildren();
    matches.forEach((tag, i) => {
      const item = document.createElement('li');
      item.className = 'tag-ac-item';
      item.id = `tag-ac-${i}`;
      item.setAttribute('role', 'option');
      const head = tag.startsWith(token.text) ? token.text.length : 0;
      const strong = document.createElement('strong');
      strong.textContent = tag.slice(0, head);
      item.append(strong, document.createTextNode(tag.slice(head)));
      // mousedown (not click) so the input keeps focus and blur doesn't close the list first
      item.addEventListener('mousedown', (event) => { event.preventDefault(); accept(i); });
      list.append(item);
    });
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    setActive(0);
  }

  function accept(index) {
    const tag = matches[index];
    if (!tag) return;
    const token = currentToken();
    const value = input.value;
    const before = value.slice(0, token.start).replace(/\s+$/, '');
    const after = value.slice(token.end).replace(/^\s*,?\s*/, '');
    const head = before ? `${before}${before.endsWith(',') ? '' : ','} ` : '';
    const inserted = `${head}${tag}, `;
    input.value = inserted + after;
    input.setSelectionRange(inserted.length, inserted.length);
    close();
    input.dispatchEvent(new Event('input', { bubbles: true })); // keeps draft + unsaved-changes logic in sync
    render();
  }

  input.addEventListener('input', render);
  input.addEventListener('click', render);
  input.addEventListener('blur', close);

  input.addEventListener('keydown', (event) => {
    if (list.hidden) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((active + 1) % matches.length);
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((active - 1 + matches.length) % matches.length);
    } else if ((event.key === 'Enter' || event.key === 'Tab') && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
      event.preventDefault();
      accept(active);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      close();
    }
  });
})();
