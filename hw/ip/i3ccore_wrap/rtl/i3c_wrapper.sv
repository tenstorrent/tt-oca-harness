// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Adapted from i3c-core/src/i3c_wrapper.sv — maintained in-tree (full-AXI4 core, open-drain SCL)

module i3c_wrapper #(
  parameter int unsigned AxiLiteDataWidth = 32,
  parameter int unsigned AxiLiteAddrWidth = 32,
  parameter int unsigned DatAw = i3c_pkg::DatAw,
  parameter int unsigned DctAw = i3c_pkg::DctAw,

  parameter int unsigned CsrAddrWidth = I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH,
  parameter int unsigned CsrDataWidth = I3CCSR_pkg::I3CCSR_DATA_WIDTH,

  // Dummy parameter for trailing comma handling
  parameter int unsigned DummyParam = 0
) (
  input clk_i,  // clock
  input rst_ni, // active low reset

  // AXI4-Lite Interface
  // Write Address Channel
  input  logic                           awvalid_i,
  output logic                           awready_o,
  input  logic [AxiLiteAddrWidth-1:0]    awaddr_i,
  input  logic [2:0]                     awprot_i,

  // Write Data Channel
  input  logic                           wvalid_i,
  output logic                           wready_o,
  input  logic [AxiLiteDataWidth-1:0]    wdata_i,
  input  logic [AxiLiteDataWidth/8-1:0]  wstrb_i,

  // Write Response Channel
  output logic                           bvalid_o,
  input  logic                           bready_i,
  output logic [1:0]                     bresp_o,

  // Read Address Channel
  input  logic                           arvalid_i,
  output logic                           arready_o,
  input  logic [AxiLiteAddrWidth-1:0]    araddr_i,
  input  logic [2:0]                     arprot_i,

  // Read Data Channel
  output logic                           rvalid_o,
  input  logic                           rready_i,
  output logic [AxiLiteDataWidth-1:0]    rdata_o,
  output logic [1:0]                     rresp_o,


  // I3C bus driver signals
  input  logic scl_i,
  input  logic sda_i,
  output logic scl_o,
  output logic sda_o,
  output logic scl_oe,
  output logic sda_oe,

  output logic sel_od_pp_o,

  // Recovery interface signals
  output logic recovery_payload_available_o,
  output logic recovery_image_activated_o,

  output logic peripheral_reset_o,
  input  logic peripheral_reset_done_i,
  output logic escalated_reset_o,

  output irq_o,

  // DAT memory export interface (active when CONTROLLER_SUPPORT=1)
  input  i3c_pkg::dat_mem_src_t  dat_mem_src_i,
  output i3c_pkg::dat_mem_sink_t dat_mem_sink_o,

  // DCT memory export interface (active when CONTROLLER_SUPPORT=1)
  input  i3c_pkg::dct_mem_src_t  dct_mem_src_i,
  output i3c_pkg::dct_mem_sink_t dct_mem_sink_o,

  // RLT (reverse-lookup table) memory export interface (active when CONTROLLER_SUPPORT=1)
  input  i3c_pkg::rlt_mem_src_t  rlt_mem_src_i,
  output i3c_pkg::rlt_mem_sink_t rlt_mem_sink_o
);

  logic core_scl_o;   // core SCL output is the bus level (1=release), not a pad OE
  logic core_sda_oe;  // core drives this only in target mode (tied 0 for active controller)

  i3c #(
    .AxiDataWidth(AxiLiteDataWidth),
    .AxiAddrWidth(AxiLiteAddrWidth),
    .AxiUserWidth(32),
    .AxiIdWidth(1),

    .CsrDataWidth(CsrDataWidth),
    .CsrAddrWidth(CsrAddrWidth),
    .DatAw(DatAw),
    .DctAw(DctAw)
  ) u_i3c (
    .clk_i,
    .rst_ni,

    // AXI4 Write Address Channel (AXI-Lite -> AXI4, single beat)
    .awaddr_i (AxiLiteAddrWidth'(awaddr_i)),
    .awburst_i(2'b01),                       // INCR; irrelevant for awlen==0
    .awsize_i (3'($clog2(AxiLiteDataWidth/8))),
    .awlen_i  (8'd0),
    .awuser_i ({32{1'b0}}),
    .awid_i   ({1{1'b0}}),
    .awlock_i (1'b0),
    .awvalid_i(awvalid_i),
    .awready_o(awready_o),

    // AXI4 Write Data Channel
    .wdata_i (wdata_i),
    .wstrb_i (wstrb_i),
    .wuser_i ({32{1'b0}}),
    .wlast_i (1'b1),
    .wvalid_i(wvalid_i),
    .wready_o(wready_o),

    // AXI4 Write Response Channel
    .bresp_o (bresp_o),
    .bid_o   (),
    .buser_o (),
    .bvalid_o(bvalid_o),
    .bready_i(bready_i),

    // AXI4 Read Address Channel
    .araddr_i (AxiLiteAddrWidth'(araddr_i)),
    .arburst_i(2'b01),
    .arsize_i (3'($clog2(AxiLiteDataWidth/8))),
    .arlen_i  (8'd0),
    .aruser_i ({32{1'b0}}),
    .arid_i   ({1{1'b0}}),
    .arlock_i (1'b0),
    .arvalid_i(arvalid_i),
    .arready_o(arready_o),

    // AXI4 Read Data Channel
    .rdata_o (rdata_o),
    .rresp_o (rresp_o),
    .rid_o   (),
    .ruser_o (),
    .rlast_o (),
    .rvalid_o(rvalid_o),
    .rready_i(rready_i),


    .i3c_scl_i  (scl_i),
    .i3c_scl_o  (core_scl_o),
    .i3c_sda_i  (sda_i),
    .i3c_sda_o  (sda_o),
    .sel_od_pp_o(sel_od_pp_o),
    .i3c_sda_oe_o(core_sda_oe),

    .dat_mem_src_i (dat_mem_src_i),   // Pass through from wrapper ports
    .dat_mem_sink_o(dat_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

    .dct_mem_src_i (dct_mem_src_i),   // Pass through from wrapper ports
    .dct_mem_sink_o(dct_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

    .rlt_mem_src_i (rlt_mem_src_i),   // Pass through from wrapper ports
    .rlt_mem_sink_o(rlt_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

    .recovery_payload_available_o(recovery_payload_available_o),
    .recovery_image_activated_o  (recovery_image_activated_o),

    .peripheral_reset_o(peripheral_reset_o),
    .peripheral_reset_done_i(peripheral_reset_done_i),
    .escalated_reset_o(escalated_reset_o),
    .irq_o(irq_o)
  );

  // Open-drain pad OE derived here (core gives bus levels, not OE, in controller mode):
  // drive low only; push-pull (sel_od_pp_o) drives both.
  assign scl_o  = 1'b0;
  assign scl_oe = ~core_scl_o;
  assign sda_oe = sel_od_pp_o | ~sda_o;

endmodule
