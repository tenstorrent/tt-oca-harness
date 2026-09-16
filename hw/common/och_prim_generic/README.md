# och_prim_generic

Technology-independent behavioral implementations of standard cell primitives:
flip-flops, clock muxes, clock gates, multi-sync flops, and simple logic gates.
These are the **simulation and generic-synthesis** stand-ins for the
TT-specific drive-strength/flavor variants in [`../och_prim/`](../och_prim/).

| Path | Contents |
|------|----------|
| `rtl/` | 28 behavioral `prim_*.sv` modules (flops, syncs, muxes, gates, clock cells) |

In a synthesis flow that targets a specific process node, every module here
should be overridden by a technology-mapped implementation from the library
collateral. In simulation and FPGA targets these behavioral models are used
as-is.

See [`../och_prim/README.md`](../och_prim/README.md) for the TT-specific
aggregators, adapters, and the OpenTitan prim fork inventory.
