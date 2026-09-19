{
  description = "Environment and Docker Container for OCAH";

  inputs = {
    # Ensure git submodules are checked out when the flake is fetched.
    self.submodules = true;

    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    # All inputs follow the same nixpkgs to avoid duplicate versions in the closure.
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs = {
        pyproject-nix.follows = "pyproject-nix";
        nixpkgs.follows = "nixpkgs";
      };
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs = {
        pyproject-nix.follows = "pyproject-nix";
        uv2nix.follows = "uv2nix";
        nixpkgs.follows = "nixpkgs";
      };
    };
  };

  outputs = inputs @ {
    self,
    nixpkgs,
    pyproject-nix,
    uv2nix,
    pyproject-build-systems,
    ...
  }: let
    # Merge project helpers into nixpkgs.lib so they travel with lib.
    lib = nixpkgs.lib.extend (_: _: self.lib);
  in {
    lib = import ./nix/lib.nix {inherit inputs self;};

    overlays.default = import ./nix/package-overlay.nix;

    devShells = lib.forAllSystems (
      system: let
        pkgs = lib.pkgsFor system;
        ocah_shell = {bundle_uv ? true}: let
          ocah = import ./ocah_deps.nix {inherit inputs pkgs bundle_uv;};
          container = import ./nix/container.nix {
            inherit
              self
              inputs
              pkgs
              ocah
              ;
          };
        in
          with ocah;
            pkgs.mkShell {
              # Need Fuse-overlayfs installed to be able to run podman containers
              packages = ocah_pkgs ++ (with pkgs; [fuse-overlayfs]);
              env =
                ocah_env
                // rec {
                  OCAH_DOCKER_IMAGE = "localhost/${container.name}:${OCAH_CONTAINER_HASH}";
                  OCAH_DOC_HTML_IMAGE = OCAH_DOCKER_IMAGE;
                  OCAH_DOC_PDF_IMAGE = OCAH_DOCKER_IMAGE;
                  OCAH_EDA_IMAGE = OCAH_DOCKER_IMAGE;
                  OCAH_CONTAINER_HASH = container.hash;
                };
            };
      in rec {
        # Default to the lighter shell; opt into with_uv_deps when Python tooling is needed.
        default = without_uv_deps;
        without_uv_deps = ocah_shell {bundle_uv = false;};
        with_uv_deps = ocah_shell {bundle_uv = true;};
      }
    );

    dockerContainers = lib.forAllSystems (
      system: let
        # Build the image with the native toolchain but always target x86_64-linux contents.
        nativePkgs = lib.pkgsFor system;
        pkgs = lib.pkgsFor "x86_64-linux";
      in {
        without_uv_deps =
          nativePkgs.dockerTools.buildLayeredImage
          (import ./nix/container.nix {
            inherit self inputs pkgs;
            bundle_uv = false;
          }).config;
        with_uv_deps =
          nativePkgs.dockerTools.buildLayeredImage
          (import ./nix/container.nix {
            inherit self inputs pkgs;
            bundle_uv = true;
            name = "ocah-uv-container";
          }).config;
      }
    );
    # Always evaluate hashes against x86_64-linux so every platform agrees on the same tag.
    containerHashes = let
      pkgs = lib.pkgsFor "x86_64-linux";
    in {
      with_uv_deps =
        (import ./nix/container.nix {
          inherit self inputs pkgs;
          bundle_uv = true;
        }).hash;
      without_uv_deps =
        (import ./nix/container.nix {
          inherit self inputs pkgs;
          bundle_uv = false;
        }).hash;
    };

    formatter = lib.forAllSystems (
      system: let
        pkgs = lib.pkgsFor system;
        # Wrap alejandra in a script to run a static diff for formatting - used in CI
        alejandra-check = pkgs.writeShellApplication {
          name = "alejandra-check";
          runtimeInputs = [pkgs.alejandra pkgs.git];
          text = ''
            failed=0
            tmpdir="$(mktemp -d)/"
            tmpdir_rel="''${tmpdir#/}"
            trap 'rm -rf "$tmpdir"' EXIT
            if [[ -n "''${NIX_FMT_CHECK_NO_COLOUR:-}" ]]; then
              colour_flag="--color=never"
            else
              colour_flag="--color=always"
            fi
            for f in "$@"; do
              rel="''${f#./}"
              dst="$tmpdir$rel"
              mkdir -p "$(dirname "$dst")"
              alejandra --quiet - < "$f" > "$dst"
              diff_out=$(git diff --no-index "$colour_flag" -- "$f" "$dst" 2>&1 || true)
              if [ -n "$diff_out" ]; then
                echo "''${diff_out//$tmpdir_rel/}"
                failed=1
              fi
            done
            exit $failed
          '';
        };
      in
        pkgs.treefmt.withConfig {
          settings.formatter.default = {
            command = "${pkgs.alejandra}/bin/alejandra";
            includes = ["*.nix"];
          };
          settings.formatter.check = {
            command = "${alejandra-check}/bin/alejandra-check";
            includes = ["*.nix"];
          };
        }
    );
  };
}
