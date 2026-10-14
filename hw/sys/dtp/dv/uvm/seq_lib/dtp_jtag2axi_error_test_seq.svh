// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI error and error-path security scenarios for the DTP SV-UVM flow —
// the SV analogue of the cocotb dtp_jtag2axi_error_test_seq.
// One parameterized sequence, selected by `scenario`, against the target
// named by `target_name` (SMC fabric or either OTP AXI-Lite port; all
// three responders are shared ocah_axi_vip slave agents):
//
//   * error_single_write / error_single_read — one-shot SLVERR then DECERR
//     injections at beat-aligned addresses with randomized payloads: the
//     JTAG status must report the injected code, the armed non-OKAY is
//     EXPECTED for the shared scoreboard (CHK-AXI-ERR-INJ), the failed
//     write commits nothing (the shared slave responder suppresses armed
//     write beats), the failed read's SINGLE_OP capture returns the seeded
//     word the errored beat carried and not the preloaded word
//     (CHK-J2A-ERR-RDATA), and an OKAY recovery access follows every
//     injection;
//   * error_series_{no_incr,incr}_{write,read} and
//     error_series_incr_{write,read}_with_status — a 3-beat series stream
//     with the fault on the middle beat, armed once the previous beat's
//     transaction is published, since a fixed-address stream revisits the
//     fault address on every beat: good beats commit/return the expected data
//     at the expected addresses, the fault beat's write is dropped by the
//     responder, the SERIES_CTRL capture after a plain-mode good beat before
//     the fault reads SUCCESS and the capture right after the fault beat
//     carries the injected code (CHK-J2A-FAULT-STATUS), the plain modes'
//     captures and the with-status write's capture hold the beat address plus
//     one stride (CHK-J2A-SERIES-ADDR), the with-status modes' captured
//     status bit must flag the fault beat and no other (CHK-J2A-STATUS-BIT),
//     and an OKAY recovery access proves no stuck state;
//   * error_security_gating — two assert/release passes of the target's
//     lifecycle disable with an injection armed but NOT expected-armed
//     (arm_expected=0: a gated op must never reach the bus, so no credit
//     may be armed for it), flat request-activity counters across the
//     gated attempt AND after release (delayed-replay catch), then a
//     restored ungated SLVERR and DECERR, one per pass in seeded order,
//     each followed by recovery.
//
// Outside error_security_gating, every operation's port transaction, the
// fault beat's included, is the one its request carried (CHK-J2A-BUS-REQ).
// Every random choice draws from the per-pass seeded stream and is logged
// with its loop context for replay. The body always clears injections and
// re-enables debug on exit, and lands CHK-AXI-NONVAC: real operations ran
// and no armed expectation was left unconsumed (dangling intents also fail
// at the scoreboard's check_phase drain).

class dtp_jtag2axi_error_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_error_test_seq)

  // Scenario selection (set by the test before start()).
  string target_name = "smc_axi";
  string scenario    = "error_single_write";

  localparam int unsigned SeriesBeats = 3;
  // The middle beat: a committed good beat precedes and follows the fault.
  localparam int unsigned SeriesFaultBeat = 1;

  // Address plan (mirrors the cocotb layout: 0x20-spaced error slots,
  // recovery accesses in a disjoint window).
  localparam bit [63:0] ErrorBase = 64'h1800;
  localparam bit [63:0] RecoveryBase = 64'h2800;

  function new(string name = "dtp_jtag2axi_error_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return (scenario == "error_security_gating") ? "" : target_name;
  endfunction

  protected function dtp_j2a_target_t target();
    case (target_name)
      "smc_otp": return target_smc_otp();
      "sep_otp": return target_sep_otp();
      "smc_axi": return target_smc_axi();
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unsupported JTAG2AXI target %s", target_name))
        return target_smc_axi();
      end
    endcase
  endfunction

  protected function bit [63:0] slot_addr(dtp_j2a_target_t t, bit [63:0] base, int unsigned idx);
    int unsigned spacing = (t.beat_bytes > 32) ? t.beat_bytes : 32;
    return base + idx * spacing;
  endfunction

  // SLVERR or DECERR from the seeded stream, logged by the caller.
  protected function ocah_axi_resp_e rand_error_resp();
    return ($urandom_range(1) == 0) ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_DECERR;
  endfunction

  // Judge one bridge status against the injected response
  // (CHK-J2A-FAULT-STATUS); the scenario summary reports the last status
  // that disagreed.
  protected function void check_fault_status(string name, dtp_j2a_status_e observed,
                                             dtp_j2a_status_e expected, string context_s = "");
    if (observed != expected) status = observed;
    check_status(target(), name, observed, expected, context_s);
  endfunction

  // Judge one with-status capture bit (1 = the previous beat failed).
  protected function void check_status_bit(string name, bit observed, bit expected,
                                           string context_s = "");
    void'(axi_evidence.expect_equal(
        DtpJ2aStatusBitCheckId,
        64'(observed),
        64'(expected),
        $sformatf(
            "%s target=%s %s", name, target_name, context_s)
    ));
  endfunction

  // CHK-AXI-NONVAC: operations ran and every armed expectation was
  // consumed by a real bus response (unconsumed intents also fail at the
  // scoreboard's check_phase drain).
  protected function void emit_error_nonvacuity(string label, int unsigned minimum_ops);
    int unsigned unconsumed = pending_expected_credits();
    emit_nonvacuity_evidence(target(), (operation_count >= minimum_ops) && (unconsumed == 0),
                             $sformatf(
                             "scenario=%s target=%s operations=%0d credits_unconsumed=%0d",
                             label,
                             target_name,
                             operation_count,
                             unconsumed
                             ));
  endfunction

  // ------------------------------------------------------------------
  // Single-op error flows.
  // ------------------------------------------------------------------

  protected task expect_error_write(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                    ocah_axi_resp_e resp, string context_s);
    dtp_j2a_status_e op_status;
    bit [63:0] mem_before;
    arm_target_error(t, addr, resp, .for_read(1'b0), .for_write(1'b1));
    mem_before = read_target_mem_int(t, addr, t.default_size);
    single_write(t, addr, data & data_mask(t.default_size), full_wstrb(t.default_size), op_status,
                 t.default_size, .use_default_size(1'b0), .context_s(context_s));
    check_fault_status({context_s, ".status"}, op_status, axi_resp_to_status(resp), $sformatf(
                       "addr=0x%0h", addr));
    // The responder drops an armed write beat, so the error slot keeps its
    // prior value.
    check_target_memory(t, addr, mem_before, t.default_size, {context_s, ".no_write_side_effect"});
    verify_target_recovery(t, addr + 64'h400, data ^ 64'h55AA_55AA_55AA_55AA, 1'b0, context_s);
    operation_count++;
  endtask

  // One errored SINGLE_OP read and its recovery read; `recovery` returns the
  // recovery word.
  protected task expect_error_read(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                   ocah_axi_resp_e resp, bit [63:0] errored, string context_s,
                                   output bit [63:0] recovery);
    dtp_j2a_status_e op_status;
    bit [63:0] rdata;
    write_target_mem_int(t, addr, data, t.default_size);
    arm_target_error(t, addr, resp, .for_read(1'b1), .for_write(1'b0), .err_rdata(errored));
    single_read(t, addr, op_status, rdata, t.default_size, .use_default_size(1'b0),
                .context_s(context_s));
    check_fault_status({context_s, ".status"}, op_status, axi_resp_to_status(resp), $sformatf(
                       "addr=0x%0h", addr));
    check_error_rdata(t, addr, rdata, resp, data, errored, t.default_size, context_s);
    recovery = (data ^ 64'h00FF_00FF_00FF_00FF) & data_mask(t.default_size);
    verify_target_recovery(t, addr + 64'h400, recovery, 1'b1, context_s);
    operation_count++;
  endtask

  protected task run_error_single_write(dtp_j2a_target_t t);
    ocah_axi_resp_e responses[2] = '{OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR};
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP write error", t.name), UVM_LOW)
    reset_to_rti();
    foreach (responses[i]) begin
      bit [63:0] addr = slot_addr(t, ErrorBase, i + 1);
      bit [63:0] data = rand_data(t);
      log_iteration(i + 1, 2, $sformatf(
                    "write error addr=0x%08h resp=%s data=0x%0h", addr, responses[i].name(), data));
      expect_error_write(t, addr, data, responses[i], $sformatf("single_write_error#%0d", i + 1));
    end
    emit_error_nonvacuity("error_single_write", 2);
  endtask

  protected task run_error_single_read(dtp_j2a_target_t t);
    ocah_axi_resp_e responses[2] = '{OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR};
    // Every word a read of this pass returned: an errored beat's word avoids
    // them, so a stale capture cannot pass for it.
    bit [63:0] returned[$];
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP read error", t.name), UVM_LOW)
    reset_to_rti();
    foreach (responses[i]) begin
      bit [63:0] addr = slot_addr(t, ErrorBase + 64'h100, i + 1);
      bit [63:0] data = rand_nonzero_data(t);
      bit [63:0] errored = random_distinct_word(t, {data, returned});
      bit [63:0] recovery;
      log_iteration(i + 1, 2, $sformatf(
                    "read error addr=0x%08h resp=%s preload=0x%0h errored=0x%0h",
                    addr,
                    responses[i].name(),
                    data,
                    errored
                    ));
      expect_error_read(t, addr, data, responses[i], errored, $sformatf(
                        "single_read_error#%0d", i + 1), recovery);
      returned.push_back(errored);
      returned.push_back(recovery);
    end
    emit_error_nonvacuity("error_single_read", 2);
  endtask

  // ------------------------------------------------------------------
  // Series error flows (fault armed on one specific beat).
  // ------------------------------------------------------------------

  protected task run_error_series_write(dtp_j2a_target_t t, bit increment, bit with_status);
    int unsigned size = t.default_size;
    int unsigned stride = increment ? t.beat_bytes : 0;
    bit [63:0] base = slot_addr(t, ErrorBase + 64'h300, 1);
    int unsigned fault_idx = SeriesFaultBeat;
    bit [63:0] fault_addr = base + fault_idx * stride;
    ocah_axi_resp_e resp = rand_error_resp();
    bit [63:0] fault_before;
    bit [63:0] expected_addr;
    dtp_j2a_status_e sr_status;
    `uvm_info(get_type_name(),
              $sformatf("%s series %s write error%s: base=0x%08h fault_beat=%0d resp=%s", t.name,
                        increment ? "incr" : "no_incr", with_status ? " (with status)" : "", base,
                        fault_idx, resp.name()), UVM_LOW)
    reset_to_rti();
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    expected_addr = base;
    for (int unsigned idx = 0; idx < SeriesBeats; idx++) begin
      bit [63:0] data = rand_data(t) & data_mask(size);
      bit [63:0] observed;
      bit [63:0] wdata = dtp_j2a_series_wdata(t, data, expected_addr, size);
      int unsigned aw0, w0, ar0, pub0;
      bit done;
      if (idx == fault_idx) begin
        // A fixed-address stream revisits the fault address on every beat,
        // so the one-shot fault is armed once the previous beat is published.
        fault_before = read_target_mem_int(t, fault_addr, size);
        arm_target_error(t, fault_addr, resp, .for_read(1'b0), .for_write(1'b1));
      end
      pub0 = port_history(t.name).count(1'b0);
      sample_activity(t, aw0, w0, ar0);
      log_iteration(idx + 1, SeriesBeats, $sformatf(
                    "series write addr=0x%08h data=0x%0h resp=%s",
                    expected_addr,
                    data,
                    (idx == fault_idx) ? resp.name() : "OKAY"
                    ));
      if (with_status) begin
        bit [63:0] cap_rdata;
        bit cap_status;
        series_data_with_status(t, data, size, increment, cap_rdata, cap_status);
        // The captured bit reports the previous beat, so only the shift
        // after the fault beat carries a 1.
        check_status_bit($sformatf("series_write_error.status_bit#%0d", idx), cap_status,
                         (idx == fault_idx + 1), $sformatf("addr=0x%0h", expected_addr));
      end else if (increment) series_data_incr(t, data, size);
      else series_data_no_incr(t, data, size);
      wait_for_target_activity(t, aw0, w0, ar0, 1'b0, $sformatf("series_write_error.axi#%0d", idx));
      wait_port_count(t, 1'b0, pub0, done);
      if (!done)
        record_wait_timeout(t, PortWaitCycles, $sformatf("series_write_error.commit#%0d", idx));
      expect_bus_request(t, 1'b0, expected_addr, size, wdata, dtp_j2a_series_wstrb(
                         t, expected_addr, size), $sformatf("series_write_error#%0d", idx));
      // The responder drops the armed beat, so the slot keeps its prior
      // value.
      if (idx == fault_idx)
        check_target_memory(t, expected_addr, fault_before, size, $sformatf(
                            "series_write_error.mem_dropped#%0d", idx));
      else
        check_target_memory(t, expected_addr, data, size, $sformatf(
                            "series_write_error.mem#%0d", idx));
      if (idx == fault_idx || (idx < fault_idx && !with_status)) begin
        // The write advances the captured address by one stride, errored or
        // not.
        check_series_addr(t, expected_addr + stride, size, $sformatf(
                          "series_write_error.addr#%0d", idx), sr_status);
        if (idx < fault_idx)
          check_fault_status("series_write_error.pre_fault_status", sr_status, DTP_J2A_SUCCESS,
                             $sformatf("beat=%0d addr=0x%0h", idx, expected_addr));
        else
          check_fault_status("series_write_error.fault_status", sr_status, axi_resp_to_status(resp),
                             $sformatf("beat=%0d addr=0x%0h", idx, expected_addr));
      end
      expected_addr += stride;
    end
    if (with_status) begin
      // A capture-only shift returns the last beat's outcome; it writes zero
      // one slot past the stream.
      bit [63:0] cap_rdata;
      bit cap_status;
      int unsigned aw0, w0, ar0, pub0;
      bit done;
      pub0 = port_history(t.name).count(1'b0);
      sample_activity(t, aw0, w0, ar0);
      series_data_with_status(t, '0, size, 1'b0, cap_rdata, cap_status);
      wait_for_target_activity(t, aw0, w0, ar0, 1'b0, "series_write_error.axi#final");
      wait_port_count(t, 1'b0, pub0, done);
      if (!done) record_wait_timeout(t, PortWaitCycles, "series_write_error.commit#final");
      expect_bus_request(t, 1'b0, expected_addr, size, '0, dtp_j2a_series_wstrb(
                         t, expected_addr, size), "series_write_error#final");
      check_status_bit($sformatf("series_write_error.status_bit#%0d", SeriesBeats), cap_status,
                       (SeriesBeats - 1 == fault_idx), $sformatf("addr=0x%0h", expected_addr));
    end
    verify_target_recovery(t, RecoveryBase, 64'hCAFE_BABE_1234_5678, 1'b0, "series_write_error");
    operation_count += SeriesBeats;
  endtask

  protected task run_error_series_read(dtp_j2a_target_t t, bit increment, bit with_status);
    int unsigned size = t.default_size;
    int unsigned stride = increment ? t.beat_bytes : 0;
    bit [63:0] base = slot_addr(t, ErrorBase + 64'h600, 1);
    int unsigned fault_idx = SeriesFaultBeat;
    bit [63:0] fault_addr = base + fault_idx * stride;
    ocah_axi_resp_e resp = rand_error_resp();
    bit [63:0] preload[SeriesBeats];
    dtp_j2a_status_e sr_status;
    `uvm_info(get_type_name(),
              $sformatf("%s series %s read error%s: base=0x%08h fault_beat=%0d resp=%s", t.name,
                        increment ? "incr" : "no_incr", with_status ? " (with status)" : "", base,
                        fault_idx, resp.name()), UVM_LOW)
    reset_to_rti();
    foreach (preload[idx]) begin
      preload[idx] = rand_nonzero_data(t) & data_mask(size);
      write_target_mem_int(t, base + idx * stride, preload[idx], size);
    end
    if (with_status) begin
      series_read_with_status_stream(t, size, stride, base, fault_idx, resp, preload);
    end else begin
      // The errored beat's word differs from zero and from every preload, so
      // a zeroed or stale capture cannot pass for it.
      bit [63:0] errored = random_distinct_word(t, preload);
      `uvm_info(get_type_name(), $sformatf("series read errored-beat word=0x%0h", errored), UVM_LOW)
      for (int unsigned idx = 0; idx < SeriesBeats; idx++) begin
        bit [63:0] addr = base + idx * stride;
        // Without increment every beat reads the one slot the last preload
        // filled.
        bit [63:0] mem_expected = increment ? preload[idx] : preload[SeriesBeats-1];
        bit [63:0] rdata;
        int unsigned aw0, w0, ar0, pub0;
        bit done;
        // A fixed-address stream revisits the fault address on every beat,
        // so the one-shot fault is armed once the previous beat is published.
        if (idx == fault_idx)
          arm_target_error(t, fault_addr, resp, .for_read(1'b1), .for_write(1'b0),
                           .err_rdata(errored));
        series_ctrl_op(t, DTP_J2A_OP_READ, addr, size);
        pub0 = port_history(t.name).count(1'b1);
        sample_activity(t, aw0, w0, ar0);
        log_iteration(
            idx + 1, SeriesBeats, $sformatf(
            "series read addr=0x%08h resp=%s", addr, (idx == fault_idx) ? resp.name() : "OKAY"));
        // The first shift launches the read; the bridge drops the second
        // shift's request and returns the first read's data.
        series_plain_read_shift(t, size, increment, rdata);
        wait_for_target_activity(t, aw0, w0, ar0, 1'b1, $sformatf("series_read_error.axi#%0d", idx
                                 ));
        series_plain_read_shift(t, size, increment, rdata);
        wait_port_count(t, 1'b1, pub0, done);
        if (!done)
          record_wait_timeout(t, PortWaitCycles, $sformatf("series_read_error.r#%0d", idx));
        expect_bus_request(t, 1'b1, addr, size, '0, '0, $sformatf("series_read_error#%0d", idx));
        if (idx == fault_idx)
          check_error_rdata(t, addr, rdata, resp, mem_expected, errored, size, $sformatf(
                            "series_read_error.fault#%0d", idx));
        else
          check_returned_rdata(t, rdata, mem_expected, $sformatf(
                               "series_read_error.rdata#%0d addr=0x%0h", idx, addr));
        // The launched read advances the captured address by one stride,
        // errored or not; the dropped second request leaves it alone.
        check_series_addr(t, addr + stride, size, $sformatf("series_read_error.addr#%0d", idx),
                          sr_status);
        if (idx < fault_idx)
          check_fault_status("series_read_error.pre_fault_status", sr_status, DTP_J2A_SUCCESS,
                             $sformatf("beat=%0d addr=0x%0h", idx, addr));
        else if (idx == fault_idx)
          check_fault_status("series_read_error.fault_status", sr_status, axi_resp_to_status(resp),
                             $sformatf("beat=%0d addr=0x%0h", idx, addr));
      end
    end
    verify_target_recovery(t, RecoveryBase + 64'h100, 64'hDEAD_BEEF_7654_3210, 1'b1,
                           "series_read_error");
    operation_count += SeriesBeats;
  endtask

  // One plain series-data read shift; returns the captured payload.
  protected task series_plain_read_shift(dtp_j2a_target_t t, int unsigned size, bit increment,
                                         output bit [63:0] rdata);
    bit [63:0] raw;
    series_data_shift(t, increment ? t.series_data_incr_instr : t.series_data_no_incr_instr, '0,
                      size, -1, raw);
    rdata = raw & data_mask(size);
  endtask

  // Status-mode stream: shift k launches read k and returns read k-1's data
  // and outcome. A with-status shift is a real read, so one CTRL programming
  // serves the whole stream and a final capture-only shift returns the last
  // beat; the fault beat's SERIES_CTRL status is read before the next launch.
  protected task series_read_with_status_stream(
      dtp_j2a_target_t t, int unsigned size, int unsigned stride, bit [63:0] base,
      int unsigned fault_idx, ocah_axi_resp_e resp, bit [63:0] preload[]);
    bit sr_reset;
    bit [63:0] sr_addr;
    int unsigned sr_pl, sr_size;
    dtp_j2a_status_e sr_status;
    series_ctrl_op(t, DTP_J2A_OP_READ, base, size);
    for (int unsigned shift = 0; shift <= SeriesBeats; shift++) begin
      bit launching = (shift < SeriesBeats);
      bit [63:0] rdata;
      bit status_bit;
      int unsigned aw0, w0, ar0, pub0;
      bit done;
      if (launching)
        log_iteration(shift + 1, SeriesBeats, $sformatf(
                      "series read addr=0x%08h resp=%s",
                      base + shift * stride,
                      (shift == fault_idx) ? resp.name() : "OKAY"
                      ));
      if (shift == fault_idx)
        arm_target_error(t, base + fault_idx * stride, resp, .for_read(1'b1), .for_write(1'b0));
      pub0 = port_history(t.name).count(1'b1);
      sample_activity(t, aw0, w0, ar0);
      series_data_with_status(t, '0, size, launching, rdata, status_bit);
      wait_for_target_activity(t, aw0, w0, ar0, 1'b1, $sformatf("series_read_error.axi#%0d", shift
                               ));
      wait_port_count(t, 1'b1, pub0, done);
      if (!done)
        record_wait_timeout(t, PortWaitCycles, $sformatf("series_read_error.r#%0d", shift));
      expect_bus_request(t, 1'b1, base + shift * stride, size, '0, '0, $sformatf(
                         "series_read_error#%0d", shift));
      if (shift == fault_idx) begin
        read_series_ctrl(t, size, sr_reset, sr_addr, sr_pl, sr_size, sr_status);
        check_fault_status("series_read_error.fault_status", sr_status, axi_resp_to_status(resp),
                           $sformatf("beat=%0d addr=0x%0h", shift, base + shift * stride));
      end
      if (shift == 0) continue;
      check_status_bit($sformatf("series_read_error.status_bit#%0d", shift - 1), status_bit,
                       (shift - 1 == fault_idx), $sformatf("addr=0x%0h", base + (shift - 1) * stride
                       ));
      if (shift - 1 != fault_idx)
        check_returned_rdata(
            t, rdata, preload[shift-1], $sformatf(
            "series_read_error.rdata#%0d addr=0x%0h", shift - 1, base + (shift - 1) * stride));
    end
  endtask

  // ------------------------------------------------------------------
  // Error-path security gating.
  // ------------------------------------------------------------------

  protected task run_error_security_gating(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    bit [63:0] addr = slot_addr(t, ErrorBase + 64'h900, 1);
    bit [63:0] data = rand_data(t) & data_mask(size);
    // The ungated error of each pass, SLVERR and DECERR in seeded order.
    ocah_axi_resp_e ungated[2];
    if ($urandom_range(1)) ungated = '{OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR};
    else ungated = '{OCAH_AXI_RESP_DECERR, OCAH_AXI_RESP_SLVERR};
    `uvm_info(get_type_name(),
              $sformatf("%s error-path security gating: addr=0x%08h data=0x%0h ungated=%s,%s",
                        t.name, addr, data, ungated[0].name(), ungated[1].name()), UVM_LOW)
    reset_to_rti();
    // Two assert/release passes of the target's direct disable prove the
    // gate is repeatable, not a one-shot POR effect.
    for (int unsigned idx = 1; idx <= 2; idx++) begin
      string gate_ctx = $sformatf("error_gate.pass%0d", idx);
      dtp_j2a_status_e op_status;
      int unsigned gb_aw, gb_w, gb_ar;
      int unsigned ga_aw, ga_w, ga_ar;
      int unsigned wr_bursts_gate, rd_bursts_gate;
      bit reference[], gated[], post[];
      log_step($sformatf("%0d", idx), $sformatf(
               "Gate %s and attempt an error-path write (pass %0d)", t.name, idx));
      gate_image_reference(t, addr, reference);
      gate_target(t);
      // arm_expected=0: the gated op must never reach the bus, so no
      // scoreboard credit may be armed for it (an armed credit that is
      // never consumed fails at the check_phase drain).
      arm_target_error(t, addr, OCAH_AXI_RESP_SLVERR, .for_read(1'b0), .for_write(1'b1),
                       .arm_expected(1'b0));
      sample_activity(t, gb_aw, gb_w, gb_ar);
      wr_bursts_gate = write_bursts_now(t);
      rd_bursts_gate = read_bursts_now(t);
      // issue_single suppresses intent arming while the target is
      // gated (target_enabled()==0).
      issue_single(t, DTP_J2A_OP_WRITE, addr, data, full_wstrb(size), size,
                   .use_default_size(1'b0));
      last_single_capture(gated);
      wait_sys_cycles(8);
      sample_activity(t, ga_aw, ga_w, ga_ar);
      expect_no_activity_evidence(t, gb_aw, gb_w, gb_ar, ga_aw, ga_w, ga_ar, {
                                  gate_ctx, ".gated_attempt"});
      capture_single(t, post);
      check_gated_tdr(t, reference, addr, full_wstrb(size), size, gated, post, gate_ctx);
      // Remove the never-consumed injection before re-opening the gate,
      // then prove the counters stay flat after release: a bridge that
      // queued the gated request and replays it once the gate re-opens
      // is the exact leak this scenario must catch.
      clear_target_error(t);
      enable_all_debug();
      wait_sys_cycles(8);
      sample_activity(t, ga_aw, ga_w, ga_ar);
      expect_no_activity_evidence(t, gb_aw, gb_w, gb_ar, ga_aw, ga_w, ga_ar, {
                                  gate_ctx, ".post_reenable"});
      // Restored error path: an ungated armed error must report
      // through the JTAG status and the scoreboard as EXPECTED.
      arm_target_error(t, addr, ungated[idx-1], .for_read(1'b0), .for_write(1'b1));
      single_write(t, addr, (data ^ idx) & data_mask(size), full_wstrb(size), op_status, size,
                   .use_default_size(1'b0), .context_s({gate_ctx, ".ungated_error"}));
      check_fault_status({gate_ctx, ".ungated_error.status"}, op_status, axi_resp_to_status(
                         ungated[idx-1]), $sformatf("addr=0x%0h", addr));
      verify_target_recovery(t, addr + 64'h400 + idx * t.beat_bytes, data ^ (idx << 4), 1'b0,
                             gate_ctx);
      // Exact delta from before the gated attempt: only the ungated error
      // write and the recovery write complete (write bursts +2, reads +0),
      // so a replay of the gated write fails here.
      void'(axi_evidence.expect_equal(
          "CHK-AXI-GATE-EXACT",
          write_bursts_now(
              t
          ),
          wr_bursts_gate + 2,
          $sformatf(
              "%s target=%s source=responder_burst_counts sanctioned=ungated_error_write+recovery_write(+2)",
              gate_ctx,
              t.name)
      ));
      void'(axi_evidence.expect_equal(
          "CHK-AXI-GATE-EXACT",
          read_bursts_now(
              t
          ),
          rd_bursts_gate,
          $sformatf(
              "%s target=%s source=responder_burst_counts reads", gate_ctx, t.name)
      ));
      operation_count++;
    end
    emit_error_nonvacuity("error_security_gating", 2);
  endtask

  // ------------------------------------------------------------------
  // Scenario dispatch.
  // ------------------------------------------------------------------

  task body();
    dtp_j2a_target_t t = target();
    seed_scenario_rng();
    use_target(t);
    enable_all_debug();
    case (scenario)
      "error_single_write":                 run_error_single_write(t);
      "error_single_read":                  run_error_single_read(t);
      "error_series_no_incr_write":         run_error_series_write(t, 1'b0, 1'b0);
      "error_series_no_incr_read":          run_error_series_read(t, 1'b0, 1'b0);
      "error_series_incr_write":            run_error_series_write(t, 1'b1, 1'b0);
      "error_series_incr_read":             run_error_series_read(t, 1'b1, 1'b0);
      "error_series_incr_write_with_status": run_error_series_write(t, 1'b1, 1'b1);
      "error_series_incr_read_with_status": run_error_series_read(t, 1'b1, 1'b1);
      "error_security_gating":              run_error_security_gating(t);
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown JTAG2AXI error scenario %s", scenario))
    endcase
    // Scenario-level non-vacuity: real operations ran and no armed
    // expectation is left pending going into the check_phase drain.
    emit_error_nonvacuity(scenario, 1);
    clear_target_error(t);
    enable_all_debug();
    `uvm_info(
        get_type_name(),
        $sformatf(
            "JTAG2AXI error scenario complete: target=%s scenario=%s operations=%0d status=%s",
            t.name, scenario, operation_count, status.name()), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_error_test_seq
