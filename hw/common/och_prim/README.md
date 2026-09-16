# och_prim

Tenstorrent-specific **prim** RTL that has **no** matching module name under
`vendor/opentitan/` (Section B in the vendor delta inventory).

TT modifications to OpenTitan primitives that *do* have a vendored upstream
counterpart are no longer forked here; they are applied as per-module patches
under
[`vendor/lowRISC/opentitan/patches/`](../../../vendor/lowRISC/opentitan/patches/)
on top of `vendor/lowRISC/opentitan/upstream/hw/ip/prim{,_generic}/rtl/`.

| Path | Contents |
|------|----------|
| `rtl/` | TT-only prim modules (bus adapters, CDC sync, JTAG, libcell behavioral, etc.) with no upstream name |

Default simulation and synthesis file lists compile `rtl/` here plus the
(patched) vendored `prim*` under `vendor/opentitan/` (see repo-root `Bender.yml`).

The root [`Bender.yml`](../../../Bender.yml) is the source inventory for these
modules and their vendored counterparts.
