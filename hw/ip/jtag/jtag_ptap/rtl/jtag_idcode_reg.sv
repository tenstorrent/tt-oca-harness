// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG IDCODE Register
//
//-----------------------------------------------------------------------------

module jtag_idcode_reg
  import prim_jtag_pkg::*;
#(
  parameter logic [10:0]  IDCODE_MFR_ID   = 11'h000,   // JTAG IDCODE manufacturer ID (11 bits)
  parameter logic [15:0]  IDCODE_PART_NUM = 16'h0000,  // JTAG IDCODE part number (16 bits)
  parameter logic [3:0]   IDCODE_SI_REV   = 4'h0       // JTAG IDCODE silicon revision (4 bits)
) (
  /* verilator lint_off UNUSEDSIGNAL */
  // JTAG DR scan control interface
  input  jtag_scan_ctrl_t  scan_ctrl_i,
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,
  output logic             scan_out_o
);

  //--------------------------------------------------------------------------
  // Local Parameters
  //--------------------------------------------------------------------------
  localparam int unsigned REG_WIDTH = 32;  // IDCODE register is always 32 bits per IEEE 1149.1 Section 12

  //--------------------------------------------------------------------------
  // IDCODE Value Construction (IEEE 1149.1 Section 12)
  //--------------------------------------------------------------------------
  // Format: [31:28] = Version (4 bits)
  //         [27:12] = Part Number (16 bits)
  //         [11:1]  = Manufacturer ID (11 bits)
  //         [0]     = Always 1
  localparam logic [REG_WIDTH-1:0] IDCODE_VALUE = {
    IDCODE_SI_REV,  // Bits [31:28] - Silicon revision/version
    IDCODE_PART_NUM,  // Bits [27:12] - Part number
    IDCODE_MFR_ID,  // Bits [11:1]  - Manufacturer ID
    1'b1  // Bit  [0]     - Always 1 per IEEE 1149.1
  };

  //--------------------------------------------------------------------------
  // IDCODE Shift Register
  //--------------------------------------------------------------------------

  // 32-bit read-only IDCODE register
  // Per IEEE 1149.1 Section 12: captures IDCODE value on capture, shifts on shift
  prim_jtag_scan_reg #(
    .WIDTH(REG_WIDTH),
    .RESET_VAL(IDCODE_VALUE),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_idcode_scan_reg (
    .scan_ctrl_i   (scan_ctrl_i),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (scan_out_o),
    .data_in_i     (IDCODE_VALUE),  // Always capture the IDCODE value (read-only)
    /* verilator lint_off PINCONNECTEMPTY */
    .data_out_o    (/* UNUSED */)   // No update register needed for read-only IDCODE
    /* verilator lint_on PINCONNECTEMPTY */
  );

endmodule : jtag_idcode_reg

