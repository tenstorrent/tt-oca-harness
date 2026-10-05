// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Header version menu, listing the root's versions.json (tools/doc/release_docs.py).
// A release snapshot is built with OCAH_DOC_SNAPSHOT set to its tag and served
// one directory below the deployed root. The menu stays hidden unless a release
// is published.
(function () {
  'use strict';

  var menu = document.querySelector('.versions-menu');
  if (!menu) return;
  var snapshot = menu.getAttribute('data-snapshot');
  var siteRoot = new URL(menu.getAttribute('data-site-root') + '/', window.location.href);
  var deployRoot = snapshot ? new URL('../', siteRoot) : siteRoot;
  var current = snapshot ? snapshot.replace(/^v/, '') : 'latest';

  fetch(new URL('versions.json', deployRoot))
    .then(function (response) { return response.json(); })
    .then(function (versions) {
      if (versions.length < 2) return;
      versions.forEach(function (entry) {
        var link = document.createElement('a');
        link.className = 'navbar-item';
        link.href = new URL(entry.path, deployRoot).href;
        link.textContent = entry.version;
        if (entry.version === current) link.setAttribute('aria-current', 'page');
        menu.querySelector('.navbar-dropdown').appendChild(link);
      });
      menu.querySelector('.navbar-link').textContent = 'Version: ' + current;
      menu.classList.add('is-ready');
    })
    .catch(function () {});
})();
