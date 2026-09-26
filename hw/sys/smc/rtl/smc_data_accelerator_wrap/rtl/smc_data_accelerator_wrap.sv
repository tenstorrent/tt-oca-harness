// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the SMC DMA and zeroer with address-based demux and mux.
//
// Adapts accelerator control and master data ports to the SMC fabric.
// Exposes status and clock-gater activity indicators alongside clock-gating control.
// The control demux decodes the DMA and zeroer windows from smc_top_addrmap_pkg and sends
// any other address to the DMA; the master mux prepends a source bit to the transfer IDs.

module smc_data_accelerator_wrap #(
  parameter bit [smc_pkg::SMC_LOCAL_ADDR_WIDTH-1:0] DMA_CTRL_REG_MAP_BASE_ADDR = 0,  // Unused; the control
                                                                                     // demux decodes the DMA
                                                                                     // window from
                                                                                     // smc_top_addrmap_pkg.
  parameter bit [smc_pkg::SMC_LOCAL_ADDR_WIDTH-1:0] DMA_CTRL_REG_MAP_SIZE = 0,  // Unused; the DMA window
                                                                                // size also comes from
                                                                                // smc_top_addrmap_pkg.
  parameter bit [smc_pkg::SMC_LOCAL_ADDR_WIDTH-1:0] ZEROER_CTRL_REG_MAP_BASE_ADDR = 0,  // Unused; the
                                                                                        // zeroer window base
                                                                                        // comes from
                                                                                        // smc_top_addrmap_pkg.
  parameter bit [smc_pkg::SMC_LOCAL_ADDR_WIDTH-1:0] ZEROER_CTRL_REG_MAP_SIZE = 0,  // Unused; the zeroer
                                                                                   // window size comes from
                                                                                   // smc_top_addrmap_pkg.
  parameter int unsigned DMA_BUFFER_DEPTH = 16  // DMA buffer depth in beats.
) (
  input  logic                                             clk_i,  // SMC core clock.
  input  logic                                             rst_ni,  // Primary reset, active-low, synchronized to
                                                                    // the SMC core clock.
  input  logic                                             test_en_i,  // Scan test mode enable, active-high;
                                                                       // forwarded to the DMA, the zeroer, and the
                                                                       // AXI demux and mux.

  input  logic                                             dma_cg_en_i,  // Enables idle clock gating of the
                                                                         // DMA front end when high; while low
                                                                         // its clock runs continuously.
  input  logic                                             zeroer_cg_en_i,  // Enables idle clock gating of the
                                                                            // zeroer datapath when high; while
                                                                            // low its clock runs continuously.
  input  logic [smc_pkg::CG_HYSTERESIS_W-1:0]              cg_hysteresis_i,  // Idle SMC core clock cycles the DMA and
                                                                             // zeroer clock gates wait after going idle
                                                                             // before stopping their clocks.

  input  smc_pkg::smc_local_32_64_8_12_axi_req_t           ctrl_axi_req_i,  // Control request from the
                                                                            // local crossbar for the DMA and
                                                                            // zeroer register windows.
  output smc_pkg::smc_local_32_64_8_12_axi_resp_t          ctrl_axi_resp_o,  // Control response to the
                                                                             // local crossbar.

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

  // Intermediate signals for demuxed control interfaces
  smc_pkg::smc_local_32_64_8_12_axi_req_t  [NumAccelerators-1:0] axi_ctrl_demux_req;
  smc_pkg::smc_local_32_64_8_12_axi_resp_t [NumAccelerators-1:0] axi_ctrl_demux_resp;

  // Intermediate signals for master data interfaces (with narrower ID width)
  smc_pkg::smc_cpu_mmio_axi_req_t  [NumAccelerators-1:0] axi_mst_mux_req;
  smc_pkg::smc_cpu_mmio_axi_resp_t [NumAccelerators-1:0] axi_mst_mux_resp;

  // Address decode logic for DMA/Zeroer selection
  smc_pkg::data_accelerator_type_t aw_select_dma_zeroer, ar_select_dma_zeroer;

  always_comb begin
    // Default to DMA (index 0)
    aw_select_dma_zeroer = smc_pkg::DMA;
    // Check if address matches ZEROER_CTRL region
    if (ctrl_axi_req_i.aw.addr >= smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR &&
        ctrl_axi_req_i.aw.addr < smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE) begin
      aw_select_dma_zeroer = smc_pkg::DMA;  // DMA
    end else if (ctrl_axi_req_i.aw.addr >= smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR &&
        ctrl_axi_req_i.aw.addr < smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_SIZE) begin
      aw_select_dma_zeroer = smc_pkg::ZEROER;  // Zeroer
    end
  end

  always_comb begin
    // Default to DMA (index 0)
    ar_select_dma_zeroer = smc_pkg::DMA;
    // Check if address matches ZEROER_CTRL region
    if (ctrl_axi_req_i.ar.addr >= smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR &&
        ctrl_axi_req_i.ar.addr < smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE) begin
      ar_select_dma_zeroer = smc_pkg::DMA;  // DMA
    end else if (ctrl_axi_req_i.ar.addr >= smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR &&
        ctrl_axi_req_i.ar.addr < smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR + smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_SIZE) begin
      ar_select_dma_zeroer = smc_pkg::ZEROER;  // Zeroer
    end
  end

  // Address demux for DMA/Zeroer control interfaces
  axi_demux #(
    .AxiIdWidth                         (smc_pkg::SMC_LOCAL_FABRIC_XBAR_MASTER_ID_WIDTH),
    .AtopSupport                        (1'b0),
    .aw_chan_t                          (smc_pkg::smc_local_32_64_8_12_axi_aw_chan_t),
    .w_chan_t                           (smc_pkg::smc_local_32_64_8_12_axi_w_chan_t),
    .b_chan_t                           (smc_pkg::smc_local_32_64_8_12_axi_b_chan_t),
    .ar_chan_t                          (smc_pkg::smc_local_32_64_8_12_axi_ar_chan_t),
    .r_chan_t                           (smc_pkg::smc_local_32_64_8_12_axi_r_chan_t),
    .axi_req_t                          (smc_pkg::smc_local_32_64_8_12_axi_req_t),
    .axi_resp_t                         (smc_pkg::smc_local_32_64_8_12_axi_resp_t),
    .NoMstPorts                         (NumAccelerators),
    .MaxTrans                           (smc_pkg::FABRIC_MAX_TRANS),
    .AxiLookBits                        (smc_pkg::FABRIC_ID_LOOKUP_BITS)
  ) u_axi_demux (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_i                             (test_en_i),
    .sel_hash_i                         (2'b00),
    .slv_req_i                          (ctrl_axi_req_i),
    .slv_aw_select_i                    (aw_select_dma_zeroer),
    .slv_ar_select_i                    (ar_select_dma_zeroer),
    .slv_resp_o                         (ctrl_axi_resp_o),
    .mst_reqs_o                         (axi_ctrl_demux_req),
    .mst_resps_i                        (axi_ctrl_demux_resp)
  );

  // Downsize the CTRL Address Width for DMA (32 -> 9)
  smc_pkg::smc_dma_ctrl_9_64_8_12_axi_req_t  dma_ctrl_axi_req;
  smc_pkg::smc_dma_ctrl_9_64_8_12_axi_resp_t dma_ctrl_axi_resp;

  `AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(dma_ctrl_axi_req, dma_ctrl_axi_resp,
                                     axi_ctrl_demux_req[smc_pkg::DMA],
                                     axi_ctrl_demux_resp[smc_pkg::DMA], smc_pkg::DMA_CTRL_ADDR_W)

  idma_wrapper #(
    .NUM_CTRL_INTERFACES                (1),
    .NUM_CTRL_STREAMS                   (1),
    .NUM_MST_INTERFACES                 (1),
    .DMA_MST_MAX_TXNS                   (smc_pkg::FABRIC_MAX_TRANS),
    // ctrl port is a master port of u_axi_demux above: MaxTrans per ID bucket, all buckets
    .CTRL_OUTSTANDING_TX                (smc_pkg::FABRIC_OUTSTANDING_TX),
    .F2M_FIFO_DEPTH                     (smc_pkg::F2M_FIFO_DEPTH),
    .M2B_FIFO_DEPTH                     (smc_pkg::M2B_FIFO_DEPTH),
    .BUFFER_DEPTH                       (DMA_BUFFER_DEPTH),
    .EN_R_AW_COUPLING                   (1'b1),
    .BYPASS_DMA_CTRL_FLOPS              (1'b0),
    .BYPASS_DMA_MST_FLOPS               (1'b0),
    .CG_HYSTERESIS_W                    (smc_pkg::CG_HYSTERESIS_W),
    .dma_ctrl_req_t                     (smc_pkg::smc_dma_ctrl_9_64_8_12_axi_req_t),
    .dma_ctrl_resp_t                    (smc_pkg::smc_dma_ctrl_9_64_8_12_axi_resp_t),
    .dma_mst_req_t                      (smc_pkg::smc_cpu_mmio_axi_req_t),
    .dma_mst_resp_t                     (smc_pkg::smc_cpu_mmio_axi_resp_t),
    .AXI_ADDR_WIDTH                     (smc_pkg::AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH                     (smc_pkg::AXI_DATA_WIDTH),
    .AXI_USER_WIDTH                     (smc_pkg::AXI_USER_WIDTH),
    .CTRL_ID_WIDTH                      (smc_pkg::SMC_LOCAL_FABRIC_XBAR_MASTER_ID_WIDTH),
    .MST_ID_WIDTH                       (smc_pkg::SMC_CPU_MMIO_AXI_ID_WIDTH),
    .BACKEND_INT_ID_WIDTH               (smc_pkg::DMA_BACKEND_MST_ID_W)
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

  // Downsize the CTRL Address Width for Zeroer (32 -> 5)
  smc_pkg::smc_zeroer_ctrl_5_64_8_12_axi_req_t  zeroer_ctrl_axi_req;
  smc_pkg::smc_zeroer_ctrl_5_64_8_12_axi_resp_t zeroer_ctrl_axi_resp;

  `AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(
      zeroer_ctrl_axi_req, zeroer_ctrl_axi_resp, axi_ctrl_demux_req[smc_pkg::ZEROER],
      axi_ctrl_demux_resp[smc_pkg::ZEROER], smc_pkg::ZEROER_CTRL_ADDR_W)

  zeroer #(
    .zeroer_ctrl_req_t                  (smc_pkg::smc_zeroer_ctrl_5_64_8_12_axi_req_t),
    .zeroer_ctrl_resp_t                 (smc_pkg::smc_zeroer_ctrl_5_64_8_12_axi_resp_t),
    .mst_req_t                          (smc_pkg::smc_cpu_mmio_axi_req_t),
    .mst_resp_t                         (smc_pkg::smc_cpu_mmio_axi_resp_t),
    .CTRL_ADDR_WIDTH                    (smc_pkg::ZEROER_CTRL_ADDR_W),
    .CTRL_DATA_WIDTH                    (smc_pkg::AXI_DATA_WIDTH),
    .CTRL_ID_WIDTH                      (smc_pkg::SMC_LOCAL_FABRIC_XBAR_MASTER_ID_WIDTH),
    .CTRL_USER_WIDTH                    (smc_pkg::AXI_USER_WIDTH),
    .AXI_ADDR_WIDTH                     (smc_pkg::AXI_ADDR_WIDTH),
    .AXI_DATA_WIDTH                     (smc_pkg::AXI_DATA_WIDTH),
    .AXI_USER_WIDTH                     (smc_pkg::AXI_USER_WIDTH),
    .MST_ID_WIDTH                       (smc_pkg::SMC_CPU_MMIO_AXI_ID_WIDTH),
    .CG_HYSTERESIS_W                    (smc_pkg::CG_HYSTERESIS_W)
  ) u_zeroer (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),
    .test_en_i                          (test_en_i),

    .cg_enable_i                        (zeroer_cg_en_i),
    .cg_hysteresis_i                    (cg_hysteresis_i),

    .zeroer_busy_o                      (zeroer_busy_o),
    .zeroer_intp_o                      (zeroer_intp_o),

    .zeroer_ctrl_axi_req_i              (zeroer_ctrl_axi_req),
    .zeroer_ctrl_axi_resp_o             (zeroer_ctrl_axi_resp),

    .mst_axi_req_o                      (axi_mst_mux_req[smc_pkg::ZEROER]),
    .mst_axi_resp_i                     (axi_mst_mux_resp[smc_pkg::ZEROER]),

    // Clock gater activity indicators
    .zeroer_clk_active_o                (zeroer_clk_active_o),
    .zeroer_bus_active_o                (zeroer_bus_active_o)
  );

  // AXI Mux to combine DMA and Zeroer master outputs
  // Uses narrower slave ID width to enable ID prepending for source identification
  axi_mux #(
    .SlvAxiIDWidth                      (smc_pkg::SMC_CPU_MMIO_AXI_ID_WIDTH),
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
    .MaxWTrans                          (smc_pkg::FABRIC_MAX_TRANS),
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
