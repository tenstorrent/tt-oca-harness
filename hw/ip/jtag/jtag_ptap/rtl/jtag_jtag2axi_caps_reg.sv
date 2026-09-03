// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// JTAG2AXI Capabilities Register
//
//-----------------------------------------------------------------------------

module jtag_jtag2axi_caps_reg
  import prim_jtag_pkg::*;
#(
  // AXI bus type parameter
  // Expected signature from AXI_TYPEDEF_ALL or AXI_LITE_TYPEDEF_ALL macros
  parameter type axi_req_t = logic,

  // Queue depth parameters
  parameter logic [1:0] RD_PL_DEPTH = 2'h3,  // Read pipeline depth (0 = single outstanding transaction)
  parameter logic [1:0] WR_PL_DEPTH = 2'h3,  // Write pipeline depth (0 = single outstanding transaction)

  // Bus type parameter
  // For AXI4 types (from AXI_TYPEDEF_ALL), set to 1'b0 (default)
  // For AXI4-Lite types (from AXI_LITE_TYPEDEF_ALL), set to 1'b1
  parameter bit IS_AXI4_LITE = 1'b0  // 0=AXI4, 1=AXI4-Lite
) (
  // JTAG DR scan control interface
  input  jtag_scan_ctrl_t  scan_ctrl_i,
  input  logic             scan_in_i,
  output logic             scan_out_o
);

  //--------------------------------------------------------------------------
  // Local Parameters
  //--------------------------------------------------------------------------
  localparam int unsigned REG_WIDTH = 14;  // JTAG2AXI_CAPS register: 14 bits (bits 0-13)

  //--------------------------------------------------------------------------
  // Local Type Definitions
  //--------------------------------------------------------------------------
  typedef logic [1:0] u2_t;
  typedef logic [2:0] u3_t;
  typedef logic [5:0] u6_t;

  //--------------------------------------------------------------------------
  // Extract AXI Bus Characteristics from Type Parameter
  //--------------------------------------------------------------------------
  // Create a dummy variable of the request type to extract field widths
  axi_req_t dummy_req;

  // Extract address width from aw.addr field (works for both AXI4 and AXI4-Lite)
  localparam int unsigned AXI_ADDR_WIDTH = $bits(dummy_req.aw.addr);

  // Extract data width from w.data field (works for both AXI4 and AXI4-Lite)
  localparam int unsigned AXI_DATA_WIDTH = $bits(dummy_req.w.data);

  // Convert data width to size encoding (powers of 2 bytes)
  // Encoding: 0=1B, 1=2B, 2=4B, 3=8B, 4=16B, 5=32B, 6=64B, 7=128B
  localparam int unsigned AXI_DATA_WIDTH_BYTES = AXI_DATA_WIDTH / 8;
  localparam int unsigned AXI_DATA_SIZE_ENCODING =
        (AXI_DATA_WIDTH_BYTES == 1)   ? 3'd0 :
        (AXI_DATA_WIDTH_BYTES == 2)   ? 3'd1 :
        (AXI_DATA_WIDTH_BYTES == 4)   ? 3'd2 :
        (AXI_DATA_WIDTH_BYTES == 8)   ? 3'd3 :
        (AXI_DATA_WIDTH_BYTES == 16)  ? 3'd4 :
        (AXI_DATA_WIDTH_BYTES == 32)  ? 3'd5 :
        (AXI_DATA_WIDTH_BYTES == 64)  ? 3'd6 :
        (AXI_DATA_WIDTH_BYTES == 128) ? 3'd7 : 3'd0;

  //--------------------------------------------------------------------------
  // JTAG2AXI Capabilities Value Construction
  //--------------------------------------------------------------------------
  // Bit field layout (from MSB to LSB, closest to TDI):
  // [13:12] = rd_pl_depth (2 bits) - read queue depth
  // [11:10] = wr_pl_depth (2 bits) - write queue depth
  // [9:7]   = data_size (3 bits) - AxDATA size in powers-of-2 bytes
  // [6:1]   = addr_size (6 bits) - AxADDR size in bits
  // [0]     = bus_type (1 bit) - 0=AXI4, 1=AXI4-Lite

  localparam logic [REG_WIDTH-1:0] CAPS_VALUE = {
    u2_t'(RD_PL_DEPTH),  // Bits [13:12] - rd_pl_depth
    u2_t'(WR_PL_DEPTH),  // Bits [11:10] - wr_pl_depth
    u3_t'(AXI_DATA_SIZE_ENCODING),  // Bits [9:7]   - data_size
    u6_t'(AXI_ADDR_WIDTH),  // Bits [6:1]   - addr_size
    IS_AXI4_LITE  // Bit  [0]     - bus_type
  };

  //--------------------------------------------------------------------------
  // JTAG2AXI Capabilities Register
  //--------------------------------------------------------------------------
  // 14-bit read-only capabilities register
  prim_jtag_scan_reg #(
    .WIDTH(REG_WIDTH),
    .RESET_VAL(CAPS_VALUE),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_2axi_caps_scan_reg (
    .scan_ctrl_i   (scan_ctrl_i),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (scan_out_o),
    .data_in_i     (CAPS_VALUE),
    .data_out_o    (/* UNUSED */)
  );

endmodule : jtag_jtag2axi_caps_reg
