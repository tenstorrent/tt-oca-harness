// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG operation: one IR scan of `width` bits (LSB-first) from
// Run-Test/Idle back to Run-Test/Idle (VIP ir_scan), returning the captured
// TDO. A plain PTAP instruction load is width DtpIrWidth; a composed
// network-wide instruction scan is wider. Started by
// dtp_base_test_seq::ir_scan(). The cocotb realization is
// dtp_base_test_seq.load_ir and shift_ir.

class dtp_jtag_ir_scan_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag_ir_scan_seq)

  bit [63:0]   value;
  int unsigned width = DtpIrWidth;
  // Result: TDO captured during the scan.
  bit [63:0]   captured;

  function new(string name = "dtp_jtag_ir_scan_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    if (width == 0 || width > 64)
      `uvm_fatal(get_type_name(), $sformatf("IR scan width %0d outside 1..64", width))
    ir_scan(value, width, captured);
  endtask

endclass : dtp_jtag_ir_scan_seq
