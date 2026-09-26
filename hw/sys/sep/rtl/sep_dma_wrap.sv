// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Bridge AXI register and host ports onto the secure_dma TileLink UL core.
//
// Register path: 64-bit AXI is downsized to 32 bits, rebased by subtracting
// OCH_SEP_TOP_SECURE_DMA_BASE_ADDR, converted to AXI-Lite and then to TL-UL. Master path:
// TL-UL is converted to AXI-Lite, then to AXI with AxCACHE 0, upsized to 64 bits, and passed
// through a window remap that rewrites addresses in
// [sep_local_base_addr_i, sep_local_base_addr_i + 0x3000_0000) to 0x1000_0000 plus the offset.
// The CTN and system interfaces and the RACL policies are tied off.
//
// dma_alert_o aggregates the fatal alert pulse with integ_fail of all channels.
//
// dma_reg_bus_err_o and dma_host_intg_err_o stick until dma_err_clr_i; a fault arriving in
// the same cycle as the clear still latches. They are not cleared by a CPU-only reset
// (sep_cpu_reset_n is a subset of this block's rst_ni), so firmware must treat an
// assertion at boot as possibly stale.

module sep_dma_wrap #(
  parameter int unsigned REG_ADDR_WIDTH = 32,  // Width of SECURE_DMA_REG_MAP_BASE_ADDR only; unused
                                               // otherwise.
  parameter bit [REG_ADDR_WIDTH-1:0]                SECURE_DMA_REG_MAP_BASE_ADDR = 32'h20000000,  // Unused; the register path rebases with OCH_SEP_TOP_SECURE_DMA_BASE_ADDR instead.
  parameter logic [secure_dma_reg_pkg::NumAlerts-1:0] AlertAsyncOn = {secure_dma_reg_pkg::NumAlerts{1'b1}},  // Per-alert async-on configuration of the secure_dma senders; the local receivers are synchronous.
  parameter int unsigned                            AlertSkewCycles = 1,  // Alert skew cycle count.
  parameter bit                                     EnableDataIntgGen = 1'b1,  // Generate TL-UL integrity in secure_dma, command and data integrity on the register
                                                                               // bridge, and response and data integrity on the host bridge.
  parameter bit                                     EnableRspDataIntgCheck = 1'b1,  // Check response data integrity in secure_dma and command integrity of its host requests
                                                                                    // in the host bridge.
  parameter logic [tlul_pkg::RsvdWidth-1:0]         TlUserRsvd = '0,  // Reserved TL user bits.
  parameter top_racl_pkg::racl_role_t               SysRaclRole = '0,  // System RACL role.
  parameter int unsigned                            OtAgentId = 0,  // OpenTitan agent ID.
  parameter bit                                     EnableRacl = 1'b0,  // Enable RACL checks.
  parameter bit                                     RaclErrorRsp = EnableRacl,  // Return error responses on RACL fail.
  parameter top_racl_pkg::racl_policy_sel_t         RaclPolicySelVec[secure_dma_reg_pkg::NumRegs] = '{secure_dma_reg_pkg::NumRegs{0}}  // Per-register RACL policy select.
) (
  input  logic                                      clk_i,  // System clock.
  input  logic                                      rst_ni,  // Active-low reset.

  input  logic                                      test_en_i,  // DFT test-enable (scan-enable).

  input  secure_dma_pkg::lsio_trigger_t             lsio_trigger_i,  // Peripheral handshake signalling that data is ready for the DMA to transfer.
  output logic                                      intr_dma_done_o,  // Secure DMA transfer-done interrupt.
  output logic                                      intr_dma_chunk_done_o,  // Secure DMA chunk-done interrupt.
  output logic                                      intr_dma_error_o,  // Secure DMA error interrupt.

  output logic                                      dma_alert_o,  // OR of the alert pulses and
                                                                  // integrity failures of the local
                                                                  // receivers for every secure_dma
                                                                  // alert.

  output logic                                      dma_reg_bus_err_o,  // Register-path fault, set when the register bridge receives a TL-UL error response.
                                                                        // Held until dma_err_clr_i, and firmware must treat an assertion at boot as possibly
                                                                        // stale rather than a fresh fault.
  output logic                                      dma_host_intg_err_o,  // DMA-master-path fault from the TL-UL to AXI-Lite bridge: a non-OKAY AXI response
                                                                          // or a failed TL-UL command-integrity check.
  input  logic                                      dma_err_clr_i,  // Single-cycle clear for dma_reg_bus_err_o and dma_host_intg_err_o, pulsed by
                                                                    // DMA_BUS_ERR_CLEAR in sep.

  input  sep_pkg::sep_32_64_6_12_axi_req_t            reg_req_i,  // 64-bit AXI register request to
                                                                  // the secure_dma CSRs, with
                                                                  // absolute addresses.
  output sep_pkg::sep_32_64_6_12_axi_resp_t           reg_resp_o,  // 64-bit AXI register response
                                                                   // from the secure_dma CSRs.

  output sep_pkg::sep_32_64_3_12_axi_req_t            dma_req_o,  // 64-bit AXI DMA master request,
                                                                  // after the local alias remap.
  input  sep_pkg::sep_32_64_3_12_axi_resp_t           dma_resp_i,  // 64-bit AXI DMA master
                                                                   // response.
  input  logic [31:0]                                sep_local_base_addr_i  // Base of the SEP local alias window; DMA master addresses within 0x3000_0000 above it
                                                                            // are remapped to 0x1000_0000 plus the offset.
);

  // Local parameter for 32-bit data width
  localparam int unsigned DATA_WIDTH_32 = 32;

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // Register interface signals (AXI Slave)
  tlul_pkg::tl_h2d_t tl_d_i;
  tlul_pkg::tl_d2h_t tl_d_o;

  sep_pkg::sep_32_32_6_12_axi_req_t  axi32_slv_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t axi32_slv_resp;

  // AXI request with offset-adjusted address for register interface
  sep_pkg::sep_32_32_6_12_axi_req_t  axi32_slv_req_offset;

  // AXI-Lite intermediate signals for register path
  sep_pkg::sep_32_32_axil_req_t  axi_lite_slv_req;
  sep_pkg::sep_32_32_axil_resp_t axi_lite_slv_resp;

  // DMA SEP Master interface signals (AXI Master)
  tlul_pkg::tl_h2d_t host_tl_h_o;
  tlul_pkg::tl_d2h_t host_tl_h_i;

  sep_pkg::sep_32_32_3_12_axi_req_t  axi32_mst_req;
  sep_pkg::sep_32_32_3_12_axi_resp_t axi32_mst_resp;

  // AXI-Lite intermediate signals for DMA path
  sep_pkg::sep_32_32_axil_req_t  axi_lite_mst_req;
  sep_pkg::sep_32_32_axil_resp_t axi_lite_mst_resp;

  // DMA AXI signals before local alias remap
  sep_pkg::sep_32_64_3_12_axi_req_t  dma_axi_req_raw;
  sep_pkg::sep_32_64_3_12_axi_resp_t dma_axi_resp_raw;

  // CTN Interface (tied off)
  tlul_pkg::tl_d2h_t ctn_tl_d2h;

  // Local alert termination (no chiplet alert_handler today)
  prim_alert_pkg::alert_tx_t [secure_dma_reg_pkg::NumAlerts-1:0] dma_alert_tx;
  prim_alert_pkg::alert_rx_t [secure_dma_reg_pkg::NumAlerts-1:0] dma_alert_rx;
  logic [secure_dma_reg_pkg::NumAlerts-1:0]                      dma_alert_pulse;
  logic [secure_dma_reg_pkg::NumAlerts-1:0]                      dma_alert_integ_fail;

  //////////////
  // DMA Core //
  //////////////

  secure_dma #(
    .AlertAsyncOn           (AlertAsyncOn),
    .AlertSkewCycles        (AlertSkewCycles),
    .EnableDataIntgGen      (EnableDataIntgGen),
    .EnableRspDataIntgCheck (EnableRspDataIntgCheck),
    .TlUserRsvd             (TlUserRsvd),
    .SysRaclRole            (SysRaclRole),
    .OtAgentId              (OtAgentId),
    .EnableRacl             (EnableRacl),
    .RaclErrorRsp           (RaclErrorRsp),
    .RaclPolicySelVec       (RaclPolicySelVec)
  ) u_secure_dma (
    .clk_i                  (clk_i),
    .rst_ni                 (rst_ni),
    .scanmode_i             (prim_mubi_pkg::mubi4_bool_to_mubi(test_en_i)),

    .lsio_trigger_i         (lsio_trigger_i),
    .intr_dma_done_o        (intr_dma_done_o),
    .intr_dma_chunk_done_o  (intr_dma_chunk_done_o),
    .intr_dma_error_o       (intr_dma_error_o),

    .alert_rx_i             (dma_alert_rx),
    .alert_tx_o             (dma_alert_tx),

    .racl_policies_i        ('0),
    .racl_error_o           (/* UNUSED */),

    // Register Interface
    .tl_d_i                 (tl_d_i),
    .tl_d_o                 (tl_d_o),

    // DMA SEP Master Interface
    .host_tl_h_i            (host_tl_h_i),
    .host_tl_h_o            (host_tl_h_o),

    // CTN Interface
    .ctn_tl_d2h_i           (ctn_tl_d2h),
    .ctn_tl_h2d_o           (/* UNUSED */),

    // System Interface
    .sys_i                  ('0),
    .sys_o                  (/* UNUSED */)
  );

  ///////////////////////////////////////////////////
  // AXI to TL-UL Conversion (Register Interface) //
  ///////////////////////////////////////////////////

  axi_dw_downsizer #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (DATA_WIDTH_32),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t)
  ) u_axi_dw_downsizer_reg (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  (reg_req_i),
    .slv_resp_o (reg_resp_o),
    .mst_req_o  (axi32_slv_req),
    .mst_resp_i (axi32_slv_resp)
  );

  // Convert absolute address to offset by subtracting base address
  always_comb begin
    axi32_slv_req_offset         = axi32_slv_req;
    axi32_slv_req_offset.ar.addr = axi32_slv_req.ar.addr - och_sep_top_addrmap_pkg::OCH_SEP_TOP_SECURE_DMA_BASE_ADDR;
    axi32_slv_req_offset.aw.addr = axi32_slv_req.aw.addr - och_sep_top_addrmap_pkg::OCH_SEP_TOP_SECURE_DMA_BASE_ADDR;
  end

  // Convert AXI to AXI-Lite (after data width conversion)
  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (4),
    .AxiMaxReadTxns  (4),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_axi_to_axi_lite_reg (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (1'b0),
    .slv_req_i   (axi32_slv_req_offset),
    .slv_resp_o  (axi32_slv_resp),
    .mst_req_o   (axi_lite_slv_req),
    .mst_resp_i  (axi_lite_slv_resp)
  );

  // Convert AXI-Lite to TL-UL
  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH     (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AXI_DATA_WIDTH     (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AXI_ID_WIDTH       (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AXI_USER_WIDTH     (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .axi_lite_req_t     (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_rsp_t     (sep_pkg::sep_32_32_axil_resp_t),
    .EnableCmdIntgGen   (EnableDataIntgGen),      // Pass through wrapper parameter
    .EnableDataIntgGen  (EnableDataIntgGen)       // Pass through wrapper parameter
  ) u_axi_lite_to_tlul_reg (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  (axi_lite_slv_req),
    .axi_lite_rsp_o  (axi_lite_slv_resp),
    .tl_o            (tl_d_i),
    .tl_i            (tl_d_o),
    .err_o           (dma_reg_bus_err_o),
    .err_clr_i       (dma_err_clr_i)
  );

  //////////////////////////////////////////////////////
  // TL-UL to AXI Conversion (DMA SEP Master Port)   //
  //////////////////////////////////////////////////////

  // Convert TL-UL to AXI-Lite
  tlul_to_axi_lite #(
    .AXI_ADDR_WIDTH             (sep_pkg::SEP_32_32_3_12_ADDR_WIDTH),
    .AXI_DATA_WIDTH             (sep_pkg::SEP_32_32_3_12_DATA_WIDTH),
    .AXI_ID_WIDTH               (sep_pkg::SEP_32_32_3_12_ID_WIDTH),
    .AXI_USER_WIDTH             (sep_pkg::SEP_32_32_3_12_USER_WIDTH),
    .axi_lite_req_t             (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_rsp_t             (sep_pkg::sep_32_32_axil_resp_t),
    .EnableRspIntgGen           (EnableDataIntgGen),        // Generate response integrity
    .EnableDataIntgGen          (EnableDataIntgGen),        // Generate data integrity
    .CmdIntgCheck               (EnableRspDataIntgCheck)    // Check incoming command integrity
  ) u_tlul_to_axi_lite_dma (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .tl_i            (host_tl_h_o),
    .tl_o            (host_tl_h_i),
    .axi_lite_req_o  (axi_lite_mst_req),
    .axi_lite_rsp_i  (axi_lite_mst_resp),
    .err_o           (dma_host_intg_err_o),
    .err_clr_i       (dma_err_clr_i)
  );

  // Convert AXI-Lite to AXI (before data width conversion)
  axi_lite_to_axi #(
    .AxiDataWidth    (sep_pkg::SEP_32_32_3_12_DATA_WIDTH),
    .req_lite_t      (sep_pkg::sep_32_32_axil_req_t),
    .resp_lite_t     (sep_pkg::sep_32_32_axil_resp_t),
    .axi_req_t       (sep_pkg::sep_32_32_3_12_axi_req_t),
    .axi_resp_t      (sep_pkg::sep_32_32_3_12_axi_resp_t)
  ) u_axi_lite_to_axi_dma (
    .slv_req_lite_i  (axi_lite_mst_req),
    .slv_resp_lite_o (axi_lite_mst_resp),
    .slv_aw_cache_i  (4'b0000),  // Non-cacheable
    .slv_ar_cache_i  (4'b0000),  // Non-cacheable
    .mst_req_o       (axi32_mst_req),
    .mst_resp_i      (axi32_mst_resp)
  );

  axi_dw_upsizer #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (DATA_WIDTH_32),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_64_3_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_3_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_3_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_3_12_axi_aw_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_64_3_12_axi_w_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_32_3_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_3_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_3_12_axi_ar_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_64_3_12_axi_r_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_32_3_12_axi_r_chan_t),
    .axi_mst_req_t       (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .axi_slv_req_t       (sep_pkg::sep_32_32_3_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_32_3_12_axi_resp_t)
  ) u_axi_dw_upsizer_dma (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  (axi32_mst_req),
    .slv_resp_o (axi32_mst_resp),
    .mst_req_o  (dma_axi_req_raw),
    .mst_resp_i (dma_axi_resp_raw)
  );

  //////////////////////////////////////
  // Local Alias Address Remapper (DMA)
  //////////////////////////////////////

  // This remapper does not remap 0xC000_0000 to 0xCFFF_FFFF
  // -> this is because the DMA is allowed to access the ICCM and DCCM in the SEP CPU
  //    therefore change the local base start to be offset by the SRAM start address
  //    and the size to be SRAM start address smaller
  axi_window_remap #(
    .axi_req_t      (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_resp_t     (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .AXI_ADDR_WIDTH (32)
  ) u_dma_local_alias_remap (
    .slv_req_i          (dma_axi_req_raw),
    .slv_resp_o         (dma_axi_resp_raw),
    .mst_req_o          (dma_req_o),
    .mst_resp_i         (dma_resp_i),
    .local_alias_base_i (sep_local_base_addr_i),
    .region_size_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_SIZE[31:0]),
    .target_base_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_BASE[31:0])
  );

  ///////////////////
  // Port Tie-offs //
  ///////////////////

  assign ctn_tl_d2h.a_ready = 1'b1;
  assign ctn_tl_d2h.d_valid = 1'b0;
  assign ctn_tl_d2h.d_opcode = tlul_pkg::AccessAck;
  assign ctn_tl_d2h.d_param = '0;
  assign ctn_tl_d2h.d_size = '0;
  assign ctn_tl_d2h.d_source = '0;
  assign ctn_tl_d2h.d_sink = '0;
  assign ctn_tl_d2h.d_data = '0;
  assign ctn_tl_d2h.d_user = '0;
  assign ctn_tl_d2h.d_error = 1'b0;

  ////////////////////
  // Alert Receiver //
  ////////////////////

  for (genvar i = 0; i < secure_dma_reg_pkg::NumAlerts; i++) begin : gen_alert_receivers
    prim_alert_receiver #(
      .AsyncOn   (1'b0),
      .SkewCycles(1)
    ) u_alert_receiver (
      .clk_i,
      .rst_ni,
      .init_trig_i  (prim_mubi_pkg::MuBi4False),
      .ping_req_i   (1'b0),
      .ping_ok_o    (),
      .integ_fail_o (dma_alert_integ_fail[i]),
      .alert_o      (dma_alert_pulse[i]),
      .alert_rx_o   (dma_alert_rx[i]),
      .alert_tx_i   (dma_alert_tx[i])
    );
  end

  assign dma_alert_o = (|dma_alert_pulse) | (|dma_alert_integ_fail);

endmodule
