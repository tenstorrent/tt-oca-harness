# hw/common

Shared RTL, packages, and bus infrastructure used across OCAH subsystems. The
primitive libraries under this directory sit beside vendored OpenTitan
`prim` / `prim_generic` sources; together they are the cell inventory product
RTL and DV flows compile against.

| Path | Role |
|------|------|
| [`ocah_prim_generic/`](ocah_prim_generic/) | Behavioral standard cells a synthesis flow swaps one-for-one with a technology library |
| [`ocah_prim/`](ocah_prim/) | Composed TT building blocks with no OpenTitan counterpart |
| [`sync.sv`](sync.sv) | PULP `common_cells` vendor shim — not product RTL |
| [`axi/`](axi/), [`tlul/`](tlul/), [`ot_chip_cfg/`](ot_chip_cfg/), … | Shared buses, packages, and integration helpers |

## Primitive layering

OpenTitan ships the baseline leaf cells (`prim_flop_2sync`, `prim_clock_gating`,
`prim_buf`, …) under `vendor/lowRISC/opentitan/.../prim_generic/`. OCAH adds
TT-only cells in two further layers rather than duplicating what OpenTitan
already provides.

```
Product RTL and TT blocks
        │
        ├─► OpenTitan prim / prim_generic     (2-stage sync, gates, flops, …)
        │
        ├─► ocah_prim wrappers & composed CDC  (prim_sync3/4*, reset sync, autohs, …)
        │         │
        │         └─► ocah_prim_generic leaf cells (prim_flop_3sync*, gates, latch, …)
        │
        └─► sync  (PULP common_cells only — see below)
```

Nothing in [`ocah_prim/`](ocah_prim/) or [`ocah_prim_generic/`](ocah_prim_generic/)
reimplements a cell that already exists in OpenTitan `prim_generic`. When
OpenTitan has the primitive, instantiate it.

The exhaustive list of behavioral leaf cells an adopter must technology-map at
synthesis (`not(synth)`, 27 modules across OpenTitan and `ocah_prim_generic`) lives
in [`ocah_prim_generic/README.md`](ocah_prim_generic/README.md#technology-swap-inventory).

## CDC and synchronizers

Synchronizer-related sources split by caller and by abstraction:

| Layer | Location | Instantiate from |
|-------|----------|------------------|
| OpenTitan 2-stage leaf | `vendor/.../prim_generic/rtl/prim_flop_2sync.sv` | TT product RTL for a plain 2-FF sync |
| TT 3/4-stage leaf flops | [`ocah_prim_generic/rtl/`](ocah_prim_generic/rtl/) | Only inside TT wrappers or tech-aware leaf logic |
| TT width / CDC wrappers | [`ocah_prim/rtl/`](ocah_prim/rtl/) (`prim_sync3`, `prim_sync3r`, `prim_sync4`, `prim_sync4r`, …) | TT product RTL when a parametrized multi-bit sync or simulation CDC instrumentation is needed |
| Composed CDC blocks | [`ocah_prim/rtl/`](ocah_prim/rtl/) (`prim_sync_reset`, `prim_sync_data_autohs`, `prim_sync3_pulse`, …) | TT product RTL for reset crossing, coherent multi-bit transfer, or pulse crossing |
| PULP adapter | [`sync.sv`](sync.sv) | **Never** — compiled only for vendored `common_cells` |

Product RTL must not instantiate `sync`. It exists so PULP CDC modules
(`cdc_fifo_gray`, `cdc_4phase`, `clk_mux_glitch_free`, …) keep their upstream
API while the implementation uses OpenTitan and TT primitives instead of PULP's
generic two-stage `sync`.

When DV or integration flows pass `-t common_cell_sync_shim`, Bender excludes
PULP's `vendor/pulp-platform/common_cells/upstream/src/sync.sv` and compiles
[`sync.sv`](sync.sv) instead. That target is documented in
[`vendor/pulp-platform/common_cells/Bender.yml`](../vendor/pulp-platform/common_cells/Bender.yml).

## Where to add new code

| Need | Add to |
|------|--------|
| Same job as an OpenTitan `prim_*` / `prim_generic` cell | OpenTitan vendor tree (patch) or instantiate the existing OT cell |
| New mappable standard cell (gate, latch, N-stage sync flop chain) | [`ocah_prim_generic/`](ocah_prim_generic/) |
| New composed block (mux, arbiter, reset sequencer, CDC handshake) | [`ocah_prim/`](ocah_prim/) |
| Change how PULP `common_cells` builds its internal `sync` | [`sync.sv`](sync.sv) |

See [`ocah_prim/README.md`](ocah_prim/README.md) and
[`ocah_prim_generic/README.md`](ocah_prim_generic/README.md) for the module
inventories and guarding rules.
