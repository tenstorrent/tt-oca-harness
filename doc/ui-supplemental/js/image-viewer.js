// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Local image viewer for article block diagrams.
// Replaces the nonfunctional medium-zoom cursor hints with a working modal
// overlay. Only images inside .doc .imageblock that are not already wrapped
// in <a> and are not logo/icon images are enhanced. Initialised idempotently;
// captions and alt text are preserved; the page degrades gracefully without JS.
(function () {
  'use strict';

  var VIEWER_ID = 'ocah-img-viewer';
  var MAX_ZOOM = 8;
  var ZOOM_STEP = 0.25;
  var PAN_STEP = 40; // px per arrow key press

  // ---- Eligibility --------------------------------------------------------

  function isEligible(img) {
    if (img.closest('a')) return false;
    if (img.closest('.navbar') || img.closest('.footer') || img.closest('.home-panel')) return false;
    if (!img.closest('.doc .imageblock')) return false;
    return true;
  }

  // ---- Viewer DOM ---------------------------------------------------------

  function buildViewer() {
    var overlay = document.createElement('div');
    overlay.id = VIEWER_ID;
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Image viewer');
    overlay.innerHTML = [
      '<div class="ocah-viewer-backdrop"></div>',
      '<div class="ocah-viewer-panel">',
      '  <div class="ocah-viewer-toolbar">',
      '    <button class="ocah-viewer-btn ocah-viewer-zoom-in"  type="button" aria-label="Zoom in">+</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-zoom-out" type="button" aria-label="Zoom out">−</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-fit"      type="button" aria-label="Fit image to screen (keyboard: 0)">⤢</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-pan-left"  type="button" aria-label="Pan left (keyboard: ←)">◀</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-pan-right" type="button" aria-label="Pan right (keyboard: →)">▶</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-pan-up"    type="button" aria-label="Pan up (keyboard: ↑)">▲</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-pan-down"  type="button" aria-label="Pan down (keyboard: ↓)">▼</button>',
      '    <a      class="ocah-viewer-btn ocah-viewer-orig"     target="_blank" rel="noopener" aria-label="Open original image in new tab">↗</a>',
      '    <button class="ocah-viewer-btn ocah-viewer-close"    type="button" aria-label="Close viewer (keyboard: Escape)">✕</button>',
      '  </div>',
      '  <div class="ocah-viewer-stage" aria-hidden="true">',
      '    <img class="ocah-viewer-img" alt="" draggable="false">',
      '  </div>',
      '</div>',
    ].join('');
    document.body.appendChild(overlay);
    return overlay;
  }

  // ---- State --------------------------------------------------------------

  var viewer = null;
  var stage = null;
  var img = null;
  var origBtn = null;
  var fitBtn = null;
  var zoomInBtn = null;
  var zoomOutBtn = null;
  var closeBtn = null;
  var panLeftBtn = null;
  var panRightBtn = null;
  var panUpBtn = null;
  var panDownBtn = null;
  var trigger = null;
  var scale = 1;
  var panX = 0;
  var panY = 0;
  var isPanning = false;
  var panStartX = 0;
  var panStartY = 0;
  var panStartPanX = 0;
  var panStartPanY = 0;
  var touchDist0 = 0;
  var touchScale0 = 1;

  // ---- Zoom/pan helpers --------------------------------------------------

  function applyTransform() {
    img.style.transform = 'translate(' + panX + 'px,' + panY + 'px) scale(' + scale + ')';
  }

  function clampScale(s) {
    return Math.max(0.01, Math.min(MAX_ZOOM, s));
  }

  // fitToStage: scale chosen to show the whole image; no minimum enforced.
  function fitToStage() {
    var sw = stage.clientWidth;
    var sh = stage.clientHeight;
    var iw = img.naturalWidth || img.width || sw;
    var ih = img.naturalHeight || img.height || sh;
    // Never scale up beyond 1:1 on fit; do not clamp downward.
    scale = Math.min(sw / iw, sh / ih, 1);
    panX = 0;
    panY = 0;
    applyTransform();
  }

  function zoomBy(delta) {
    scale = clampScale(scale + delta);
    applyTransform();
  }

  function panBy(dx, dy) {
    panX += dx;
    panY += dy;
    applyTransform();
  }

  // ---- Modal isolation ----------------------------------------------------
  //
  // We use the HTML `inert` attribute to make background content non-focusable
  // and non-interactive. Before opening, save each element's prior inert state
  // so we can restore it exactly on close rather than blindly clearing it.

  var savedInert = []; // [{el, wasInert}]

  function isolateBackground() {
    savedInert = [];
    document.querySelectorAll('body > *').forEach(function (el) {
      if (el === viewer) return;
      savedInert.push({ el: el, wasInert: el.inert });
      el.inert = true;
    });
    // Signal to site keyboard-shortcuts.js that the viewer is open
    window.ocahViewerOpen = true;
  }

  function restoreBackground() {
    savedInert.forEach(function (item) {
      item.el.inert = item.wasInert;
    });
    savedInert = [];
    window.ocahViewerOpen = false;
  }

  // ---- Focus trap ---------------------------------------------------------
  //
  // Because background elements are inert, only the viewer's own focusable
  // elements remain reachable. We still wrap Tab/Shift+Tab at the boundaries
  // so focus cycles within the toolbar buttons and the original-image link.

  function focusableEls() {
    return Array.prototype.slice.call(
      viewer.querySelectorAll('button:not([disabled]),a[href]')
    );
  }

  function trapFocus(e) {
    if (e.key !== 'Tab') return;
    var els = focusableEls();
    if (!els.length) return;
    var first = els[0];
    var last = els[els.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first || document.activeElement === viewer) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  // ---- Scroll lock --------------------------------------------------------

  var savedBodyOverflow = '';

  function lockScroll() {
    savedBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }

  function unlockScroll() {
    document.body.style.overflow = savedBodyOverflow;
  }

  // ---- Open/close ---------------------------------------------------------

  function open(btn, src, alt, caption) {
    trigger = btn;
    img.src = src;
    img.alt = alt || '';
    // Update accessible label with caption and/or alt for distinguishability
    var label = 'Image viewer';
    if (caption) label += ': ' + caption;
    else if (alt) label += ': ' + alt;
    viewer.setAttribute('aria-label', label);
    // Update original-link label
    origBtn.setAttribute('aria-label', 'Open ' + (caption || alt || 'image') + ' in new tab');
    origBtn.href = src;

    viewer.classList.add('is-open');
    lockScroll();
    isolateBackground();

    if (img.complete && img.naturalWidth) {
      fitToStage();
    } else {
      img.addEventListener('load', fitToStage, { once: true });
    }

    // Focus first toolbar button (not the overlay itself) so Shift+Tab wraps
    var els = focusableEls();
    if (els.length) els[0].focus();
    document.addEventListener('keydown', onKeyDown);
  }

  function close() {
    viewer.classList.remove('is-open');
    document.removeEventListener('keydown', onKeyDown);
    unlockScroll();
    restoreBackground();
    img.src = '';
    if (trigger) { trigger.focus(); trigger = null; }
  }

  // ---- Key handler --------------------------------------------------------

  function onKeyDown(e) {
    switch (e.key) {
      case 'Escape': e.preventDefault(); close(); return;
      case '+': case '=': e.preventDefault(); zoomBy(ZOOM_STEP); return;
      case '-': e.preventDefault(); zoomBy(-ZOOM_STEP); return;
      case '0': e.preventDefault(); fitToStage(); return;
      case 'ArrowLeft':  e.preventDefault(); panBy(PAN_STEP, 0); return;
      case 'ArrowRight': e.preventDefault(); panBy(-PAN_STEP, 0); return;
      case 'ArrowUp':    e.preventDefault(); panBy(0, PAN_STEP); return;
      case 'ArrowDown':  e.preventDefault(); panBy(0, -PAN_STEP); return;
    }
    trapFocus(e);
  }

  // ---- Mouse pan ----------------------------------------------------------

  function onMouseDown(e) {
    if (e.button !== 0) return;
    isPanning = true;
    panStartX = e.clientX;
    panStartY = e.clientY;
    panStartPanX = panX;
    panStartPanY = panY;
    stage.style.cursor = 'grabbing';
    e.preventDefault();
  }

  function onMouseMove(e) {
    if (!isPanning) return;
    panX = panStartPanX + (e.clientX - panStartX);
    panY = panStartPanY + (e.clientY - panStartY);
    applyTransform();
  }

  function onMouseUp() {
    isPanning = false;
    stage.style.cursor = '';
  }

  // ---- Touch pinch/pan ---------------------------------------------------

  function touchDist(t) {
    var dx = t[0].clientX - t[1].clientX;
    var dy = t[0].clientY - t[1].clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function onTouchStart(e) {
    if (e.touches.length === 2) {
      touchDist0 = touchDist(e.touches);
      touchScale0 = scale;
      isPanning = false;
    } else if (e.touches.length === 1) {
      isPanning = true;
      panStartX = e.touches[0].clientX;
      panStartY = e.touches[0].clientY;
      panStartPanX = panX;
      panStartPanY = panY;
    }
  }

  function onTouchMove(e) {
    e.preventDefault();
    if (e.touches.length === 2) {
      var d = touchDist(e.touches);
      scale = clampScale(touchScale0 * (d / touchDist0));
      applyTransform();
    } else if (e.touches.length === 1 && isPanning) {
      panX = panStartPanX + (e.touches[0].clientX - panStartX);
      panY = panStartPanY + (e.touches[0].clientY - panStartY);
      applyTransform();
    }
  }

  function onTouchEnd() {
    isPanning = false;
  }

  // ---- Viewport resize ---------------------------------------------------

  function onResize() {
    if (viewer && viewer.classList.contains('is-open')) {
      fitToStage();
    }
  }

  // ---- Init ---------------------------------------------------------------

  function init() {
    if (document.getElementById(VIEWER_ID)) return;
    if (!document.querySelector('.doc .imageblock')) return;

    var allImgs = document.querySelectorAll('.doc .imageblock img');
    var anyEligible = false;
    for (var k = 0; k < allImgs.length; k++) {
      if (isEligible(allImgs[k])) { anyEligible = true; break; }
    }
    if (!anyEligible) return;

    viewer = buildViewer();
    stage = viewer.querySelector('.ocah-viewer-stage');
    img = viewer.querySelector('.ocah-viewer-img');
    origBtn = viewer.querySelector('.ocah-viewer-orig');
    fitBtn = viewer.querySelector('.ocah-viewer-fit');
    zoomInBtn = viewer.querySelector('.ocah-viewer-zoom-in');
    zoomOutBtn = viewer.querySelector('.ocah-viewer-zoom-out');
    closeBtn = viewer.querySelector('.ocah-viewer-close');
    panLeftBtn = viewer.querySelector('.ocah-viewer-pan-left');
    panRightBtn = viewer.querySelector('.ocah-viewer-pan-right');
    panUpBtn = viewer.querySelector('.ocah-viewer-pan-up');
    panDownBtn = viewer.querySelector('.ocah-viewer-pan-down');

    closeBtn.addEventListener('click', close);
    fitBtn.addEventListener('click', fitToStage);
    zoomInBtn.addEventListener('click', function () { zoomBy(ZOOM_STEP); });
    zoomOutBtn.addEventListener('click', function () { zoomBy(-ZOOM_STEP); });
    panLeftBtn.addEventListener('click', function () { panBy(PAN_STEP, 0); });
    panRightBtn.addEventListener('click', function () { panBy(-PAN_STEP, 0); });
    panUpBtn.addEventListener('click', function () { panBy(0, PAN_STEP); });
    panDownBtn.addEventListener('click', function () { panBy(0, -PAN_STEP); });

    viewer.querySelector('.ocah-viewer-backdrop').addEventListener('click', close);

    stage.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    stage.addEventListener('touchstart', onTouchStart, { passive: false });
    stage.addEventListener('touchmove', onTouchMove, { passive: false });
    stage.addEventListener('touchend', onTouchEnd);
    stage.addEventListener('wheel', function (e) {
      e.preventDefault();
      zoomBy(e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP);
    }, { passive: false });

    window.addEventListener('resize', onResize);

    document.querySelectorAll('.doc .imageblock').forEach(function (block) {
      var im = block.querySelector('img');
      if (!im || !isEligible(im)) return;

      var captionEl = block.querySelector('.title');
      var caption = captionEl ? captionEl.textContent.trim() : '';
      // Use caption, then alt, then fallback for a distinguishable name
      var triggerLabel = 'View enlarged: ' + (caption || im.alt || 'figure');

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ocah-viewer-trigger';
      btn.setAttribute('aria-label', triggerLabel);
      im.parentNode.insertBefore(btn, im);
      btn.appendChild(im);

      btn.addEventListener('click', function () {
        open(btn, im.src, im.alt, caption);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
