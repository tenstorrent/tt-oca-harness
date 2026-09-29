// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG2AXI operation: one SINGLE_OP status capture on the SMC-fabric
// bridge. Shifts a zero request image through the target's SINGLE_OP
// register (the instruction is already loaded by
// smu_jtag2axi_single_op_seq) and decodes the captured status and read
// data (dtp_env_pkg codec). Started by smu_base_test_seq::poll_single_j2a(),
// which bounds the polls and records the TIMEOUT-PATH site. Mirrors the DTP
// bench's dtp_jtag2axi_single_status_seq (hw/sys/dtp/dv/uvm/seq_lib).

class smu_jtag2axi_single_status_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag2axi_single_status_seq)

  dtp_env_pkg::dtp_j2a_target_t target;
  // Results.
  dtp_env_pkg::dtp_j2a_status_e status = dtp_env_pkg::DTP_J2A_BUSY_OR_FULL;
  bit [63:0]                    rdata;

  function new(string name = "smu_jtag2axi_single_status_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit zeros[] = new[dtp_env_pkg::dtp_j2a_single_op_len(target)];
    bit rbits[];
    foreach (zeros[i]) zeros[i] = 1'b0;
    dr_scan_wide(zeros, rbits);
    dtp_env_pkg::dtp_j2a_unpack_single_op(target, rbits, status, rdata);
  endtask

endclass : smu_jtag2axi_single_status_seq
