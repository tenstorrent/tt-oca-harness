// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DEBUG_CONTROL CLA clock stop: CLA_CLOCK_STOP_EN exports the enable, a
// seeded nonzero request mask on the CLA clock-stop vector must assert
// stop_clks and the read-only CLA status bit, and clearing the requests
// releases both. Mirrors the cocotb
// dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq.

class dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq)

  function new(string name = "dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"};
    bit [63:0] control_value, readback;
    bit [NumClkStopReq-1:0] request_mask;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();
    set_clk_stop_requests('0);
    read_debug_control(readback);
    family_check("CHK-DBG-TDR", "DEBUG_CONTROL reset", readback, 64'd0);

    control_value = pack_debug_control(.cla_clock_stop_en(1'b1));
    write_debug_control(control_value);
    wait_sys_cycles();
    expect_dbg_signal("cla_clock_stop_en", 1'b1, "enable exported");
    wait_for_signal_value("stop_clks", 1'b0, .context_s("no CLA request"));

    // Seeded nonzero request mask: any asserted CLA request must stop
    // the clocks, so repeated loops cover different aggregation inputs.
    request_mask = NumClkStopReq'($urandom_range((1 << NumClkStopReq) - 1, 1));
    set_clk_stop_requests(request_mask);
    wait_for_signal_value("stop_clks", 1'b1,
                          .context_s($sformatf("xtrig_clk_stop_req=0x%03h", request_mask)));

    read_debug_control(readback, control_value);
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b1, "DEBUG_CONTROL.cla_clock_stop",
                            "CLA request");
    check_debug_control_bit(readback, DbgClaClockStopEnBit, 1'b1, "DEBUG_CONTROL.cla_clock_stop_en",
                            "CLA request");

    set_clk_stop_requests('0);
    wait_for_signal_value("stop_clks", 1'b0, .context_s("xtrig_clk_stop_req=0"));
    read_debug_control(readback, control_value);
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop",
                            "request cleared");

    write_debug_control(pack_debug_control());
    wait_sys_cycles();
    expect_dbg_signal("cla_clock_stop_en", 1'b0, "enable cleared");

    finalize_family_checker();
  endtask

endclass : dtp_dbg_ctrl_clk_stop_cla_clock_stop_test_seq
