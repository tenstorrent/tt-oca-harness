# DTP OCAH Open-Source TB

OCAH open-source **PyUVM** DV testbench for **DTP (Debug & Test Ports)** in the
`tt-oca` repository. DTP is the
subsystem that hosts the primary JTAG TAP (IEEE 1149.1), the JTAG2AXI debug
bridges, the iJTAG networks (IEEE 1687), and the cross-trigger network (CTP/CTM).
It follows the canonical `hw/sys/<system>/dv/` layout and runs on Verilator.

The TB wraps unified OCAH BFMs in a UVM hierarchy:

```
dtp_<scenario>_test (uvm_test, @pyuvm.test)
  └─ DtpEnv
       ├─ DtpJtagAgent   sequencer + driver (wraps ocah_jtag_vip) + analysis port
       ├─ DtpAxiAgent    ocah_axi_vip OcahAxiSlaveAgent responder + backdoor
       └─ DtpScoreboard  IDCODE / JTAG2AXI data-integrity checks
  seq_lib/ dtp_base_test_seq → dtp_sanity_test_seq, dtp_jtag_idcode_test_seq,
           dtp_jtag2axi_smc_axi_wr_test_seq, dtp_jtag2axi_smc_axi_rd_test_seq
```

Tests inherit `dtp_base_test` (env build + clock/reset + `start_seq` helper);
sequences inherit `dtp_base_test_seq` (common TAP building blocks). Each test has
its own sequence file: `tests/<name>.py` runs `seq_lib/<name>_seq.py`.

- `docs/` — public verification plan, TB architecture, register/coverage notes.
- `tb/` — SystemVerilog testbench top (`dtp_uvm_top`, shared by the cocotb and SV-UVM flows) and `dtp_tb_if`.
- `env/` — UVM env: config, JTAG agent, AXI memory agent, scoreboard, TDR encoders.
- `seq_lib/` — reusable UVM sequences (the VPLAN scenarios).
- `tests/` — `uvm_test` classes (one `@pyuvm.test()` per file, VPLAN-named).
- `testlists/` — native TOML testlists.
- `dtp_sim_cfg.toml` — `tt-oca`-local simulation defaults, modes, bender targets, tool knobs.

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
| iJTAG (IEEE 1687 SIB networks) | DUT-local `DtpIjtagSibModel` | Implemented for DTP's three SIBs, lifecycle gates, and looped instruments; topology-specific. |
| STAP / 3DCR | DUT-local `DtpStap3dcrModel` | Partial DTP hierarchy model; downstream STAPs remain wire loopbacks. |
| CTP / CTM | DUT-local `DtpXtrigBfm` / `DtpCtmRefModel` | Implemented for DTP signal counts, CSR layout, and OCH routing policy; promote only after parameterization and independent reuse. |

The cocotb runner adds `hw/common/dv/vip` to `PYTHONPATH` so tests can import
the unified wrappers and their local backends.
The ownership and promotion checklist is in `hw/common/dv/README.md`.

## Simulation defines

DTP DV, lint, and synthesis compiles pass preprocessor defines that switch the
shared testbench shape, gate assertions, and select a simulation vs synthesis
view. The inventory — each define, why it exists, and what a DTP build does with
or without it — is in [`../doc/defines.adoc`](../doc/defines.adoc). Runtime
environment variables and plusargs in the commands below are not preprocessor
defines.

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

# JTAG2AXI SMC fabric write / read
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag2axi_smc_axi_wr_test
python3 tools/dv/run_dv.py --dut dtp --items dtp_jtag2axi_smc_axi_rd_test

# Every JTAG2AXI test runs the shared ocah_axi_vip scoreboard (passive bus
# monitors + reference model) with per-test required evidence IDs and
# per-stream minimum compared-transaction counts, so a silent no-op run
# fails at finalization
python3 tools/dv/run_dv.py --dut dtp --items jtag2axi

# Every XTRIG/CTM test finalizes a named-evidence checker (CTM reference
# model route compare, CSR readback, quiet windows, stretch measurements)
python3 tools/dv/run_dv.py --dut dtp --items xtrig

# Checker negative validation: deliberately wrong arming must fail the run
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

The SV-UVM smoke flow shares this DV root, sim config, and testlist with the
cocotb flow: `dtp_sim_cfg.toml` declares it as the `[frameworks.uvm]` overlay
(same Bender RTL recipe and defines), and `--dut dtp --framework uvm` selects
it. A testlist scenario carries both implementations in its `module` binding
map (`module = { cocotb = "...", uvm = "..." }`), so the same `--items` name
selects the same VPLAN scenario in either framework; the UVM class name is
the `uvm` entry (`+UVM_TESTNAME`). Selecting a scenario with no `uvm` entry
errors; `--skip-unimplemented` runs a group's UVM-implemented subset instead.
VCS only for now — a commercial simulator is required because Verilator has
no SV-UVM support (see `frameworks` in `simulators.toml`); Xcelium support
is planned but not yet signed off. `--cov` instruments the VCS build with
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

Both frameworks share ONE testbench top module — `dtp_uvm_top` in `tb/tb_top.sv` —
with the bare `+define+UVM` (set by the `[frameworks.uvm]` overlay) switching it from the
cocotb ported shape to the self-contained SV-UVM shape. The class library
mirrors the cocotb layout: `uvm/env/dtp_env_pkg.sv` (reusable environment:
shared `ocah_jtag_vip` SV-UVM agent + `dtp_tap_fsm_checker` subscriber),
`uvm/seq_lib/dtp_seq_lib_pkg.sv` (JTAG base sequence + scenarios, issuing
`ocah_jtag_item`s on the agent sequencer), and `uvm/tests/dtp_tests.sv`
(non-reusable tests, `include`d by tb_top). The pin-level JTAG interface and
agent are the shared `hw/common/dv/vip/ocah_jtag_vip/` `interface/` and
`uvm/` collateral; DTP-local resets/observables ride `tb/dtp_tb_if.sv`. The UVM library comes from the
simulator (`-ntb_opts uvm`). `dtp_sanity_test` carries the full VPLAN 0.1
semantics: deterministic 32-edge TAP FSM closure with an IEEE 1149.1
reference model, BYPASS 1-TCK TDI-to-TDO latency, and clean scan-path
returns, plus randomized TMS stress walks reproducible from `--seed`.

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
   `seq_lib/<name>_seq.py` semantics on the shared VIP stimulus API. Extend
   `dtp_jtag_cmd_lib_seq` for instruction-family scenarios (per-pass family
   evidence + scan-builder cross-checks) or `dtp_jtag2axi_base_test_seq` for
   bridge scenarios (single/series ops, responder backdoor, error arming).
   Start `body()` with `seed_scenario_rng()` so every pass replays from
   `--seed`. Add the `` `include `` to `uvm/seq_lib/dtp_seq_lib_pkg.sv`.
2. **Test** — add `uvm/tests/<name>.svh` (file = class = scenario name)
   extending `dtp_base_test`: override `create_scenario_seq()` and the
   loop-count plusarg name hooks, arm the checker evidence the scenario
   owns (required `CHK-*` IDs; `jtag_require_checks` /
   `cfg.require_checks`), and plumb scenario handles in
   `plumb_scenario_seq()`. Add the `` `include `` to `uvm/tests/dtp_tests.sv`.
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
never define it, so the open-source build is unchanged.

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

Synopsys VIP (svt) integration notes for the AMBA AXI suite: every analysis
step, including the UVM library pre-analysis, must carry the same
`+define+UVM_PACKER_MAX_BYTES` value the suite expects, or the suite exits
fatally at time zero; the suite package's compile unit must see
`uvm_macros.svh` before the suite package (include the macros header, not
`uvm_pkg.sv`, which resolves to a simulator wrapper) so the suite's
methodology detection engages; `DESIGNWARE_HOME` points at the VIP
installation root, with the suite's include and source directories on the
include path. A healthy overlaid run shows the vendor license checkout and
the vendor monitor's transaction tracking alongside the unchanged `CHK-*`
evidence and the `UVM TEST PASSED` banner.

## Scope

This DTP public bring-up now includes the 19-test Smoke and Basic JTAG group:
TAP FSM, IDCODE, BYPASS variants, undefined-instruction fallback, RUNBIST,
BSR-oriented instructions, TMP CLAMP_HOLD/RELEASE, TRST/POR/TLR reset behavior,
and AC EXTEST train/pulse smoke checks. JTAG2AXI, iJTAG/3DCR, and cross-trigger
scenarios are also implemented and enrolled in the native TOML catalog, with
their current DUT-local model limitations documented above and in
[`docs/DTP_VPLAN.adoc`](docs/DTP_VPLAN.adoc). Their presence does not make the
topology-specific models shared VIPs.
