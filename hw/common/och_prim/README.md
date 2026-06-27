# och_prim

Tenstorrent-specific **prim** RTL that has **no** matching module name under
`vendor/opentitan/` (Section B in the vendor delta inventory).

TT modifications to OpenTitan primitives that *do* have a vendored upstream
counterpart are no longer forked here; they are applied as per-module patches
under [`vendor/opentitan/patches/`](../../../vendor/opentitan/patches/) on top of
`vendor/opentitan/upstream/hw/ip/prim{,_generic}/rtl/`. See
[`../ot_prim_modifications/`](../ot_prim_modifications/) for the open patch inventory.

| Path | Contents |
|------|----------|
| `rtl/` | TT-only prim modules (bus adapters, CDC sync, JTAG, libcell behavioral, etc.) with no upstream name |
| `icl/` | JTAG ICL descriptions (where present) |

Default simulation and synthesis file lists compile `rtl/` here plus the
(patched) vendored `prim*` under `vendor/opentitan/` (see repo-root `Bender.yml`).

**Full inventory (TT-only prims + the OpenTitan fork patches):**
[../ot_prim_modifications/VENDOR_DELTA.md](../ot_prim_modifications/VENDOR_DELTA.md)
