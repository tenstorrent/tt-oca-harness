{
  stdenv,
  fetchFromGitHub,
  cmake,
  systemc20,
  rapidjson,
  runCommand,
  yq-go,
  ...
}: let
  # Once VP is merged, source CCI Version from CI Yaml
  vp_mk = ../../virtual_platform/tt-oca-harness-model/.github/workflows/ci-rhel8.yml;
  configJson = runCommand "config.json" {} ''
    ${yq-go}/bin/yq -o=json '${vp_mk}' > $out
  '';

  config = builtins.fromJSON (builtins.readFile configJson);

  vp_version = config.env.CCI_VERSION;

  version =
    if builtins.pathExists vp_mk
    then vp_version
    else "1.0.2";
in
  stdenv.mkDerivation rec {
    pname = "systemc-cci";
    inherit version;

    src = fetchFromGitHub {
      owner = "accellera-official";
      repo = "cci";
      rev = "v${version}";
      # Update this on version bump
      sha256 = "sha256-FU2CE49hhcoJ4HV+vzGyb1MqBK8AIqTK55c89qyw094=";
    };

    postPatch = ''
      mkdir -p docs/cci/archived
      touch docs/cci/archived/CODING_STYLE.txt
    '';

    nativeBuildInputs = [cmake];

    buildInputs = [
      systemc20
      rapidjson
    ];

    configureFlags = ["CXXFLAGS=\"-std=c++20\""];

    cmakeFlags = [
      "-DCMAKE_PREFIX_PATH=${systemc20}"
      "-DSYSTEMC_HOME=${systemc20}"
      "-DSYSTEMCCCI_BUILD_TESTS=OFF"
      "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"
      "-DCMAKE_CXX_STANDARD=20"
      "-DBUILD_SHARED_LIBS=OFF"
    ];
  }
