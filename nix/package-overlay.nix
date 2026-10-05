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
in
  # Build an attrset mapping each package name to its callPackage result, then merge into the overlay.
  lib.foldr (
    package: folded: folded // {"${package}" = final.callPackage ./packages/${package}.nix {};}
  ) {}
  packages
