# Open-source lint/synth/format flows

All targets are native-or-fail (tools must be on `PATH`; a hint to use the
container is printed on failure). Covered blocks:
the four `hw/sys` blocks (`smc`, `sep`, `smu`, `dtp`) plus vendored IP
packages (currently `aou`). The container bundles `slang`,
`yosys` + the `yosys-slang` plugin, and `verible`. See
[`scripts/docker.md`](../../../scripts/docker.md) for how the
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
lint-slang*` / `format-sv*` / `lint-sv-verible` / `synth-yosys*` all require the
matching tool on `PATH`; if it is not found, Make prints a hint to use
`./scripts/docker-run.sh run-here make …` and exits. `yosys` and `yosys-slang`
are optional host installs — the container is the intended fallback for
hosts that do not have them.

For ad-hoc debugging, the container is also reachable directly:

```bash
./scripts/docker-run.sh run-here yosys --version
./scripts/docker-run.sh shell-here # Use 1-1 paths as bender flist uses absolute paths
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

## Structural readiness without technology mapping

From the repository root, select the structural-only driver and a separate output
directory:

```bash
make synth-yosys-all BLOCK=dtp OCAH_SYNTH_DIR=build/readiness \
  OCAH_YOSYS_SYNTH_TCL="$PWD/flows/synth/yosys/scripts/readiness.tcl"
```

Run each block independently when collecting a full status matrix: the normal
multi-block dispatcher stops at the first failure. The driver elaborates with
strict module resolution, records pre-cleanup checks and cell statistics, rejects
inferred latch cells and blackboxes, then flattens and checks the cleaned design.
It stops before technology mapping or ABC; `TECH` does not affect this driver.
Frontend and lint warnings still require review even if the structural check
passes. Assertions are ignored, enum conversions are strict unless a block declares
the audited compatibility path below, and the Slang unroll limit is 100000. This is
not CDC or timing sign-off.

The flow loads the SystemVerilog frontend when Yosys starts (`yosys -m slang`);
individual Tcl drivers do not load a version-specific plugin filename. Unknown
modules remain fatal. Blocks that require a vendor compatibility exception declare
an owner-local diagnostic pattern file through `FLOW_SYNTH_SLANG_EXPECTED_ERRORS`
and the corresponding lowering option through `FLOW_SYNTH_SLANG_COMPAT_FLAGS`.
Before Yosys runs, full standalone Slang elaboration requires every listed
path-and-message pattern exactly once and rejects every additional error. Yosys then
uses the lowering option because accepting a diagnostic alone cannot turn the
strictly invalid enum assignment into a lowerable AST.

### Reviewed latch definition

A latch is reviewed only when all of these are recorded and verified:

1. The RTL expresses intentional storage (`always_latch` or an explicit latch
   primitive); an incomplete combinational assignment is not eligible.
2. Its functional purpose and enable behaviour are identified, including reset,
   test and power-state expectations where applicable.
3. A site-specific rule identifies the owning source location and expected latch
   cell type. Broad module-tree or count-only rules are not acceptable.
4. The synthesized latch cells retain source attribution to that reviewed site,
   and every other latch remains a failure.
5. The rule has an owner, rationale and review reference, and becomes stale when
   its source match is unused.

Cell counts are evidence for detecting change, not the basis for acceptance. The
current structural driver reports all latches and rejects them all; reviewed-latch
rules must not be added until this policy is implemented with unused-rule checking.

## Scaling across PDKs: `TECH=`

`TECH` (default `ihp-sg13g2`) is completely independent of `BLOCK`, so adding
a PDK later never touches an existing one:

```bash
make synth-yosys-all BLOCK=smu TECH=ihp-sg13g2   # default
make synth-yosys-all BLOCK=smu TECH=sky130A      # once wired up (see below)
```

The value is the PDK name as used by `ciel` — `yosys.mk` passes it into the
container as `PDK=$(TECH)`, and `scripts/init_tech.tcl` reads `$::env(PDK)`
back out. Only `ihp-sg13g2` is currently supported. PDKs are downloaded on
demand via `ciel build` into `PDK_ROOT` (default `local/pdks`). See
[`pdks.md`](pdks.md) for install instructions and how to wire up a new PDK.

Build output is TECH-scoped (`hw/<tree>/<block>/build/synth/<tech>/...`), so
re-running with a different `TECH` never clobbers a previous PDK's results.
`lint`/`format` have no PDK dimension, so their output stays flat
(`build/lint/...`).

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

This flow was adapted from the
[Croc Yosys synthesis flow](https://github.com/pulp-platform/croc/tree/main/yosys).

The Tcl scripts and IHP SG13G2 tech data follow a common open-source
Yosys + `yosys-slang` + ABC synthesis pattern, generalized here to be
env-driven and PDK-parametrized rather than hardcoded to one design/PDK.
`scripts/synth.tcl`'s ABC step uses a plain `-constr`/`-D <period>` pass,
keeping the tech data self-contained rather than depending on a large
recorded-AIG library file.
