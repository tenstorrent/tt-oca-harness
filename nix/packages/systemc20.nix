# Build SystemC and other dependencies of Virtual Platform
{
  systemc,
  yq-go,
  runCommand,
  fetchFromGitHub,
  ...
}: let
  # Once VP is merged, source SystemC Version from CI Yaml
  vp_mk = ../../virtual_platform/tt-oca-harness-model/.github/workflows/ci-rhel8.yml;
  configJson = runCommand "config.json" {} ''
    ${yq-go}/bin/yq -o=json '${vp_mk}' > $out
  '';

  config = builtins.fromJSON (builtins.readFile configJson);

  vp_version = config.env.SYSTEMC_VERSION;

  version =
    if builtins.pathExists vp_mk
    then vp_version
    else "3.0.2";
in
  systemc.overrideAttrs (old: {
    inherit version;

    src = fetchFromGitHub {
      owner = "accellera-official";
      repo = "systemc";
      tag = version;
      hash = "sha256-v/PcQu0m/7zyx2TtpZrLFbHtknahgVCkzcRi3lgrRGw=";
    };

    cmakeFlags = (old.cmakeFlags or []) ++ ["-DCMAKE_CXX_STANDARD=20"];
    configureFlags = (old.configureFlags or []) ++ ["CXXFLAGS=\"-std=c++20\""];
  })
