// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Example-only fabric boundary for an application-owned external NPU.
// The external NPU checkout must provide npu_pkg and npu_axi_csr_wrap.
// No NPU implementation source is copied into OCAH.

module ocah_npu_fabric_adapter
  import npu_pkg::*;
#(
  parameter int unsigned FabricAddrWidth = 56,
  parameter bit          PrefetchEn      = 1'b1
) (
  input  logic clk_i,
  input  logic rst_ni,

  // Trusted release from secure-management logic. Assert synchronously to
  // clk_i only after authentication and fabric containment are active.
  input  logic security_release_i,

  // Application CSR fabric: 32-bit AXI4-Lite subordinate.
  // The adopter decoder supplies a zero-based offset within the NPU aperture.
  input  logic        s_axil_awvalid_i,
  output logic        s_axil_awready_o,
  input  logic [31:0] s_axil_awaddr_i,
  input  logic        s_axil_wvalid_i,
  output logic        s_axil_wready_o,
  input  logic [31:0] s_axil_wdata_i,
  input  logic [3:0]  s_axil_wstrb_i,
  output logic        s_axil_bvalid_o,
  input  logic        s_axil_bready_i,
  output logic [1:0]  s_axil_bresp_o,
  input  logic        s_axil_arvalid_i,
  output logic        s_axil_arready_o,
  input  logic [31:0] s_axil_araddr_i,
  output logic        s_axil_rvalid_o,
  input  logic        s_axil_rready_i,
  output logic [31:0] s_axil_rdata_o,
  output logic [1:0]  s_axil_rresp_o,

  // Adopter memory fabric: AXI4 manager.
  output logic                         m_axi_awvalid_o,
  input  logic                         m_axi_awready_i,
  output logic [NPU_AXI_ID_W-1:0]      m_axi_awid_o,
  output logic [FabricAddrWidth-1:0]   m_axi_awaddr_o,
  output logic [7:0]                   m_axi_awlen_o,
  output logic [2:0]                   m_axi_awsize_o,
  output logic [1:0]                   m_axi_awburst_o,
  output logic [2:0]                   m_axi_awprot_o,
  output logic                         m_axi_wvalid_o,
  input  logic                         m_axi_wready_i,
  output logic [NPU_AXI_DATA_W-1:0]    m_axi_wdata_o,
  output logic [NPU_AXI_STRB_W-1:0]    m_axi_wstrb_o,
  output logic                         m_axi_wlast_o,
  input  logic                         m_axi_bvalid_i,
  output logic                         m_axi_bready_o,
  input  logic [NPU_AXI_ID_W-1:0]      m_axi_bid_i,
  input  logic [1:0]                   m_axi_bresp_i,
  output logic                         m_axi_arvalid_o,
  input  logic                         m_axi_arready_i,
  output logic [NPU_AXI_ID_W-1:0]      m_axi_arid_o,
  output logic [FabricAddrWidth-1:0]   m_axi_araddr_o,
  output logic [7:0]                   m_axi_arlen_o,
  output logic [2:0]                   m_axi_arsize_o,
  output logic [1:0]                   m_axi_arburst_o,
  output logic [2:0]                   m_axi_arprot_o,
  input  logic                         m_axi_rvalid_i,
  output logic                         m_axi_rready_o,
  input  logic [NPU_AXI_ID_W-1:0]      m_axi_rid_i,
  input  logic [NPU_AXI_DATA_W-1:0]    m_axi_rdata_i,
  input  logic [1:0]                   m_axi_rresp_i,
  input  logic                         m_axi_rlast_i,

  output logic intr_done_o,
  output logic intr_error_o
);

  logic [31:0] npu_dma_awaddr;
  logic [31:0] npu_dma_araddr;
  logic        npu_rst_ni;

  // Either input may assert reset asynchronously. Both rising inputs must be
  // synchronized to clk_i so npu_rst_ni deasserts synchronously. The rst_ni
  // source must also meet the implementation technology's minimum reset pulse
  // width; the NPU architecture does not prescribe a clock-cycle count.
  assign npu_rst_ni = rst_ni & security_release_i;

  // The NPU can issue only low-4-GiB physical addresses. These sized casts
  // zero-extend because the source signals are unsigned packed logic vectors.
  assign m_axi_awaddr_o = FabricAddrWidth'(npu_dma_awaddr);
  assign m_axi_araddr_o = FabricAddrWidth'(npu_dma_araddr);

  // npu_axi_csr_wrap has no AxPROT outputs. Classify every DMA request at this
  // trusted ingress as data, non-secure, and unprivileged. An adopter-specific
  // wrapper must also assign a non-spoofable stream/source ID for its fabric.
  assign m_axi_awprot_o = 3'b010;
  assign m_axi_arprot_o = 3'b010;

  initial begin
    assert (FabricAddrWidth >= 32)
      else $error("FabricAddrWidth must be at least 32");
  end

  npu_axi_csr_wrap #(
    .PrefetchEn (PrefetchEn)
  ) u_npu (
    .clk_i,
    .rst_ni (npu_rst_ni),

    .s_axil_awvalid_i,
    .s_axil_awready_o,
    .s_axil_awaddr_i,
    .s_axil_wvalid_i,
    .s_axil_wready_o,
    .s_axil_wdata_i,
    .s_axil_wstrb_i,
    .s_axil_bvalid_o,
    .s_axil_bready_i,
    .s_axil_bresp_o,
    .s_axil_arvalid_i,
    .s_axil_arready_o,
    .s_axil_araddr_i,
    .s_axil_rvalid_o,
    .s_axil_rready_i,
    .s_axil_rdata_o,
    .s_axil_rresp_o,

    .m_axi_awvalid_o,
    .m_axi_awready_i,
    .m_axi_awid_o,
    .m_axi_awaddr_o  (npu_dma_awaddr),
    .m_axi_awlen_o,
    .m_axi_awsize_o,
    .m_axi_awburst_o,
    .m_axi_wvalid_o,
    .m_axi_wready_i,
    .m_axi_wdata_o,
    .m_axi_wstrb_o,
    .m_axi_wlast_o,
    .m_axi_bvalid_i,
    .m_axi_bready_o,
    .m_axi_bid_i,
    .m_axi_bresp_i,
    .m_axi_arvalid_o,
    .m_axi_arready_i,
    .m_axi_arid_o,
    .m_axi_araddr_o  (npu_dma_araddr),
    .m_axi_arlen_o,
    .m_axi_arsize_o,
    .m_axi_arburst_o,
    .m_axi_rvalid_i,
    .m_axi_rready_o,
    .m_axi_rid_i,
    .m_axi_rdata_i,
    .m_axi_rresp_i,
    .m_axi_rlast_i,

    .intr_done_o,
    .intr_error_o
  );

endmodule : ocah_npu_fabric_adapter
