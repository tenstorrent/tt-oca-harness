# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

require 'asciidoctor/extensions'

module OCAH
  module RegisterMapCoverage
    def self.check(document, manifest)
      paths = File.readlines(manifest, chomp: true).reject(&:empty?).map { |path| File.realpath(path) }.uniq
      raise 'Register map manifest is empty' if paths.empty?

      sections = document.find_by(context: :section).group_by do |section|
        location = section.source_location
        File.realpath(location.file) if location && location.file
      end
      toc_depth = document.attr('toclevels', 2).to_i
      outline_depth = document.attr('outlinelevels', toc_depth).to_i
      errors = []
      paths.each do |path|
        expected = File.readlines(path).filter_map { |line| line[/\A===? (.+)$/, 1] }
        actual = sections.fetch(path, [])
        if expected.empty? || !actual.map(&:title).each_cons(expected.length).include?(expected)
          errors << "Missing or incomplete register map: #{path}"
        end
        actual.each do |section|
          if !document.attr?('toc') || section.level > toc_depth || section.level > outline_depth
            errors << "Register section exceeds contents/bookmark depth: #{path}: #{section.title} (level #{section.level})"
          end
        end
      end
      raise errors.join("\n") unless errors.empty?
    end
  end
end

Asciidoctor::Extensions.register do
  document.sourcemap = true
  treeprocessor do
    process do |doc|
      OCAH::RegisterMapCoverage.check(doc, doc.attr('register-map-manifest'))
      doc
    end
  end
end
