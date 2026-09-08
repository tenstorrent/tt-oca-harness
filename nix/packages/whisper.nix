# The version of whisper packaged here is not final yet - awaiting https://github.com/tenstorrent/tt-oca-harness/pull/#1586 merge
{
  stdenv,
  fetchFromGitHub,
  systemc20,
  systemc-cci,
  boost-merged,
  openssl,
  rapidjson,
  zlib,
  ...
}:
stdenv.mkDerivation {
  pname = "whisper";
  version = "master";

  src = fetchFromGitHub {
    owner = "tenstorrent";
    repo = "whisper";
    rev = "e11c49e0d3011300909bce7ef588ab8e6302b71b";
    sha256 = "sha256-SGAUDprd0aRM7kt1T8oV/oKLvUkVdAYVZUEj6DJ8BQo=";
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
