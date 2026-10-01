// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC fabric JTAG2AXI read-side scenarios — the SV analogue of
// the cocotb dtp_jtag2axi_smc_axi_rd_test_seq. One parameterized sequence
// runs one focused scenario per pass, selected by `scenario`:
//
//   single_write_read                one write plus readback of the same slot
//   series_write_read_incr           write an incrementing series front-door,
//                                    then read it back per beat through
//                                    SERIES_CTRL(READ) + SERIES_DATA_INCR
//   series_write_read_incr_narrow    32-bit INCR write-read at beat offset +4
//   series_write_read_no_incr        fixed-address series: every read beat
//                                    returns the last value written
//   series_write_read_incr_with_error  *_DATA_WITH_ERROR_STATUS mode with a
//                                    mixed increment pattern on both legs and
//                                    one armed fault beat on the read leg
//   read_random_ops                  randomized single reads of backdoor-
//                                    preloaded data (address/size/payload)
//   read_security_gating             gated read attempts produce zero request
//                                    activity; baseline/restore reads prove
//                                    the observation path is alive
//   read_security_gating_no_axi_activity  same must-not-happen property,
//                                    banner-scoped to the no-activity window
//                                    (VPLAN 3.6a)
//
// Series read-data pipeline: a SERIES_DATA shift in READ mode launches the
// bus read for the programmed address and RETURNS THE PREVIOUS shift's data,
// so each beat needs a priming shift (bus-activity checked) followed by a
// capture shift whose TDO carries the primed beat. Random choices come from
// the per-pass seeded stream and are logged with iteration context for
// replay. The JTAG-status/readback truth is owned by the shared AXI
// scoreboard (CHK-AXI-RESP/RDATA on every observed transaction); gating
// evidence rides the tb pulse counters (CHK-AXI-GATE-*).

class dtp_jtag2axi_smc_axi_rd_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_smc_axi_rd_test_seq)

  // Selected by the test before start(); body() dispatches on it.
  string scenario = "series_write_read_incr";

  int unsigned operation_count = 0;

  localparam bit [63:0] DefaultAxiAddr = 64'h40;

  function new(string name = "dtp_jtag2axi_smc_axi_rd_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    if (scenario == "read_security_gating" || scenario == "read_security_gating_no_axi_activity")
      return "";
    return "smc_axi";
  endfunction

  // TAP reset ending in Run-Test/Idle (scan contract).
  protected task reset_and_idle();
    tap_reset();
    step(1'b0);  // TLR -> RTI
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after TLR->RTI step");
  endtask

  // Series beats per pass: at least 2, at most 6, tracking +DTP_RANDOM_COUNT.
  protected function int unsigned series_beats();
    if (random_count < 2) return 2;
    if (random_count > 6) return 6;
    return random_count;
  endfunction

  // ------------------------------------------------------------------
  // single_write_read
  // ------------------------------------------------------------------
  task run_single_write_read();
    dtp_j2a_target_t t = target_smc_axi();
    dtp_j2a_status_e status;
    `uvm_info(get_type_name(), "=== SMC_AXI_SINGLE_OP Single Write-Read ===", UVM_LOW)
    reset_and_idle();
    write_neighbour_then_read(t, DefaultAxiAddr + 64'h400, "single_wr_rd", status);
    operation_count += 3;
    emit_nonvacuity_evidence(t, operation_count >= 2, $sformatf(
                             "scenario=single_write_read operations=%0d", operation_count));
  endtask

  // ------------------------------------------------------------------
  // series_write_read_incr
  // ------------------------------------------------------------------
  task run_series_write_read_incr();
    dtp_j2a_target_t t = target_smc_axi();
    int unsigned size = 3;
    int unsigned stride = size_bytes(size);
    int unsigned beats = series_beats();
    bit [63:0] base_addr;
    bit [63:0] expected_q[$];
    bit [63:0] data, obs, addr, addr_after;
    bit series_reset;
    int unsigned pl_depth, size_rd;
    dtp_j2a_status_e status;

    `uvm_info(get_type_name(), "=== SMC_AXI Series Write-Read Incrementing ===", UVM_LOW)
    reset_and_idle();
    base_addr = random_series_base(t, beats * stride, 1'b1);

    series_ctrl_op(t, DTP_J2A_OP_WRITE, base_addr, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      data = {$urandom, $urandom} & data_mask(size);
      expected_q.push_back(data);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series incr write addr=0x%014h data=0x%0h",
                idx + 1,
                beats,
                base_addr + idx * stride,
                data
                ), UVM_LOW)
      series_write_beat(t, data, base_addr + idx * stride, size, 1'b1, $sformatf(
                        "series_wr_rd_incr.write#%0d", idx));
    end

    foreach (expected_q[idx]) begin
      addr = base_addr + idx * stride;
      series_read_beat(t, addr, size, 1'b1, $sformatf("series_wr_rd_incr.read#%0d", idx), obs);
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: series read incr addr=0x%014h obs=0x%0h", idx + 1, beats, addr, obs),
          UVM_LOW)
      if (obs !== expected_q[idx])
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "series_wr_rd_incr.rdata#%0d: read 0x%0h != expected 0x%0h (addr=0x%0h)",
                   idx,
                   obs,
                   expected_q[idx],
                   addr
                   ))
      operation_count++;
    end

    // The last primed incrementing read advanced the series address by one
    // stride past the last beat.
    check_series_addr(t, addr + stride, size, "series_wr_rd_incr.final", status);
    check_status("series_wr_rd_incr.final", status, DTP_J2A_SUCCESS);
    emit_nonvacuity_evidence(
        t, operation_count >= 2, $sformatf(
        "scenario=series_write_read_incr beats=%0d read_ops=%0d", beats, operation_count));
  endtask

  // ------------------------------------------------------------------
  // series_write_read_incr_narrow
  // ------------------------------------------------------------------
  task run_series_write_read_incr_narrow();
    dtp_j2a_target_t t = target_smc_axi();
    int unsigned size = 2;
    int unsigned stride = size_bytes(size);
    int unsigned beats = series_beats();
    // The whole 64-bit beats the stream's words touch.
    int unsigned span = t.beat_bytes * ((4 + beats * stride + t.beat_bytes - 1) / t.beat_bytes);
    bit [63:0] base_addr;
    bit [63:0] expected_q[$];
    bit [63:0] data, obs, addr, addr_after;
    bit series_reset;
    int unsigned pl_depth, size_rd;
    dtp_j2a_status_e status;

    `uvm_info(get_type_name(), "=== SMC_AXI Series Write-Read 32-bit Incrementing at +4 ===",
              UVM_LOW)
    reset_and_idle();
    base_addr = random_series_base(t, span, 1'b1) + 64'd4;
    // A read returns the whole beat, which the reference model predicts from
    // its shadow at the full address: whole-beat preloads give every beat
    // the stream touches a known word on the lanes it does not write.
    for (
        bit [63:0] beat = base_addr - (base_addr % t.beat_bytes);
        beat < base_addr + beats * stride;
        beat += t.beat_bytes
    )
      write_target_mem_int(t, beat, {$urandom, $urandom}, 3);

    series_ctrl_op(t, DTP_J2A_OP_WRITE, base_addr, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      data = {$urandom, $urandom} & data_mask(size);
      expected_q.push_back(data);
      addr = base_addr + idx * stride;
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series incr narrow write addr=0x%014h data=0x%0h",
                idx + 1,
                beats,
                addr,
                data
                ), UVM_LOW)
      series_write_beat(t, data, addr, size, 1'b1, $sformatf(
                        "series_wr_rd_incr_narrow.write#%0d", idx));
      // A NOP SERIES_CTRL capture leaves the latched stream running.
      check_series_addr(t, addr + stride, size, $sformatf("series_wr_rd_incr_narrow.write#%0d", idx
                        ), status);
      check_status($sformatf("series_wr_rd_incr_narrow.write_status#%0d", idx), status,
                   DTP_J2A_SUCCESS);
    end

    foreach (expected_q[idx]) begin
      addr = base_addr + idx * stride;
      series_read_beat(t, addr, size, 1'b1, $sformatf("series_wr_rd_incr_narrow.read#%0d", idx),
                       obs);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series read incr narrow addr=0x%014h obs=0x%0h",
                idx + 1,
                beats,
                addr,
                obs
                ), UVM_LOW)
      if (obs !== expected_q[idx])
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "series_wr_rd_incr_narrow.rdata#%0d: read 0x%0h != expected 0x%0h (addr=0x%0h)",
                   idx,
                   obs,
                   expected_q[idx],
                   addr
                   ))
      // The primed read advanced the series address by one stride.
      check_series_addr(t, addr + stride, size, $sformatf("series_wr_rd_incr_narrow.read#%0d", idx),
                        status);
      check_status($sformatf("series_wr_rd_incr_narrow.read_status#%0d", idx), status,
                   DTP_J2A_SUCCESS);
      operation_count++;
    end
    emit_nonvacuity_evidence(
        t, operation_count >= 2, $sformatf(
        "scenario=series_write_read_incr_narrow beats=%0d read_ops=%0d", beats, operation_count));
  endtask

  // ------------------------------------------------------------------
  // series_write_read_no_incr
  // ------------------------------------------------------------------
  task run_series_write_read_no_incr();
    dtp_j2a_target_t t = target_smc_axi();
    int unsigned size = 3;
    int unsigned beats = series_beats();
    bit [63:0] addr, upper;
    bit [63:0] values_q[$];
    dtp_j2a_status_e status;

    `uvm_info(get_type_name(), "=== SMC_AXI Series Write-Read No-Increment ===", UVM_LOW)
    reset_and_idle();
    upper = random_upper_addr(t);
    addr = upper | random_target_aligned_addr(t, size);

    for (int unsigned idx = 0; idx < beats; idx++)
      values_q.push_back({$urandom, $urandom} & data_mask(size));

    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    foreach (values_q[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series no-incr write addr=0x%014h data=0x%0h",
                idx + 1,
                beats,
                addr,
                values_q[idx]
                ), UVM_LOW)
      series_write_beat(t, values_q[idx], addr, size, 1'b0, $sformatf(
                        "series_wr_rd_no_incr.write#%0d", idx + 1));
    end

    series_reread_fixed(t, addr, values_q[$], beats, "series_wr_rd_no_incr", status);
    operation_count += beats;
    check_status("series_wr_rd_no_incr.final", status, DTP_J2A_SUCCESS);
    emit_nonvacuity_evidence(
        t, operation_count >= 2, $sformatf(
        "scenario=series_write_read_no_incr beats=%0d read_ops=%0d", beats, operation_count));
  endtask

  // ------------------------------------------------------------------
  // series_write_read_incr_with_error (*_DATA_WITH_ERROR_STATUS mode)
  // ------------------------------------------------------------------
  task run_series_write_read_incr_with_error();
    dtp_j2a_target_t t = target_smc_axi();
    dtp_j2a_series_status_plan_t plan = plan_series_status(t);
    bit [63:0] words[] = new[DtpJ2aSeriesStatusBeats];
    bit [63:0] expected[];
    dtp_j2a_status_e status;
    foreach (words[i]) words[i] = {$urandom, $urandom} & data_mask(plan.size);
    `uvm_info(get_type_name(),
              $sformatf("=== SMC_AXI Series Write-Read With Error-Status Mode: base=0x%08h ===",
                        plan.base), UVM_LOW)
    reset_and_idle();
    run_series_status_write(t, plan, words, "series_wr_rd_status.write");
    dtp_j2a_series_status_final_words(plan, words, expected);
    arm_series_status_fault(t, plan, 1'b1);
    `uvm_info(get_type_name(), $sformatf("read leg: fault_beat=%0d resp=%s", plan.fault_idx,
                                         plan.expected.name()), UVM_LOW)
    run_series_status_read(t, plan, expected, "series_wr_rd_status.read");
    recover_target(t, series_status_recovery_addr(plan), {$urandom, $urandom}, 1'b1,
                   "series_wr_rd_status", status);
    operation_count += 2 * DtpJ2aSeriesStatusBeats + 1;
    emit_series_status_nonvacuity("series_write_read_incr_with_error", t, plan, operation_count);
  endtask

  // ------------------------------------------------------------------
  // read_random_ops
  // ------------------------------------------------------------------
  task run_read_random_ops();
    dtp_j2a_target_t t = target_smc_axi();
    int unsigned size;
    bit [63:0] addr, data, beat, offset, word;
    dtp_j2a_status_e status;

    `uvm_info(get_type_name(), "=== SMC_AXI_SINGLE_OP Randomized Reads ===", UVM_LOW)
    reset_and_idle();
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      size   = $urandom_range(3);
      beat   = random_upper_addr(t);
      beat |= random_target_aligned_addr(t, size);
      offset = 64'($urandom_range((t.beat_bytes >> size) - 1) << size);
      addr   = beat + offset;
      word   = {$urandom, $urandom};
      data   = (word >> (8 * offset)) & data_mask(size);
      // Whole-beat backdoor preload (mirrored into the passive reference
      // model): the read returns the whole beat, which the model predicts
      // from its shadow at the full address.
      write_target_mem_int(t, beat, word, 3);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: random read addr=0x%08h size=%0d data=0x%0h",
                idx,
                random_count,
                addr,
                size,
                data
                ), UVM_LOW)
      read_target_single_and_check(t, addr, data, status, size, $sformatf("random_read#%0d", idx));
      operation_count++;
    end
    emit_nonvacuity_evidence(t, operation_count >= 2, $sformatf(
                             "scenario=read_random_ops reads=%0d", operation_count));
  endtask

  // ------------------------------------------------------------------
  // read_security_gating (+ the no-activity-scoped VPLAN variant)
  // ------------------------------------------------------------------
  task run_read_security_gating(bit no_activity_only);
    dtp_j2a_target_t t = target_smc_axi();
    bit [63:0] addr = DefaultAxiAddr + 64'h500;
    bit [63:0] data;
    int unsigned base_aw, base_w, base_ar;
    int unsigned gate_aw, gate_w, gate_ar;
    int unsigned now_aw, now_w, now_ar;
    int unsigned rd_bursts_gate, wr_bursts_gate;
    dtp_j2a_status_e status;

    `uvm_info(
        get_type_name(),
        no_activity_only ? "=== SMC_AXI Read Security Gating No-Activity ===" : "=== SMC_AXI Read Security Gating ===",
        UVM_LOW)
    reset_and_idle();
    data = {$urandom, $urandom};
    write_target_mem_int(t, addr, data, 3);

    // Baseline read proves the observation path is alive (positive control).
    sample_activity(t, base_aw, base_w, base_ar);
    read_target_single_and_check(t, addr, data, status, 3, "read_gate.baseline");
    sample_activity(t, now_aw, now_w, now_ar);
    if (!(now_ar > base_ar))
      `uvm_error("jtag2axi_activity_chk", $sformatf(
                 "read_gate.baseline: expected AR activity for the baseline read (ar %0d -> %0d)",
                 base_ar,
                 now_ar
                 ))

    // Two assert/release passes of the one direct disable prove the gate
    // is repeatable, not a one-shot POR effect.
    for (int unsigned idx = 1; idx <= 2; idx++) begin
      bit reference[], gated[], post[];
      `uvm_info(get_type_name(), $sformatf(
                "Step %0d: gate SMC fabric read with smc_jtag2axi (pass %0d)", idx + 1, idx),
                UVM_LOW)
      gate_image_reference(t, addr + idx * 8, reference);
      gate_target(t);
      // Snapshot BEFORE the gated attempt so a request pulse leaked at
      // shift time is caught: pulse counters for the flat windows,
      // responder burst counts for the exact-delta proof (pulse counts
      // per transaction are timing-dependent; burst counts are exact).
      sample_activity(t, gate_aw, gate_w, gate_ar);
      rd_bursts_gate = read_bursts_now(t);
      wr_bursts_gate = write_bursts_now(t);
      issue_single(t, DTP_J2A_OP_READ, addr + idx * 8);  // gated: no intent armed
      last_single_capture(gated);
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, $sformatf(
                                  "read_gate.pass%0d window=gated_attempt+8cyc", idx));
      capture_single(t, post);
      check_gated_tdr(t, reference, addr + idx * 8, 8'h00, t.default_size, gated, post, $sformatf(
                      "read_gate.pass%0d", idx));
      // Delayed-leak protection: counters must still be flat after the
      // disable releases, before any sanctioned traffic — a bridge that
      // queued the gated request and replays it is the exact leak this
      // scenario must catch.
      enable_all_debug();
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, $sformatf(
                                  "read_gate.pass%0d.post_reenable", idx));
      // Restore read, then the exact-delta proof from BEFORE the gated
      // attempt to AFTER the restore: only the sanctioned restore read
      // may complete (read bursts +1, write bursts unchanged); a
      // delayed replay anywhere in the span makes read bursts >= +2.
      read_target_single_and_check(t, addr, data, status, 3, $sformatf(
                                   "read_gate.pass%0d.restore", idx));
      sample_activity(t, now_aw, now_w, now_ar);
      if (!(now_ar > gate_ar))
        `uvm_error("jtag2axi_activity_chk", $sformatf(
                   "read_gate.pass%0d.restore: expected AR activity", idx))
      if (axi_evidence != null) begin
        void'(axi_evidence.expect_equal(
            "CHK-AXI-GATE-EXACT",
            read_bursts_now(
                t
            ),
            rd_bursts_gate + 1,
            $sformatf(
                {
                  "read_gate.pass%0d target=%s ",
                  "source=responder_burst_counts sanctioned=restore_read(+1)"
                },
                idx,
                t.name)
        ));
        void'(axi_evidence.expect_equal(
            "CHK-AXI-GATE-EXACT",
            write_bursts_now(
                t
            ),
            wr_bursts_gate,
            $sformatf(
                "read_gate.pass%0d target=%s source=responder_burst_counts writes", idx, t.name)
        ));
      end
      operation_count++;
    end

    // CHK-AXI-NONVAC: the counters that stayed flat while gated
    // demonstrably move for real traffic (baseline + both restores).
    sample_activity(t, now_aw, now_w, now_ar);
    emit_nonvacuity_evidence(t, operation_count >= 2 && now_ar >= 3, $sformatf(
                             "gated_attempts=%0d ar_pulses=%0d expected_ar>=3 (baseline+2 restores)",
                             operation_count,
                             now_ar
                             ));
  endtask

  task body();
    seed_scenario_rng();
    operation_count = 0;
    enable_all_debug();
    case (scenario)
      "single_write_read":                    run_single_write_read();
      "series_write_read_incr":               run_series_write_read_incr();
      "series_write_read_incr_narrow":        run_series_write_read_incr_narrow();
      "series_write_read_no_incr":            run_series_write_read_no_incr();
      "series_write_read_incr_with_error":    run_series_write_read_incr_with_error();
      "read_random_ops":                      run_read_random_ops();
      "read_security_gating":                 run_read_security_gating(1'b0);
      "read_security_gating_no_axi_activity": run_read_security_gating(1'b1);
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown read-side JTAG2AXI scenario %s", scenario))
    endcase
    enable_all_debug();
    `uvm_info(get_type_name(),
              $sformatf(
                  "Summary: SMC fabric read-side scenario complete scenario=%s operations=%0d",
                  scenario, operation_count), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_smc_axi_rd_test_seq
