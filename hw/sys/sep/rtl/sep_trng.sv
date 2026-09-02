// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP integration wrapper for the internal entropy complex.
//
// This groups the coordinated three-port AXI reset boundary, CSR conversion,
// entropy source, and DRBG. Source selection and consumer adapters remain in
// sep_crypto because they also serve the external TRNG path.

module sep_trng #(
    parameter int unsigned NUM_AXIS = sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT
) (
    input logic clk_i,
    input logic rst_ni,
    input logic test_en_i,
    input logic trng_sw_rst_req_ni,
    input logic entropy_rosc_sample_clk_i,

    input  sep_pkg::sep_32_64_6_12_axi_req_t  esrc_axi_req_i,
    output sep_pkg::sep_32_64_6_12_axi_resp_t esrc_axi_resp_o,
    input  sep_pkg::sep_32_64_6_12_axi_req_t  csrng_axi_req_i,
    output sep_pkg::sep_32_64_6_12_axi_resp_t csrng_axi_resp_o,
    input  sep_pkg::sep_32_64_6_12_axi_req_t  edn_axi_req_i,
    output sep_pkg::sep_32_64_6_12_axi_resp_t edn_axi_resp_o,

    output drbg_pkg::drbg_axis_req_t [NUM_AXIS-1:0] drbg_axis_req_o,
    input  drbg_pkg::drbg_axis_rsp_t [NUM_AXIS-1:0] drbg_axis_rsp_i,

    input  prim_alert_pkg::alert_rx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_rx_i,
    output prim_alert_pkg::alert_tx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_tx_o,
    input  prim_alert_pkg::alert_rx_t [  edn_reg_pkg::NumAlerts-1:0] edn_alert_rx_i,
    output prim_alert_pkg::alert_tx_t [  edn_reg_pkg::NumAlerts-1:0] edn_alert_tx_o,

    output logic entropy_source_irq_o,
    output logic intr_cs_cmd_req_done_o,
    output logic intr_cs_entropy_req_o,
    output logic intr_cs_hw_inst_exc_o,
    output logic intr_cs_fatal_err_o,
    output logic intr_edn_cmd_req_done_o,
    output logic intr_edn_fatal_err_o,

    // DRBG register bridge faults, CSRNG and EDN paths reported separately
    // (sticky, each held until its own clear)
    output logic csrng_bus_err_o,
    input  logic csrng_bus_err_clr_i,
    output logic edn_bus_err_o,
    input  logic edn_bus_err_clr_i,

    // Local-reset indication, consumed only as a synchronous clear downstream.
    output logic trng_reset_active_o
);

    logic trng_gated_rst_n;

    sep_pkg::sep_32_64_6_12_axi_req_t  esrc_axi_isolated_req;
    sep_pkg::sep_32_64_6_12_axi_req_t  csrng_axi_isolated_req;
    sep_pkg::sep_32_64_6_12_axi_req_t  edn_axi_isolated_req;
    sep_pkg::sep_32_64_6_12_axi_resp_t esrc_axi_isolated_resp;
    sep_pkg::sep_32_64_6_12_axi_resp_t csrng_axi_isolated_resp;
    sep_pkg::sep_32_64_6_12_axi_resp_t edn_axi_isolated_resp;

    sep_crypto_trng_axi_isolate #(
        .ADDR_WIDTH (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .DATA_WIDTH (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .ID_WIDTH   (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .USER_WIDTH (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .NUM_PENDING(4),
        .axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
        .axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t)
    ) u_axi_isolate (
        .clk_i,
        .rst_ni,
        .trng_sw_rst_req_ni,
        .esrc_slv_req_i  (esrc_axi_req_i),
        .esrc_slv_resp_o (esrc_axi_resp_o),
        .esrc_mst_req_o  (esrc_axi_isolated_req),
        .esrc_mst_resp_i (esrc_axi_isolated_resp),
        .csrng_slv_req_i (csrng_axi_req_i),
        .csrng_slv_resp_o(csrng_axi_resp_o),
        .csrng_mst_req_o (csrng_axi_isolated_req),
        .csrng_mst_resp_i(csrng_axi_isolated_resp),
        .edn_slv_req_i   (edn_axi_req_i),
        .edn_slv_resp_o  (edn_axi_resp_o),
        .edn_mst_req_o   (edn_axi_isolated_req),
        .edn_mst_resp_i  (edn_axi_isolated_resp),
        .trng_gated_rst_no (trng_gated_rst_n)
    );

    assign trng_reset_active_o = ~trng_gated_rst_n;

    drbg_pkg::drbg_axil64_req_t  csrng_axil_req;
    drbg_pkg::drbg_axil64_resp_t csrng_axil_resp;
    drbg_pkg::drbg_axil64_req_t  edn_axil_req;
    drbg_pkg::drbg_axil64_resp_t edn_axil_resp;

    axi_to_axi_lite #(
        .AxiAddrWidth   (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiDataWidth   (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiIdWidth     (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .AxiUserWidth   (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .AxiMaxWriteTxns(4),
        .AxiMaxReadTxns (4),
        .full_req_t     (sep_pkg::sep_32_64_6_12_axi_req_t),
        .full_resp_t    (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .lite_req_t     (drbg_pkg::drbg_axil64_req_t),
        .lite_resp_t    (drbg_pkg::drbg_axil64_resp_t)
    ) u_csrng_axi_to_axi_lite (
        .clk_i,
        .rst_ni    (trng_gated_rst_n),
        .test_i    (test_en_i),
        .slv_req_i (csrng_axi_isolated_req),
        .slv_resp_o(csrng_axi_isolated_resp),
        .mst_req_o (csrng_axil_req),
        .mst_resp_i(csrng_axil_resp)
    );

    axi_to_axi_lite #(
        .AxiAddrWidth   (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiDataWidth   (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiIdWidth     (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .AxiUserWidth   (sep_pkg::SEP_32_64_6_12_USER_WIDTH),
        .AxiMaxWriteTxns(4),
        .AxiMaxReadTxns (4),
        .full_req_t     (sep_pkg::sep_32_64_6_12_axi_req_t),
        .full_resp_t    (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .lite_req_t     (drbg_pkg::drbg_axil64_req_t),
        .lite_resp_t    (drbg_pkg::drbg_axil64_resp_t)
    ) u_edn_axi_to_axi_lite (
        .clk_i,
        .rst_ni    (trng_gated_rst_n),
        .test_i    (test_en_i),
        .slv_req_i (edn_axi_isolated_req),
        .slv_resp_o(edn_axi_isolated_resp),
        .mst_req_o (edn_axil_req),
        .mst_resp_i(edn_axil_resp)
    );

    sep_pkg::sep_32_32_6_12_axi_req_t  esrc_axi32_req;
    sep_pkg::sep_32_32_6_12_axi_resp_t esrc_axi32_resp;

    axi_dw_converter #(
        .AxiMaxReads        (8),
        .AxiSlvPortDataWidth(sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .AxiMstPortDataWidth(sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
        .AxiAddrWidth       (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
        .AxiIdWidth         (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .aw_chan_t          (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
        .mst_w_chan_t       (sep_pkg::sep_32_32_6_12_axi_w_chan_t),
        .slv_w_chan_t       (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
        .b_chan_t           (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
        .ar_chan_t          (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
        .mst_r_chan_t       (sep_pkg::sep_32_32_6_12_axi_r_chan_t),
        .slv_r_chan_t       (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
        .axi_mst_req_t      (sep_pkg::sep_32_32_6_12_axi_req_t),
        .axi_mst_resp_t     (sep_pkg::sep_32_32_6_12_axi_resp_t),
        .axi_slv_req_t      (sep_pkg::sep_32_64_6_12_axi_req_t),
        .axi_slv_resp_t     (sep_pkg::sep_32_64_6_12_axi_resp_t)
    ) u_esrc_axi_dw_converter (
        .clk_i,
        .rst_ni    (trng_gated_rst_n),
        .slv_req_i (esrc_axi_isolated_req),
        .slv_resp_o(esrc_axi_isolated_resp),
        .mst_req_o (esrc_axi32_req),
        .mst_resp_i(esrc_axi32_resp)
    );

    sep_pkg::sep_32_32_axil_req_t  esrc_axil_req;
    sep_pkg::sep_32_32_axil_resp_t esrc_axil_resp;

    axi_to_axi_lite #(
        .AxiAddrWidth   (sep_pkg::SEP_32_32_6_12_ADDR_WIDTH),
        .AxiDataWidth   (sep_pkg::SEP_32_32_6_12_DATA_WIDTH),
        .AxiIdWidth     (sep_pkg::SEP_32_32_6_12_ID_WIDTH),
        .AxiUserWidth   (sep_pkg::SEP_32_32_6_12_USER_WIDTH),
        .AxiMaxWriteTxns(4),
        .AxiMaxReadTxns (4),
        .full_req_t     (sep_pkg::sep_32_32_6_12_axi_req_t),
        .full_resp_t    (sep_pkg::sep_32_32_6_12_axi_resp_t),
        .lite_req_t     (sep_pkg::sep_32_32_axil_req_t),
        .lite_resp_t    (sep_pkg::sep_32_32_axil_resp_t)
    ) u_esrc_axi_to_axi_lite (
        .clk_i,
        .rst_ni    (trng_gated_rst_n),
        .test_i    (test_en_i),
        .slv_req_i (esrc_axi32_req),
        .slv_resp_o(esrc_axi32_resp),
        .mst_req_o (esrc_axil_req),
        .mst_resp_i(esrc_axil_resp)
    );

    logic [31:0] entropy_stream_data;
    logic entropy_stream_vld;

    entropy_source u_entropy_source_s3c_scan (
        .clk_i,
        .rst_ni               (trng_gated_rst_n),
        .s_axil_awvalid_i     (esrc_axil_req.aw_valid),
        .s_axil_awready_o     (esrc_axil_resp.aw_ready),
        .s_axil_awaddr_i      (esrc_axil_req.aw.addr[8:0]),
        .s_axil_awprot_i      (esrc_axil_req.aw.prot),
        .s_axil_wvalid_i      (esrc_axil_req.w_valid),
        .s_axil_wready_o      (esrc_axil_resp.w_ready),
        .s_axil_wdata_i       (esrc_axil_req.w.data),
        .s_axil_wstrb_i       (esrc_axil_req.w.strb),
        .s_axil_bvalid_o      (esrc_axil_resp.b_valid),
        .s_axil_bready_i      (esrc_axil_req.b_ready),
        .s_axil_bresp_o       (esrc_axil_resp.b.resp),
        .s_axil_arvalid_i     (esrc_axil_req.ar_valid),
        .s_axil_arready_o     (esrc_axil_resp.ar_ready),
        .s_axil_araddr_i      (esrc_axil_req.ar.addr[8:0]),
        .s_axil_arprot_i      (esrc_axil_req.ar.prot),
        .s_axil_rvalid_o      (esrc_axil_resp.r_valid),
        .s_axil_rready_i      (esrc_axil_req.r_ready),
        .s_axil_rdata_o       (esrc_axil_resp.r.data),
        .s_axil_rresp_o       (esrc_axil_resp.r.resp),
        .signal_monitor_o     (),
        .rosc_sample_clk_i    (entropy_rosc_sample_clk_i),
        .entropy_stream_data_o(entropy_stream_data),
        .entropy_stream_vld_o (entropy_stream_vld),
        .irq_o                (entropy_source_irq_o)
    );

    drbg #(
        .EDN_ENDPOINT_COUNT       (NUM_AXIS),
        .EDN_NATIVE_ENDPOINT_COUNT(0)
    ) u_drbg_s3c_scan (
        .clk_i,
        .rst_ni                    (trng_gated_rst_n),
        .entropy_stream_data_i     (entropy_stream_data),
        .entropy_stream_vld_i      (entropy_stream_vld),
        .edn_axis_o                (drbg_axis_req_o),
        .edn_axis_i                (drbg_axis_rsp_i),
        .edn_native_req_i          (edn_pkg::EDN_REQ_DEFAULT),
        .edn_native_rsp_o          (),
        .csrng_axil_req_i          (csrng_axil_req),
        .csrng_axil_rsp_o          (csrng_axil_resp),
        .edn_axil_req_i            (edn_axil_req),
        .edn_axil_rsp_o            (edn_axil_resp),
        .otp_en_csrng_sw_app_read_i(prim_mubi_pkg::MuBi8True),
        .lc_hw_debug_en_i          (lc_ctrl_pkg::Off),
        .csrng_alert_rx_i          (csrng_alert_rx_i),
        .csrng_alert_tx_o          (csrng_alert_tx_o),
        .edn_alert_rx_i            (edn_alert_rx_i),
        .edn_alert_tx_o            (edn_alert_tx_o),
        .intr_cs_cmd_req_done_o,
        .intr_cs_entropy_req_o,
        .intr_cs_hw_inst_exc_o,
        .intr_cs_fatal_err_o,
        .intr_edn_cmd_req_done_o,
        .intr_edn_fatal_err_o,
        .csrng_bus_err_o           (csrng_bus_err_o),
        .csrng_bus_err_clr_i       (csrng_bus_err_clr_i),
        .edn_bus_err_o             (edn_bus_err_o),
        .edn_bus_err_clr_i         (edn_bus_err_clr_i)
    );

    if (NUM_AXIS != sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT) begin : g_endpoint_width_check
        $error("sep_trng: NUM_AXIS must equal SEP_CRYPTO_EDN_ENDPOINT_COUNT");
    end

endmodule
