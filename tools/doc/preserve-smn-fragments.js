// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

'use strict'

// Antora's static redirect assigns a URL without carrying over the fragment.
// Preserve bookmarks when following the renamed SMN page's compatibility alias.
exports.register = function () {
  this.on('redirectsProduced', ({ contentCatalog }) => {
    for (const alias of contentCatalog.findBy({ family: 'alias' })) {
      if (alias.src.component !== 'ocah-docs' || alias.src.module !== 'ROOT' ||
          alias.src.relative !== 'smn.placeholder.adoc' || !alias.contents) continue
      const html = alias.contents.toString()
      alias.contents = Buffer.from(html.replace(
        /<script>location=("[^"]+")<\/script>/,
        '<script>location.replace($1 + location.hash)</script>'
      ))
    }
  })
}
