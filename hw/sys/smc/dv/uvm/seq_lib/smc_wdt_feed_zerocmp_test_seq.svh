// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Checks keyed feed, scaled count, compare rollover and software interrupt clearing.

class smc_wdt_feed_zerocmp_test_seq extends smc_wdt_base_test_seq;
  `uvm_object_utils(smc_wdt_feed_zerocmp_test_seq)

  localparam string ChkScoreboard = "CHK-WDT-CSR-SCOREBOARD";
  localparam int unsigned ComparisonTimeoutCycles = 1024;
  localparam string ChkRate = "CHK-WDT-FEED-RATE";
  localparam string ChkClear = "CHK-WDT-FEED-CLEAR";
  localparam string ChkReject = "CHK-WDT-FEED-REJECT";
  localparam string ChkScaled = "CHK-WDT-FEED-SCALED";
  localparam string ChkZeroCmp = "CHK-WDT-FEED-ZEROCMP";
  localparam string ChkIp = "CHK-WDT-FEED-IP";
  localparam string ChkWindow = "CHK-WDT-FEED-WINDOW";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned RateWindowCycles = 1024;
  localparam int unsigned ScaledShift = 4;
  localparam int unsigned ZeroCmpCompare = 4096;
  localparam int unsigned ZeroCmpReads = 8;
  localparam int unsigned IpCompare = 2048;
  localparam int unsigned IpMargin = 256;
  localparam int unsigned IpPollIntervalCycles = 64;
  localparam int unsigned IpWaitSlackCycles = 1024;
  // Keyed writes each contribute two accesses; compare polling adds variable reads.
  localparam int unsigned FixedAccesses = 83;
  localparam int unsigned FeedCases = 2;
  localparam bit [31:0] CountStart = 32'h0100_0000;
  localparam bit [31:0] ScaledStart = 32'h0001_0000;
  localparam bit [31:0] CompareMax = WDT_CMP_WDOGCMP0_MASK;
  localparam bit [31:0] CompareReset = 32'(WDT_CMP_REG_DEFAULT);
  localparam bit [31:0] ScaledCountLimit = WDT_SCALED_COUNT_WDOGS_MASK + 32'd1;
  localparam bit [31:0] AlwaysMask = WDT_CTRL_WDOGENALWAYS_MASK;
  localparam bit [31:0] IpMask = WDT_CTRL_WDOGIP0_MASK;
  localparam bit [31:0] ZeroCmpMask = WDT_CTRL_WDOGZEROCMP_MASK;
  localparam bit [31:0] BaseConfig = AlwaysMask | WDT_CTRL_WDOGSCALE_MASK;

  bit negative;

  function new(string name = "smc_wdt_feed_zerocmp_test_seq");
    super.new(name);
  endfunction

  protected task require_window(bit predicate, string label, string context_s = "");
    check_evidence(ChkWindow, label, 64'(predicate), 64'h1, context_s);
    if (!predicate) begin
      `uvm_fatal(get_type_name(), {"Invalid watchdog measurement window: ", label})
    end
  endtask

  protected task ctrl_read(input bit [31:0] config_value, output bit [31:0] value,
                           input bit mask_ip = 1'b0);
    bit [31:0] mask = mask_ip ? ~IpMask : '1;
    csr_read(smc_wdt_addr(core, WDT_CTRL), value, "WDT.CTRL");
    if ((value & mask) != (config_value & mask)) begin
      `uvm_fatal(get_type_name(), "Watchdog configuration does not match the measurement stimulus")
    end
  endtask

  // The wdt_csr feature grades this read against its passive prediction.
  protected task cmp_read();
    bit [31:0] value;
    csr_read(smc_wdt_addr(core, WDT_CMP), value, "WDT.CMP readback");
  endtask

  protected task key_read(bit unlocked);
    bit [31:0] value;
    csr_read(smc_wdt_addr(core, WDT_KEY), value, "WDT.KEY readback");
    if (value != 32'(unlocked)) begin
      `uvm_fatal(get_type_name(), "FEED requires the expected unlock state")
    end
  endtask

  protected task ip_check(bit [31:0] ctrl, bit want, bit corrupt = 1'b0);
    check_evidence(ChkIp, "pending interrupt", 64'((ctrl & IpMask) != 0),
                   64'(corrupt ? !want : want));
  endtask

  protected task count_side(bit high, output bit [31:0] value);
    real stamp;
    read_count(value, stamp);
    require_window(value < ScaledCountLimit && (high ? value >= IpCompare : value < IpCompare),
                   "COUNT brackets interrupt observation", $sformatf(
                   "count=%0d cycle=%0f high=%0b", value, stamp, high));
  endtask

  task body();
    bit [31:0] c0, c1, ctrl, scaled, values[$];
    real t0, t1, rate, key_at, total_span, first_at, last_at, deadline;
    bit predicate, rollover, bounded;
    string samples;
    int unsigned poll_reads = 0;
    int unsigned compare_before, mismatch_before, target;
    bit comparisons_ready = 1'b0;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkRate, ChkClear, ChkReject, ChkScaled, ChkZeroCmp,
                    ChkIp, ChkWindow, ChkNonvac, ChkSbMinAct, ChkScoreboard});
    check_min_activity(SmcFeatureWdtCsr, FixedAccesses);
    compare_before = scoreboard.compare_count(SmcFeatureWdtCsr);
    mismatch_before = scoreboard.mismatch_count(SmcFeatureWdtCsr);
    wait_fuse_sense_done();
    core = loop_index % SmcWdtCores;
    negative = env_cfg.wdt_feed_sequence_negative;
    ctrl_read(0, ctrl);
    wdt_write(WDT_CMP, CompareMax);
    cmp_read();
    wdt_write(WDT_CTRL, BaseConfig);
    ctrl_read(BaseConfig, ctrl, 1'b0);
    wdt_write(WDT_COUNT, CountStart);
    read_count(c0, t0);
    wait_smc_cycles(RateWindowCycles);
    read_count(c1, t1);
    predicate = t1 > t0 && c1 > c0;
    check_evidence(ChkRate, "positive calibration", 64'(predicate), 64'h1, $sformatf(
                   "count0=%0d count1=%0d t0=%0f t1=%0f", c0, c1, t0, t1));
    if (!predicate) begin
      `uvm_fatal(get_type_name(), "Watchdog count-rate calibration is invalid")
    end
    rate = real'(c1 - c0) / (t1 - t0);

    for (int unsigned invalid = 0; invalid < FeedCases; invalid++) begin
      wdt_write(WDT_COUNT, CountStart);
      read_count(c0, t0);
      if (c0 < CountStart) begin
        check_evidence(invalid == 0 ? ChkClear : ChkReject, "known starting count",
                       64'(c0 >= CountStart), 64'h1);
        `uvm_fatal(get_type_name(), "FEED measurement did not load the known count")
      end
      key_at = smc_cycle_time();
      csr_write(smc_wdt_addr(core, WDT_KEY), SmcWdtMagicKey, "FEED unlock");
      key_read(1'b1);
      csr_write(smc_wdt_addr(core, WDT_FEED),
                invalid == 0 ? SmcWdtFeedMagic : SmcWdtFeedMagic ^ 32'h1, "WDT.FEED");
      key_read(1'b0);
      read_count(c1, t1);
      if (invalid == 0) begin
        predicate = negative ? c1 >= c0 : c1 < c0 && real'(c1) <= rate * (t1 - key_at) + 1.0;
      end else begin
        predicate = negative ? c1 < c0 : c1 >= c0;
      end
      check_evidence(invalid == 0 ? ChkClear : ChkReject, "FEED count", 64'(predicate), 64'h1,
                     $sformatf("count0=%0d count1=%0d rate=%0f span=%0f", c0, c1, rate, t1 - key_at
                     ));
    end

    wdt_write(WDT_CTRL, AlwaysMask | 32'(ScaledShift));
    ctrl_read(AlwaysMask | 32'(ScaledShift), ctrl);
    wdt_write(WDT_COUNT, ScaledStart);
    read_count(c0, t0);
    csr_read(smc_wdt_addr(core, WDT_SCALED_COUNT), scaled, "WDT.SCALED_COUNT");
    read_count(c1, t1);
    require_window(c1 >= c0 && (c1 >> ScaledShift) < ScaledCountLimit, "scaled count does not wrap",
                   $sformatf("count0=%0d count1=%0d", c0, c1));
    predicate = negative ? scaled == (c0 >> (ScaledShift - 1)) :
                           scaled >= (c0 >> ScaledShift) && scaled <= (c1 >> ScaledShift);
    check_evidence(ChkScaled, "bracketed scaled count", 64'(predicate), 64'h1, $sformatf(
                   "count0=%0d scaled=%0d count1=%0d", c0, scaled, c1));

    wdt_write(WDT_CMP, ZeroCmpCompare);
    cmp_read();
    wdt_write(WDT_CTRL, AlwaysMask | ZeroCmpMask);
    ctrl_read(AlwaysMask | ZeroCmpMask, ctrl, 1'b1);
    wdt_write(WDT_COUNT, 0);
    rollover = 0;
    bounded = 1;
    samples = "";
    for (int unsigned sample_index = 0; sample_index < ZeroCmpReads; sample_index++) begin
      if (sample_index != 0) begin
        wait_smc_cycles(int'($ceil(real'(ZeroCmpCompare) / (3.0 * rate))));
      end
      read_count(c1, t1);
      if (sample_index == 0) first_at = t1;
      else if (c1 < values[$]) rollover = 1;
      values.push_back(c1);
      bounded &= c1 <= ZeroCmpCompare;
      last_at = t1;
      samples = {samples, $sformatf(" [%0f:%0d]", t1, c1)};
    end
    total_span = last_at - first_at;
    require_window(total_span >= 2.0 * real'(ZeroCmpCompare) / rate, "compare sampling span",
                   samples);
    predicate = negative ? !bounded : bounded && rollover;
    check_evidence(ChkZeroCmp, "sampled compare rollover", 64'(predicate), 64'h1, samples);

    wdt_write(WDT_FEED, SmcWdtFeedMagic);
    wdt_write(WDT_CMP, IpCompare);
    cmp_read();
    wdt_write(WDT_CTRL, AlwaysMask);
    count_side(1'b0, c0);
    ctrl_read(AlwaysMask, ctrl, 1'b1);
    count_side(1'b0, c1);
    ip_check(ctrl, 1'b0);
    deadline = smc_cycle_time() + real'(IpCompare + IpMargin) / rate + IpWaitSlackCycles;
    forever begin
      read_count(c0, t0);
      poll_reads++;
      if (c0 >= IpCompare + IpMargin) break;
      if (smc_cycle_time() >= deadline) begin
        require_window(1'b0, "count reaches compare before deadline", $sformatf(
                       "count=%0d cycle=%0f deadline=%0f", c0, t0, deadline));
      end
      wait_smc_cycles(IpPollIntervalCycles);
    end
    require_window(t0 <= deadline, "count reaches compare before deadline");
    require_window(c0 >= IpCompare + IpMargin && c0 < ScaledCountLimit, "COUNT past compare margin",
                   $sformatf("count=%0d", c0));
    ctrl_read(AlwaysMask, ctrl, 1'b1);
    count_side(1'b1, c1);
    ip_check(ctrl, 1'b1);

    count_side(1'b1, c0);
    wdt_write(WDT_CTRL, AlwaysMask);
    ctrl_read(AlwaysMask, ctrl, 1'b1);
    count_side(1'b1, c1);
    ip_check(ctrl, 1'b1, negative);

    wdt_write(WDT_FEED, SmcWdtFeedMagic);
    count_side(1'b0, c0);
    wdt_write(WDT_CTRL, AlwaysMask);
    ctrl_read(AlwaysMask, ctrl, 1'b1);
    count_side(1'b0, c1);
    ip_check(ctrl, 1'b0);

    wdt_write(WDT_FEED, SmcWdtFeedMagic);
    wdt_write(WDT_CTRL, 0);
    wdt_write(WDT_CMP, CompareReset);
    cmp_read();
    ctrl_read(0, ctrl);
    target = compare_before + FixedAccesses + poll_reads;
    for (int unsigned cycle = 0; cycle < ComparisonTimeoutCycles; cycle++) begin
      if (scoreboard.compare_count(SmcFeatureWdtCsr) >= target) begin
        comparisons_ready = 1'b1;
        break;
      end
      wait_smc_cycles(1);
    end
    if (!comparisons_ready)
      `uvm_error("OCAH_SMC_WDT_CSR_TIMEOUT", "Watchdog comparisons did not complete within bound")
    check_evidence(ChkScoreboard, "watchdog comparisons complete without mismatch",
                   64'(scoreboard.compare_count(SmcFeatureWdtCsr
                   ) == target && scoreboard.mismatch_count(SmcFeatureWdtCsr) == mismatch_before),
                   64'h1, $sformatf(
                   "compares=%0d expected=%0d new_mismatches=%0d",
                   scoreboard.compare_count(
                       SmcFeatureWdtCsr
                   ) - compare_before,
                   FixedAccesses + poll_reads,
                   scoreboard.mismatch_count(
                       SmcFeatureWdtCsr
                   ) - mismatch_before
                   ));
    check_evidence(ChkNonvac, "sep_in_csr_accesses", 64'(csr_accesses),
                   64'(FixedAccesses + poll_reads));
    finalize_evidence();
  endtask
endclass : smc_wdt_feed_zerocmp_test_seq
