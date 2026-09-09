// Image viewer for article block diagrams.
// Replaces the nonfunctional medium-zoom cursor hints with a working local
// modal overlay. Only images inside .doc .imageblock that are not already
// wrapped in an <a> and are not logo/icon images are enhanced.
// Initialised idempotently; captions and alt text are preserved; the page
// degrades gracefully when JavaScript is unavailable.
(function () {
  'use strict';

  var VIEWER_ID = 'ocah-img-viewer';
  var MIN_ZOOM = 0.1;
  var MAX_ZOOM = 8;
  var ZOOM_STEP = 0.25;

  // ---- Eligibility --------------------------------------------------------

  function isEligible(img) {
    // Already linked
    if (img.closest('a')) return false;
    // Logos and icons (in navbar, footer, home-panel)
    if (img.closest('.navbar') || img.closest('.footer') || img.closest('.home-panel')) return false;
    // Not inside .doc .imageblock
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
    overlay.setAttribute('tabindex', '-1');
    overlay.innerHTML = [
      '<div class="ocah-viewer-backdrop"></div>',
      '<div class="ocah-viewer-panel">',
      '  <div class="ocah-viewer-toolbar">',
      '    <button class="ocah-viewer-btn ocah-viewer-zoom-in"  type="button" aria-label="Zoom in">+</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-zoom-out" type="button" aria-label="Zoom out">−</button>',
      '    <button class="ocah-viewer-btn ocah-viewer-fit"      type="button" aria-label="Fit to screen">⤢</button>',
      '    <a      class="ocah-viewer-btn ocah-viewer-orig"     target="_blank" rel="noopener" aria-label="Open original image">↗</a>',
      '    <button class="ocah-viewer-btn ocah-viewer-close"    type="button" aria-label="Close viewer">✕</button>',
      '  </div>',
      '  <div class="ocah-viewer-stage">',
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
  var trigger = null;   // the button that opened the viewer
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
    return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, s));
  }

  function fitToStage() {
    var sw = stage.clientWidth;
    var sh = stage.clientHeight;
    var iw = img.naturalWidth || img.width || sw;
    var ih = img.naturalHeight || img.height || sh;
    scale = clampScale(Math.min(sw / iw, sh / ih, 1));
    panX = 0;
    panY = 0;
    applyTransform();
  }

  function zoomBy(delta) {
    scale = clampScale(scale + delta);
    applyTransform();
  }

  // ---- Focus trap ---------------------------------------------------------

  function focusableEls() {
    return Array.prototype.slice.call(
      viewer.querySelectorAll('button:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])')
    );
  }

  function trapFocus(e) {
    var els = focusableEls();
    if (!els.length) return;
    var first = els[0];
    var last = els[els.length - 1];
    if (e.key === 'Tab') {
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
  }

  // ---- Scroll lock --------------------------------------------------------

  var savedOverflow = '';

  function lockScroll() {
    savedOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  }

  function unlockScroll() {
    document.body.style.overflow = savedOverflow;
  }

  // ---- Open/close ---------------------------------------------------------

  function open(btn, src, alt, caption) {
    trigger = btn;
    img.src = src;
    img.alt = alt || '';
    viewer.setAttribute('aria-label', caption ? ('Image viewer: ' + caption) : 'Image viewer');
    origBtn.href = src;
    viewer.classList.add('is-open');
    lockScroll();
    // Inert the rest of the page
    document.querySelectorAll('body > *:not(#' + VIEWER_ID + ')').forEach(function (el) {
      el.setAttribute('aria-hidden', 'true');
      el.setAttribute('data-ocah-inert', '1');
    });
    // Wait for image to load before fitting
    if (img.complete) {
      fitToStage();
    } else {
      img.addEventListener('load', fitToStage, { once: true });
    }
    document.addEventListener('keydown', onKeyDown);
    viewer.focus();
  }

  function close() {
    viewer.classList.remove('is-open');
    unlockScroll();
    document.querySelectorAll('[data-ocah-inert]').forEach(function (el) {
      el.removeAttribute('aria-hidden');
      el.removeAttribute('data-ocah-inert');
    });
    document.removeEventListener('keydown', onKeyDown);
    img.src = '';
    if (trigger) { trigger.focus(); trigger = null; }
  }

  // ---- Key handler --------------------------------------------------------

  function onKeyDown(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key === '+' || e.key === '=') { zoomBy(ZOOM_STEP); return; }
    if (e.key === '-') { zoomBy(-ZOOM_STEP); return; }
    if (e.key === '0') { fitToStage(); return; }
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

  // ---- Init ---------------------------------------------------------------

  function init() {
    if (document.getElementById(VIEWER_ID)) return; // idempotent
    if (!document.querySelector('.doc .imageblock')) return; // nothing to enhance

    // Check at least one eligible image exists before building viewer DOM
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

    // Toolbar button actions
    closeBtn.addEventListener('click', close);
    fitBtn.addEventListener('click', fitToStage);
    zoomInBtn.addEventListener('click', function () { zoomBy(ZOOM_STEP); });
    zoomOutBtn.addEventListener('click', function () { zoomBy(-ZOOM_STEP); });

    // Backdrop click to close
    viewer.querySelector('.ocah-viewer-backdrop').addEventListener('click', close);

    // Pan events on stage
    stage.addEventListener('mousedown', onMouseDown);
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    stage.addEventListener('touchstart', onTouchStart, { passive: false });
    stage.addEventListener('touchmove', onTouchMove, { passive: false });
    stage.addEventListener('touchend', onTouchEnd);

    // Zoom on scroll
    stage.addEventListener('wheel', function (e) {
      e.preventDefault();
      zoomBy(e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP);
    }, { passive: false });

    // Enhance eligible imageblock images
    document.querySelectorAll('.doc .imageblock').forEach(function (block) {
      var im = block.querySelector('img');
      if (!im || !isEligible(im)) return;

      var captionEl = block.querySelector('.title');
      var caption = captionEl ? captionEl.textContent.trim() : '';

      // Wrap image in a button so it is keyboard reachable
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ocah-viewer-trigger';
      btn.setAttribute('aria-label', 'View image' + (caption ? ': ' + caption : ''));
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
