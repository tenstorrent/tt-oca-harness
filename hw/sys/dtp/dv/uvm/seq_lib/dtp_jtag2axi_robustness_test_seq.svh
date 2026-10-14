// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross-bridge JTAG2AXI robustness scenarios for the DTP SV-UVM flow — the
// SV analogue of the cocotb dtp_jtag2axi_robustness_test_seq. One
// parameterized sequence, selected by `scenario`, iterating ALL THREE
// JTAG2AXI bridges (smc_axi, smc_otp, sep_otp) in one pass:
//
//   * backpressure_aw_before_w — WREADY stalled behind an accepted AW on
//     each bridge: the write completes, reports SUCCESS, produced a real
//     AW request pulse, and the memory matches the stimulus intent; the
//     port's stall counters show the W stall and no AW stall cycle;
//   * backpressure_long_stall — AW+W stalls sized in status-poll units so
//     the bridge reports BUSY_OR_FULL before settling, a stalled-AR read
//     of a preloaded value, then zero-strobe and memory-window-boundary
//     corner writes once the stalls are cleared; the port's stall counters
//     show every stalled channel's stall;
//   * backpressure_abort_at_data_w / cdc_clear_abort_narrow_reset_mid_xaction
//     — a write held on the W (or AW) channel by a READY stall that is
//     released only after a system-reset pulse, so the reset lands while
//     the bridge FSM is observed mid-flight through dtp_tb_if; the FSM's
//     return to IDLE, the CDC's TCK-side clear, the absence of an escaped
//     write, and the recovery status are recorded per bridge and the pass
//     is judged once every bridge has left its evidence; the narrow-reset
//     scenario then lands a reset with the TAP holding Update-DR of a
//     SINGLE_OP, so the CDC's clear returns the state machine from its
//     address state with no request in the crossing and SINGLE_OP reads
//     DECERR, and then holds a SINGLE_OP read or write on the fabric by a READY
//     stall across a TCK-side clear (TRST, or a TMS walk into
//     Test-Logic-Reset), released inside the clear, after it, after it with
//     a request of the new session queued behind it, or a swept number of
//     system cycles around the TRST assertion; the held request lands
//     exactly once, its response never reaches the JTAG side, and the next
//     operation reports its own response;
//   * cdc_clear_abort_back_to_back_reset — per bridge, a system reset placed
//     in a seeded phase of the ACLK-side clear sequence a reset with TCK
//     idle restarted (the phase read through dtp_tb_if, the pulse deposited
//     on the following system clock edge), then two adjacent reset pulses
//     with seeded spacing and a recovery write and read; after the bridges,
//     TRST in the one TCK cycle the TCK-side four-phase receivers wait for
//     their isolate acknowledge after a system reset, and a system reset in
//     the one system clock cycle the ACLK-side receivers wait after TRST,
//     each followed by the clear, an idle status poll and a recovery write
//     and read on every bridge;
//   * decode_error_decerr_{write,read} / decode_error_mixed — one-shot
//     DECERR injections per bridge (the DTP boundary has no address
//     decoder: each target's responder injects the response) with OKAY
//     recovery accesses; the errored write leaves its slot unchanged and
//     the errored read's SINGLE_OP capture returns the errored beat's
//     RDATA (CHK-J2A-ERR-RDATA); the mixed flavor brackets a responder-
//     injected DECERR read and a DECERR write to one slot between a good
//     write and its read-back at a neighbouring address.
//     Credits are armed direction-exact so every armed DECERR is consumed
//     by a real bus response (CHK-AXI-NONVAC + the scoreboard's
//     check_phase drain);
//   * series_corner_all_bridges — incrementing and fixed-address write
//     series with their SERIES_CTRL address captures, one faulted beat whose
//     status holds until SERIES_CTRL.reset, and the three bridges' beats
//     interleaved; then every entry of each bridge's CDC FIFOs filled at
//     least twice in one TAP session by checked writes and reads of seeded
//     addresses, sizes and data, one SLVERR or DECERR per entry, a TAP reset
//     and a system reset with every entry holding its payload, the
//     SINGLE_OP status back at its reset value, and a recovery write and
//     read on every bridge.
//
// Every random choice draws from the per-pass seeded stream and is logged
// with its loop context for replay. select_target() (the family layer)
// points the base-class handles at one bridge, so every inherited helper
// acts on the bridge under test. The body always clears injections and
// backpressure on all bridges and re-enables debug on exit.
//
// The back-to-back reset legs time each system-reset deposit from dtp_tb_if
// clock edges and CDC phase observables, and start a deposit that follows
// TRST once the TRST operation returns, with no TCK edge in between; a
// phase watcher that never fires is killed once the TCK steps it races
// have run.

class dtp_jtag2axi_robustness_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_robustness_test_seq)

  // Scenario selection (set by the test before start()).
  string scenario = "backpressure_aw_before_w";

  // Robustness address plan (mirrors the cocotb layout): 0x400-spaced
  // per-operation slots off one base, inside the 64 KiB responder window;
  // series streams in a disjoint window.
  localparam bit [63:0] RobustBase = 64'h3800;
  localparam bit [63:0] SeriesBase = 64'h5000;

  function new(string name = "dtp_jtag2axi_robustness_test_seq");
    super.new(name);
  endfunction

  protected function bit [63:0] robust_addr(dtp_j2a_target_t t, int unsigned idx);
    return RobustBase + idx * 64'h400 + t.beat_bytes;
  endfunction

  // One status-poll scan's duration in system-clock cycles: the DR shift
  // plus the ~8 TCK the VIP spends navigating RTI -> Shift-DR -> RTI per
  // poll. An overestimate silently pushes the settle point past the
  // MaxStatusPolls completion bound. The TCK and system periods are drawn
  // independently, so the scan is rounded up once: rounding each TCK up to
  // whole system cycles inflates the scan by up to 2x when the TCK period
  // is just above a multiple of the system period.
  protected function int unsigned poll_scan_sys_cycles(dtp_j2a_target_t t);
    return ((single_op_len(t) + 8) * test_cfg.tck_period_ns + tb_vif.clk_period_ns - 1) /
        tb_vif.clk_period_ns;
  endfunction

  // READY stall sized in status-poll units, so the operation stays
  // outstanding into the polls and the bridge reports BUSY_OR_FULL before
  // the settled status. The responder applies an AW+W stall's two channel
  // patterns back to back and the AW pattern's phase adds up to one more
  // stall window, so the settle point lands near 2*scans polls — callers
  // cap scans at 5 so completion stays inside DtpJ2aMaxStatusPolls.
  protected function int unsigned stall_beyond_polls(dtp_j2a_target_t t, int unsigned scans);
    return scans * poll_scan_sys_cycles(t) + $urandom_range(64, 16);
  endfunction

  // The READY stall seen on the port across one operation
  // (CHK-J2A-STALL-HOLD): a channel in `stalled` held its VALID against a
  // low READY for at least one cycle; any other channel of the operation was
  // accepted on its first VALID cycle. The tb_top stall counters advance only
  // while axi_sva_en is set, so a counted cycle is one the port's
  // ocah_axi_sva stability rules evaluated.
  protected function void judge_stall_hold(string channel, string stalled[$],
                                           int unsigned count_before, int unsigned count_after,
                                           string context_s);
    int unsigned delta = count_after - count_before;
    string hits[$] = stalled.find(c) with (c == channel);
    string detail = $sformatf("%s_stall_delta=%0d", channel, delta);
    string name;
    if (hits.size() > 0) begin
      name = {context_s, ".", channel, "_stall_hold"};
      void'(record_abort_check(DtpJ2aStallHoldCheckId, name, 64'(delta > 0), 64'd1, detail));
    end else begin
      name = {context_s, ".", channel, "_accepted_unstalled"};
      void'(record_abort_check(DtpJ2aStallHoldCheckId, name, 64'(delta), 64'd0, detail));
    end
  endfunction

  // Backpressured checked single write. The READY stall outlasts the first
  // status poll, so the bridge is observed on the stalled path before the
  // write settles at SUCCESS with the memory matching the stimulus intent
  // and the request on the bus; the port's stall counters show the stall on
  // exactly the write channels in `channels`, W judged only when `judge_w`
  // is set.
  protected task write_with_backpressure(dtp_j2a_target_t t, string channels[$],
                                         int unsigned stall_cycles, string context_s,
                                         bit judge_w = 1'b1);
    dtp_j2a_status_e op_status;
    bit [63:0] rdata;
    int unsigned aw0, w0, ar0;
    int unsigned aw_stall0, w_stall0, ar_stall0, aw_stall1, w_stall1, ar_stall1;
    int unsigned size = t.default_size;
    bit [63:0]   addr = robust_addr(t, operation_count + 1);
    bit [63:0]   data = (64'h1020_3040_5060_7080 ^ addr) & data_mask(size);
    configure_target_backpressure(t, channels, stall_cycles);
    sample_activity(t, aw0, w0, ar0);
    sample_stall(t, aw_stall0, w_stall0, ar_stall0);
    issue_single(t, DTP_J2A_OP_WRITE, addr, data, full_wstrb(size), size, .use_default_size(1'b0));
    observe_stall(t, 1'b0, context_s);
    poll_single(t, op_status, rdata, context_s);
    check_status(t, {context_s, ".status"}, op_status, DTP_J2A_SUCCESS);
    status = op_status;
    check_target_memory(t, addr, data, size, context_s);
    expect_request_activity(t, 1'b0, aw0, context_s);
    sample_stall(t, aw_stall1, w_stall1, ar_stall1);
    judge_stall_hold("aw", channels, aw_stall0, aw_stall1, context_s);
    if (judge_w) judge_stall_hold("w", channels, w_stall0, w_stall1, context_s);
    clear_target_backpressure(t);
    operation_count++;
  endtask

  // Reset-abort stimulus: the READY stall outlasts everything and is released
  // after the reset, so the write sits on the bus throughout the reset pulse.
  localparam int unsigned AbortHoldCycles = 100000;
  // TCK cycles for the bridge FSM to leave IDLE after the SINGLE_OP
  // Update-DR, and to return to IDLE after the reset.
  localparam int unsigned AbortMidFlightTck = 64;
  localparam int unsigned AbortSettleTck = 128;

  // Checked single write whose first status capture follows its completion:
  // TCK steps in Run-Test/Idle until the bridge drops its pending flag, so
  // the first capture already reads the settled status.
  protected task write_polled_after_completion(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                               string context_s);
    dtp_j2a_status_e op_status;
    bit [63:0] rdata;
    int unsigned size = t.default_size;
    bit [63:0] masked = data & data_mask(size);
    issue_single(t, DTP_J2A_OP_WRITE, addr, masked, full_wstrb(size), size,
                 .use_default_size(1'b0));
    for (int unsigned i = 0; i < AbortSettleTck && bridge_op_pending(t); i++) step(1'b0);
    poll_single(t, op_status, rdata, context_s);
    expect_bus_request(t, 1'b0, addr, size, masked, full_wstrb(size), context_s);
    check_status(t, {context_s, ".status"}, op_status, DTP_J2A_SUCCESS);
    check_target_memory(t, addr, masked, size, context_s);
    status = op_status;
    operation_count++;
  endtask

  // Backpressured checked single read of a backdoor-preloaded value, the
  // bridge observed on the stalled read path first.
  protected task read_with_backpressure(dtp_j2a_target_t t, string channels[$],
                                        int unsigned stall_cycles, string context_s);
    dtp_j2a_status_e op_status;
    bit [63:0] rdata;
    int unsigned aw0, w0, ar0;
    int unsigned aw_stall0, w_stall0, ar_stall0, aw_stall1, w_stall1, ar_stall1;
    int unsigned size = t.default_size;
    bit [63:0]   addr = robust_addr(t, operation_count + 1);
    bit [63:0]   data = (64'hABCD_EF01_2345_6789 ^ addr) & data_mask(size);
    write_target_mem_int(t, addr, data, size);
    configure_target_backpressure(t, channels, stall_cycles);
    sample_activity(t, aw0, w0, ar0);
    sample_stall(t, aw_stall0, w_stall0, ar_stall0);
    issue_single(t, DTP_J2A_OP_READ, addr, '0, '0, size, .use_default_size(1'b0));
    observe_stall(t, 1'b1, context_s);
    poll_single(t, op_status, rdata, context_s);
    check_status(t, {context_s, ".status"}, op_status, DTP_J2A_SUCCESS);
    status = op_status;
    check_returned_rdata(t, rdata & data_mask(size), data, $sformatf(
                         "%s.rdata addr=0x%0h", context_s, addr));
    expect_request_activity(t, 1'b1, ar0, context_s);
    sample_stall(t, aw_stall1, w_stall1, ar_stall1);
    judge_stall_hold("ar", channels, ar_stall0, ar_stall1, context_s);
    clear_target_backpressure(t);
    operation_count++;
  endtask

  // ------------------------------------------------------------------
  // Scenario runners (each iterates all three bridges).
  // ------------------------------------------------------------------

  protected task run_backpressure_aw_before_w();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      // WREADY held past the first status poll (seeded margin): the bridge
      // is observed waiting on the write path while AW is already accepted.
      int unsigned stall = stall_beyond_polls(t, 2);
      log_iteration(i + 1, NumTargets, $sformatf("target=%s WREADY stall=%0d", t.name, stall));
      write_with_backpressure(t, '{"w"}, stall, $sformatf("aw_before_w.%s", t.name));
    end
  endtask

  protected task run_backpressure_long_stall();
    int unsigned order[NumTargets] = '{0, 1, 2};
    // Seeded target-order shuffle: each loop stresses a different
    // bridge ordering.
    order.shuffle();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(order[i]);
      dtp_j2a_status_e op_status;
      int unsigned size = t.default_size;
      // A stall outlasting the scan cadence keeps the op outstanding into
      // the status polls, so the bridge reports BUSY_OR_FULL before the
      // settled status: the AW+W stall of five scans settles in the
      // long-wait poll class, the AW-only and AR stalls of two scans in the
      // short-wait class.
      int unsigned stall = stall_beyond_polls(t, 5);
      bit [63:0] boundary_addr = 64'(DtpJ2aTargetMemBytes) - size_bytes(size);
      bit [63:0] boundary_data = rand_data(t) & data_mask(size);
      log_iteration(i + 1, NumTargets, $sformatf("target=%s stall=%0d", t.name, stall));
      write_with_backpressure(t, '{"aw", "w"}, stall, $sformatf("long_stall.write.%s", t.name));
      // AW held alone, the responder taking the W beat during the AW stall
      // (W before AW); only AW is judged.
      arm_target_w_before_aw(t);
      write_with_backpressure(t, '{"aw"}, stall_beyond_polls(t, 2), $sformatf(
                              "long_stall.aw_only.%s", t.name), 1'b0);
      read_with_backpressure(t, '{"ar"}, stall_beyond_polls(t, 2), $sformatf(
                             "long_stall.read.%s", t.name));
      write_polled_after_completion(t, robust_addr(t, i + 45), rand_data(t), $sformatf(
                                    "long_stall.settled.%s", t.name));
      // Zero-strobe and window-boundary singles: legal corner
      // operands exercised once the stalls are cleared.
      write_target_single_and_check(t, robust_addr(t, i + 41), 64'($urandom), op_status, size,
                                    8'h00, $sformatf("long_stall.wstrb_none.%s", t.name));
      write_target_single_and_check(t, boundary_addr, boundary_data, op_status, size, full_wstrb(
                                    size), $sformatf("long_stall.boundary.%s", t.name));
      status = op_status;
    end
  endtask

  // SINGLE_OP captures within which the status leaves BUSY_OR_FULL after the
  // reset; one capture is one Capture-DR from Run-Test/Idle, the instruction
  // loaded once and no idle TCK after it.
  localparam int unsigned AbortRecoveryPolls = 8;
  // TCK cycles after a reset pulse for the CDC controller to run its
  // TCK-side isolate-and-clear on an idle bridge.
  localparam int unsigned AbortCdcClearTck = 32;

  // Record one judgement on the target's evidence recorder without stopping
  // the pass, so every bridge leaves evidence.
  protected function bit record_abort_check(string check_id, string name, bit [63:0] observed,
                                            bit [63:0] expected, string context_s);
    return axi_evidence.expect_equal(check_id, observed, expected, {name, " ", context_s});
  endfunction

  // CHK-J2A-CDC-CLEAR: the bridge's TCK side ran its isolate-and-clear.
  protected function bit record_cdc_clear(dtp_j2a_target_t t, string name, string context_s);
    return
        record_abort_check(DtpJ2aCdcClearCheckId, name, 64'(cdc_clear_seen(t)), 64'd1, context_s);
  endfunction

  // The READY stall seen from the DUT: the bridge's state machine has left
  // idle onto the stalled path (CHK-J2A-STALL-FSM) and the first status poll
  // reads BUSY_OR_FULL (CHK-J2A-STALL-BUSY). Both need the stall to outlast
  // the poll, so callers size it with stall_beyond_polls().
  protected task observe_stall(dtp_j2a_target_t t, bit is_read, string context_s);
    bit idle;
    dtp_j2a_status_e first;
    bit [63:0] rdata;
    bit on_path;
    wait_bridge_fsm(t, 1'b0, AbortMidFlightTck, idle);
    on_path = bridge_fsm_on_path(t, is_read);
    void'(record_abort_check(
        DtpJ2aStallFsmCheckId,
        {
          context_s, ".stall_fsm"
        },
        64'(on_path),
        64'd1,
        $sformatf(
            "idle=%0d under the %s READY stall", idle, is_read ? "read" : "write")
    ));
    single_status_once(t, first, rdata);
    void'(record_abort_check(
        DtpJ2aStallBusyCheckId,
        {
          context_s, ".stall_busy"
        },
        64'(first),
        64'(DTP_J2A_BUSY_OR_FULL),
        "first status poll under the READY stall"
    ));
  endtask

  // Pulse the system reset again on an idle bridge whose first clear has
  // completed, and record its CDC clear.
  protected task second_reset(dtp_j2a_target_t t, int unsigned reset_cycles, string context_s);
    repeat (AbortSettleTck) step(1'b0);
    clear_cdc_clear_seen();
    pulse_system_reset(reset_cycles);
    repeat (AbortCdcClearTck) step(1'b0);
    void'(record_cdc_clear(
        t, {context_s, ".second_cdc_clear"}, "tck-side isolate-and-clear after the second reset"
    ));
  endtask

  // System reset while the bridge is observed mid-flight on a held write; a
  // non-zero `second_reset_cycles` pulses the reset again once the first
  // clear has completed, before the status is polled. `recovered` is 1 when
  // the bridge reported the discarded write as DECERR afterwards and the
  // recovery write ran.
  protected task reset_abort_mid_flight(dtp_j2a_target_t t, string channel,
                                        int unsigned reset_cycles, int unsigned addr_idx,
                                        bit [63:0] recovery_xor, string context_s,
                                        int unsigned second_reset_cycles, output bit recovered);
    int unsigned size = t.default_size;
    bit [63:0] addr = robust_addr(t, addr_idx);
    bit [63:0] data = rand_data(t) & data_mask(size);
    bit [63:0] prior_word = read_target_mem_int(t, addr, size);
    bit idle;
    dtp_j2a_status_e st;
    bit [63:0] rdata;
    bit mid_flight;
    int unsigned aw0, w0, ar0;
    bit on_bus;
    configure_target_backpressure(t, '{channel}, AbortHoldCycles);
    sample_stall(t, aw0, w0, ar0);
    // The reset aborts this write, so it arms no intent; CHK-J2A-ABORT-ESCAPE
    // judges its slot.
    issue_single(t, DTP_J2A_OP_WRITE, addr, data, full_wstrb(size), size, .use_default_size(1'b0),
                 .arm_intent(1'b0));
    wait_bridge_fsm(t, 1'b0, AbortMidFlightTck, idle);
    wait_held_on_bus(t, channel, (channel == "w") ? w0 : aw0, AbortMidFlightTck, on_bus);
    mid_flight = !idle && bridge_op_pending(t) && on_bus;
    void'(record_abort_check(
        DtpJ2aAbortMidFlightCheckId,
        {
          context_s, ".mid_flight"
        },
        64'(mid_flight),
        64'd1,
        $sformatf(
            "idle=%0d write_path=%0d %s_held=%0d",
            idle,
            bridge_fsm_on_path(
                t, 1'b0
            ),
            channel,
            on_bus)
    ));
    clear_cdc_clear_seen();
    pulse_system_reset(reset_cycles);
    clear_target_backpressure(t);
    wait_bridge_fsm(t, 1'b1, AbortSettleTck, idle);
    void'(record_abort_check(
        DtpJ2aAbortFsmCheckId,
        {
          context_s, ".fsm_idle"
        },
        64'(idle),
        64'd1,
        "after the mid-flight reset"
    ));
    void'(record_cdc_clear(t, {context_s, ".cdc_clear"}, "tck-side isolate-and-clear"));
    void'(record_abort_check(
        DtpJ2aAbortEscapeCheckId,
        {
          context_s, ".no_escape"
        },
        read_target_mem_int(
            t, addr, size
        ),
        prior_word,
        $sformatf(
            "addr=0x%0h", addr)
    ));
    if (second_reset_cycles != 0) second_reset(t, second_reset_cycles, context_s);
    poll_single(t, st, rdata, {context_s, ".recovery"}, AbortRecoveryPolls);
    recovered = record_abort_check(
        DtpJ2aAbortRecoveryCheckId,
        {context_s, ".recovery_status"},
        64'(st),
        64'(DTP_J2A_DECERR),
        $sformatf(
            "status=%s max_captures=%0d after the mid-flight reset", st.name(), AbortRecoveryPolls)
    );
    status = st;
    if (recovered) begin
      recover_target(t, addr + 64'h200, data ^ recovery_xor, 1'b0, context_s, status);
      // A write the bridge holds across the reset lands only once it is
      // issued, which can follow the first sample, so the slot is judged
      // again.
      void'(record_abort_check(
          DtpJ2aAbortEscapeCheckId,
          {
            context_s, ".no_escape_after_recovery"
          },
          read_target_mem_int(
              t, addr, size
          ),
          prior_word,
          $sformatf(
              "addr=0x%0h", addr)
      ));
    end
    operation_count++;
  endtask

  // Step TCK in Run-Test/Idle until the port's stall counter of `channel`
  // has advanced past `stall_count`: the request VALID waits on the bus
  // against a low READY. The bridge pushes the request into its CDC only on
  // TCK edges.
  protected task wait_held_on_bus(dtp_j2a_target_t t, string channel, int unsigned stall_count,
                                  int unsigned tck_cycles, output bit on_bus);
    int unsigned aw, w, ar;
    on_bus = 1'b0;
    for (int unsigned i = 0; i <= tck_cycles; i++) begin
      sample_stall(t, aw, w, ar);
      if (((channel == "w") ? w : (channel == "ar") ? ar : aw) > stall_count) begin
        on_bus = 1'b1;
        return;
      end
      if (i < tck_cycles) step(1'b0);
    end
  endtask

  // System reset while a SINGLE_OP read's response is outstanding: tb_top
  // asserts the reset from the clock edge that completes the read's AR
  // handshake, so the R beat never reaches the bridge. The bridge discards
  // the read: SINGLE_OP reads DECERR with a zero data field, and a read of
  // the same slot then returns the preloaded word. `recovered` is 1 when the
  // discard was reported and the follow-on read ran.
  protected task reset_abort_read_response(int unsigned idx, int unsigned addr_idx,
                                           string context_s, output bit recovered);
    dtp_j2a_target_t t = select_target(idx);
    int unsigned size = t.default_size;
    bit [63:0] addr = robust_addr(t, addr_idx);
    bit [63:0] word = rand_nonzero_data(t) & data_mask(size);
    logic [31:0] reset_count;
    bit fired, idle;
    dtp_j2a_status_e st;
    bit [63:0] rdata;
    write_target_mem_int(t, addr, word, size);
    clear_cdc_clear_seen();
    reset_count = tb_vif.sys_rst_assert_count;
    tb_vif.sys_rst_on_ar_cycles <= 4'd1;
    tb_vif.sys_rst_on_ar_arm <= 3'(1 << idx);
    // The reset discards this read, so it arms no intent.
    issue_single(t, DTP_J2A_OP_READ, addr, '0, '0, size, .use_default_size(1'b0),
                 .arm_intent(1'b0));
    fired = 1'b0;
    for (int unsigned i = 0; i <= AbortMidFlightTck; i++) begin
      if (tb_vif.sys_rst_assert_count != reset_count) begin
        fired = 1'b1;
        break;
      end
      if (i < AbortMidFlightTck) step(1'b0);
    end
    wait_sys_cycles(4);
    tb_vif.sys_rst_on_ar_arm <= '0;
    check_reset_counted("sys_rst_assert_count", reset_count, tb_vif.sys_rst_assert_count, $sformatf(
                        "%s armed on the AR handshake", context_s));
    void'(record_abort_check(
        DtpJ2aAbortMidFlightCheckId,
        {
          context_s, ".mid_flight"
        },
        64'(fired),
        64'd1,
        "reset asserted on the AR handshake"
    ));
    wait_bridge_fsm(t, 1'b1, AbortSettleTck, idle);
    void'(record_abort_check(
        DtpJ2aAbortFsmCheckId,
        {
          context_s, ".fsm_idle"
        },
        64'(idle),
        64'd1,
        "after the read-response reset"
    ));
    void'(record_cdc_clear(t, {context_s, ".cdc_clear"}, "tck-side isolate-and-clear"));
    poll_single(t, st, rdata, {context_s, ".recovery"}, AbortRecoveryPolls);
    recovered = record_abort_check(
        DtpJ2aAbortRecoveryCheckId,
        {
          context_s, ".recovery_status"
        },
        64'(st),
        64'(DTP_J2A_DECERR),
        $sformatf(
            "status=%s max_captures=%0d after the read-response reset",
            st.name(),
            AbortRecoveryPolls)
    );
    void'(record_abort_check(
        DtpJ2aAbortRecoveryCheckId,
        {
          context_s, ".discarded_read_data"
        },
        rdata & bit_mask(
            t.data_width
        ),
        64'd0,
        "data field of the discarded read"
    ));
    status = st;
    if (recovered) begin
      read_target_single_and_check(t, addr, word, st, size, {context_s, ".recover_read"});
      status = st;
    end
    operation_count++;
  endtask

  protected task run_read_response_abort(string label, int unsigned addr_offset);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      bit recovered;
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s %s: system reset with the read response outstanding",
                i + 1,
                NumTargets,
                targets[i].name,
                label
                ), UVM_LOW)
      reset_abort_read_response(i, i + 1 + addr_offset, $sformatf("%s.%s", label, targets[i].name),
                                recovered);
    end
  endtask

  // System reset with the TAP holding Update-DR of a SINGLE_OP, so the CDC's
  // clear reaches the bridge in the one TCK cycle its state machine spends in
  // the address state. The pulse lands with TCK idle. The bridge latches the
  // operation on the first TCK edge after it and moves onto the address path
  // on the second; the clear, two TCK edges behind the reset through the
  // CDC's synchronizer, returns the state machine to idle on the third with
  // no request pushed into the crossing. SINGLE_OP then reads DECERR, with a
  // zero data field for a read. `recovered` is 1 when the discard was
  // reported and the recovery access ran.
  protected task reset_abort_address_phase(dtp_j2a_target_t t, bit is_read,
                                           int unsigned reset_cycles, int unsigned addr_idx,
                                           string context_s, output bit recovered);
    int unsigned size = t.default_size;
    bit [63:0] addr = robust_addr(t, addr_idx);
    bit [63:0] word = rand_nonzero_data(t) & data_mask(size);
    string direction = is_read ? "read" : "write";
    bit [63:0] prior_word;
    int unsigned aw0, w0, ar0;
    int unsigned aw1, w1, ar1;
    bit on_path, pending, quiet;
    dtp_j2a_status_e st;
    bit [63:0] rdata;
    if (is_read) write_target_mem_int(t, addr, word, size);
    prior_word = read_target_mem_int(t, addr, size);
    scan_single_to_update_dr(t, is_read ? DTP_J2A_OP_READ : DTP_J2A_OP_WRITE, addr,
                             is_read ? '0 : word, is_read ? '0 : full_wstrb(size), size);
    clear_cdc_clear_seen();
    pulse_system_reset(reset_cycles);
    // The reset clears the port's request counters: quiet means no request
    // counted since the pulse.
    sample_activity(t, aw0, w0, ar0);
    step(1'b0);
    step(1'b0);
    on_path = bridge_fsm_on_path(t, is_read);
    pending = bridge_op_pending(t);
    sample_activity(t, aw1, w1, ar1);
    quiet = (aw1 == aw0) && (w1 == w0) && (ar1 == ar0);
    void'(record_abort_check(
        DtpJ2aAbortMidFlightCheckId,
        {
          context_s, ".mid_flight"
        },
        64'(on_path && pending && quiet),
        64'd1,
        $sformatf(
            "%s_path=%0d pending=%0d port_quiet=%0d in the address state",
            direction,
            on_path,
            pending,
            quiet)
    ));
    step(1'b0);
    void'(record_abort_check(
        DtpJ2aAbortFsmCheckId,
        {
          context_s, ".fsm_idle"
        },
        64'(bridge_fsm_idle(
            t
        ) && !bridge_op_pending(
            t
        )),
        64'd1,
        "one TCK edge after the address state"
    ));
    void'(record_cdc_clear(t, {context_s, ".cdc_clear"}, "tck-side isolate-and-clear"));
    repeat (AbortCdcClearTck) step(1'b0);
    sample_activity(t, aw1, w1, ar1);
    quiet = (aw1 == aw0) && (w1 == w0) && (ar1 == ar0);
    void'(record_abort_check(
        DtpJ2aAbortEscapeCheckId,
        {
          context_s, ".no_request"
        },
        64'(quiet),
        64'd1,
        "no AW, W or AR reached the port"
    ));
    void'(record_abort_check(
        DtpJ2aAbortEscapeCheckId,
        {
          context_s, ".no_escape"
        },
        read_target_mem_int(
            t, addr, size
        ),
        prior_word,
        $sformatf(
            "addr=0x%0h", addr)
    ));
    poll_single(t, st, rdata, {context_s, ".recovery"}, AbortRecoveryPolls);
    recovered = record_abort_check(
        DtpJ2aAbortRecoveryCheckId,
        {
          context_s, ".recovery_status"
        },
        64'(st),
        64'(DTP_J2A_DECERR),
        $sformatf(
            "status=%s max_captures=%0d after the address-phase reset",
            st.name(),
            AbortRecoveryPolls)
    );
    if (is_read)
      void'(record_abort_check(
          DtpJ2aAbortRecoveryCheckId,
          {
            context_s, ".discarded_read_data"
          },
          rdata & bit_mask(
              t.data_width
          ),
          64'd0,
          "data field of the discarded read"
      ));
    status = st;
    if (recovered)
      recover_target(t, addr + 64'h200, random_distinct_word(t, '{word}), is_read, context_s,
                     status);
    operation_count++;
  endtask

  protected task run_address_phase_aborts(string label, int unsigned reset_cycles_hi,
                                          int unsigned addr_offset);
    for (int unsigned leg = 0; leg < 2 * NumTargets; leg++) begin
      dtp_j2a_target_t t = select_target(leg / 2);
      bit is_read = bit'(leg % 2);
      string direction = is_read ? "read" : "write";
      bit recovered;
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s %s: system reset with the %s in its address state",
                leg + 1,
                2 * NumTargets,
                t.name,
                label,
                direction
                ), UVM_LOW)
      reset_abort_address_phase(t, is_read, $urandom_range(reset_cycles_hi, 1),
                                leg + 1 + addr_offset, $sformatf(
                                "%s.%s.%s", label, t.name, direction), recovered);
    end
  endtask

  // System reset while a series write beat is held on the W channel: the
  // reset discards the series operation, so SERIES_CTRL reads DECERR and
  // keeps the held beat's address, since the beat never completed. After
  // SERIES_CTRL.reset a beat programmed at that address lands. `recovered`
  // is 1 when the discard was reported and the follow-on beat ran.
  protected task reset_abort_series(int unsigned idx, int unsigned addr_idx,
                                    int unsigned reset_cycles, string context_s,
                                    output bit recovered);
    dtp_j2a_target_t t = select_target(idx);
    int unsigned size = t.default_size;
    bit [63:0] addr = robust_addr(t, addr_idx);
    bit [63:0] data = rand_data(t) & data_mask(size);
    bit [63:0] prior_word = read_target_mem_int(t, addr, size);
    int unsigned aw0, w0, ar0;
    bit idle, on_bus;
    dtp_j2a_status_e st;
    series_ctrl_op(t, DTP_J2A_OP_NOP, '0, size, 0, 1'b1);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    configure_target_backpressure(t, '{"w"}, AbortHoldCycles);
    sample_stall(t, aw0, w0, ar0);
    series_data_incr(t, data, size);
    wait_bridge_fsm(t, 1'b0, AbortMidFlightTck, idle);
    wait_held_on_bus(t, "w", w0, AbortMidFlightTck, on_bus);
    void'(record_abort_check(
        DtpJ2aAbortMidFlightCheckId,
        {
          context_s, ".mid_flight"
        },
        64'(!idle && on_bus),
        64'd1,
        $sformatf(
            "idle=%0d w_held=%0d", idle, on_bus)
    ));
    clear_cdc_clear_seen();
    pulse_system_reset(reset_cycles);
    clear_target_backpressure(t);
    wait_bridge_fsm(t, 1'b1, AbortSettleTck, idle);
    void'(record_abort_check(
        DtpJ2aAbortFsmCheckId, {context_s, ".fsm_idle"}, 64'(idle), 64'd1, "after the series reset"
    ));
    void'(record_cdc_clear(t, {context_s, ".cdc_clear"}, "tck-side isolate-and-clear"));
    void'(record_abort_check(
        DtpJ2aAbortEscapeCheckId,
        {
          context_s, ".no_escape"
        },
        read_target_mem_int(
            t, addr, size
        ),
        prior_word,
        $sformatf(
            "addr=0x%0h", addr)
    ));
    check_series_addr(t, addr, size, {context_s, ".kept"}, st);
    recovered = record_abort_check(DtpJ2aAbortRecoveryCheckId, {context_s, ".series_status"},
                                   64'(st), 64'(DTP_J2A_DECERR),
                                   $sformatf("SERIES_CTRL status=%s after the series reset",
                                             st.name()));
    status = st;
    if (recovered) begin
      series_ctrl_op(t, DTP_J2A_OP_NOP, '0, size, 0, 1'b1);
      series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
      series_write_beat(t, data ^ data_mask(size), addr, size, 1'b1, {context_s, ".recover"});
      check_series_addr(t, addr + t.beat_bytes, size, {context_s, ".recover"}, st);
      check_status(t, {context_s, ".recover"}, st, DTP_J2A_SUCCESS);
      status = st;
    end
    operation_count++;
  endtask

  protected task run_series_abort(string label, int unsigned reset_cycles_hi,
                                  int unsigned addr_offset);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      bit recovered;
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s %s: system reset while a series beat is held",
                i + 1,
                NumTargets,
                targets[i].name,
                label
                ), UVM_LOW)
      reset_abort_series(i, i + 1 + addr_offset, $urandom_range(reset_cycles_hi, 1), $sformatf(
                         "%s.%s", label, targets[i].name), recovered);
    end
  endtask

  protected task run_reset_abort(string label, string channel, int unsigned reset_cycles_hi,
                                 bit [63:0] recovery_xor, int unsigned addr_offset,
                                 bit with_second_reset = 1'b0);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      bit recovered;
      int unsigned second_reset_cycles = 0;
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s %s: system reset while %s is held",
                i + 1,
                NumTargets,
                t.name,
                label,
                channel
                ), UVM_LOW)
      if (with_second_reset) second_reset_cycles = $urandom_range(reset_cycles_hi, 1);
      reset_abort_mid_flight(t, channel, $urandom_range(reset_cycles_hi, 1), i + 1 + addr_offset,
                             recovery_xor, $sformatf("%s.%s", label, t.name), second_reset_cycles,
                             recovered);
    end
  endtask

  // Phases of the ACLK-side clear sequence a system reset is placed in while
  // the sequence runs: a bridge's pass takes the phase at its loop index plus
  // the scenario seed, so the passes visit every phase on every bridge.
  localparam int unsigned B2bClearPhases = 4;
  // TCK cycles stepped in Run-Test/Idle while waiting for the phase, and
  // after the reset for the restarted sequence to complete: the four phase
  // handshakes each cost a few cycles of each clock, and TCK is the slower
  // one.
  localparam int unsigned B2bPhaseTck = 64;
  // TCK or system clock edges after the other side's reset at which a
  // four-phase receiver spends one cycle waiting for its isolate
  // acknowledge: the request crosses two synchronizer stages, and the
  // acknowledge flop loads on the third edge while the receiver samples the
  // value before it.
  localparam int unsigned B2bReceiverWaitEdges = 3;
  // First slot of the recovery accesses after the receiver legs; the
  // per-bridge loop takes the slots below it.
  localparam int unsigned B2bRecoverySlot = 20;

  protected task run_back_to_back_reset();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      bit [63:0] addr = robust_addr(t, i + 17);
      // Seeded per-pass payload and pulse widths: each loop stresses a
      // different back-to-back reset spacing.
      bit [63:0] data = rand_data(t);
      dtp_j2a_status_e op_status;
      dtp_j2a_status_e st;
      bit [63:0] rdata;
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s back-to-back reset", i + 1, NumTargets, t.name), UVM_LOW)
      arm_target_error(t, addr + 64'h100, OCAH_AXI_RESP_SLVERR, .for_read(1'b0), .for_write(1'b1));
      write_target_single_expect_status(t, addr + 64'h100, data ^ 64'h5A5A, DTP_J2A_SLVERR,
                                        op_status, t.default_size, full_wstrb(t.default_size),
                                        $sformatf("back_to_back_reset.%s.prime", t.name));
      reset_in_clear_phase(t, clear_phase_name(i + 1 + scenario_seed), $urandom_range(3, 1),
                           $sformatf("back_to_back_reset.%s", t.name));
      clear_cdc_clear_seen();
      pulse_system_reset($urandom_range(2, 1));
      pulse_system_reset($urandom_range(3, 1));
      // The CDC's TCK-side isolate-and-clear runs only while TCK runs.
      repeat (AbortCdcClearTck) step(1'b0);
      void'(record_cdc_clear(
          t,
          $sformatf(
              "back_to_back_reset.%s.cdc_clear", t.name
          ),
          "tck-side isolate-and-clear after two resets"
      ));
      record_idle_bridge(t, $sformatf("back_to_back_reset.%s.fsm_idle", t.name));
      poll_single(t, st, rdata, $sformatf("back_to_back_reset.%s.status_kept", t.name),
                  AbortRecoveryPolls);
      void'(record_abort_check(
          DtpJ2aAbortRecoveryCheckId,
          $sformatf(
              "back_to_back_reset.%s.status_kept", t.name
          ),
          64'(st),
          64'(DTP_J2A_SLVERR),
          $sformatf(
              "status=%s max_captures=%0d after two idle resets", st.name(), AbortRecoveryPolls)
      ));
      verify_target_recovery(t, addr, data, 1'b0, $sformatf("back_to_back_reset.%s", t.name));
      recover_target(t, addr, data, 1'b1, $sformatf("back_to_back_reset_read.%s", t.name), status);
      operation_count++;
    end
    begin
      bit seen;
      tap_reset_in_receiver_wait(seen);
      judge_receiver_leg("tck_wda", seen, B2bRecoverySlot);
      system_reset_in_receiver_wait(seen);
      judge_receiver_leg("aclk_wda", seen, B2bRecoverySlot + NumTargets);
    end
  endtask

  // TCK-side clear with a request held on the fabric. TRST is asserted with
  // one to four TCK cycles clocked under it and held until the TAP leaves
  // Test-Logic-Reset. The ACLK side starts its clear about two system cycles
  // after the TCK-side reset and holds it until TCK clocks the clear's
  // phases after the reset is released, so a release six to sixteen system
  // cycles after the last TCK cycle of the reset lands inside the clear. The
  // 64 to 96 TCK cycles stepped in Run-Test/Idle after Test-Logic-Reset
  // cover the CDC's four-phase isolate-and-clear: each phase handshake costs
  // a few cycles of each clock, and TCK is the slower one. A clear in
  // progress sets the sticky clear-seen flag within the probe window. A
  // queued request reaches the CDC two TCK cycles after the state machine
  // leaves idle and crosses the three-stage pointer synchronizers into the
  // destination spill register within sixteen system cycles.
  localparam int unsigned OrphanTrstHoldMax = 4;
  localparam int unsigned OrphanInClearMin = 6;
  localparam int unsigned OrphanInClearMax = 16;
  localparam int unsigned OrphanClearTckMin = 64;
  localparam int unsigned OrphanClearTckMax = 96;
  localparam int unsigned OrphanClearProbeCycles = 4;
  localparam int unsigned OrphanQueueTck = 2;
  localparam int unsigned OrphanQueueCycles = 16;
  // Release offsets of the aligned leg, in system cycles after the TRST
  // assertion (before it when negative). A pass starts at its scenario seed
  // modulo the span and each bridge and direction takes the next offset, so
  // consecutive passes walk every offset on every leg.
  localparam int OrphanAlignMin = -2;
  localparam int unsigned OrphanAlignSpan = 6;
  // Each drain point takes three consecutive 0x400 slots, for its held,
  // queued and follow-on requests; the recovery accesses take the slots
  // after the last.
  localparam int unsigned OrphanSlotStride = 3;

  // When the responder releases a request held across a TCK-side clear:
  // while the TAP still holds the bridge's TCK side in reset; once the clear
  // has finished; as the latter with a request of the new session waiting
  // behind it; a swept number of system cycles around the TRST assertion.
  typedef enum int unsigned {
    DTP_J2A_DRAIN_IN_CLEAR,
    DTP_J2A_DRAIN_AFTER_CLEAR,
    DTP_J2A_DRAIN_QUEUED,
    DTP_J2A_DRAIN_ALIGNED
  } dtp_j2a_drain_e;

  // One bridge and direction at one drain point, with its seeded choices.
  // `resp` is the leg's error code: the held read's response and the queued
  // write's. The follow-on operation gets the other one.
  typedef struct {
    dtp_j2a_target_t t;
    bit              is_read;
    dtp_j2a_drain_e  drain;
    int unsigned     slot;
    bit              via_trst;
    int unsigned     trst_hold;
    int unsigned     clear_tck;
    int unsigned     in_clear_wait;
    int              offset;
    ocah_axi_resp_e  resp;
    string           context_s;
  } orphan_leg_t;

  protected function string clear_phase_name(int unsigned k);
    case (k % B2bClearPhases)
      0:       return "clear";
      1:       return "wait_clear_phase_ack";
      2:       return "post_clear";
      default: return "finished";
    endcase
  endfunction

  // The dtp_tb_if phase observable j2a_cdc_<name>.
  protected function bit phase_flag(string name);
    case (name)
      "aclk_clear":                return tb_vif.j2a_cdc_aclk_clear;
      "aclk_wait_clear_phase_ack": return tb_vif.j2a_cdc_aclk_wait_clear_phase_ack;
      "aclk_post_clear":           return tb_vif.j2a_cdc_aclk_post_clear;
      "aclk_finished":             return tb_vif.j2a_cdc_aclk_finished;
      "tck_dst_wait_ack":          return tb_vif.j2a_cdc_tck_dst_wait_ack;
      "aclk_dst_wait_ack":         return tb_vif.j2a_cdc_aclk_dst_wait_ack;
      default: `uvm_fatal(get_type_name(), {"unknown phase observable ", name})
    endcase
    return 1'b0;
  endfunction

  protected task wait_clear_phase(string phase);
    case (phase)
      "clear":                @(posedge tb_vif.j2a_cdc_aclk_clear);
      "wait_clear_phase_ack": @(posedge tb_vif.j2a_cdc_aclk_wait_clear_phase_ack);
      "post_clear":           @(posedge tb_vif.j2a_cdc_aclk_post_clear);
      default:                @(posedge tb_vif.j2a_cdc_aclk_finished);
    endcase
  endtask

  // CHK-J2A-ABORT-FSM on a bridge that has nothing in flight: its state
  // machine idle with no operation pending.
  protected function void record_idle_bridge(dtp_j2a_target_t t, string name);
    bit idle = bridge_fsm_idle(t);
    bit pending = bridge_op_pending(t);
    void'(record_abort_check(
        DtpJ2aAbortFsmCheckId,
        name,
        64'(idle && !pending),
        64'd1,
        $sformatf(
            "idle=%0d pending=%0d after the reset", idle, pending)
    ));
  endfunction

  // Pulse the system reset for `cycles` system clocks from the falling
  // system clock edge `edges` rising edges after the caller's trigger,
  // sampling the dtp_tb_if phase observable `flag` at the deposit. The
  // deposit lands half a cycle inside a state at least one cycle wide that
  // begins on the rising edge.
  protected task reset_after_edges(int unsigned edges, string flag, int unsigned cycles,
                                   string context_s, output bit seen);
    logic [31:0] before_count;
    repeat (edges) @(posedge tb_vif.clk);
    @(negedge tb_vif.clk);
    seen = phase_flag(flag);
    before_count = tb_vif.sys_rst_assert_count;
    tb_vif.sys_rst_n <= 1'b0;
    wait_sys_cycles(cycles);
    tb_vif.sys_rst_n <= 1'b1;
    wait_sys_cycles(cycles);
    check_reset_counted("sys_rst_assert_count", before_count, tb_vif.sys_rst_assert_count,
                        context_s);
  endtask

  // Pulse the system reset while the ACLK-side clear sequence, restarted by
  // a pulse with TCK idle, is in `phase`, then step TCK until the restarted
  // sequence completes. The watcher deposits the pulse once the phase is
  // observed; the TCK stepper stops after the step in which it landed, so no
  // JTAG item is cut short; a watcher that never fired is killed at its
  // wait for the phase.
  protected task reset_in_clear_phase(dtp_j2a_target_t t, string phase, int unsigned cycles,
                                      string context_s);
    bit seen = 1'b0;
    bit fired = 1'b0;
    bit landed = 1'b0;
    process watcher = null;
    `uvm_info(get_type_name(), $sformatf("%s: system reset in the %s phase, %0d cycles wide",
                                         context_s, phase, cycles), UVM_LOW)
    clear_cdc_clear_seen();
    pulse_system_reset(1);
    fork
      begin
        watcher = process::self();
        wait_clear_phase(phase);
        fired = 1'b1;
        reset_after_edges(0, {"aclk_", phase}, cycles, {context_s, " in ", phase}, seen);
        landed = 1'b1;
      end
    join_none
    for (int unsigned i = 0; i < B2bPhaseTck && !landed; i++) step(1'b0);
    if (fired) wait (landed);
    else if (watcher != null) watcher.kill();
    void'(record_abort_check(
        DtpJ2aCdcPhaseCheckId,
        {
          context_s, ".phase.", phase
        },
        64'(seen),
        64'd1,
        $sformatf(
            "system reset deposited in %s, landed=%0d", phase, landed)
    ));
    repeat (B2bPhaseTck) step(1'b0);
  endtask

  // TRST in the one TCK cycle the TCK-side four-phase receivers wait for
  // their isolate acknowledge after a system reset with TCK idle; `seen` is
  // the receiver observable sampled at the TRST deposit.
  protected task tap_reset_in_receiver_wait(output bit seen);
    int unsigned hold = $urandom_range(OrphanTrstHoldMax, 1);
    `uvm_info(get_type_name(),
              $sformatf(
                  "TRST %0d TCK cycles after a system reset with TCK idle, held %0d TCK cycles",
                  B2bReceiverWaitEdges, hold), UVM_LOW)
    clear_cdc_clear_seen();
    pulse_system_reset(1);
    repeat (B2bReceiverWaitEdges) step(1'b0);
    seen = tb_vif.j2a_cdc_tck_dst_wait_ack;
    set_trst(1'b0, hold);
    leave_tap_reset(1'b1, B2bPhaseTck);
  endtask

  // System reset in the one system clock cycle the ACLK-side four-phase
  // receivers wait for their isolate acknowledge after TRST; `seen` is the
  // receiver observable sampled at the deposit. TRST is deposited half a
  // system cycle from any system clock edge, so the receivers' synchronizers
  // take it on the next edge.
  protected task system_reset_in_receiver_wait(output bit seen);
    int unsigned cycles = $urandom_range(3, 1);
    int unsigned hold = $urandom_range(OrphanTrstHoldMax, 1);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "system reset %0d system clock edges after TRST, %0d cycles wide, TRST held %0d TCK",
            B2bReceiverWaitEdges, cycles, hold), UVM_LOW)
    clear_cdc_clear_seen();
    @(negedge tb_vif.clk);
    trst_op(1'b1);
    fork
      reset_after_edges(B2bReceiverWaitEdges, "aclk_dst_wait_ack", cycles,
                        "back_to_back_reset.aclk_wda", seen);
      hold_trst(hold);
    join
    leave_tap_reset(1'b1, B2bPhaseTck);
  endtask

  // Every bridge's evidence after a reset placed in its receivers' waiting
  // cycle: the receiver observable at the deposit, the TCK-side clear, the
  // idle state machine, the SINGLE_OP status at its reset value, and a
  // recovery write and read at slot `slot` onwards.
  protected task judge_receiver_leg(string leg, bit seen, int unsigned slot);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      string context_s = $sformatf("back_to_back_reset.%s.%s", leg, t.name);
      bit [63:0] addr = robust_addr(t, slot + i);
      bit [63:0] data = rand_nonzero_data(t);
      dtp_j2a_status_e st;
      bit [63:0] rdata;
      void'(record_abort_check(
          DtpJ2aCdcPhaseCheckId,
          {
            context_s, ".phase"
          },
          64'(seen),
          64'd1,
          "receiver waiting for its isolate acknowledge at the reset"
      ));
      void'(record_cdc_clear(
          t, {context_s, ".cdc_clear"}, "tck-side isolate-and-clear after the reset"
      ));
      record_idle_bridge(t, {context_s, ".fsm_idle"});
      load_ir(IrWidth'(t.single_op_instr));
      poll_single(t, st, rdata, {context_s, ".status"}, AbortRecoveryPolls);
      void'(record_abort_check(
          DtpJ2aAbortRecoveryCheckId,
          {
            context_s, ".status"
          },
          64'(st),
          64'(DTP_J2A_SUCCESS),
          $sformatf(
              "status=%s max_captures=%0d on an idle bridge", st.name(), AbortRecoveryPolls)
      ));
      verify_target_recovery(t, addr, data, 1'b0, context_s);
      recover_target(t, addr, data, 1'b1, {context_s, "_read"}, status);
      operation_count++;
    end
  endtask

  protected function string drain_label(dtp_j2a_drain_e drain);
    case (drain)
      DTP_J2A_DRAIN_IN_CLEAR:    return "in_clear";
      DTP_J2A_DRAIN_AFTER_CLEAR: return "after_clear";
      DTP_J2A_DRAIN_QUEUED:      return "queued";
      default:                   return "aligned";
    endcase
  endfunction

  // The channel whose READY stall holds the leg's request.
  protected function string held_channel(orphan_leg_t leg);
    string channel = "aw";
    if (leg.is_read) channel = "ar";
    return channel;
  endfunction

  // Port completions of the leg's direction once the stall is released.
  protected function int unsigned leg_landings(orphan_leg_t leg);
    return (leg.drain == DTP_J2A_DRAIN_QUEUED) ? 2 : 1;
  endfunction

  // Record one CHK-J2A-ORPHAN-* judgement on the selected bridge;
  // +DTP_J2A_ORPHAN_NEGATIVE flips bit 0 of `expected`, so the run must fail.
  protected function bit record_orphan_check(string check_id, string name, bit [63:0] observed,
                                             bit [63:0] expected, string context_s);
    if (test_cfg != null && test_cfg.j2a_orphan_negative) expected ^= 64'd1;
    return record_abort_check(check_id, name, observed, expected, context_s);
  endfunction

  // Issue a SINGLE_OP whose request the responder holds on the fabric. A
  // read holds its AR and is answered with the leg's error and the
  // errored-beat word `word`; a write holds its AW and W and is answered
  // OKAY, so it lands `word`. The request completes on the bus once the
  // stall is released, so its intents are armed. Records
  // CHK-J2A-ABORT-MIDFLIGHT once the state machine waits on it and the held
  // channel's stall counter has advanced.
  protected task hold_on_fabric(orphan_leg_t leg, bit [63:0] addr, bit [63:0] word, output bit ok);
    dtp_j2a_target_t t = leg.t;
    string held = held_channel(leg);
    int unsigned aw0, w0, ar0;
    bit idle, on_bus;
    if (leg.is_read) begin
      configure_target_backpressure(t, '{"ar"}, AbortHoldCycles);
      arm_target_error(t, addr, leg.resp, .for_read(1'b1), .for_write(1'b0), .arm_expected(1'b1),
                       .err_rdata(word));
    end else begin
      configure_target_backpressure(t, '{"aw", "w"}, AbortHoldCycles);
    end
    sample_stall(t, aw0, w0, ar0);
    if (leg.is_read) issue_single(t, DTP_J2A_OP_READ, addr);
    else issue_single(t, DTP_J2A_OP_WRITE, addr, word, full_wstrb(t.default_size));
    wait_bridge_fsm(t, 1'b0, AbortMidFlightTck, idle);
    wait_held_on_bus(t, held, leg.is_read ? ar0 : aw0, AbortMidFlightTck, on_bus);
    ok = record_abort_check(
        DtpJ2aAbortMidFlightCheckId,
        {
          leg.context_s, ".mid_flight"
        },
        64'(!idle && bridge_op_pending(
            t
        ) && on_bus),
        64'd1,
        $sformatf(
            "idle=%0d %s_held=%0d", idle, held, on_bus)
    );
  endtask

  // Reset the bridges' TCK side: TRST asserted over `hold` TCK cycles and
  // left asserted, or the TMS walk into Test-Logic-Reset.
  protected task enter_tap_reset(bit via_trst, int unsigned hold);
    if (via_trst) set_trst(1'b0, hold);
    else goto_tlr_via_tms();
  endtask

  // Release TRST, leave Test-Logic-Reset, and step `clear_tck` TCK cycles in
  // Run-Test/Idle, during which the CDC runs its TCK-side isolate-and-clear.
  protected task leave_tap_reset(bit via_trst, int unsigned clear_tck);
    if (via_trst) set_trst(1'b1, 1);
    repeat (clear_tck + 1) step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after the TAP reset");
  endtask

  // Assert TRST and release the stall `offset` system cycles after it, or
  // before it when `offset` is negative. Both start from one instant and
  // wait whole system clock periods, so they take effect `offset` clock
  // edges apart.
  protected task aligned_tap_reset(dtp_j2a_target_t t, int offset, int unsigned hold);
    if (offset < 0) begin
      clear_target_backpressure(t);
      wait_sys_cycles(int'(-offset));
      set_trst(1'b0, hold);
      return;
    end
    fork
      begin
        if (offset > 0) wait_sys_cycles(offset);
        clear_target_backpressure(t);
      end
      set_trst(1'b0, hold);
    join
  endtask

  // CHK-J2A-ORPHAN-DRAIN: the clear has finished while the request is still
  // held. The sticky clear-seen flag stays clear over the probe window and
  // the held channel's stall counter keeps advancing.
  protected task judge_clear_finished(orphan_leg_t leg, output bit ok);
    int unsigned aw0, w0, ar0, aw1, w1, ar1;
    bit pending, still_held;
    clear_cdc_clear_seen();
    sample_stall(leg.t, aw0, w0, ar0);
    wait_sys_cycles(OrphanClearProbeCycles);
    pending = cdc_clear_seen(leg.t);
    sample_stall(leg.t, aw1, w1, ar1);
    still_held = leg.is_read ? (ar1 > ar0) : (aw1 > aw0);
    ok = record_orphan_check(DtpJ2aOrphanDrainCheckId, {leg.context_s, ".clear_finished"},
                             64'(!pending && still_held), 64'd1, $sformatf(
                             "clear_pending=%0d %s_held=%0d", pending, held_channel(leg),
                             still_held));
  endtask

  // Reset the TAP with the request held and leave Test-Logic-Reset again.
  // Inside the clear the stall is released while the TAP holds
  // Test-Logic-Reset (CHK-J2A-ORPHAN-DRAIN for the landing there), and at
  // the aligned drain point together with TRST. CHK-J2A-CDC-CLEAR records
  // the TCK-side clear; ahead of a release after the clear,
  // CHK-J2A-ORPHAN-DRAIN records the finished clear with the request still
  // held.
  protected task drain_tap_reset(orphan_leg_t leg, int unsigned completed, output bit ok);
    dtp_j2a_target_t t = leg.t;
    bit landed, step_ok;
    ok = 1'b1;
    clear_cdc_clear_seen();
    if (leg.drain == DTP_J2A_DRAIN_ALIGNED) aligned_tap_reset(t, leg.offset, leg.trst_hold);
    else enter_tap_reset(leg.via_trst, leg.trst_hold);
    if (leg.drain == DTP_J2A_DRAIN_IN_CLEAR) begin
      wait_sys_cycles(leg.in_clear_wait);
      clear_target_backpressure(t);
      wait_port_count(t, leg.is_read, completed, landed);
      ok = record_orphan_check(
          DtpJ2aOrphanDrainCheckId,
          {
            leg.context_s, ".drained_in_reset"
          },
          64'(landed && (tb_vif.tap_state === 16'(TEST_LOGIC_RESET))),
          64'd1,
          $sformatf(
              "landed=%0d tap_state=0x%04h", landed, tb_vif.tap_state)
      );
    end
    leave_tap_reset(leg.via_trst, leg.clear_tck);
    ok &= record_cdc_clear(
        t, {leg.context_s, ".cdc_clear"}, "tck-side isolate-and-clear after the TAP reset"
    );
    if (leg.drain inside {DTP_J2A_DRAIN_AFTER_CLEAR, DTP_J2A_DRAIN_QUEUED}) begin
      judge_clear_finished(leg, step_ok);
      ok &= step_ok;
    end
  endtask

  // A seeded beat of slot `slot`'s 0x400 window, with seeded address bits
  // above the responder window.
  protected function bit [63:0] queued_addr(dtp_j2a_target_t t, int unsigned slot);
    bit [63:0] beat = 64'($urandom_range(32'h400 / t.beat_bytes - 1) * t.beat_bytes);
    return (RobustBase + 64'(slot) * 64'h400 + beat) | random_upper_addr(t);
  endfunction

  // Issue a SINGLE_OP of the new session behind the held request. A read of
  // a slot holding `word` is answered OKAY, and a write of `word` with the
  // leg's error, so neither response matches the held request's. `expected`
  // is the status the queued request reports; `ok` is 1 when
  // CHK-J2A-ORPHAN-ORDER saw the bridge waiting on it while the held request
  // still stalls.
  protected task queue_behind(orphan_leg_t leg, bit [63:0] addr, bit [63:0] word,
                              output dtp_j2a_status_e expected, output bit ok);
    dtp_j2a_target_t t = leg.t;
    int unsigned size = t.default_size;
    int unsigned aw0, w0, ar0, aw1, w1, ar1;
    bit idle, still_held;
    sample_stall(t, aw0, w0, ar0);
    if (leg.is_read) begin
      expected = DTP_J2A_SUCCESS;
      write_target_mem_int(t, addr, word, size);
      issue_single(t, DTP_J2A_OP_READ, addr);
    end else begin
      expected = dtp_j2a_axi_resp_to_status(leg.resp);
      arm_target_error(t, addr, leg.resp, .for_read(1'b0), .for_write(1'b1));
      issue_single(t, DTP_J2A_OP_WRITE, addr, word, full_wstrb(size));
    end
    wait_bridge_fsm(t, 1'b0, AbortMidFlightTck, idle);
    repeat (OrphanQueueTck) step(1'b0);
    wait_sys_cycles(OrphanQueueCycles);
    sample_stall(t, aw1, w1, ar1);
    still_held = leg.is_read ? (ar1 > ar0) : (aw1 > aw0);
    ok = record_orphan_check(DtpJ2aOrphanOrderCheckId, {leg.context_s, ".queued"},
                             64'(!idle && bridge_op_pending(t) && still_held), 64'd1, $sformatf(
                             "idle=%0d %s_held=%0d", idle, held_channel(leg), still_held));
  endtask

  // Judge the port and SINGLE_OP once the held request, and a queued one,
  // drained. `held_addr`/`held_word` are the held request's, and
  // `last_addr`/`last_word`/`last_status` the newest request's.
  // CHK-J2A-ORPHAN-DRAIN: one completion of the direction, two with a queued
  // request, and a held write's word in its slot. Without a queued request,
  // the newest completion is the held one (CHK-J2A-ORPHAN-DRAIN) and
  // SINGLE_OP reads the TAP reset's SUCCESS (CHK-J2A-ORPHAN-DISCARD). With
  // one, CHK-J2A-ORPHAN-ORDER: the newest completion is the queued
  // request's, SINGLE_OP reads its status, and a queued read's data field
  // holds its slot's word.
  protected task judge_drain(orphan_leg_t leg, bit [63:0] held_addr, bit [63:0] held_word,
                             bit [63:0] last_addr, bit [63:0] last_word,
                             dtp_j2a_status_e last_status, int unsigned completed, output bit ok);
    dtp_j2a_target_t t = leg.t;
    int unsigned size = t.default_size;
    bit queued = (leg.drain == DTP_J2A_DRAIN_QUEUED);
    string status_id = queued ? DtpJ2aOrphanOrderCheckId : DtpJ2aOrphanDiscardCheckId;
    string status_label = ".status_after_drain";
    dtp_axi_port_history port = port_history(t.name);
    dtp_j2a_status_e st;
    bit [63:0] rdata;
    ocah_axi_item newest;
    bit done;
    if (queued) status_label = ".queued_status";
    wait_port_count(t, leg.is_read, completed + leg_landings(leg) - 1, done);
    for (int unsigned i = 0; i < AbortSettleTck && bridge_op_pending(t); i++) step(1'b0);
    // A TAP reset loads IDCODE, and the status capture shifts the SINGLE_OP
    // register under the instruction already loaded.
    load_ir(t.single_op_instr);
    poll_single(t, st, rdata, {leg.context_s, ".drained"}, AbortRecoveryPolls);
    ok = record_orphan_check(
        DtpJ2aOrphanDrainCheckId,
        {
          leg.context_s, ".landings"
        },
        64'(port.count(
            leg.is_read
        ) - completed),
        64'(leg_landings(
            leg
        )),
        "port completions of the direction after the release"
    );
    void'(port.last(leg.is_read, newest));
    ok &= record_orphan_check(
        queued ? DtpJ2aOrphanOrderCheckId : DtpJ2aOrphanDrainCheckId,
        {
          leg.context_s, ".last_address"
        },
        (newest != null) ? newest.address : '0,
        last_addr & bit_mask(
            t.addr_width
        ),
        "address of the newest completion of the direction"
    );
    if (!leg.is_read) begin
      check_target_memory(t, held_addr, held_word, size, {leg.context_s, ".held_slot"});
      ok &= record_orphan_check(
          DtpJ2aOrphanDrainCheckId,
          {
            leg.context_s, ".held_slot"
          },
          read_target_mem_int(
              t, held_addr, size
          ),
          held_word & data_mask(
              size
          ),
          $sformatf(
              "addr=0x%0h", held_addr)
      );
    end
    ok &= record_orphan_check(
        status_id,
        {
          leg.context_s, status_label
        },
        64'(st),
        64'(last_status),
        $sformatf(
            "status=%s max_captures=%0d", st.name(), AbortRecoveryPolls)
    );
    if (queued && leg.is_read)
      ok &= record_orphan_check(
          DtpJ2aOrphanOrderCheckId,
          {
            leg.context_s, ".queued_rdata"
          },
          rdata & bit_mask(
              t.data_width
          ),
          last_word,
          $sformatf(
              "addr=0x%0h", last_addr)
      );
  endtask

  // The next operation in the held request's direction reports its own
  // response. The responder answers it with the error code the leg's
  // earlier requests did not get, and a read with a seeded errored-beat
  // word, so no earlier response of the direction can pass for it
  // (CHK-J2A-ORPHAN-DISCARD); the port completes it as the only further
  // transaction of that direction (CHK-J2A-ORPHAN-DRAIN).
  protected task orphan_follow_on(orphan_leg_t leg, bit [63:0] avoid[$], int unsigned completed,
                                  output bit ok);
    dtp_j2a_target_t t = leg.t;
    int unsigned size = t.default_size;
    bit [63:0] addr = robust_addr(t, leg.slot + 2);
    ocah_axi_resp_e resp = (leg.resp == OCAH_AXI_RESP_SLVERR) ? OCAH_AXI_RESP_DECERR
                                                               : OCAH_AXI_RESP_SLVERR;
    dtp_j2a_status_e expected = dtp_j2a_axi_resp_to_status(resp);
    bit [63:0] errored = random_distinct_word(t, avoid);
    dtp_j2a_status_e st;
    bit [63:0] rdata;
    bit done;
    if (leg.is_read) begin
      avoid.push_back(errored);
      write_target_mem_int(t, addr, random_distinct_word(t, avoid), size);
      arm_target_error(t, addr, resp, .for_read(1'b1), .for_write(1'b0), .arm_expected(1'b1),
                       .err_rdata(errored));
      issue_single(t, DTP_J2A_OP_READ, addr);
    end else begin
      arm_target_error(t, addr, resp, .for_read(1'b0), .for_write(1'b1));
      issue_single(t, DTP_J2A_OP_WRITE, addr, errored, full_wstrb(size));
    end
    poll_single(t, st, rdata, {leg.context_s, ".follow_on"}, AbortRecoveryPolls);
    ok = record_orphan_check(
        DtpJ2aOrphanDiscardCheckId,
        {
          leg.context_s, ".follow_on_status"
        },
        64'(st),
        64'(expected),
        $sformatf(
            "status=%s max_captures=%0d", st.name(), AbortRecoveryPolls)
    );
    if (leg.is_read)
      ok &= record_orphan_check(
          DtpJ2aOrphanDiscardCheckId,
          {
            leg.context_s, ".follow_on_rdata"
          },
          rdata & bit_mask(
              t.data_width
          ),
          errored,
          "errored-beat word of the follow-on read"
      );
    wait_port_count(t, leg.is_read, completed, done);
    ok &= record_orphan_check(
        DtpJ2aOrphanDrainCheckId,
        {
          leg.context_s, ".single_landing"
        },
        64'(port_history(
            t.name
        ).count(
            leg.is_read
        )),
        64'(completed + 1),
        "port completions of the direction after the follow-on operation"
    );
  endtask

  // TCK-side clear while a SINGLE_OP is held on the fabric, drained as
  // `leg` selects. The held request completes on the bus exactly once and
  // the bridge consumes its response, so SINGLE_OP reads the TAP reset's
  // SUCCESS, or the queued request's own status, and the next operation
  // reports its own response. `ok` is 1 when every judgement of the leg
  // matched.
  protected task tap_reset_orphan(orphan_leg_t leg, output bit ok);
    dtp_j2a_target_t t = leg.t;
    bit [63:0] addr = robust_addr(t, leg.slot);
    bit [63:0] word = rand_nonzero_data(t);
    int unsigned completed = port_history(t.name).count(leg.is_read);
    string clear_kind = "tms_walk";
    bit [63:0] last_addr = addr;
    bit [63:0] last_word = word;
    dtp_j2a_status_e last_status = DTP_J2A_SUCCESS;
    dtp_j2a_status_e error_status = dtp_j2a_axi_resp_to_status(leg.resp);
    bit step_ok;
    if (leg.via_trst) clear_kind = "trst";
    `uvm_info(
        get_type_name(),
        $sformatf(
            "%s clear=%s trst_hold=%0d clear_tck=%0d in_clear_wait=%0d release_offset=%0d error=%s",
            leg.context_s, clear_kind, leg.trst_hold, leg.clear_tck, leg.in_clear_wait, leg.offset,
            error_status.name()), UVM_LOW)
    hold_on_fabric(leg, addr, word, ok);
    drain_tap_reset(leg, completed, step_ok);
    ok &= step_ok;
    if (leg.drain == DTP_J2A_DRAIN_QUEUED) begin
      last_addr = queued_addr(t, leg.slot + 1);
      last_word = random_distinct_word(t, {word});
      queue_behind(leg, last_addr, last_word, last_status, step_ok);
      ok &= step_ok;
    end
    if (leg.drain inside {DTP_J2A_DRAIN_AFTER_CLEAR, DTP_J2A_DRAIN_QUEUED})
      clear_target_backpressure(t);
    judge_drain(leg, addr, word, last_addr, last_word, last_status, completed, step_ok);
    ok &= step_ok;
    orphan_follow_on(leg, {word, last_word}, completed + leg_landings(leg), step_ok);
    ok &= step_ok;
    operation_count++;
  endtask

  protected task run_tap_reset_orphans();
    dtp_j2a_drain_e drains[4] = '{
        DTP_J2A_DRAIN_IN_CLEAR,
        DTP_J2A_DRAIN_AFTER_CLEAR,
        DTP_J2A_DRAIN_QUEUED,
        DTP_J2A_DRAIN_ALIGNED
    };
    int unsigned num_drains = $size(drains);
    int unsigned pairs = 2 * NumTargets;
    int unsigned base = scenario_seed % OrphanAlignSpan;
    reset_to_rti();
    if (test_cfg != null && test_cfg.j2a_orphan_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: every CHK-J2A-ORPHAN-* expectation is corrupted", UVM_LOW)
    for (int unsigned pair = 0; pair < pairs; pair++) begin
      dtp_j2a_target_t t = select_target(pair / 2);
      bit is_read = bit'(pair % 2);
      string direction = "write";
      if (is_read) direction = "read";
      // Seeded drain order per bridge and direction; every drain runs on
      // every bridge and direction.
      drains.shuffle();
      foreach (drains[d]) begin
        orphan_leg_t leg;
        bit ok;
        leg.t = t;
        leg.is_read = is_read;
        leg.drain = drains[d];
        leg.slot = 1 + OrphanSlotStride * (num_drains * is_read + d);
        leg.via_trst = (drains[d] == DTP_J2A_DRAIN_ALIGNED) || $urandom_range(1);
        leg.trst_hold = $urandom_range(OrphanTrstHoldMax, 1);
        leg.clear_tck = $urandom_range(OrphanClearTckMax, OrphanClearTckMin);
        leg.in_clear_wait = $urandom_range(OrphanInClearMax, OrphanInClearMin);
        leg.offset = OrphanAlignMin + int'((base + pair) % OrphanAlignSpan);
        leg.resp = $urandom_range(1) ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_DECERR;
        leg.context_s = $sformatf("tap_reset.%s.%s.%s", t.name, direction, drain_label(drains[d]));
        `uvm_info(get_type_name(), $sformatf(
                  "[%0d/%0d] target=%s %s held on the fabric, drain=%s",
                  pair * num_drains + d + 1,
                  pairs * num_drains,
                  t.name,
                  direction,
                  drain_label(
                      drains[d]
                  )
                  ), UVM_LOW)
        tap_reset_orphan(leg, ok);
      end
    end
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      for (int unsigned is_read = 0; is_read < 2; is_read++) begin
        recover_target(t, robust_addr(t, OrphanSlotStride * 2 * num_drains + 1 + is_read),
                       rand_nonzero_data(t), bit'(is_read), $sformatf("tap_reset.%s", t.name),
                       status);
      end
    end
  endtask

  protected task run_decode_error_decerr_write();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      dtp_j2a_status_e op_status;
      int unsigned size = t.default_size;
      bit [63:0]   addr = robust_addr(t, i + 25);
      bit [63:0] mem_before;
      arm_target_error(t, addr, OCAH_AXI_RESP_DECERR, .for_read(1'b0), .for_write(1'b1));
      mem_before = read_target_mem_int(t, addr, size);
      write_target_single_expect_status(t, addr, 64'($urandom) ^ 64'(i + 1), DTP_J2A_DECERR,
                                        op_status, size, full_wstrb(size), $sformatf(
                                        "decerr_write.%s", t.name));
      // The responder drops an armed write beat, so the error slot keeps
      // its prior value.
      check_target_memory(t, addr, mem_before, size, $sformatf(
                          "decerr_write.%s.no_write_side_effect", t.name));
      // Seeded per-pass recovery payload.
      recover_target(t, addr + 64'h200, 64'($urandom) ^ 64'(i + 1), 1'b0, $sformatf(
                     "decerr_write.%s", t.name), status);
      operation_count++;
    end
  endtask

  protected task run_decode_error_decerr_read();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      dtp_j2a_status_e op_status;
      bit [63:0]   rdata;
      int unsigned size = t.default_size;
      bit [63:0]   addr = robust_addr(t, i + 33);
      bit [63:0]   preload = rand_nonzero_data(t);
      // The errored beat's word differs from zero and from the preload, so
      // neither a zeroed capture nor the slot's word can pass for it.
      bit [63:0]   errored = random_distinct_word(t, {preload});
      write_target_mem_int(t, addr, preload, size);
      arm_target_error(t, addr, OCAH_AXI_RESP_DECERR, .for_read(1'b1), .for_write(1'b0),
                       .err_rdata(errored));
      read_target_single_expect_status(t, addr, DTP_J2A_DECERR, op_status, rdata, size, $sformatf(
                                       "decerr_read.%s", t.name));
      check_error_rdata(t, addr, rdata, OCAH_AXI_RESP_DECERR, preload, errored, size, $sformatf(
                        "decerr_read.%s", t.name));
      // Seeded per-pass recovery payload.
      recover_target(t, addr + 64'h200, 64'($urandom) ^ 64'(i + 1), 1'b1, $sformatf(
                     "decerr_read.%s", t.name), status);
      operation_count++;
    end
  endtask

  protected task run_decode_error_mixed();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      dtp_j2a_status_e op_status;
      bit [63:0]   rdata;
      int unsigned size = t.default_size;
      bit [63:0]   good_addr = robust_addr(t, i + 41);
      bit [63:0]   bad_addr  = good_addr + 64'h100;
      bit [63:0]   good_data = rand_data(t);
      write_target_single_and_check(t, good_addr, good_data, op_status, size, full_wstrb(size),
                                    $sformatf("mixed.good_write.%s", t.name));
      // One DECERR arming per direction at the faulted slot, each consumed
      // by the access that follows it, so no armed credit dangles.
      arm_target_error(t, bad_addr, OCAH_AXI_RESP_DECERR, .for_read(1'b1), .for_write(1'b0));
      read_target_single_expect_status(t, bad_addr, DTP_J2A_DECERR, op_status, rdata, size,
                                       $sformatf("mixed.bad_read.%s", t.name));
      arm_target_error(t, bad_addr, OCAH_AXI_RESP_DECERR, .for_read(1'b0), .for_write(1'b1));
      write_target_single_expect_status(t, bad_addr, rand_data(t), DTP_J2A_DECERR, op_status, size,
                                        full_wstrb(size), $sformatf("mixed.bad_write.%s", t.name));
      read_target_single_and_check(t, good_addr, good_data, op_status, size, $sformatf(
                                   "mixed.good_read.%s", t.name));
      status = op_status;
      operation_count++;
    end
  endtask

  // --- series corner legs ---------------------------------------------------
  // Aligned base of one series leg's window: one 0x400 window per bridge,
  // one 0x100 leg per series.
  protected function bit [63:0] series_corner_base(int unsigned idx, int unsigned leg);
    return SeriesBase + (idx + 1) * 64'h400 + leg * 64'h100;
  endfunction

  // Land one write beat of a programmed series and compare the word it wrote.
  protected task series_corner_beat(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                    int unsigned size, bit increment, string context_s);
    int unsigned aw0, w0, ar0, wb0;
    bit [63:0] observed;
    sample_activity(t, aw0, w0, ar0);
    wb0 = write_bursts_now(t);
    if (increment) series_data_incr(t, data, size);
    else series_data_no_incr(t, data, size);
    wait_for_target_activity(t, aw0, w0, ar0, 1'b0, context_s);
    wait_for_write_completion(t, wb0, context_s);
    check_target_memory(t, addr, data, size, {context_s, ".mem"});
    operation_count++;
  endtask

  // An incrementing then a fixed-address series: the captured address follows
  // the mode.
  protected task series_corner_progressions(int unsigned idx, int unsigned beats);
    dtp_j2a_target_t t = select_target(idx);
    int unsigned size = t.default_size;
    bit [63:0] base = series_corner_base(idx, 0);
    bit [63:0] addr = series_corner_base(idx, 1);
    dtp_j2a_status_e sstatus;
    series_ctrl_op(t, DTP_J2A_OP_NOP, '0, size, 0, 1'b1);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    for (int unsigned beat = 0; beat < beats; beat++)
      series_corner_beat(t, base + beat * t.beat_bytes, rand_data(t) & data_mask(size), size, 1'b1,
                         $sformatf("series_corner.incr.%s.%0d", t.name, beat));
    check_series_addr(t, base + beats * t.beat_bytes, size, $sformatf(
                      "series_corner.incr.%s", t.name), sstatus);
    check_status(t, $sformatf("series_corner.incr.%s", t.name), sstatus, DTP_J2A_SUCCESS);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    for (int unsigned beat = 0; beat < beats; beat++)
      series_corner_beat(t, addr, rand_data(t) & data_mask(size), size, 1'b0, $sformatf(
                         "series_corner.fixed.%s.%0d", t.name, beat));
    check_series_addr(t, addr, size, $sformatf("series_corner.fixed.%s", t.name), sstatus);
    check_status(t, $sformatf("series_corner.fixed.%s", t.name), sstatus, DTP_J2A_SUCCESS);
    status = sstatus;
  endtask

  // One faulted beat sets the series status, which holds across the clean
  // beats after it until SERIES_CTRL.reset starts a fresh series.
  protected task series_corner_sticky_status(int unsigned idx, int unsigned beats);
    dtp_j2a_target_t t = select_target(idx);
    int unsigned size = t.default_size;
    bit [63:0] base = series_corner_base(idx, 2);
    // At least one clean beat follows the fault, so the held status is
    // observed after a beat the responder accepted.
    int unsigned fault_beat = $urandom_range(beats - 2);
    ocah_axi_resp_e resp = $urandom_range(1) ? OCAH_AXI_RESP_DECERR : OCAH_AXI_RESP_SLVERR;
    dtp_j2a_status_e expected = (resp == OCAH_AXI_RESP_DECERR) ? DTP_J2A_DECERR : DTP_J2A_SLVERR;
    bit [63:0] fault_addr = base + fault_beat * t.beat_bytes;
    bit [63:0] fault_before, clear_addr;
    dtp_j2a_status_e sstatus;
    arm_target_error(t, fault_addr, resp, .for_read(1'b0), .for_write(1'b1));
    fault_before = read_target_mem_int(t, fault_addr, size);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    for (int unsigned beat = 0; beat < beats; beat++) begin
      bit [63:0] addr = base + beat * t.beat_bytes;
      bit [63:0] data = rand_data(t) & data_mask(size);
      bit [63:0] observed, expected_word;
      int unsigned aw0, w0, ar0, wb0;
      string context_s = $sformatf("series_corner.sticky.%s.%0d", t.name, beat);
      sample_activity(t, aw0, w0, ar0);
      wb0 = write_bursts_now(t);
      series_data_incr(t, data, size);
      wait_for_target_activity(t, aw0, w0, ar0, 1'b0, context_s);
      wait_for_write_completion(t, wb0, context_s);
      expected_word = (beat == fault_beat) ? fault_before : data;
      check_target_memory(t, addr, expected_word, size, {
                          context_s, (beat == fault_beat) ? ".mem_dropped" : ".mem"});
      // The capture right after the faulted beat carries the code.
      if (beat == fault_beat) begin
        check_series_addr(t, addr + t.beat_bytes, size, {context_s, ".faulted"}, sstatus);
        check_status(t, {context_s, ".faulted"}, sstatus, expected);
      end
      operation_count++;
    end
    // The code holds across the clean beats that followed the fault.
    check_series_addr(t, base + beats * t.beat_bytes, size, $sformatf(
                      "series_corner.sticky.%s", t.name), sstatus);
    check_status(t, $sformatf("series_corner.sticky.%s.held", t.name), sstatus, expected);
    clear_target_error(t);
    series_ctrl_op(t, DTP_J2A_OP_NOP, '0, size, 0, 1'b1);
    clear_addr = base + (beats + 1) * t.beat_bytes;
    series_ctrl_op(t, DTP_J2A_OP_WRITE, clear_addr, size);
    series_corner_beat(t, clear_addr, rand_data(t) & data_mask(size), size, 1'b1, $sformatf(
                       "series_corner.sticky.%s.cleared", t.name));
    check_series_addr(t, clear_addr + t.beat_bytes, size, $sformatf(
                      "series_corner.sticky.%s.cleared", t.name), sstatus);
    check_status(t, $sformatf("series_corner.sticky.%s.cleared", t.name), sstatus, DTP_J2A_SUCCESS);
    status = sstatus;
  endtask

  // Beats of the three bridges' series landed in seeded interleaved order
  // leave every bridge's address progression and every word exact.
  protected task series_corner_interleaved(int unsigned beats);
    bit [63:0] bases[NumTargets];
    bit [63:0] words[NumTargets][];
    dtp_j2a_status_e sstatus;
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      bases[i] = series_corner_base(i, 3);
      words[i] = new[beats];
      foreach (words[i][b]) words[i][b] = rand_data(t) & data_mask(t.default_size);
      series_ctrl_op(t, DTP_J2A_OP_NOP, '0, t.default_size, 0, 1'b1);
      series_ctrl_op(t, DTP_J2A_OP_WRITE, bases[i], t.default_size);
    end
    for (int unsigned beat = 0; beat < beats; beat++) begin
      int unsigned order[$];
      for (int unsigned i = 0; i < NumTargets; i++) order.push_back(i);
      order.shuffle();
      foreach (order[k]) begin
        dtp_j2a_target_t t = select_target(order[k]);
        series_corner_beat(t, bases[order[k]] + beat * t.beat_bytes, words[order[k]][beat],
                           t.default_size, 1'b1, $sformatf(
                           "series_corner.interleaved.%s.%0d", t.name, beat));
      end
    end
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      int unsigned size = t.default_size;
      check_series_addr(t, bases[i] + beats * t.beat_bytes, size, $sformatf(
                        "series_corner.interleaved.%s", t.name), sstatus);
      check_status(t, $sformatf("series_corner.interleaved.%s", t.name), sstatus, DTP_J2A_SUCCESS);
      for (int unsigned beat = 0; beat < beats; beat++)
      check_target_memory(t, bases[i] + beat * t.beat_bytes, words[i][beat], size, $sformatf(
                          "series_corner.interleaved.%s.final#%0d", t.name, beat));
      status = sstatus;
    end
  endtask

  protected task run_series_corner_all_bridges();
    // Seeded per-pass beat count, above the two beats a progression needs.
    int unsigned beats = $urandom_range(6, 3);
    `uvm_info(get_type_name(), $sformatf("Series corner: %0d beats per series", beats), UVM_LOW)
    for (int unsigned i = 0; i < NumTargets; i++) series_corner_progressions(i, beats);
    for (int unsigned i = 0; i < NumTargets; i++) series_corner_sticky_status(i, beats);
    series_corner_interleaved(beats);
  endtask

  // --- CDC FIFO entry sweep -------------------------------------------------
  // Entries in each CDC FIFO of the bridge behind `t`. The bridge sizes the
  // five FIFOs of its clock crossing to the power of two at or above its read
  // pipeline depth plus two. A FIFO pushes into its entries in turn from its
  // last clear, so push j lands in entry j % slots, and a stored entry keeps
  // its payload until the asynchronous reset of the FIFO's source side.
  protected function int unsigned cdc_fifo_slots(dtp_j2a_target_t t);
    return 1 << $clog2(t.rd_pl_depth + 2);
  endfunction

  // The injected response of each of `pushes` accesses into a `slots`-entry
  // FIFO, OKAY where none is injected. Every entry takes one errored access
  // on a seeded visit and OKAY on the others, so it stores an error code and
  // OKAY in turn; SLVERR and DECERR alternate across entries from a seeded
  // phase. With `errored_last` the final access is its entry's errored one.
  protected function void sweep_error_plan(int unsigned slots, int unsigned pushes,
                                           bit errored_last, ref ocah_axi_resp_e plan[]);
    int unsigned phase = $urandom_range(1);
    plan = new[pushes];
    foreach (plan[j]) plan[j] = OCAH_AXI_RESP_OKAY;
    for (int unsigned entry = 0; entry < slots; entry++) begin
      int unsigned visits = (pushes - entry + slots - 1) / slots;
      int unsigned visit = entry + slots * $urandom_range(visits - 1);
      if (errored_last && entry == (pushes - 1) % slots) visit = pushes - 1;
      plan[visit] = ((entry + phase) % 2 == 0) ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_DECERR;
    end
  endfunction

  // A seeded beat address: bits above the responder window and a beat inside
  // it.
  protected function bit [63:0] sweep_beat(dtp_j2a_target_t t);
    return random_upper_addr(t) | random_target_aligned_addr(t, t.default_size);
  endfunction

  // A seeded address and transfer size for one OKAY access of the sweep: a
  // seeded beat; on an AXI4 port a seeded byte offset inside it with a seeded
  // size the offset is aligned to, on an AXI-Lite port the beat address with
  // a seeded size up to the beat.
  protected function void sweep_addr(dtp_j2a_target_t t, output bit [63:0] addr,
                                     output int unsigned size);
    int unsigned offset = (t.bus_type == 1'b0) ? $urandom_range(t.beat_bytes - 1) : 0;
    int unsigned sizes[$];
    for (int unsigned s = 0; s <= t.default_size; s++) begin
      if (offset % size_bytes(s) == 0) sizes.push_back(s);
    end
    addr = sweep_beat(t) + 64'(offset);
    size = sizes[$urandom_range(sizes.size() - 1)];
  endfunction

  // One checked SINGLE_OP write of seeded data and strobes; with a non-OKAY
  // `resp` the responder answers the full-beat write with that code and drops
  // it.
  protected task sweep_write(dtp_j2a_target_t t, ocah_axi_resp_e resp, string context_s);
    dtp_j2a_status_e op_status;
    bit [63:0] addr;
    int unsigned size;
    if (resp == OCAH_AXI_RESP_OKAY) begin
      bit [7:0] wstrb;
      sweep_addr(t, addr, size);
      wstrb = 8'($urandom_range(int'(full_wstrb(size)), 1));
      write_target_single_and_check(t, addr, rand_data(t), op_status, size, wstrb, context_s);
    end else begin
      bit [63:0] prior_word;
      size = t.default_size;
      addr = sweep_beat(t);
      prior_word = read_target_mem_int(t, addr, size);
      arm_target_error(t, addr, resp, .for_read(1'b0), .for_write(1'b1));
      write_target_single_expect_status(t, addr, rand_data(t), axi_resp_to_status(resp), op_status,
                                        size, full_wstrb(size), context_s);
      check_target_memory(t, addr, prior_word, size, {context_s, ".no_write_side_effect"});
    end
    operation_count++;
  endtask

  // One checked SINGLE_OP read of a seeded preloaded beat; with a non-OKAY
  // `resp` the responder answers the full-beat read with that code and a
  // second seeded word (CHK-J2A-ERR-RDATA).
  protected task sweep_read(dtp_j2a_target_t t, ocah_axi_resp_e resp, string context_s);
    dtp_j2a_status_e op_status;
    bit [63:0] addr, rdata;
    int unsigned size;
    if (resp == OCAH_AXI_RESP_OKAY) begin
      bit [63:0] word = rand_data(t);
      int unsigned lane;
      sweep_addr(t, addr, size);
      lane = int'(addr % t.beat_bytes);
      write_target_mem_int(t, addr - 64'(lane), word, t.default_size);
      read_target_single_and_check(t, addr, word >> (8 * lane), op_status, size, context_s);
    end else begin
      bit [63:0] preload = rand_nonzero_data(t);
      bit [63:0] errored = random_distinct_word(t, {preload});
      addr = sweep_beat(t);
      write_target_mem_int(t, addr, preload, t.default_size);
      arm_target_error(t, addr, resp, .for_read(1'b1), .for_write(1'b0), .arm_expected(1'b1),
                       .err_rdata(errored));
      read_target_single_expect_status(t, addr, axi_resp_to_status(resp), op_status, rdata,
                                       t.default_size, context_s);
      check_error_rdata(t, addr, rdata, resp, preload, errored, t.default_size, context_s);
    end
    operation_count++;
  endtask

  // CHK-J2A-CDC-CLEAR and CHK-J2A-ABORT-FSM on every bridge after the
  // `label` reset.
  protected function void record_sweep_clear(string label);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      string context_s = $sformatf("cdc_fifo_entry_sweep.%s.%s", t.name, label);
      void'(record_cdc_clear(
          t, {context_s, ".cdc_clear"}, {"tck-side isolate-and-clear after the ", label}
      ));
      void'(record_abort_check(
          DtpJ2aAbortFsmCheckId,
          {
            context_s, ".fsm_idle"
          },
          64'(bridge_fsm_idle(
              t
          )),
          64'd1,
          {
            "after the ", label
          }
      ));
    end
  endfunction

  protected task run_cdc_fifo_entry_sweep();
    ocah_axi_resp_e write_plan[], read_plan[];
    dtp_j2a_status_e st;
    bit [63:0] rdata;
    reset_to_rti();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      int unsigned slots = cdc_fifo_slots(t);
      // Two full rotations plus two pushes: every entry is written at least
      // twice, entries 0 and 1 three times.
      int unsigned pushes = 2 * slots + 2;
      sweep_error_plan(slots, pushes, 1'b0, write_plan);
      sweep_error_plan(slots, pushes, 1'b1, read_plan);
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s slots=%0d writes=%0d reads=%0d write_plan=%p read_plan=%p",
                i + 1,
                NumTargets,
                t.name,
                slots,
                pushes,
                pushes,
                write_plan,
                read_plan
                ), UVM_LOW)
      for (int unsigned push = 0; push < pushes; push++) begin
        string context_s = $sformatf("cdc_fifo_entry_sweep.%s.%0d", t.name, push);
        sweep_write(t, write_plan[push], {context_s, ".write"});
        sweep_read(t, read_plan[push], {context_s, ".read"});
      end
    end
    // TAP reset while every request entry holds its last payload.
    clear_cdc_clear_seen();
    reset_to_rti();
    repeat (AbortSettleTck) step(1'b0);
    record_sweep_clear("tap_reset");
    // System reset while every response entry holds its last payload.
    clear_cdc_clear_seen();
    pulse_system_reset($urandom_range(3, 1));
    repeat (AbortSettleTck) step(1'b0);
    record_sweep_clear("system_reset");
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      string context_s = $sformatf("cdc_fifo_entry_sweep.%s", t.name);
      // The last read of the sweep left an error code, which the TAP reset
      // returns to the op field's reset value; the system reset on the idle
      // bridge discards nothing and keeps it. The TAP reset also selects
      // IDCODE, so the poll loads the SINGLE_OP instruction first.
      load_ir(IrWidth'(t.single_op_instr));
      poll_single(t, st, rdata, {context_s, ".status_reset"}, AbortRecoveryPolls);
      void'(record_abort_check(
          DtpJ2aAbortRecoveryCheckId,
          {
            context_s, ".status_reset"
          },
          64'(st),
          64'(DTP_J2A_SUCCESS),
          $sformatf(
              "status=%s max_captures=%0d after the TAP and system resets",
              st.name(),
              AbortRecoveryPolls)
      ));
      recover_target(t, sweep_beat(t), rand_data(t), 1'b0, context_s, status);
      recover_target(t, sweep_beat(t), rand_data(t), 1'b1, context_s, status);
      operation_count += 2;
    end
  endtask

  // CHK-AXI-NONVAC on every bridge: that bridge's responder completed at
  // least one burst this pass and no armed expectation was left unconsumed
  // on its recorder (a tied-off, idle, or always-OKAY bridge cannot satisfy
  // this).
  task body();
    seed_scenario_rng();
    begin_all_bridges_pass();
    case (scenario)
      "backpressure_aw_before_w":   run_backpressure_aw_before_w();
      "backpressure_long_stall":    run_backpressure_long_stall();
      "backpressure_abort_at_data_w": begin
        run_reset_abort("abort_w", "w", 3, 64'h1111, 0);
        run_series_abort("abort_w_series", 3, 4);
      end
      // The responder accepts W only after AW, so holding AW keeps both
      // channels from handshaking before the reset.
      "cdc_clear_abort_narrow_reset_mid_xaction": begin
        run_reset_abort("narrow_reset", "aw", 1, 64'h2222, 8, 1'b1);
        run_read_response_abort("narrow_reset_read", 12);
        run_address_phase_aborts("address_phase", 3, 27);
        run_tap_reset_orphans();
      end
      "cdc_clear_abort_back_to_back_reset": run_back_to_back_reset();
      "decode_error_decerr_write":  run_decode_error_decerr_write();
      "decode_error_decerr_read":   run_decode_error_decerr_read();
      "decode_error_mixed":         run_decode_error_mixed();
      "series_corner_all_bridges": begin
        run_series_corner_all_bridges();
        run_cdc_fifo_entry_sweep();
      end
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown JTAG2AXI robustness scenario %s", scenario))
    endcase
    emit_all_bridges_nonvacuity(scenario);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      clear_target_error(t);
      clear_target_backpressure(t);
    end
    enable_all_debug();
    `uvm_info(get_type_name(),
              $sformatf(
                  "JTAG2AXI robustness scenario complete: scenario=%s operations=%0d status=%s",
                  scenario, operation_count, status.name()), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_robustness_test_seq
