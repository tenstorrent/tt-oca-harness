// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Checks per-core second-stage watchdog service, expiry and warm-reset recovery.

class smc_wdt_second_stage_reset_test_seq extends smc_wdt_base_test_seq;
  `uvm_object_utils(smc_wdt_second_stage_reset_test_seq)

  localparam string ChkConfig = "CHK-WDT-STAGE2-CONFIG";
  localparam string ChkFirst = "CHK-WDT-STAGE2-FIRST";
  localparam string ChkService = "CHK-WDT-STAGE2-SERVICE";
  localparam string ChkHeld = "CHK-WDT-STAGE2-HELD";
  localparam string ChkExpires = "CHK-WDT-STAGE2-EXPIRES";
  localparam string ChkWrong = "CHK-WDT-STAGE2-WRONG-CORE";
  localparam string ChkRecovery = "CHK-WDT-STAGE2-RECOVERY";
  localparam string ChkScope = "CHK-WDT-STAGE2-SCOPE";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned Stage1Compare = 2048;
  localparam int unsigned Stage2Cycles = 6144;
  localparam int unsigned ServiceIntervalCycles = Stage2Cycles / 6;
  localparam int unsigned ServiceWindowCycles = 2 * Stage2Cycles;
  localparam int unsigned FirstTimeoutBoundCycles = 16384;
  localparam int unsigned ServiceGapBoundCycles = Stage2Cycles / 2;
  // Negedge samples follow the decrement and registered second-timeout updates.
  localparam int unsigned TimingSlackCycles = 2;
  localparam int unsigned PostServiceSlackCycles = 1024;
  localparam int unsigned WarmAssertBoundCycles = 4096;
  localparam int unsigned WarmReleaseBoundCycles = 16384;
  localparam int unsigned WrongCoreStopCycles = Stage2Cycles - ServiceIntervalCycles;
  localparam int unsigned WatcherBoundCycles = 16;
  localparam int unsigned FunctionalResetsPerPass = 2;
  // Initial reads, two recovery baselines, two arms and timeout configuration/restore.
  localparam int unsigned FixedCsrAccesses =
      2 * SmcWdtCores + FunctionalResetsPerPass * (13 * SmcWdtCores + 1) + 18 + 7;
  localparam bit [31:0] WdtConfig = WDT_CTRL_WDOGENALWAYS_MASK | WDT_CTRL_WDOGRSTEN_MASK;
  localparam bit [63:0] TimeoutAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR;
  localparam bit [63:0] ServiceAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_RESET_BASE_ADDR;

  bit negative;
  bit watch_ready, watch_done, watch_stop;
  bit first_seen, second_seen, wdt_reset_seen, warm_seen, warm_released;
  bit first_broken, wrong_source, primary_seen, unknown_seen;
  real first_at, second_at, wdt_at, warm_at, release_at;
  real last_start, last_return, maximum_gap;
  int unsigned service_pulses, wrong_pulses, warm_assertions;

  function new(string name = "smc_wdt_second_stage_reset_test_seq");
    super.new(name);
  endfunction

  protected function bit [31:0] service_mask(int unsigned selected);
    case (selected)
      0: return CPU_CTRL_WDT_TIMEOUT_RESET_RESET_CYCLE_COUNT_0_MASK;
      1: return CPU_CTRL_WDT_TIMEOUT_RESET_RESET_CYCLE_COUNT_1_MASK;
      2: return CPU_CTRL_WDT_TIMEOUT_RESET_RESET_CYCLE_COUNT_2_MASK;
      3: return CPU_CTRL_WDT_TIMEOUT_RESET_RESET_CYCLE_COUNT_3_MASK;
      default: begin
        `uvm_fatal(get_type_name(), "Invalid second-stage service core")
        return '0;
      end
    endcase
  endfunction

  protected task watch_timeout();
    watch_ready = 1;
    while (!watch_stop) begin
      @(negedge tb_vif.clk_smc);
      if ($isunknown(
              {
                tb_vif.wdt_first_timeout,
                tb_vif.wdt_second_timeout,
                tb_vif.wdt_timeout_core,
                tb_vif.rst_primary_smc_clk_n,
                tb_vif.rst_wdt_smc_clk_n,
                tb_vif.rst_warm_smc_clk_n
              }
          ))
        unknown_seen = 1;
      if (tb_vif.rst_primary_smc_clk_n !== 1'b1) primary_seen = 1;
      if (!first_seen && tb_vif.wdt_timeout_core[core] === 1'b1) begin
        first_seen = 1;
        first_at = smc_cycle_time();
      end
      if (!second_seen && tb_vif.wdt_second_timeout === 1'b1) begin
        second_seen = 1;
        second_at = smc_cycle_time();
      end
      if (first_seen && !second_seen) begin
        if (tb_vif.wdt_timeout_core[core] !== 1'b1 || tb_vif.wdt_first_timeout !== 1'b1)
          first_broken = 1;
        if ((tb_vif.wdt_timeout_core & ~(32'h1 << core)) != 0) wrong_source = 1;
      end
      if (!wdt_reset_seen && tb_vif.rst_wdt_smc_clk_n === 1'b0) begin
        wdt_reset_seen = 1;
        wdt_at = smc_cycle_time();
      end
      if (!warm_seen && tb_vif.rst_warm_smc_clk_n === 1'b0) begin
        warm_seen = 1;
        warm_assertions++;
        warm_at = smc_cycle_time();
      end
      if (warm_seen && !warm_released && tb_vif.rst_warm_smc_clk_n === 1'b1) begin
        warm_released = 1;
        release_at = smc_cycle_time();
      end
    end
    watch_done = 1;
  endtask

  protected task start_watch();
    if (watch_ready && !watch_done) begin
      `uvm_fatal(get_type_name(), "Watchdog watcher is already active")
    end
    watch_ready = 0;
    watch_done = 0;
    watch_stop = 0;
    first_seen = 0;
    second_seen = 0;
    wdt_reset_seen = 0;
    warm_seen = 0;
    warm_released = 0;
    first_broken = 0;
    wrong_source = 0;
    primary_seen = 0;
    unknown_seen = 0;
    first_at = 0;
    second_at = 0;
    wdt_at = 0;
    warm_at = 0;
    release_at = 0;
    fork
      watch_timeout();
    join_none
    for (int unsigned cycle = 0; cycle < WatcherBoundCycles; cycle++) begin
      if (watch_ready) return;
      wait_smc_cycles(1);
    end
    `uvm_fatal(get_type_name(), "Watchdog watcher did not start")
  endtask

  protected task stop_watch();
    watch_stop = 1;
    for (int unsigned cycle = 0; cycle < WatcherBoundCycles; cycle++) begin
      if (watch_done) return;
      wait_smc_cycles(1);
    end
    `uvm_fatal(get_type_name(), "Watchdog watcher did not stop")
  endtask

  protected task require_condition(string id, bit actual, string label, bit corrupt = 1'b0,
                                   string context_s = "");
    check_evidence(id, label, 64'(actual), corrupt ? 64'h0 : 64'h1, context_s);
    if (!actual) begin
      `uvm_fatal(get_type_name(), {"Invalid watchdog stimulus or observation: ", label})
    end
  endtask

  protected task clean_watchdogs();
    bit [31:0] ctrl, count_value;
    for (int unsigned selected = 0; selected < SmcWdtCores; selected++) begin
      csr_read(smc_wdt_addr(selected, WDT_CTRL), ctrl, "WDT reset CTRL");
      csr_read(smc_wdt_addr(selected, WDT_COUNT), count_value, "WDT reset COUNT");
      require_condition(ChkConfig,
                        ctrl == WDT_CTRL_REG_DEFAULT && count_value == WDT_COUNT_REG_DEFAULT,
                        "watchdog reset state", 1'b0, $sformatf(
                        "core=%0d ctrl=%0h count=%0h", selected, ctrl, count_value));
    end
    require_condition(ChkScope,
                      tb_vif.wdt_timeout_core === '0 && tb_vif.wdt_second_timeout === 1'b0 &&
                      tb_vif.rst_wdt_smc_clk_n === 1'b1 &&
                      tb_vif.rst_warm_smc_clk_n === 1'b1 &&
                      tb_vif.rst_primary_smc_clk_n === 1'b1,
                      "reset scope initially released");
  endtask

  protected task arm_job();
    bit [31:0] ctrl, count_value, compare_value;
    wdt_write(WDT_COUNT, 0);
    wdt_write(WDT_CMP, Stage1Compare);
    csr_read(smc_wdt_addr(core, WDT_COUNT), count_value, "WDT pre-arm COUNT");
    csr_read(smc_wdt_addr(core, WDT_CMP), compare_value, "WDT pre-arm CMP");
    require_condition(ChkConfig, count_value == 0 && compare_value == Stage1Compare,
                      "pre-arm watchdog configuration", 1'b0, $sformatf(
                      "core=%0d count=%0h cmp=%0h expected_cmp=%0h",
                      core,
                      count_value,
                      compare_value,
                      Stage1Compare
                      ));
    start_watch();
    wdt_write(WDT_CTRL, WdtConfig);
    csr_read(smc_wdt_addr(core, WDT_CTRL), ctrl, "WDT armed CTRL");
    require_condition(ChkConfig, (ctrl & ~WDT_CTRL_WDOGIP0_MASK) == WdtConfig,
                      "armed WDT configuration");
    for (int unsigned cycle = 0; cycle < FirstTimeoutBoundCycles; cycle++) begin
      if (first_seen) break;
      wait_smc_cycles(1);
    end
    require_condition(ChkFirst,
                      first_seen && !second_seen && !warm_seen && !primary_seen && !unknown_seen,
                      "first timeout precedes reset");
  endtask

  protected task recovery_write(int unsigned selected, smc_wdt_reg_e reg_kind, bit [31:0] value);
    csr_write(smc_wdt_addr(selected, WDT_KEY), SmcWdtMagicKey, "recovery WDT.KEY");
    csr_write(smc_wdt_addr(selected, reg_kind), value, "recovery WDT configuration");
  endtask

  protected task rebaseline_after_warm(string leg);
    bit [31:0] timeout_value, ctrl, count_value, compare_value;
    csr_read(TimeoutAddr, timeout_value, "WDT_TIMEOUT after warm reset observation");
    `uvm_info(get_type_name(), {
              "OBS-BLOCKED CHK-WDT-STAGE2-TIMEOUT-RETAINED reason=CPU_CTRL timeout ",
              "retention across warm reset is not explicitly defined"}, UVM_LOW)
    `uvm_info(get_type_name(),
              $sformatf("OBS-WDT-STAGE2-RETAINED seed=%0d core=%0d leg=%s timeout=0x%08h",
                        scenario_seed, core, leg, timeout_value), UVM_LOW)
    `uvm_info(get_type_name(), {"OBS-BLOCKED CHK-WDT-STAGE2-WDT-RESET reason=watchdog CSR reset ",
                                "values after warm reset are not explicitly defined"}, UVM_LOW)
    for (int unsigned selected = 0; selected < SmcWdtCores; selected++) begin
      csr_read(smc_wdt_addr(selected, WDT_CTRL), ctrl, "WDT warm CTRL observation");
      csr_read(smc_wdt_addr(selected, WDT_COUNT), count_value, "WDT warm COUNT observation");
      `uvm_info(get_type_name(), $sformatf(
                "OBS-WDT-STAGE2-STATE seed=%0d core=%0d leg=%s ctrl=0x%08h count=0x%08h",
                scenario_seed,
                selected,
                leg,
                ctrl,
                count_value
                ), UVM_LOW)
      recovery_write(selected, WDT_CTRL, 32'(WDT_CTRL_REG_DEFAULT));
      recovery_write(selected, WDT_COUNT, 32'(WDT_COUNT_REG_DEFAULT));
      recovery_write(selected, WDT_CMP, 32'(WDT_CMP_REG_DEFAULT));
      // Clear the pending interrupt after COUNT is below CMP.
      recovery_write(selected, WDT_CTRL, 32'(WDT_CTRL_REG_DEFAULT));
      csr_read(smc_wdt_addr(selected, WDT_CTRL), ctrl, "WDT configured idle CTRL");
      csr_read(smc_wdt_addr(selected, WDT_COUNT), count_value, "WDT configured idle COUNT");
      csr_read(smc_wdt_addr(selected, WDT_CMP), compare_value, "WDT configured idle CMP");
      require_condition(ChkConfig,
                        ctrl == WDT_CTRL_REG_DEFAULT && count_value == WDT_COUNT_REG_DEFAULT &&
                        compare_value == WDT_CMP_REG_DEFAULT,
                        "explicit watchdog recovery configuration", 1'b0, $sformatf(
                        "core=%0d ctrl=%0h count=%0h cmp=%0h",
                        selected,
                        ctrl,
                        count_value,
                        compare_value
                        ));
    end
    require_condition(ChkScope,
                      tb_vif.wdt_timeout_core === '0 && tb_vif.wdt_second_timeout === 1'b0 &&
                      tb_vif.rst_wdt_smc_clk_n === 1'b1 &&
                      tb_vif.rst_warm_smc_clk_n === 1'b1 &&
                      tb_vif.rst_primary_smc_clk_n === 1'b1,
                      "rebaselined timeout taps idle and resets released", 1'b0, $sformatf(
                      "leg=%s first=%b second=%b wdt_n=%b warm_n=%b primary_n=%b",
                      leg,
                      tb_vif.wdt_timeout_core,
                      tb_vif.wdt_second_timeout,
                      tb_vif.rst_wdt_smc_clk_n,
                      tb_vif.rst_warm_smc_clk_n,
                      tb_vif.rst_primary_smc_clk_n
                      ));
  endtask

  protected task pulse_core(int unsigned selected);
    real pulse_start, pulse_return, gap;
    pulse_start = smc_cycle_time();
    csr_write(ServiceAddr, service_mask(selected), "CPU_CTRL.WDT_TIMEOUT_RESET");
    pulse_return = smc_cycle_time();
    if (selected == core) begin
      gap = service_pulses == 0 ? pulse_return - first_at : pulse_return - last_start;
      if (gap > maximum_gap) maximum_gap = gap;
      service_pulses++;
    end else begin
      wrong_pulses++;
    end
    last_start = pulse_start;
    last_return = pulse_return;
  endtask

  protected task await_recovery(real earliest, real latest, bit wrong_leg);
    bit arrived;
    real fuse_ready_at;
    real deadline = latest + WarmAssertBoundCycles + WarmReleaseBoundCycles;
    while (!warm_released && smc_cycle_time() <= deadline) begin
      wait_smc_cycles(1);
    end
    arrived = second_seen && second_at >= earliest && second_at <= latest;
    check_evidence(
        ChkExpires, "second timeout interval", 64'(arrived), negative && !wrong_leg ? 64'h0 : 64'h1,
        $sformatf(
        "first=%0f second=%0f earliest=%0f latest=%0f", first_at, second_at, earliest, latest));
    if (wrong_leg) begin
      check_evidence(ChkWrong, "wrong-core service does not defer timeout", 64'(arrived),
                     negative ? 64'h0 : 64'h1);
    end
    require_condition(ChkFirst, !first_broken && !wrong_source,
                      "selected first timeout remains high");
    require_condition(ChkRecovery,
                      second_seen && wdt_reset_seen && warm_seen && warm_released &&
                      wdt_at >= second_at && warm_at >= second_at &&
                      warm_at <= second_at + WarmAssertBoundCycles &&
                      release_at <= warm_at + WarmReleaseBoundCycles,
                      "WDT and warm reset assert and release", negative && !wrong_leg, $sformatf(
                      {
                        "core=%0d leg=%s second_seen=%0b wdt_seen=%0b warm_seen=%0b ",
                        "released=%0b wdt_delay=%0f warm_delay=%0f warm_duration=%0f"
                      },
                      core,
                      wrong_leg ? "C" : "B",
                      second_seen,
                      wdt_reset_seen,
                      warm_seen,
                      warm_released,
                      wdt_at - second_at,
                      warm_at - second_at,
                      release_at - warm_at
                      ));
    require_condition(ChkScope, !primary_seen && !unknown_seen,
                      "no primary reset or unknown observable");
    stop_watch();
    wait_fuse_sense_done();
    fuse_ready_at = smc_cycle_time();
    require_condition(ChkRecovery,
                      tb_vif.fuse_sense_done === 1'b1 && tb_vif.fuse_reset_n === 1'b1 &&
                      tb_vif.rst_warm_smc_clk_n === 1'b1,
                      "fuse readiness observed", 1'b0, $sformatf(
                      "core=%0d leg=%s warm_release=%0f fuse_ready=%0f release_to_ready=%0f",
                      core,
                      wrong_leg ? "C" : "B",
                      release_at,
                      fuse_ready_at,
                      fuse_ready_at - release_at
                      ));
    rebaseline_after_warm(wrong_leg ? "C" : "B");
  endtask

  task body();
    bit [31:0] baseline, readback;
    int unsigned other_core;
    real service_begin, stop_deadline, preceding_return, remaining;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkConfig, ChkFirst, ChkService, ChkHeld,
                    ChkExpires, ChkWrong, ChkRecovery, ChkScope, ChkNonvac});
    wait_fuse_sense_done();
    core = loop_index % SmcWdtCores;
    other_core = (core + 1) % SmcWdtCores;
    negative = env_cfg.wdt_stage2_sequence_negative;
    warm_assertions = 0;
    service_pulses = 0;
    wrong_pulses = 0;
    maximum_gap = 0;
    require_condition(ChkScope, tb_vif.cpu_cluster_isolate === 1'b0,
                      "all cores released before watchdog CSR access");
    clean_watchdogs();
    csr_read(TimeoutAddr, baseline, "WDT_TIMEOUT baseline");
    csr_write(TimeoutAddr, Stage2Cycles, "WDT_TIMEOUT configure");
    csr_read(TimeoutAddr, readback, "WDT_TIMEOUT configured");
    check_evidence(ChkConfig, "second-stage timeout configuration", readback,
                   negative ? 32'(Stage2Cycles) ^ 32'h1 : 32'(Stage2Cycles));
    if (readback != Stage2Cycles) begin
      `uvm_fatal(get_type_name(), "Second-stage timeout write did not take effect")
    end
    arm_job();
    service_begin = smc_cycle_time();
    pulse_core(core);
    while (smc_cycle_time() - service_begin < ServiceWindowCycles) begin
      wait_smc_cycles(ServiceIntervalCycles);
      pulse_core(core);
      require_condition(ChkService,
                        maximum_gap < ServiceGapBoundCycles && !first_broken && !wrong_source,
                        "service gap and source", 1'b0, $sformatf(
                        "pulses=%0d maximum_gap=%0f", service_pulses, maximum_gap));
    end
    require_condition(ChkService,
                      service_pulses > 1 &&
                      smc_cycle_time() - service_begin >= ServiceWindowCycles &&
                      maximum_gap < ServiceGapBoundCycles,
                      "service duration and initial gap");
    require_condition(
        ChkHeld, !second_seen && !wdt_reset_seen && !warm_seen && !primary_seen && !unknown_seen,
        "no timeout while serviced", negative);
    // No CSR is issued between the final service response and reset recovery.
    await_recovery(last_start + Stage2Cycles, last_return + Stage2Cycles + TimingSlackCycles, 1'b0);
    csr_write(TimeoutAddr, Stage2Cycles, "WDT_TIMEOUT reconfigure before wrong-core leg");
    csr_read(TimeoutAddr, readback, "WDT_TIMEOUT reconfigured");
    require_condition(ChkConfig, readback == Stage2Cycles, "explicit timeout reconfiguration");

    arm_job();
    stop_deadline = first_at + WrongCoreStopCycles;
    while (smc_cycle_time() + PostServiceSlackCycles < stop_deadline) begin
      wait_smc_cycles(ServiceIntervalCycles);
      preceding_return = smc_cycle_time();
      remaining = stop_deadline - preceding_return;
      if (remaining <= PostServiceSlackCycles) break;
      pulse_core(other_core);
      require_condition(ChkService, last_return < stop_deadline,
                        "wrong-core pulse completes before reset window");
    end
    require_condition(ChkWrong,
                      other_core != core && wrong_pulses > 1 &&
                      last_start > first_at + TimingSlackCycles &&
                      last_return < stop_deadline,
                      "wrong-core stimulus identity and timing");
    await_recovery(first_at + Stage2Cycles, first_at + Stage2Cycles + TimingSlackCycles, 1'b1);
    csr_write(TimeoutAddr, baseline, "restore WDT_TIMEOUT");
    csr_read(TimeoutAddr, readback, "restored WDT_TIMEOUT");
    require_condition(ChkConfig, readback == baseline, "timeout baseline restored");
    check_evidence(ChkNonvac, "observed warm-reset assertions", warm_assertions,
                   FunctionalResetsPerPass, $sformatf(
                   "service_pulses=%0d wrong_pulses=%0d", service_pulses, wrong_pulses));
    check_evidence(ChkNonvac, "sep_in_csr_accesses", csr_accesses,
                   FixedCsrAccesses + service_pulses + wrong_pulses);
    finalize_evidence();
  endtask
endclass : smc_wdt_second_stage_reset_test_seq
