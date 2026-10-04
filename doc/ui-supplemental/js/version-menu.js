// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Header version menu. The deployed site serves the main build at its root and
// the newest release of each published minor series under vX.Y/, listed in
// the root's versions.json (tools/doc/release_docs.py). A snapshot is built
// with OCAH_DOC_SNAPSHOT set to its tag, so its own root sits one directory
// below the deployed root. The menu stays hidden until versions.json lists
// more than one version, which keeps local and pull-request builds unchanged.
(function () {
  'use strict';

  var menu = document.querySelector('.versions-menu');
  if (!menu || !window.fetch || !window.URL) return;

  var siteRoot = new URL((menu.getAttribute('data-site-root') || '.') + '/', window.location.href);
  var snapshot = menu.getAttribute('data-snapshot') || '';
  var deployRoot = snapshot ? new URL('../', siteRoot) : siteRoot;
  var current = snapshot ? snapshot.replace(/^v(?=[0-9])/, '') : 'latest';

  fetch(new URL('versions.json', deployRoot).href, { cache: 'no-cache' })
    .then(function (response) {
      if (!response.ok) throw new Error(response.status);
      return response.json();
    })
    .then(function (versions) {
      if (!Array.isArray(versions) || versions.length < 2) return;
      var dropdown = menu.querySelector('.navbar-dropdown');
      versions.forEach(function (entry) {
        var link = document.createElement('a');
        link.className = 'navbar-item';
        link.href = new URL(entry.path, deployRoot).href;
        link.textContent = entry.version;
        if (entry.version === current) {
          link.classList.add('is-current');
          link.setAttribute('aria-current', 'page');
        }
        dropdown.appendChild(link);
      });
      menu.querySelector('.navbar-link').textContent = 'Version: ' + current;
      menu.classList.add('is-ready');
    })
    .catch(function () {});
})();
