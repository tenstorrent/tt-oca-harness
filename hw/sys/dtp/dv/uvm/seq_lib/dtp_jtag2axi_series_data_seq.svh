// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable JTAG2AXI operation: one series-data shift on a bridge: load the
// selected SERIES_DATA instruction (address-increment, no-increment, or
// with-error-status), shift the payload-sized data word plus, in
// with-status mode, the MSB increment bit, then idle
// DtpJ2aSeriesLaunchCycles TCK cycles for the op to launch in the system
// domain. Returns the captured word (read data and, in with-status mode,
// the status bit above the payload). Started by
// dtp_jtag2axi_base_test_seq::series_data_*(). The cocotb twin is
// seq_lib/dtp_jtag2axi_series_data_seq.py.

class dtp_jtag2axi_series_data_seq extends dtp_jtag_op_seq;
  `uvm_object_utils(dtp_jtag2axi_series_data_seq)

  dtp_j2a_target_t                      target;
  jtag_inst_reg_pkg::jtag_instruction_e instr;
  bit [63:0]                            data;
  int unsigned                          size;
  // With-status mode carries one increment/status bit above the payload;
  // -1 selects the plain payload-only shift.
  int                                   increment = -1;
  // Result: the captured payload and, in with-status mode, the status bit
  // above it (1 = the previous transaction failed).
  bit [63:0]                            captured;
  bit                                   captured_status;

  function new(string name = "dtp_jtag2axi_series_data_seq");
    super.new(name);
  endfunction

  virtual task do_op();
    int unsigned payload_bits = 8 * dtp_j2a_size_bytes(size);
    int unsigned width = payload_bits + ((increment >= 0) ? 1 : 0);
    bit pattern[] = new[width];
    bit rbits[];
    bit [63:0] ir_captured;
    for (int unsigned i = 0; i < payload_bits; i++) pattern[i] = data[i];
    if (increment >= 0) pattern[payload_bits] = bit'(increment);
    ir_scan(64'(instr), DtpIrWidth, ir_captured);
    dr_scan_wide(pattern, rbits);
    captured = '0;
    captured_status = 1'b0;
    foreach (rbits[i]) if (i < payload_bits && i < 64) captured[i] = rbits[i];
    if (increment >= 0 && payload_bits < rbits.size()) captured_status = rbits[payload_bits];
    repeat (DtpJ2aSeriesLaunchCycles) step(1'b0);
  endtask

endclass : dtp_jtag2axi_series_data_seq
