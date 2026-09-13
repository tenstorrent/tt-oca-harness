// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base of the harness scenario sequences: the handles the test binds before
// start() and the helpers every scenario repeats (the device's one-hot TAP
// state, the newest reconstructed scan, a Run-Test/Idle landing after a TAP
// reset). The cocotb twin is the helper set of ocah_jtag_vip_harness.py.

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
