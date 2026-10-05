// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Group the internal entropy source and DRBG under one local reset, rst_ni.
//
// Owns:
//
// - entropy_source on a 32-bit AXI-Lite port (9-bit register offset), whose conditioned
//   entropy stream seeds the DRBG directly.
// - The DRBG (CSRNG and EDN) on two 64-bit AXI-Lite ports, with NUM_AXIS EDN AXI-Stream
//   endpoints and no native EDN endpoints.
// - CSRNG and EDN alerts; for each, index 0 is recoverable (recov_alert) and index 1 is
//   fatal (fatal_alert).
// - Sticky CSRNG/EDN register-bridge faults, each held until its clear.
//
// CSRNG software application reads are always enabled and lifecycle hardware debug is tied
// off. Source selection and consumer adapters live in sep_crypto because they also serve
// the external TRNG path.
//
// trng_reset_active_o is rst_ni's assertion synchronized to clk_i under por_rst_ni; it is
// meant as a synchronous clear downstream, not as a reset.

module sep_trng #(
  parameter int unsigned NUM_AXIS = sep_crypto_pkg::SepCryptoEdnEndpointCount      // Number of DRBG AXI-Stream endpoints; elaboration fails
                                                                                   // unless it equals SepCryptoEdnEndpointCount.
) (
  input logic clk_i,                          // System clock.
  input logic por_rst_ni,                     // Active-low power-on reset; resets only the
                                              // trng_reset_active_o synchronizer.
  input logic rst_ni,                         // Active-low local reset for entropy_source and the
                                              // DRBG.
  input logic entropy_rosc_sample_clk_i,      // Ring-oscillator sample clock for entropy_source;
                                              // asynchronous to clk_i.

  input  sep_pkg::sep_32_32_axil_req_t  esrc_axil_req_i,  // entropy_source register request;
                                                          // address bits [8:0] are used.
  output sep_pkg::sep_32_32_axil_resp_t esrc_axil_resp_o,  // entropy_source register response.
  input  drbg_pkg::drbg_axil64_req_t    csrng_axil_req_i,  // CSRNG register request, bridged to
                                                           // TL-UL inside the DRBG.
  output drbg_pkg::drbg_axil64_resp_t   csrng_axil_resp_o,  // CSRNG register response.
  input  drbg_pkg::drbg_axil64_req_t    edn_axil_req_i,  // EDN register request, bridged to TL-UL
                                                         // inside the DRBG.
  output drbg_pkg::drbg_axil64_resp_t   edn_axil_resp_o,  // EDN register response.

  output drbg_pkg::drbg_axis_req_t [NUM_AXIS-1:0] drbg_axis_req_o,  // DRBG random-data streams, one independent stream per EDN endpoint.
  input  drbg_pkg::drbg_axis_rsp_t [NUM_AXIS-1:0] drbg_axis_rsp_i,  // Consumer tready for each DRBG random-data stream.

  input  prim_alert_pkg::alert_rx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_rx_i,  // CSRNG alert receiver handshakes; index 0 recoverable (recov_alert), index 1
                                                                                      // fatal (fatal_alert).
  output prim_alert_pkg::alert_tx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_tx_o,  // CSRNG differential alert senders; index 0 recoverable (recov_alert), index 1
                                                                                      // fatal (fatal_alert).
  input  prim_alert_pkg::alert_rx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_rx_i,  // EDN alert receiver handshakes; index 0 recoverable (recov_alert), index 1
                                                                                    // fatal (fatal_alert).
  output prim_alert_pkg::alert_tx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_tx_o,  // EDN differential alert senders; index 0 recoverable (recov_alert), index 1
                                                                                    // fatal (fatal_alert).

  output logic entropy_source_irq_o,          // entropy_source interrupt, aggregating its sticky
                                              // fault and health-test status.
  output logic intr_cs_cmd_req_done_o,        // CSRNG command-request-done interrupt.
  output logic intr_cs_entropy_req_o,         // CSRNG entropy-request interrupt.
  output logic intr_cs_hw_inst_exc_o,         // CSRNG hardware-instance exception interrupt.
  output logic intr_cs_fatal_err_o,           // CSRNG fatal-error interrupt.
  output logic intr_edn_cmd_req_done_o,       // EDN command-request-done interrupt.
  output logic intr_edn_fatal_err_o,          // EDN fatal-error interrupt.

  output logic csrng_bus_err_o,               // Set by a TL-UL error response on the CSRNG register
                                              // bridge; sticky until csrng_bus_err_clr_i.
  input  logic csrng_bus_err_clr_i,           // Single-cycle clear for csrng_bus_err_o, pulsed by
                                              // PERIPH_BUS_ERR_CLEAR.csrng in sep.
  output logic edn_bus_err_o,                 // Set by a TL-UL error response on the EDN register
                                              // bridge; sticky until edn_bus_err_clr_i.
  input  logic edn_bus_err_clr_i,             // Single-cycle clear for edn_bus_err_o, pulsed by
                                              // PERIPH_BUS_ERR_CLEAR.edn in sep.

  output logic trng_reset_active_o            // High while rst_ni is asserted, through a two-flop
                                              // synchronizer to clk_i that por_rst_ni resets high.
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

  if (NUM_AXIS != sep_crypto_pkg::SepCryptoEdnEndpointCount) begin : gen_endpoint_width_check
    $error("sep_trng: NUM_AXIS must equal SepCryptoEdnEndpointCount");
  end

endmodule
