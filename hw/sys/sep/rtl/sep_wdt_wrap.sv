// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP WDT Wrapper - Watchdog Timer with AXI interface

module sep_wdt_wrap (
  // Global Interface
  input  logic                         clk_i,
  input  logic                         clk_wdt_i,
  input  logic                         rst_ni,

  input  logic                         test_en_i,
  input  logic                         scan_rst_ni,

  // AXI4 Slave Interface
  input  sep_pkg::sep_32_64_6_12_axi_req_t    sep_wdt_axi_req_i,
  output sep_pkg::sep_32_64_6_12_axi_resp_t   sep_wdt_axi_resp_o,

  // WDT Interface
  output logic                         intr_wdog_timer_bark_o,
  output logic                         wdt_timer_rst_req_o,
  // Aggregated fatal alert (alert pulse | integ_fail of all channels)
  output logic                         wdt_alert_o,
  input  logic                         wdt_debug_sleep_mode_i,

  // Register bridge fault (sticky, held until bus_err_clr_i)
  output logic                         bus_err_o,
  input  logic                         bus_err_clr_i
);

  localparam int unsigned NumAlerts = aon_timer_reg_pkg::NumAlerts;

  logic rst_wdt_n;

  prim_alert_pkg::alert_tx_t [NumAlerts-1:0] wdt_alert_tx;
  prim_alert_pkg::alert_rx_t [NumAlerts-1:0] wdt_alert_rx;
  logic [NumAlerts-1:0]                      wdt_alert_pulse;
  logic [NumAlerts-1:0]                      wdt_alert_integ_fail;

  prim_sync_reset u_rst_wdt_sync (
    .clk_i       (clk_wdt_i),
    .rst_ni      (rst_ni),
    .test_mode_i (test_en_i),
    .scan_rst_ni (scan_rst_ni),
    .sync_rst_no (rst_wdt_n)
  );

  sep_pkg::sep_32_32_6_12_axi_req_t  sep_wdt_tlul_axi_req;
  sep_pkg::sep_32_32_6_12_axi_resp_t sep_wdt_tlul_axi_resp;

  // AXI request with offset-adjusted address for register interface
  sep_pkg::sep_32_32_6_12_axi_req_t  sep_wdt_tlul_axi_req_offset;

  axi_dw_converter #(
    .AxiMaxReads         (16),
    .AxiSlvPortDataWidth (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .AxiMstPortDataWidth (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiAddrWidth        (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .AxiIdWidth          (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .aw_chan_t           (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .slv_w_chan_t        (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .mst_w_chan_t        (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
    .b_chan_t            (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t           (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .slv_r_chan_t        (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .mst_r_chan_t        (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
    .axi_slv_req_t       (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_slv_resp_t      (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .axi_mst_req_t       (sep_pkg::sep_32_32_6_12_axi_req_t),
    .axi_mst_resp_t      (sep_pkg::sep_32_32_6_12_axi_resp_t)
  ) u_wdt_axi_dw_converter (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),
    .slv_req_i           (sep_wdt_axi_req_i),
    .slv_resp_o          (sep_wdt_axi_resp_o),
    .mst_req_o           (sep_wdt_tlul_axi_req),
    .mst_resp_i          (sep_wdt_tlul_axi_resp)
  );

  // Convert absolute address to offset by subtracting base address
  always_comb begin
    sep_wdt_tlul_axi_req_offset         = sep_wdt_tlul_axi_req;
    sep_wdt_tlul_axi_req_offset.ar.addr = sep_wdt_tlul_axi_req.ar.addr - och_sep_top_addrmap_pkg::OCH_SEP_TOP_WDT_TIMER_BASE_ADDR;
    sep_wdt_tlul_axi_req_offset.aw.addr = sep_wdt_tlul_axi_req.aw.addr - och_sep_top_addrmap_pkg::OCH_SEP_TOP_WDT_TIMER_BASE_ADDR;
  end

  tlul_pkg::tl_h2d_t tl_d_i;
  tlul_pkg::tl_d2h_t tl_d_o;

  // AXI-Lite intermediate signals
  sep_pkg::sep_32_32_axil_req_t  axi_lite_req;
  sep_pkg::sep_32_32_axil_resp_t axi_lite_resp;

  // Stage 1: AXI to AXI-Lite conversion
  axi_to_axi_lite #(
    .AxiAddrWidth    (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AxiDataWidth    (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AxiIdWidth      (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AxiUserWidth    (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .AxiMaxWriteTxns (2),
    .AxiMaxReadTxns  (2),
    .full_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
    .full_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
    .lite_req_t      (sep_pkg::sep_32_32_axil_req_t),
    .lite_resp_t     (sep_pkg::sep_32_32_axil_resp_t)
  ) u_wdt_axi_to_axi_lite (
    .clk_i       (clk_i),
    .rst_ni      (rst_ni),
    .test_i      (test_en_i),
    .slv_req_i   (sep_wdt_tlul_axi_req_offset),
    .slv_resp_o  (sep_wdt_tlul_axi_resp),
    .mst_req_o   (axi_lite_req),
    .mst_resp_i  (axi_lite_resp)
  );

  // Stage 2: AXI-Lite to TL-UL conversion
  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH   (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
    .AXI_DATA_WIDTH   (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
    .AXI_ID_WIDTH     (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
    .AXI_USER_WIDTH   (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
    .axi_lite_req_t   (sep_pkg::sep_32_32_axil_req_t),
    .axi_lite_rsp_t   (sep_pkg::sep_32_32_axil_resp_t)
  ) u_wdt_axi_lite_to_tlul (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  (axi_lite_req),
    .axi_lite_rsp_o  (axi_lite_resp),
    .tl_o            (tl_d_i),
    .tl_i            (tl_d_o),
    .err_o           (bus_err_o),
    .err_clr_i       (bus_err_clr_i)
  );

  aon_timer #(
    .AlertAsyncOn     (1'b0),
    .AlertSkewCycles  (1),
    .EnableRacl       (1'b0),
    .RaclErrorRsp     (1'b0),
    .RaclPolicySelVec ('{aon_timer_reg_pkg::NumRegs{0}})
  ) u_wdt_aon_timer (
    .clk_i                     (clk_i),
    .rst_ni                    (rst_ni),
    .clk_aon_i                 (clk_wdt_i),
    .rst_aon_ni                (rst_wdt_n),
    .tl_i                      (tl_d_i),
    .tl_o                      (tl_d_o),

    .alert_rx_i                (wdt_alert_rx),
    .alert_tx_o                (wdt_alert_tx),
    .racl_policies_i           ('0),
    .racl_error_o              (/* UNUSED */),

    .lc_escalate_en_i          (lc_ctrl_pkg::Off),
    .intr_wkup_timer_expired_o (/* UNUSED */),
    .intr_wdog_timer_bark_o    (intr_wdog_timer_bark_o),
    .nmi_wdog_timer_bark_o     (/* UNUSED */),

    .wkup_req_o                (/* UNUSED */),
    .aon_timer_rst_req_o       (wdt_timer_rst_req_o),

    .sleep_mode_i              (wdt_debug_sleep_mode_i)
  );

  for (genvar i = 0; i < NumAlerts; i++) begin : gen_alert_receivers
    prim_alert_receiver #(
      .AsyncOn   (1'b0),
      .SkewCycles(1)
    ) u_alert_receiver (
      .clk_i,
      .rst_ni,
      .init_trig_i  (prim_mubi_pkg::MuBi4False),
      .ping_req_i   (1'b0),
      .ping_ok_o    (),
      .integ_fail_o (wdt_alert_integ_fail[i]),
      .alert_o      (wdt_alert_pulse[i]),
      .alert_rx_o   (wdt_alert_rx[i]),
      .alert_tx_i   (wdt_alert_tx[i])
    );
  end

  assign wdt_alert_o = (|wdt_alert_pulse) | (|wdt_alert_integ_fail);

endmodule
