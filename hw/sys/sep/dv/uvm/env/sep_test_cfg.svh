// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP test configuration: the highest configuration level and the only
// object the seed touches. Randomizes the system clock period from the
// runner seed over the cocotb SepEnvCfg.randomize_timing range (4..20 ns),
// carries the fixed WDT and entropy sample clock periods, the bring-up and
// bounded-wait constants of the cocotb base test, the negative-validation
// switch, and the scoreboard features a test requires. The base test fills
// the knobs (read_knobs), seeds and randomizes it once, then derives
// sep_env_cfg from it. The cocotb twin is env/sep_env_cfg.py.

class sep_test_cfg extends ocah_test_cfg;
  `uvm_object_utils(sep_test_cfg)

  // --- randomized timing --------------------------------------------------
  rand int unsigned sys_clk_period_ns;
  constraint sys_c {sys_clk_period_ns inside {[4 : 20]};}
  int unsigned wdt_clk_period_ns     = 5000;
  int unsigned entropy_clk_period_ns = 3;

  // --- bring-up and bounded waits (cocotb sep_base_test parity) ------------
  // System-clock cycles the primary reset is held asserted, and the cycles
  // after its release before the first pass (release_no_cpu_reset).
  int unsigned reset_hold_cycles = 20;
  int unsigned post_reset_cycles = 2;
  // System-clock bound on the fuse-sense-done poll and the settle after it
  // (wait_fuse_sense max_cycles and its post-done ClockCycles).
  int unsigned fuse_sense_timeout_cycles = 20_000;
  int unsigned fuse_sense_settle_cycles = 20;
  // CPU-LSU master handshake watchdog, in system-clock cycles per wait: the
  // cocotb 50 us AXI timeout at the 5 ns nominal system clock.
  int unsigned axi_timeout_cycles = 10_000;

  // --- negative-validation switch (must FAIL the run when set) -----------
  bit csr_scoreboard_negative;  // +SEP_CSR_SCOREBOARD_NEGATIVE

  function new(string name = "sep_test_cfg");
    super.new(name);
  endfunction

  // Fill the knob-derived controls through the one knob accessor.
  function void read_knobs();
    csr_scoreboard_negative = ocah_knobs::is_set("SEP_CSR_SCOREBOARD_NEGATIVE");
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "%s sys_clk_period_ns=%0d wdt_clk_period_ns=%0d entropy_clk_period_ns=%0d csr_negative=%0d",
        super.convert2string(),
        sys_clk_period_ns,
        wdt_clk_period_ns,
        entropy_clk_period_ns,
        csr_scoreboard_negative
    );
  endfunction

endclass : sep_test_cfg
