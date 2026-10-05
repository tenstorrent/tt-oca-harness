// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// IC_RESET override and hold scenario: all fields default to 1 with
// deasserted slice outputs after TAP reset; each slice's active-low
// enable drives {ovrd=1, ctrl_n=0} and releases cleanly; reset_hold=0
// preserves four directed patterns, which give every slice each of its
// four enable/control values, seeded random patterns, and the slice
// outputs through a TMS-walked TLR; reset_hold=1 lets TLR restore
// defaults; and TRST always restores the full default image. The slice
// outputs across a TLR or a TRST are judged before the following readback,
// whose Update-DR writes the expected value back into the register.
// Mirrors the cocotb dtp_jtag_ic_reset_test_seq.

class dtp_jtag_ic_reset_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_ic_reset_test_seq)

  function new(string name = "dtp_jtag_ic_reset_test_seq");
    super.new(name);
  endfunction

  // Leave Test-Logic-Reset for Run-Test/Idle, where the following scans
  // start.
  protected task tlr_to_rti();
    step(1'b0);
    check_state(RUN_TEST_IDLE, "debug_tdr_scan_chk", "after TMS TLR->RTI");
  endtask

  // Check one flattened IC_RESET slice output pair.
  protected function void expect_slice(string name, bit ovrd, bit ctrl_n, string context_s);
    expect_dbg_signal({"jtag_ic_reset_", name, "_ovrd"}, ovrd, context_s);
    expect_dbg_signal({"jtag_ic_reset_", name, "_ctrl_n"}, ctrl_n, context_s);
  endfunction

  protected function void expect_default_outputs(string context_s);
    expect_slice("smc", 1'b0, 1'b1, context_s);
    expect_slice("sep", 1'b0, 1'b1, context_s);
    expect_slice("ext", 1'b0, 1'b1, context_s);
  endfunction

  // Every slice output follows the TDR fields of its port: ovrd is the
  // inverted active-low enable and ctrl_n is the control bit ("IC_RESET
  // Support" table), whatever the other ports hold.
  protected function void expect_slices(bit [IcResetPorts-1:0] reset_enable,
                                        bit [IcResetPorts-1:0] reset_control, string context_s);
    string       port_names[3]   = '{"smc", "sep", "ext"};
    int unsigned port_indices[3] = '{int'(ICR_SMC), int'(ICR_SEP), int'(ICR_EXT)};
    foreach (port_names[p])
    expect_slice(port_names[p], !reset_enable[port_indices[p]], reset_control[port_indices[p]],
                 $sformatf("%s enable=0b%03b control=0b%03b", context_s, reset_enable, reset_control
                 ));
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"};
    string       port_names[3]   = '{"smc", "sep", "ext"};
    int unsigned port_indices[3] = '{int'(ICR_SMC), int'(ICR_SEP), int'(ICR_EXT)};
    bit [63:0] default_value = bit_mask(IcResetLen);
    bit [63:0] observed, held_pattern, expected;
    bit [IcResetPorts-1:0] reset_enable, reset_control;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();
    read_ic_reset(observed, default_value);
    family_check("CHK-DBG-TDR", "IC_RESET default", observed, default_value);
    expect_default_outputs("after reset");

    // Each slice through override active and inactive states.
    foreach (port_names[p]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/3: JTAG override for %s", p + 1, port_names[p]), UVM_LOW)
      reset_enable  = '1;
      reset_control = '1;
      reset_enable[port_indices[p]]  = 1'b0;
      reset_control[port_indices[p]] = 1'b0;
      write_ic_reset(1'b1, reset_enable, reset_control, held_pattern);
      wait_sys_cycles();
      expect_slice(port_names[p], 1'b1, 1'b0, $sformatf("%s override active", port_names[p]));
      write_ic_reset(1'b1, '1, '1, held_pattern);
      wait_sys_cycles();
      expect_slice(port_names[p], 1'b0, 1'b1, $sformatf("%s override released", port_names[p]));
    end

    // reset_hold=0 preserves enable/control bits through a TMS TLR. Each
    // port's {reset_enable, reset_control} is rotated so each slice takes
    // all four values across the four patterns.
    for (int unsigned rotation = 0; rotation < 4; rotation++) begin
      string context_s = $sformatf("reset_hold=0 directed pattern#%0d", rotation + 1);
      foreach (port_names[p]) begin
        bit [1:0] slice_value;
        slice_value = 2'((rotation + p) % 4);
        reset_enable[port_indices[p]]  = slice_value[1];
        reset_control[port_indices[p]] = slice_value[0];
      end
      `uvm_info(get_type_name(), $sformatf("Iteration %0d/4: %s", rotation + 1, context_s), UVM_LOW)
      write_ic_reset(1'b0, reset_enable, reset_control, held_pattern);
      wait_sys_cycles();
      expect_slices(reset_enable, reset_control, context_s);
      goto_tlr_via_tms();
      wait_sys_cycles();
      expect_slices(reset_enable, reset_control, {context_s, " in Test-Logic-Reset"});
      tlr_to_rti();
      expected = dtp_ic_reset_after_tlr(1'b0, held_pattern, default_value);
      read_ic_reset(observed, expected);
      family_check("CHK-DBG-TDR", "IC_RESET reset_hold=0 TLR preserve", observed, expected,
                   context_s);
    end

    // Seeded random reset_hold=0 preservation patterns.
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      reset_enable  = 3'($urandom);
      reset_control = 3'($urandom);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: hold=0 enable=0b%03b control=0b%03b",
                idx,
                random_count,
                reset_enable,
                reset_control
                ), UVM_LOW)
      write_ic_reset(1'b0, reset_enable, reset_control, held_pattern);
      wait_sys_cycles();
      expect_slices(reset_enable, reset_control, $sformatf("reset_hold=0 iteration=%0d", idx));
      goto_tlr_via_tms();
      wait_sys_cycles();
      expect_slices(reset_enable, reset_control, $sformatf(
                    "reset_hold=0 in Test-Logic-Reset iteration=%0d", idx));
      tlr_to_rti();
      expected = dtp_ic_reset_after_tlr(1'b0, held_pattern, default_value);
      read_ic_reset(observed, expected);
      family_check("CHK-DBG-TDR", "IC_RESET random reset_hold=0 preserve", observed, expected,
                   $sformatf("iteration=%0d", idx));
    end

    // reset_hold=1 lets a TMS TLR restore the default image.
    write_ic_reset(1'b1, '0, '0, held_pattern);
    if (held_pattern == default_value)
      `uvm_error("debug_tdr_chk", "clearable IC_RESET pattern unexpectedly equals the default")
    goto_tlr_via_tms();
    expect_default_outputs("reset_hold=1 in Test-Logic-Reset");
    tlr_to_rti();
    expected = dtp_ic_reset_after_tlr(1'b1, held_pattern, default_value);
    read_ic_reset(observed, expected);
    family_check("CHK-DBG-TDR", "IC_RESET reset_hold=1 TLR clear", observed, expected);

    // TRST always restores reset_hold and enable/control defaults
    // (set_trst drives the active-low trst_n pin directly).
    write_ic_reset(1'b0, '0, '0, held_pattern);
    set_trst(1'b0, 5);
    set_trst(1'b1, 2);
    expect_default_outputs("after TRST");
    step(1'b0);
    check_state(RUN_TEST_IDLE, "debug_tdr_scan_chk", "after TRST release");
    read_ic_reset(observed, default_value);
    family_check("CHK-DBG-TDR", "IC_RESET TRST reset", observed, default_value);

    finalize_family_checker();
  endtask

endclass : dtp_jtag_ic_reset_test_seq
