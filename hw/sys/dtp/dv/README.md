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

The DTP TB imports the unified OCAH BFM packages from `dv/oss/hw/common/dv/vip`.
Those wrappers keep protocol details out of tests and use the project-local
protocol BFMs behind a stable API:

| Interface | VIP | Rationale |
|-----------|-----|-----------|
| JTAG TAP (IEEE 1149.1) | **`ocah_jtag_vip`** | `dtp`'s JTAG port is raw `{tck,tms,trst_n}`+`tdi`/`tdo` — pin-level. |
| AXI4 debug manager (`axi_smc_dbg`) | **`ocah_axi_vip`** (`OcahAxiRam`) | JTAG2AXI bridge drives it; memory model responds. |
| AXI4-Lite OTP managers (`smc_otp`, `sep_otp`) | **`ocah_axi_vip`** (`OcahAxiLiteMaster`/future responder) | Standard AXI-Lite. |
| AXI4-Lite CSR subordinate (`axil_xtrig`) | **`ocah_axi_vip`** (`OcahAxiLiteMaster`) | Cross-trigger CSR; wired, exercised in a later phase. |
| iJTAG (IEEE 1687 SIB networks) | OCAH-local model (later) | No suitable public VIP identified. |
| CTP (custom OCH wire-OR / P2P) | OCAH-local BFM (later) | Custom cross-trigger protocol. |
| CTM (custom OCH matrix) | OCAH-local model/BFM (later) | Custom cross-trigger routing. |

The cocotb runner adds both `dv/oss/hw/common/dv` and `dv/vip/cocotb` to
`PYTHONPATH` so tests can import the unified wrappers and their local backends.

## Running

```bash
# Filelist + Verilator build only
python3 dv/oss/tools/dv/run_dv.py --dut dtp --build-only

# Smoke: TAP FSM sanity (dtp_sanity_test)
python3 dv/oss/tools/dv/run_dv.py --dut dtp --items dtp_sanity_test

# Smoke: IDCODE field verification
python3 dv/oss/tools/dv/run_dv.py --dut dtp --items dtp_jtag_idcode_test

# Basic JTAG: all Smoke and Basic JTAG VPLAN scenarios
python3 dv/oss/tools/dv/run_dv.py --dut dtp --items basic_jtag

# JTAG2AXI SMC fabric write / read
python3 dv/oss/tools/dv/run_dv.py --dut dtp --items dtp_jtag2axi_smc_axi_wr_test
python3 dv/oss/tools/dv/run_dv.py --dut dtp --items dtp_jtag2axi_smc_axi_rd_test

# Smoke + functional group
python3 dv/oss/tools/dv/run_dv.py --dut dtp --items functional

# Commercial backends for coverage (same PyUVM tests)
python3 dv/oss/tools/dv/run_dv.py --dut dtp --items dtp_sanity_test --tool xcelium --cov
```

The cocotb tests use deterministic random scenarios derived from `RANDOM_SEED`.
Loop and transaction counts can be increased without changing test code:

```bash
# Apply to any looped test without a more specific override
DTP_TEST_LOOPS=8 python3 dv/oss/tools/dv/run_dv.py --dut dtp --items smoke

# Apply to the Basic JTAG group, with more random scan patterns per loop
DTP_BASIC_JTAG_TEST_LOOPS=8 DTP_RANDOM_COUNT=10 \
  python3 dv/oss/tools/dv/run_dv.py --dut dtp --items basic_jtag

# Apply to JTAG2AXI read/write tests
DTP_JTAG2AXI_TEST_LOOPS=16 python3 dv/oss/tools/dv/run_dv.py --dut dtp --items functional
```

PASS/FAIL is classified by the global parser registry in
`dv/oss/hw/common/dv/configs/parsers.toml`; the cocotb flow requires positive evidence from
`results.xml`, so a clean simulator exit alone is not enough.

## Scope

This DTP public bring-up now includes the 19-test Smoke and Basic JTAG group:
TAP FSM, IDCODE, BYPASS variants, undefined-instruction fallback, RUNBIST,
BSR-oriented instructions, TMP CLAMP_HOLD/RELEASE, TRST/POR/TLR reset behavior,
and AC EXTEST train/pulse smoke checks. The remaining JTAG2AXI, iJTAG, 3DCR, and
cross-trigger scenarios from the working reference (`dv/dtp/doc/DTP_VPLAN.md`,
72 logical tests) are tracked as a 147-test scenario-expanded roadmap in
[`docs/DTP_VPLAN.md`](docs/DTP_VPLAN.md); each maps to a UVM sequence in
`seq_lib/`.
