// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_jtag_idcode_test (the SV-UVM twin of the cocotb
// selftest): a DR scan straight out of Test-Logic-Reset returns the device
// identification value with the marker bit set, checked IDCODE reads emit
// CHK-IDCODE-RAW / CHK-IDCODE-MARKER, every scan reconstructs at its driven
// width, and a TAP reset after instruction churn re-selects IDCODE.
// +OCAH_JTAG_SELFTEST_NEGATIVE arms a wrong expected IDCODE so the run must
// FAIL.

class ocah_jtag_idcode_test_seq extends ocah_jtag_vip_base_test_seq;
  `uvm_object_utils(ocah_jtag_idcode_test_seq)

  int unsigned n_reads = 6;

  function new(string name = "ocah_jtag_idcode_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] observed, captured;
    bit [31:0] expected_idcode = Idcode;
    require_handles();
    if (ocah_knobs::is_set(NegativeKnob)) begin
      expected_idcode ^= 32'h2;
      `uvm_info(get_type_name(),
                $sformatf(
                    "NEGATIVE VALIDATION: arming wrong expected IDCODE 0x%08h instead of 0x%08h",
                    expected_idcode, Idcode), UVM_LOW)
    end

    reset_to_idle();
    dr_scan(64'h0, IdcodeWidth, observed);
    void'(evidence.expect_equal(
        "CHK-JTAG-TLR-IDCODE", observed[31:0], expected_idcode, "DR scan after TLR, no IR load"
    ));
    check_last_scan(1'b0, IdcodeWidth, "TLR-selected IDCODE");

    for (int unsigned index = 0; index < n_reads; index++) begin
      string ctx = $sformatf("read %0d", index);
      repeat ($urandom_range(3)) step(1'b0);
      ir_scan(IdcodeOpcode, IrWidth, captured);
      dr_scan(64'h0, IdcodeWidth, observed);
      void'(evidence.expect_equal("CHK-IDCODE-RAW", observed[31:0], expected_idcode, ctx));
      void'(evidence.expect_equal(
          "CHK-IDCODE-MARKER", observed[0], 1'b1, $sformatf("raw=0x%08h %s", observed[31:0], ctx)
      ));
      check_last_scan(1'b1, IrWidth, ctx);
      check_last_scan(1'b0, IdcodeWidth, ctx);
    end

    ir_scan(UnusedOpcode, IrWidth, captured);
    check_last_scan(1'b1, IrWidth, "IR churn");
    reset_to_idle();
    dr_scan(64'h0, IdcodeWidth, observed);
    void'(evidence.expect_equal(
        "CHK-JTAG-TLR-IDCODE",
        observed[31:0],
        expected_idcode,
        "TLR re-selects IDCODE after IR churn"
    ));
  endtask
endclass : ocah_jtag_idcode_test_seq
