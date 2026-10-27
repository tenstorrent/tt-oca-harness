# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
final: prev: let
  lib = prev.lib;
  # Returns package names by listing .nix files in a directory, stripping the .nix suffix.
  getPackageNames = dir:
    lib.map (lib.strings.removeSuffix ".nix") (
      builtins.attrNames (
        lib.attrsets.filterAttrs (name: _: (lib.hasSuffix ".nix" name)) (builtins.readDir dir)
      )
    );
  packages = getPackageNames ./packages;
  # nodejs_24 at the pinned nixpkgs (24.21.0) predates the 2026-10-21 Node.js security
  # release; nodejs_22 (22.23.4) carries it. Packages that run on Node in the image build
  # with it. Overriding nodejs itself would also rebuild Chromium, which only builds with Node.
  buildNpmPackage = prev.buildNpmPackage.override {nodejs = final.nodejs_22;};
  nodeRuntimePackages = [
    "antora"
    "antora-lunr-extension"
    "asciidoctor-kroki"
    "markdownlint-cli"
    "mermaid-cli"
    "vega-cli"
  ];
  # Build an attrset mapping each package name to its callPackage result.
  custom =
    lib.foldr (
      package: folded: folded // {"${package}" = final.callPackage ./packages/${package}.nix {};}
    ) {}
    packages;
in
  custom
  // lib.genAttrs nodeRuntimePackages (
    name: (custom.${name} or prev.${name}).override {inherit buildNpmPackage;}
  )
