// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Grades cool-reset CSR clearing and fresh recovery after held W and B phases.
class smc_zeroer_reset_during_operation_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_zeroer_reset_during_operation_test_seq)
  localparam logic [2:0] ZeroerStIdle = 3'b001;
  localparam logic [2:0] ZeroerStIssueData = 3'b100;
  localparam int unsigned PollBound = 50000;
  localparam int unsigned ResetBound = 5000;
  localparam int unsigned StableSamples = 16;
  localparam int unsigned GuardBytes = 64;
  localparam int unsigned MaxRecoveryBytes = 1024;
  localparam int unsigned MinInterruptedBytes = 2056;
  localparam int unsigned MaxInterruptedBytes = 3584;
  localparam int unsigned MaxOffsetBytes = 512;
  localparam int unsigned MinStallCycles = 2048;
  localparam int unsigned MaxStallCycles = 6144;
  localparam bit [63:0] InterruptedOffsetA = 64'h1000;
  localparam bit [63:0] InterruptedOffsetB = 64'h5000;
  localparam bit [63:0] RecoveryOffsetA = 64'h9000;
  localparam bit [63:0] RecoveryOffsetB = 64'hD000;
  localparam bit [63:0] PassStride = 64'h20000;
  localparam bit [63:0] PassExtent = RecoveryOffsetB + MaxOffsetBytes +
      MaxRecoveryBytes + GuardBytes;
  localparam int unsigned ResetWindowCycles = 512;
  localparam int unsigned StallMarginCycles = 32;
  localparam bit [63:0] OutputBase = 64'h0200_0000;
  localparam bit [63:0] PassAll = FILTER_CTRL_FILTER_CONFIG_READ_ALLOWED_MASK |
      FILTER_CTRL_FILTER_CONFIG_WRITE_ALLOWED_MASK | FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_MASK |
      FILTER_CTRL_FILTER_CONFIG_ALLOW_BURST_MASK;

  localparam bit [63:0] FilterWriteMask = PassAll | FILTER_CTRL_FILTER_CONFIG_ALLOW_NS_MASK |
      FILTER_CTRL_FILTER_CONFIG_SRC_ID_MASK | FILTER_CTRL_FILTER_CONFIG_GROUP_ID_MASK |
      FILTER_CTRL_FILTER_CONFIG_LOCKED_MASK;

  typedef struct {
    logic [2:0] state;
    logic busy, wvalid, wready;
    logic [31:0] outstanding;
    longint unsigned cycle, aw, w_bytes, wlast, b, irq;
    time sampled_at;
  } sample_t;
  protected sample_t sample;
  protected bit stop_sampling;
  protected int unsigned w_stall, accepted_before_stall, recovery_size;
  protected bit negative, arm_w_stall;
  protected longint unsigned stall_start_cycle;
  protected int unsigned next_command;
  protected bit last_irq;
  protected longint unsigned old_post_reset_irq;
  protected bit [63:0] region_base;
  protected bit [63:0] filter_start_addr, filter_end_addr, filter_config_addr;
  protected smc_zeroer_burst_observer observer;
  protected longint unsigned clock_cycles;
  protected bit [63:0] fresh_dest;
  protected int unsigned old_completed_before, old_bytes_before;

  function new(string name = "smc_zeroer_reset_during_operation_test_seq");
    super.new(name);
  endfunction

  protected task sample_port();
    while (!stop_sampling) begin
      @(tb_vif.zeroer_cb);
      clock_cycles++;
      if (tb_vif.zeroer_cb.rst_primary_smc_clk_n === 1'b1) begin
        sample.cycle = clock_cycles;
        sample.sampled_at = $time;
        if (tb_vif.zeroer_cb.zeroer_intp === 1'b1 && !last_irq) sample.irq++;
        last_irq = tb_vif.zeroer_cb.zeroer_intp === 1'b1;
        sample.state = tb_vif.zeroer_cb.zeroer_state;
        sample.busy = tb_vif.zeroer_cb.zeroer_busy;
        sample.outstanding = tb_vif.zeroer_cb.zeroer_outstanding;
        sample.wvalid = tb_vif.zeroer_cb.zeroer_wvalid;
        sample.wready = tb_vif.zeroer_cb.zeroer_wready;
        if (tb_vif.zeroer_cb.zeroer_awvalid === 1'b1 && tb_vif.zeroer_cb.zeroer_awready === 1'b1)
          sample.aw++;
        if (tb_vif.zeroer_cb.zeroer_wvalid === 1'b1 &&
            tb_vif.zeroer_cb.zeroer_wready === 1'b1) begin
          sample.w_bytes += $countones(tb_vif.zeroer_cb.zeroer_wstrb);
          if (tb_vif.zeroer_cb.zeroer_wlast === 1'b1) sample.wlast++;
        end
        if (tb_vif.zeroer_cb.zeroer_bvalid === 1'b1 && tb_vif.zeroer_cb.zeroer_bready === 1'b1)
          sample.b++;
        if (arm_w_stall && sample.w_bytes / SmcMemBytes >= accepted_before_stall) begin
          p_sequencer.m_sys_out_slave_seq.enable_backpressure('{"w"}, w_stall);
          stall_start_cycle = clock_cycles;
          arm_w_stall = 0;
        end
      end else begin
        last_irq = 0;
      end
    end
  endtask

  protected function void grade(string id, string label, bit [63:0] observed, bit [63:0] expected,
                                string context_s = "");
    check_evidence(id, label, observed, negative ? expected ^ 64'h1 : expected, context_s);
  endfunction

  protected task read_grade(string id, bit [63:0] addr, bit [63:0] expected, string label);
    bit [63:0] observed;
    mem_read(addr, observed, label);
    grade(id, label, observed, expected, $sformatf("addr=%016h", addr));
  endtask

  protected task wait_sample();
    @(tb_vif.zeroer_cb);
    uvm_wait_for_nba_region();
  endtask

  protected task filter_window(bit restore, bit [63:0] start_value, bit [63:0] end_value,
                               bit [63:0] config_value);
    mem_write(filter_config_addr, 0, "filter disabled");
    mem_write(filter_start_addr, start_value, "filter START");
    mem_write(filter_end_addr, end_value, "filter END");
    mem_write(filter_config_addr, config_value, "filter CONFIG");
    read_grade("CHK-ZEROER-RESET-FILTER", filter_start_addr, start_value, "filter START readback");
    read_grade("CHK-ZEROER-RESET-FILTER", filter_end_addr, end_value, "filter END readback");
    // DATA_BUS_WIDTH has no storage; compare the defined software-writable fields.
    begin
      bit [63:0] observed;
      mem_read(filter_config_addr, observed, "filter CONFIG readback");
      grade("CHK-ZEROER-RESET-FILTER", "filter writable fields", observed & FilterWriteMask,
            config_value & FilterWriteMask, $sformatf("restore=%0b", restore));
    end
  endtask

  protected task wait_reset(bit level);
    bit reached = 0;
    for (int unsigned i = 0; i < ResetBound; i++) begin
      if (tb_vif.rst_primary_smc_clk_n === level && tb_vif.rst_warm_smc_clk_n === level) begin
        reached = 1;
        break;
      end
      wait_smc_cycles(1);
    end
    grade(level ? "CHK-ZEROER-RESET-RELEASED" : "CHK-ZEROER-RESET-ASSERTED",
          "reset levels reached within bound", 64'(reached), 1, $sformatf(
          "requested=%0b primary=%0b warm=%0b bound=%0d",
          level,
          tb_vif.rst_primary_smc_clk_n,
          tb_vif.rst_warm_smc_clk_n,
          ResetBound
          ));
    if (!reached) begin
      `uvm_fatal(get_type_name(),
                 $sformatf("reset transition exceeded bound level=%0b primary=%0b warm=%0b", level,
                           tb_vif.rst_primary_smc_clk_n, tb_vif.rst_warm_smc_clk_n))
    end
  endtask

  protected task wait_idle(string label);
    bit [63:0] status;
    int unsigned polls = 0;
    bit reached = 0;
    for (int unsigned i = 0; i < ResetBound; i++) begin
      mem_read(SmcZeroerCtrlStatusAddr, status, label);
      polls++;
      if ((status & ZEROER_CTRL_CTRL_STATUS_STATUS_MASK) == 0) begin
        reached = 1;
        break;
      end
    end
    grade("CHK-ZEROER-RESET-DONE", label, 64'(reached), 1, $sformatf(
          "status=%016h polls=%0d bound=%0d", status, polls, ResetBound));
    if (!reached) begin
      `uvm_fatal(get_type_name(), {label, " did not complete"})
    end
  endtask

  protected task declare_job(bit [63:0] dest, int unsigned size, bit draining);
    bit [63:0] epoch = observer.current_epoch();
    bit synced = epoch == scoreboard.zeroer_current_epoch() &&
        epoch == p_sequencer.m_zeroer_range_ref_model.current_epoch();
    check_evidence("CHK-ZEROER-RESET-EPOCH", "component reset counters agree", 64'(synced), 1);
    next_command = observer.declare_command(dest, size, int'(draining), GuardBytes);
    mem_write(SmcZeroerDestAddr, dest, "job DEST");
    mem_write(SmcZeroerSizeAddr, 64'(size), "job SIZE");
    read_grade("CHK-ZEROER-RESET-PRE-CSR", SmcZeroerDestAddr, dest, "DEST programmed");
    read_grade("CHK-ZEROER-RESET-PRE-CSR", SmcZeroerSizeAddr, 64'(size), "SIZE programmed");
    mem_write(SmcZeroerCtrlStatusAddr, ZEROER_CTRL_CTRL_STATUS_INT_EN_MASK, "job START");
  endtask

  protected task recover_job(bit draining);
    bit [63:0] dest = fresh_dest;
    bit [7:0] poison[$], observed_bytes[$];
    int unsigned compare_before = scoreboard.compare_count(SmcFeatureZeroerRange);
    int unsigned mismatch_before = scoreboard.mismatch_count(SmcFeatureZeroerRange);
    int unsigned outside_before = observer.outside_count();
    longint unsigned irq_before;
    bit data_ok = 1;
    bit guards_ok = 1;
    bit ready = 0;
    bit [63:0] epoch;
    int unsigned observed_byte_count, completed_bursts;
    string drain_context;
    repeat (recovery_size + 2 * GuardBytes) poison.push_back(8'(random_pattern(8)) | 8'h1);
    p_sequencer.m_sys_out_slave_seq.write_bytes(dest - GuardBytes, poison);
    p_sequencer.m_sys_out_slave_seq.read_bytes(dest - GuardBytes, recovery_size + 2 * GuardBytes,
                                               observed_bytes);
    check_evidence("CHK-ZEROER-RECOVERY-POISON", "poison and guards", 64'(observed_bytes == poison),
                   1, $sformatf("phase=%0b", draining));
    p_sequencer.m_zeroer_range_ref_model.arm_recovery_negative();
    irq_before = sample.irq;
    old_post_reset_irq = irq_before;
    declare_job(dest, recovery_size, draining);
    wait_idle("recovery STATUS");
    for (int unsigned i = 0; i < ResetBound; i++) begin
      if (p_sequencer.m_sys_out_monitor.pending_count() == 0) begin
        ready = 1;
        break;
      end
      wait_smc_cycles(1);
    end
    drain_context = $sformatf(
        "phase=%0b pending=%0d bound=%0d",
        draining,
        p_sequencer.m_sys_out_monitor.pending_count(),
        ResetBound
    );
    grade("CHK-ZEROER-RECOVERY-DRAIN", "SYS_OUT pending drained within bound", 64'(ready), 1,
          drain_context);
    if (!ready) begin
      `uvm_fatal(get_type_name(), "recovery SYS_OUT pending did not drain")
    end
    uvm_wait_for_nba_region();
    observed_byte_count = observer.byte_count(next_command);
    completed_bursts = observer.completed_count(next_command);
    grade("CHK-NONVAC", "recovery observed bytes present", 64'(observed_byte_count > 0), 1,
          $sformatf("observed_bytes=%0d completed_bursts=%0d", observed_byte_count, completed_bursts
          ));
    observer.close_command(next_command);
    epoch = observer.current_epoch();
    ready = 0;
    for (int unsigned i = 0; i < 64; i++) begin
      if (scoreboard.zeroer_expected_seen(epoch, next_command)) begin
        ready = 1;
        break;
      end
      wait_smc_cycles(1);
    end
    grade("CHK-ZEROER-EXPECTED-TIMEOUT", "recovery expected present", 64'(ready), 1);
    check_evidence("CHK-ZEROER-ACCOUNTING", "exact recovery comparison delta",
                   64'(scoreboard.compare_count(SmcFeatureZeroerRange) - compare_before), 1);
    check_evidence("CHK-ZEROER-ACCOUNTING", "recovery mismatch delta",
                   64'(scoreboard.mismatch_count(SmcFeatureZeroerRange) - mismatch_before), 0);
    check_evidence("CHK-ZEROER-ACCOUNTING", "recovery out-of-scope delta",
                   64'(observer.outside_count() - outside_before), 0);
    p_sequencer.m_sys_out_slave_seq.read_bytes(dest - GuardBytes, recovery_size + 2 * GuardBytes,
                                               observed_bytes);
    foreach (observed_bytes[i]) begin
      if (i >= GuardBytes && i < GuardBytes + recovery_size) data_ok &= observed_bytes[i] == 0;
      else guards_ok &= observed_bytes[i] == poison[i];
    end
    grade("CHK-ZEROER-RECOVERY-DATA", "zero recovery payload", 64'(data_ok), 1);
    grade("CHK-ZEROER-RECOVERY-DATA", "recovery guards", 64'(guards_ok), 1);
    grade("CHK-ZEROER-RESET-RESPONDER", "one completed recovery burst from SYS_OUT monitor",
          64'(completed_bursts), 1, $sformatf("phase=%0b dest=%016h", draining, fresh_dest));
    grade("CHK-ZEROER-RECOVERY-IRQ", "one recovery interrupt", sample.irq - irq_before, 1);
  endtask

  protected task reach_phase(bit draining, bit [63:0] size_bytes);
    string phase_name = draining ? "B" : "A";
    bit reached = 0;
    int unsigned stable = 0;
    for (int unsigned i = 0; i < PollBound; i++) begin
      wait_sample();
      if (draining) begin
        if (sample.state === ZeroerStIdle && sample.aw == 1 && sample.wlast == 1 &&
            sample.outstanding === 32'd1 && sample.b == 0) begin
          stable++;
        end else begin
          stable = 0;
        end
        reached = stable >= StableSamples;
      end else begin
        if (sample.state === ZeroerStIssueData && sample.wvalid === 1'b1 &&
            sample.wready === 1'b0 && !arm_w_stall && sample.w_bytes < size_bytes)
          stable++;
        else stable = 0;
        reached = stable >= StableSamples && clock_cycles > stall_start_cycle &&
            clock_cycles-stall_start_cycle + ResetWindowCycles + StallMarginCycles < w_stall;
      end
      if (reached) break;
    end
    grade(draining ? "CHK-ZEROER-RESET-PHASE-B" : "CHK-ZEROER-RESET-PHASE-A",
          "selected phase reached within bound", 64'(reached), 1, $sformatf(
          {
            "phase=%s state=%0h wvalid=%0b wready=%0b aw=%0d w_bytes=%0d ",
            "wlast=%0d b=%0d outstanding=%0d stable=%0d bound=%0d"
          },
          phase_name,
          sample.state,
          sample.wvalid,
          sample.wready,
          sample.aw,
          sample.w_bytes,
          sample.wlast,
          sample.b,
          sample.outstanding,
          stable,
          PollBound
          ));
    if (!reached) begin
      `uvm_fatal(get_type_name(),
                 $sformatf(
                     "phase not reached phase=%s state=%0h aw=%0d w=%0d last=%0d b=%0d out=%0d",
                     phase_name, sample.state, sample.aw, sample.w_bytes, sample.wlast, sample.b,
                     sample.outstanding))
    end
  endtask

  protected task reset_and_release(bit draining, bit [63:0] size_bytes,
                                   longint unsigned responder_before, output sample_t at_reset);
    string phase_name = draining ? "B" : "A";
    time reset_requested, reset_effective;
    sample_t held;
    longint unsigned request_cycle, responder_at_request, responder_after_release;
    // The phase check uses the last pre-reset clocking-block sample.
    wait_sample();
    if (!draining && (clock_cycles <= stall_start_cycle ||
        clock_cycles-stall_start_cycle + ResetWindowCycles + StallMarginCycles >= w_stall)) begin
      `uvm_fatal(get_type_name(), "CSR prechecks consumed the remaining W stall window")
    end
    held = sample;
    request_cycle = clock_cycles;
    responder_at_request = p_sequencer.m_sys_out_slave_seq.write_burst_count();
    grade("CHK-ZEROER-RESET-RESPONDER", "no burst completed before reset request",
          responder_at_request - responder_before, 0);
    reset_requested = $time;
    tb_vif.rst_cool_n <= 0;
    fork
      begin
        fork
          begin
            @(negedge tb_vif.rst_primary_smc_clk_n);
            reset_effective = $time;
            at_reset = sample;
          end
          begin
            wait_smc_cycles(ResetBound);
            grade("CHK-ZEROER-RESET-ASSERTED", "primary reset assertion within bound", 0, 1,
                  $sformatf(
                  "phase=%s primary=%0b warm=%0b request_cycle=%0d cycle=%0d bound=%0d",
                  phase_name,
                  tb_vif.rst_primary_smc_clk_n,
                  tb_vif.rst_warm_smc_clk_n,
                  request_cycle,
                  clock_cycles,
                  ResetBound
                  ));
            `uvm_fatal(get_type_name(), "primary reset assertion exceeded bound")
          end
        join_any
        disable fork;
      end
    join
    `uvm_info(get_type_name(),
              $sformatf(
                  {"ZEROER-RESET-CONTEXT phase=%s pass=%0d request=%0t effective=%0t sample=%0t ",
                   "latency_smc_equivalent=%0f state=%0h busy=%0b aw=%0d w_bytes=%0d last=%0d ",
                   "b=%0d outstanding=%0d w_delta=%0d responder_delta=%0d"}, phase_name,
                    loop_index, reset_requested, reset_effective, at_reset.sampled_at,
                    real'(reset_effective - reset_requested) / (tb_vif.smc_clk_period_ns * 1ns),
                    at_reset.state, at_reset.busy, at_reset.aw, at_reset.w_bytes, at_reset.wlast,
                    at_reset.b, at_reset.outstanding, at_reset.w_bytes - held.w_bytes,
                    p_sequencer.m_sys_out_slave_seq.write_burst_count() - responder_before),
              UVM_LOW)
    grade(draining ? "CHK-ZEROER-RESET-PHASE-B" : "CHK-ZEROER-RESET-PHASE-A",
          "phase at effective reset",
          64'(draining ?
                   (at_reset.state === ZeroerStIdle && at_reset.outstanding === 32'd1 &&
                    at_reset.aw == 1 && at_reset.wlast == 1 && at_reset.b == 0) :
                   (at_reset.state === ZeroerStIssueData && at_reset.wvalid === 1'b1 &&
                    at_reset.w_bytes == held.w_bytes && at_reset.w_bytes < size_bytes)),
          1, $sformatf(
          "phase=%s aw=%0d w_bytes=%0d b=%0d out=%0d",
          phase_name,
          at_reset.aw,
          at_reset.w_bytes,
          at_reset.b,
          at_reset.outstanding
          ));
    if (!draining) begin
      grade("CHK-ZEROER-RESET-PHASE-A", "reset fits the reserved stall budget",
            64'(at_reset.cycle - request_cycle <= ResetWindowCycles), 1, $sformatf(
            "phase=%s sampled_smc_edges=%0d bound=%0d",
            phase_name,
            at_reset.cycle - request_cycle,
            ResetWindowCycles
            ));
    end
    wait_reset(0);
    p_sequencer.m_sys_out_slave_seq.disable_backpressure();
    tb_vif.output_axi_resp_hold <= 0;
    sample = '{default: 0};
    fork
      begin
        @(posedge tb_vif.rst_primary_smc_clk_n);
        responder_after_release = p_sequencer.m_sys_out_slave_seq.write_burst_count();
      end
      begin
        tb_vif.rst_cool_n <= 1;
        wait_reset(1);
      end
    join
    wait_fuse_sense_done();
    grade("CHK-ZEROER-RESET-RESPONDER", "no completed burst across reset",
          responder_after_release - responder_at_request, 0);
  endtask

  protected task run_interrupt_case(bit draining);
    string phase_name = draining ? "B" : "A";
    bit [63:0] destination;
    bit [63:0] size_bytes;
    bit [63:0] word;
    sample_t at_reset;
    longint unsigned responder_before;
    bit [7:0] poison[$], old_bytes[$];
    int unsigned zeros = 0, nonzeros = 0, changed_guard = 0;
    int unsigned completed_old, bytes_old;
    longint unsigned old_irq;

    destination = region_base + (draining ? InterruptedOffsetB : InterruptedOffsetA) +
        64'(SmcMemBytes * (random_pattern(16) % (MaxOffsetBytes / SmcMemBytes + 1)));
    size_bytes = draining ? 64'(SmcMemBytes * (1 + random_pattern(16) % 256)) :
        64'(MinInterruptedBytes + SmcMemBytes * (random_pattern(16) %
            ((MaxInterruptedBytes - MinInterruptedBytes) / SmcMemBytes + 1)));
    recovery_size = SmcMemBytes * (1 + int'(random_pattern(16) % (MaxRecoveryBytes / SmcMemBytes)));
    fresh_dest = region_base + (draining ? RecoveryOffsetB : RecoveryOffsetA) +
        64'(SmcMemBytes * (random_pattern(16) % (MaxOffsetBytes / SmcMemBytes + 1)));
    accepted_before_stall = 8 + int'(random_pattern(8) % 25);
    w_stall = test_cfg.zeroer_reset_w_stall != 0 ? test_cfg.zeroer_reset_w_stall :
        MinStallCycles + int'(random_pattern(16) % (MaxStallCycles - MinStallCycles + 1));
    old_completed_before = observer.old_completed_count(draining);
    old_bytes_before = observer.old_byte_count(draining);
    `uvm_info(get_type_name(),
              $sformatf(
                  {"ZEROER-RESET-DRAW pass=%0d phase=%s dest=%016h size=%0d accept_threshold=%0d ",
                   "stall=%0d recovery_dest=%016h recovery_size=%0d"}, loop_index, phase_name,
                    destination, size_bytes, accepted_before_stall, w_stall, fresh_dest,
                    recovery_size), UVM_LOW)
    repeat (int'(size_bytes) + 2 * GuardBytes) poison.push_back(8'hA5);
    p_sequencer.m_sys_out_slave_seq.write_bytes(destination - GuardBytes, poison);
    wait_fuse_sense_done();
    filter_window(0, OutputBase, OutputBase + 64'h3FFFFF, PassAll);
    tb_vif.output_axi_resp_hold <= draining;
    arm_w_stall = !draining;
    sample = '{default:0};
    responder_before = p_sequencer.m_sys_out_slave_seq.write_burst_count();
    old_irq = sample.irq;
    declare_job(destination, int'(size_bytes), draining);
    reach_phase(draining, size_bytes);
    read_grade("CHK-ZEROER-RESET-PRE-CSR", SmcZeroerDestAddr, destination,
               "DEST immediately before reset");
    read_grade("CHK-ZEROER-RESET-PRE-CSR", SmcZeroerSizeAddr, size_bytes,
               "SIZE immediately before reset");
    mem_read(SmcZeroerCtrlStatusAddr, word, "pre-reset CTRL_STATUS");
    grade("CHK-ZEROER-RESET-PRE-CSR", "INT_EN armed before reset",
          word & ZEROER_CTRL_CTRL_STATUS_INT_EN_MASK, ZEROER_CTRL_CTRL_STATUS_INT_EN_MASK);
    grade("CHK-ZEROER-RESET-PRE-CSR", "STATUS busy before reset",
          word & ZEROER_CTRL_CTRL_STATUS_STATUS_MASK, ZEROER_CTRL_CTRL_STATUS_STATUS_MASK);
    reset_and_release(draining, size_bytes, responder_before, at_reset);
    read_grade("CHK-ZEROER-RESET-CSR", SmcZeroerDestAddr, ZEROER_CTRL_DEST_ADDR_REG_DEFAULT,
               "DEST reset");
    read_grade("CHK-ZEROER-RESET-CSR", SmcZeroerSizeAddr, ZEROER_CTRL_SIZE_REG_DEFAULT,
               "SIZE reset");
    read_grade("CHK-ZEROER-RESET-CSR", SmcZeroerCtrlStatusAddr, ZEROER_CTRL_CTRL_STATUS_REG_DEFAULT,
               "CTRL_STATUS reset");
    mem_read(SmcZeroerCtrlStatusAddr, word, "post-reset CTRL_STATUS observation");
    `uvm_info(get_type_name(),
              $sformatf("ZEROER-RESET-CONTEXT-RELEASE phase=%s status=%016h responder_delta=%0d",
                        phase_name, word,
                        p_sequencer.m_sys_out_slave_seq.write_burst_count() - responder_before),
              UVM_LOW)
    filter_window(0, OutputBase, OutputBase + 64'h3FFFFF, PassAll);
    recover_job(draining);
    p_sequencer.m_sys_out_slave_seq.read_bytes(destination - GuardBytes,
                                               int'(size_bytes) + 2 * GuardBytes, old_bytes);
    foreach (old_bytes[i]) begin
      if (i < GuardBytes || i >= GuardBytes + int'(size_bytes))
        changed_guard += int'(old_bytes[i] != poison[i]);
      else if (old_bytes[i] == 0) zeros++;
      else nonzeros++;
    end
    `uvm_info(get_type_name(),
              $sformatf(
                  "OBS-BLOCKED CHK-ZEROER-RESET-STALE-REQ phase=%s reason=reset contract is open",
                  phase_name), UVM_LOW)
    completed_old = observer.old_completed_count(draining) - old_completed_before;
    bytes_old = observer.old_byte_count(draining) - old_bytes_before;
    `uvm_info(
        get_type_name(),
        $sformatf(
            "OBS-ZEROER-RESET-STALE-REQ: phase=%s epoch=%0d completed_bursts=%0d enabled_bytes=%0d",
            phase_name, observer.current_epoch(), completed_old, bytes_old), UVM_LOW)
    `uvm_info(
        get_type_name(),
        $sformatf(
            "OBS-BLOCKED CHK-ZEROER-RESET-UNEXPLAINED-B phase=%s reason=reset contract is open",
            phase_name), UVM_LOW)
    `uvm_info(
        get_type_name(),
        $sformatf(
            "OBS-ZEROER-RESET-UNEXPLAINED-B: phase=%s excess_b=%0d engine_aw=%0d engine_b=%0d",
            phase_name, sample.b > sample.aw ? sample.b - sample.aw : 0, sample.aw, sample.b),
        UVM_LOW)
    `uvm_info(
        get_type_name(),
        $sformatf(
            "OBS-BLOCKED CHK-ZEROER-RESET-OLD-DATA phase=%s reason=interrupted data is unspecified",
            phase_name), UVM_LOW)
    `uvm_info(get_type_name(),
              $sformatf("OBS-ZEROER-RESET-OLD-DATA: phase=%s zero_bytes=%0d other_bytes=%0d",
                        phase_name, zeros, nonzeros), UVM_LOW)
    `uvm_info(
        get_type_name(),
        $sformatf(
            "OBS-BLOCKED CHK-ZEROER-RESET-OLD-GUARD phase=%s reason=reset guard contract is open",
            phase_name), UVM_LOW)
    `uvm_info(get_type_name(), $sformatf("OBS-ZEROER-RESET-OLD-GUARD: phase=%s changed_bytes=%0d",
                                         phase_name, changed_guard), UVM_LOW)
    `uvm_info(get_type_name(),
              $sformatf(
                  "OBS-BLOCKED CHK-ZEROER-RESET-OLD-IRQ phase=%s reason=abort IRQ is unspecified",
                  phase_name), UVM_LOW)
    `uvm_info(get_type_name(),
              $sformatf("OBS-ZEROER-RESET-OLD-IRQ: phase=%s pre_reset=%0d post_reset=%0d",
                        phase_name, at_reset.irq - old_irq, old_post_reset_irq), UVM_LOW)
  endtask

  virtual task body();
    bit [63:0] saved_start, saved_end, saved_config;
    bit [63:0] epoch_before;
    int unsigned cool_before, cold_before;
    bit first_draining;
    seed_scenario_rng();
    negative = env_cfg.zeroer_reset_sequence_negative;
    if (negative)
      `uvm_info(get_type_name(), "NEGATIVE VALIDATION: invert Zeroer DUT expectations", UVM_LOW)
    attach_evidence(
        '{ChkFuseSense, ChkMemResp, "CHK-ZEROER-RESET-FILTER", "CHK-ZEROER-RESET-PRE-CSR",
        "CHK-ZEROER-RESET-CSR", "CHK-ZEROER-RESET-PHASE-A", "CHK-ZEROER-RESET-PHASE-B",
        "CHK-ZEROER-RECOVERY-DATA", "CHK-ZEROER-RECOVERY-IRQ", "CHK-ZEROER-ACCOUNTING",
        "CHK-ZEROER-RESET-RESPONDER", "CHK-ZEROER-EXPECTED-TIMEOUT", "CHK-ZEROER-RECOVERY-POISON",
        "CHK-ZEROER-RESET-DONE", "CHK-ZEROER-RESET-EPOCH", "CHK-ZEROER-RESET-ASSERTED",
        "CHK-ZEROER-RESET-RELEASED", "CHK-ZEROER-RECOVERY-DRAIN", "CHK-NONVAC"});
    observer = p_sequencer.m_zeroer_burst_observer;
    if (observer == null) `uvm_fatal(get_type_name(), "Zeroer feature was not configured")
    filter_start_addr =
        smc_top_addrmap_pkg::
        SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR(0);
    filter_end_addr =
        smc_top_addrmap_pkg::
        SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR(0);
    filter_config_addr =
        smc_top_addrmap_pkg::
        SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0);
    region_base = OutputBase + 64'(loop_index) * PassStride;
    if (region_base + PassExtent > env_cfg.sys_out_mem_bytes ||
        region_base + PassExtent > OutputBase + 64'h400000) begin
      `uvm_fatal(get_type_name(), "Zeroer pass window exceeds filter or backing memory")
    end
    if (test_cfg.zeroer_reset_w_stall != 0 &&
        (test_cfg.zeroer_reset_w_stall < MinStallCycles ||
         test_cfg.zeroer_reset_w_stall > MaxStallCycles))
      `uvm_fatal(get_type_name(), "W stall override must be within 2048..6144 cycles")
    wait_fuse_sense_done();
    epoch_before = observer.current_epoch();
    cool_before = tb_vif.cool_rst_assert_count;
    cold_before = tb_vif.cold_rst_assert_count;
    mem_read(filter_start_addr, saved_start, "saved filter START");
    mem_read(filter_end_addr, saved_end, "saved filter END");
    mem_read(filter_config_addr, saved_config, "saved filter CONFIG");
    stop_sampling = 0;
    sample = '{default:0};
    fork
      sample_port();
    join_none
    first_draining = bit'(random_pattern(1));
    run_interrupt_case(first_draining);
    run_interrupt_case(!first_draining);
    filter_window(1, saved_start, saved_end, saved_config);
    stop_sampling = 1;
    wait_sample();
    check_evidence("CHK-ZEROER-ACCOUNTING", "no pending command or unmatched sample",
                   scoreboard.zeroer_pending_count(), 0);
    check_evidence("CHK-ZEROER-ACCOUNTING", "phase A interrupted commands",
                   scoreboard.zeroer_interrupted_commands(0), 64'(loop_index + 1));
    check_evidence("CHK-ZEROER-ACCOUNTING", "phase B interrupted commands",
                   scoreboard.zeroer_interrupted_commands(1), 64'(loop_index + 1));
    check_evidence("CHK-ZEROER-RESET-EPOCH", "two cool resets and no cold reset",
                   64'(observer.current_epoch() == smc_csr_reset_epoch(cold_before, cool_before + 2
                   ) && tb_vif.cool_rst_assert_count == cool_before + 2 &&
                       tb_vif.cold_rst_assert_count == cold_before),
                   1, $sformatf(
                   "epoch=%0d->%0d cool=%0d->%0d cold=%0d->%0d",
                   epoch_before,
                   observer.current_epoch(),
                   cool_before,
                   tb_vif.cool_rst_assert_count,
                   cold_before,
                   tb_vif.cold_rst_assert_count
                   ));
    finalize_evidence();
  endtask
endclass : smc_zeroer_reset_during_operation_test_seq
