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
git submodule update --init hw/sys/sep/bootrom/prod/tools/tt-boot-manifest
```

If the required RISC-V toolchain is not available on the host, use the
repository toolchain container for the compiled images and run packaging on
the host:

```bash
./scripts/docker-run.sh run-here \
  make -C hw/sys/sep/bootrom/prod toolchain-images
make -C hw/sys/sep/bootrom/prod pack-images
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

## Build variants

The three ROM variants use the same source and packed manifest bytes. Each ROM
variant has its own object directory so builds do not overwrite one another.

| Target | Output directory | Flash transport |
|---|---|---|
| `toolchain-images` | `build/` | Default memory-mapped SPI integration seam |
| `ot-toolchain-images` | `build_ot/` | OpenTitan SPI host, secure-DMA RX drain |
| `ot-pio-toolchain-images` | `build_ot_pio/` | OpenTitan SPI host, CPU-PIO RX drain |

Useful packaging and maintenance targets are:

| Target | Purpose |
|---|---|
| `make` | Build the default ROM, BL1 test payload, and SMC-SRAM package. |
| `toolchain-images` | Build ROM images and the BL1 payload with the RISC-V toolchain. |
| `pack-images` | Package the non-secure manifest and BL1 for the SMC-SRAM path. |
| `secure_boot_spi` | Package the RSA-3072 signed SPI test image. |
| `encrypted_boot_spi` | Package the signed, AES-CBC encrypted SPI test image. |
| `clean` | Remove every ROM variant and the BL1 test build. |

For example, build both OpenTitan receive paths and the signed flash image:

```bash
make -C hw/sys/sep/bootrom/prod ot-toolchain-images
make -C hw/sys/sep/bootrom/prod ot-pio-toolchain-images
make -C hw/sys/sep/bootrom/prod secure_boot_spi
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
| `non_secure_boot.bin` | Unsigned manifest and BL1 flash image. |
| `non_secure_boot.spi_preload` | Verilog-hex form of the unsigned image. |
| `smc_mem.hex` | Unsigned image rebased to the SEP-visible SMC SRAM address. |
| `secure_boot.bin` / `.spi_preload` | RSA-3072 signed test image. |
| `encrypted_boot.bin` / `.spi_preload` | Signed, AES-CBC encrypted test image. |

The manifest configs and signing key shipped through the manifest-tool
submodule are DV assets. They do not define production key provisioning.

## Use by DV

This ROM is not built by the shared firmware engine in `hw/common/dv/fw/`, so
`make -f ocah.mk ocah-dv-fw-tests` does not produce it. `[c_build.boot_rom]` in
`hw/sys/sep/dv/sep_sim_cfg.toml` runs `toolchain-images` and `pack-images` from
this directory during the `c_compile` stage, falling back to the toolchain
container when the host compiler has no picolibc. The OpenTitan variants have
their own `[c_build.boot_rom_ot]` and `[c_build.boot_rom_ot_pio]` templates.

A test selects an image with `firmware = { name = "boot_rom", mode = "boot_rom" }`
and receives it through plusargs. `hw/sys/sep/dv/testlists/rom_fw.toml` passes
`+sep_boot_rom_hex` and `+sep_smc_mem_hex` pointing at `build/boot_rom.vmem` and
`build/smc_mem.hex`. Those outputs are gitignored, so a plain `run_dv.py`
invocation builds what it needs, with one exception: the manifest-packer
submodule above, which a build step must not initialize because it would mutate
git state.

## Configuration

Common build variables include:

| Variable | Default | Purpose |
|---|---|---|
| `DCCM_SCRUB_BYTES` | `0x20000` | Cold-boot DCCM scrub length. |
| `SRAM_SCRUB_BYTES` | `0` | SEP SRAM scrub length. |
| `ROM_ICCM_CLEAR_ENABLE` | `0` | Clear ICCM through the DMA before loading BL1. |
| `PMP_ENABLE` | `1` | Program the BL0 PMP entries. |
| `PMP_LOCK` | `0` | Lock the programmed PMP entries until reset. |
| `BOOT_SPI_CONTROLLER_OT` | `0` | Select the OpenTitan SPI host when set. |
| `BOOT_OT_SPI_USE_PIO` | `0` | Use CPU PIO instead of secure DMA for OpenTitan RX. |
| `BOOT_OT_SPI_PROFILE` | `0` | Select the OpenTitan timing profile. |
| `BUILD_TYPE` | `test` | Recorded in the rebuild stamp; selects no build behavior. |

The open Makefile builds a test/debug-oriented image. Its zero-length SEP SRAM
scrub and disabled full-ICCM clear reduce RTL simulation cost. A release image
must establish ECC for the full ICCM and apply the adopter's final memory
sanitization, PMP lock, SPI-controller, version, and key-provisioning policy.

There is no enforced release build mode in the current Makefile:
`TEST_BUILD=1` and `DEBUG` are always present in `CFLAGS`, and `BUILD_TYPE`
only participates in the rebuild stamp. Consequently, debug virtual-console
output remains compiled in even when the status-report-disable strap skips the
SMC status ring. The ROM version string is a fixed placeholder for the same
reason; it keeps the open build's image, and the hash the ROM reports over
itself, reproducible.

The rebuild stamp tracks most variables in the table, but not
`ROM_ICCM_CLEAR_ENABLE`. Clean before changing that variable:

```bash
make -C hw/sys/sep/bootrom/prod clean
make -C hw/sys/sep/bootrom/prod ROM_ICCM_CLEAR_ENABLE=1
```

## Source layout

- `src/` — reset-independent boot logic, manifest processing, crypto, and handoff
- `include/` — image formats and SEP/SMC firmware contracts
- `link/` — ROM and DCCM placement
- `configs/` — DV manifest-package configurations
- `tools/` — image conversion, ROM hash insertion, and manifest packaging
- `doc/` — production ROM firmware behavior
