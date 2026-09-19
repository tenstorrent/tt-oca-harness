{
  stdenv,
  fetchFromGitHub,
  systemc20,
  systemc-cci,
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
      systemc20
      systemc-cci
      boost-merged
      openssl
      rapidjson
      zlib
    ];

    SYSTEMC_HOME = "${systemc20}";
    CCI_HOME = "${systemc-cci}";

    enableParallelBuilding = true;

    makeFlags = [
      "BOOST_ROOT=${boost-merged}"
      "STATIC_LINK=0"
      "MEM_CALLBACKS=1"
      "EXTRA_CXXFLAGS=-std=gnu++20"
    ];

    installPhase = ''
      mkdir -p $out
      cp -r build-Linux $out/build-Linux
      for f in $(find virtual_memory iommu aplic imsic pci trace-reader third_party -name '*.a'); do
        install -Dm644 "$f" "$out/$f"
      done
    '';
  }
