// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Stub for i3ccore_wrapper - all outputs driven to 0

module i3ccore_wrapper #(
  parameter int unsigned NUM_I3C = 2,
  parameter int unsigned I3C_REG_ADDR_WIDTH = 11,
  parameter int unsigned BASE_ADDR = 0,
  parameter int unsigned INSTANCE_SPACING = 32'h500,

  parameter int unsigned DatAw = 4,
  parameter int unsigned DctAw = 4,

  parameter int unsigned CsrAddrWidth = 11,
  parameter int unsigned CsrDataWidth = 32,

  parameter int unsigned HciRespFifoDepth = 8,
  parameter int unsigned HciCmdFifoDepth  = 8,
  parameter int unsigned HciRxFifoDepth   = 8,
  parameter int unsigned HciTxFifoDepth   = 8,
  parameter int unsigned HciIbiFifoDepth  = 8,

  parameter int unsigned TtiRxDescFifoDepth = 8,
  parameter int unsigned TtiTxDescFifoDepth = 8,
  parameter int unsigned TtiRxFifoDepth = 8,
  parameter int unsigned TtiTxFifoDepth = 8,
  parameter int unsigned TtiIbiFifoDepth = 8,

  localparam int unsigned SelectWidth = (NUM_I3C > 32'd1) ? $clog2(NUM_I3C) : 32'd1,
  localparam type select_t = logic [SelectWidth-1:0]
) (
  input wire logic clk_i,
  input wire logic rst_ni,

  // AXI4-Lite slave interface
  // Write Address Channel
  input  wire logic        awvalid_i,
  output logic             awready_o,
  input  wire logic [31:0] awaddr_i,
  input  wire logic [ 2:0] awprot_i,

  // Write Data Channel
  input  wire logic        wvalid_i,
  output logic             wready_o,
  input  wire logic [31:0] wdata_i,
  input  wire logic [ 3:0] wstrb_i,

  // Write Response Channel
  output logic            bvalid_o,
  input  wire logic       bready_i,
  output logic      [1:0] bresp_o,

  // Read Address Channel
  input  wire logic        arvalid_i,
  output logic             arready_o,
  input  wire logic [31:0] araddr_i,
  input  wire logic [ 2:0] arprot_i,

  // Read Data Channel
  output logic             rvalid_o,
  input  wire logic        rready_i,
  output logic      [31:0] rdata_o,
  output logic      [ 1:0] rresp_o,

  // Interrupts - one per I3C instance
  output logic [NUM_I3C-1:0] irq_o,

  // I3C bus signals - one set per instance
  input wire logic [NUM_I3C-1:0] scl_i,
  input wire logic [NUM_I3C-1:0] sda_i,
  output logic [NUM_I3C-1:0] scl_o,
  output logic [NUM_I3C-1:0] sda_o,
  output logic [NUM_I3C-1:0] scl_oe_o,
  output logic [NUM_I3C-1:0] sda_oe_o,
  output logic [NUM_I3C-1:0] sel_od_pp_o,

  // Recovery interface signals
  output logic [NUM_I3C-1:0] recovery_payload_available_o,
  output logic [NUM_I3C-1:0] recovery_image_activated_o,
  output logic [NUM_I3C-1:0] peripheral_reset_o,
  input wire logic [NUM_I3C-1:0] peripheral_reset_done_i,
  output logic [NUM_I3C-1:0] escalated_reset_o,

  // I3C DAT/DCT memory interfaces (NUM_I3C instances)
  // dat_mem_src_t:  {rdata[63:0], rvalid, rerror[1:0]} = 67 bits
  // dat_mem_sink_t: {req, write, addr[3:0], wdata[63:0], wmask[63:0]} = 134 bits
  // dct_mem_src_t:  {rdata[127:0], rvalid, rerror[1:0]} = 131 bits
  // dct_mem_sink_t: {req, write, addr[3:0], wdata[127:0], wmask[127:0]} = 262 bits
  input  wire logic [NUM_I3C-1:0] dat_mem_src_i,
  output logic      [NUM_I3C-1:0] dat_mem_sink_o,
  input  wire logic [NUM_I3C-1:0] dct_mem_src_i,
  output logic      [NUM_I3C-1:0] dct_mem_sink_o,
  // I3C RLT (reverse-lookup table) memory interface (dual-port, NUM_I3C instances)
  // rlt_mem_src_t:  {a_rdata[DatAw-1:0], b_rdata[DatAw-1:0]}
  // rlt_mem_sink_t: {a_{req,write,addr[6:0],wdata[DatAw-1:0],wmask[DatAw-1:0]}, b_{...}}
  input  wire logic [NUM_I3C-1:0] rlt_mem_src_i,
  output logic      [NUM_I3C-1:0] rlt_mem_sink_o
);

  assign awready_o                    = '0;
  assign wready_o                     = '0;
  assign bvalid_o                     = '0;
  assign bresp_o                      = '0;
  assign arready_o                    = '0;
  assign rvalid_o                     = '0;
  assign rdata_o                      = '0;
  assign rresp_o                      = '0;
  assign irq_o                        = '0;
  assign scl_o                        = '0;
  assign sda_o                        = '0;
  assign scl_oe_o                     = '0;
  assign sda_oe_o                     = '0;
  assign sel_od_pp_o                  = '0;
  assign recovery_payload_available_o = '0;
  assign recovery_image_activated_o   = '0;
  assign peripheral_reset_o           = '0;
  assign escalated_reset_o            = '0;
  assign dat_mem_sink_o               = '0;
  assign dct_mem_sink_o               = '0;
  assign rlt_mem_sink_o               = '0;

endmodule
