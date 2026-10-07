// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG2AXI operation: one SERIES_CTRL register access on a bridge:
// load the target's SERIES_CTRL instruction and shift the packed
// OP | SIZE | PL_DEPTH | ADDR | RESET word (dtp_types codec), returning the
// captured word for the caller to decode. A WRITE or READ op arms a stream,
// NOP with reset clears it, and a NOP image reads the settled status.
// Started by dtp_jtag2axi_base_test_seq::series_ctrl_op() and
// read_series_ctrl(). The cocotb realization issues this access from
// dtp_jtag2axi_base_test_seq.jtag2axi_series_ctrl and read_series_ctrl.

class dtp_jtag2axi_series_ctrl_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag2axi_series_ctrl_seq)

  dtp_j2a_target_t target;
  dtp_j2a_op_e     op = DTP_J2A_OP_NOP;
  bit [63:0]       addr;
  int unsigned     size;
  int unsigned     pipeline_depth;
  bit              series_reset;
  // Result: the SERIES_CTRL word captured while shifting.
  bit [63:0]       captured;

  function new(string name = "dtp_jtag2axi_series_ctrl_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    bit [63:0] value = dtp_j2a_pack_series_ctrl(target, op, addr, pipeline_depth, size,
                                                    series_reset);
    bit [63:0] ir_captured;
    ir_scan(64'(target.series_ctrl_instr), DtpIrWidth, ir_captured);
    dr_scan(value, dtp_j2a_series_ctrl_len(target), captured);
  endtask

endclass : dtp_jtag2axi_series_ctrl_seq
