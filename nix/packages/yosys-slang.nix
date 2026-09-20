{
  lib,
  stdenv,
  fetchFromGitHub,
  cmake,
  ninja,
  yosys,
  python3,
  tomlplusplus,
  ...
}:
stdenv.mkDerivation (finalAttrs: {
  pname = "yosys-slang";
  version = "2026-08-30";

  src = fetchFromGitHub {
    owner = "povik";
    repo = "sv-elab"; # renamed from "yosys-slang"; old name 301-redirects here
    rev = finalAttrs.version;
    fetchSubmodules = true;
    hash = "sha256-qW6Io983kjZ1TENq7JNJURE/3LMEwhsJmff7sDLu0qM=";
  };

  nativeBuildInputs = [
    cmake
    ninja
  ];

  buildInputs = [
    yosys
    python3
  ];

  cmakeFlags = [
    (lib.cmakeBool "BUILD_AS_PLUGIN" true)
    (lib.cmakeFeature "FETCHCONTENT_SOURCE_DIR_BOOST_REGEX" "${fetchFromGitHub {
      owner = "MikePopoloski";
      repo = "regex";
      rev = "boost-1.91.0";
      hash = "sha256-/a3wW6hMQwxrxs7pX3KKZGKFTm78HALaquBAwDMJfq4=";
    }}")
    (lib.cmakeFeature "FETCHCONTENT_SOURCE_DIR_TOMLPLUSPLUS" "${tomlplusplus.src}")
    (lib.cmakeBool "FETCHCONTENT_FULLY_DISCONNECTED" true)
  ];
  postPatch = ''
    substituteInPlace src/CMakeLists.txt \
      --replace-fail 'DESTINATION ''${YOSYS_DATDIR}/plugins' "DESTINATION $out/share/yosys/plugins"
  '';

  postConfigure = "";
  doCheck = false;

  passthru.plugin = "slang";
})
