// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG2AXI operation: one SINGLE_OP status capture. Shifts a zero
// request image through the target's SINGLE_OP register (the instruction is
// already loaded by dtp_jtag2axi_single_op_seq) and decodes the captured
// status and read data; `captured` holds the whole image. Started by
// dtp_jtag2axi_base_test_seq::poll_single(), which bounds the polls and
// records CHK-AXI-COMPLETION. The cocotb realization captures the register
// from dtp_jtag2axi_base_test_seq.poll_target_single_status.

class dtp_jtag2axi_single_status_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag2axi_single_status_seq)

  dtp_j2a_target_t target;
  // Results.
  dtp_j2a_status_e status = DTP_J2A_BUSY_OR_FULL;
  bit [63:0]       rdata;
  bit              captured[];

  function new(string name = "dtp_jtag2axi_single_status_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit zeros[] = new[dtp_j2a_single_op_len(target)];
    foreach (zeros[i]) zeros[i] = 1'b0;
    dr_scan_wide(zeros, captured);
    dtp_j2a_unpack_single_op(target, captured, status, rdata);
  endtask

endclass : dtp_jtag2axi_single_status_seq
