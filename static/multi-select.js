// Custom multi-select component
(function () {
  'use strict';

  function initMultiSelect(container) {
    const trigger = container.querySelector('.multi-select-trigger');
    const dropdown = container.querySelector('.multi-select-dropdown');
    const search = container.querySelector('.multi-select-search');
    const options = container.querySelectorAll('.multi-select-option');
    const hiddenSelect = container.querySelector('select[multiple]');
    const tagsContainer = container.querySelector('.multi-select-tags');
    const placeholder = container.querySelector('.multi-select-placeholder');

    if (!trigger || !dropdown || !hiddenSelect) return;

    function updateTrigger() {
      const selected = Array.from(hiddenSelect.selectedOptions);
      tagsContainer.innerHTML = '';
      if (selected.length === 0) {
        placeholder.hidden = false;
      } else {
        placeholder.hidden = true;
        selected.forEach(opt => {
          const tag = document.createElement('span');
          tag.className = 'multi-select-tag';
          tag.dataset.value = opt.value;
          tag.innerHTML = `
            <span>${escapeHtml(opt.textContent)}</span>
            <button type="button" aria-label="Remove ${escapeHtml(opt.textContent)}">&times;</button>
          `;
          tag.querySelector('button').addEventListener('click', (e) => {
            e.stopPropagation();
            opt.selected = false;
            updateTrigger();
            hiddenSelect.dispatchEvent(new Event('change', { bubbles: true }));
          });
          tagsContainer.append(tag);
        });
      }
    }

    function escapeHtml(text) {
      return text.replace(/[&<>"']/g, c => ({'&':'&','<':'<','>':'>','"':'"',"'":'''}[c]));
    }

    function toggleDropdown() {
      const isOpen = dropdown.classList.toggle('open');
      trigger.classList.toggle('open', isOpen);
      trigger.setAttribute('aria-expanded', isOpen);
      if (isOpen) {
        search?.focus();
        filterOptions('');
      }
    }

    function closeDropdown() {
      dropdown.classList.remove('open');
      trigger.classList.remove('open');
      trigger.setAttribute('aria-expanded', 'false');
    }

    function filterOptions(query) {
      const q = query.toLowerCase().trim();
      options.forEach(opt => {
        const label = opt.querySelector('.multi-select-option-label').textContent.toLowerCase();
        const affiliation = opt.querySelector('.multi-select-option-affiliation')?.textContent.toLowerCase() || '';
        const match = !q || label.includes(q) || affiliation.includes(q);
        opt.style.display = match ? 'flex' : 'none';
      });
    }

    // Event listeners
    trigger.addEventListener('click', (e) => {
      if (e.target.closest('.multi-select-tag button')) return;
      toggleDropdown();
    });

    document.addEventListener('click', (e) => {
      if (!container.contains(e.target)) closeDropdown();
    });

    trigger.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeDropdown();
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggleDropdown();
      }
    });

    options.forEach(opt => {
      const checkbox = opt.querySelector('input[type="checkbox"]');
      opt.addEventListener('click', (e) => {
        if (e.target === checkbox) return;
        checkbox.checked = !checkbox.checked;
        const hiddenOpt = hiddenSelect.querySelector(`option[value="${checkbox.value}"]`);
        if (hiddenOpt) hiddenOpt.selected = checkbox.checked;
        updateTrigger();
        hiddenSelect.dispatchEvent(new Event('change', { bubbles: true }));
      });
      checkbox.addEventListener('change', () => {
        const hiddenOpt = hiddenSelect.querySelector(`option[value="${checkbox.value}"]`);
        if (hiddenOpt) hiddenOpt.selected = checkbox.checked;
        updateTrigger();
        hiddenSelect.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });

    search?.addEventListener('input', (e) => filterOptions(e.target.value));

    // Sync initial state
    hiddenSelect.style.display = 'none';
    updateTrigger();
    hiddenSelect.addEventListener('change', updateTrigger);

    // Initialize checkboxes from hidden select
    Array.from(hiddenSelect.options).forEach(opt => {
      const checkbox = container.querySelector(`.multi-select-option input[value="${opt.value}"]`);
      if (checkbox) checkbox.checked = opt.selected;
    });
  }

  // Auto-init on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('.multi-select').forEach(initMultiSelect);
    });
  } else {
    document.querySelectorAll('.multi-select').forEach(initMultiSelect);
  }

  // Export for dynamic content
  window.initMultiSelect = initMultiSelect;
})();