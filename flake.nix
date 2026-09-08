{
  description = "Environment and Docker Container for OCAH";

  inputs = {
    self.submodules = true;
    
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

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

  outputs =
    inputs@{
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      # Load helper functions defined in nix/lib.nix
      lib = nixpkgs.lib.extend (_: _: self.lib);
  
      
    in
    {
      lib = import ./nix/lib.nix {inherit inputs self;};
      
      overlays.default = import ./nix/package-overlay.nix;
      
      devShells = lib.forAllSystems (
        system: let 
          pkgs = lib.pkgsFor system;
          ocah_shell = {bundle_uv ? true} : let
            ocah = import ./ocah_deps.nix {inherit inputs pkgs bundle_uv;}; 
            container = import ./nix/container.nix {inherit self inputs pkgs ocah;};
          in with ocah; pkgs.mkShell {
              # Need Fuse-overlayfs installed to be able to run podman containers
              packages = ocah_pkgs ++ (with pkgs; [fuse-overlayfs]);
              env = ocah_env // rec {
                OCAH_DOCKER_IMAGE = "localhost/${container.name}:${OCAH_CONTAINER_HASH}";
                OCAH_DOC_HTML_IMAGE = OCAH_DOCKER_IMAGE;
                OCAH_DOC_PDF_IMAGE = OCAH_DOCKER_IMAGE;
                OCAH_EDA_IMAGE = OCAH_DOCKER_IMAGE;
                OCAH_CONTAINER_HASH = container.hash;
              };
            };
          in rec {
            default = with_uv_deps;
            no_uv_deps = ocah_shell {bundle_uv = false;};
            with_uv_deps = ocah_shell {bundle_uv = true;};
          }
      );

      dockerContainers = lib.forAllSystems (system: let 
        nativePkgs = lib.pkgsFor system;
        pkgs = lib.pkgsFor "x86_64-linux";
      in ( let 
        ocah_container_config = (import ./nix/container.nix {inherit self inputs pkgs; bundle_uv=false;}).config; 
      in {
        default = nativePkgs.dockerTools.buildLayeredImage ocah_container_config;
        # Stream Compressed Image to stdout to save on disk space?
        # - Image tag remains the same, so this is an option, if piped into docker/podman load
        stream = nativePkgs.dockerTools.streamLayeredImage ocah_container_config;
      }) // ( let 
        ocah_container_config_uv_bundle = (import ./nix/container.nix {inherit self inputs pkgs; bundle_uv=false;}).config; 
      in {
        bundle_uv = nativePkgs.dockerTools.buildLayeredImage ocah_container_config_uv_bundle;

        bundle_uv_stream = nativePkgs.dockerTools.streamLayeredImage ocah_container_config_uv_bundle;
      })
    );
  };
}
