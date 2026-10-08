// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DEBUG_CONTROL CLA clock stop: CLA_CLOCK_STOP_EN exports the enable,
// request line 0 alone and then a seeded nonzero request mask on the CLA
// clock-stop vector must assert stop_clks and the read-only CLA status bit,
// and clearing the requests releases both. With CLA_CLOCK_STOP_EN clear a
// seeded request stops the clocks and sets the CLA status (the enable-off
// leg); under JTAG_CLOCK_STOP alone the CLA status reads 0, a seeded request
// sets it, and clearing that request clears it while stop_clks stays
// asserted (the JTAG-only leg). Across the pass no stop_clks change falls
// off a clk_i rising edge (CHK-DBG-STOP-EDGE). Mirrors the cocotb
// dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq.

class dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq)

  function new(string name = "dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN", "CHK-DBG-STOP-EDGE"};
    bit [63:0] control_value, clear_value, jtag_value, readback;
    bit [NumClkStopReq-1:0] request_masks[2];
    bit [NumClkStopReq-1:0] en_off_mask, jtag_mask;
    int unsigned off_edge_start;
    string ctx;
    seed_scenario_rng();
    attach_family_checker(required);
    off_edge_start = stop_clks_off_edge_count();

    log_step("1", "Reset TAP and clear clock-stop requests");
    reset_to_tlr();
    set_clk_stop_requests('0);
    read_debug_control(readback);
    family_check("CHK-DBG-TDR", "DEBUG_CONTROL reset", readback, 64'd0);

    log_step("2", "Set CLA_CLOCK_STOP_EN and check exported enable");
    control_value = pack_debug_control(.cla_clock_stop_en(1'b1));
    write_debug_control(control_value);
    wait_sys_cycles();
    expect_dbg_signal("cla_clock_stop_en", 1'b1, "enable exported");
    wait_for_signal_value("stop_clks", 1'b0, .context_s("no CLA request"));

    // Request line 0 alone, then a seeded nonzero request mask: any asserted
    // CLA request must stop the clocks, so repeated loops cover different
    // aggregation inputs.
    log_step("3", "Drive request line 0, then a seeded mask; expect stop and status");
    request_masks[0] = NumClkStopReq'(1);
    request_masks[1] = NumClkStopReq'($urandom_range((1 << NumClkStopReq) - 1, 1));
    foreach (request_masks[idx]) begin
      ctx = $sformatf("xtrig_clk_stop_req=0x%03h", request_masks[idx]);
      log_iteration(idx + 1, 2, ctx);
      set_clk_stop_requests(request_masks[idx]);
      wait_for_signal_value("stop_clks", 1'b1, .context_s(ctx));

      read_debug_control(readback, control_value);
      check_debug_control_bit(readback, DbgClaClockStopBit, 1'b1, "DEBUG_CONTROL.cla_clock_stop",
                              ctx);
      check_debug_control_bit(readback, DbgClaClockStopEnBit, 1'b1,
                              "DEBUG_CONTROL.cla_clock_stop_en", ctx);

      set_clk_stop_requests('0);
      wait_for_signal_value("stop_clks", 1'b0, .context_s("xtrig_clk_stop_req=0"));
      read_debug_control(readback, control_value);
      check_debug_control_bit(readback, DbgClaClockStopBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop",
                              "request cleared");
    end

    log_step("4", "Clear CLA_CLOCK_STOP_EN");
    clear_value = pack_debug_control();
    write_debug_control(clear_value);
    wait_sys_cycles();
    expect_dbg_signal("cla_clock_stop_en", 1'b0, "enable cleared");

    log_step("5", "Drive a seeded CLA request with CLA_CLOCK_STOP_EN clear");
    en_off_mask = NumClkStopReq'($urandom_range((1 << NumClkStopReq) - 1, 1));
    ctx = $sformatf("cla_clock_stop_en=0 xtrig_clk_stop_req=0x%03h", en_off_mask);
    set_clk_stop_requests(en_off_mask);
    wait_for_signal_value("stop_clks", 1'b1, .context_s(ctx));
    expect_dbg_signal("cla_clock_stop_en", 1'b0, ctx);
    read_debug_control(readback, clear_value);
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b1, "DEBUG_CONTROL.cla_clock_stop",
                            ctx);
    check_debug_control_bit(readback, DbgClaClockStopEnBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop_en",
                            ctx);
    check_debug_control_bit(readback, DbgJtagClockStopBit, 1'b0, "DEBUG_CONTROL.jtag_clock_stop",
                            ctx);
    set_clk_stop_requests('0);
    wait_for_signal_value("stop_clks", 1'b0, .context_s("cla_clock_stop_en=0 released"));
    read_debug_control(readback, clear_value);
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop",
                            "cla_clock_stop_en=0 released");

    // Every read shifts jtag_value back in, so JTAG_CLOCK_STOP stays set
    // across the leg.
    log_step("6", "Set JTAG_CLOCK_STOP alone, then add and clear a seeded CLA request");
    jtag_value = pack_debug_control(.jtag_clock_stop(1'b1));
    write_debug_control(jtag_value);
    wait_sys_cycles();
    wait_for_signal_value("stop_clks", 1'b1, .context_s("jtag_clock_stop=1"));
    read_debug_control(readback, jtag_value);
    check_debug_control_bit(readback, DbgJtagClockStopBit, 1'b1, "DEBUG_CONTROL.jtag_clock_stop",
                            "jtag_clock_stop=1");
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop",
                            "jtag_clock_stop=1");
    jtag_mask = NumClkStopReq'($urandom_range((1 << NumClkStopReq) - 1, 1));
    ctx = $sformatf("jtag_clock_stop=1 xtrig_clk_stop_req=0x%03h", jtag_mask);
    set_clk_stop_requests(jtag_mask);
    read_debug_control(readback, jtag_value);
    check_debug_control_bit(readback, DbgJtagClockStopBit, 1'b1, "DEBUG_CONTROL.jtag_clock_stop",
                            ctx);
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b1, "DEBUG_CONTROL.cla_clock_stop",
                            ctx);
    expect_dbg_signal("stop_clks", 1'b1, ctx);
    set_clk_stop_requests('0);
    read_debug_control(readback, jtag_value);
    check_debug_control_bit(readback, DbgJtagClockStopBit, 1'b1, "DEBUG_CONTROL.jtag_clock_stop",
                            "jtag_clock_stop=1 xtrig_clk_stop_req=0");
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop",
                            "jtag_clock_stop=1 xtrig_clk_stop_req=0");
    expect_dbg_signal("stop_clks", 1'b1, "JTAG_CLOCK_STOP holds");
    write_debug_control(clear_value);
    wait_sys_cycles();
    wait_for_signal_value("stop_clks", 1'b0, .context_s("jtag_clock_stop=0"));
    check_stop_clks_off_edge(off_edge_start, "whole pass");

    finalize_family_checker();
  endtask

endclass : dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq
