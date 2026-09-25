# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Asciidoctor extension for the TRM PDF, enabled by the block-catalog attribute.
# Numbers and captions figures and tables, fills the linked lists of figures and
# tables, and adds references to each section's figures and tables.

require 'asciidoctor/extensions'

module OCAH
  class BlockCatalog < Asciidoctor::Extensions::TreeProcessor
    def process(document)
      return document unless document.attr? 'block-catalog'

      catalogs = { image: [], table: [] }
      owners = Hash.new { |hash, key| hash[key] = [] }
      document.find_by.each do |block|
        next unless catalogs.key? block.context

        catalog = catalogs[block.context]
        kind = block.context == :image ? 'Figure' : 'Table'
        number = catalog.length + 1
        owner = block.parent
        owner = owner.parent while owner && ![:section, :document].include?(owner.context)
        title = block.title? ? block.instance_variable_get(:@title) : fallback_title(block, owner)
        block.title = title.sub(/\A(?:Figure|Table)\s+\d+[.:]?\s+/, '')
        block.numeral = number
        block.caption = "#{kind} #{number}. "
        unless block.id
          id = "trm-#{kind.downcase}-#{number}"
          id += '-block' while document.catalog[:refs].key? id
          block.id = id
        end
        document.register :refs, [block.id, block]
        catalog << block
        owners[owner] << block
      end

      catalogs.each do |context, blocks|
        id = context == :image ? 'list-of-figures' : 'list-of-tables'
        section = document.find_by(id: id)&.first
        raise "Missing block catalog section: #{id}" unless section

        list = create_list(section, :ulist)
        list.style = 'unstyled'
        blocks.each do |block|
          label = block.caption + block.instance_variable_get(:@title)
          list.items << create_list_item(list, "<<#{block.id},#{label}>>")
        end
        section << list
      end

      owners.each do |owner, blocks|
        next unless owner

        links = blocks.map { |block| "<<#{block.id},#{block.caption.delete_suffix('. ')}>>" }
        paragraph = create_paragraph(owner, "Figures and tables: #{links.join('; ')}.",
                                     { 'role' => 'block-references' }, subs: :normal)
        position = owner.blocks.index { |block| block.context == :section } || owner.blocks.length
        owner.blocks.insert(position, paragraph)
      end
      document
    end

    def fallback_title(block, owner)
      return block.attr('alt', 'Diagram').tr('_', ' ') if block.context == :image

      section = owner&.instance_variable_get(:@title) || 'Reference'
      ancestor = owner&.parent
      while ancestor && ancestor.context != :document
        title = ancestor.instance_variable_get(:@title)
        if title&.start_with?('Address Map: ')
          section = "#{title.delete_prefix('Address Map: ')}.#{section}"
          break
        end
        ancestor = ancestor.parent
      end
      headings = block.rows.head.flatten.map(&:text)
      if headings.include?('Field') && headings.include?('Bits')
        "#{section} fields"
      elsif headings.include?('Address') && headings.include?('Name')
        "#{section} register list"
      elsif headings.any? && headings.all? { |heading| heading.match?(/\A\d+\z/) }
        "#{section} bit layout"
      else
        section
      end
    end
  end
end

Asciidoctor::Extensions.register do
  treeprocessor OCAH::BlockCatalog
end
