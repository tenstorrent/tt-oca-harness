// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the SMC DMA and zeroer and merge their master ports into one fabric port.
//
// Exposes status and clock-gater activity indicators alongside clock-gating control.
// The DMA control port receives the page that holds the DMA's registers. A burst goes to the
// DMA only when every beat falls in the DMA's register map, the SMC_TOP_DMA_CTRL_SIZE bytes at
// the start of the page; every other burst receives SLVERR with read data 0xBADCAB1E on every
// beat. The zeroer control port is AXI-Lite and carries the zeroer's
// own page. The master mux prepends a source bit to the transfer IDs.

`include "ocah_assert.svh"

module smc_data_accelerator_wrap #(
  parameter int unsigned DMA_BUFFER_DEPTH = 16  // DMA buffer depth in beats.
) (
  input  logic                                             clk_i,  // SMC core clock.
  input  logic                                             rst_ni,  // Primary reset, active-low, synchronized to
                                                                    // the SMC core clock.
  input  logic                                             test_en_i,  // Scan test mode enable, active-high;
                                                                       // forwarded to the DMA, the zeroer, the
                                                                       // AXI demux and mux, and the DMA control
                                                                       // error subordinate.

  input  logic                                             dma_cg_en_i,  // Enables idle clock gating of the
                                                                         // DMA front end when high; while low
                                                                         // its clock runs continuously.
  input  logic                                             zeroer_cg_en_i,  // Enables idle clock gating of the
                                                                            // zeroer datapath when high; while
                                                                            // low its clock runs continuously.
  input  logic [smc_pkg::CgHysteresisW-1:0]              cg_hysteresis_i,    // Idle SMC core clock cycles the DMA and
                                                                             // zeroer clock gates wait after going idle
                                                                             // before stopping their clocks.

  input  smc_pkg::smc_local_32_64_8_12_axi_req_t           dma_ctrl_axi_req_i,  // DMA control request from
                                                                                // the local crossbar for the
                                                                                // page that holds the DMA
                                                                                // registers.
  output smc_pkg::smc_local_32_64_8_12_axi_resp_t          dma_ctrl_axi_resp_o,  // DMA control response to
                                                                                 // the local crossbar.
  input  smc_pkg::smc_axil_32_64_req_t                     zeroer_ctrl_axil_req_i,  // Zeroer control request
                                                                                    // from the internal CSR
                                                                                    // crossbar for the
                                                                                    // zeroer's page.
  output smc_pkg::smc_axil_32_64_resp_t                    zeroer_ctrl_axil_resp_o,  // Zeroer control
                                                                                     // response to the
                                                                                     // internal CSR crossbar.

  output smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t    mst_axi_req_o,  // Transfer request from the
                                                                           // DMA or zeroer into the input
                                                                           // fabric.
  input  smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t   mst_axi_resp_i,  // Transfer response from the
                                                                            // input fabric.

  output logic                                             dma_busy_o,  // High while the DMA front end or back end
                                                                        // has a transfer in flight.
  output logic                                             dma_intp_o,  // DMA completion interrupt, a one-cycle
                                                                        // pulse when dma_busy_o falls.
  output logic                                             zeroer_busy_o,  // High while the zeroer has work in flight.
  output logic                                             zeroer_intp_o,  // Zeroer completion interrupt, a one-cycle
                                                                           // pulse when zeroer_busy_o falls while its
                                                                           // interrupt is enabled; held low when the
                                                                           // zeroer enters its error state.

  output logic                                             dma_frontend_clk_active_o,  // High while the DMA
                                                                                       // front-end gated clock
                                                                                       // is running.
  output logic                                             dma_frontend_bus_active_o,  // High while the DMA
                                                                                       // control port has an
                                                                                       // AXI transaction
                                                                                       // outstanding.
  output logic                                             zeroer_clk_active_o,  // High while the zeroer
                                                                                 // datapath gated clock is
                                                                                 // running.
  output logic                                             zeroer_bus_active_o  // High while the zeroer
                                                                                // control bus has traffic.
);

  localparam int unsigned NumAccelerators = 2;
  localparam int unsigned NumDmaCtrlPorts = 2;
  localparam int unsigned DmaCtrlDmaPort = 0;
  localparam int unsigned DmaCtrlErrPort = 1;

  `OCAH_ASSERT_STATIC(DmaCtrlBaseAligned_A,
                      smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR % smc_pkg::RegPageSize == 0)
  `OCAH_ASSERT_STATIC(DmaCtrlMapFitsWindow_A,
                      smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE <= (1 << smc_pkg::DmaCtrlAddrW))
  `OCAH_ASSERT_STATIC(DmaCtrlMapEndsOnBusWord_A,
                      smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE % smc_pkg::AxiStrbWidth == 0)

  // Intermediate signals for demuxed DMA control interfaces
  smc_pkg::smc_local_32_64_8_12_axi_req_t  [NumDmaCtrlPorts-1:0] dma_ctrl_demux_req;
  smc_pkg::smc_local_32_64_8_12_axi_resp_t [NumDmaCtrlPorts-1:0] dma_ctrl_demux_resp;

  // Intermediate signals for master data interfaces (with narrower ID width)
  smc_pkg::smc_cpu_mmio_axi_req_t  [NumAccelerators-1:0] axi_mst_mux_req;
  smc_pkg::smc_cpu_mmio_axi_resp_t [NumAccelerators-1:0] axi_mst_mux_resp;

  typedef logic [$clog2(NumDmaCtrlPorts)-1:0] dma_ctrl_select_t;

  localparam smc_pkg::smc_axi_local_addr_t DmaMapLast = smc_pkg::smc_axi_local_addr_t'(
      smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE - 1);

  smc_pkg::smc_axi_local_addr_t aw_last_addr, ar_last_addr;
  dma_ctrl_select_t aw_select_dma, ar_select_dma;

  // The port carries only the DMA's page and the register map starts that page, so no beat lies
  // below it. A FIXED burst repeats its first address, a WRAP burst fills the aligned block of
  // (len + 1) << size bytes around it, and an INCR burst ends at its last beat. The map ends on a
  // bus word, so a beat that starts inside it also ends inside it.
  assign aw_last_addr =
      (dma_ctrl_axi_req_i.aw.burst == axi_pkg::BURST_FIXED) ? dma_ctrl_axi_req_i.aw.addr :
      (dma_ctrl_axi_req_i.aw.burst == axi_pkg::BURST_WRAP) ? (dma_ctrl_axi_req_i.aw.addr |
      (((smc_pkg::smc_axi_local_addr_t'(dma_ctrl_axi_req_i.aw.len) + 1) << dma_ctrl_axi_req_i.aw.size) - 1)) :
      ((dma_ctrl_axi_req_i.aw.addr >> dma_ctrl_axi_req_i.aw.size) << dma_ctrl_axi_req_i.aw.size) +
      (smc_pkg::smc_axi_local_addr_t'(dma_ctrl_axi_req_i.aw.len) << dma_ctrl_axi_req_i.aw.size);
  assign ar_last_addr =
      (dma_ctrl_axi_req_i.ar.burst == axi_pkg::BURST_FIXED) ? dma_ctrl_axi_req_i.ar.addr :
      (dma_ctrl_axi_req_i.ar.burst == axi_pkg::BURST_WRAP) ? (dma_ctrl_axi_req_i.ar.addr |
      (((smc_pkg::smc_axi_local_addr_t'(dma_ctrl_axi_req_i.ar.len) + 1) << dma_ctrl_axi_req_i.ar.size) - 1)) :
      ((dma_ctrl_axi_req_i.ar.addr >> dma_ctrl_axi_req_i.ar.size) << dma_ctrl_axi_req_i.ar.size) +
      (smc_pkg::smc_axi_local_addr_t'(dma_ctrl_axi_req_i.ar.len) << dma_ctrl_axi_req_i.ar.size);

  assign aw_select_dma = dma_ctrl_select_t'(
      (aw_last_addr > DmaMapLast) ? DmaCtrlErrPort : DmaCtrlDmaPort);
  assign ar_select_dma = dma_ctrl_select_t'(
      (ar_last_addr > DmaMapLast) ? DmaCtrlErrPort : DmaCtrlDmaPort);

  axi_demux #(
    .AxiIdWidth                         (smc_pkg::SmcLocalFabricXbarMasterIdWidth),
    .AtopSupport                        (1'b0),
    .aw_chan_t                          (smc_pkg::smc_local_32_64_8_12_axi_aw_chan_t),
    .w_chan_t                           (smc_pkg::smc_local_32_64_8_12_axi_w_chan_t),
    .b_chan_t                           (smc_pkg::smc_local_32_64_8_12_axi_b_chan_t),
    .ar_chan_t                          (smc_pkg::smc_local_32_64_8_12_axi_ar_chan_t),
    .r_chan_t                           (smc_pkg::smc_local_32_64_8_12_axi_r_chan_t),
    .axi_req_t                          (smc_pkg::smc_local_32_64_8_12_axi_req_t),
    .axi_resp_t                         (smc_pkg::smc_local_32_64_8_12_axi_resp_t),
    .NoMstPorts                         (NumDmaCtrlPorts),
    .MaxTrans                           (smc_pkg::FabricMaxTrans),
    .AxiLookBits                        (smc_pkg::FabricIdLookupBits)
  ) u_dma_ctrl_demux (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_i                             (test_en_i),
    .sel_hash_i                         (2'b00),
    .slv_req_i                          (dma_ctrl_axi_req_i),
    .slv_aw_select_i                    (aw_select_dma),
    .slv_ar_select_i                    (ar_select_dma),
    .slv_resp_o                         (dma_ctrl_axi_resp_o),
    .mst_reqs_o                         (dma_ctrl_demux_req),
    .mst_resps_i                        (dma_ctrl_demux_resp)
  );

  axi_err_slv #(
    .AxiIdWidth (smc_pkg::SmcLocalFabricXbarMasterIdWidth),
    .axi_req_t  (smc_pkg::smc_local_32_64_8_12_axi_req_t),
    .axi_resp_t (smc_pkg::smc_local_32_64_8_12_axi_resp_t),
    .Resp       (axi_pkg::RESP_SLVERR),
    .ATOPs      (1'b0),
    .MaxTrans   (smc_pkg::ErrSlvMaxTrans)
  ) u_dma_ctrl_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (dma_ctrl_demux_req[DmaCtrlErrPort]),
    .slv_resp_o (dma_ctrl_demux_resp[DmaCtrlErrPort])
  );

  // Downsize the CTRL Address Width for DMA (32 -> 9)
  smc_pkg::smc_dma_ctrl_9_64_8_12_axi_req_t  dma_ctrl_axi_req;
  smc_pkg::smc_dma_ctrl_9_64_8_12_axi_resp_t dma_ctrl_axi_resp;

  `AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(dma_ctrl_axi_req, dma_ctrl_axi_resp,
                                     dma_ctrl_demux_req[DmaCtrlDmaPort],
                                     dma_ctrl_demux_resp[DmaCtrlDmaPort], smc_pkg::DmaCtrlAddrW)

  idma_wrapper #(
    .NUM_CTRL_INTERFACES                (1),
    .NUM_CTRL_STREAMS                   (1),
    .NUM_MST_INTERFACES                 (1),
    .DMA_MST_MAX_TXNS                   (smc_pkg::FabricMaxTrans),
    // ctrl port is a master port of u_dma_ctrl_demux above: MaxTrans per ID bucket, all buckets
    .CTRL_OUTSTANDING_TX                (smc_pkg::FabricOutstandingTx),
    .F2M_FIFO_DEPTH                     (smc_pkg::F2mFifoDepth),
    .M2B_FIFO_DEPTH                     (smc_pkg::M2bFifoDepth),
    .BUFFER_DEPTH                       (DMA_BUFFER_DEPTH),
    .EN_R_AW_COUPLING                   (1'b1),
    .BYPASS_DMA_CTRL_FLOPS              (1'b0),
    .BYPASS_DMA_MST_FLOPS               (1'b0),
    .CG_HYSTERESIS_W                    (smc_pkg::CgHysteresisW),
    .dma_ctrl_req_t                     (smc_pkg::smc_dma_ctrl_9_64_8_12_axi_req_t),
    .dma_ctrl_resp_t                    (smc_pkg::smc_dma_ctrl_9_64_8_12_axi_resp_t),
    .dma_mst_req_t                      (smc_pkg::smc_cpu_mmio_axi_req_t),
    .dma_mst_resp_t                     (smc_pkg::smc_cpu_mmio_axi_resp_t),
    .AXI_ADDR_WIDTH                     (smc_pkg::AxiAddrWidth),
    .AXI_DATA_WIDTH                     (smc_pkg::AxiDataWidth),
    .AXI_USER_WIDTH                     (smc_pkg::AxiUserWidth),
    .CTRL_ID_WIDTH                      (smc_pkg::SmcLocalFabricXbarMasterIdWidth),
    .MST_ID_WIDTH                       (smc_pkg::SmcCpuMmioAxiIdWidth),
    .BACKEND_INT_ID_WIDTH               (smc_pkg::DmaBackendMstIdW)
  ) u_dma_wrap (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),

    .test_en_i                          (test_en_i),

    .dma_busy_o                         (dma_busy_o),
    .dma_intp_o                         (dma_intp_o),

    .cg_enable_i                        (dma_cg_en_i),
    .cg_hysteresis_i                    (cg_hysteresis_i),

    .dma_ctrl_axi_req_i                 (dma_ctrl_axi_req),
    .dma_ctrl_axi_resp_o                (dma_ctrl_axi_resp),

    .dma_mst_axi_req_o                  (axi_mst_mux_req[smc_pkg::DMA]),
    .dma_mst_axi_resp_i                 (axi_mst_mux_resp[smc_pkg::DMA]),

    // Clock gater activity indicators
    .frontend_clk_active_o              (dma_frontend_clk_active_o),
    .frontend_bus_active_o              (dma_frontend_bus_active_o)
  );

  zeroer #(
    .zeroer_ctrl_req_t                  (smc_pkg::smc_axil_32_64_req_t),
    .zeroer_ctrl_resp_t                 (smc_pkg::smc_axil_32_64_resp_t),
    .CTRL_OUTSTANDING_TX                (smc_internal_axi_lite_xbar_pkg::XbarCfg.MaxSlvTrans),
    .mst_req_t                          (smc_pkg::smc_cpu_mmio_axi_req_t),
    .mst_resp_t                         (smc_pkg::smc_cpu_mmio_axi_resp_t),
    .AXI_ADDR_WIDTH                     (smc_pkg::AxiAddrWidth),
    .AXI_DATA_WIDTH                     (smc_pkg::AxiDataWidth),
    .AXI_USER_WIDTH                     (smc_pkg::AxiUserWidth),
    .MST_ID_WIDTH                       (smc_pkg::SmcCpuMmioAxiIdWidth),
    .CG_HYSTERESIS_W                    (smc_pkg::CgHysteresisW)
  ) u_zeroer (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_en_i                          (test_en_i),

    .cg_enable_i                        (zeroer_cg_en_i),
    .cg_hysteresis_i                    (cg_hysteresis_i),

    .zeroer_busy_o                      (zeroer_busy_o),
    .zeroer_intp_o                      (zeroer_intp_o),

    .zeroer_ctrl_axil_req_i             (zeroer_ctrl_axil_req_i),
    .zeroer_ctrl_axil_resp_o            (zeroer_ctrl_axil_resp_o),

    .mst_axi_req_o                      (axi_mst_mux_req[smc_pkg::ZEROER]),
    .mst_axi_resp_i                     (axi_mst_mux_resp[smc_pkg::ZEROER]),

    // Clock gater activity indicators
    .zeroer_clk_active_o                (zeroer_clk_active_o),
    .zeroer_bus_active_o                (zeroer_bus_active_o)
  );

  // AXI Mux to combine DMA and Zeroer master outputs
  // Uses narrower slave ID width to enable ID prepending for source identification
  axi_mux #(
    .SlvAxiIDWidth                      (smc_pkg::SmcCpuMmioAxiIdWidth),
    .slv_aw_chan_t                      (smc_pkg::smc_cpu_mmio_axi_aw_chan_t),
    .mst_aw_chan_t                      (smc_pkg::smc_input_fabric_56_64_4_12_axi_aw_chan_t),
    .w_chan_t                           (smc_pkg::smc_cpu_mmio_axi_w_chan_t),
    .slv_b_chan_t                       (smc_pkg::smc_cpu_mmio_axi_b_chan_t),
    .mst_b_chan_t                       (smc_pkg::smc_input_fabric_56_64_4_12_axi_b_chan_t),
    .slv_ar_chan_t                      (smc_pkg::smc_cpu_mmio_axi_ar_chan_t),
    .mst_ar_chan_t                      (smc_pkg::smc_input_fabric_56_64_4_12_axi_ar_chan_t),
    .slv_r_chan_t                       (smc_pkg::smc_cpu_mmio_axi_r_chan_t),
    .mst_r_chan_t                       (smc_pkg::smc_input_fabric_56_64_4_12_axi_r_chan_t),
    .slv_req_t                          (smc_pkg::smc_cpu_mmio_axi_req_t),
    .slv_resp_t                         (smc_pkg::smc_cpu_mmio_axi_resp_t),
    .mst_req_t                          (smc_pkg::smc_input_fabric_56_64_4_12_axi_req_t),
    .mst_resp_t                         (smc_pkg::smc_input_fabric_56_64_4_12_axi_resp_t),
    .NoSlvPorts                         (NumAccelerators),
    .MaxWTrans                          (smc_pkg::FabricMaxTrans),
    .FallThrough                        (1'b0),
    .SpillAw                            (1'b1),
    .SpillW                             (1'b0),
    .SpillB                             (1'b1),
    .SpillAr                            (1'b1),
    .SpillR                             (1'b0)
  ) u_axi_mux (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_i                             (test_en_i),
    .slv_reqs_i                         (axi_mst_mux_req),
    .slv_resps_o                        (axi_mst_mux_resp),
    .mst_req_o                          (mst_axi_req_o),
    .mst_resp_i                         (mst_axi_resp_i)
  );

endmodule
