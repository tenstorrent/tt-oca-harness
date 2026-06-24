# Shared DV Firmware Policy

This directory holds shared DV firmware collateral only (shared toolchain rules,
the static register umbrellas, and policy notes). Keep it thin: subsystem
firmware sources live beside the hardware that owns them.

- `hw/ip/km/dv/fw/`
- `hw/sys/smc/dv/fw/`
- `hw/sys/sep/dv/fw/`

Discovery mirrors the register flow: any block exposing a `dv/fw/fw.mk` is built
automatically, so new subsystems need no dispatcher edits.

## Makefile roles

There are two kinds of `fw.mk` in the tree:

* `hw/common/dv/fw/fw.mk` is the open-tree DV firmware entrypoint. It owns the
  user-visible targets (`ocah-dv-fw`, `ocah-dv-fw-tests`, list and clean
  targets), discovers subsystem `dv/fw/fw.mk` files under `OCAH_ROOT`, and binds
  that discovery to the open tree.
* `hw/{ip,sys}/<name>/dv/fw/fw.mk` is a subsystem build manifest. It declares
  `FW_*` inputs for one firmware target: source files, include paths, linker
  scripts, test deltas, and the subsystem `toolchain.mk`.

`dispatch.mk` sits between those roles. It has no tree-specific targets and does
not know about the open tree; it is only a small library of make functions for
discovering `dv/fw/fw.mk` files, mapping them to subsystem names, and fanning a
goal out to selected recursive sub-makes. Keeping that logic in `dispatch.mk`
lets another tree reuse the same fan-out machinery while keeping its own
entrypoint target names and help text in its own `fw.mk`.

So `fw.mk` is still the right name when the file is the makefile an integrator or
subsystem includes/runs for firmware. `dispatch.mk` names the private helper
layer, not another firmware build entrypoint.

## Two-stage firmware port

The `tt-oca-hw` firmware is ported in two explicit milestones. Do **not** start
with tests; every test depends on the driver/register-header interface being
correct first.

1. **Driver-archive milestone (current).** Port and reconcile each subsystem's
   runtime drivers until it compiles into one archive library. Compile success
   is the interface check that the driver sources, toolchain flags, and the
   generated `tt-oca` register headers agree.
   - `hw/ip/km/dv/fw/build/libkm.a`
   - `hw/sys/smc/dv/fw/build/libsmc.a`
   - `hw/sys/sep/dv/fw/build/libsep.a`
2. **DV-test milestone (later).** Once all three archives compile, port the DV
   tests and add generic test-build plumbing that links each test against the
   corresponding driver archive. Test porting is kept separate so failures are
   easy to attribute.

### Build commands

```
make dv-fw TARGET=km        # -> hw/ip/km/dv/fw/build/libkm.a
make dv-fw TARGET=smc       # -> hw/sys/smc/dv/fw/build/libsmc.a
make dv-fw TARGET=sep       # -> hw/sys/sep/dv/fw/build/libsep.a
make dv-fw                  # builds all discovered subsystems
make dv-fw-list             # list discovered subsystems
make dv-fw-tests TARGET=smc            # build all of smc's FW C tests
make dv-fw-tests TARGET=smc TEST=name  # build a single FW C test (TEST= selects it)
```

Each subsystem is an independent recursive sub-make with its own `toolchain.mk`,
so the three different ISA/ABI/libc environments never share global flag state.

### Toolchain contract

`RISCV_TOOLCHAIN` is intentionally empty by default (do not commit site-specific
paths). When empty the build uses `riscv64-unknown-elf-*` from `PATH`; when set
it must point at a **directory** containing those tools:

```
make dv-fw TARGET=smc RISCV_TOOLCHAIN=/opt/riscv/bin
```

A `dv-fw` build with no resolvable toolchain emits a clear error pointing at
`RISCV_TOOLCHAIN`. All three subsystems use picolibc via
`--specs=picolibc.specs` (provided by the Docker-provisioned toolchain); it is
**not** vendored here.

## Known interface deltas from tt-oca-hw

The ported drivers expected the old flattened `*_reg.h` register surface; tt-oca
emits PeakRDL headers instead. Generated headers stay authoritative and are
never hand-edited. The open driver blocks are rewritten to the native interface
(no in-tree shim); only proprietary/vendor blocks with no generated equivalent
fall back to a local, uncommitted stub force-included via `FW_EXTRA_CFLAGS`.

- **Raw value member.** Old unions expose `.val`; PeakRDL unions expose `.w`
  (raw) and `.f` (field view). Driver accesses are updated to `.w`/`.f`.
- **KM.** Old drivers used `key_manager_regs.h` with types like
  `KM_KPV_CTRL_REG_reg_u` at macros like `KPV_CTRL_0__REG_ADDR`. These are
  rewritten directly to the native `km.h` unions (`km_kpv__ctrl_reg_t`) and
  `km_addr.h` addresses (`KEY_MANAGER_KPV_CTRL_BASE_ADDR(idx)`). `libkm.a` builds
  fully native with no shim or stub.
- **SEP.** Old SEP used the flattened `och_sep_top_reg.h` (absolute `*_REG_ADDR`,
  block `*_REG_MAP_BASE_ADDR`, unions like `EL2_PIC_MEIGWCTRL_reg_u`). These are
  rewritten to `sep_addr.h` (`OCH_SEP_TOP_*_BASE_ADDR`) and per-block headers
  (`el2_pic__MEIGWCTRL_t`). The SEP register port is validated; build with the
  Docker-provisioned picolibc toolchain (see `tools/docker/README.md`).
- **SMC.** Open driver blocks use the native umbrella `smc.h` (per-block PeakRDL
  headers, `SMC_TOP_*_BASE_ADDR` addresses) directly. Two blocks are **not
  modeled** by tt-oca and keep the legacy surface:
  - *PLL wrap* - `pll_wrap.rdl` is an intentional placeholder footprint
    (proprietary PLL hard-IP, no CSRs), so `SMC_PLL_WRAP_*`, `PLL_CNTL_*`,
    `CGM_*`, `AWM_*` have no generated definitions.
  - *I3C wrap* - renamed/re-parented to `oca_i3c_wrap` (now directly under
    `smc_top`), so the legacy `SMC_AXIL_EXTENSION_CDNS_I3C_WRAP_*` addresses and
    `CDNSI3C_REG_*`/`I3C_CTRL_*` union types are not emitted.

  These proprietary blocks are supplied by a local, **uncommitted** vendor stub
  (copied verbatim from the frozen tt-oca-hw header, raw `val` renamed to `w`)
  force-included at build time so the committed tree stays clean:

  ```
  make dv-fw TARGET=smc FW_EXTRA_CFLAGS="-include /path/to/smc_rename_stub.h"
  ```

  The stub's I3C base addresses are still the tt-oca-hw map values; reconciling
  them to `oca_i3c_wrap.h` is deferred to the DV-test milestone. SEP uses the
  same `FW_EXTRA_CFLAGS` stub mechanism for its proprietary blocks.

This skeleton intentionally does not fetch a toolchain, vendor picolibc, or
generate ROM images.
