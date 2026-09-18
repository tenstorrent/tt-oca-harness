// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI single write/read scenario (dtp_jtag2axi_<target>_single_write_read_test),
// run against one target ("smc_otp" AXI-Lite or "smc_axi" AXI4):
//
//   1. reset + TAP reset + clearing the lifecycle debug disables;
//   2. randomized single write + readback loop (JTAG status checked here;
//      response/readback truth is owned by the shared AXI scoreboard);
//   3. armed SLVERR write and armed DECERR read (JTAG status SLVERR/DECERR
//      AND scoreboard CHK-AXI-RESP with expected non-OKAY + CHK-AXI-ERR-INJ);
//   4. recovery write + readback after disarming;
//   5. security gating: assert exactly the target's dbg_disable bit, issue
//      an op, prove zero request activity (CHK-AXI-GATE-*), restore, prove
//      recovery.
//
// Every random choice is logged with the loop index for replay.

class dtp_jtag2axi_single_write_read_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_single_write_read_test_seq)

  // "smc_otp" (default) or "smc_axi"; set by the test before start().
  string target_name = "smc_otp";

  // Gated request settle window: the bridge's TCK-to-system launch path
  // is a handful of cycles; a queued request would reach AW/AR well
  // inside this bound.
  localparam int unsigned GateSettleCycles = 20;
  function new(string name = "dtp_jtag2axi_single_write_read_test_seq");
    super.new(name);
  endfunction

  protected function dtp_j2a_target_t target();
    return (target_name == "smc_axi") ? target_smc_axi() : target_smc_otp();
  endfunction

  protected function bit [63:0] random_beat_addr(dtp_j2a_target_t t);
    int unsigned beat = 1 << t.default_size;
    // Responder memory is 64 KiB; keep clear of the armed-error addresses.
    return 64'((($urandom_range(0, (16'h8000 / beat) - 1)) * beat));
  endfunction

  protected function bit [63:0] mask_data(dtp_j2a_target_t t, bit [63:0] value);
    return (t.data_width >= 64) ? value : (value & ((64'd1 << t.data_width) - 1));
  endfunction

  task body();
    dtp_j2a_target_t t = target();
    // Write+readback pairs per pass (+DTP_JTAG2AXI_RANDOM_OPS through the test cfg).
    int unsigned random_ops = test_cfg.jtag2axi_random_ops;
    dtp_j2a_status_e status;
    bit [63:0] rdata;
    bit [7:0]  full_strb = 8'((1 << (1 << t.default_size)) - 1);
    bit [63:0] err_wr_addr = 64'h0000_9000;
    bit [63:0] err_rd_addr = 64'h0000_9100;
    int unsigned gate_before_aw, gate_before_w, gate_before_ar;
    int unsigned gate_after_aw, gate_after_w, gate_after_ar;

    seed_scenario_rng();
    sys_reset();
    tap_reset();
    step(1'b0);  // TLR -> RTI: IR/DR scans require Run-Test/Idle
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after TLR->RTI step");
    enable_all_debug();

    // -- 1. randomized write + readback ---------------------------------
    for (int unsigned idx = 0; idx < random_ops; idx++) begin
      bit [63:0] addr = random_beat_addr(t);
      bit [63:0] data = mask_data(t, {$urandom, $urandom});
      `uvm_info(get_type_name(), $sformatf(
                "loop %0d/%0d: %s write+readback addr=0x%0h data=0x%0h",
                idx + 1,
                random_ops,
                t.name,
                addr,
                data
                ), UVM_LOW)
      single_write(t, addr, data, full_strb, status);
      check_status($sformatf("random#%0d.write", idx), status, DTP_J2A_SUCCESS);
      single_read(t, addr, status, rdata);
      check_status($sformatf("random#%0d.read", idx), status, DTP_J2A_SUCCESS);
      if (rdata !== mask_data(t, data))
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "random#%0d readback 0x%0h != written 0x%0h", idx, rdata, data))
    end

    // -- 2. armed SLVERR write ------------------------------------------
    arm_target_error(t, err_wr_addr, OCAH_AXI_RESP_SLVERR, 1'b0, 1'b1);
    single_write(t, err_wr_addr, 64'hBAD0_5150, full_strb, status);
    check_status("armed_slverr.write", status, DTP_J2A_SLVERR);
    clear_target_error(t);

    // -- 3. armed DECERR read -------------------------------------------
    arm_target_error(t, err_rd_addr, OCAH_AXI_RESP_DECERR, 1'b1, 1'b0);
    single_read(t, err_rd_addr, status, rdata);
    check_status("armed_decerr.read", status, DTP_J2A_DECERR);
    clear_target_error(t);

    // -- 4. recovery ------------------------------------------------------
    single_write(t, err_wr_addr + 64'h40, 64'hFACE_0001, full_strb, status);
    check_status("recovery.write", status, DTP_J2A_SUCCESS);
    single_read(t, err_wr_addr + 64'h40, status, rdata);
    check_status("recovery.read", status, DTP_J2A_SUCCESS);

    // -- 5. security gating: assert exactly the target's disable ---------
    gate_target(t);
    sample_activity(t, gate_before_aw, gate_before_w, gate_before_ar);
    issue_single(t, DTP_J2A_OP_READ, 64'h0000_0040);
    wait_sys_cycles(GateSettleCycles);
    sample_activity(t, gate_after_aw, gate_after_w, gate_after_ar);
    expect_no_activity_evidence(t, gate_before_aw, gate_before_w, gate_before_ar, gate_after_aw,
                                gate_after_w, gate_after_ar, "read_gate");
    // Delayed-leak protection: a bridge that queued the gated request and
    // replays it once the gate re-opens must be caught — counters must
    // still be flat after re-enable, before any sanctioned traffic.
    enable_all_debug();
    wait_sys_cycles(GateSettleCycles);
    sample_activity(t, gate_after_aw, gate_after_w, gate_after_ar);
    expect_no_activity_evidence(t, gate_before_aw, gate_before_w, gate_before_ar, gate_after_aw,
                                gate_after_w, gate_after_ar, "read_gate.post_reenable");
    single_read(t, err_wr_addr + 64'h40, status, rdata);
    check_status("read_gate.restore", status, DTP_J2A_SUCCESS);
    if (rdata !== mask_data(t, 64'hFACE_0001))
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "gating restore readback 0x%0h != 0x%0h", rdata, mask_data(t, 64'hFACE_0001)))
  endtask

endclass : dtp_jtag2axi_single_write_read_test_seq
