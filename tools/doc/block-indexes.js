// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

'use strict'

const path = require('node:path').posix

exports.register = function () {
  this.on('documentsConverted', ({ contentCatalog }) => {
    const pages = contentCatalog.getPages().filter((page) => page.src.component === 'ocah-docs' && page.out)
    for (const [name, kind] of [['list-of-figures.adoc', 'image'], ['list-of-tables.adoc', 'table']]) {
      const index = pages.find((page) => page.src.module === 'ROOT' && page.src.relative === name)
      if (!index) throw new Error(`Missing TRM catalog page: ${name}`)
      const sections = []
      for (const page of [...pages].sort((a, b) => a.pub.url.localeCompare(b.pub.url))) {
        const entries = (page.blockCatalog || []).filter((entry) => entry.kind === kind)
        if (!entries.length) continue
        const url = path.relative(path.dirname(index.pub.url), page.pub.url)
        const links = entries.map((entry) => `<li><a href="${url}#${entry.id}">${entry.label}. ${entry.title}</a></li>`)
        sections.push(`<div class="sect1"><h2 id="catalog-topic-${sections.length + 1}">${page.asciidoc.doctitle}</h2><div class="sectionbody"><ul>${links.join('\n')}</ul></div></div>`)
      }
      index.contents = Buffer.concat([index.contents, Buffer.from(sections.join('\n'))])
    }
  })
}
