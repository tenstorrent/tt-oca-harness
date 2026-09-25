// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Asciidoctor extension for Antora TRM pages that numbers and captions figures
// and tables within each page, including generated register HTML tables. Adds
// section-local references and records metadata for the lists of figures and
// tables built by block-indexes.js.

'use strict'

function tableTitle (section, headings) {
  if (headings.includes('Bits') && headings.includes('Field')) return `${section} fields`
  if (headings.includes('Address') && headings.includes('Name')) return `${section} register list`
  if (headings.length && headings.every((text) => /^\d+$/.test(text))) return `${section} bit layout`
  return section
}

exports.register = function (registry, { file } = {}) {
  registry.treeProcessor(function () {
    this.process(function (doc) {
      // Keep legacy fragments at their first table while scoped IDs address
      // each map independently on pages containing several register banks.
      const legacyIds = new Set()
      for (const block of doc.findBy()) {
        if (block.getContext() !== 'pass') continue
        block.lines = [block.getSource().replace(/(<h[1-6]\b[^>]* data-register-alias="([^"]+)"[^>]*>)/g, (heading, tag, id) => {
          if (legacyIds.has(id) || doc.getCatalog().refs['$key?'](id)) return heading
          legacyIds.add(id)
          return `<span id="${id}"></span>${heading}`
        })]
      }
      if (!doc.hasAttribute('ocah-trm')) return doc
      const counts = { image: 0, table: 0 }
      const entries = []
      const owners = new Map()
      const refs = doc.getCatalog().refs
      const allocated = new Set()
      const uniqueId = (base) => {
        while (refs['$key?'](base) || allocated.has(base)) base += '-block'
        allocated.add(base)
        return base
      }
      const record = (kind, id, title) => {
        const label = `${kind === 'image' ? 'Figure' : 'Table'} ${++counts[kind]}`
        entries.push({ kind, id, title, label })
        return label
      }
      for (const block of doc.findBy()) {
        const kind = block.getContext()
        let owner = block.getParent()
        while (owner && !['section', 'document'].includes(owner.getContext())) owner = owner.getParent()
        const section = owner && owner.getTitle() || 'Reference'
        if (kind === 'pass' && block.getSource().includes('class="ocah-reg-html"')) {
          let heading = section
          let addressMap = ''
          block.lines = [block.getSource().replace(/<h[23]\b[^>]*>(.*?)<\/h[23]>|<table\b[^>]*>[\s\S]*?<\/table>/g, (html, title) => {
            if (title !== undefined) {
              if (title.startsWith('Address Map: ')) {
                addressMap = title.slice('Address Map: '.length)
                heading = title
              } else {
                heading = addressMap ? `${addressMap}.${title}` : title
              }
              return html
            }
            const headings = [...html.matchAll(/<th\b[^>]*>(.*?)<\/th>/g)].map((match) => match[1])
            const caption = tableTitle(heading, headings)
            const id = uniqueId(`trm-table-${counts.table + 1}`)
            const label = record('table', id, caption)
            return html.replace('<table', `<table id="${id}"`).replace(/(<table\b[^>]*>)/,
              `$1\n<caption class="title"><a href="#${id}">${label}</a>. ${caption}</caption>`)
          })]
          continue
        }
        if (!(kind in counts)) continue
        let title = block.getTitle()
        if (!title) {
          title = kind === 'image' ? block.getAttribute('alt', 'Diagram').replace(/_/g, ' ')
            : tableTitle(section, block.getRows().head.flat().map((cell) => cell.getText()))
        }
        title = title.replace(/^(?:Figure|Table)\s+\d+[.:]?\s+/, '')
        let id = block.getId()
        if (!id) {
          id = uniqueId(`trm-${kind === 'image' ? 'figure' : 'table'}-${counts[kind] + 1}`)
          block.setId(id)
        }
        const label = record(kind, id, title)
        block.setTitle(title)
        block.setCaption(`${label}. `)
        block.setNumeral(counts[kind])
        doc.$register('refs', [id, block])
        if (owner) {
          if (!owners.has(owner)) owners.set(owner, [])
          owners.get(owner).push(`<a href="#${encodeURIComponent(id)}">${label}</a>`)
        }
      }
      for (const [owner, links] of owners) {
        const blocks = owner.getBlocks()
        const firstSection = blocks.findIndex((block) => block.getContext() === 'section')
        const paragraph = this.createBlock(owner, 'pass', `<p class="block-references">Figures and tables: ${links.join('; ')}.</p>`)
        blocks.splice(firstSection < 0 ? blocks.length : firstSection, 0, paragraph)
      }
      if (file) file.blockCatalog = entries
      return doc
    })
  })
}
