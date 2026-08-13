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

  // Stock toolbar home-icon link: a background-image-only <a> with no
  // text content or accessible name at all.
  document.querySelectorAll('.home-link').forEach(function (el) {
    ensureAccessibleName(el, 'Home');
  });

  // Stock sidebar nav-tree expand/collapse toggle: an empty <button>,
  // same issue. Only present on pages whose sidebar has nested sections.
  document.querySelectorAll('.nav-item-toggle').forEach(function (el) {
    ensureAccessibleName(el, 'Toggle section');
  });

  // Horizontally-scrolling code blocks need to be in the tab order so
  // keyboard users can scroll them (axe's scrollable-region-focusable
  // rule). Antora renders these as "pre.highlight > code"; overflow is
  // detected directly per-element rather than assumed, since not every
  // code block actually overflows.
  document.querySelectorAll('.doc pre.highlight > code, .doc pre').forEach(function (el) {
    if (el.scrollWidth > el.clientWidth && !el.hasAttribute('tabindex')) {
      el.setAttribute('tabindex', '0');
    }
  });
})();
