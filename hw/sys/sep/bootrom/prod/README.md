<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SEP Production ROM

> [!WARNING]
> The production ROM firmware and its documentation are works in progress and
> are not ready for production use.

The SEP production ROM is the BL0 Root-of-Trust firmware. For its reset flow,
manifest processing, security policy, status channels, and BL1 handoff, see
[SEP Production ROM documentation](doc/index.adoc).

## Prerequisites

The firmware build requires an RV32-capable `riscv64-unknown-elf` GCC and
binutils toolchain with `picolibc.specs`. Python 3 is used for ROM image
conversion. Manifest packaging requires `uv`; it installs the Python
dependencies declared by the manifest-tool submodule.

Initialize that submodule once:

```bash
git submodule update --init hw/sys/sep/bootrom/prod/tools/tt-oca-manifest
```

If the required RISC-V toolchain is not available on the host, use the
repository toolchain container for the compiled images and run packaging on
the host:

```bash
./scripts/docker-run.sh run-here \
  make -C hw/sys/sep/bootrom/prod toolchain-images
make -C hw/sys/sep/bootrom/prod oca-images
```

When the host provides both tool sets, build the default ROM and packed image
in one command:

```bash
make -C hw/sys/sep/bootrom/prod
```

Set `GCC_PREFIX` when the compiler has a different executable prefix:

```bash
make -C hw/sys/sep/bootrom/prod \
  GCC_PREFIX=/path/to/bin/riscv64-unknown-elf
```

## Build types

`BUILD_TYPE` selects debug or release. It defaults to `debug`, which is the
image DV builds and is what a bare `make` produces; any other value than these
two is a build error.

| | `debug` (default) | `release` |
|---|---|---|
| Modulus read from | `tests/signing_keys/` private test keys | `release_signing_keys/` public keys only |
| Ships keys | yes, DV assets | no — provision them, or the build stops |
| Virtual-console debug output | compiled in (`-DDEBUG`) | compiled out (`-DNDEBUG=1`) |
| Output directory | `build/` | `build_release/` |
| `oca-images` | packs the DV test images | not implemented (see below) |

```bash
make                      # debug
make release              # or: make BUILD_TYPE=release
```

The ROM's anchors are always SHA-256 over the RSA-3072 **public** modulus. The
build type selects only which file form that modulus is extracted from, so no
private key material reaches a digest in either build.

A release build refuses to produce a ROM anchored on the test keys. It reads
public keys only, and fails if it finds any private key in the key directory —
see [`release_signing_keys/README.md`](release_signing_keys/README.md).

Release does not pack flash images. Every config under `configs/` signs with a
private test key, and a signed flashable image carrying a test signature is as
dangerous as a mask anchored on one. Real release signing needs a key store
rather than a key file, and is not wired up yet; `make BUILD_TYPE=release
oca-images` says so rather than doing nothing.

## Build variants

The OpenTitan DMA and PIO profiles use the same source and packed manifest
bytes. Each profile has its own object directory so builds do not overwrite one
another. They are independent of `BUILD_TYPE`.

| Target | Output directory | Flash transport |
|---|---|---|
| `toolchain-images` | `build/` | OpenTitan SPI host, secure-DMA RX drain |
| `pio-toolchain-images` | `build_pio/` | OpenTitan SPI host, CPU-PIO RX drain |

Useful packaging and maintenance targets are:

| Target | Purpose |
|---|---|
| `make` | Build the default ROM, BL1 test payload, and SMC-SRAM package. |
| `debug` / `release` | Build `all` with that `BUILD_TYPE`. |
| `key-digests` | Generate `$(BUILD_DIR)/key_digests.c` from the build type's keys. Host-only; `toolchain-images` runs it for you. |
| `toolchain-images` | Build ROM images and the BL1 payload with the RISC-V toolchain. |
| `oca-images` | Pack every OCA test image: one `.spi_preload` per entry in `OCA_IMAGES` (signed, encrypted, PQC, per-ROM-key and the negative cases) plus the bare SMC-SRAM bundle. Debug only. |
| `clean` | Remove every ROM variant and the BL1 test build. |

For example, build both OpenTitan receive paths and the signed flash image:

```bash
make -C hw/sys/sep/bootrom/prod toolchain-images
make -C hw/sys/sep/bootrom/prod pio-toolchain-images
make -C hw/sys/sep/bootrom/prod oca-images
```

## Outputs

The selected `BUILD_DIR` contains:

| File | Purpose |
|---|---|
| `boot_rom.elf` | Linked BL0 ELF image. |
| `boot_rom.vmem` | 64-bit VMEM loaded by the Boot ROM responder. |
| `boot_rom.itcm.hex` | ROM code and read-only sections rebased for a byte-hex loader. |
| `boot_rom.dtcm.hex` | Writable runtime sections rebased for the DCCM loader. |
| `boot_rom.dis` | Source-interleaved disassembly. |
| `boot_rom.sym` | Address-sorted symbol table. |

The default `build/` may also contain:

| File | Purpose |
|---|---|
| `oca_<name>.bin` / `.spi_preload` | Flash image for each entry in `OCA_IMAGES`, with the bundle at both boot slots, as raw binary and Verilog hex. |
| `oca_non_secure_boot.bin` / `.spi_preload` | Unsigned manifest and BL1. |
| `oca_secure_boot.bin` / `.spi_preload` | RSA-3072 signed test image. |
| `oca_encrypted_boot.bin` / `.spi_preload` | Signed, AES-CBC encrypted test image. |
| `oca_smc_mem.hex` | `oca_non_secure_boot.bin` rebased to the SEP-visible SMC SRAM address. |
| `oca_smc_bundle.bin` | Bare signed bundle the virtual platform stages in SMC SRAM. |
| `invalid_class_key.bin` | Decryption negative image, from `decrypt_negative_images`. |

The manifest configs and the signing keys in `tests/signing_keys/` are DV assets
for `BUILD_TYPE=debug`. They do not define production key provisioning, and a
release build cannot reach them.

## Use by DV

This ROM is not built by the shared firmware engine in `hw/common/dv/fw/`, so
`make -f ocah.mk ocah-dv-fw-tests` does not produce it. `[c_build.boot_rom]` in
`hw/sys/sep/dv/sep_sim_cfg.toml` runs `key-digests`, then
`toolchain-images-build`, then `oca-images` from this directory during the
`c_compile` stage, falling back to the toolchain container when the host
compiler has no picolibc. The split is deliberate: `toolchain-images-build`
needs the RISC-V toolchain and can run in the container, while `key-digests` and
`oca-images` are pure Python and must run on the HOST, because their
dependencies come from `uv` and the toolchain rootfs has none. The default
OpenTitan secure-DMA ROM uses `build/`; `pio-toolchain-images` builds the
OpenTitan CPU-PIO profile in `build_pio/`.

A caller that enters the container without generating digests first does not get
an import error from inside the sandbox — the rule says which command to run on
the host.

A test selects an image with `firmware = { name = "boot_rom", mode = "boot_rom" }`
and receives it through plusargs. `hw/sys/sep/dv/testlists/rom_fw.toml` passes
`+sep_boot_rom_hex` and `+sep_smc_mem_hex` pointing at `build/boot_rom.vmem` and
`build/oca_smc_mem.hex`. Those outputs are gitignored, so a plain `run_dv.py`
invocation builds what it needs, with one exception: the manifest-packer
submodule above, which a build step must not initialize because it would mutate
git state.

## Configuration

Common build variables include:

| Variable | Default | Purpose |
|---|---|---|
| `DCCM_SCRUB_BYTES` | `0x20000` | Cold-boot DCCM scrub length. |
| `SRAM_SCRUB_BYTES` | `0` | SEP SRAM scrub length. |
| `ROM_ICCM_CLEAR_ENABLE` | `1` | Establish ICCM ECC during BL1 handoff. |
| `ROM_ICCM_CLEAR_FULL` | `0` | Clear the entire ICCM before loading BL1. |
| `PMP_ENABLE` | `1` | Program the BL0 PMP entries. |
| `BOOT_SPI_CONTROLLER_OT` | `1` | Use the OpenTitan SPI host; set to `0` for memory-mapped flash through the XIP window, with an integrator-supplied controller driver. |
| `BOOT_OT_SPI_USE_PIO` | `0` | Use CPU PIO instead of secure DMA for OpenTitan RX. |
| `BOOT_OT_SPI_PROFILE` | `0` | Select the OpenTitan timing profile. |
| `BUILD_TYPE` | `debug` | `debug` or `release`; see [Build types](#build-types). |
| `SEP_ROM_RELEASE_SIGNING_KEYS_DIR` | `release_signing_keys` | Where a release build reads its public ROM keys. |

The default build is debug-oriented. Its zero-length SEP SRAM scrub leaves in place
anything the testbench preloads into SEP SRAM. ICCM ECC establishment is enabled, while the full-region clear
is disabled; an adopter requiring full ICCM residue clearing sets
`ROM_ICCM_CLEAR_FULL=1`. PMP rules are locked and bound to machine mode whenever
`PMP_ENABLE=1`. A release image must also apply the adopter's final
memory-sanitization, SPI-controller, and version policy.

`BUILD_TYPE=release` covers key provisioning and debug output: it generates the
ROM's trust anchors from public keys that are not in this repository, and drops
`-DDEBUG`, which compiles out the virtual console — roughly 12 KiB of the ROM,
and with it the scratch-register writes that would otherwise report lifecycle
state, fuse lock values, key-slot selection and the BL1 load address on a
production part. The status-report-disable strap does not suppress those; only
the build type does.

The remaining release-hardening knobs in the table above are still
caller-selected in both build types, and the ROM version string stays a fixed
placeholder so the open build's image, and the hash the ROM reports over itself,
remain reproducible. See issue #2026.

The rebuild stamp tracks the compile-affecting variables, including both ICCM
clear controls, so changing a knob rebuilds objects in the selected build
directory.

## Source layout

- `src/` — reset-independent boot logic, manifest processing, crypto, and handoff
- `include/` — image formats and SEP/SMC firmware contracts
- `link/` — ROM and DCCM placement
- `configs/` — DV manifest-package configurations
- `tests/signing_keys/` — private test keys; debug builds only
- `release_signing_keys/` — where a release build reads its public ROM keys; ships empty
- `tools/` — image conversion, ROM hash insertion, key digest generation, and manifest packaging
- `doc/` — production ROM firmware behavior
