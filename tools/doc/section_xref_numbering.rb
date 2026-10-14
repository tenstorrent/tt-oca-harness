# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

require 'asciidoctor/extensions'

# A section below sectnumlevels shows no number in its heading, but Asciidoctor
# still flags it as numbered, so a short-style cross-reference to it renders as
# "Section N.N.N". Clearing the flag makes the reference render the title.
Asciidoctor::Extensions.register do
  treeprocessor do
    process do |doc|
      depth = doc.attr('sectnumlevels', 3).to_i
      doc.find_by(context: :section).each do |section|
        section.numbered = false if section.level > depth
      end
      doc
    end
  end
end
