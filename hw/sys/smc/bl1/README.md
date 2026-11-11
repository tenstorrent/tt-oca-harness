<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# SMC BL1

Reference first-stage bootloader for SMC hart 0, started by the SEP BL1. It answers the SEP
BL1's mailbox challenge and parks. `doc/index.adoc` describes it; the contract it implements
is `hw/sys/smu/bl1/doc/index.adoc`.

## Build

```bash
make                                # debug: build/debug/smc_bl1.{elf,bin,dis}
make BUILD_TYPE=release             # release: defines SMU_BL1_RELEASE, no console
make RISCV_TOOLCHAIN=<bin dir>      # use a host toolchain instead of the container
```

With `RISCV_TOOLCHAIN` unset the build runs through `scripts/docker-run.sh run-here`. The
toolchain needs a picolibc multilib for `rv64imac_zicsr_zifencei`/`lp64`; the build checks.

The test fixtures that replace `src/main.c` live in `hw/sys/smu/bl1/test/fixtures/` and build
with `make -C hw/sys/smu/bl1 fixtures`. Release builds refuse them.

## Layout

| Path | Contents |
|---|---|
| `src/start.S` | Entry, trap stub and park routine |
| `src/main.c` | Challenge and confirmation sequence |
| `src/mailbox.c` | SMC outbound filter entry, SEP mailbox 0 pop and push |
| `src/post.c` | POST word and the debug console |
| `src/ring.c` | Writer for the SMC Boot ROM's status ring |
| `include/smc_bl1_status.h` | Status values and the POST word layout |
| `include/smc_bl1_layout.h` | Contract values in assembler and linker form |
| `link/smc_bl1.ld` | Image and writable windows |
