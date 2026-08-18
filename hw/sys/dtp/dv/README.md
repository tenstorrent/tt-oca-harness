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
       ├─ DtpAxiAgent    ocah_axi_vip OcahAxiRam responder + backdoor
       └─ DtpScoreboard  IDCODE / JTAG2AXI data-integrity checks
  seq_lib/ dtp_base_test_seq → dtp_sanity_test_seq, dtp_jtag_idcode_test_seq,
           dtp_jtag2axi_smc_axi_wr_test_seq, dtp_jtag2axi_smc_axi_rd_test_seq
```

Tests inherit `dtp_base_test` (env build + clock/reset + `start_seq` helper);
sequences inherit `dtp_base_test_seq` (common TAP building blocks). Each test has
its own sequence file: `tests/<name>.py` runs `seq_lib/<name>_seq.py`.

- `docs/` — public verification plan, TB architecture, register/coverage notes.
- `tb/` — SystemVerilog testbench top (`dtp_uvm_top`) plus Verilator stubs.
- `env/` — UVM env: config, JTAG agent, AXI memory agent, scoreboard, TDR encoders.
- `seq_lib/` — reusable UVM sequences (the VPLAN scenarios).
- `tests/` — `uvm_test` classes (one `@pyuvm.test()` per file, VPLAN-named).
- `testlists/` — native TOML testlists.
- `dtp_sim_cfg.toml` — `tt-oca`-local simulation defaults, modes, bender targets, tool knobs.
- `dtp_sim.core` — optional FuseSoC/CAPI-2 view (not parsed by the native flow).

## BFM Policy

The DTP TB imports the unified OCAH BFM packages from `hw/common/dv/vip`.
Those wrappers keep protocol details out of tests and use the project-local
protocol BFMs behind a stable API:

| Interface | VIP | Rationale |
|-----------|-----|-----------|
| JTAG TAP (IEEE 1149.1) | **`ocah_jtag_vip`** | `dtp`'s JTAG port is raw `{tck,tms,trst_n}`+`tdi`/`tdo` — pin-level. |
| AXI4 debug manager (`axi_smc_dbg`) | **`ocah_axi_vip`** (`OcahAxiRam`) | JTAG2AXI bridge drives it; memory model responds. |
| AXI4-Lite OTP managers (`smc_otp`, `sep_otp`) | **`ocah_axi_vip`** (`OcahAxiLiteMaster`/future responder) | Standard AXI-Lite. |
| AXI4-Lite CSR subordinate (`axil_xtrig`) | DUT-local `DtpFlatAxiLiteMaster` | Implemented for the flattened XTRIG fixture; migrate needed behavior into `ocah_axi_vip` rather than promoting a second AXI-Lite VIP. |
| Boundary scan / BSR loopback | DUT-local `DtpScanModel` | Implemented for this TB's compact identity loopback; not a generic boundary-cell model. |
| iJTAG (IEEE 1687 SIB networks) | DUT-local `DtpIjtagSibModel` | Implemented for DTP's three SIBs, lifecycle gates, and looped instruments; topology-specific. |
| STAP / 3DCR | DUT-local `DtpStap3dcrModel` | Partial DTP hierarchy model; downstream STAPs remain wire loopbacks. |
| CTP / CTM | DUT-local `DtpXtrigBfm` / `DtpCtmRefModel` | Implemented for DTP signal counts, CSR layout, and OCH routing policy; promote only after parameterization and independent reuse. |

The cocotb runner adds both `hw/common/dv` and `dv/vip/cocotb` to
`PYTHONPATH` so tests can import the unified wrappers and their local backends.
The ownership and promotion checklist is in `hw/common/dv/README.md`.

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
python3 tools/dv/run_dv.py --dut dtp_uvm --items dtp_sanity_test \
  --plusarg +DTP_JTAG_TAP_CHECKER_NEGATIVE

# Smoke + functional group
python3 tools/dv/run_dv.py --dut dtp --items functional

# Commercial backends for coverage (same PyUVM tests)
python3 tools/dv/run_dv.py --dut dtp --items dtp_sanity_test --tool xcelium --cov
```

### SystemVerilog UVM flow (`--dut dtp_uvm`)

A separate SV-UVM smoke flow shares this DV root (same Bender RTL recipe and
defines) via the `dtp_uvm` alias and the `native-uvm` profile. Logical item
names match the VPLAN scenarios, so the same `--items` name selects the same
scenario in either flow; the UVM class name lives in the testlist `module`
field (`+UVM_TESTNAME`). VCS only for now (maintainer flow, commercial
license); Xcelium support is planned but not yet signed off. `--cov` is not
yet wired for this flow and is rejected up front.

```bash
# PyUVM (cocotb) and SV-UVM, same logical scenario name
python3 tools/dv/run_dv.py --dut dtp     --items dtp_sanity_test --tool verilator
python3 tools/dv/run_dv.py --dut dtp_uvm --items dtp_sanity_test --tool vcs --seed 1

# SV-UVM build only / smoke group
python3 tools/dv/run_dv.py --dut dtp_uvm --build-only
python3 tools/dv/run_dv.py --dut dtp_uvm --items smoke --tool vcs

# SV-UVM JTAG2AXI checker proofs (shared ocah_axi_vip passive env)
python3 tools/dv/run_dv.py --dut dtp_uvm --tool vcs --seed 1 \
  --items dtp_jtag2axi_smc_otp_axi_single_write_read_test
python3 tools/dv/run_dv.py --dut dtp_uvm --tool vcs --seed 1 \
  --items dtp_jtag2axi_smc_axi_single_write_read_test
```

Both flows share ONE testbench top module — `dtp_uvm_top` in `tb/tb_top.sv` —
with `+define+DTP_UVM_TB` (set by the `dtp_uvm` config) switching it from the
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
