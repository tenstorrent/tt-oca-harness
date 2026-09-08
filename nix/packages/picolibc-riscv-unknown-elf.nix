{
  stdenvNoCC,
  fetchFromGitHub,
  gcc-riscv-unknown-elf,
  binutils-riscv-unknown-elf,
  meson,
  ninja,
  python3,
}:
stdenvNoCC.mkDerivation {
  pname = "picolibc-riscv64-unknown-elf";
  version = "1.8.12";

  src = fetchFromGitHub {
    owner = "picolibc";
    repo = "picolibc";
    rev = "1.8.12";
    hash = "sha256-a2XLUN2U49Lpsyizzb2cQpMbww0cmOUUKdgIj6OHhpQ=";
  };

  nativeBuildInputs = [
    gcc-riscv-unknown-elf
    binutils-riscv-unknown-elf
    meson
    ninja
    python3
  ];

  dontUseMesonConfigure = true;
  dontUseNinjaBuild = true;
  dontUseNinjaInstall = true;

  configurePhase = ''
        runHook preConfigure

        PATH="${binutils-riscv-unknown-elf}/bin:$PATH"

        cat > "$TMPDIR/riscv64-elf.ini" << 'CROSS_EOF'
    [binaries]
    c      = 'riscv64-unknown-elf-gcc'
    ar     = 'riscv64-unknown-elf-ar'
    as     = 'riscv64-unknown-elf-as'
    strip  = 'riscv64-unknown-elf-strip'
    nm     = 'riscv64-unknown-elf-nm'

    [host_machine]
    system     = 'unknown'
    cpu_family = 'riscv64'
    cpu        = 'riscv'
    endian     = 'little'

    [properties]
    c_args       = ['-msave-restore']
    c_args_      = ['-mcmodel=medany']
    c_args_space = ['-mcmodel=medany']
    skip_sanity_check = true
    CROSS_EOF

        meson setup . "$TMPDIR/picolibc-build" \
          --cross-file "$TMPDIR/riscv64-elf.ini" \
          --prefix="$out" \
          -Dspecsdir="$out/lib/gcc/riscv64-unknown-elf/15" \
          -Dlibdir="lib/gcc/riscv64-unknown-elf/15" \
          -Dincludedir="riscv64-unknown-elf/include" \
          -Dsystem-libc=true \
          -Ddebug=true \
          --buildtype=release \
          -Dtests=false \
          || { cat "$TMPDIR/picolibc-build/meson-logs/meson-log.txt" 2>/dev/null; exit 1; }

          runHook postConfigure
  '';

  buildPhase = ''
    runHook preBuild
    ninja -C "$TMPDIR/picolibc-build" -j$NIX_BUILD_CORES
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    ninja -C "$TMPDIR/picolibc-build" install
    runHook postInstall
  '';
}
