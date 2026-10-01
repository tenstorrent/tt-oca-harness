# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
{
  lib,
  stdenv,
  fetchurl,
  binutils-riscv-unknown-elf,
  gawk,
  bison,
  flex,
  texinfo,
  gperf,
  autoconf,
  automake,
  libtool,
  m4,
  gmp,
  mpfr,
  libmpc,
  isl,
  zlib,
  makeWrapper,
  ...
}:
stdenv.mkDerivation rec {
  pname = "gcc-riscv64-unknown-elf";
  version = "15.3.0";

  src = fetchurl {
    url = "mirror://gnu/gcc/gcc-${version}/gcc-${version}.tar.xz";
    hash = "sha256-+lnBvu+JlfJ8TXHB3yJ1hxiTFdPm+v8btDBuYbDFMOs=";
  };

  patches = let
    salsaRaw = name: hash:
      fetchurl {
        url = "https://salsa.debian.org/debian/gcc-riscv64-unknown-elf/-/raw/debian/debian/patches/${name}";
        inherit hash;
      };
  in [
    (salsaRaw "0001-Ignore-document-errors-during-build.patch" "sha256-0QfdGxYioSaszv2tceRM6alwKefDRH8dovqFxfLccvI=")
    (salsaRaw "0002-Add-more-multi-lib-for-rv32-and-rv64.patch" "sha256-8L9x7SBbHrz3ehFMLM9h8TyVbJkNWYvJg2oO0xDoIN8=")
    (salsaRaw "0003-riscv-Preserve-qnan-fraction-and-sign.patch" "sha256-z7Hq5gklrH92mW2A4+Q5mjnoiGpeSLqU6JczzcT00ls=")
    (salsaRaw "0004-Remove-use-of-include_next-from-c-headers.patch" "sha256-/Pw+rTf6zcKKBpfJ2UDJosR9WtPhqI6H7rxaCBC6jM4=")
    (salsaRaw "0005-Change-default-for-fzero-init-padding-bits-to-all.patch" "sha256-AIK3ICMoJ3OsCdfYke063Qvrb//87UI1QnJRf6xmPjE=")
    (salsaRaw "0006-Add-support-for-using-picolibc.patch" "sha256-w+4W/eFMSoG2qLFQ7zHEQxMc0QmCU534YLDK+uX26Yk=")
    (salsaRaw "0007-libstdc-Fix-C-11-ctype-when-using-picolibc-blank-vs-.patch" "sha256-H8UrJ7bU+A97kZOg+fSlgwK0sOywDNmSrSwe9KHcmWY=")
    (salsaRaw "0011-driver-Add-if-driverlang-spec-function.patch" "sha256-CpBvpayMoTCpWvThjBtuLLVCUfeAAgUzLQfrsSINKzI=")
    (salsaRaw "0012-picolibc-Add-C-bits-when-linking-with-C-driver.patch" "sha256-2tpiAXA+4gNex0zDc3KhXeE8oAoM7Aj3DecYvyGD9pY=")
  ];

  nativeBuildInputs = [
    binutils-riscv-unknown-elf
    gawk
    bison
    flex
    texinfo
    gperf
    autoconf
    automake
    libtool
    m4
  ];

  buildInputs = [
    gmp
    mpfr
    libmpc
    isl
    zlib
    makeWrapper
  ];

  preConfigure = ''
    configureScript=$(pwd)/configure
    mkdir ../build
    cd ../build
  '';

  configureFlags = [
    "--target=riscv64-unknown-elf"
    "--with-arch=rv64imafdc"
    "--with-cmodel=medany"
    "--enable-multilib"
    "--enable-languages=c,c++,lto"
    "--with-picolibc"
    "--without-newlib"
    "--disable-libstdcxx"
    "--disable-decimal-float"
    "--disable-libffi"
    "--disable-libgomp"
    "--disable-libmudflap"
    "--disable-libquadmath"
    "--disable-libssp"
    "--disable-libstdcxx-pch"
    "--disable-nls"
    "--disable-shared"
    "--disable-threads"
    "--enable-tls"
    "--with-system-zlib"
    "--with-gnu-as"
    "--with-gnu-ld"
    "--with-headers=no"
    "--with-gcc-major-version-only"
    "--without-included-gettext"
    # Prevents a libgcc TM clone-registry symbol clash on bare-metal targets
    "INHIBIT_LIBC_CFLAGS=-DUSE_TM_CLONE_REGISTRY=0"
    "AR_FOR_TARGET=riscv64-unknown-elf-ar"
    "AS_FOR_TARGET=riscv64-unknown-elf-as"
    "LD_FOR_TARGET=riscv64-unknown-elf-ld"
    "NM_FOR_TARGET=riscv64-unknown-elf-nm"
    "OBJDUMP_FOR_TARGET=riscv64-unknown-elf-objdump"
    "RANLIB_FOR_TARGET=riscv64-unknown-elf-ranlib"
    "READELF_FOR_TARGET=riscv64-unknown-elf-readelf"
    "STRIP_FOR_TARGET=riscv64-unknown-elf-strip"
  ];

  hardeningDisable = ["format"];

  enableParallelBuilding = true;

  postInstall = ''
    for prog in $out/bin/*; do
        wrapProgram $prog --prefix PATH : ${lib.makeBinPath [binutils-riscv-unknown-elf]}
    done
    mkdir -p $out/riscv64-unknown-elf/bin
    for tool in as ld ar nm objcopy objdump ranlib readelf strip; do
        ln -s ${binutils-riscv-unknown-elf}/bin/riscv64-unknown-elf-$tool \
              $out/riscv64-unknown-elf/bin/$tool
    done
  '';
}
