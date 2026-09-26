// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Shift the IEEE 1149.1 IDCODE value assembled from manufacturer, part, and revision parameters.
//
// IDCODE_MFR_ID is 11 bits, IDCODE_PART_NUM 16 bits, and IDCODE_SI_REV 4 bits, packed as
// {IDCODE_SI_REV, IDCODE_PART_NUM, IDCODE_MFR_ID, 1'b1} with bit 0 nearest TDO.
// scan_ctrl_i selects capture and shift on the DR path between scan_in_i and scan_out_o.

module jtag_idcode_reg
  import prim_jtag_pkg::*;
#(
  parameter logic [10:0]  IDCODE_MFR_ID   = 11'h000,  // JTAG IDCODE manufacturer ID, bits [11:1].
  parameter logic [15:0]  IDCODE_PART_NUM = 16'h0000,  // JTAG IDCODE part number, bits [27:12].
  parameter logic [3:0]   IDCODE_SI_REV   = 4'h0  // JTAG IDCODE silicon revision, bits [31:28].
) (
  /* verilator lint_off UNUSEDSIGNAL */
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  /* verilator lint_on UNUSEDSIGNAL */
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o   // Scan data out (TDO).
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

