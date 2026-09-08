{
  stdenv,
  fetchurl,
  bison,
  flex,
  texinfo,
  zlib,
  ...
}:
stdenv.mkDerivation {
  pname = "binutils-riscv64-unknown-elf";
  version = "2.44";

  src = fetchurl {
    url = "mirror://gnu/binutils/binutils-2.44.tar.xz";
    hash = "sha256-ziAX4FnWPmfduSQOnU7EnCiTYFA1zWDpKtUxd/Q3cjc=";
  };

  nativeBuildInputs = [ bison flex texinfo ];
  buildInputs       = [ zlib ];

  configureFlags = [
    "--target=riscv64-unknown-elf"
    "--disable-werror"
    "--enable-multilib"
    "--disable-nls"
    "--with-system-zlib"
  ];

  enableParallelBuilding = true;
}