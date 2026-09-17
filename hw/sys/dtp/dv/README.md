# DTP OCAH Open-Source TB

OCAH open-source **PyUVM** DV testbench for **DTP (Debug & Test Ports)** in the
`tt-oca-harness` repository. DTP is the
subsystem that hosts the primary JTAG TAP (IEEE 1149.1), the JTAG2AXI debug
bridges, the iJTAG networks (IEEE 1687), and the cross-trigger network (CTP/CTM).
It follows the canonical `hw/sys/<system>/dv/` layout and runs on Verilator.

The cocotb realization composes the shared OCAH VIPs in a PyUVM hierarchy;
the SV-UVM twin and the differences between the two realizations are in
`docs/DTP_TB_ARCH.adoc`:

```
dtp_<scenario>_test (@pyuvm.test, on dtp_base_test from the ocah_lib OcahTest base)
  └─ DtpEnv
       ├─ DtpJtagAgent      sequencer + DtpJtagDriver over the ocah_jtag_vip engine
       ├─ DtpAxiAgent       ocah_axi_vip slave agents and passive monitors on the three
       │                    JTAG2AXI bridge ports, with memory backdoor
       ├─ DtpXtrigAgent     ocah_axi_vip AXI-Lite master on the CSR port + CTP/CTM pin BFM
       ├─ DtpStapDsAgent    ocah_jtag_vip slave devices behind the STAP host ports
       ├─ DtpScoreboard     IDCODE and JTAG2AXI data-integrity checks on the driver's
       │                    completed-item stream
       └─ DtpAxiScoreboard  shared ocah_axi_vip reference models and scoreboard, armed
                            by the JTAG2AXI tests with required evidence IDs
  seq_lib/ dtp_base_test_seq → dtp_<family>_base_test_seq → dtp_<scenario>_test_seq
```

Tests inherit `dtp_base_test` (env build, the `bring_up()` reset ladder, the
looped `run_scenario()`); scenario sequences inherit a family base on
`dtp_base_test_seq` (common TAP building blocks). A single-scenario test pairs
`tests/<name>.py` with `seq_lib/<name>_seq.py`; a multi-scenario family shares
one parameterized sequence.

- `docs/` — public verification plan, TB architecture, functional-coverage plan, and the requirement-to-test matrix (`docs/DTP_SCOPE_TRACEABILITY.adoc`). The design specification and the register maps are designer-owned: `../doc/` (DTP integration plus the JTAG and cross-trigger IP chapters) and the SystemRDL under `hw/ip/cross_trigger/*/regs/`.
- `tb/` — SystemVerilog testbench top (`dtp_uvm_top`, one framework-neutral core shared by the cocotb and SV-UVM flows) and the `dtp_tb_if`, `dtp_scan_if`, and `dtp_xtrig_if` TB interfaces.
- `env/` — UVM env: config, JTAG agent, AXI memory agent, scoreboard, TDR encoders.
- `seq_lib/` — reusable UVM sequences (the VPLAN scenarios).
- `tests/` — `uvm_test` classes (one `@pyuvm.test()` per file, VPLAN-named).
- `testlists/` — native TOML testlists.
- `dtp_sim_cfg.toml` — the DUT's simulation defaults, run modes, Bender targets, and tool knobs.
- `formal/` — formal property modules and bind files, one per described block of the plan's nine targets, and the binds of the shared AXI and JTAG checkers (`props/`), the open-path SymbiYosys task files and environment modules of the `dtp`, `jtag2axi` and `cross_trigger_network` tops (`fpv/sby/`), and the generated filelist and work directories (`build/`); see `hw/common/dv/docs/formal-property-style.adoc`.

## BFM Policy

The DTP TB imports the unified OCAH BFM packages from `hw/common/dv/vip`.
Those wrappers keep protocol details out of tests and use the project-local
protocol BFMs behind a stable API:

| Interface | VIP | Rationale |
|-----------|-----|-----------|
| JTAG TAP (IEEE 1149.1) | **`ocah_jtag_vip`** | `dtp`'s JTAG port is raw `{tck,tms,trst_n}`+`tdi`/`tdo` — pin-level. |
| AXI4 debug manager (`axi_smc_dbg`) | **`ocah_axi_vip`** (`OcahAxiSlaveAgent`) | JTAG2AXI bridge drives it; memory model responds. |
| AXI4-Lite OTP managers (`smc_otp`, `sep_otp`) | **`ocah_axi_vip`** (`OcahAxiLiteSlaveAgent`) | Standard AXI-Lite; memory model responds. |
| AXI4-Lite CSR subordinate (`axil_xtrig`) | **`ocah_axi_vip`** (`ocah_axi_master_agent`, SV-UVM / `OcahAxiLiteMasterAgent`, cocotb) | Both flows drive the CSR port through the shared VIP master; the channel-skew, RREADY-hold, and partial-strobe operations live on its sequence APIs. |
| Boundary scan / BSR loopback | DUT-local `DtpScanModel` | Implemented for this TB's compact identity loopback; not a generic boundary-cell model. |
| iJTAG (IEEE 1687 SIB networks) | DUT-local `DtpIjtagSibModel` | Implemented for DTP's three SIBs, lifecycle gates, and the bench's 4/5/6-bit instrument stubs; topology-specific. |
| STAP / 3DCR | DUT-local `DtpStap3dcrModel` over **`ocah_jtag_vip`** slave devices | Composed TAP_3DCR chain model (PTAP 3DCR, per-STAP SIB/3DCR, network-wide IR scans); the STAP host ports loop back by default, and the STAP-selection scenarios splice a shared `ocah_jtag_vip` reactive TAP behind every port (see "Downstream STAP TAPs"). |
| CTP / CTM | DUT-local `DtpXtrigBfm` / `DtpCtmRefModel` | Implemented for DTP signal counts, CSR layout, and OCAH routing policy; promote only after parameterization and independent reuse. |

The cocotb runner adds `hw/common/dv/vip` to `PYTHONPATH` so tests can import
the unified wrappers and their local backends.
The ownership and promotion checklist is in `hw/common/dv/README.md`.

### Downstream STAP TAPs

Each STAP host port (`jtag_stap_{io,smc,sep,extra0}_host_*`) has one
downstream `ocah_jtag_if` instance in tb_top (`u_stap_<x>_ds_if`, wired from
the port's forwarded TAP pins and its TDO) and one attach enable,
`dtp_scan_if.stap_<x>_ds_en`. With the enable clear (the default for every
scenario) the port's TDI is its own TDO: the wire loopback. With it set the
bench splices a reactive `ocah_jtag_vip` slave device on that instance behind
the port (cocotb: `env/dtp_stap_ds_agent.py`; SV-UVM: four
`ocah_jtag_slave_agent`s in `dtp_env`), one IEEE 1149.1 TAP per port with a 5-bit IR, a distinct IDCODE,
and one writable `DS_TDR` of a distinct width. The four
`dtp_3dcr_stap_sel_*_test` scenarios attach all four ports (test attribute
`stap_ds_attach` / `stap_ds_attach_mask()`) and prove selection, gating,
isolation, and recovery end to end: the downstream IDCODE and a written
`DS_TDR` read back through the selected STAP, the register stays frozen while
the port is gated (the downstream TAP parks in Test-Logic-Reset), and recovery
is checked against real downstream state. Once a STAP is selected every scan
is composed over the full network, IR scans included, because the PTAP routes
its instruction shift-out into the STAP chain.

## Simulation defines

DTP DV, lint, and synthesis compiles pass preprocessor defines that switch the
shared testbench shape, gate assertions, and select a simulation vs synthesis
view. The inventory — each define, why it exists, and what a DTP build does with
or without it — is in [`../doc/defines.adoc`](../doc/defines.adoc). Runtime
environment variables and plusargs in the commands below are not preprocessor
defines.

## Protocol assertions

The shared protocol checkers `ocah_jtag_sva` (primary TAP) and `ocah_axi_sva`
(SMC OTP, SEP OTP, and XTRIG AXI4-Lite; SMC AXI4) are instantiated in the
framework-neutral core of `tb/tb_top.sv`, so both frameworks run them. Their
rules split into two trees by simulator capability:

| Tree | Macros | Rules | Live on |
|---|---|---|---|
| Two-state | `OCAH_SVA_RULE` / `OCAH_SVA_ASSERT_I` (`hw/common/assert/ocah_sva_macros.svh`) | reset-VALID, handshake hold and payload stability, burst legality, WLAST/RLAST position, strobe lanes, response ordering and ID matching, JTAG TDO timing, TAP-state encoding and transition legality | every `SIMULATION` compile, which the DV profiles set on every simulator, and every `FORMAL` elaboration of a licensed backend; Verilator evaluates them under `--assert` |
| Four-state | `OCAH_RULE` (`hw/common/assert/ocah_sva_macros.svh`) / `OCAH_COVER` (`hw/common/assert/ocah_assert.svh`) | X-hygiene (`*_KNOWN`) and the non-vacuity covers | commercial simulators and licensed formal backends: `OCAH_INC_ASSERT` is undefined under Verilator |

The Verilator target passes `--assert --no-assert-case`: `--assert` evaluates
the two-state set, `--no-assert-case` keeps the `unique`/`priority` case checks
of the DUT and vendored RTL out of it. A failing assertion prints an `%Error`
line and stops the simulation; the parser policy hard-fails the test on that
line. `dtp_tb_if.jtag_sva_en` / `axi_sva_en` are the runtime suppress knobs
(default on). The JTAG checker's reset input is TRST AND power-on reset, the
TAP controller's effective reset. A new rule with two-state-safe operands goes on
`OCAH_SVA_RULE`; one that needs `$isunknown` or X-propagation goes on
`OCAH_RULE`. The first argument of either is the checker parameter of the
side that drives the rule's signals, `ASSUME_MASTER_RULES` or
`ASSUME_SLAVE_RULES`, so a formal backend can assume that side; both default
to assertions here.

## Formal

`formal/` is the reference implementation of the property style in
`hw/common/dv/docs/formal-property-style.adoc`: one bound property module per
described block, in the boolean subset that the open-source frontend and the
licensed backends both elaborate, each with a `bmc`, `cover` and `prove` task
triple. Six blocks run on the `dtp` top (the TAP controller, the instruction
register, the reset hierarchy, the STAP and SIB gating, the debug-control
register), the bridge control on `jtag2axi`, and the clock stop, the
cross-trigger transport and the CSR contract on `cross_trigger_network`.
The shared AXI and JTAG checkers of the open path
(`hw/common/dv/vip/*/sva/ocah_*_fv.sv`) are bound on the
`cross_trigger_network` AXI-Lite port in the CSR item, on the request machine's side of the
`jtag2axi` bridge's CDC and on the primary TAP of `dtp`, each asserting the design's side and
assuming the environment's (`props/dtp_*_fv_bind.sv`).
`dtp_formal_cfg.toml` and `testlists/formal.toml` launch them through the
runner; the plan section is "Formal Verification Plan" in
`docs/DTP_VPLAN.adoc`, which names each target's rows, labels, item, depth and
path and records the observations the proofs settle. `testlists/formal.toml`
lists `dtp_tap_fpv` in the `smoke` group and every item in `fpv`.

```bash
python3 tools/dv/run_dv.py --dut dtp --mode formal              # the smoke group: flist, then the TAP triple
python3 tools/dv/run_dv.py --dut dtp --mode formal --items fpv  # every item
python3 tools/dv/run_dv.py --dut dtp --mode formal --dry-run    # the rendered command
```

That chapter also carries the filelist generation and the `sby` invocation by
hand. The items need `sby`, Yosys with a yosys-slang build that carries the
concurrent-assertion lowering, and `yices` on one `PATH`; a site whose tools
live in a container or that supplies a licensed backend selects them through
the site layer, as the Formal verification chapter of `tools/dv/doc/run-dv.adoc`
describes.

## Running

```bash
# Filelist + Verilator build only
python3 tools/dv/run_dv.py --dut dtp --build-only

# Smoke: TAP FSM sanity (dtp_sanity_test)
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test

# Smoke: IDCODE field verification
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag_idcode_test

# Basic JTAG: all Smoke and Basic JTAG VPLAN scenarios
python3 tools/dv/run_dv.py --dut dtp --items basic_jtag

# JTAG2AXI SMC fabric write / write-read
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag2axi_smc_axi_single_write_test
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag2axi_smc_axi_single_write_read_test

# Every JTAG2AXI test runs the shared ocah_axi_vip scoreboard (passive bus
# monitors + reference model) with per-test required evidence IDs and
# per-stream minimum compared-transaction counts, so a silent no-op run
# fails at finalization
python3 tools/dv/run_dv.py --dut dtp --items jtag2axi

# Every XTRIG/CTM test finalizes a named-evidence checker (CTM reference
# model route compare, CSR readback, quiet windows, stretch measurements)
python3 tools/dv/run_dv.py --dut dtp --items xtrig

# Checker negative validation: wrong arming must fail the run
DTP_AXI_SCOREBOARD_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag2axi_decode_error_decerr_read_test

# TAP checker negative validation: a desynced TAP reference model must fail
DTP_JTAG_TAP_CHECKER_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag_tlr_reset_test

# Every JTAG instruction test (BYPASS variants, IDCODE, SAMPLE/PRELOAD,
# EXTEST, INTEST, EXTEST_TRAIN/PULSE, CLAMP, HIGHZ, RUNBIST, CLAMP_HOLD/
# RELEASE, undefined-instruction fallback, TRST/POR/TLR) finalizes a named
# evidence checker per pass; most also run a passive pin-level scan monitor
# whose IR/DR reconstruction is cross-checked against the sequence's own
# scan intent. Corrupted family expectations must fail the run:
DTP_JTAG_FAMILY_CHECKER_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag_extest_test

# XTRIG checker negative validation: a corrupted CTM reference model must
# fail every route-comparing scenario
DTP_XTRIG_CHECKER_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_ctm_p2p_cla_to_ctp_test

# JTAG2AXI geometry gate negative validation: every JTAG2AXI scenario opens a
# pass by comparing the three *_JTAG2AXI_CAPS TDRs with the DV geometry table
# (CHK-J2A-GEOMETRY); a corrupted expected address size must fail the run
DTP_J2A_GEOMETRY_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag2axi_smc_otp_axi_single_write_read_test

# JTAG2AXI with-status series negative validation: the six
# *_series_write*_incr_with_error tests arm one SLVERR/DECERR beat and judge
# the WITH_ERROR_STATUS bit on every shift (CHK-J2A-STATUS-BIT); leaving the
# fault unarmed while the expectation stands must fail the fault beat's checks
DTP_J2A_STATUS_BIT_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test

# SV-UVM TAP checker negative validation (VCS): wrong armed IDCODE must fail
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items dtp_sanity_test \
  --plusarg +DTP_JTAG_TAP_CHECKER_NEGATIVE

# Smoke + functional group
python3 tools/dv/run_dv.py --dut dtp --items functional

# Debug-disable closure: the two per-gate matrices plus every directed
# gating test for the eleven dbg_disable_t fields
python3 tools/dv/run_dv.py --dut dtp --items dbg_disable
python3 tools/dv/run_dv.py --dut dtp --items dbg_disable --regress --reseed 3

# Commercial backends for coverage (same PyUVM tests)
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test --tool xcelium --cov
```

### SystemVerilog UVM framework (`--framework uvm`)

The SV-UVM flow shares this DV root, sim config, and testlist with the
cocotb flow: `dtp_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay
(same Bender RTL recipe and defines), and `--dut dtp --framework uvm` selects
it. A testlist scenario carries both implementations in its `module` binding
map (`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). Selecting a scenario with no `uvm` entry
errors; `--skip-unimplemented` runs a group's UVM-implemented subset instead.
The SV-UVM flow runs on VCS: a commercial simulator is required because
Verilator has no SV-UVM support (see `frameworks` in `simulators.toml`).
`--cov` instruments the VCS build with
`-cm line+cond+tgl+fsm+branch+assert` (covergroups collect into the same
databases), writes one `simv.vdb` per test, and merges/reports through the
standard `cov_merge`/`cov_report` stages (`urg`).

```bash
# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items dtp_sanity_test --seed 1

# SV-UVM build only / smoke group (UVM-implemented subset)
python3 tools/dv/run_dv.py --dut dtp --framework uvm --build-only
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items smoke --skip-unimplemented

# SV-UVM JTAG2AXI checker proofs (shared ocah_axi_vip passive env)
python3 tools/dv/run_dv.py --dut dtp --framework uvm --seed 1 \
  --items dtp_jtag2axi_smc_otp_axi_single_write_read_test
python3 tools/dv/run_dv.py --dut dtp --framework uvm --seed 1 \
  --items dtp_jtag2axi_smc_axi_single_write_read_test
```

Both frameworks share ONE testbench top module — `dtp_uvm_top` in `tb/tb_top.sv`, a
framework-neutral core whose interface instances both frameworks consume — with the bare
`+define+UVM` (set by the `[frameworks.uvm]` overlay) adding the SV-UVM harness block
(clock generator, `uvm_config_db` publication, `run_test()`). The class library
realizes the same component tree as the cocotb side with identical
basenames, on the shared framework bases of `hw/common/dv/vip/ocah_lib/`:
`uvm/env/dtp_env_pkg.sv` (DUT types and codecs, `dtp_test_cfg` and the
derived `dtp_env_cfg`, `dtp_virtual_sequencer`, one `dtp_<feature>_ref_model`
per scoreboard feature publishing expected items over TLM, the plain models
they hold, the always-on `dtp_scoreboard` that pairs expected with observed
and predicts nothing, the `dtp_tap_fsm_checker` and
`dtp_scan_window_monitor` subscribers, and `dtp_env`, which composes the
shared `ocah_jtag_vip` and `ocah_axi_vip` SV-UVM environments and agents),
`uvm/seq_lib/dtp_seq_lib_pkg.sv` (reusable operation sequences
`dtp_jtag_<op>_seq`, `dtp_jtag2axi_<op>_seq`, `dtp_axi_csr_<op>_seq` on the
VIP sequence APIs, and the scenario virtual sequences on
`dtp_base_test_seq`), and `uvm/tests/dtp_tests.sv` (thin tests on
`dtp_base_test`, `include`d by tb_top). The pin-level JTAG interface and
agent are the shared `hw/common/dv/vip/ocah_jtag_vip/` `interface/` and
`uvm/` collateral; DTP-local resets, observables, and the harness clock
period ride `tb/dtp_tb_if.sv`, the scan-network observables `tb/dtp_scan_if.sv`,
and the cross-trigger pins `tb/dtp_xtrig_if.sv`. The test cfg randomizes the system-clock and
TCK periods from `--seed` exactly as the cocotb env cfg does. The UVM
library comes from the simulator (`-ntb_opts uvm`). `dtp_sanity_test`
carries the full VPLAN 0.1 semantics: deterministic 32-edge TAP FSM closure
with an IEEE 1149.1 reference model, BYPASS 1-TCK TDI-to-TDO latency, and
clean scan-path returns, plus randomized TMS stress walks reproducible from
`--seed`.

The cocotb tests use deterministic random scenarios derived from `RANDOM_SEED`.
Every looped scenario runs at least 16 passes by default
(`dtp_base_test.MIN_DEFAULT_LOOPS`), each pass with its own scenario seed
(`RANDOM_SEED + loop_idx`); the two debug-disable matrix tests instead run a
16-row matrix per pass (seeded multi-hot rows). Loop and transaction counts
can be changed without touching test code:

```bash
# Apply to any looped test without a more specific override (e.g. a quick
# 1-pass bring-up run, or a deeper soak)
DTP_TEST_LOOPS=1 python3 tools/dv/run_dv.py --dut dtp --items smoke
DTP_TEST_LOOPS=64 python3 tools/dv/run_dv.py --dut dtp --items smoke

# Apply to the Basic JTAG group, with more random scan patterns per loop
DTP_BASIC_JTAG_TEST_LOOPS=32 DTP_RANDOM_COUNT=10 \
  python3 tools/dv/run_dv.py --dut dtp --items basic_jtag

# Group knobs: DTP_JTAG2AXI_TEST_LOOPS, DTP_SCAN_TEST_LOOPS,
# DTP_XTRIG_TEST_LOOPS, DTP_DEBUG_TDR_TEST_LOOPS
DTP_JTAG2AXI_TEST_LOOPS=32 python3 tools/dv/run_dv.py --dut dtp --items functional
```

The SV-UVM flow follows the same floor with the same knob names as plusargs:
every looped UVM test runs at least 16 scenario passes
(`dtp_base_test.MinDefaultLoops`), each pass seeded `+ntb_random_seed` + loop
index, resolved specific-first exactly like the cocotb environment knobs:

```bash
# Suite-wide, group, and per-test loop counts (plusarg twins of the env vars)
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items basic_jtag \
  --plusarg +DTP_TEST_LOOPS=1
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items basic_jtag \
  --plusarg +DTP_BASIC_JTAG_TEST_LOOPS=32 --plusarg +DTP_RANDOM_COUNT=10
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items dtp_jtag_extest_test \
  --plusarg +DTP_JTAG_EXTEST_TEST_LOOPS=4
```

`dtp_sanity_test` additionally runs 16 randomized TMS stress walks
(`+DTP_RAND_WALKS=<n>` overrides) and the JTAG2AXI single-op scenario runs 16
randomized write+readback passes (`+DTP_JTAG2AXI_RANDOM_OPS=<n>` overrides).

### Porting a scenario to the SV-UVM framework (`uvm =` dual mapping)

One VPLAN scenario, two implementations: the testlist entry's `module`
binding map carries both, and the same `--items` name selects either flow.
To port a cocotb scenario:

1. **Sequence** — add `uvm/seq_lib/<name>_seq.svh` mirroring the cocotb
   `seq_lib/<name>_seq.py` semantics as a virtual sequence on the family
   layer that matches the scenario: `dtp_jtag_base_test_seq` for
   instruction-family scenarios (per-pass family evidence + scan-builder
   cross-checks), `dtp_jtag2axi_base_test_seq` for bridge scenarios
   (single/series operations, responder backdoor, error arming),
   `dtp_debug_tdr_base_test_seq`, `dtp_scan_base_test_seq`, or
   `dtp_xtrig_base_test_seq`. The scenario starts the reusable operations
   (`dtp_jtag_<op>_seq`, `dtp_jtag2axi_<op>_seq`, `dtp_axi_csr_<op>_seq`)
   through the base wrappers and never a VIP driver or interface; a missing
   operation becomes a new `_seq` on the VIP sequence API first. Start
   `body()` with `seed_scenario_rng()` so every pass replays from `--seed`,
   and read knobs from `test_cfg`. Add the `` `include `` to
   `uvm/seq_lib/dtp_seq_lib_pkg.sv`.
2. **Test** — add `uvm/tests/<name>.svh` (file = class = scenario name)
   extending `dtp_base_test`: override `create_scenario_seq()` and the
   loop-count knob hooks (`specific_loops_knob`, `group_loops_knob`), declare
   the scoreboard features and the required `CHK-*` IDs the scenario owns in
   `configure_test_cfg()` (`cfg.require_feature`, `cfg.require_jtag_ids`,
   `cfg.require_axi_ids`), and plumb scenario evidence handles in
   `plumb_scenario_seq()` after `super`. Add the `` `include `` to
   `uvm/tests/dtp_tests.sv`.
3. **Testlist** — change the scenario's entry to
   `module = { cocotb = "<name>", uvm = "<name>" }`; the `uvm` value drives
   `+UVM_TESTNAME`.
4. **Qualify** — the group's VCS run must be green at the 16-iteration floor,
   and each checker's negative hook must FAIL when armed (below).

Checker-arming conventions: every ported test declares the evidence that
must land (required IDs), and each evidence path has a documented negative
hook proven to fail a run when the expectation is corrupted:

```bash
# SV-UVM TAP checker negative validation (VCS): wrong armed IDCODE must fail
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items dtp_sanity_test \
  --plusarg +DTP_JTAG_TAP_CHECKER_NEGATIVE

# Instruction-family checker negative validation: corrupted family
# expectations (decoded IR, loopback, bypass delay) must fail
python3 tools/dv/run_dv.py --dut dtp --framework uvm --items dtp_jtag_extest_test \
  --plusarg +DTP_JTAG_FAMILY_CHECKER_NEGATIVE

# AXI scoreboard negative validation: arming the wrong expected response for
# an injected error must fail
python3 tools/dv/run_dv.py --dut dtp --framework uvm \
  --items dtp_jtag2axi_smc_axi_error_single_write_test \
  --plusarg +DTP_AXI_SCOREBOARD_NEGATIVE

# Bridge reference-model negative validation: the jtag2axi_req reference
# model predicts corrupted addresses, so the scoreboard's pairing with the
# observed bus transactions must fail
python3 tools/dv/run_dv.py --dut dtp --framework uvm \
  --items dtp_jtag2axi_smc_axi_single_write_read_test \
  --plusarg +DTP_J2A_REF_MODEL_NEGATIVE

# JTAG2AXI geometry gate negative validation: a corrupted expected address
# size in the per-pass CAPS comparison (CHK-J2A-GEOMETRY) must fail
python3 tools/dv/run_dv.py --dut dtp --framework uvm \
  --items dtp_jtag2axi_smc_otp_axi_single_write_read_test \
  --plusarg +DTP_J2A_GEOMETRY_NEGATIVE

# JTAG2AXI with-status series negative validation: the fault beat left
# unarmed while its expectation stands (CHK-J2A-STATUS-BIT) must fail the
# fault beat's checks
python3 tools/dv/run_dv.py --dut dtp --framework uvm \
  --items dtp_jtag2axi_smc_otp_axi_series_write_incr_with_error_test \
  --plusarg +DTP_J2A_STATUS_BIT_NEGATIVE
```

PASS/FAIL is classified by the global parser registry in
`hw/common/dv/configs/parsers.toml`; the cocotb flow requires positive evidence from
`results.xml`, so a clean simulator exit alone is not enough.

### Overlaying a commercial VIP (`DTP_OVERLAY_TESTS`)

The SV-UVM testbench can host a commercial protocol VIP as a passive
overlay: an adopter-side build variation that adds vendor protocol monitors
to the stock tests without editing this tree. The seam is the
`DTP_OVERLAY_TESTS` compile hook at the end of `uvm/tests/dtp_tests.sv` —
define it to the quoted name of an include file on the overlay's own
include path and that file compiles into the test manifest. The OSS flists
never define it, so the open-source build is unaffected.

An overlay is three adopter-owned files, kept outside this repository
(vendor VIP collateral cannot be committed here):

1. **Wiring top** — a second elaboration top that taps the observed port's
   pins (e.g. `dtp_uvm_top.m_axi_*`, the SMC fabric AXI4 manager port) into
   the vendor interface with continuous assigns, as a pure observer, and
   publishes the virtual interface through `uvm_config_db`. Nothing in the
   overlay may drive DUT or responder signals.
2. **Overlay test** — the hook's include file: a class extending any stock
   test (e.g. `dtp_jtag2axi_smc_axi_single_write_test`) whose `build_phase`
   additionally creates the vendor env in passive mode, configured to the
   observed port geometry (SMC fabric: AXI4, 56-bit address, 64-bit data,
   2-bit ID). The stock scenario, evidence arming, and looped runner are
   inherited unchanged, so the in-repo `CHK-*` checkers and the vendor
   monitor run side by side on the same traffic. Select the overlay class
   per run with `--plusarg +UVM_TESTNAME=<overlay class>` on the stock
   `--items` name: the runner emits the testlist-mapped test name only when
   none is supplied, and a `+uvm_set_type_override` cannot swap the test
   itself because the simulator-shipped UVM library applies command-line
   factory overrides only after `run_test()` has created the test.
3. **Vendor package compile unit** — the vendor library analyzed into the
   same work library before `dtp_uvm_compile.f`, then both tops elaborated
   (`dtp_uvm_top` plus the wiring top).

A vendor library brings its own compile-unit requirements (packer-size
defines applied to every analysis step, macro-header ordering, an
installation-root variable); those live in the overlay's build recipe.

## Scope

The DTP public testbench covers the Smoke and Basic JTAG groups:
TAP FSM, IDCODE, BYPASS variants, undefined-instruction fallback, RUNBIST,
BSR-oriented instructions, TMP CLAMP_HOLD/RELEASE, TRST/POR/TLR reset behavior,
and AC EXTEST train/pulse smoke checks. JTAG2AXI, iJTAG/3DCR, and cross-trigger
scenarios are also implemented and enrolled in the native TOML catalog, with
their DUT-local model limitations documented above and in
[`docs/DTP_VPLAN.adoc`](docs/DTP_VPLAN.adoc). Their presence does not make the
topology-specific models shared VIPs.
