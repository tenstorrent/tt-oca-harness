# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  inputs,
  pkgs,
  bundle_uv ? true,
  ...
}: let
  # load-uv-env.nix returns a function; apply it to pkgs to get the pythonSet and venv.
  uv_loader = import ./nix/load-uv-env.nix {inherit inputs;};
  uv_loaded = uv_loader pkgs;
  # VeeR-ISS includes <zlib.h> and links -lz/-lbz2/-llzma/-lzstd bare, with no find_package
  # hook to point at a prefix. The container has no system /usr/include or /usr/lib.
  vp_system_libs = with pkgs; [zlib bzip2 xz zstd];
in {
  ocah_env =
    rec {
      # Needed to allow dashboard to fetch badges
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";

      # Bypass NPX for MDlint
      OCAH_MARKDOWNLINT = "${pkgs.markdownlint-cli}/bin/markdownlint";
      # Documentation Variables - bypass NPX
      OCAH_ANTORA = "${pkgs.ocah-antora}/bin/antora";
      # Diagram generator paths
      DIAGRAM_DITAA_CLASSPATH = "${pkgs.ocah-ditaa}/lib/ditaa.jar";
      DIAGRAM_PLANTUML_CLASSPATH = "${pkgs.plantuml}/lib/plantuml.jar";
      OCAH_NO_INSTALL_NPM_DEPS = "1";
      # Run Synth Natively, rather than (nesting) container
      OCAH_EDA_SKIP_CONTAINERS = "1";
      OCAH_YOSYS_BUNDLED_SLANG = "1";
      # SMC Bootrom
      RISCV_TOOLCHAIN = "${pkgs.riscv-unknown-elf-toolchain}/bin";
      # VP Env Variables
      SYSTEMC_HOME = "${pkgs.systemc20}";
      CCI_HOME = "${pkgs.systemc-cci}";
      BOOST_DIR = "${pkgs.boost-merged}";
      BOOST_ROOT = BOOST_DIR;
      OPENSSL_ROOT = "${pkgs.openssl-merged}";
      WHISPER_HOME = "${pkgs.whisper}/whisper";
      CPATH = pkgs.lib.makeSearchPathOutput "dev" "include" vp_system_libs;
      LIBRARY_PATH = pkgs.lib.makeLibraryPath vp_system_libs;
      CMAKE_CXX_STANDARD = "20";
      # Nix compilers enforce no -mtune native for reproducibility by default, overridden here
      NIX_ENFORCE_NO_NATIVE = "0";
    }
    // (
      # When bundling, point UV at the Nix-provided Python/venv and disable all network sync so it
      # never tries to download packages or manage its own environment at runtime.
      if bundle_uv
      then rec {
        # UV Bypass Rules
        UV_NO_SYNC = "1";
        UV_PYTHON = uv_loaded.pythonSet.python.interpreter;
        UV_PYTHON_DOWNLOADS = "never";
        OCAH_DV_SKIP_UV = "1";
        OCAH_CLANG_FORMAT_SKIP_UV = "1";
        OCAH_TCLINT_SKIP_UV = "1";
        OCAH_MYPY_SKIP_UV = "1";
        OCAH_CODESPELL_SKIP_UV = "1";
        OCAH_PRE_COMMIT_SKIP_UV = "1";
        OCAH_RUFF_SKIP_UV = "1";
        OCAH_SHELLCHECK_SKIP_UV = "1";
        OCAH_TOMLLINT_SKIP_UV = "1";
        OCAH_YAMLLINT_SKIP_UV = "1";
        # Find Python+libraries correctly
        PYTHON = "${uv_loaded.venv}/bin/python";
        # Register Generation Binaries
        OCAH_REG_PYTHON = PYTHON;
        OCAH_REG_PEAKRDL = "${uv_loaded.venv}/bin/peakrdl";
        OCAH_REG_SKIP_UV_SYNC = "1";
        # OTBN
        OTBN_PYTHON = PYTHON;
        VP_PYTHON = PYTHON;
        # SEP ROM builds
        MANIFEST_PYTHON = PYTHON;
      }
      else {}
    );
  # Full list of packages to include in the container image and dev shell.
  # Package names may be checked at https://search.nixos.org/
  ocah_pkgs = with pkgs;
    [
      uv
      # Documentation Tools
      ocah-antora
      ocah-asciidoctor
      ocah-ditaa
      mermaid-cli
      plantuml
      kroki
      # Build Tools
      gnumake
      bender-patched
      verilator
      # cocotb's Verilator runner invokes the verilator script through `perl`
      perl
      sv-lang
      gcc
      ccache
      riscv-unknown-elf-toolchain
      cmake
      # Linters
      verible
      svlint
      checkmake
      markdownlint-cli
      vale
      # Synthesis
      pdk-ciel
      yosys
      # Formal DV
      sby
      # Libraries
      lz4
      zlib
      libvncserver
      doxygen
      # Other Tools
      surfer
      graphviz
      # VP Dependencies
      openssl-merged
      systemc20
      systemc-cci
      boost-merged
      whisper
      bzip2
      xz
      zstd
    ]
    ++ (
      if bundle_uv
      then [
        # Load the UV Environment Defined in uv.lock
        uv_loaded.venv
      ]
      else [
        python311
      ]
    );
}
