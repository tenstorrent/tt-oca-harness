final: prev:
let
  lib = prev.lib;
  getPackageNames =
    dir:
    lib.map (lib.strings.removeSuffix ".nix") (
      builtins.attrNames (
        lib.attrsets.filterAttrs (name: _: (lib.hasSuffix ".nix" name)) (builtins.readDir dir)
      )
    );
  packages = getPackageNames ./packages;
in
lib.foldr (
  package: folded: folded // { "${package}" = final.callPackage ./packages/${package}.nix { }; }
) { } packages
