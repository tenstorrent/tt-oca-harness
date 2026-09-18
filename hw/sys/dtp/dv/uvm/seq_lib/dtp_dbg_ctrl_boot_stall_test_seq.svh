// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DEBUG_CONTROL boot stall: the exported jtag_boot_stall/_ovrd pins must
// track every write of the 2x2 boot_stall_ovrd x boot_stall matrix (in a
// shuffled per-pass order), boot_stall must toggle freely while the
// override stays asserted, and the pair must be independent of the
// clock-stop bits. Mirrors the cocotb dtp_dbg_ctrl_boot_stall_test_seq.

class dtp_dbg_ctrl_boot_stall_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_ctrl_boot_stall_test_seq)

  function new(string name = "dtp_dbg_ctrl_boot_stall_test_seq");
    super.new(name);
  endfunction

  // Write one DEBUG_CONTROL combination and check pins plus readback.
  protected task check_boot_stall_combo(bit boot_stall_ovrd, bit boot_stall, bit jtag_clock_stop,
                                        bit cla_clock_stop_en, string context_s);
    bit [63:0] value, readback;
    value = pack_debug_control(
        .boot_stall(boot_stall),
        .boot_stall_ovrd(boot_stall_ovrd),
        .cla_clock_stop_en(cla_clock_stop_en),
        .jtag_clock_stop(jtag_clock_stop)
    );
    `uvm_info(
        get_type_name(),
        $sformatf(
            "%s write DEBUG_CONTROL=0x%02h boot_ovrd=%0d boot_stall=%0d jtag_stop=%0d cla_stop_en=%0d",
            context_s, value, boot_stall_ovrd, boot_stall, jtag_clock_stop, cla_clock_stop_en),
        UVM_MEDIUM)
    write_debug_control(value);
    wait_sys_cycles();
    expect_dbg_signal("jtag_boot_stall_ovrd", boot_stall_ovrd, context_s);
    expect_dbg_signal("jtag_boot_stall", boot_stall, context_s);
    read_debug_control(readback, value);
    check_debug_control_bit(readback, DbgBootStallOvrdBit, boot_stall_ovrd,
                            "DEBUG_CONTROL.boot_stall_ovrd", context_s);
    check_debug_control_bit(readback, DbgBootStallBit, boot_stall, "DEBUG_CONTROL.boot_stall",
                            context_s);
    check_debug_control_bit(readback, DbgJtagClockStopBit, jtag_clock_stop,
                            "DEBUG_CONTROL.jtag_clock_stop", context_s);
    check_debug_control_bit(readback, DbgClaClockStopEnBit, cla_clock_stop_en,
                            "DEBUG_CONTROL.cla_clock_stop_en", context_s);
  endtask

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"};
    bit [1:0] combos[4] = '{2'b00, 2'b01, 2'b10, 2'b11};  // {ovrd, stall}
    bit toggle_seq[4] = '{1'b0, 1'b1, 1'b0, 1'b1};
    bit [63:0] readback;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();
    // The DEBUG_CONTROL reset check includes the live cla_clock_stop
    // status bit, which mirrors the CLA request vector: clear it
    // explicitly instead of relying on one-time bring-up state.
    set_clk_stop_requests('0);
    read_debug_control(readback);
    family_check("CHK-DBG-TDR", "DEBUG_CONTROL reset", readback, 64'd0);
    expect_dbg_signal("jtag_boot_stall_ovrd", 1'b0, "after reset");
    expect_dbg_signal("jtag_boot_stall", 1'b0, "after reset");

    // Exhaustive 2x2 sweep in a seeded per-pass order.
    for (int unsigned i = 3; i > 0; i--) begin
      int unsigned j = $urandom_range(i);
      bit [1:0] tmp = combos[i];
      combos[i] = combos[j];
      combos[j] = tmp;
    end
    foreach (combos[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/4: boot_stall_ovrd=%0d boot_stall=%0d",
                idx + 1,
                combos[idx][1],
                combos[idx][0]
                ), UVM_LOW)
      check_boot_stall_combo(combos[idx][1], combos[idx][0], 1'b0, 1'b0, $sformatf(
                             "combo#%0d", idx + 1));
    end

    // boot_stall toggles while the override stays asserted.
    foreach (toggle_seq[idx])
      check_boot_stall_combo(1'b1, toggle_seq[idx], 1'b0, 1'b0, $sformatf("independent#%0d", idx + 1
                             ));

    // Boot-stall fields are independent of the clock-stop bits.
    check_boot_stall_combo(1'b1, 1'b1, 1'b1, 1'b0, "interaction#1");
    check_boot_stall_combo(1'b1, 1'b1, 1'b0, 1'b1, "interaction#2");
    check_boot_stall_combo(1'b1, 1'b1, 1'b1, 1'b1, "interaction#3");

    // Cleanup.
    write_debug_control('0);
    wait_sys_cycles();
    expect_dbg_signal("jtag_boot_stall_ovrd", 1'b0, "cleanup");
    expect_dbg_signal("jtag_boot_stall", 1'b0, "cleanup");

    finalize_family_checker();
  endtask

endclass : dtp_dbg_ctrl_boot_stall_test_seq
