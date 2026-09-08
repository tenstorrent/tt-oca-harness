{
  self,
  inputs,
  pkgs,

  bundle_uv ? true,
  ocah ? import ../ocah_deps.nix {inherit inputs pkgs bundle_uv;},
  name ? "ocah-container",
  systemForHash ? "x86_64-linux"
}: rec {
  inherit name;

  hash = self.dockerContainers.${systemForHash}.${if bundle_uv then "bundle_uv" else "default"}.passthru.imageTag;

  config = {
    inherit name;

    # Ensure Container has /tmp
    extraCommands = ''
      mkdir -m 1777 tmp
    '';
    contents = with pkgs; [
      bash
      stdenv
      busybox
      git
      gnused
      findutils
      curl
      cacert
    ] ++ ocah.ocah_pkgs;
    config = {
      Env = builtins.attrValues (builtins.mapAttrs (e: v: "${e}=${v}") ocah.ocah_env ) ++ [ "PS1=\\[\\e[1;36m\\]OCAH-Container >\\[\\e[0m\\] " "TMPDIR=/tmp" ];
      WorkingDir = "/work";
    };
  } // (
    # Pin tag to hash of x86_64-linux Docker Image - easier reproducibility
    if (pkgs.stdenv.system != systemForHash) then {
      tag = hash;
    } else {}
  );
}