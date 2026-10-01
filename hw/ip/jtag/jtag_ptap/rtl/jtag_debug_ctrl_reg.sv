// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Implement the DEBUG_CONTROL TDR for clock-stop and boot-stall controls.
//
// Captures cla_clock_stop_i, synchronized to TCK through two flops, into bit 4 and updates
// the control outputs from bits [3:0] on the falling TCK edge of Update-DR; bit 0 is nearest
// TDO. Drives jtag_clock_stop_o, cla_clock_stop_en_o, boot_stall_ovrd_o, and boot_stall_o,
// which reset low on the scan-control reset.

module jtag_debug_ctrl_reg
  import prim_jtag_pkg::*;
(
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o,  // Scan data out (TDO).

  input  logic             cla_clock_stop_i,  // CLA clock stop status; asynchronous, synchronized
                                              // to TCK.

  output logic             jtag_clock_stop_o,  // JTAG stop clock control, bit 3.
  output logic             cla_clock_stop_en_o,  // CLA clock stop enable, bit 2.
  output logic             boot_stall_ovrd_o,  // Boot stall override enable, bit 1.
  output logic             boot_stall_o  // Boot stall control value, bit 0.
);

  //--------------------------------------------------------------------------
  // Local Parameters
  //--------------------------------------------------------------------------
  localparam int unsigned REG_WIDTH = 5;  // DEBUG_CTRL register: 5 bits (bits 0-4)

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  logic [REG_WIDTH-1:0] debug_ctrl_reg_q;  // Debug control register output (update register)

  //--------------------------------------------------------------------------
  // Bit Field Assignments
  //--------------------------------------------------------------------------
  // Bit [4]: cla_clock_stop - RO (closest to TDI)
  // Bit [3]: jtag_clock_stop - R/W
  // Bit [2]: cla_clock_stop_en - R/W
  // Bit [1]: boot_stall_ovrd - R/W
  // Bit [0]: boot_stall - R/W (closest to TDO)

  //--------------------------------------------------------------------------
  // Synchronize cla_clock_stop_i to TCK
  //--------------------------------------------------------------------------
  // cla_clock_stop_i originates from the ck_feedthru clock domain (CLA chiplet
  // requests aggregated by ctn_clock_stop_ctrl). It must be synchronized to
  // JTAG_TCK before capture into the scan register.
  //
  // The JTAG state machine navigates through at least 2 TCK edges between any
  // idle state and Capture-DR (RTI→Select-DR-Scan→Capture-DR), which gives the
  // 2-stage synchronizer exactly the time it needs to resolve metastability before
  // the scan register latches the value in Capture-DR.
  logic cla_clock_stop_sync;
  prim_flop_2sync #(
    .Width(1)
  ) u_cla_clock_stop_sync (
    .clk_i  (scan_ctrl_i.tck),
    .rst_ni (1'b1),
    .d_i    (cla_clock_stop_i),
    .q_o    (cla_clock_stop_sync)
  );

  //--------------------------------------------------------------------------
  // Debug Control Register
  //--------------------------------------------------------------------------
  // Per table specification:
  // - Bit [4]: cla_clock_stop - read-only, captures synchronized status from input
  // - Bits [3:0]: R/W control bits
  // On capture: bit 4 captures cla_clock_stop_sync, bits [3:0] retain their value
  prim_jtag_scan_reg #(
    .WIDTH(REG_WIDTH),
    .RESET_VAL(5'b00000),  // All bits reset to 0
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_debug_ctrl_scan_reg (
    .scan_ctrl_i   (scan_ctrl_i),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (scan_out_o),
    .data_in_i     ({cla_clock_stop_sync, debug_ctrl_reg_q[3:0]}),
    .data_out_o    (debug_ctrl_reg_q)
  );

  //--------------------------------------------------------------------------
  // Extract Control Bits from Register
  //--------------------------------------------------------------------------
  // Output assignments from update register (data_out_o) which holds stable values after update
  assign jtag_clock_stop_o   = debug_ctrl_reg_q[3];
  assign cla_clock_stop_en_o = debug_ctrl_reg_q[2];
  assign boot_stall_ovrd_o   = debug_ctrl_reg_q[1];
  assign boot_stall_o        = debug_ctrl_reg_q[0];

endmodule : jtag_debug_ctrl_reg
