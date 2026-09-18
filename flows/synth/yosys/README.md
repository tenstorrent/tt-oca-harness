# Open-source lint/synth/format flows

Slang and verible Make targets are native-or-fail (tools must be on `PATH`);
yosys synthesis is Docker-by-default. Covered blocks: the four `hw/sys`
blocks (`smc`, `sep`, `smu`, `dtp`) plus vendored IP packages (currently
`aou`). The EDA container image,
[`hpretl/iic-osic-tools`](https://github.com/hpretl/iic-osic-tools), bundles
`slang`, `yosys` + the `yosys-slang` plugin, and `verible`. See
[`tools/docker/README.md`](../../../tools/docker/README.md) for how the
container is invoked.

**Status: work in progress.** What is here is an initial set of scripts -
enough to elaborate and map the four `hw/sys` blocks, not a qualified
synthesis flow. Timing constraints are not wired in at all (see
[Timing constraints](#timing-constraints-constraintssdc-vs-the-abc-driving-cellload-model)
below), so the timing and area reports carry no weight. Commands, layout and
reports will keep changing as the flow matures; until then, use it at your own
risk.

## Commands

```bash
make lint-slang-all     [BLOCK=<block>]              # slang --lint-only
make synth-yosys-all    [BLOCK=<block>] [TECH=<pdk>] # yosys + yosys-slang
make format-sv          [FORMAT_PATH=<path>]         # verible-verilog-format --inplace
make format-sv-check    [FORMAT_PATH=<path>]         # verible-verilog-format --verify
```

`BLOCK` selects one of the discovered blocks (`smc`/`sep`/`smu`/`dtp`/
`aou`; omit to run all of them - see [Layout](#layout) for how a block is
discovered). It is not called `TARGET` because `hw/common/regs/classify.mk`
already validates a top-level `TARGET=` against the (disjoint) register-block
namespace, unconditionally, for every goal - `make lint-slang-all TARGET=smu` would fail with
"Unknown OCAH register block 'smu'" before lint ever ran, since `smu`/`dtp`
have no registers. `FORMAT_PATH` scopes formatting to a subtree (default
`hw`); it is not called `PATH` for the same kind of reason - that would
clobber the shell's own command-search path for every recipe. `make
lint-slang*` / `format-sv*` / `lint-sv-verible` require the matching tool on
`PATH` (or use `./scripts/docker-run.sh eda-run make …`). Only `make synth-yosys*`
runs through Docker by default (`OCAH_EDA_IMAGE`, overridable), since few
hosts have `yosys`+`yosys-slang`+an open PDK installed.

For ad-hoc debugging, the container is also reachable directly:

```bash
./scripts/docker-run.sh eda-run yosys --version
./scripts/docker-run.sh eda-shell
```

## Lint (slang) vs. synth's elaboration (yosys)

`slang --lint-only` and yosys's `read_slang` (the `yosys-slang` plugin) both
consume the same bender-generated filelist for a block, but at different
depth: lint checks each module's local semantics without building the fully
instantiated hierarchy, while synth's `read_slang` fully elaborates the
design (required to produce RTLIL). Lint is the fast, frequent gate you run
on every change; synth's elaboration is the authoritative one - a passing
lint is an early signal, not a full guarantee that synth will elaborate
cleanly.

What does matter is keeping both engines pointed at the same inputs: if
lint's bender target list for a block drifted from synth's, the two would
end up checking different designs entirely. That is why each block has
exactly **one** descriptor, `hw/<tree>/<block>/flow.mk`
(`FLOW_DESIGN`/`FLOW_BENDER_TARGETS`), consumed by both engines, instead of
two near-duplicate per-block files.

## Scaling across PDKs: `TECH=`

`TECH` (default `ihp-sg13g2`) is completely independent of `BLOCK`, so adding
a PDK later never touches an existing one:

```bash
make synth-yosys-all BLOCK=smu TECH=ihp-sg13g2   # default
make synth-yosys-all BLOCK=smu TECH=sky130A      # once wired up (see below)
```

The value is literally the PDK subdirectory name `hpretl/iic-osic-tools`
itself uses: it bundles several (`ihp-sg13g2`, `sky130A`, `gf180mcuD`,
`ihp-sg13cmos5l`) at `$PDK_ROOT/<name>`, selected by the `PDK` environment
variable. `TECH` is forwarded into the container as `PDK=$(TECH)` (see
`yosys.mk`), and `scripts/init_tech.tcl` reads `$::env(PDK)` back out.

Build output is TECH-scoped (`hw/<tree>/<block>/build/synth/<tech>/...`), so
re-running with a different `TECH` never clobbers a previous PDK's results.
`lint`/`format` have no PDK dimension, so their output stays flat
(`build/lint/...`).

### Adding a PDK

1. Add `tech/<pdk>/tech.tcl` - the only PDK-specific data: `pdk_cells_lib`/
   `pdk_sram_lib`/`pdk_io_lib` paths, the liberty file(s) (`tech_cells`/
   `tech_macros`), the tie-off cell names (`tech_cell_tiehi`/`tech_cell_tielo`),
   an optional `dont_use_list`, and the ABC constraint (`abc_constr`,
   `abc_period_ps`) - see `tech/ihp-sg13g2/tech.tcl` for the shape. Each PDK
   gets its own directory so it can grow beyond these two files (e.g. extra
   corners, vendored macro views) without colliding with another PDK's names.
2. If the PDK is already bundled in the image, nothing else changes:
   `scripts/init_tech.tcl` is a thin, tech-agnostic dispatcher that resolves
   `tech/$PDK/tech.tcl` from the environment and errors with the list of
   known `tech/*` subdirectories on an unknown value.
3. If it is not bundled, point `OCAH_EDA_IMAGE` at an image/tag that has it.

`scripts/common.tcl`, `scripts/elab.tcl`, and `scripts/synth.tcl` never change
for a new PDK - every tech-specific value is hidden behind the generic names
`init_tech.tcl` + `tech/<pdk>/tech.tcl` define.

## Timing constraints (`constraints.sdc`) vs. the ABC driving-cell/load model

Each `hw/sys/<block>/synth/constraints.sdc` (`smc`, `dtp`, `sep`, `smu`) is a
full Synopsys Design Constraints file - `create_clock`/`create_generated_clock`
for every clock domain, asynchronous clock groups, and `set_input_delay`/
`set_output_delay` for every top-level port - validated against this repo's
actual RTL port lists and hierarchy (see the header comment in each file for
block-specific caveats).

Each one also bounds its clock-domain crossings, in two layers. The asynchronous
groups are declared with `set_async_clock_groups`
(`flows/synth/constraints/async_clock_groups.tcl`), which also applies a default
`max_delay` to every inter-group clock pair. The block's
`<block>_cdc_max_delay.tcl`, sourced at the end of the SDC, then bounds each
synchronizer and async FIFO individually, using the procedures in
`flows/synth/constraints/cdc_max_delay_procs.tcl` and the per-instance calls in
`<block>_cdc_max_delay_generated.tcl`. "CDC Timing Constraints" in the Integrator
Guide documents how the bounds are derived and the integration steps they require.

**None of this is read by `make synth-yosys-all` today**, and that is intentional, not
an oversight. Yosys's ABC step (`scripts/synth.tcl`) does not consume SDC at
all - ABC's timing model is a driving-cell/load pair
(`tech/ihp-sg13g2/abc.constr`, i.e. `set_driving_cell`/`set_load`) plus a single
scalar clock period (`-D <period>`) passed on the `abc` command line; there
is no multi-clock, multi-exception constraint graph in the loop. A full SDC
only becomes a real synthesis-flow input once a place-and-route or
standalone STA stage is added downstream of Yosys - those tools need the
real clock/exception graph for timing-driven placement, CTS, and signoff.
This repo's flow currently stops at Yosys synthesis, so the `.sdc` files are
carried as genuine, validated documentation of block-level timing intent:
ready to become real inputs the moment such a stage exists, rather than
needing to be reverse-engineered from scratch later.

A standalone post-synthesis OpenSTA run (source the SDC, check timing
against the synthesized netlist, no P&R required) is a plausible, low-cost
future addition - OpenSTA (`sta`) is already present in the EDA image used
by this flow - but it was deliberately not wired up in this pass so this SDC
work could land as pure documentation first.

## Layout

```
flows/
├── common.mk                # shared plumbing: docker-run + bender-flist + dispatch-loop macros
├── lint/slang.mk             # ocah-lint-slang-all / ocah-lint-slang
├── synth/constraints/        # engine-agnostic SDC helpers, sourced by each block's constraints.sdc
│   ├── async_clock_groups.tcl   # set_async_clock_groups: -allow_paths + default inter-group bound
│   └── cdc_max_delay_procs.tcl  # one set_cdc_max_delay_* proc per CDC element type
├── synth/yosys/
│   ├── yosys.mk              # ocah-synth-yosys-all / ocah-synth-yosys, TECH ?= ihp-sg13g2
│   ├── scripts/
│   │   ├── common.tcl        # env vars, out/tmp/reports dirs
│   │   ├── init_tech.tcl     # resolves $PDK, sources tech/$PDK/tech.tcl
│   │   ├── elab.tcl          # read_slang / hierarchy / check / proc
│   │   └── synth.tcl         # coarse opt / techmap / ABC / write_verilog (entry point)
│   └── tech/
│       └── ihp-sg13g2/
│           ├── tech.tcl      # liberty paths, tie cells, dont_use
│           └── abc.constr    # ABC driving-cell/load constraint
└── lint/verible.mk           # ocah-lint-sv-verible, ocah-format-sv / ocah-format-sv-check
```

Each `hw/sys/<block>/flow.mk` sets `FLOW_DESIGN`/`FLOW_BENDER_TARGETS` and
includes `flows/common.mk` + the two engines above. Each
`hw/sys/<block>/synth/constraints.sdc` holds that block's full timing intent
(see [above](#timing-constraints-constraintssdc-vs-the-abc-driving-cellload-model));
it lives next to the block rather than under `flows/` because it is
block-specific data, not shared flow plumbing.

`flows/common.mk` discovers block descriptors by globbing for `flow.mk`
under `hw/sys/*`, `hw/ip/*`, `hw/ip/*/*`, and `vendor/*/*/overlay/*` - a
block's name is normally its own directory name, except under
`vendor/<org>/<pkg>/overlay/flow.mk`, where the block is named after `<pkg>`
(the package directory one level above `overlay/`). Vendored packages keep
their flow descriptor in `overlay/` rather than editing the vendored tree
directly, mirroring how other TT-specific collateral is already layered onto
vendored packages in this repo (generated regs, waivers, etc.) - see
`vendor/tenstorrent/aou/overlay/flow.mk` for an example.

## Provenance

The Tcl scripts and IHP SG13G2 tech data follow a common open-source
Yosys + `yosys-slang` + ABC synthesis pattern, generalized here to be
env-driven and PDK-parametrized rather than hardcoded to one design/PDK.
`scripts/synth.tcl`'s ABC step uses a plain `-constr`/`-D <period>` pass,
keeping the tech data self-contained rather than depending on a large
recorded-AIG library file.
