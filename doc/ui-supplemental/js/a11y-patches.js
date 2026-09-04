// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

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

  function applyScrollableCodeFix() {
    document.querySelectorAll('.doc pre.highlight > code, .doc pre').forEach(function (el) {
      if (el.scrollWidth > el.clientWidth && !el.hasAttribute('tabindex')) {
        el.setAttribute('tabindex', '0');
      }
    });
  }

  function applyPatches() {
    document.querySelectorAll('.home-link').forEach(function (el) {
      ensureAccessibleName(el, 'Home');
    });
    document.querySelectorAll('.nav-item-toggle').forEach(function (el) {
      ensureAccessibleName(el, 'Toggle section');
    });
    applyScrollableCodeFix();
    // Custom monospace fonts (Berkeley Mono) use font-display: swap, so a
    // code block's rendered width -- and therefore whether it overflows --
    // can change after this initial pass, once the font actually loads.
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(applyScrollableCodeFix);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyPatches);
  } else {
    applyPatches();
  }
})();