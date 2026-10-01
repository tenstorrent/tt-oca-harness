# ocah_prim

Tenstorrent building-block RTL for which OpenTitan has no primitive: bus
adapters and arbiters, counters, clock dividers and glitch-free clock muxes,
multi-stage and pulse synchronizers, reset synchronizers, JTAG scan cells and
memory wrappers. Modules here are composed from ordinary RTL and from the cells
in [`../ocah_prim_generic/`](../ocah_prim_generic/) and the vendored OpenTitan
`prim` / `prim_generic` libraries; they are never swapped for a technology cell
themselves.

OCAH uses OpenTitan IP, and with it OpenTitan's primitives. A module belongs
here only if nothing under
`vendor/lowRISC/opentitan/upstream/hw/ip/prim{,_generic}/rtl/` does the same
job. Two-stage synchronizers, clock gates, clock muxes and buffers, flops and
simple gates are OpenTitan's (`prim_flop_2sync`, `prim_clock_gating`,
`prim_clock_mux2`, `prim_clock_buf`, `prim_buf`, `prim_flop`, `prim_inv`,
`prim_and2`, ...); instantiate those rather than adding a TT equivalent.
Changes TT needs in an OpenTitan primitive are applied as per-module patches
under
[`vendor/lowRISC/opentitan/patches/`](../../../vendor/lowRISC/opentitan/patches/),
not forked here.

| Path | Contents |
|------|----------|
| `rtl/` | TT-only building blocks with no OpenTitan counterpart |

The root [`Bender.yml`](../../../Bender.yml) is the source inventory for these
modules and their vendored counterparts.

## CDC and synchronizers

TT product RTL reaches synchronizers through this stack (see
[`../README.md`](../README.md) for the full picture):

| Module | Role |
|--------|------|
| `prim_sync3`, `prim_sync3r`, `prim_sync4`, `prim_sync4r` | Width-parametrized wrappers around [`../ocah_prim_generic/`](../ocah_prim_generic/) multi-stage flop chains; under `` `ifdef SIMULATION `` they optionally insert OpenTitan `prim_cdc_rand_delay` before the leaf chain |
| `prim_sync_reset` | Async-reset synchronizer with scan bypass |
| `prim_sync_data_autohs` | Multi-bit coherent CDC with auto handshake |
| `prim_sync3_pulse` | Clock-domain pulse crossing |

For a plain 2-FF synchronizer, instantiate OpenTitan `prim_flop_2sync` directly.
Do not add another wrapper here.

[`../sync.sv`](../sync.sv) is **not** part of `ocah_prim`. It implements the
PULP `sync` module name for vendored `common_cells` when flows pass
`-t common_cell_sync_shim`. Product blocks must not instantiate `sync`; only
PULP CDC sources in `vendor/pulp-platform/common_cells/` do.
