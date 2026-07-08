# Open-source lint/synth/format flows

Docker-by-default flows for the four `hw/sys` blocks (`smc`, `sep`, `smu`,
`dtp`) plus vendored IP packages (currently `aou-rtl`), built on open-source
tooling bundled in one pulled image,
[`hpretl/iic-osic-tools`](https://github.com/hpretl/iic-osic-tools): `slang`
(lint), `yosys` + the `yosys-slang` plugin (synthesis), and `verible`
(formatting). See [`tools/docker/README.md`](../../../tools/docker/README.md)
for how the container is invoked.

## Commands

```bash
make lint  [BLOCK=<block>]              # slang --lint-only
make synth [BLOCK=<block>] [TECH=<pdk>] # yosys + yosys-slang
make format [FORMAT_PATH=<path>]        # verible-verilog-format --inplace
make format-check [FORMAT_PATH=<path>]  # verible-verilog-format --verify
```

`BLOCK` selects one of the discovered blocks (`smc`/`sep`/`smu`/`dtp`/
`aou-rtl`; omit to run all of them - see [Layout](#layout) for how a block is
discovered). It is not called `TARGET` because `hw/common/regs/classify.mk`
already validates a top-level `TARGET=` against the (disjoint) register-block
namespace, unconditionally, for every goal - `make lint TARGET=smu` would fail with
"Unknown OCAH register block 'smu'" before lint ever ran, since `smu`/`dtp`
have no registers. `FORMAT_PATH` scopes formatting to a subtree (default
`hw`); it is not called `PATH` for the same kind of reason - that would
clobber the shell's own command-search path for every recipe. All four
commands run through Docker unconditionally (`OCAH_EDA_IMAGE`, overridable) -
there is no native-tool fallback, since essentially nobody has
`yosys`+`yosys-slang`+an open PDK on `PATH` the way a C compiler might be.

For ad-hoc debugging, the container is also reachable directly:

```bash
./scripts/docker-run.sh eda-run yosys --version
./scripts/docker-run.sh eda-shell
```

## Why lint (slang) and synth (yosys) both parse the same RTL

Both `slang --lint-only` and yosys's `read_slang` (the `yosys-slang` plugin)
parse and elaborate the same SystemVerilog RTL for the same block, off the
same bender-generated filelist - that is genuinely redundant work, and it is
fine by design:

- **Lint** is fast (no PDK, no netlist, seconds) and its whole purpose is rich
  semantic/style diagnostics (unused nets, width mismatches, latch inference,
  ...) - the cheap, frequent gate you run on every change.
- **Synth** only needs elaboration to succeed well enough to build RTLIL; it
  then spends most of its time on synthesis-specific work (coarse opt,
  techmap, ABC against the PDK's liberty files) that lint never touches.

Running lint before synth is exactly like running a linter before a compiler
even though the compiler also parses the code: not wasted effort, just staged
so cheap failures are caught before expensive ones. The one thing worth
avoiding is **configuration drift** between the two - if lint's bender target
list for a block drifted from synth's, "lint passed" would stop being a
reliable predictor of "synth will elaborate cleanly." That is why each block
has exactly **one** descriptor, `hw/<tree>/<block>/flow.mk`
(`FLOW_DESIGN`/`FLOW_BENDER_TARGETS`), consumed by both engines, instead of
two near-duplicate per-block files.

## Scaling across PDKs: `TECH=`

`TECH` (default `ihp-sg13g2`) is completely independent of `BLOCK`, so adding
a PDK later never touches an existing one:

```bash
make synth BLOCK=smu TECH=ihp-sg13g2   # default
make synth BLOCK=smu TECH=sky130A      # once wired up (see below)
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

1. Add `tech/<pdk>.tcl` - the only PDK-specific data: `pdk_cells_lib`/
   `pdk_sram_lib`/`pdk_io_lib` paths, the liberty file(s) (`tech_cells`/
   `tech_macros`), the tie-off cell names (`tech_cell_tiehi`/`tech_cell_tielo`),
   an optional `dont_use_list`, and the ABC constraint (`abc_constr`,
   `abc_period_ps`) - see `tech/ihp-sg13g2.tcl` for the shape.
2. If the PDK is already bundled in the image, nothing else changes:
   `scripts/init_tech.tcl` is a thin, tech-agnostic dispatcher that resolves
   `tech/$PDK.tcl` from the environment and errors with the list of known
   `tech/*.tcl` files on an unknown value.
3. If it is not bundled, point `OCAH_EDA_IMAGE` at an image/tag that has it.

`scripts/common.tcl`, `scripts/elab.tcl`, and `scripts/synth.tcl` never change
for a new PDK - every tech-specific value is hidden behind the generic names
`init_tech.tcl` + `tech/<pdk>.tcl` define.

## Timing constraints (`constraints.sdc`) vs. the ABC driving-cell/load model

Each `hw/sys/<block>/synth/constraints.sdc` (`smc`, `dtp`, `sep`, `smu`) is a
full Synopsys Design Constraints file - `create_clock`/`create_generated_clock`
for every clock domain, `set_clock_groups`, and `set_input_delay`/
`set_output_delay` for every top-level port - ported and sanitized from
`tt-oca-hw`'s block-level timing collateral and validated against this repo's
actual RTL port lists and hierarchy (see the header comment in each file for
block-specific caveats and any drift from the source).

**None of this is read by `make synth` today**, and that is intentional, not
an oversight. Yosys's ABC step (`scripts/synth.tcl`) does not consume SDC at
all - ABC's timing model is a driving-cell/load pair
(`tech/ihp-sg13g2.constr`, i.e. `set_driving_cell`/`set_load`) plus a single
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
├── lint/slang.mk             # ocah-lint / ocah-lint-one
├── synth/yosys/
│   ├── yosys.mk              # ocah-synth / ocah-synth-one, TECH ?= ihp-sg13g2
│   ├── scripts/
│   │   ├── common.tcl        # env vars, out/tmp/reports dirs
│   │   ├── init_tech.tcl     # resolves $PDK, sources tech/$PDK.tcl
│   │   ├── elab.tcl          # read_slang / hierarchy / check / proc
│   │   └── synth.tcl         # coarse opt / techmap / ABC / write_verilog (entry point)
│   └── tech/
│       ├── ihp-sg13g2.tcl    # liberty paths, tie cells, dont_use
│       └── ihp-sg13g2.constr # ABC driving-cell/load constraint
└── format/verible.mk         # ocah-format / ocah-format-check
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
`vendor/tenstorrent/aou-rtl/overlay/flow.mk` for an example.

## Provenance

The Tcl scripts and IHP SG13G2 tech data follow a common open-source
Yosys + `yosys-slang` + ABC synthesis pattern, generalized here to be
env-driven and PDK-parametrized rather than hardcoded to one design/PDK.
`scripts/synth.tcl`'s ABC step uses a plain `-constr`/`-D <period>` pass,
keeping the tech data self-contained rather than depending on a large
recorded-AIG library file.
