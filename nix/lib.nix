{
  inputs,
  self,
  ...
}: let
  lib = inputs.nixpkgs.lib;
in {
  # Build for multiple architectures
  forAllSystems = lib.genAttrs lib.systems.flakeExposed;

  # Instantiates nixpkgs for a given platform (system) with the project overlay applied.
  pkgsFor = system:
    import inputs.nixpkgs {
      inherit system;
      overlays = [
        (self.overlays.default)
      ];
    };
}
