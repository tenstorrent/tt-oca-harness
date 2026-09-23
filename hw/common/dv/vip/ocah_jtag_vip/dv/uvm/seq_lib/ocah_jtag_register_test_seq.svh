// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_jtag_register_test (the SV-UVM twin of the cocotb
// selftest): host writes to the writable CTRL register latch on Update-DR,
// are recorded by the device, and read back over the bus; a write paused in
// Pause-DR latches whole and reconstructs at its full width, whether the scan
// resumes shifting after the pause or updates straight from Exit2-DR; a
// capture-only scan (no Shift-DR cycle) latches the captured value back; the
// read-only
// STATUS register captures its stored value and never latches; every IR and
// DR scan reconstructs at its driven width.

class ocah_jtag_register_test_seq extends ocah_jtag_vip_base_test_seq;
  `uvm_object_utils(ocah_jtag_register_test_seq)

  int unsigned n_writes = 6;
  int unsigned pause_cycles = 4;
  // Pause after half the bits (the scan resumes shifting) and after the last
  // bit (the scan updates from Exit2-DR).
  localparam int unsigned PauseSplits[2] = '{CtrlWidth / 2, CtrlWidth};

  function new(string name = "ocah_jtag_register_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] captured, readback, value, status, paused;
    int unsigned updates_before;
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

    // Writes paused in Pause-DR latch whole: one resumes shifting after the
    // pause, one pauses after its last bit and updates from Exit2-DR. A
    // capture-only scan then latches the captured value back, and the
    // readback that follows returns the last paused value: four more CTRL
    // updates.
    foreach (PauseSplits[i]) begin
      string label = (PauseSplits[i] < CtrlWidth) ? "resumed" : "completed";
      string ctx = {label, " paused write"};
      paused = 64'($urandom()) & 64'hFFFF;
      paused_scan(1'b0, paused, CtrlWidth, PauseSplits[i], pause_cycles, ctx);
      check_last_scan(1'b0, CtrlWidth, ctx);
      void'(slave_seq.check_last_update("CTRL", paused, ctx));
    end
    updates_before = slave_seq.responder.updates.size();
    capture_only_scan(1'b0);
    void'(evidence.expect_equal(
        "CHK-JTAG-DR-CAPTURE-ONLY",
        64'(slave_seq.responder.updates.size() - updates_before),
        64'd1,
        "a capture-only scan latches once"
    ));
    void'(slave_seq.check_last_update(
        "CTRL", paused, "capture-only scan latches the captured value"
    ));
    dr_scan(64'h0, CtrlWidth, readback);
    void'(evidence.expect_equal(
        "CHK-JTAG-DR-PAUSE",
        readback,
        paused,
        $sformatf(
            "readback after a write paused %0d cycles and a capture-only scan", pause_cycles)
    ));
    void'(slave_seq.check_update_count(
        2 * n_writes + 4,
        "CTRL",
        "one write and one readback scan per value, two paused writes, the capture-only scan, and its readback"
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
