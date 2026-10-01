// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Keyboard shortcuts for the docs site: "/" and Cmd/Ctrl+K focus the search
// field; "n"/"N" go to the next/previous page (when pagination links exist
// on the current page); "j"/"k" step between section headings on the
// current page. All single-key shortcuts are suppressed while focus is in
// an input, textarea, or contenteditable element, so normal typing (e.g.
// typing "/" into the search box itself) is never intercepted.
(function () {
  'use strict';

  function isTypingContext(el) {
    if (!el) return false;
    var tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }

  function focusSearch() {
    var input = document.getElementById('search-input');
    if (!input) return;
    input.focus();
    input.select();
  }

  function goToPage(selector) {
    var link = document.querySelector(selector);
    if (link) window.location.href = link.href;
  }

  function getHeadings() {
    return Array.prototype.slice.call(
      document.querySelectorAll('.doc h1, .doc h2, .doc h3, .doc h4, .doc h5, .doc h6')
    );
  }

  // Sticky navbar + toolbar height, so a heading counts as "current" once
  // it's scrolled just past the fixed header rather than exactly at the
  // very top of the viewport.
  var STICKY_OFFSET = 96;

  function currentHeadingIndex(headings) {
    var idx = -1;
    for (var i = 0; i < headings.length; i++) {
      var top = headings[i].getBoundingClientRect().top;
      if (top <= STICKY_OFFSET) {
        idx = i;
      } else {
        break;
      }
    }
    return idx;
  }

  function jumpToHeading(direction) {
    var headings = getHeadings();
    if (!headings.length) return;
    var idx = currentHeadingIndex(headings);
    var targetIdx = direction === 'next'
      ? Math.min(idx + 1, headings.length - 1)
      : Math.max(idx - 1, 0);
    var target = headings[targetIdx];
    if (!target) return;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    // Headings aren't normally focusable; make the target one briefly
    // focusable so keyboard/screen-reader users land somewhere sensible,
    // without adding a permanent tabindex to every heading on the page.
    target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  }

  document.addEventListener('keydown', function (e) {
    if (document.querySelector('.ocah-image-viewer[aria-modal="true"]')) return;

    // Cmd+K (Mac) / Ctrl+K (Windows/Linux) - checked first, and allowed to
    // fire even while already focused in the search box (harmless no-op).
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      focusSearch();
      return;
    }

    // Everything below is a plain single key with no modifier (Shift is
    // allowed through deliberately, since "N" is Shift+n on most layouts).
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (isTypingContext(document.activeElement)) return;

    switch (e.key) {
      case '/':
        e.preventDefault();
        focusSearch();
        break;
      case 'n':
        goToPage('nav.pagination .next a');
        break;
      case 'N':
        goToPage('nav.pagination .prev a');
        break;
      case 'j':
        jumpToHeading('next');
        break;
      case 'k':
        jumpToHeading('prev');
        break;
    }
  });
})();
