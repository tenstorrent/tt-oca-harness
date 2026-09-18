# PDK management

PDKs are downloaded on demand via `ciel build` into `PDK_ROOT` (default
`local/pdks`); a version-pinned sentinel file gates re-download so each PDK
is only fetched once. Run `make ocah-synth-pdks` to pre-install all supported
PDKs at once (useful for offline environments):

```bash
make ocah-synth-pdks [PDK_ROOT=<path>]
```

## Supported PDKs

`ciel` currently supports three PDKs, all wired up in `yosys.mk`:

| `TECH=`       | Status              |
|---------------|---------------------|
| `ihp-sg13g2`  | Supported (default) |
| `sky130`      | Not yet wired up    |
| `gf180mcuD`   | Not yet wired up    |

`sky130` and `gf180mcuD` have `ciel` version hashes and `ocah-synth-pdks`
entries but no `tech/<pdk>/tech.tcl` yet, so they cannot be used with
`make synth-all`.

## Adding a PDK

1. Add `tech/<pdk>/tech.tcl` - the only PDK-specific data: `pdk_cells_lib`/
   `pdk_sram_lib`/`pdk_io_lib` paths, the liberty file(s) (`tech_cells`/
   `tech_macros`), the tie-off cell names (`tech_cell_tiehi`/`tech_cell_tielo`),
   an optional `dont_use_list`, and the ABC constraint (`abc_constr`,
   `abc_period_ps`) - see `tech/ihp-sg13g2/tech.tcl` for the shape. Each PDK
   gets its own directory so it can grow beyond these two files (e.g. extra
   corners, vendored macro views) without colliding with another PDK's names.
2. Add a `<pdk>_HASH` variable in `yosys.mk` with the `ciel` version hash, and
   add `${PDK_ROOT}/<pdk>` as a prerequisite of `ocah-synth-pdks`. That is all
   `yosys.mk` needs: `scripts/init_tech.tcl` is a thin, tech-agnostic
   dispatcher that resolves `tech/$PDK/tech.tcl` from the environment and
   errors with the list of known `tech/*` subdirectories on an unknown value.

`scripts/common.tcl`, `scripts/elab.tcl`, and `scripts/synth.tcl` never change
for a new PDK - every tech-specific value is hidden behind the generic names
`init_tech.tcl` + `tech/<pdk>/tech.tcl` define.
