// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Antora's TOC scans nested .sectN containers before its site script runs.
// Register partials use standalone headings, so their depth comes from the
// section in which they are included.
(function () {
  'use strict';

  var ids = new Set(Array.from(document.querySelectorAll('[id]'), function (el) {
    return el.id;
  }));

  function uniqueId(base) {
    var id = base;
    var suffix = 2;
    while (ids.has(id)) id = base + '-' + suffix++;
    ids.add(id);
    return id;
  }

  function slug(text) {
    return text.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-|-$/g, '');
  }

  document.querySelectorAll('.doc .ocah-reg-html').forEach(function (block) {
    var title = block.querySelector(':scope > h2');
    if (!title) return;
    var parent = block.closest('.sect1, .sect2, .sect3, .sect4, .sect5');
    var parentLevel = parent ? Number(parent.className.match(/\bsect(\d)\b/)[1]) : 0;
    if (parentLevel === 5) return;
    var level = parentLevel + 1;
    var mapId = uniqueId('register-map-' + slug(title.textContent.replace(/^Address Map:\s*/, '')));
    var links = new Map();
    var nodes = Array.from(block.childNodes);
    var sections = [];

    // Table styling must not depend on the heading depth of the host page.
    block.querySelectorAll(':scope > p + table').forEach(function (table) {
      table.classList.add('register-list');
    });
    block.querySelectorAll(':scope > h3 + table').forEach(function (table) {
      table.classList.add('register-fields');
    });

    block.classList.add('sect' + level);
    var content = block;
    if (level === 1) {
      content = document.createElement('div');
      content.className = 'sectionbody';
      block.appendChild(content);
    }

    nodes.forEach(function (node) {
      if (node.nodeType !== 1 || !/^H[23]$/.test(node.tagName)) {
        (sections.length ? sections[sections.length - 1].content : content).appendChild(node);
        return;
      }

      var depth = Math.min(level + (node === title ? 0 : 1), 5);
      var id = node.id;
      if (id) {
        if (document.getElementById(id) !== node) id = uniqueId(mapId + '-' + id);
        links.set(node.id, id);
      } else {
        id = node === title ? mapId : uniqueId(mapId + '-' + slug(node.textContent));
      }
      var heading = document.createElement('h' + (depth + 1));
      heading.id = id;
      heading.textContent = node.textContent;
      node.remove();

      while (sections.length && sections[sections.length - 1].depth >= depth) sections.pop();
      var container = sections.length ? sections[sections.length - 1].content : content;
      if (depth === level) {
        block.insertBefore(heading, level === 1 ? content : null);
      } else {
        var section = document.createElement('div');
        section.className = 'sect' + depth;
        section.appendChild(heading);
        container.appendChild(section);
        sections.push({ depth: depth, content: section });
      }
    });

    block.querySelectorAll('a[href^="#"]').forEach(function (link) {
      var id = links.get(link.getAttribute('href').slice(1));
      if (id) link.setAttribute('href', '#' + id);
    });
  });
})();
