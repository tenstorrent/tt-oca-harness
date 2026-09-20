{inputs, ...}: let
  # Load ./uv.lock
  uv_workspace = inputs.uv2nix.lib.workspace.loadWorkspace {workspaceRoot = ../.;};

  # Editable overlay installs the local workspace packages in-place via $REPO_ROOT,
  # so source changes are picked up without rebuilding the venv.
  editableOverlay = uv_workspace.mkEditablePyprojectOverlay {
    root = "$REPO_ROOT";
  };

  # Non-editable overlay for third-party dependencies, preferring pre-built wheels.
  overlay = uv_workspace.mkPyprojectOverlay {
    sourcePreference = "wheel";
  };

  # Build a Python Package Set to build packages from UV using Wheels, and patch packages where needed.
  pythonSetWith = (
    pkgs: let
      lib = pkgs.lib;
      python = pkgs.python311;
    in
      (pkgs.callPackage inputs.pyproject-nix.build.packages {
        inherit python;
      }).overrideScope
      (
        lib.composeManyExtensions [
          # Prefer to build packages by Wheels
          inputs.pyproject-build-systems.overlays.wheel
          overlay
          # Inject setuptools for source-only packages that ship no wheel and rely on it implicitly.
          (
            final: prev: let
              patchSetupTools = (
                pkg: {
                  ${pkg} = prev.${pkg}.overrideAttrs (old: {
                    buildInputs = (old.buildInputs or []) ++ final.resolveBuildSystem {setuptools = [];};
                  });
                }
              );
            in
              lib.mergeAttrsList (
                lib.map patchSetupTools [
                  "cocotbext-jtag"
                  "antlr4-python3-runtime"
                  "cocotb"
                  "cocotb-bus"
                  "cocotbext-axi"
                  "cocotbext-i2c"
                ]
              )
          )
        ]
      )
  );
in
  # Returns pythonSet and the venv built from it; apply editableOverlay last so local packages shadow wheels.
  pkgs: rec {
    pythonSet = (pythonSetWith pkgs).overrideScope editableOverlay;
    venv = pythonSet.mkVirtualEnv "tt-oca-env" (uv_workspace.deps.all);
  }
