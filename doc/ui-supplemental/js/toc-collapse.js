// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

(function () {
  'use strict';

  // The stock site script builds both TOCs synchronously after this script.
  document.addEventListener('DOMContentLoaded', function () {
    var expanded = new Map();
    var menus = [];

    document.querySelectorAll('.toc .toc-menu').forEach(function (menu, menuIndex) {
      var parents = [];
      var entries = Array.from(menu.querySelectorAll('li[data-level]'), function (item, index) {
        var link = item.querySelector('a');
        var level = Number(item.dataset.level);
        while (parents.length && parents[parents.length - 1].level >= level) parents.pop();
        var entry = { item: item, link: link, level: level, parent: parents[parents.length - 1], children: [] };
        if (entry.parent) entry.parent.children.push(entry);
        item.id = 'toc-item-' + menuIndex + '-' + index;
        parents.push(entry);
        if (!expanded.has(link.hash)) expanded.set(link.hash, level < 3);
        return entry;
      });

      entries.forEach(function (entry) {
        if (!entry.children.length) return;
        entry.link.setAttribute('aria-controls', entry.children.map(function (child) { return child.item.id; }).join(' '));
        entry.link.addEventListener('click', function (event) {
          if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
          expanded.set(entry.link.hash, !expanded.get(entry.link.hash));
          render();
        });
      });

      menu.classList.add('is-collapsible');
      menus.push(entries);

      // Keep the current section visible in the overview without reopening
      // branches the reader has collapsed while scrolling through the page.
      new MutationObserver(function (changes) {
        if (changes.some(function (change) { return change.target.tagName === 'A'; })) highlight(entries);
      }).observe(menu, { subtree: true, attributes: true, attributeFilter: ['class'] });
    });

    function highlight(entries) {
      entries.forEach(function (entry) {
        if (entry.item.classList.contains('is-active-ancestor')) entry.item.classList.remove('is-active-ancestor');
      });
      entries.forEach(function (entry) {
        if (!entry.item.hidden || !entry.link.classList.contains('is-active')) return;
        var parent = entry.parent;
        while (parent && parent.item.hidden) parent = parent.parent;
        if (parent) parent.item.classList.add('is-active-ancestor');
      });
    }

    function render() {
      var embedded = document.querySelector('.toc.embedded');
      var height = embedded ? embedded.offsetHeight : 0;
      menus.forEach(function (entries) {
        entries.forEach(function (entry) {
          entry.item.hidden = !!entry.parent && (entry.parent.item.hidden || !expanded.get(entry.parent.link.hash));
          if (entry.children.length) {
            entry.link.setAttribute('aria-expanded', String(expanded.get(entry.link.hash)));
          }
        });
        highlight(entries);
      });

      // Expanding the inline contents moves every section below it.
      if (embedded && embedded.offsetHeight !== height) {
        var target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
        if (target) {
          var toolbar = document.querySelector('.toolbar');
          var inset = toolbar ? toolbar.getBoundingClientRect().bottom : 0;
          window.scrollTo({ top: window.scrollY + target.getBoundingClientRect().top - inset, behavior: 'instant' });
        }
      }
    }

    function revealHash() {
      menus.forEach(function (entries) {
        var target = entries.find(function (entry) { return entry.link.hash === window.location.hash; });
        if (!target) return;
        for (var parent = target.parent; parent; parent = parent.parent) expanded.set(parent.link.hash, true);
      });
      render();
    }

    revealHash();
    window.addEventListener('hashchange', revealHash);
  });
})();
