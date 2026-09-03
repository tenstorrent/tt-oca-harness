// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_trst_test scenario sequence — asynchronous TRST reset and
// recovery with named evidence (the SV port of the cocotb
// dtp_jtag_trst_test_seq):
//   * from four distinct start states (Run-Test/Idle, Shift-IR, Shift-DR,
//     and a seeded Capture-IR/Capture-DR pick), hold TRST low for a seeded
//     2..8 TCK cycles and prove the TAP lands in Test-Logic-Reset while the
//     reset is still asserted (CHK-TAP-TRST-TLR);
//   * release TRST for a seeded 1..3 cycles, TAP-reset again, and prove the
//     device-identification register reads back after every recovery
//     (CHK-IDCODE-RAW);
//   * CHK-NONVAC rejects a degenerate pass (repeated start states, sub-2
//     TRST widths, or missed recoveries).
// The per-cycle TAP-state legality lives in the env's dtp_tap_fsm_checker
// (aggregate CHK-TAP-STATE armed by the test); partial scans cut short by
// TRST are dropped by the scan builder, so the pin-level scan cross-check
// stays consistent and remains enabled for this scenario.

class dtp_jtag_trst_test_seq extends dtp_jtag_cmd_lib_seq;
  `uvm_object_utils(dtp_jtag_trst_test_seq)

  function new(string name = "dtp_jtag_trst_test_seq");
    super.new(name);
  endfunction

  task body();
    ocah_jtag_tap_state_e states[4];
    int unsigned trst_cycles[$];
    int unsigned min_cycles[$];
    int unsigned idcode_ok = 0;
    bit unique_states = 1'b1;
    bit [63:0] idcode;
    string required[$];

    seed_scenario_rng();
    required = {"CHK-TAP-RESET-TLR", "CHK-TAP-TRST-TLR", "CHK-IDCODE-RAW", "CHK-NONVAC"};
    attach_family_checker(required);

    states[0] = OCAH_JTAG_RUN_TEST_IDLE;
    states[1] = OCAH_JTAG_SHIFT_IR;
    states[2] = OCAH_JTAG_SHIFT_DR;
    states[3] = $urandom_range(1) ? OCAH_JTAG_CAPTURE_IR : OCAH_JTAG_CAPTURE_DR;

    foreach (states[s]) begin
      int unsigned assert_cycles  = $urandom_range(8, 2);
      int unsigned release_cycles = $urandom_range(3, 1);
      bit [IrWidth-1:0] instr = $urandom_range(1) ? IDCODE_INSTR : BYPASS_INSTR;
      `uvm_info(get_type_name(), $sformatf(
                "TRST pass %0d/4: start=%s ir=0x%02h assert=%0d release=%0d",
                s + 1,
                states[s].name(),
                instr,
                assert_cycles,
                release_cycles
                ), UVM_LOW)

      reset_to_tlr();
      load_ir(instr);
      goto_state(states[s]);
      check_state(tap_state_e'(16'h1 << int'(states[s])), "jtag_trst_chk", $sformatf(
                  "start state %s before TRST", states[s].name()));

      // Hold TRST low across the seeded window; the TAP must be in
      // Test-Logic-Reset while the reset is still asserted.
      set_trst(1'b0, assert_cycles);
      trst_cycles.push_back(assert_cycles);
      if (m_family != null)
        void'(m_family.check_reset_to_tlr(
            tb_vif.tap_state,
            $sformatf(
                "trst_from=%s cycles=%0d", states[s].name(), assert_cycles
            ),
            "CHK-TAP-TRST-TLR"
        ));
      check_state(TEST_LOGIC_RESET, "jtag_trst_chk", $sformatf(
                  "while TRST held from %s", states[s].name()));
      set_trst(1'b1, release_cycles);

      // Recovery: TAP-reset and prove IDCODE reads back.
      reset_to_tlr();
      read_idcode(idcode);
      family_check("CHK-IDCODE-RAW", "IDCODE after TRST recovery", idcode[31:0], DtpDefaultIdcode,
                   $sformatf("recovery after TRST from=%s", states[s].name()));
      if (idcode[31:0] == DtpDefaultIdcode) idcode_ok++;
    end

    foreach (states[i])
      for (int unsigned j = i + 1; j < 4; j++) if (states[i] == states[j]) unique_states = 1'b0;
    min_cycles = trst_cycles.min();
    if (m_family != null)
      void'(m_family.expect_true(
          "CHK-NONVAC",
          unique_states && (min_cycles[0] >= 2) && (idcode_ok == 4),
          $sformatf(
              "unique_start_states=%0d min_trst_cycles=%0d idcode_recovered=%0d/4",
              unique_states,
              min_cycles[0],
              idcode_ok)
      ));
    finalize_family_checker();
  endtask

endclass : dtp_jtag_trst_test_seq
