// Runtime accessibility patches for gaps in the stock antora-ui-default
// markup that can't be fixed via CSS alone -- these three elements are
// rendered without any accessible name or keyboard focusability in the
// bundle itself, independent of this project's own templates/overrides.
(function () {
  'use strict';

  function ensureAccessibleName(el, label) {
    if (!el) return;
    var hasName =
      el.getAttribute('aria-label') ||
      el.getAttribute('aria-labelledby') ||
      el.getAttribute('title') ||
      (el.textContent && el.textContent.trim().length > 0);
    if (!hasName) {
      el.setAttribute('aria-label', label);
    }
  }

  function applyPatches() {
    document.querySelectorAll('.home-link').forEach(function (el) {
      ensureAccessibleName(el, 'Home');
    });
    document.querySelectorAll('.nav-item-toggle').forEach(function (el) {
      ensureAccessibleName(el, 'Toggle section');
    });
    document.querySelectorAll('.doc pre.highlight > code, .doc pre').forEach(function (el) {
      if (el.scrollWidth > el.clientWidth && !el.hasAttribute('tabindex')) {
        el.setAttribute('tabindex', '0');
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyPatches);
  } else {
    applyPatches();
  }
})();