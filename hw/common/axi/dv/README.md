<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

AXI4-Lite to AHB-Lite Converter DV
==================================

IP-level cocotb bench for `hw/common/axi/axi_lite_to_ahb.sv`, running on the
unified DV flow (`tools/dv/run_dv.py`, DUT name `axi_lite_to_ahb`). The DV root
sits outside the `hw/ip/<name>/dv` convention, so the DUT is registered in
`hw/common/dv/configs/duts.toml`.

Layout
------

* `axi_lite_to_ahb_sim_cfg.toml` — flow configuration (build recipe, cocotb
  framework view, run modes).
* `tb/tb_top.sv` — pin-level testbench top (`axi_lite_to_ahb_tb_top`). It
  elaborates the converter three times so one build covers the parameter
  sets:

  | Instance  | Pins      | AHB_DATA_WIDTH | AllowSubWordWrite | AckZeroStrobeWrite |
  |-----------|-----------|----------------|-------------------|--------------------|
  | `u_dut_a` | `a_*`     | 64             | 0                 | 1                  |
  | `u_dut_b` | `b_*`     | 32             | 1                 | 0                  |
  | `u_dut_c` | `c_*`     | 64             | 1                 | 0                  |

  Cfg A is the SEP Adams Bridge control path (`sep_crypto_abr_wrapper.sv`);
  cfg C puts sub-word writes on either half of a 64-bit bus.
  Each instance exposes its AXI4-Lite slave port as `<x>_axil_*` (the names
  cocotbext-axi resolves from a prefix) and its AHB-Lite master port as
  `<x>_ahb_*`.
* `cocotb/models/` — bench components:
  * `ahb_lite_slave.py` — memory-backed AHB-Lite slave: honours HSIZE and the
    HADDR byte lanes on writes, returns the bus-wide beat on reads (unused
    lanes filled with random data, the neighbouring memory, or zeros), random
    or planned wait states in the address and data phases, the two-cycle ERROR
    response, and a record of every transfer and of every AHB-Lite master rule
    it sees broken.
  * `axil_agents.py` — `AxilPort`, an AXI4-Lite master built from the
    cocotbext-axi channel endpoints (any WSTRB, back-to-back queueing, VALID
    and READY throttling per channel); `AxilRawPort` for direct pin access;
    `AxilMonitor`, the passive AXI-side checker.
  * `a2h_scoreboard.py` — the converter's expected behaviour, written from
    its specification, and the reference-memory scoreboard.
* `cocotb/tests/` — one module per scenario; `a2h_base_test.py` carries the
  shared bench (`Bench`, `ConverterEnv`, random traffic).
* `testlists/all.toml` — testlist and groups (`smoke`, `all`, `sva_live`).

The RTL closure is `axi_lite_to_ahb.sv` alone, from the `axi_lite_to_ahb`
Bender target; the pulp `axi` dependency provides `axi_pkg` and
`axi/typedef.svh` for the tb_top structs.

Always-on checks
----------------

Every test runs these on every instance, and `Bench.finish()` fails the test
on any breach:

* AHB slave model: HTRANS never BUSY or SEQ, address and control held while
  HREADY is low, HWDATA held through a write data phase, aligned transfers no
  wider than the bus, no address phase overlapping a data phase.
* AXI monitor: R and B stay valid and unchanged until taken, AW and W are
  accepted together, one request in flight, and HTRANS IDLE while a response
  is pending.
* Scoreboard: each request pairs with at most one AHB transfer, whose HADDR,
  HSIZE, HPROT, HBURST and HMASTLOCK match the specification, and whose HRESP
  sets the response; read data comes from the reference memory, and at the end
  the slave memory equals the reference byte for byte.
* RTL SVA: the sim config defines `OCAH_OT_INC_ASSERT` and passes `--assert`
  for Verilator, which `prim_assert.sv` otherwise leaves compiled out; VCS and
  Xcelium compile them by default. A failed assertion prints `%Error` and
  fails the leaf.

Running
-------

```bash
# Smoke group (default items)
python3 tools/dv/run_dv.py --dut axi_lite_to_ahb

# Everything
python3 tools/dv/run_dv.py --dut axi_lite_to_ahb --items all --sim-jobs 8

# The SVA negative control
python3 tools/dv/run_dv.py --dut axi_lite_to_ahb --items sva_live

# One test with waves
python3 tools/dv/run_dv.py --dut axi_lite_to_ahb --items a2h_pipelined_read_test --waves
```

`--stage sim` alone reuses whatever model is on disk, so keep `hdl_compile` in
the stage list after an RTL change (the default plan includes it). Verilator
is the default tool; VCS and Xcelium are available where licensed
(`--tool vcs`). Per-test logs and `results.xml` land under
`build/runs/<run>/<test>/`.

Tests
-----

* `a2h_smoke_test` — word write and readback through the stock cocotbext-axi
  `AxiLiteMaster`, on both AHB halves of the 64-bit sets: one NONSEQ word
  transfer per access, HWDATA replicated on both halves, read data from the
  half HADDR[2] selects.
* `a2h_strobe_matrix_test` — all 16 WSTRB values on every parameter set at
  HADDR[2] = 0 and 1: the response, whether an AHB transfer is issued, its
  HSIZE and HADDR[1:0], and the memory word afterwards.
* `a2h_wait_states_test` — HREADY low in the address phase and fixed or
  random data-phase wait states.
* `a2h_error_response_test` — two-cycle ERROR on reads and writes, after zero
  or more wait states: SLVERR, memory untouched, the next transfer clean.
* `a2h_backpressure_test` — RREADY and BREADY held low: the response holds,
  AHB stays IDLE and a queued request waits; then random READY throttling.
* `a2h_arbitration_test` — reads and writes both waiting alternate strictly;
  AW without W (and W without AW) is not accepted while reads keep flowing;
  alternation under random VALID gaps.
* `a2h_pipelined_read_test` — 1, 2, 3, 4 and 8 queued reads of offset 0xC
  and a mixed-offset burst, each returning its own word and each issued as a
  NONSEQ read with the full HADDR.
* `a2h_hprot_signals_test` — HPROT for every AxPROT value; HBURST, HMASTLOCK
  and HTRANS held to their single-transfer values.
* `a2h_reset_test` — reset in each phase of a transaction returns the FSM to
  IDLE with HTRANS IDLE, and traffic resumes cleanly.
* `a2h_random_stress_test` — 1500 random requests per instance with random
  waits, errors, strobes, AxPROT and throttling, against the scoreboard; the
  testlist reseeds it three times.
* `a2h_sva_live_test` (group `sva_live`, not in `all`) — negative control. It
  deposits a new address into the converter's request register inside a
  stalled address phase so `AddrPhaseHeld_A` fires. The testlist marks it
  `expect_fail`, so it grades PASS only when the assertion fired, and FAIL in
  a build with the SVA compiled out.

Scope
-----

This suite covers the converter on its own. The path it serves in SEP — the
AxCACHE override, the 64-to-32-bit `axi_dw_converter` and `axi_to_axi_lite`
ahead of it, and the Adams Bridge AHB slave behind it — is covered by the SEP
bench (`hw/sys/sep/dv`).
