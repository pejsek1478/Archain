/*
 * Full-screen image viewer for entry attachments.
 * Any element with [data-lightbox] (data-src, data-name) opens it; arrows, swipe and keys move between images.
 */
(function () {
  'use strict';

  const triggers = Array.from(document.querySelectorAll('[data-lightbox]'));
  if (!triggers.length) return;

  const overlay = document.createElement('div');
  overlay.className = 'lightbox';
  overlay.hidden = true;
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', 'Image viewer');
  overlay.innerHTML = `
    <button type="button" class="lightbox-close icon-button" aria-label="Close viewer">✕</button>
    <button type="button" class="lightbox-nav prev icon-button" aria-label="Previous image">‹</button>
    <figure>
      <img alt="" />
      <figcaption>
        <span class="lb-name"></span>
        <span class="lb-count"></span>
        <a class="lb-open" target="_blank" rel="noopener">Open original</a>
      </figcaption>
    </figure>
    <button type="button" class="lightbox-nav next icon-button" aria-label="Next image">›</button>
  `;
  document.body.append(overlay);

  const image = overlay.querySelector('img');
  const nameLabel = overlay.querySelector('.lb-name');
  const countLabel = overlay.querySelector('.lb-count');
  const openLink = overlay.querySelector('.lb-open');
  const closeButton = overlay.querySelector('.lightbox-close');
  const prevButton = overlay.querySelector('.prev');
  const nextButton = overlay.querySelector('.next');

  let index = 0;
  let lastFocus = null;

  function show(position) {
    index = (position + triggers.length) % triggers.length;
    const trigger = triggers[index];
    image.src = trigger.dataset.src;
    image.alt = trigger.dataset.name || '';
    nameLabel.textContent = trigger.dataset.name || '';
    countLabel.textContent = triggers.length > 1 ? `${index + 1} / ${triggers.length}` : '';
    openLink.href = trigger.dataset.src;
    prevButton.hidden = nextButton.hidden = triggers.length < 2;

    // warm the cache for the neighbours so paging feels instant
    [index - 1, index + 1].forEach((neighbour) => {
      if (triggers.length < 2) return;
      new Image().src = triggers[(neighbour + triggers.length) % triggers.length].dataset.src;
    });
  }

  function open(position) {
    lastFocus = document.activeElement;
    show(position);
    overlay.hidden = false;
    document.body.classList.add('lightbox-open');
    closeButton.focus();
  }

  function close() {
    overlay.hidden = true;
    image.removeAttribute('src');
    document.body.classList.remove('lightbox-open');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  triggers.forEach((trigger, position) => {
    trigger.addEventListener('click', () => open(position));
  });

  closeButton.addEventListener('click', close);
  prevButton.addEventListener('click', () => show(index - 1));
  nextButton.addEventListener('click', () => show(index + 1));
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay || event.target.tagName === 'FIGURE') close();
  });

  document.addEventListener('keydown', (event) => {
    if (overlay.hidden) return;
    if (event.key === 'Escape') {
      close();
    } else if (event.key === 'ArrowLeft') {
      show(index - 1);
    } else if (event.key === 'ArrowRight') {
      show(index + 1);
    } else if (event.key === 'Tab') {
      // keep keyboard focus inside the viewer
      const focusable = Array.from(overlay.querySelectorAll('button:not([hidden]), a[href]'));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  // swipe left / right on touch screens
  let touchStartX = null;
  overlay.addEventListener('touchstart', (event) => {
    touchStartX = event.touches[0].clientX;
  }, { passive: true });
  overlay.addEventListener('touchend', (event) => {
    if (touchStartX === null || triggers.length < 2) return;
    const delta = event.changedTouches[0].clientX - touchStartX;
    touchStartX = null;
    if (Math.abs(delta) > 50) show(index + (delta < 0 ? 1 : -1));
  });
})();
