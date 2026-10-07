// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG2AXI operation: issue one SINGLE_OP request to a bridge:
// pack OP | SIZE | WSTRB | DATA | ADDR (dtp_types codec), load the target's
// SINGLE_OP instruction, and shift the request through the wide DR path.
// The bridge launches the AXI transaction in the system domain after the
// shift; dtp_jtag2axi_single_status_seq polls its completion. `captured`
// holds the image the request's own Capture-DR shifted out. Started by
// dtp_jtag2axi_base_test_seq::issue_single(), which owns the evidence
// arming. The cocotb realization issues the request from
// dtp_jtag2axi_base_test_seq.write_target_single_raw.

class dtp_jtag2axi_single_op_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag2axi_single_op_seq)

  dtp_j2a_target_t  target;
  dtp_j2a_request_t request;
  // Result.
  bit               captured[];

  function new(string name = "dtp_jtag2axi_single_op_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit dr[];
    bit [63:0] ir_captured;
    dtp_j2a_pack_single_op(target, request, dr);
    ir_scan(64'(target.single_op_instr), DtpIrWidth, ir_captured);
    dr_scan_wide(dr, captured);
  endtask

endclass : dtp_jtag2axi_single_op_seq
