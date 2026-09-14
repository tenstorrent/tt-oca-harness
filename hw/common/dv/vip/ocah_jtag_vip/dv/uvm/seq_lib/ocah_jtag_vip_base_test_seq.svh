// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base of the harness scenario sequences: the handles the test binds before
// start() and the helpers every scenario repeats (the device's one-hot TAP
// state, the newest reconstructed scan, a Run-Test/Idle landing after a TAP
// reset, a scan paused in Pause-x, a capture-only scan). The cocotb twin
// is the helper set of ocah_jtag_vip_harness.py.

class ocah_jtag_vip_base_test_seq extends ocah_jtag_master_sequence;
  `uvm_object_utils(ocah_jtag_vip_base_test_seq)

  // Bound by the test before start().
  ocah_jtag_checker        evidence;
  ocah_jtag_slave_sequence slave_seq;
  ocah_jtag_scan_builder   scans;

  localparam int unsigned IrWidth = 5;
  localparam int unsigned IdcodeWidth = 32;
  localparam bit [31:0] Idcode = 32'h1B34_C0D1;
  localparam bit [63:0] IdcodeOpcode = 64'h1;
  localparam bit [63:0] CtrlOpcode = 64'h2;
  localparam int unsigned CtrlWidth = 16;
  localparam bit [63:0] StatusOpcode = 64'h3;
  localparam int unsigned StatusWidth = 8;
  localparam bit [63:0] UnusedOpcode = 64'h0A;
  localparam bit [63:0] BypassOpcode = 64'h1F;
  localparam string NegativeKnob = "OCAH_JTAG_SELFTEST_NEGATIVE";

  function new(string name = "ocah_jtag_vip_base_test_seq");
    super.new(name);
  endfunction

  protected function void require_handles();
    if (evidence == null || slave_seq == null || scans == null)
      `uvm_fatal(get_type_name(), "evidence/slave_seq/scans handles not bound")
  endfunction

  // The device's TAP controller state as the one-hot the checker consumes.
  protected function bit [15:0] device_onehot();
    return 16'h1 << int'(slave_seq.responder.device_state());
  endfunction

  // TAP reset, then one TMS-low cycle so the scans start from Run-Test/Idle.
  protected task reset_to_idle();
    tap_reset_op();
    step(1'b0);
  endtask

  // Scan `value` LSB-first with a Pause-x stop of `pause_cycles` TCK cycles
  // after `split` bits, as raw steps from Run-Test/Idle along the IEEE 1149.1
  // controller diagram: Select-x, Capture-x, Shift-x, Exit1-x, Pause-x,
  // Exit2-x, then Shift-x for the remaining bits and Exit1-x, or Update-x
  // straight from Exit2-x when `split` equals `width`; Update-x,
  // Run-Test/Idle. The device holds its shift register across the pause and
  // the scan builder publishes the whole scan at the last Exit1-x. The device
  // state is judged in the pause (CHK-SLAVE-STATE).
  protected task paused_scan(bit is_ir, bit [63:0] value, int unsigned width, int unsigned split,
                             int unsigned pause_cycles, string context_s);
    ocah_jtag_tap_state_e pause_state = is_ir ? OCAH_JTAG_PAUSE_IR : OCAH_JTAG_PAUSE_DR;
    if (split == 0 || split > width || pause_cycles == 0)
      `uvm_fatal(get_type_name(), $sformatf(
                 "paused_scan: split=%0d width=%0d pause_cycles=%0d", split, width, pause_cycles))
    step(1'b1);  // Run-Test/Idle -> Select-DR-Scan
    if (is_ir) step(1'b1);  // Select-DR-Scan -> Select-IR-Scan
    step(1'b0);  // Select-x -> Capture-x
    step(1'b0);  // Capture-x -> Shift-x
    for (int unsigned i = 0; i < split; i++) step(i == split - 1, value[i]);
    step(1'b0);  // Exit1-x -> Pause-x
    repeat (pause_cycles) step(1'b0);
    void'(slave_seq.check_state(pause_state, {context_s, " pause"}));
    step(1'b1);  // Pause-x -> Exit2-x
    if (split < width) begin
      step(1'b0);  // Exit2-x -> Shift-x
      for (int unsigned i = split; i < width; i++) step(i == width - 1, value[i]);
    end
    step(1'b1);  // Exit1-x or Exit2-x -> Update-x
    step(1'b0);  // Update-x -> Run-Test/Idle
  endtask

  // A scan with no Shift-x cycle, as raw steps from Run-Test/Idle and back:
  // a DR scan captures the selected register and latches that value again;
  // an IR scan loads the device's instruction capture pattern.
  protected task capture_only_scan(bit is_ir);
    step(1'b1);  // Run-Test/Idle -> Select-DR-Scan
    if (is_ir) step(1'b1);  // Select-DR-Scan -> Select-IR-Scan
    step(1'b0);  // Select-x -> Capture-x
    step(1'b1);  // Capture-x -> Exit1-x
    step(1'b1);  // Exit1-x -> Update-x
    step(1'b0);  // Update-x -> Run-Test/Idle
  endtask

  // CHK-SCAN-IR-LEN / CHK-SCAN-DR-LEN on the newest reconstructed scan.
  protected function void check_last_scan(bit is_ir, int unsigned width, string context_s);
    ocah_jtag_scan_item items[$];
    items = is_ir ? scans.ir_items : scans.dr_items;
    if (items.size() == 0)
      `uvm_fatal(get_type_name(), $sformatf(
                 "no reconstructed %s scan observed (%s)", is_ir ? "IR" : "DR", context_s))
    void'(evidence.check_scan_length(items[$], width, context_s));
  endfunction
endclass : ocah_jtag_vip_base_test_seq
