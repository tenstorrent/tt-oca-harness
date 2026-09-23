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
//     AW request pulse, and the memory matches the stimulus intent;
//   * backpressure_long_stall — AW+W stalls sized in status-poll units so
//     the bridge reports BUSY_OR_FULL before settling, a stalled-AR read
//     of a preloaded value, then zero-strobe and memory-window-boundary
//     corner writes once the stalls are cleared;
//   * backpressure_abort_at_data_w / cdc_clear_abort_narrow_reset_mid_xaction
//     — a write held on the W (or AW) channel by a READY stall that is
//     released only after a system-reset pulse, so the reset lands while
//     the bridge FSM is observed mid-flight through dtp_tb_if; the FSM's
//     return to IDLE, the CDC's TCK-side clear, the absence of an escaped
//     write, and the recovery status are recorded per bridge and the pass
//     is judged once every bridge has left its evidence;
//   * cdc_clear_abort_back_to_back_reset — two adjacent reset pulses with
//     seeded spacing, then recovery write and read on every bridge;
//   * decode_error_decerr_{write,read} / decode_error_mixed — one-shot
//     DECERR injections per bridge (the DTP boundary has no address
//     decoder: each target's responder injects the response) with OKAY
//     recovery accesses; the errored write leaves its slot unchanged and
//     the errored read's SINGLE_OP capture returns the errored beat's
//     RDATA (CHK-J2A-ERR-RDATA); the mixed flavor brackets the bad read
//     between good write/read accesses at a neighbouring mapped address.
//     Credits are armed direction-exact so every armed DECERR is consumed
//     by a real bus response (CHK-AXI-NONVAC + the scoreboard's
//     check_phase drain);
//   * series_corner_all_bridges — incrementing and fixed-address write
//     series with their SERIES_CTRL address captures, one faulted beat whose
//     status holds until SERIES_CTRL.reset, and the three bridges' beats
//     interleaved.
//
// Every random choice draws from the per-pass seeded stream and is logged
// with its loop context for replay. The test plumbs the per-target handle
// bundles (index-aligned arrays below); select_target() swaps the
// base-class handles so every inherited helper acts on the bridge under
// test. The body always clears injections and backpressure on all bridges
// and re-enables debug on exit.

class dtp_jtag2axi_robustness_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_robustness_test_seq)

  // Scenario selection (set by the test before start()).
  string scenario = "backpressure_aw_before_w";

  // Final settled status for the summary; pass/fail is owned by the
  // inline checks and the scoreboard evidence.
  dtp_j2a_status_e status = DTP_J2A_SUCCESS;
  int unsigned operation_count = 0;

  // Robustness address plan (mirrors the cocotb layout): 0x400-spaced
  // per-operation slots off one base, inside the 64 KiB responder window;
  // series streams in a disjoint window.
  localparam bit [63:0] RobustBase = 64'h3800;
  localparam bit [63:0] SeriesBase = 64'h5000;

  localparam int unsigned NumTargets = 3;

  // Per-target evidence bundles, index-aligned with targets[] in the
  // cocotb ROBUST_TARGETS order (smc_axi, smc_otp, sep_otp); plumbed by
  // the test. Class handles cannot live inside dtp_j2a_target_t; the
  // responders come from the virtual sequencer by target name.
  dtp_j2a_target_t     targets[NumTargets];
  ocah_axi_config      target_cfgs[NumTargets];
  ocah_axi_checker     target_evidence[NumTargets];
  ocah_axi_ref_model   target_ref_models[NumTargets];
  dtp_axi_read_history target_read_history[NumTargets];

  function new(string name = "dtp_jtag2axi_robustness_test_seq");
    super.new(name);
    targets[0] = target_smc_axi();
    targets[1] = target_smc_otp();
    targets[2] = target_sep_otp();
  endfunction

  // Swap the base-class handles to the indexed bridge and return its
  // geometry: every inherited helper then acts on that bridge.
  protected function dtp_j2a_target_t select_target(int unsigned idx);
    axi_cfg       = target_cfgs[idx];
    axi_evidence  = target_evidence[idx];
    axi_ref_model = target_ref_models[idx];
    axi_reads     = target_read_history[idx];
    return targets[idx];
  endfunction

  protected function bit [63:0] robust_addr(dtp_j2a_target_t t, int unsigned idx);
    return RobustBase + idx * 64'h400 + t.beat_bytes;
  endfunction

  protected function bit [63:0] rand_data(dtp_j2a_target_t t);
    return {$urandom, $urandom} & bit_mask(t.data_width);
  endfunction

  // TAP reset into Run-Test/Idle (scans start from RTI).
  protected task reset_to_rti();
    tap_reset();
    step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after TLR->RTI step");
  endtask

  // One status-poll scan's duration in system-clock cycles: the DR shift
  // plus the ~8 TCK the VIP spends navigating RTI -> Shift-DR -> RTI per
  // poll. An overestimate silently pushes the settle point past the
  // MaxStatusPolls completion bound.
  protected function int unsigned poll_scan_sys_cycles(dtp_j2a_target_t t);
    return (single_op_len(t) + 8) * tck_sys_ratio();
  endfunction

  // READY stall sized in status-poll units, so the operation stays
  // outstanding into the polls and the bridge reports BUSY_OR_FULL before
  // the settled status. The responder applies an AW+W stall's two channel
  // patterns back to back and the AW pattern's phase adds up to one more
  // stall window, so the settle point lands near 2*scans polls — callers
  // cap scans at 5 so completion stays inside the MaxStatusPolls=16
  // budget with margin (the cocotb pause generators run phase-free in
  // parallel and can afford a larger scan budget there).
  protected function int unsigned stall_beyond_polls(dtp_j2a_target_t t, int unsigned scans);
    return scans * poll_scan_sys_cycles(t) + $urandom_range(64, 16);
  endfunction

  // Post-completion request-activity assertion (cocotb
  // expect_target_activity parity): the checked operation must have
  // produced an AW (write) or AR (read) request pulse on the bridge.
  protected function void expect_activity(dtp_j2a_target_t t, int unsigned before_aw,
                                          int unsigned before_ar, bit is_read, string context_s);
    int unsigned aw, w, ar;
    sample_activity(t, aw, w, ar);
    if (is_read ? (ar <= before_ar) : (aw <= before_aw))
      `uvm_error("jtag2axi_activity_chk", $sformatf(
                 "%s: expected %s %s activity (aw=%0d->%0d ar=%0d->%0d)",
                 context_s,
                 t.name,
                 is_read ? "AR" : "AW",
                 before_aw,
                 aw,
                 before_ar,
                 ar
                 ))
    else
      `uvm_info("jtag2axi_activity_chk", $sformatf(
                "%s: %s activity confirmed (aw=%0d->%0d ar=%0d->%0d)",
                context_s,
                t.name,
                before_aw,
                aw,
                before_ar,
                ar
                ), UVM_MEDIUM)
  endfunction

  // Backpressured checked single write. The READY stall outlasts the first
  // status poll, so the bridge is observed on the stalled path before the
  // write settles at SUCCESS with the memory matching the stimulus intent
  // and the request on the bus.
  protected task write_with_backpressure(dtp_j2a_target_t t, string channels[$],
                                         int unsigned stall_cycles, string context_s);
    dtp_j2a_status_e op_status;
    bit [63:0] rdata;
    int unsigned aw0, w0, ar0;
    int unsigned size = t.default_size;
    bit [63:0]   addr = robust_addr(t, operation_count + 1);
    bit [63:0]   data = (64'h1020_3040_5060_7080 ^ addr) & data_mask(size);
    configure_target_backpressure(t, channels, stall_cycles);
    sample_activity(t, aw0, w0, ar0);
    issue_single(t, DTP_J2A_OP_WRITE, addr, data, full_wstrb(size), size, 1'b0);
    observe_stall(t, 1'b0, context_s);
    poll_single(t, op_status, rdata, context_s);
    check_status({context_s, ".status"}, op_status, DTP_J2A_SUCCESS);
    check_target_memory(t, addr, data, size, context_s);
    expect_activity(t, aw0, ar0, 1'b0, context_s);
    clear_target_backpressure(t);
    operation_count++;
  endtask

  // Backpressured checked single read of a backdoor-preloaded value, the
  // bridge observed on the stalled read path first.
  protected task read_with_backpressure(dtp_j2a_target_t t, string channels[$],
                                        int unsigned stall_cycles, string context_s);
    dtp_j2a_status_e op_status;
    bit [63:0] rdata;
    int unsigned aw0, w0, ar0;
    int unsigned size = t.default_size;
    bit [63:0]   addr = robust_addr(t, operation_count + 1);
    bit [63:0]   data = (64'hABCD_EF01_2345_6789 ^ addr) & data_mask(size);
    write_target_mem_int(t, addr, data, size);
    configure_target_backpressure(t, channels, stall_cycles);
    sample_activity(t, aw0, w0, ar0);
    issue_single(t, DTP_J2A_OP_READ, addr, '0, '0, size, 1'b0);
    observe_stall(t, 1'b1, context_s);
    poll_single(t, op_status, rdata, context_s);
    check_status({context_s, ".status"}, op_status, DTP_J2A_SUCCESS);
    if ((rdata & data_mask(size)) !== data)
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "%s: rdata 0x%0h != expected 0x%0h (addr=0x%0h)",
                 context_s,
                 rdata & data_mask(
                     size
                 ),
                 data,
                 addr
                 ))
    expect_activity(t, aw0, ar0, 1'b1, context_s);
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
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s WREADY stall=%0d", i + 1, NumTargets, t.name, stall), UVM_LOW)
      write_with_backpressure(t, '{"w"}, stall, $sformatf("aw_before_w.%s", t.name));
    end
  endtask

  protected task run_backpressure_long_stall();
    int unsigned order[NumTargets] = '{0, 1, 2};
    // Seeded target-order shuffle: each loop stresses a different
    // bridge ordering.
    for (int unsigned i = NumTargets - 1; i > 0; i--) begin
      int unsigned j = $urandom_range(i);
      int unsigned tmp = order[i];
      order[i] = order[j];
      order[j] = tmp;
    end
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(order[i]);
      dtp_j2a_status_e op_status;
      int unsigned size = t.default_size;
      // A stall outlasting the scan cadence keeps the op outstanding
      // into the status polls, so the bridge reports BUSY_OR_FULL
      // before the settled status; the seeded scan budget spreads the
      // settle point across the early-poll and late-poll classes.
      int unsigned scans = ($urandom_range(1) == 0) ? 2 : 5;
      int unsigned stall = stall_beyond_polls(t, scans);
      bit [63:0] boundary_addr = 64'h1_0000 - size_bytes(size);
      bit [63:0] boundary_data = rand_data(t) & data_mask(size);
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s scans=%0d stall=%0d", i + 1, NumTargets, t.name, scans, stall),
                UVM_LOW)
      write_with_backpressure(t, '{"aw", "w"}, stall, $sformatf("long_stall.write.%s", t.name));
      read_with_backpressure(t, '{"ar"}, stall_beyond_polls(t, 2), $sformatf(
                             "long_stall.read.%s", t.name));
      // Zero-strobe and window-boundary singles: legal corner
      // operands exercised once the stalls are cleared.
      write_target_single_and_check(t, robust_addr(t, i + 41), 64'($urandom), op_status, size,
                                    8'h00, $sformatf("long_stall.wstrb_none.%s", t.name));
      write_target_single_and_check(t, boundary_addr, boundary_data, op_status, size, full_wstrb(
                                    size), $sformatf("long_stall.boundary.%s", t.name));
    end
  endtask

  // Stalled write, then a system-reset pulse, then a recovery write.
  // The 64 idle TCK between the scan and the reset outlast the bounded
  // stall, so the transaction completes before the reset lands: a stall
  // long enough for a true mid-flight abort leaves the recovery write
  // BUSY_OR_FULL indefinitely.
  // Reset-abort stimulus: the READY stall outlasts everything and is released
  // after the reset, so the write sits on the bus throughout the reset pulse.
  localparam int unsigned AbortHoldCycles = 100000;
  // TCK cycles for the bridge FSM to leave IDLE after the SINGLE_OP
  // Update-DR, and to return to IDLE after the reset.
  localparam int unsigned AbortMidFlightTck = 64;
  localparam int unsigned AbortSettleTck = 128;
  // TCK cycles after a reset pulse for the CDC controller to run its
  // TCK-side isolate-and-clear on an idle bridge.
  localparam int unsigned AbortCdcClearTck = 32;

  // Record one judgement on the target's evidence recorder and report it
  // without stopping the pass, so every bridge leaves evidence.
  protected function bit record_abort_check(string check_id, string name, bit [63:0] observed,
                                            bit [63:0] expected, string context_s);
    bit ok = (observed == expected);
    if (axi_evidence != null)
      void'(axi_evidence.expect_equal(check_id, observed, expected, {name, " ", context_s}));
    if (!ok)
      `uvm_error("jtag2axi_abort_chk", $sformatf(
                 "%s: observed 0x%0h, expected 0x%0h (%s)", name, observed, expected, context_s))
    else
      `uvm_info("jtag2axi_abort_chk", $sformatf(
                "%s: 0x%0h as expected (%s)", name, observed, context_s), UVM_MEDIUM)
    return ok;
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

  // System reset while the bridge is observed mid-flight on a held write;
  // `recovered` is 1 when the bridge's status settled to SUCCESS afterwards
  // and the recovery write ran.
  protected task reset_abort_mid_flight(
      dtp_j2a_target_t t, string channel, int unsigned reset_cycles, int unsigned addr_idx,
      bit [63:0] recovery_xor, string context_s, output bit recovered);
    int unsigned size = t.default_size;
    bit [63:0] addr = robust_addr(t, addr_idx);
    bit [63:0] data = rand_data(t) & data_mask(size);
    bit [63:0] prior_word = read_target_mem_int(t, addr, size);
    bit idle;
    dtp_j2a_status_e st;
    bit [63:0] rdata;
    bit mid_flight;
    configure_target_backpressure(t, '{channel}, AbortHoldCycles);
    issue_single(t, DTP_J2A_OP_WRITE, addr, data, full_wstrb(size), size, 1'b0);
    wait_bridge_fsm(t, 1'b0, AbortMidFlightTck, idle);
    mid_flight = !idle && bridge_op_pending(t);
    void'(record_abort_check(
        DtpJ2aAbortMidFlightCheckId,
        {
          context_s, ".mid_flight"
        },
        64'(mid_flight),
        64'd1,
        $sformatf(
            "idle=%0d write_path=%0d", idle, bridge_fsm_on_path(t, 1'b0))
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
    void'(record_abort_check(
        DtpJ2aCdcClearCheckId,
        {
          context_s, ".cdc_clear"
        },
        64'(cdc_clear_seen(
            t
        )),
        64'd1,
        "tck-side isolate-and-clear"
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
    poll_single(t, st, rdata, {context_s, ".recovery"});
    recovered = record_abort_check(DtpJ2aAbortRecoveryCheckId, {context_s, ".recovery_status"},
                                   64'(st), 64'(DTP_J2A_SUCCESS), "after the mid-flight reset");
    status = st;
    if (recovered) verify_target_recovery(t, addr + 64'h200, data ^ recovery_xor, 1'b0, context_s);
    operation_count++;
  endtask

  protected task run_reset_abort(string label, string channel, int unsigned reset_cycles_hi,
                                 bit [63:0] recovery_xor, int unsigned addr_offset);
    string stuck = "";
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      bit recovered;
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s %s: system reset while %s is held",
                i + 1,
                NumTargets,
                t.name,
                label,
                channel
                ), UVM_LOW)
      reset_abort_mid_flight(t, channel, $urandom_range(reset_cycles_hi, 1), i + 1 + addr_offset,
                             recovery_xor, $sformatf("%s.%s", label, t.name), recovered);
      if (!recovered) stuck = {stuck, (stuck == "") ? "" : ", ", t.name};
    end
    if (stuck != "")
      `uvm_error("jtag2axi_abort_chk", $sformatf(
                 "%s: %s stayed BUSY_OR_FULL after the mid-flight reset", label, stuck))
  endtask

  protected task run_back_to_back_reset();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      bit [63:0] addr = robust_addr(t, i + 17);
      // Seeded per-pass payload and pulse widths: each loop stresses a
      // different back-to-back reset spacing.
      bit [63:0] data = rand_data(t);
      `uvm_info(get_type_name(), $sformatf(
                "[%0d/%0d] target=%s back-to-back reset", i + 1, NumTargets, t.name), UVM_LOW)
      clear_cdc_clear_seen();
      pulse_system_reset($urandom_range(2, 1));
      pulse_system_reset($urandom_range(3, 1));
      // The CDC's TCK-side isolate-and-clear runs only while TCK runs.
      repeat (AbortCdcClearTck) step(1'b0);
      void'(record_abort_check(
          DtpJ2aCdcClearCheckId,
          $sformatf(
              "back_to_back_reset.%s.cdc_clear", t.name
          ),
          64'(cdc_clear_seen(
              t
          )),
          64'd1,
          "tck-side isolate-and-clear after two resets"
      ));
      verify_target_recovery(t, addr, data, 1'b0, $sformatf("back_to_back_reset.%s", t.name));
      verify_target_recovery(t, addr, data, 1'b1, $sformatf("back_to_back_reset_read.%s", t.name));
      operation_count++;
    end
  endtask

  protected task run_decode_error_decerr_write();
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      dtp_j2a_status_e op_status;
      int unsigned size = t.default_size;
      bit [63:0]   addr = robust_addr(t, i + 25);
      bit [63:0] mem_before, mem_after;
      arm_target_error(t, addr, OCAH_AXI_RESP_DECERR, 1'b0, 1'b1);
      mem_before = read_target_mem_int(t, addr, size);
      write_target_single_expect_status(t, addr, 64'($urandom) ^ 64'(i + 1), DTP_J2A_DECERR,
                                        op_status, size, full_wstrb(size), $sformatf(
                                        "decerr_write.%s", t.name));
      // The responder drops an armed write beat, so the error slot keeps
      // its prior value.
      mem_after = read_target_mem_int(t, addr, size);
      if (mem_after !== mem_before)
        `uvm_error("jtag2axi_mem_chk", $sformatf(
                   "decerr_write.%s.no_write_side_effect: memory at 0x%0h changed 0x%0h -> 0x%0h",
                   t.name,
                   addr,
                   mem_before,
                   mem_after
                   ))
      // Seeded per-pass recovery payload.
      verify_target_recovery(t, addr + 64'h200, 64'($urandom) ^ 64'(i + 1), 1'b0, $sformatf(
                             "decerr_write.%s", t.name));
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
      write_target_mem_int(t, addr, preload, size);
      arm_target_error(t, addr, OCAH_AXI_RESP_DECERR, 1'b1, 1'b0);
      read_target_single_expect_status(t, addr, DTP_J2A_DECERR, op_status, rdata, size, $sformatf(
                                       "decerr_read.%s", t.name));
      check_error_rdata(t, addr, rdata, OCAH_AXI_RESP_DECERR, preload, size, $sformatf(
                        "decerr_read.%s", t.name));
      // Seeded per-pass recovery payload.
      verify_target_recovery(t, addr + 64'h200, 64'($urandom) ^ 64'(i + 1), 1'b1, $sformatf(
                             "decerr_read.%s", t.name));
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
      // Read-only DECERR arming at the unmapped slot: injection and
      // expectation stay direction-exact so no armed credit dangles
      // (the write side of that slot is never accessed).
      arm_target_error(t, bad_addr, OCAH_AXI_RESP_DECERR, 1'b1, 1'b0);
      read_target_single_expect_status(t, bad_addr, DTP_J2A_DECERR, op_status, rdata, size,
                                       $sformatf("mixed.bad_read.%s", t.name));
      read_target_single_and_check(t, good_addr, good_data, op_status, size, $sformatf(
                                   "mixed.good_read.%s", t.name));
      operation_count++;
    end
  endtask

  // --- series corner legs ---------------------------------------------------
  // Aligned base of one series leg's window: one 0x400 window per bridge,
  // one 0x100 leg per series.
  protected function bit [63:0] series_corner_base(int unsigned idx, int unsigned leg);
    return SeriesBase + (idx + 1) * 64'h400 + leg * 64'h100;
  endfunction

  // CHK-J2A-FAULT-STATUS on a SERIES_CTRL capture, recorded and checked.
  protected function void record_series_status(dtp_j2a_target_t t, dtp_j2a_status_e observed,
                                               dtp_j2a_status_e expected, string context_s);
    if (axi_evidence != null)
      void'(axi_evidence.expect_equal(
          DtpJ2aFaultStatusCheckId,
          64'(observed),
          64'(expected),
          $sformatf(
              "%s target=%s", context_s, t.name)
      ));
    check_status(context_s, observed, expected);
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
    observed = read_target_mem_int(t, addr, size);
    if (observed !== data)
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "%s.mem: memory 0x%0h != written 0x%0h (addr=0x%0h)",
                 context_s,
                 observed,
                 data,
                 addr
                 ))
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
    check_series_addr(t, base + beats * t.beat_bytes, size,
                      $sformatf("series_corner.incr.%s", t.name), sstatus);
    record_series_status(t, sstatus, DTP_J2A_SUCCESS, $sformatf("series_corner.incr.%s", t.name));
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    for (int unsigned beat = 0; beat < beats; beat++)
      series_corner_beat(t, addr, rand_data(t) & data_mask(size), size, 1'b0,
                         $sformatf("series_corner.fixed.%s.%0d", t.name, beat));
    check_series_addr(t, addr, size, $sformatf("series_corner.fixed.%s", t.name), sstatus);
    record_series_status(t, sstatus, DTP_J2A_SUCCESS, $sformatf("series_corner.fixed.%s", t.name));
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
    arm_target_error(t, fault_addr, resp, 1'b0, 1'b1);
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
      observed = read_target_mem_int(t, addr, size);
      expected_word = (beat == fault_beat) ? fault_before : data;
      if (observed !== expected_word)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "%s.%s: memory 0x%0h != expected 0x%0h (addr=0x%0h)",
                   context_s,
                   (beat == fault_beat) ? "mem_dropped" : "mem",
                   observed,
                   expected_word,
                   addr
                   ))
      // The capture right after the faulted beat carries the code.
      if (beat == fault_beat) begin
        check_series_addr(t, addr + t.beat_bytes, size, {context_s, ".faulted"}, sstatus);
        record_series_status(t, sstatus, expected, {context_s, ".faulted"});
      end
      operation_count++;
    end
    // The code holds across the clean beats that followed the fault.
    check_series_addr(t, base + beats * t.beat_bytes, size,
                      $sformatf("series_corner.sticky.%s", t.name), sstatus);
    record_series_status(t, sstatus, expected, $sformatf("series_corner.sticky.%s.held", t.name));
    clear_target_error(t);
    series_ctrl_op(t, DTP_J2A_OP_NOP, '0, size, 0, 1'b1);
    clear_addr = base + (beats + 1) * t.beat_bytes;
    series_ctrl_op(t, DTP_J2A_OP_WRITE, clear_addr, size);
    series_corner_beat(t, clear_addr, rand_data(t) & data_mask(size), size, 1'b1,
                       $sformatf("series_corner.sticky.%s.cleared", t.name));
    check_series_addr(t, clear_addr + t.beat_bytes, size,
                      $sformatf("series_corner.sticky.%s.cleared", t.name), sstatus);
    record_series_status(t, sstatus, DTP_J2A_SUCCESS,
                         $sformatf("series_corner.sticky.%s.cleared", t.name));
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
                           t.default_size, 1'b1,
                           $sformatf("series_corner.interleaved.%s.%0d", t.name, beat));
      end
    end
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      int unsigned size = t.default_size;
      check_series_addr(t, bases[i] + beats * t.beat_bytes, size,
                        $sformatf("series_corner.interleaved.%s", t.name), sstatus);
      record_series_status(t, sstatus, DTP_J2A_SUCCESS,
                           $sformatf("series_corner.interleaved.%s", t.name));
      for (int unsigned beat = 0; beat < beats; beat++) begin
        bit [63:0] addr = bases[i] + beat * t.beat_bytes;
        bit [63:0] observed = read_target_mem_int(t, addr, size);
        if (observed !== words[i][beat])
          `uvm_error("jtag2axi_data_chk", $sformatf(
                     "series_corner.interleaved.%s.final#%0d: memory 0x%0h != written 0x%0h (addr=0x%0h)",
                     t.name,
                     beat,
                     observed,
                     words[i][beat],
                     addr
                     ))
      end
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

  // CHK-AXI-NONVAC on every bridge: that bridge's responder completed at
  // least one burst this pass and no armed expectation was left unconsumed
  // on its recorder (a tied-off, idle, or always-OKAY bridge cannot satisfy
  // this).
  protected function void emit_robustness_nonvacuity(string label);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      int unsigned unconsumed = 0;
      int unsigned bursts = bursts_since_baseline(targets[i]);
      if (target_cfgs[i] != null)
        unconsumed = target_cfgs[i].pending_expected_resp()
                           + target_cfgs[i].pending_expected_writes()
                           + target_cfgs[i].pending_expected_reads();
      if (target_evidence[i] != null)
        void'(target_evidence[i].expect_true(
            "CHK-AXI-NONVAC",
            (bursts > 0) && (unconsumed == 0),
            $sformatf(
                "scenario=%s target=%s responder_bursts=%0d operations=%0d credits_unconsumed=%0d",
                label,
                targets[i].name,
                bursts,
                operation_count,
                unconsumed)
        ));
    end
  endfunction

  task body();
    seed_scenario_rng();
    foreach (target_cfgs[i]) begin
      if (target_cfgs[i] == null || target_evidence[i] == null || target_ref_models[i] == null
              || target_read_history[i] == null)
        `uvm_fatal(get_type_name(), $sformatf(
                   "robustness sequence needs all target bundles plumbed (index %0d)", i))
    end
    void'(select_target(0));
    enable_all_debug();
    reset_to_rti();
    case (scenario)
      "backpressure_aw_before_w":   run_backpressure_aw_before_w();
      "backpressure_long_stall":    run_backpressure_long_stall();
      "backpressure_abort_at_data_w": run_reset_abort("abort_w", "w", 3, 64'h1111, 0);
      "cdc_clear_abort_narrow_reset_mid_xaction":
                run_reset_abort("narrow_reset", "aw", 1, 64'h2222, 8);
      "cdc_clear_abort_back_to_back_reset": run_back_to_back_reset();
      "decode_error_decerr_write":  run_decode_error_decerr_write();
      "decode_error_decerr_read":   run_decode_error_decerr_read();
      "decode_error_mixed":         run_decode_error_mixed();
      "series_corner_all_bridges":  run_series_corner_all_bridges();
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown JTAG2AXI robustness scenario %s", scenario))
    endcase
    emit_robustness_nonvacuity(scenario);
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
