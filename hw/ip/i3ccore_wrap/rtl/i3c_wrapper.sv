// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

// Generated from i3c-core/src/i3c_wrapper.sv - DO NOT EDIT MANUALLY

module i3c_wrapper
  import I3CCSR_pkg::CONTROLLER_SUPPORT;
  import I3CCSR_pkg::TARGET_SUPPORT;
#(
    parameter int unsigned AxiLiteDataWidth = 32,
    parameter int unsigned AxiLiteAddrWidth = 32,
    parameter int unsigned DatAw = i3c_pkg::DatAw,
    parameter int unsigned DctAw = i3c_pkg::DctAw,

    parameter int unsigned CsrAddrWidth = I3CCSR_pkg::I3CCSR_MIN_ADDR_WIDTH,
    parameter int unsigned CsrDataWidth = I3CCSR_pkg::I3CCSR_DATA_WIDTH,

    // HCI FIFO depth parameters (active when CONTROLLER_SUPPORT=1)
    parameter int unsigned HciRespFifoDepth = I3CCSR_pkg::resp_fifo_size,
    parameter int unsigned HciCmdFifoDepth = I3CCSR_pkg::cmd_fifo_size,
    parameter int unsigned HciRxFifoDepth = I3CCSR_pkg::rx_fifo_size,
    parameter int unsigned HciTxFifoDepth = I3CCSR_pkg::tx_fifo_size,
    parameter int unsigned HciIbiFifoDepth = I3CCSR_pkg::ibi_fifo_size,
    // TTI FIFO depth parameters (active when TARGET_SUPPORT=1)
    parameter int unsigned TtiRxDescFifoDepth = I3CCSR_pkg::tti_rx_desc_fifo_size,
    parameter int unsigned TtiTxDescFifoDepth = I3CCSR_pkg::tti_tx_desc_fifo_size,
    parameter int unsigned TtiRxFifoDepth = I3CCSR_pkg::tti_rx_fifo_size,
    parameter int unsigned TtiTxFifoDepth = I3CCSR_pkg::tti_tx_fifo_size,
    parameter int unsigned TtiIbiFifoDepth = I3CCSR_pkg::tti_ibi_fifo_size,
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
    output i3c_pkg::dct_mem_sink_t dct_mem_sink_o
);

  i3c #(
      .AxiLiteDataWidth(AxiLiteDataWidth),
      .AxiLiteAddrWidth(AxiLiteAddrWidth),
      .CsrDataWidth(CsrDataWidth),
      .CsrAddrWidth(CsrAddrWidth),
      .DatAw(DatAw),
      .DctAw(DctAw)
      // HCI FIFO depth parameters
      ,.HciRespFifoDepth(HciRespFifoDepth)
      ,.HciCmdFifoDepth(HciCmdFifoDepth)
      ,.HciRxFifoDepth(HciRxFifoDepth)
      ,.HciTxFifoDepth(HciTxFifoDepth)
      ,.HciIbiFifoDepth(HciIbiFifoDepth)
      // TTI FIFO depth parameters
      ,.TtiRxDescFifoDepth(TtiRxDescFifoDepth)
      ,.TtiTxDescFifoDepth(TtiTxDescFifoDepth)
      ,.TtiRxFifoDepth(TtiRxFifoDepth)
      ,.TtiTxFifoDepth(TtiTxFifoDepth)
      ,.TtiIbiFifoDepth(TtiIbiFifoDepth)
  ) i3c (
      .clk_i,
      .rst_ni,

      // AXI4-Lite Write Address Channel
      .awvalid_i(awvalid_i),
      .awready_o(awready_o),
      .awaddr_i(awaddr_i),
      .awprot_i(awprot_i),

      // AXI4-Lite Write Data Channel
      .wvalid_i(wvalid_i),
      .wready_o(wready_o),
      .wdata_i(wdata_i),
      .wstrb_i(wstrb_i),

      // AXI4-Lite Write Response Channel
      .bvalid_o(bvalid_o),
      .bready_i(bready_i),
      .bresp_o(bresp_o),

      // AXI4-Lite Read Address Channel
      .arvalid_i(arvalid_i),
      .arready_o(arready_o),
      .araddr_i(araddr_i),
      .arprot_i(arprot_i),

      // AXI4-Lite Read Data Channel
      .rvalid_o(rvalid_o),
      .rready_i(rready_i),
      .rdata_o(rdata_o),
      .rresp_o(rresp_o),


      .i3c_scl_i  (scl_i),
      .i3c_scl_o  (scl_o),
      .i3c_sda_i  (sda_i),
      .i3c_sda_o  (sda_o),
      .sel_od_pp_o(sel_od_pp_o),
      .i3c_sda_oe_o(sda_oe),
      .i3c_scl_oe_o(scl_oe),

      .dat_mem_src_i (dat_mem_src_i),   // Pass through from wrapper ports
      .dat_mem_sink_o(dat_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

      .dct_mem_src_i (dct_mem_src_i),   // Pass through from wrapper ports
      .dct_mem_sink_o(dct_mem_sink_o),  // Pass through to wrapper ports (driven by i3c.sv)

      .recovery_payload_available_o(recovery_payload_available_o),
      .recovery_image_activated_o  (recovery_image_activated_o),

      .peripheral_reset_o,
      .peripheral_reset_done_i,
      .escalated_reset_o,
      .irq_o
  );

endmodule
