{
  self,
  inputs,
  pkgs,

  bundle_uv ? false,
  ocah ? import ../ocah_deps.nix { inherit inputs pkgs bundle_uv; },
  name ? "ocah-container",
  systemForHash ? "x86_64-linux",
  PS1 ? "\\[\\e[1;36m\\]OCAH-Container >\\[\\e[0m\\] ",
  workDir ? "/work",
  extraDeps ? [ ],
}:
rec {
  inherit name;

  # self.containerHashes is an alias of this output, not the other way around - don't cause infinite recursion
  hash =
    self.dockerContainers.${systemForHash}.${
      if bundle_uv then "with_uv_deps" else "without_uv_deps"
    }.passthru.imageTag;

  config = {
    inherit name;

    # Ensure Container has /tmp
    extraCommands = ''
      mkdir -m 1777 tmp
    '';
    contents =
      with pkgs;
      [
        bash
        stdenv
        busybox
        git
        gnused
        findutils
        curl
        cacert
      ]
      ++ ocah.ocah_pkgs
      ++ extraDeps;
    config = {
      Env = builtins.attrValues (builtins.mapAttrs (e: v: "${e}=${v}") ocah.ocah_env) ++ [
        "PS1=${PS1}"
        "TMPDIR=/tmp"
      ];
      WorkingDir = workDir;
    };
  }
  // (
    # Pin tag to hash of x86_64-linux Docker Image - easier reproducibility
    if (pkgs.stdenv.system != systemForHash) then
      {
        tag = hash;
      }
    else
      { }
  );
}
