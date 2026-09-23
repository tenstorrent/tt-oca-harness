// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP integration wrapper for the internal entropy complex.
//
// This groups the entropy source and DRBG behind the coordinated three-port
// AXI-Lite reset boundary. Source selection and consumer adapters remain in
// sep_crypto because they also serve the external TRNG path.

module sep_trng #(
  parameter int unsigned NUM_AXIS = sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT
) (
  input logic clk_i,
  input logic por_rst_ni,
  input logic rst_ni,
  input logic entropy_rosc_sample_clk_i,

  input  sep_pkg::sep_32_32_axil_req_t  esrc_axil_req_i,
  output sep_pkg::sep_32_32_axil_resp_t esrc_axil_resp_o,
  input  drbg_pkg::drbg_axil64_req_t    csrng_axil_req_i,
  output drbg_pkg::drbg_axil64_resp_t   csrng_axil_resp_o,
  input  drbg_pkg::drbg_axil64_req_t    edn_axil_req_i,
  output drbg_pkg::drbg_axil64_resp_t   edn_axil_resp_o,

  output drbg_pkg::drbg_axis_req_t [NUM_AXIS-1:0] drbg_axis_req_o,
  input  drbg_pkg::drbg_axis_rsp_t [NUM_AXIS-1:0] drbg_axis_rsp_i,

  input  prim_alert_pkg::alert_rx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_rx_i,
  output prim_alert_pkg::alert_tx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_tx_o,
  input  prim_alert_pkg::alert_rx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_rx_i,
  output prim_alert_pkg::alert_tx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_tx_o,

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

  logic trng_reset_active_async;

  assign trng_reset_active_async = ~rst_ni;

  // POR initializes clear asserted without using the local reset being observed.
  prim_flop_2sync #(
    .Width     (1),
    .ResetValue(1'b1)
  ) u_trng_reset_active_sync (
    .clk_i,
    .rst_ni (por_rst_ni),
    .d_i    (trng_reset_active_async),
    .q_o    (trng_reset_active_o)
  );

  logic [31:0] entropy_stream_data;
  logic entropy_stream_vld;

  entropy_source u_entropy_source_s3c_scan (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),
    .s_axil_awvalid_i     (esrc_axil_req_i.aw_valid),
    .s_axil_awready_o     (esrc_axil_resp_o.aw_ready),
    .s_axil_awaddr_i      (esrc_axil_req_i.aw.addr[8:0]),
    .s_axil_awprot_i      (esrc_axil_req_i.aw.prot),
    .s_axil_wvalid_i      (esrc_axil_req_i.w_valid),
    .s_axil_wready_o      (esrc_axil_resp_o.w_ready),
    .s_axil_wdata_i       (esrc_axil_req_i.w.data),
    .s_axil_wstrb_i       (esrc_axil_req_i.w.strb),
    .s_axil_bvalid_o      (esrc_axil_resp_o.b_valid),
    .s_axil_bready_i      (esrc_axil_req_i.b_ready),
    .s_axil_bresp_o       (esrc_axil_resp_o.b.resp),
    .s_axil_arvalid_i     (esrc_axil_req_i.ar_valid),
    .s_axil_arready_o     (esrc_axil_resp_o.ar_ready),
    .s_axil_araddr_i      (esrc_axil_req_i.ar.addr[8:0]),
    .s_axil_arprot_i      (esrc_axil_req_i.ar.prot),
    .s_axil_rvalid_o      (esrc_axil_resp_o.r_valid),
    .s_axil_rready_i      (esrc_axil_req_i.r_ready),
    .s_axil_rdata_o       (esrc_axil_resp_o.r.data),
    .s_axil_rresp_o       (esrc_axil_resp_o.r.resp),
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
    .clk_i                     (clk_i),
    .rst_ni                    (rst_ni),
    .entropy_stream_data_i     (entropy_stream_data),
    .entropy_stream_vld_i      (entropy_stream_vld),
    .edn_axis_o                (drbg_axis_req_o),
    .edn_axis_i                (drbg_axis_rsp_i),
    .edn_native_req_i          (edn_pkg::EDN_REQ_DEFAULT),
    .edn_native_rsp_o          (),
    .csrng_axil_req_i          (csrng_axil_req_i),
    .csrng_axil_rsp_o          (csrng_axil_resp_o),
    .edn_axil_req_i            (edn_axil_req_i),
    .edn_axil_rsp_o            (edn_axil_resp_o),
    .otp_en_csrng_sw_app_read_i(prim_mubi_pkg::MuBi8True),
    .lc_hw_debug_en_i          (lc_ctrl_pkg::Off),
    .csrng_alert_rx_i          (csrng_alert_rx_i),
    .csrng_alert_tx_o          (csrng_alert_tx_o),
    .edn_alert_rx_i            (edn_alert_rx_i),
    .edn_alert_tx_o            (edn_alert_tx_o),
    .intr_cs_cmd_req_done_o    (intr_cs_cmd_req_done_o),
    .intr_cs_entropy_req_o     (intr_cs_entropy_req_o),
    .intr_cs_hw_inst_exc_o     (intr_cs_hw_inst_exc_o),
    .intr_cs_fatal_err_o       (intr_cs_fatal_err_o),
    .intr_edn_cmd_req_done_o   (intr_edn_cmd_req_done_o),
    .intr_edn_fatal_err_o      (intr_edn_fatal_err_o),
    .csrng_bus_err_o           (csrng_bus_err_o),
    .csrng_bus_err_clr_i       (csrng_bus_err_clr_i),
    .edn_bus_err_o             (edn_bus_err_o),
    .edn_bus_err_clr_i         (edn_bus_err_clr_i)
  );

  if (NUM_AXIS != sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT) begin : gen_endpoint_width_check
    $error("sep_trng: NUM_AXIS must equal SEP_CRYPTO_EDN_ENDPOINT_COUNT");
  end

endmodule
