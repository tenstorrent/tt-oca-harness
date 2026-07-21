# och_prim_generic

Technology-independent behavioral implementations of standard cell primitives:
flip-flops, clock muxes, clock gates, multi-sync flops, and simple logic gates.
These are the **simulation and generic-synthesis** stand-ins for the
TT-specific drive-strength/flavor variants in [`../och_prim/`](../och_prim/).

| Path | Contents |
|------|----------|
| `rtl/` | 24 behavioral `prim_*.sv` modules (flops, syncs, muxes, gates, clock cells), plus `prim_pad_shim.sv` |

In a synthesis flow that targets a specific process node, every module here
should be overridden by a technology-mapped implementation from the library
collateral. In simulation and FPGA targets these behavioral models are used
as-is.

`prim_pad_shim.sv` is the exception to the "standard cell primitive" rule: it
translates [`gpio_shim_pkg::gpio_model_ctrl_t`](../../ip/gpio/rtl/gpio_shim_pkg.sv)
into the vendored OpenTitan `prim_pad_wrapper_pkg::pad_attr_t` and instantiates
the technology-independent `prim_pad_wrapper` (from
`vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/`) — one instance per
pin, used by the reference `hw/top/smc_ip_integration.sv` wrapper. Like
`prim_pad_wrapper` itself, it is simulation-only and not synthesizable; a real
integration replaces it with foundry pad cells driven directly from the GPIO
shim.

See [`../och_prim/README.md`](../och_prim/README.md) for the TT-specific
aggregators, adapters, and the OpenTitan prim fork inventory.
