// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DEBUG_CONTROL JTAG clock stop: JTAG_CLOCK_STOP must assert and release
// stop_clks (polled until the clk_i register settles), leave the CLA enable
// and status untouched, and behave repeatably across seeded stop/release
// toggles (no one-shot behavior). Across the pass no stop_clks change falls
// off a clk_i rising edge (CHK-DBG-STOP-EDGE). Mirrors the cocotb
// dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq.

class dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq)

  function new(string name = "dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN", "CHK-DBG-STOP-EDGE"};
    bit [63:0] control_value, clear_value, readback;
    int unsigned toggles;
    int unsigned off_edge_start;
    seed_scenario_rng();
    attach_family_checker(required);
    off_edge_start = stop_clks_off_edge_count();

    log_step("1", "Reset TAP and clear CLA clock-stop requests");
    reset_to_tlr();
    set_clk_stop_requests('0);
    read_debug_control(readback);
    family_check("CHK-DBG-TDR", "DEBUG_CONTROL reset", readback, 64'd0);

    log_step("2", "Set JTAG_CLOCK_STOP and expect stop_clks to assert");
    control_value = pack_debug_control(.jtag_clock_stop(1'b1));
    write_debug_control(control_value);
    wait_sys_cycles();
    wait_for_signal_value("stop_clks", 1'b1, .context_s("jtag_clock_stop=1"));
    expect_dbg_signal("cla_clock_stop_en", 1'b0, "jtag stop only");

    log_step("3", "Read DEBUG_CONTROL and confirm CLA status ignores JTAG stop");
    read_debug_control(readback, control_value);
    check_debug_control_bit(readback, DbgJtagClockStopBit, 1'b1, "DEBUG_CONTROL.jtag_clock_stop");
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop",
                            "JTAG stop only");

    log_step("4", "Clear JTAG_CLOCK_STOP and expect stop_clks to release");
    clear_value = pack_debug_control();
    write_debug_control(clear_value);
    wait_sys_cycles();
    wait_for_signal_value("stop_clks", 1'b0, .context_s("jtag_clock_stop=0"));

    log_step("5", "Repeat seeded stop/release toggles to prove no one-shot behavior");
    toggles = $urandom_range(4, 1);
    for (int unsigned toggle = 1; toggle <= toggles; toggle++) begin
      log_iteration(toggle, toggles, "stop/release toggle");
      write_debug_control(control_value);
      wait_sys_cycles($urandom_range(8, 2));
      wait_for_signal_value("stop_clks", 1'b1, .context_s($sformatf("toggle#%0d.stop", toggle)));
      write_debug_control(clear_value);
      wait_sys_cycles($urandom_range(8, 2));
      wait_for_signal_value("stop_clks", 1'b0, .context_s($sformatf("toggle#%0d.release", toggle)));
    end

    read_debug_control(readback, clear_value);
    check_debug_control_bit(readback, DbgJtagClockStopBit, 1'b0, "DEBUG_CONTROL.jtag_clock_stop",
                            "after the toggles");
    check_debug_control_bit(readback, DbgClaClockStopBit, 1'b0, "DEBUG_CONTROL.cla_clock_stop",
                            "after the toggles");
    check_stop_clks_off_edge(off_edge_start, "whole pass");
    finalize_family_checker();
  endtask

endclass : dtp_dbg_ctrl_clk_stop_jtag_clock_stop_test_seq
