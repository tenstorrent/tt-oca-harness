# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  stdenv,
  fetchFromGitHub,
  boost-merged,
  openssl,
  rapidjson,
  zlib,
  runCommand,
  yq-go,
  ...
}: let
  # Once VP is merged, source Whisper Version from CI Yaml
  vp_mk = ../../virtual_platform/tt-oca-harness-model/.github/workflows/ci-rhel8.yml;
  configJson = runCommand "config.json" {} ''
    ${yq-go}/bin/yq -o=json '${vp_mk}' > $out
  '';

  config = builtins.fromJSON (builtins.readFile configJson);

  vp_version = config.env.WHISPER_REV;

  version =
    if builtins.pathExists vp_mk
    then vp_version
    else "a53d0f3e";
in
  stdenv.mkDerivation {
    pname = "whisper";
    inherit version;

    src = fetchFromGitHub {
      owner = "tenstorrent";
      repo = "whisper";
      rev = version;
      # Should only need to update the hash here after updating submodule CI
      sha256 = "sha256-tL/wT2VD+QIjbzJi7bietpEwGsrm7fNCEUolVA5jros=";
    };

    buildInputs = [
      boost-merged
      openssl
      rapidjson
      zlib
    ];

    preBuild = ''
      printf 'smc_vp_whisper_libs: $(BUILD_DIR)/librvcore.a $(soft_float_lib) $(pci_lib) $(virtual_memory_lib)\n' \
        > whisper-smc-libs.mk
    '';

    enableParallelBuilding = true;

    makeFlags = [
      "-f GNUmakefile"
      "-f whisper-smc-libs.mk"
      "MEM_CALLBACKS=1"
      "CXX_STD=c++20"
      "EXTRA_CXXFLAGS=-fPIC"
      "BOOST_ROOT=${boost-merged}/"
    ];

    buildTarget = "smc_vp_whisper_libs";

    installPhase = ''
      runHook preInstall
      mkdir -p $out/whisper $out/bin
      for f in $(find build-Linux virtual_memory iommu aplic imsic pci trace-reader third_party -name '*.a' 2>/dev/null); do
        install -Dm644 "$f" "$out/whisper/$f"
      done
      for f in $(find . -name '*.hpp' 2>/dev/null); do
        install -Dm644 "$f" "$out/whisper/$f"
      done
      install -Dm755 build-Linux/whisper $out/bin/whisper
      runHook postInstall
    '';
  }
