// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_jtag_tap_reset_test (the SV-UVM twin of the
// cocotb selftest): the device's TAP controller state is the observable. A
// TMS-high reset lands it in Test-Logic-Reset, every step of a random TMS
// walk matches the reference model, five or more TMS-high cycles reach
// Test-Logic-Reset from any start state, asserting TRST lands the device in
// Test-Logic-Reset, and a DR scan after release returns IDCODE with no
// instruction loaded. +OCAH_JTAG_SELFTEST_NEGATIVE desynchronizes the
// reference model before the walk so the first CHK-TAP-STATE fails and the
// run must FAIL.

class ocah_jtag_tap_reset_test_seq extends ocah_jtag_vip_base_test_seq;
  `uvm_object_utils(ocah_jtag_tap_reset_test_seq)

  int unsigned n_steps = 48;

  function new(string name = "ocah_jtag_tap_reset_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] observed;
    ocah_jtag_tap_state_e starts[4];
    require_handles();

    tap_reset_op();
    void'(evidence.check_reset_to_tlr(device_onehot(), "TMS-high reset at start"));

    if (ocah_knobs::is_set(NegativeKnob)) begin
      `uvm_info(
          get_type_name(),
          "NEGATIVE VALIDATION: desynchronizing the reference model to SHIFT_DR before the walk",
          UVM_LOW)
      evidence.sync_state(OCAH_JTAG_SHIFT_DR);
    end
    for (int unsigned index = 0; index < n_steps; index++) begin
      bit tms = 1'($urandom_range(1));
      step(tms);
      void'(evidence.check_state_step(tms, device_onehot(), $sformatf("walk step %0d", index)));
    end

    starts[0] = OCAH_JTAG_RUN_TEST_IDLE;
    starts[1] = OCAH_JTAG_SHIFT_IR;
    starts[2] = OCAH_JTAG_SHIFT_DR;
    starts[3] = $urandom_range(1) ? OCAH_JTAG_PAUSE_IR : OCAH_JTAG_PAUSE_DR;
    foreach (starts[i]) begin
      int unsigned ones = $urandom_range(8, 5);
      goto_state(starts[i]);
      evidence.sync_state(starts[i]);
      void'(slave_seq.check_state(starts[i], "after goto_state"));
      repeat (ones) step(1'b1);
      void'(evidence.check_tms_ones_to_tlr(
          ones, device_onehot(), $sformatf("from=%s", starts[i].name())
      ));
    end

    goto_state(OCAH_JTAG_SHIFT_DR);
    evidence.sync_state(OCAH_JTAG_SHIFT_DR);
    assert_trst(2);
    void'(evidence.expect_equal(
        "CHK-JTAG-TRST-TLR", device_onehot(), 16'h0001, "device state after TRST from SHIFT_DR"
    ));
    release_trst(1);
    step(1'b0);
    dr_scan(64'h0, IdcodeWidth, observed);
    void'(evidence.expect_equal(
        "CHK-JTAG-TRST-IDCODE", observed[31:0], Idcode, "DR scan after TRST release, no IR load"
    ));
  endtask
endclass : ocah_jtag_tap_reset_test_seq
