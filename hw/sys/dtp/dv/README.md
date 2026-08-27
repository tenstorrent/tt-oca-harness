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
| AXI4-Lite CSR subordinate (`axil_xtrig`) | DUT-local `DtpFlatAxiLiteMaster` | Implemented for the flattened XTRIG fixture; migrate needed behavior into `ocah_axi_vip` rather than promoting a second AXI-Lite VIP. |
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

# JTAG2AXI checker-enabled tests (shared ocah_axi_vip scoreboard)
python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag2axi_decode_error_decerr_read_test \
          dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test \
          dtp_jtag2axi_smc_axi_error_single_write_test

# Checker negative validation: deliberately wrong arming must fail the run
DTP_AXI_SCOREBOARD_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag2axi_decode_error_decerr_read_test

# TAP checker negative validation: a desynced TAP reference model must fail
DTP_JTAG_TAP_CHECKER_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --items dtp_jtag_tlr_reset_test

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
is planned but not yet signed off. `--cov` is not yet wired for this
framework and is rejected up front.

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
Loop and transaction counts can be increased without changing test code:

```bash
# Apply to any looped test without a more specific override
DTP_TEST_LOOPS=8 python3 tools/dv/run_dv.py --dut dtp --items smoke

# Apply to the Basic JTAG group, with more random scan patterns per loop
DTP_BASIC_JTAG_TEST_LOOPS=8 DTP_RANDOM_COUNT=10 \
  python3 tools/dv/run_dv.py --dut dtp --items basic_jtag

# Apply to JTAG2AXI read/write tests
DTP_JTAG2AXI_TEST_LOOPS=16 python3 tools/dv/run_dv.py --dut dtp --items functional
```

PASS/FAIL is classified by the global parser registry in
`hw/common/dv/configs/parsers.toml`; the cocotb flow requires positive evidence from
`results.xml`, so a clean simulator exit alone is not enough.

## Scope

This DTP public bring-up now includes the 19-test Smoke and Basic JTAG group:
TAP FSM, IDCODE, BYPASS variants, undefined-instruction fallback, RUNBIST,
BSR-oriented instructions, TMP CLAMP_HOLD/RELEASE, TRST/POR/TLR reset behavior,
and AC EXTEST train/pulse smoke checks. JTAG2AXI, iJTAG/3DCR, and cross-trigger
scenarios are also implemented and enrolled in the native TOML catalog, with
their current DUT-local model limitations documented above and in
[`docs/DTP_VPLAN.adoc`](docs/DTP_VPLAN.adoc). Their presence does not make the
topology-specific models shared VIPs.
