# ocah_prim_generic

Behavioral models of standard cells that a synthesis flow replaces one-for-one
with a technology cell: multi-stage synchronizer flops, a metastability-hardened
flop, a negative latch, a clock NAND, a data mux and a handful of logic gates.

| Path | Contents |
|------|----------|
| `rtl/` | 16 behavioral `prim_*.sv` cells (the OCAH half of the swap inventory below) |

Every file here is a direct tech swap. The root [`Bender.yml`](../../../Bender.yml)
lists this directory under `not(synth)`, so simulation, lint and FPGA builds
use these models as-is. A synthesis flow that passes `-t synth` must supply a
matching technology-library implementation for **every** module in the inventory
below — not only the files in `rtl/`. A module with no technology replacement
belongs in [`../ocah_prim/`](../ocah_prim/) instead.

Each technology under [`flows/synth/pdk/`](../../../flows/synth/pdk/)
implements the whole inventory in its `prim/` directory.

## Technology swap inventory

These **29 modules** are the exhaustive set of behavioral `prim_*` leaf cells
guarded with `not(synth)` in the open tree. An adopter synthesis flow that
passes `-t synth` must provide a one-for-one technology replacement for each
name (same module name and ports). Nothing else in [`../ocah_prim/`](../ocah_prim/)
or [`../sync.sv`](../sync.sv) belongs on this list — those are composed blocks
or vendor shims, not mappable standard cells.

The manifests are the source of truth:

- OpenTitan: [`vendor/lowRISC/opentitan/Bender.yml`](../../../vendor/lowRISC/opentitan/Bender.yml)
- OCAH: [`Bender.yml`](../../../Bender.yml) (`ocah_prim_generic` group)

### OpenTitan `prim_generic` (13)

Vendored behavioral sources under
`vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/`:

- `prim_and2`
- `prim_buf`
- `prim_clock_buf`
- `prim_clock_gating`
- `prim_clock_inv`
- `prim_clock_mux2`
- `prim_flop`
- `prim_flop_2sync`
- `prim_flop_en`
- `prim_flop_no_rst`
- `prim_inv`
- `prim_xnor2`
- `prim_xor2`

### OCAH `ocah_prim_generic` (16)

Behavioral sources under [`rtl/`](rtl/):

- `prim_and3`
- `prim_ao222`
- `prim_clock_nand2`
- `prim_flop_3sync`
- `prim_flop_3sync_r`
- `prim_flop_3sync_s`
- `prim_flop_4sync`
- `prim_flop_4sync_r`
- `prim_flop_4sync_s`
- `prim_latch_n`
- `prim_metastab_hardened_dffr`
- `prim_nand4`
- `prim_nor4`
- `prim_or2`
- `prim_or4`
- `prim_stdmux2`

## Synchronizer leaf cells in this directory

The multi-stage entries above are single-purpose flop chains mapped to standard
cells. Product RTL normally instantiates them only through the wrappers in
[`../ocah_prim/`](../ocah_prim/) (`prim_sync3`, `prim_sync3r`, …), not directly.

| Cell | Stages / style |
|------|----------------|
| `prim_flop_3sync`, `prim_flop_3sync_r`, `prim_flop_3sync_s` | 3-FF chain (no reset, async clear, async set) |
| `prim_flop_4sync`, `prim_flop_4sync_r`, `prim_flop_4sync_s` | 4-FF chain (same reset variants) |
| `prim_metastab_hardened_dffr` | Metastability-hardened flop (used by `prim_sync_reset`) |

Two-stage synchronizers are OpenTitan `prim_flop_2sync` (listed above), not files
in this directory. [`../sync.sv`](../sync.sv) is a separate PULP vendor shim and
is not part of the swap inventory; see [`../README.md`](../README.md).
