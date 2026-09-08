{
  stdenv,
  fetchFromGitHub,
  cmake,
  systemc20,
  rapidjson,
  ...
}:
stdenv.mkDerivation rec {
  pname = "systemc-cci";
  version = "1.0.1";

  src = fetchFromGitHub {
    owner = "accellera-official";
    repo = "cci";
    rev = "v${version}";
    sha256 = "sha256-UyStnzZcB8ZgyHlVRR8IGeyrHAs+N38b02caHxUA5Fs=";
  };

  postPatch = ''
    substituteInPlace src/cci/core/cci_value.h \
      --replace-fail \
        "typedef void value_type; // TODO: add  explicit value_type " \
        "typedef cci_value_map_elem_cref value_type; // TODO: add  explicit value_type " \
      --replace-fail \
        "typedef void value_type; // TODO: add  explicit value_type" \
        "typedef cci_value_map_elem_ref value_type; // TODO: add  explicit value_type"
    mkdir -p docs/cci/archived
    touch docs/cci/archived/CODING_STYLE.txt
  '';

  nativeBuildInputs = [ cmake ];

  buildInputs = [
    systemc20
    rapidjson
  ];

  configureFlags = [ "CXXFLAGS=\"-std=c++20\"" ];

  cmakeFlags = [
    "-DCMAKE_PREFIX_PATH=${systemc20}"
    "-DSYSTEMCCCI_BUILD_TESTS=OFF"
    "-DCMAKE_POLICY_VERSION_MINIMUM=3.5"
    "-DCMAKE_CXX_STANDARD=20"
    "-DBUILD_SHARED_LIBS=OFF"
  ];
}
