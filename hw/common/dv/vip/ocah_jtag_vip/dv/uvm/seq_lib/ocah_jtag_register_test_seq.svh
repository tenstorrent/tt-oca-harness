// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_jtag_register_test (the SV-UVM twin of the cocotb
// selftest): host writes to the writable CTRL register latch on Update-DR,
// are recorded by the device, and read back over the bus; the read-only
// STATUS register captures its stored value and never latches; every IR and
// DR scan reconstructs at its driven width.

class ocah_jtag_register_test_seq extends ocah_jtag_vip_base_test_seq;
  `uvm_object_utils(ocah_jtag_register_test_seq)

  int unsigned n_writes = 6;

  function new(string name = "ocah_jtag_register_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] captured, readback, value, status;
    require_handles();
    if (n_writes < 2)
      `uvm_fatal(get_type_name(), $sformatf(
                 "n_writes must be >= 2 (value corners); got %0d", n_writes))

    reset_to_idle();
    for (int unsigned index = 0; index < n_writes; index++) begin
      string ctx = $sformatf("write %0d", index);
      case (index)
        0:       value = 64'h0;
        1:       value = 64'hFFFF;
        default: value = 64'($urandom()) & 64'hFFFF;
      endcase
      ir_scan(CtrlOpcode, IrWidth, captured);
      check_last_scan(1'b1, IrWidth, $sformatf("select %0d", index));
      dr_scan(value, CtrlWidth, captured);
      check_last_scan(1'b0, CtrlWidth, ctx);
      void'(slave_seq.check_last_update("CTRL", value, ctx));
      void'(slave_seq.check_register("CTRL", value, ctx));
      // The readback scan shifts zeros in, so its own Update-DR latches 0.
      dr_scan(64'h0, CtrlWidth, readback);
      void'(evidence.expect_equal("CHK-JTAG-DR-READBACK", readback, value, ctx));
    end
    void'(slave_seq.check_update_count(
        2 * n_writes, "CTRL", "one write and one readback scan per value"
    ));

    status = 64'($urandom()) & 64'hFF;
    slave_seq.set_register(StatusOpcode, status);
    ir_scan(StatusOpcode, IrWidth, captured);
    dr_scan(64'hFF, StatusWidth, captured);
    void'(evidence.expect_equal("CHK-JTAG-RO-CAPTURE", captured, status, "read-only capture"));
    void'(slave_seq.check_update_count(0, "STATUS", "a read-only register never latches"));
    void'(slave_seq.check_register("STATUS", status, "stored value survives the host write"));
  endtask
endclass : ocah_jtag_register_test_seq
