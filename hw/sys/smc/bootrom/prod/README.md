<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC Production ROM

> [!WARNING]
> The production ROM FW and its documentation are works in progress and are
> not ready for production use.

The production ROM FW has a self-contained build. For its architecture, boot
behavior, OCCP protocol, and implementation details, see
[SMC Production ROM documentation](doc/index.adoc).

## Quick Start

Build the release image from the harness root:

```bash
make -C hw/sys/smc/bootrom/prod
```

For a debug build:

```bash
make -C hw/sys/smc/bootrom/prod BUILD_TYPE=debug
```

When `RISCV_TOOLCHAIN` is unset, the build uses
`scripts/docker-run.sh run-here`. To compile on the host, point the variable at
a picolibc-enabled `riscv64-unknown-elf-*` bin directory:

```bash
make -C hw/sys/smc/bootrom/prod \
  RISCV_TOOLCHAIN=/path/to/riscv64/bin
```

Build products are written under `build/release/` or `build/debug/`. The `bin/`
directory contains the ELF and binary image, `hex/` contains the generated ROM
formats, and `disasm/` contains the disassembly.

## Build and Development

The build requires `riscv64-unknown-elf-gcc` and related binutils with the
configured picolibc specs (via `RISCV_TOOLCHAIN` or the OCAH toolchain
container), plus Python 3 for host-side image conversion.

Useful targets:

| Target | Purpose |
|---|---|
| `make` | Build the selected release or debug image and all output formats. |
| `make toolchain-images` | Compile and link via `RISCV_TOOLCHAIN` or the OCAH container. |
| `make pack-images` | Convert existing toolchain outputs into ROM preload formats on the host. |
| `make check` | Check tool availability and the linker script. |
| `make size` | Print section and aggregate image sizes. |
| `make memory` | Print the largest linked symbols. |
| `make clean` | Remove the local `build/` directory. |
| `make help` | List the basic build commands and options. |

Set `ENABLE_RELEASE_PRINTS=1` to retain debug console calls in a release build.
Set `I3C_CORE=swap` to compile the open HCI I3C driver. `EXTRA_DEFINES` provides
additional build-time definitions.

Key implementation directories are:

- `boot/` — assembly entry, C runtime, traps, SRAM initialization, and early memory checks
- `src/` — the C boot phases
- `drivers/` — strap, eFuse, PLL, I2C, and I3C interfaces
- `lib/` — OCCP, status, security, and coordination support
- `linker/smc/` — ROM and SRAM placement
- `scripts/` — output-image conversion and ECC generation
