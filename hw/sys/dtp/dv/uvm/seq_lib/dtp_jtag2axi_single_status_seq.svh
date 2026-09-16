// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG2AXI operation: one SINGLE_OP status capture. Shifts a zero
// request image through the target's SINGLE_OP register (the instruction is
// already loaded by dtp_jtag2axi_single_op_seq) and decodes the captured
// status and read data. Started by dtp_jtag2axi_base_test_seq::poll_single(),
// which bounds the polls and records CHK-AXI-COMPLETION. The cocotb twin is
// seq_lib/dtp_jtag2axi_single_status_seq.py.

class dtp_jtag2axi_single_status_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag2axi_single_status_seq)

  dtp_j2a_target_t target;
  // Results.
  dtp_j2a_status_e status = DTP_J2A_BUSY_OR_FULL;
  bit [63:0]       rdata;

  function new(string name = "dtp_jtag2axi_single_status_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit zeros[] = new[dtp_j2a_single_op_len(target)];
    bit rbits[];
    foreach (zeros[i]) zeros[i] = 1'b0;
    dr_scan_wide(zeros, rbits);
    dtp_j2a_unpack_single_op(target, rbits, status, rdata);
  endtask

endclass : dtp_jtag2axi_single_status_seq
