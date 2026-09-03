// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// IC_RESET override and hold scenario: all fields default to 1 with
// deasserted slice outputs after TAP reset; each slice's active-low
// enable drives {ovrd=1, ctrl_n=0} and releases cleanly; reset_hold=0
// preserves directed and seeded random enable/control patterns through a
// TMS-walked TLR; reset_hold=1 lets TLR restore defaults; and TRST always
// restores the full default image. Mirrors the cocotb
// dtp_jtag_ic_reset_test_seq.

class dtp_jtag_ic_reset_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_ic_reset_test_seq)

  function new(string name = "dtp_jtag_ic_reset_test_seq");
    super.new(name);
  endfunction

  // TLR through five TMS-high steps (TRST untouched), then back to RTI
  // for the following scans.
  protected task tlr_via_tms_to_rti();
    goto_tlr_via_tms();
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

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"};
    string       port_names[3]   = '{"smc", "sep", "ext"};
    int unsigned port_indices[3] = '{int'(ICR_SMC), int'(ICR_SEP), int'(ICR_EXT)};
    bit [63:0] default_value = bit_mask(IcResetLen);
    bit [63:0] observed, held_pattern;
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

    // reset_hold=0 preserves enable/control bits through a TMS TLR.
    reset_enable  = 3'b001;  // ext=1, sep=0, smc=0
    reset_control = 3'b010;  // ext=0, sep=1, smc=0
    write_ic_reset(1'b0, reset_enable, reset_control, held_pattern);
    tlr_via_tms_to_rti();
    read_ic_reset(observed, held_pattern);
    family_check("CHK-DBG-TDR", "IC_RESET reset_hold=0 TLR preserve", observed, held_pattern);

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
      tlr_via_tms_to_rti();
      read_ic_reset(observed, held_pattern);
      family_check("CHK-DBG-TDR", "IC_RESET random reset_hold=0 preserve", observed, held_pattern,
                   $sformatf("iteration=%0d", idx));
    end

    // reset_hold=1 lets a TMS TLR restore the default image.
    write_ic_reset(1'b1, '0, '0, held_pattern);
    if (held_pattern == default_value)
      `uvm_error("debug_tdr_chk", "clearable IC_RESET pattern unexpectedly equals the default")
    tlr_via_tms_to_rti();
    read_ic_reset(observed, default_value);
    family_check("CHK-DBG-TDR", "IC_RESET reset_hold=1 TLR clear", observed, default_value);
    expect_default_outputs("after reset_hold=1 TLR");

    // TRST always restores reset_hold and enable/control defaults
    // (set_trst drives the active-low trst_n pin directly).
    write_ic_reset(1'b0, '0, '0, held_pattern);
    set_trst(1'b0, 5);
    set_trst(1'b1, 2);
    step(1'b0);
    check_state(RUN_TEST_IDLE, "debug_tdr_scan_chk", "after TRST release");
    read_ic_reset(observed, default_value);
    family_check("CHK-DBG-TDR", "IC_RESET TRST reset", observed, default_value);
    expect_default_outputs("after TRST");

    finalize_family_checker();
  endtask

endclass : dtp_jtag_ic_reset_test_seq
