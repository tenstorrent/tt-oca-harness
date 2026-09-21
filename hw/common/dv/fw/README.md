# Shared DV Firmware Policy

This directory holds shared DV firmware collateral only (shared toolchain rules,
the static register umbrellas, and policy notes). Keep it thin: subsystem
firmware sources live beside the hardware that owns them.

- `hw/ip/key_manager/dv/fw/`
- `hw/sys/smc/dv/fw/`
- `hw/sys/sep/dv/fw/`

Discovery mirrors the register flow: any block exposing a `dv/fw/fw.mk` is built
automatically, so new subsystems need no dispatcher edits.

## Makefile roles

There are two kinds of `fw.mk` in the tree:

- `hw/common/dv/fw/fw.mk` is the top-level DV firmware entrypoint. It owns the
  user-visible targets (`ocah-dv-fw-libs`, `ocah-dv-fw-tests`, list and clean
  targets), discovers subsystem `dv/fw/fw.mk` files under `OCAH_ROOT`, and binds
  that discovery to the harness root.
- `hw/{ip,sys}/<name>/dv/fw/fw.mk` is a subsystem build manifest. It declares
  `FW_*` inputs for one firmware target: source files, include paths, linker
  scripts, test deltas, and the subsystem `toolchain.mk`.

`dispatch.mk` sits between those roles. It has no tree-specific targets and does
not know about a particular tree layout; it is only a small library of make functions for
discovering `dv/fw/fw.mk` files, mapping them to subsystem names, and fanning a
goal out to selected recursive sub-makes. Keeping that logic in `dispatch.mk`
lets another tree reuse the same fan-out machinery while keeping its own
entrypoint target names and help text in its own `fw.mk`.

`fw.mk` names the makefile an integrator or subsystem includes/runs for
firmware. `dispatch.mk` names the private helper layer, not another firmware
build entrypoint.

## Build commands

```
make ocah-dv-fw-libs TARGET=key_manager  # -> hw/ip/key_manager/dv/fw/build/libkey_manager.a
make ocah-dv-fw-libs TARGET=smc          # -> hw/sys/smc/dv/fw/build/libsmc.a
make ocah-dv-fw-libs TARGET=sep          # -> hw/sys/sep/dv/fw/build/libsep.a
make ocah-dv-fw-libs                     # builds all discovered subsystem libraries
make ocah-dv-fw-list                     # list discovered subsystems
make ocah-dv-fw-tests TARGET=smc            # build all of smc's FW C tests
make ocah-dv-fw-tests TARGET=smc TEST=name  # build a single FW C test (TEST= selects it)
```

Each subsystem is an independent recursive sub-make with its own `toolchain.mk`,
so the three different ISA/ABI/libc environments never share global flag state.

Driver archives and discovered test ELFs both use the native PeakRDL register
headers under each block's `regs/gen/c/`.

## Toolchain contract

`RISCV_TOOLCHAIN` is empty by default (do not commit site-specific paths).
When empty the build uses `riscv64-unknown-elf-*` from `PATH`; when set
it must point at a **directory** containing those tools:

```
make ocah-dv-fw-libs TARGET=smc RISCV_TOOLCHAIN=/opt/riscv/bin
```

A `ocah-dv-fw-libs` build with no resolvable toolchain emits a clear error
pointing at `RISCV_TOOLCHAIN`. All three subsystems use picolibc via
`--specs=picolibc.specs` (provided by the Docker-provisioned toolchain); it is
**not** vendored here.

## Register interface notes

Generated PeakRDL headers are authoritative and are never hand-edited. Firmware
and tests use that surface directly (`.w` / `.f` on register unions; `*_BASE_ADDR`
macros from the generated address headers).

- **KM.** `key_manager_fw.h` pulls leaf PeakRDL headers (`km_csr.h`, wrapper-key
  headers, etc.) plus `key_manager_addr.h`.
- **SEP.** `sep_addr.h` (`SEP_TOP_*_BASE_ADDR`) and per-block headers under
  `regs/gen/c/blocks/` (`aes__*`, `SEP_TOP_AES_*`).
- **SMC.** Umbrella `smc.h` with `SMC_TOP_*_BASE_ADDR`. Two blocks are not
  modeled with open CSRs:
  - *PLL wrap* — placeholder footprint; no generated `SMC_PLL_WRAP_*` / `PLL_CNTL_*`
    / `CGM_*` / `AWM_*` definitions.
  - *I3C wrap* — open surface is `oca_i3c_wrap`; the vendor controller's wrap
    names are not emitted.

  Adopter overlay headers can be force-included locally without committing them:

  ```
  make ocah-dv-fw-libs TARGET=smc FW_EXTRA_CFLAGS="-include /path/to/smc_rename_stub.h"
  ```

This tree does not fetch a toolchain, vendor picolibc, or generate ROM
images.
