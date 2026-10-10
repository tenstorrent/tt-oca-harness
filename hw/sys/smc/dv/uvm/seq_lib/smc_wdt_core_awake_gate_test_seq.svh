// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Measures watchdog core-reset gating and always-count priority through SEP_IN.

class smc_wdt_core_awake_gate_test_seq extends smc_wdt_base_test_seq;
  `uvm_object_utils(smc_wdt_core_awake_gate_test_seq)

  localparam string ChkConfig = "CHK-WDT-AWAKE-CONFIG";
  localparam string ChkReset = "CHK-WDT-AWAKE-CORE-RESET";
  localparam string ChkRate = "CHK-WDT-AWAKE-RATE";
  localparam string ChkHeld = "CHK-WDT-AWAKE-HELD";
  localparam string ChkAlways = "CHK-WDT-AWAKE-ALWAYS";
  localparam string ChkWindow = "CHK-WDT-AWAKE-WINDOW";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned RateWindowCycles = 1024;
  localparam int unsigned HoldCycles = 8192;
  localparam int unsigned BoundaryPollCycles = 64;
  // Nine keyed writes, six CTRL reads, eight COUNT reads and one CMP read.
  localparam int unsigned WdtAccessesPerPass = 33;
  localparam string ChkScoreboard = "CHK-WDT-AWAKE-SCOREBOARD";
  localparam int unsigned ResetApplyPolls = 64;
  localparam int unsigned ResetIntervalsPerPass = 2;
  localparam bit [31:0] CountStart = 32'h0100_0000;
  // Maximum scale and compare keep the seeded count below the interrupt threshold.
  localparam bit [31:0] AwakeConfig = WDT_CTRL_WDOGCOREAWAKE_MASK | WDT_CTRL_WDOGSCALE_MASK;
  localparam bit [31:0] AlwaysMask = WDT_CTRL_WDOGENALWAYS_MASK;
  localparam bit [31:0] CompareValue = WDT_CMP_WDOGCMP0_MASK;
  localparam bit [63:0] AppliedMask = CPU_CTRL_RESET_TIMEOUT_RESET_APPLIED_MASK;
  localparam bit [63:0] ResetCtrlAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR;
  localparam bit [63:0] ResetTimeoutAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR;

  int unsigned compare_before, mismatch_before;
  bit [63:0] reset_baseline;
  bit [63:0] core_reset_mask;

  function new(string name = "smc_wdt_core_awake_gate_test_seq");
    super.new(name);
  endfunction

  protected function bit [63:0] reset_mask(int unsigned selected_core);
    case (selected_core)
      0: return CPU_CTRL_RESET_CTRL_CORE0_RESET_N_N0_SCAN_MASK;
      1: return CPU_CTRL_RESET_CTRL_CORE1_RESET_N_N0_SCAN_MASK;
      2: return CPU_CTRL_RESET_CTRL_CORE2_RESET_N_N0_SCAN_MASK;
      3: return CPU_CTRL_RESET_CTRL_CORE3_RESET_N_N0_SCAN_MASK;
      default: begin
        `uvm_fatal(get_type_name(), "Watchdog core has no generated reset-control mask")
        return '0;
      end
    endcase
  endfunction

  protected task check_ctrl(bit [31:0] expected, bit negative = 1'b0);
    bit [31:0] observed;
    csr_read(smc_wdt_addr(core, WDT_CTRL), observed, "WDT.CTRL");
    check_evidence(ChkConfig, "watchdog configuration", observed,
                   negative ? expected ^ WDT_CTRL_WDOGCOREAWAKE_MASK : expected);
    if (observed != expected) begin
      `uvm_fatal(get_type_name(), "Watchdog configuration does not match the measurement stimulus")
    end
  endtask

  protected task await_applied(bit want);
    bit [63:0] observed;
    for (int unsigned poll = 0; poll < ResetApplyPolls; poll++) begin
      mem_read(ResetTimeoutAddr, observed, "RESET_TIMEOUT poll");
      if (bit'((observed & AppliedMask) != 0) == want) begin
        check_evidence(ChkReset, "reset applied level", 64'((observed & AppliedMask) != 0),
                       64'(want));
        return;
      end
      wait_smc_cycles(1);
    end
    check_evidence(ChkReset, "reset applied timeout", 64'((observed & AppliedMask) != 0),
                   64'(want));
    `uvm_fatal(get_type_name(), "Software core reset did not reach the requested level")
  endtask

  protected task check_reset_ctrl(bit [63:0] expected);
    bit [63:0] observed;
    mem_read(ResetCtrlAddr, observed, "RESET_CTRL readback");
    check_evidence(ChkReset, "core reset configuration", observed, expected);
    if (observed != expected) begin
      `uvm_fatal(get_type_name(),
                 "Core reset configuration does not match the measurement stimulus")
    end
  endtask

  protected task await_boundary(bit isolated);
    for (int unsigned cycle = 0; cycle < BoundaryPollCycles; cycle++) begin
      if (tb_vif.cpu_cluster_isolate === isolated) begin
        check_evidence(ChkReset, "cluster isolation level", 64'(tb_vif.cpu_cluster_isolate),
                       64'(isolated));
        return;
      end
      wait_smc_cycles(1);
    end
    check_evidence(ChkReset, "cluster isolation timeout", 64'(tb_vif.cpu_cluster_isolate),
                   64'(isolated));
    `uvm_fatal(get_type_name(), "Cluster isolation did not reach the requested level")
  endtask

  protected task measure_interval(output bit [31:0] before_count, output bit [31:0] after_count,
                                  output real total, output real held);
    bit [63:0] timeout_word;
    real t0, t1, applied_at, release_at;
    read_count(before_count, t0);
    mem_write(ResetCtrlAddr, reset_baseline & ~core_reset_mask, "hold core reset");
    check_reset_ctrl(reset_baseline & ~core_reset_mask);
    await_applied(1'b1);
    await_boundary(1'b1);
    applied_at = smc_cycle_time();
    // L2 frontend traffic stalls while any core is held in reset.
    wait_smc_cycles(HoldCycles);
    mem_read(ResetTimeoutAddr, timeout_word, "RESET_TIMEOUT held");
    check_evidence(ChkReset, "reset held before release", 64'((timeout_word & AppliedMask) != 0),
                   64'h1);
    if ((timeout_word & AppliedMask) == 0) begin
      `uvm_fatal(get_type_name(), "Core reset was not held throughout the measurement interval")
    end
    release_at = smc_cycle_time();
    mem_write(ResetCtrlAddr, reset_baseline, "release core reset");
    check_reset_ctrl(reset_baseline);
    await_applied(1'b0);
    await_boundary(1'b0);
    read_count(after_count, t1);
    total = t1 - t0;
    held = release_at - applied_at;
    if (held <= 0.0 || total < held) begin
      `uvm_fatal(get_type_name(), "Invalid watchdog measurement timestamps")
    end
  endtask

  task body();
    bit [31:0] c0, c1, saved_compare, saved_count, saved_ctrl, restored_count;
    bit [63:0] timeout_word;
    real t0, t1, rate, total, held, delta, margin, held_limit, always_limit;
    bit negative, predicate;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkMemResp, ChkConfig, ChkReset, ChkRate, ChkHeld,
                    ChkAlways, ChkWindow, ChkNonvac, ChkScoreboard, ChkSbMinAct});
    wait_fuse_sense_done();
    negative = env_cfg.wdt_coreawake_sequence_negative;
    core = loop_index % SmcWdtCores;
    core_reset_mask = reset_mask(core);
    compare_before = scoreboard.compare_count(SmcFeatureWdtCsr);
    mismatch_before = scoreboard.mismatch_count(SmcFeatureWdtCsr);
    check_min_activity(SmcFeatureWdtCsr, WdtAccessesPerPass);
    mem_read(ResetCtrlAddr, reset_baseline, "RESET_CTRL baseline");
    mem_read(ResetTimeoutAddr, timeout_word, "RESET_TIMEOUT baseline");
    check_evidence(ChkReset, "selected core released", 64'((reset_baseline & core_reset_mask) != 0),
                   64'h1);
    check_evidence(ChkReset, "baseline reset applied", 64'((timeout_word & AppliedMask) != 0),
                   negative ? 64'h1 : 64'h0);
    if ((reset_baseline & core_reset_mask) == 0 || (timeout_word & AppliedMask) != 0) begin
      `uvm_fatal(get_type_name(), "Core reset measurement requires a released core")
    end

    await_boundary(1'b0);
    csr_read(smc_wdt_addr(core, WDT_CTRL), saved_ctrl, "CTRL baseline");
    check_evidence(ChkConfig, "disabled watchdog baseline", saved_ctrl, WDT_CTRL_REG_DEFAULT);
    if (saved_ctrl != WDT_CTRL_REG_DEFAULT) begin
      `uvm_fatal(get_type_name(), "Count restoration requires the disabled reset configuration")
    end
    csr_read(smc_wdt_addr(core, WDT_COUNT), saved_count, "COUNT baseline");
    csr_read(smc_wdt_addr(core, WDT_CMP), saved_compare, "CMP baseline");
    wdt_write(WDT_CMP, CompareValue);
    wdt_write(WDT_CTRL, AwakeConfig);
    check_ctrl(AwakeConfig, negative);
    wdt_write(WDT_COUNT, CountStart);
    read_count(c0, t0);
    wait_smc_cycles(RateWindowCycles);
    read_count(c1, t1);
    if (t1 <= t0 || c1 < c0) begin
      check_evidence(ChkRate, "valid rate calibration", 64'h0, 64'h1, $sformatf(
                     "count0=%0d count1=%0d t0=%0f t1=%0f", c0, c1, t0, t1));
      `uvm_fatal(get_type_name(), "Watchdog calibration timestamps or count are invalid")
    end
    rate = real'(c1 - c0) / (t1 - t0);
    check_evidence(ChkRate, "positive count rate", 64'(rate > 0.0), 64'h1, $sformatf(
                   "core=%0d count0=%0d count1=%0d rate=%0f", core, c0, c1, rate));
    if (rate <= 0.0) begin
      `uvm_fatal(get_type_name(), "Watchdog does not count with the core released")
    end

    for (int unsigned mode = 0; mode < ResetIntervalsPerPass; mode++) begin
      if (mode != 0) begin
        wdt_write(WDT_CTRL, AwakeConfig | AlwaysMask);
        check_ctrl(AwakeConfig | AlwaysMask);
      end
      wdt_write(WDT_COUNT, CountStart);
      measure_interval(c0, c1, total, held);
      check_ctrl(mode == 0 ? AwakeConfig : AwakeConfig | AlwaysMask);
      `uvm_info(get_type_name(), {
                "OBS-BLOCKED CHK-WDT-AWAKE-RETAINED reason=COUNT retention across ",
                "software core reset is not explicitly defined"
                }, UVM_LOW)
      `uvm_info(get_type_name(), $sformatf(
                "OBS-WDT-AWAKE-COUNT seed=%0d core=%0d mode=%0d before=%0d after=%0d",
                scenario_seed,
                core,
                mode,
                c0,
                c1
                ), UVM_LOW)
      delta = real'(c1) - real'(c0);
      margin = rate * held / 4.0;
      held_limit = rate * (total - held) + margin;
      always_limit = rate * total - margin;
      check_evidence(ChkWindow, "integer count bounds are distinguishable",
                     64'(always_limit - held_limit >= 2.0), 64'h1, $sformatf(
                     "rate=%0f held=%0f low=%0f high=%0f separation=%0f",
                     rate,
                     held,
                     held_limit,
                     always_limit,
                     always_limit - held_limit
                     ));
      if (always_limit - held_limit < 2.0) begin
        `uvm_fatal(get_type_name(), "Count bounds must separate by at least two count units")
      end
      predicate = mode == 0 ? delta <= held_limit : delta >= always_limit;
      if (negative) begin
        predicate = mode == 0 ? delta >= always_limit : delta <= held_limit;
      end
      check_evidence(mode == 0 ? ChkHeld : ChkAlways, "count across reset interval", 64'(predicate),
                     64'h1, $sformatf(
                     "core=%0d rate=%0f total=%0f held=%0f delta=%0f low=%0f high=%0f",
                     core,
                     rate,
                     total,
                     held,
                     delta,
                     held_limit,
                     always_limit
                     ));
    end
    wdt_write(WDT_CTRL, saved_ctrl);
    check_ctrl(saved_ctrl);
    wdt_write(WDT_COUNT, saved_count);
    csr_read(smc_wdt_addr(core, WDT_COUNT), restored_count, "COUNT restored");
    check_evidence(ChkConfig, "restored stopped count", restored_count, saved_count);
    check_reset_ctrl(reset_baseline);
    await_applied(1'b0);
    wdt_write(WDT_CMP, saved_compare);
    for (int unsigned cycle = 0; cycle < BoundaryPollCycles; cycle++) begin
      if (scoreboard.compare_count(SmcFeatureWdtCsr) >= compare_before + WdtAccessesPerPass) break;
      wait_smc_cycles(1);
    end
    check_evidence(ChkNonvac, "sep_in_csr_accesses", csr_accesses, WdtAccessesPerPass);
    check_evidence(ChkNonvac, "passive watchdog comparisons", scoreboard.compare_count(
                   SmcFeatureWdtCsr) - compare_before, WdtAccessesPerPass);
    check_evidence(ChkScoreboard, "new watchdog mismatches", scoreboard.mismatch_count(
                   SmcFeatureWdtCsr) - mismatch_before, 0);
    finalize_evidence();
  endtask
endclass : smc_wdt_core_awake_gate_test_seq
