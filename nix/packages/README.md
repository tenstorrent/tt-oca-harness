# OCAH Package Dependencies

This directory contains dependencies of OCAH that are built from source, or modified, rather than using the standard nixpkgs version.

## Packages

The packages currently installed in this way are the below:

### Documentation Builds

#### ASCIIDoctor-Kroki

This is a library used by the website build of the documentation, but not packaged in nixpkgs.

#### OCAH Antora

This bundles the nixpkgs antora binary with the ASCIIDoctor-Kroki (above) and Antora-Lunr (from nixpkgs) extensions, which removes a reliance on runtime NPM installations. 

#### OCAH ASCIIDoctor

Aliases ASCIIDoctor-with-extensions, to include ASCIIDoctor-Diagram

#### OCAH Ditaa

Original Java version of ditaa, to be compatible with ASCIIDoctor-Diagram

### RISCV-Toolchain

OCAH Previously used a Debian linux container, with the debian `riscv64-unknown-elf-*` toolchain. These derivations construct the same toolchain, meaning that builds should work in the same way.

#### Binutils RISCV Unknown ELF

Builds the GNU Binutils matching the debian package version as of writing. To update, change the `version` and `hash` attribute. To get the new hash, run the build once on the old hash - it will fail on a hash mismatch, and give the new hash in the error message.

#### GCC RISCV Unknown ELF

Builds a `riscv-unknown-elf-gcc` matching the Debian Binary - able to compile for both RV64 and RV32 - both used for the different CPUs in the harness. To update, similarly modify the version and hash. However, the Debian package applies several patches, which may need consulting - see the patches attribute for details.

#### Picolibc RISCV Unknown ELF

Builds Picolibc to match the above, which is statically linked into the firmware binaries.

#### RISCV Unknown ELF Toolchain

This Links the above binaries into a single derivation. Nix packages by default are sandboxed from each other, which can cause problems with C compilers. This bundles all the above into a single derivation and patches the compiler binaries to find picolibc.

### Synthesis

#### Yosys-Slang

This packages the Yosys SystemVerilog Plugin, not currently in nixpkgs. This requires headers from Regex-Boost and Toml++. Regex is fetched from source, and Toml++ uses the source of the nixpkgs version.

#### Yosys with Slang

This bundles the nixpkgs Yosys with the above plugin.

### Virtual Platform

The Virtual Platform Repository is able to build all it's dependencies from source as part of the build process, however, this may not be possible on a sandboxed system, so the nix container includes the same dependencies bundled in.

#### SystemC20

Nixpkgs includes SystemC, but build with C++17, so this is overridden to C++20 to match the VP requirement. The package is renamed to avoid collisions with other packages in nixpkgs.

#### Boost Merged and OpenSSL Merged

The nixpkgs Boost and OpenSSL packages include some headers as a separate `.dev` output. These bundle the shared objects and headers back together.

#### SystemC CCI

This package is not in nixpkgs, so is packaged from source, and build with the required SystemC20.

#### Whisper

The SMC-VP requires the Whisper RISC-V simulator, so this is packaged and included as well. 

> The version of whisper packaged here is not final yet - awaiting https://github.com/tenstorrent/tt-oca-harness/pull/#1586 merge
