# DRBG Wrapper Verification

## Verification Goals

The DRBG wrapper verification strategy is focused on proving that the wrapper
glue logic preserves the intended behavior of the wrapped `csrng` and `edn`
blocks while enforcing the wrapper-specific interface contracts.

The primary verification goals are:

- validate the producer-driven entropy ingress behavior,
- confirm the routing priority between entropy distribution and CSRNG seed
  accumulation,
- verify correct 32-bit to 384-bit seed formation for CSRNG,
- verify EDN endpoint export and buffering on the AXI-Stream boundary,
- verify control-plane narrowing from 64-bit AXI-Lite to 32-bit wrapped CSRs,
- verify that unsupported AXI-Lite accesses are rejected cleanly, and
- confirm that the plain `bender script flist-plus -t drbg` flow compiles and
  runs cleanly.

## Verification Environment

The directed verification environment lives in `hw/comp/drbg/tb_vcs` and is
built around:

- `tb_drbg.sv` as the SystemVerilog harness,
- `test_drbg.py` as the cocotb test suite,
- a plain Bender-generated `drbg` filelist,
- VCS as the primary simulator, and
- Verilator as a parity target for the directed test scope.

The harness flattens the typed wrapper interfaces into cocotb-friendly signals
and exposes additional observability points for internal wrapper decisions such
as:

- route decision pulses,
- FIFO full and depth indicators,
- seed queue visibility,
- TL-UL activity after AXI-Lite filtering, and
- flattened EDN endpoint response/control hooks for test injection where needed.

## Verification Scope

The current DRBG verification scope is directed and integration-oriented rather
than constrained-random.

It focuses on wrapper behavior at the interfaces between:

- entropy ingress and the wrapper-local routing logic,
- the seed adapter and wrapped CSRNG entropy request interface,
- wrapped EDN endpoint traffic and exported AXI-Stream outputs, and
- the external AXI-Lite control plane and the wrapped CSRNG/EDN TL-UL buses.

It does not currently introduce a standalone UVM environment for the wrapper or
attempt exhaustive state-space exploration of the wrapped CSRNG/EDN internals.
Those internals continue to rely on their own component-level verification.

## Directed Test Inventory

The current cocotb regression includes the following tests.

| Test | Intent |
|---|---|
| `test_parameterized_smoke` | Confirms elaboration and idle behavior with sane non-zero parameters |
| `test_entropy_routing_priority` | Verifies distribution-first routing, CSRNG fallback, and drop-on-full behavior |
| `test_seed_packing_and_fips` | Verifies 12-word seed formation and provisional seed FIPS policy |
| `test_nondefault_seed_queue_depth` | Verifies multi-seed queueing when `SEED_FIFO_DEPTH > 1` |
| `test_edn_axis_endpoint_buffering` | Verifies endpoint buffering and AXI-Stream `tstrb` behavior |
| `test_multi_endpoint_backpressure_isolation` | Verifies endpoint independence under multi-endpoint elaboration |
| `test_csrng_axil_lane_filtering` | Verifies accepted and rejected CSRNG AXI-Lite access patterns |
| `test_edn_axil_lane_filtering` | Verifies accepted and rejected EDN AXI-Lite access patterns |
| `test_control_plane_idle_and_passthrough` | Verifies idle control behavior plus interrupt, alert, OTP, and lifecycle passthrough |
| `test_entropy_to_edn_end_to_end` | Verifies an end-to-end entropy-to-CSRNG-to-EDN path under software configuration |
| `test_entropy_to_csrng_software_path` | Verifies wrapper-provided entropy while CSRNG is exercised through its software command path |

Together these tests provide coverage of the wrapper-local contracts that are
most likely to regress during integration work.

## Simulator Flows

### Primary VCS regression

The standard directed regression is:

```bash
source bin/setup_env.sh
make -C hw/comp/drbg/tb_vcs sim-vcs
```

Run an individual test with:

```bash
make -C hw/comp/drbg/tb_vcs sim-vcs TESTCASE=test_entropy_routing_priority
```

### Verilator parity

The same harness and Python test suite are expected to run in Verilator for the
supported directed subset:

```bash
source bin/setup_env.sh
make -C hw/comp/drbg/tb_vcs sim-verilator
```

### Non-default parameter smoke

The wrapper should also be validated with at least one non-default elaboration:

```bash
source bin/setup_env.sh
make -C hw/comp/drbg/tb_vcs smoke-nondefault-vcs
make -C hw/comp/drbg/tb_vcs smoke-nondefault-verilator
```

The current smoke configuration overrides:

- `INGRESS_FIFO_DEPTH = 4`
- `SEED_FIFO_DEPTH = 2`
- `EDN_ENDPOINT_COUNT = 2`
- `ENDPOINT_FIFO_DEPTH = 4`

This specifically exercises queueing and endpoint behavior that cannot be proven
with the default single-endpoint, single-seed configuration alone.

## Lint and Build Checks

The wrapper flow also includes lightweight static checks:

```bash
source bin/setup_env.sh
make -C hw/comp/drbg/tb_vcs lint
make -C hw/comp/drbg/tb_vcs lint-verilator
make -C hw/comp/drbg/tb_vcs build-verilator
```

These checks are intended to catch:

- wrapper-local style and lint issues,
- Verilator parse/elaboration issues, and
- filelist generation regressions before full simulation.

## Build-System Verification

An important part of the DRBG verification story is build integrity, not just
simulation behavior.

The expected filelist flow is:

```bash
bender script flist-plus -t drbg
```

produces a compile-usable filelist on its own.

This means DRBG verification includes checking:

- package ordering in `Bender.yml`,
- the `drbg` Bender target contents,
- the `prim_assert.sv` shim macro surface used by the dependency tree, and
- the checked-in DRBG cocotb flow that consumes the generated filelist.

## Assertions and Observability

The wrapper RTL contains top-level assertions for:

- parameter legality,
- no TL-UL activity on rejected AXI-Lite accesses,
- known-value behavior on output and sideband signals, and
- fixed `tstrb` / seed-policy expectations.

These assertions complement the cocotb tests by catching illegal wrapper-local
states even when a dedicated Python test is not checking that condition
explicitly.

The harness-level debug signals are also considered part of the verification
infrastructure. They are not the production interface, but they materially
reduce debug time for directed regressions.

## Current Verification Limits

The current DRBG verification strategy has some intentional limits:

- no dedicated UVM environment for the wrapper,
- no formal verification for wrapper-local datapaths,
- no performance or throughput characterization beyond directed functional
  checks,
- no exhaustive overflow stress against an unbounded entropy producer, and
- no external FIPS sideband verification for EDN AXI-Stream output because that
  sideband is not currently part of the wrapper contract.

These are acceptable for the present feature scope because the wrapper is a
thin integration layer around already-verified underlying blocks.

## Recommended Regression Triggers

Rerun the DRBG regression whenever any of the following changes:

- `hw/comp/drbg/rtl/*`
- `hw/comp/drbg/tb_vcs/*`
- `hw/comp/csrng/rtl/*`
- `hw/comp/edn/rtl/*`
- `hw/common/prim/rtl/prim_assert.sv`
- `Bender.yml`

At minimum, the recommended sequence is:

1. `make -C hw/comp/drbg/tb_vcs lint`
2. `make -C hw/comp/drbg/tb_vcs sim-vcs`
3. `make -C hw/comp/drbg/tb_vcs smoke-nondefault-vcs`
4. `make -C hw/comp/drbg/tb_vcs sim-verilator` if simulator parity is expected

This sequence covers both functional behavior and the build assumptions that are
critical to the wrapper's integration story.
