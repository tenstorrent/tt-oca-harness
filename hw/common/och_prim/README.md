# och_prim

Tenstorrent building-block RTL for which OpenTitan has no primitive: bus
adapters and arbiters, counters, clock dividers and glitch-free clock muxes,
multi-stage and pulse synchronizers, reset synchronizers, JTAG scan cells and
memory wrappers. Modules here are composed from ordinary RTL and from the cells
in [`../och_prim_generic/`](../och_prim_generic/) and the vendored OpenTitan
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
