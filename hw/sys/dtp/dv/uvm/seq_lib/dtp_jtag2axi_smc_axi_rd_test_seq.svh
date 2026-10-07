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
//                                    preloaded data: every transfer size once,
//                                    then seeded sizes, addresses and payloads
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
// replay. The shared AXI scoreboard judges every observed transaction
// (CHK-AXI-RESP/RDATA); the read data and status the bridge returns over
// JTAG land as CHK-AXI-RDATA (source=jtag-capture) and CHK-J2A-FAULT-STATUS;
// the gating windows ride the tb pulse counters (CHK-AXI-NOACT). The series
// write-read and gating flows are the family layer's
// (dtp_jtag2axi_base_test_seq), shared with the OTP bridges.

class dtp_jtag2axi_smc_axi_rd_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_smc_axi_rd_test_seq)

  // Selected by the test before start(); body() dispatches on it.
  string scenario = "series_write_read_incr";

  localparam bit [63:0] DefaultAxiAddr = 64'h40;

  function new(string name = "dtp_jtag2axi_smc_axi_rd_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    if (scenario == "read_security_gating" || scenario == "read_security_gating_no_axi_activity")
      return "";
    return "smc_axi";
  endfunction

  // ------------------------------------------------------------------
  // single_write_read
  // ------------------------------------------------------------------
  task run_single_write_read();
    dtp_j2a_target_t t = target_smc_axi();
    `uvm_info(get_type_name(), "=== SMC_AXI_SINGLE_OP Single Write-Read ===", UVM_LOW)
    write_neighbour_then_read(t, DefaultAxiAddr + 64'h400, "single_wr_rd", status);
    operation_count += 3;
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
    bit [63:0] data, obs, addr;

    `uvm_info(get_type_name(), "=== SMC_AXI Series Write-Read 32-bit Incrementing at +4 ===",
              UVM_LOW)
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

    log_step("1", "Write 32-bit incrementing series at +4");
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base_addr, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      data = {$urandom, $urandom} & data_mask(size);
      expected_q.push_back(data);
      addr = base_addr + idx * stride;
      log_iteration(idx + 1, beats, $sformatf(
                    "series incr narrow write addr=0x%014h data=0x%0h", addr, data));
      series_write_beat(t, data, addr, size, 1'b1, $sformatf(
                        "series_wr_rd_incr_narrow.write#%0d", idx));
      // A NOP SERIES_CTRL capture leaves the latched stream running.
      check_series_addr(t, addr + stride, size, $sformatf("series_wr_rd_incr_narrow.write#%0d", idx
                        ), status);
      check_status(t, $sformatf("series_wr_rd_incr_narrow.write_status#%0d", idx), status,
                   DTP_J2A_SUCCESS);
    end

    log_step("2", "Read 32-bit incrementing series back");
    foreach (expected_q[idx]) begin
      addr = base_addr + idx * stride;
      series_read_beat(t, addr, size, 1'b1, $sformatf("series_wr_rd_incr_narrow.read#%0d", idx),
                       obs);
      log_iteration(idx + 1, beats, $sformatf(
                    "series read incr narrow addr=0x%014h obs=0x%0h", addr, obs));
      check_returned_rdata(t, obs, expected_q[idx], $sformatf(
                           "series_wr_rd_incr_narrow.rdata#%0d addr=0x%0h", idx, addr));
      // The primed read advanced the series address by one stride.
      check_series_addr(t, addr + stride, size, $sformatf("series_wr_rd_incr_narrow.read#%0d", idx),
                        status);
      check_status(t, $sformatf("series_wr_rd_incr_narrow.read_status#%0d", idx), status,
                   DTP_J2A_SUCCESS);
      operation_count++;
    end
  endtask

  // ------------------------------------------------------------------
  // read_random_ops
  // ------------------------------------------------------------------
  task run_read_random_ops();
    dtp_j2a_target_t t = target_smc_axi();
    int unsigned size;
    bit [63:0] addr, data, beat, offset, word;

    `uvm_info(get_type_name(), "=== SMC_AXI_SINGLE_OP Randomized Reads ===", UVM_LOW)
    // Every pass reads each transfer size once before the drawn sizes.
    for (int unsigned idx = 1; idx <= random_count + 4; idx++) begin
      size   = (idx <= 4) ? idx - 1 : $urandom_range(3);
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
      log_iteration(idx, random_count + 4, $sformatf(
                    "random read addr=0x%08h size=%0d data=0x%0h", addr, size, data));
      read_target_single_and_check(t, addr, data, status, size, $sformatf("random_read#%0d", idx));
      operation_count++;
    end
  endtask

  task body();
    dtp_j2a_target_t t = target_smc_axi();
    seed_scenario_rng();
    use_target(t);
    operation_count = 0;
    enable_all_debug();
    reset_to_rti();
    case (scenario)
      "single_write_read":                 run_single_write_read();
      "series_write_read_incr": begin
        `uvm_info(get_type_name(), "=== SMC_AXI Series Write-Read Incrementing ===", UVM_LOW)
        run_series_write_read_incr(t, t.default_size, "series_wr_rd_incr");
      end
      "series_write_read_incr_narrow":     run_series_write_read_incr_narrow();
      "series_write_read_no_incr": begin
        `uvm_info(get_type_name(), "=== SMC_AXI Series Write-Read No-Increment ===", UVM_LOW)
        run_series_write_read_no_incr(t);
      end
      "series_write_read_incr_with_error": begin
        `uvm_info(get_type_name(), "=== SMC_AXI Series Write-Read With Error-Status Mode ===",
                  UVM_LOW)
        run_series_write_read_incr_with_error(t);
      end
      "read_random_ops":                   run_read_random_ops();
      "read_security_gating": begin
        `uvm_info(get_type_name(), "=== SMC_AXI Read Security Gating ===", UVM_LOW)
        run_read_security_gating(t, DefaultAxiAddr + 64'h500);
      end
      "read_security_gating_no_axi_activity": begin
        `uvm_info(get_type_name(), "=== SMC_AXI Read Security Gating No-Activity ===", UVM_LOW)
        run_read_security_gating(t, DefaultAxiAddr + 64'h500);
      end
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown read-side JTAG2AXI scenario %s", scenario))
    endcase
    enable_all_debug();
    emit_nonvacuity_evidence(t, operation_count >= 1, $sformatf(
                             "scenario=%s operations=%0d min_ops=1", scenario, operation_count));
    `uvm_info(get_type_name(),
              $sformatf(
                  "Summary: SMC fabric read-side scenario complete scenario=%s operations=%0d",
                  scenario, operation_count), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_smc_axi_rd_test_seq
