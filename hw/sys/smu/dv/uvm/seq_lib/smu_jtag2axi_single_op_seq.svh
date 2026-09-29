// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG2AXI operation: issue one SINGLE_OP request to the SMC-fabric
// bridge the embedded DTP exposes on its primary TAP: pack OP | SIZE |
// WSTRB | DATA | ADDR (dtp_env_pkg codec, the same codec and geometry the
// DTP bench uses for this bridge), load the target's SINGLE_OP instruction,
// and shift the request through the wide DR path. The bridge launches the
// AXI transaction in the SMU domain after the shift;
// smu_jtag2axi_single_status_seq polls its completion. Started by
// smu_base_test_seq::issue_single_j2a(). Mirrors the DTP bench's
// dtp_jtag2axi_single_op_seq (hw/sys/dtp/dv/uvm/seq_lib).

class smu_jtag2axi_single_op_seq extends smu_jtag_op_seq;
  `uvm_object_utils(smu_jtag2axi_single_op_seq)

  dtp_env_pkg::dtp_j2a_target_t target;
  dtp_env_pkg::dtp_j2a_op_e     op = dtp_env_pkg::DTP_J2A_OP_NOP;
  bit [63:0]                    addr;
  bit [63:0]                    data;
  bit [7:0]                     wstrb;
  int unsigned                  size;

  function new(string name = "smu_jtag2axi_single_op_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit dr[];
    bit unused[];
    bit [63:0] ir_captured;
    dtp_env_pkg::dtp_j2a_pack_single_op(target, op, addr, data, wstrb, size, dr);
    ir_scan(64'(target.single_op_instr), dtp_env_pkg::DtpIrWidth, ir_captured);
    dr_scan_wide(dr, unused);
  endtask

endclass : smu_jtag2axi_single_op_seq
