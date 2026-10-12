// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Expose a read-only TDR for JTAG2AXI bridge pipeline depths and bus type.
//
// Encodes RD_PL_DEPTH and WR_PL_DEPTH where 0 means a single outstanding transaction.
// IS_AXI4_LITE is 0 for AXI4 typedefs and 1 for AXI4-Lite typedefs. The address width
// (bits [6:1]) and the log2 data size in bytes (bits [9:7]) are derived from the aw.addr and
// w.data fields of axi_req_t.

module jtag_jtag2axi_caps_reg
  import prim_jtag_pkg::jtag_scan_ctrl_t;
#(
  parameter type axi_req_t = logic,     // AXI request struct type; its aw.addr and w.data widths
                                        // set the addr_size and data_size fields.

  parameter logic [1:0] RD_PL_DEPTH = 2'h3,  // Read pipeline depth (0 = single outstanding
                                             // transaction), bits [13:12].
  parameter logic [1:0] WR_PL_DEPTH = 2'h3,  // Write pipeline depth (0 = single outstanding
                                             // transaction), bits [11:10].

  parameter bit IS_AXI4_LITE = 1'b0     // Bus type in bit 0: 0=AXI4, 1=AXI4-Lite.
) (
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o   // Scan data out (TDO).
);

  //--------------------------------------------------------------------------
  // Local Parameters
  //--------------------------------------------------------------------------
  localparam int unsigned RegWidth = 14;  // JTAG2AXI_CAPS register: 14 bits (bits 0-13)

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
  localparam int unsigned AxiAddrWidth = $bits(dummy_req.aw.addr);

  // Extract data width from w.data field (works for both AXI4 and AXI4-Lite)
  localparam int unsigned AxiDataWidth = $bits(dummy_req.w.data);

  // Convert data width to size encoding (powers of 2 bytes)
  // Encoding: 0=1B, 1=2B, 2=4B, 3=8B, 4=16B, 5=32B, 6=64B, 7=128B
  localparam int unsigned AxiDataWidthBytes = AxiDataWidth / 8;
  localparam int unsigned AxiDataSizeEncoding =
        (AxiDataWidthBytes == 1)   ? 3'd0 :
        (AxiDataWidthBytes == 2)   ? 3'd1 :
        (AxiDataWidthBytes == 4)   ? 3'd2 :
        (AxiDataWidthBytes == 8)   ? 3'd3 :
        (AxiDataWidthBytes == 16)  ? 3'd4 :
        (AxiDataWidthBytes == 32)  ? 3'd5 :
        (AxiDataWidthBytes == 64)  ? 3'd6 :
        (AxiDataWidthBytes == 128) ? 3'd7 : 3'd0;

  //--------------------------------------------------------------------------
  // JTAG2AXI Capabilities Value Construction
  //--------------------------------------------------------------------------
  // Bit field layout (from MSB to LSB, closest to TDI):
  // [13:12] = rd_pl_depth (2 bits) - read queue depth
  // [11:10] = wr_pl_depth (2 bits) - write queue depth
  // [9:7]   = data_size (3 bits) - AxDATA size in powers-of-2 bytes
  // [6:1]   = addr_size (6 bits) - AxADDR size in bits
  // [0]     = bus_type (1 bit) - 0=AXI4, 1=AXI4-Lite

  localparam logic [RegWidth-1:0] CapsValue = {
    u2_t'(RD_PL_DEPTH),  // Bits [13:12] - rd_pl_depth
    u2_t'(WR_PL_DEPTH),  // Bits [11:10] - wr_pl_depth
    u3_t'(AxiDataSizeEncoding),  // Bits [9:7]   - data_size
    u6_t'(AxiAddrWidth),  // Bits [6:1]   - addr_size
    IS_AXI4_LITE  // Bit  [0]     - bus_type
  };

  //--------------------------------------------------------------------------
  // JTAG2AXI Capabilities Register
  //--------------------------------------------------------------------------
  // 14-bit read-only capabilities register
  prim_jtag_scan_reg #(
    .WIDTH(RegWidth),
    .RESET_VAL(CapsValue),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_2axi_caps_scan_reg (
    .scan_ctrl_i   (scan_ctrl_i),
    .scan_in_i     (scan_in_i),
    .scan_out_o    (scan_out_o),
    .data_in_i     (CapsValue),
    .data_out_o    (/* UNUSED */)
  );

endmodule : jtag_jtag2axi_caps_reg
