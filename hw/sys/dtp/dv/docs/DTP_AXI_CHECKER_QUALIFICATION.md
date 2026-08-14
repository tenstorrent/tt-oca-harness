<!-- SPDX-License-Identifier: Apache-2.0 -->
# DTP AXI Checker Qualification Record (issue tt-oca-hw#3295)

Qualification record per `hw/common/dv/docs/vip-checker-model.adoc`
§"Qualification Record" for the shared `ocah_axi_vip` checker /
reference-model / scoreboard stack adopted by the DTP jtag2axi tests. Raw run
directories stay untracked (`build/runs/`); this record retains the named
evidence and the exact reproduction commands.

## Source

- Branch `ahsiao_2026-08-13_vip`, base commit
  `9d2656b535c32d85e54c6e2c2eeb0d5b0c29dbb4`, captured 2026-08-14.

## Environment

- Runner: `tools/dv/run_dv.py`, run-level `result.json` schema v1
- Framework: cocotb 2.0.1 + pyuvm 4.0.1, Python 3.11.15
- Simulator: Verilator 5.050 (native-cocotb profile)

## Invocations

```bash
# Simulator-free checker/model/scoreboard proof (positive + negatives A-R)
PYTHONPATH="$PWD/hw/common/dv/vip" .venv/bin/python \
  hw/common/dv/vip/ocah_axi_vip/cocotb/examples/example_axi_scoreboard_selftest.py

# Checker-enabled DUT proofs (Verilator)
python3 tools/dv/run_dv.py --dut dtp --tool verilator --ui plain \
  --items dtp_jtag2axi_decode_error_decerr_read_test \
          dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test \
          dtp_jtag2axi_smc_axi_error_single_write_test

# Negative validation: deliberately wrong arming MUST fail the run
DTP_AXI_SCOREBOARD_NEGATIVE=1 python3 tools/dv/run_dv.py --dut dtp \
  --tool verilator --seed 1 --ui plain \
  --items dtp_jtag2axi_decode_error_decerr_read_test

# No-regression sweep
python3 tools/dv/run_dv.py --dut dtp --tool verilator --ui plain --items jtag2axi
```

## Positive evidence (run `20260814_025117__verilator__multi`)

`dtp_jtag2axi_decode_error_decerr_read_test` — expected DECERR on all three
targets, per-beat response positions pinned by the model, model-checked
readback, poll-bound completion:

```
CHK-AXI-RESP-EXPECTED PASS expected=0x3 observed=0x3 context=stream=smc_axi axi4 read addr=0xbc08 beats=1 target=smc_axi injected=0xbc08
CHK-AXI-NONVAC PASS expected=true observed=true context=scenario=decerr_read targets=3 resp=DECERR credits_unconsumed=0
CHK-AXI-DRAIN PASS expected={'pending': 0, 'orphans': 0} observed={'pending': 0, 'orphans': 0} context=stream=smc_axi monitor=dtp_smc_axi_monitor in_flight={'write': 0, 'read': 0}
CHECKER_SUMMARY name=dtp-axi-scoreboard checks=29 passed=29 failed=0 missing=0
```

`dtp_jtag2axi_smc_axi_error_single_write_test` — SLVERR and DECERR
injections expected, stimulus-intent strobes, intent-based memory audit,
completion bound (16 loops):

```
CHK-AXI-RESP-EXPECTED PASS expected=0x2 observed=0x2 context=stream=smc_axi axi4 write addr=0x1820 beats=1 target=smc_axi injected=0x1820
CHK-AXI-STRB PASS expected=(255,) observed=(255,) context=stream=smc_axi axi4 write addr=0x1820 beats=1 single_op target=smc_axi source=stimulus-wstrb
CHK-AXI-WMEM PASS expected=0x3748704275ede573 observed=0x3748704275ede573 context=single_write_error#1.recover_write addr=0x1c20 len=8 source=intent
CHK-AXI-NONVAC PASS expected=true observed=true context=scenario=error_single_write target=smc_axi injections=2 resp_set=SLVERR+DECERR credits_unconsumed=0
CHK-AXI-STREAM-MIN PASS expected=true observed=true context=stream=smc_axi transactions=64 min=4
CHECKER_SUMMARY name=dtp-axi-scoreboard checks=280 passed=280 failed=0 missing=0
```

`dtp_jtag2axi_smc_axi_read_security_gating_no_axi_activity_test` — blocked
window held across lifecycle re-enable plus an exact activity delta (only the
sanctioned restore read may appear across the whole span):

```
CHK-AXI-NOACT PASS expected={'aw': 0, 'w': 0, 'ar': 1} observed={'aw': 0, 'w': 0, 'ar': 1} context=read_gate.ap_debug target=smc_axi source=tb_pulse_counters window=gated_attempt+8cyc
CHK-AXI-NOACT PASS expected={'aw': 0, 'w': 0, 'ar': 2} observed={'aw': 0, 'w': 0, 'ar': 2} context=read_gate.ap_debug target=smc_axi source=tb_pulse_counters window=exact_delta sanctioned=restore_read(ar+1)
CHECKER_SUMMARY name=dtp-axi-scoreboard checks=20 passed=20 failed=0 missing=0
```

Run-level authority for all three: `result.json status=PASS tests=3`,
per-test `results.xml` passing, `TESTS=1 PASS=1 FAIL=0 SKIP=0` in each log.

## Negative evidence

- Wrong-arming DUT run (`DTP_AXI_SCOREBOARD_NEGATIVE=1`):
  `CHK-AXI-RESP FAIL` on all three targets → `result.json status=FAIL`.
- The simulator-free self-test (cases A-R) rejects, at finalization: a
  wrong model expectation, an un-armed DECERR, a stale armed credit, zero
  checks, blocked-region transactions (whole-region, mid-burst, and
  sub-word — while a narrow transfer not touching the blocked byte passes),
  per-beat error responses in the wrong position, wrong write strobes, a
  credit conflicting with the model expectation, a timeout that no test
  armed, a transaction observed after finalization, in-flight/orphan/
  callback-error drain violations, a duplicate commit_order displacing a
  buffered transaction, temporal-policy bypass via commit-order buffering
  (blocked-window membership and credit arming are judged at arrival), and
  corrupted expected-EXOKAY read data. Shadow-memory commits replay in the
  responder's data order (`commit_order`) under cross-ID B reordering.

## No-regression

Full jtag2axi group sweep after adoption: 78/78 PASS
(`--items jtag2axi`, run-level `result.json status=PASS`).

## Artifact

Evidence attached to the tracking issue:
<https://github.com/tenstorrent/tt-oca-hw/issues/3295#issuecomment-5283503989>

## SV-UVM flow (VCS)

```bash
python3 tools/dv/run_dv.py --dut dtp_uvm --build-only --tool vcs
python3 tools/dv/run_dv.py --dut dtp_uvm --items dtp_sanity_test --tool vcs --seed 1
python3 tools/dv/run_dv.py --dut dtp_uvm --tool vcs --seed 1 \
  --items dtp_jtag2axi_smc_otp_axi_single_write_read_test
```
