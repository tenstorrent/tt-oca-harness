# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  self,
  inputs,
  pkgs,
  bundle_uv ? false,
  ocah ? import ../ocah_deps.nix {inherit inputs pkgs bundle_uv;},
  name ? "ocah-container",
  systemForHash ? "x86_64-linux",
  PS1 ? "\\[\\e[1;36m\\]OCAH-Container >\\[\\e[0m\\] ",
  workDir ? "/work",
  extraDeps ? [],
}: rec {
  inherit name;

  # self.containerHashes is an alias of this output, not the other way around - don't cause infinite recursion
  # Reads the image tag from the canonical x86_64-linux build so all platforms share one stable hash.
  hash =
    self.dockerContainers.${
      systemForHash
    }.${
      if bundle_uv
      then "with_uv_deps"
      else "without_uv_deps"
    }.passthru.imageTag;

  config =
    {
      inherit name;

      # Ensure Container has /tmp and /usr/bin
      extraCommands = ''
        mkdir -m 1777 tmp
        mkdir -p usr
        ln -sr bin usr/bin
        ln -sr lib usr/lib
        ln -sr include usr/include
      '';
      # Base system tools plus project packages; extraDeps allows callsites to extend the image.
      contents = with pkgs;
        [
          bash
          stdenv
          busybox
          git
          gnused
          findutils
          curl
          cacert
          coreutils
        ]
        ++ ocah.ocah_pkgs
        ++ extraDeps
        # Libraries for Python Packages
        ++ pkgs.steam-run-free.args.multiPkgs pkgs
        ++ [pkgs.stdenv.cc.cc.lib];
      config = {
        # Convert ocah_env attrset to Docker ENV strings, then append container-specific vars.
        Env = builtins.attrValues (builtins.mapAttrs (e: v: "${e}=${v}") (ocah.ocah_env
          // {
            inherit PS1;
            TMPDIR = "/tmp";
            LD_LIBRARY_PATH = "/lib";
          }));
        Labels = {
          "org.opencontainers.image.source" = "https://github.com/tenstorrent/tt-oca-harness";
          "org.opencontainers.image.licenses" = "Apache-2.0";
        };
        WorkingDir = workDir;
      };
    }
    // (
      # Pin tag to hash of x86_64-linux Docker Image - easier reproducibility
      if (pkgs.stdenv.system != systemForHash)
      then {
        tag = hash;
      }
      else {}
    );
}
