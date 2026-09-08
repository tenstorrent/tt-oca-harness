# Build riscv-toolchain matching the versions installed within Previous Debian Docker Container
{
  lib,
  symlinkJoin,
  gcc-riscv-unknown-elf,
  binutils-riscv-unknown-elf,
  picolibc-riscv-unknown-elf,
  bash,
  ...
}:
symlinkJoin {
  name = "riscv-toolchain";
  paths = [
    gcc-riscv-unknown-elf
    binutils-riscv-unknown-elf
    picolibc-riscv-unknown-elf
  ];
  postBuild = ''
    picolibc_specdir="${picolibc-riscv-unknown-elf}/lib/gcc/riscv64-unknown-elf/15"
    picolibc_includedir="${picolibc-riscv-unknown-elf}/riscv64-unknown-elf/include"
    for prog in riscv64-unknown-elf-gcc riscv64-unknown-elf-gcc-${lib.versions.major gcc-riscv-unknown-elf.version} riscv64-unknown-elf-g++ riscv64-unknown-elf-c++ riscv64-unknown-elf-cpp; do
      if [ -L "$out/bin/$prog" ]; then
        target=$(readlink -f "$out/bin/$prog")
        rm "$out/bin/$prog"
        printf '%s\n' \
          '#!${bash}/bin/bash' \
          "exec \"$target\" -B\"$picolibc_specdir\" -isystem\"$picolibc_includedir\" \"\$@\"" \
          > "$out/bin/$prog"
        chmod +x "$out/bin/$prog"
      fi
    done
  '';
}
