// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Wrap CSRNG, EDN, and the wrapper-local seed and AXIS adapters into one DRBG block.
//
// Integrate the CSRNG seed adapter, EDN endpoint AXI-Stream adapters, and separate CSRNG
// and EDN 64-bit AXI-Lite control ports. Register-bridge faults are sticky per path and
// held until each path's own clear.
//
// The producer-driven entropy_stream_* input feeds the seed packer directly. The entropy
// source is fire-and-forget, and words offered while the seed path is full are dropped
// without forming a partial seed.
//
// Native EDN endpoints bypass the AXI-Stream adapter; port width is 1 when
// EDN_NATIVE_ENDPOINT_COUNT is 0.
//
// All wrapper logic stays in the single clk_i / rst_ni domain. Reset may assert
// asynchronously but must deassert synchronously to clk_i. The wrapper adds no internal
// reset-domain crossings or autonomous CSR control sequencing.

module drbg
  import drbg_pkg::DrbgDefaultSeedFifoDepth;
  import drbg_pkg::DrbgDefaultEdnEndpointCount;
  import drbg_pkg::DrbgDefaultEdnNativeEndpointCount;
  import drbg_pkg::DrbgDefaultEndpointFifoDepth;
  import drbg_pkg::drbg_axil64_req_t;
  import drbg_pkg::drbg_axil64_resp_t;
  import drbg_pkg::drbg_axis_req_t;
  import drbg_pkg::drbg_axis_rsp_t;
  import drbg_pkg::drbg_axil32_req_t;
  import drbg_pkg::drbg_axil32_resp_t;
  import drbg_pkg::DrbgAxil32AddrWidth;
  import drbg_pkg::DrbgAxil32DataWidth;
  import drbg_pkg::DrbgCsrngSeedFipsProvisional;
#(
  parameter int unsigned SEED_FIFO_DEPTH = DrbgDefaultSeedFifoDepth,     // Number of complete packed seeds queued for CSRNG.
                                                                         // Must be at least 1.
  parameter int unsigned EDN_ENDPOINT_COUNT = DrbgDefaultEdnEndpointCount,     // Number of EDN endpoints exposed as AXI-Stream outputs.
                                                                               // Each output carries an independent random-data stream.
                                                                               // Must be at least 1.
  parameter int unsigned EDN_NATIVE_ENDPOINT_COUNT = DrbgDefaultEdnNativeEndpointCount,      // Number of native EDN req/rsp endpoints.
                                                                                             // Each exposes a raw edn_pkg bundle that bypasses
                                                                                             // the AXI-Stream FIFOs.
  localparam int unsigned EdnNativePortWidth =           // Width of the native EDN ports, which is 1 when EDN_NATIVE_ENDPOINT_COUNT is 0. The single slot is then unused and its request should be tied off.
        (EDN_NATIVE_ENDPOINT_COUNT == 0) ? 1 : EDN_NATIVE_ENDPOINT_COUNT,
  parameter int unsigned ENDPOINT_FIFO_DEPTH = DrbgDefaultEndpointFifoDepth,     // Depth of the FIFO on each AXI-Stream EDN endpoint.
                                                                                 // Must be at least 1.
  parameter type csrng_axil_req_t = drbg_axil64_req_t,      // CSRNG AXI-Lite request type.
  parameter type csrng_axil_rsp_t = drbg_axil64_resp_t,     // CSRNG AXI-Lite response type.
  parameter type edn_axil_req_t = drbg_axil64_req_t,        // EDN AXI-Lite request type.
  parameter type edn_axil_rsp_t = drbg_axil64_resp_t        // EDN AXI-Lite response type.
) (
  input  logic clk_i,                                       // System clock.
  input  logic rst_ni,                                      // Active-low. May assert
                                                            // asynchronously; must deassert
                                                            // synchronously to clk_i.

  input  logic [31:0] entropy_stream_data_i,                // Producer entropy word into the seed
                                                            // packer.
  input  logic   entropy_stream_vld_i,                      // Producer entropy valid, with no
                                                            // back-pressure; a word offered while
                                                            // the packer holds a complete seed is
                                                            // dropped.

  output drbg_axis_req_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_o, // EDN AXI-Stream requests toward
                                                              // consumers; tuser carries the EDN
                                                              // FIPS bit of each word.
  input  drbg_axis_rsp_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_i, // EDN AXI-Stream ready from
                                                              // consumers.

  input  edn_pkg::edn_req_t [EdnNativePortWidth-1:0] edn_native_req_i,    // Native EDN client requests (bypass AXI-Stream).
                                                                          // Port width is 1 when EDN_NATIVE_ENDPOINT_COUNT is 0.
  output edn_pkg::edn_rsp_t [EdnNativePortWidth-1:0] edn_native_rsp_o,    // Native EDN client responses.

  input  csrng_axil_req_t csrng_axil_req_i,                 // CSRNG AXI-Lite CSR request.
  output csrng_axil_rsp_t csrng_axil_rsp_o,                 // CSRNG AXI-Lite CSR response.
  input  edn_axil_req_t edn_axil_req_i,                     // EDN AXI-Lite CSR request.
  output edn_axil_rsp_t   edn_axil_rsp_o,                   // EDN AXI-Lite CSR response.

  input  prim_mubi_pkg::mubi8_t otp_en_csrng_sw_app_read_i, // OTP enable for CSRNG SW app read.
  input  lc_ctrl_pkg::lc_tx_t   lc_hw_debug_en_i,           // Lifecycle HW-debug enable.

  input  prim_alert_pkg::alert_rx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_rx_i, // CSRNG alert receivers.
  output prim_alert_pkg::alert_tx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_tx_o, // CSRNG alert transmitters.
  input  prim_alert_pkg::alert_rx_t [edn_reg_pkg::NumAlerts-1:0] edn_alert_rx_i, // EDN alert receivers.
  output prim_alert_pkg::alert_tx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_tx_o, // EDN alert transmitters.

  output logic intr_cs_cmd_req_done_o,                      // CSRNG cmd-req-done interrupt.
  output logic intr_cs_entropy_req_o,                       // CSRNG entropy-req interrupt.
  output logic intr_cs_hw_inst_exc_o,                       // CSRNG HW-instance exception
                                                            // interrupt.
  output logic intr_cs_fatal_err_o,                         // CSRNG fatal-error interrupt.
  output logic intr_edn_cmd_req_done_o,                     // EDN cmd-req-done interrupt.
  output logic intr_edn_fatal_err_o,                        // EDN fatal-error interrupt.

  output logic csrng_bus_err_o,                             // Sticky CSRNG register-bridge fault,
                                                            // set when a TL-UL response from CSRNG
                                                            // carries d_error. Held until
                                                            // csrng_bus_err_clr_i.
  input  logic csrng_bus_err_clr_i,                         // Clear the CSRNG bus-fault sticky,
                                                            // active-high; a fault in the same
                                                            // cycle still sets it.
  output logic edn_bus_err_o,                               // Sticky EDN register-bridge fault, set
                                                            // when a TL-UL response from EDN
                                                            // carries d_error. Held until
                                                            // edn_bus_err_clr_i.
  input  logic edn_bus_err_clr_i                            // Clear the EDN bus-fault sticky,
                                                            // active-high; a fault in the same
                                                            // cycle still sets it.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  localparam int unsigned CsrngNumHwApps = csrng_reg_pkg::NumApps - 1;
  localparam int unsigned EdnTotalEndpoints = EDN_ENDPOINT_COUNT + EDN_NATIVE_ENDPOINT_COUNT;

  drbg_axil32_req_t  csrng_axil32_req;
  drbg_axil32_resp_t csrng_axil32_rsp;
  drbg_axil32_req_t  edn_axil32_req;
  drbg_axil32_resp_t edn_axil32_rsp;

  tlul_pkg::tl_h2d_t csrng_tl_h2d;
  tlul_pkg::tl_d2h_t csrng_tl_d2h;
  tlul_pkg::tl_h2d_t edn_tl_h2d;
  tlul_pkg::tl_d2h_t edn_tl_d2h;

  logic csrng_bridge_unsupported_pulse;
  logic csrng_bridge_forwarded_read_pulse;
  logic csrng_bridge_forwarded_write_pulse;
  logic edn_bridge_unsupported_pulse;
  logic edn_bridge_forwarded_read_pulse;
  logic edn_bridge_forwarded_write_pulse;

  // Entropy stream feeds the seed packer directly. The entropy source is
  // fire-and-forget (no ready), and prim_packer_fifo declines a word when its
  // wready is low (only during the 1-cycle full-seed handoff), dropping
  // fungible raw words without ever forming a partial seed. csrng_word_ready
  // is therefore observed for assertions/status only, not back-pressure.
  logic csrng_word_ready;

  entropy_src_pkg::entropy_src_hw_if_req_t csrng_entropy_req;
  entropy_src_pkg::entropy_src_hw_if_rsp_t csrng_entropy_rsp;

  logic seed_queue_valid;
  logic [383:0] seed_queue_bits;
  logic seed_queue_fips;
  logic seed_push_pulse;
  logic [4:0] seed_packer_word_count;
  logic [$clog2(SEED_FIFO_DEPTH + 1)-1:0] seed_queue_depth;

  csrng_pkg::csrng_req_t [CsrngNumHwApps-1:0] csrng_hw_req;
  csrng_pkg::csrng_rsp_t [CsrngNumHwApps-1:0] csrng_hw_rsp;
  csrng_pkg::csrng_req_t edn_csrng_req;
  csrng_pkg::csrng_rsp_t edn_csrng_rsp;

  // Total EDN endpoints: AXI-Stream (for Key Manager) + native (for crypto blocks)
  edn_pkg::edn_req_t [EdnTotalEndpoints-1:0] edn_all_req;
  edn_pkg::edn_rsp_t [EdnTotalEndpoints-1:0] edn_all_rsp;

  // AXI-Stream adapter subset
  edn_pkg::edn_req_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_endpoint_req;
  edn_pkg::edn_rsp_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_endpoint_rsp;
  logic [EDN_ENDPOINT_COUNT-1:0] endpoint_fifo_full;
  logic [EDN_ENDPOINT_COUNT-1:0][$clog2(ENDPOINT_FIFO_DEPTH + 1)-1:0] endpoint_fifo_depth;

  // =========================================================================
  // Seed packing and endpoint AXI-Stream adaptation
  // =========================================================================

  // Pack the entropy stream into complete seeds for CSRNG.
  drbg_csrng_seed_adapter #(
    .SEED_FIFO_DEPTH(SEED_FIFO_DEPTH)
  ) u_csrng_seed_adapter (
    .clk_i                 (clk_i),
    .rst_ni                (rst_ni),
    .csrng_word_valid_i    (entropy_stream_vld_i),
    .csrng_word_data_i     (entropy_stream_data_i),
    .csrng_word_ready_o    (csrng_word_ready),
    .entropy_src_hw_if_req_i(csrng_entropy_req),
    .entropy_src_hw_if_rsp_o(csrng_entropy_rsp),
    .seed_queue_valid_o    (seed_queue_valid),
    .seed_queue_bits_o     (seed_queue_bits),
    .seed_queue_fips_o     (seed_queue_fips),
    .seed_push_o           (seed_push_pulse),
    .packer_word_count_o   (seed_packer_word_count),
    .seed_queue_depth_o    (seed_queue_depth)
  );

  // The entropy source is a fire-and-forget producer with no ready signal. The
  // packer drops any word offered while it holds a complete seed, which is
  // acceptable because conditioned words are fungible and no partial seed is
  // ever formed. Its write-ready is therefore unused; sink it for lint.
  logic unused_csrng_word_ready;
  assign unused_csrng_word_ready = csrng_word_ready;

  drbg_edn_axis_adapter #(
    .EDN_ENDPOINT_COUNT (EDN_ENDPOINT_COUNT),
    .ENDPOINT_FIFO_DEPTH(ENDPOINT_FIFO_DEPTH)
  ) u_edn_axis_adapter (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),
    .edn_req_o           (edn_axis_endpoint_req),
    .edn_rsp_i           (edn_axis_endpoint_rsp),
    .edn_axis_o          (edn_axis_o),
    .edn_axis_i          (edn_axis_i),
    .endpoint_fifo_full_o(endpoint_fifo_full),
    .endpoint_fifo_depth_o(endpoint_fifo_depth)
  );

  // Map AXI-Stream adapter endpoints to EDN indices [0 .. EDN_ENDPOINT_COUNT-1]
  for (genvar i = 0; i < EDN_ENDPOINT_COUNT; i++) begin : gen_axis_edn_map
    assign edn_all_req[i] = edn_axis_endpoint_req[i];
    assign edn_axis_endpoint_rsp[i] = edn_all_rsp[i];
  end

  // Map native endpoints to EDN indices [EDN_ENDPOINT_COUNT .. EdnTotalEndpoints-1]
  if (EDN_NATIVE_ENDPOINT_COUNT > 0) begin : gen_native_edn
    for (genvar i = 0; i < EDN_NATIVE_ENDPOINT_COUNT; i++) begin : gen_native_edn_map
      assign edn_all_req[EDN_ENDPOINT_COUNT + i] = edn_native_req_i[i];
      assign edn_native_rsp_o[i] = edn_all_rsp[EDN_ENDPOINT_COUNT + i];
    end
  end else begin : gen_native_edn_tieoff
    assign edn_native_rsp_o[0] = edn_pkg::EDN_RSP_DEFAULT;
  end

  // =========================================================================
  // CSRNG and EDN control-plane bridging
  // =========================================================================

  drbg_axil64_lane_adapter #(
    .axil64_req_t(csrng_axil_req_t),
    .axil64_rsp_t(csrng_axil_rsp_t),
    .axil32_req_t(drbg_axil32_req_t),
    .axil32_rsp_t(drbg_axil32_resp_t)
  ) u_csrng_axil_adapter (
    .clk_i                     (clk_i),
    .rst_ni                    (rst_ni),
    .axil64_req_i              (csrng_axil_req_i),
    .axil64_rsp_o              (csrng_axil_rsp_o),
    .axil32_req_o              (csrng_axil32_req),
    .axil32_rsp_i              (csrng_axil32_rsp),
    .unsupported_access_pulse_o(csrng_bridge_unsupported_pulse),
    .forwarded_read_pulse_o    (csrng_bridge_forwarded_read_pulse),
    .forwarded_write_pulse_o   (csrng_bridge_forwarded_write_pulse)
  );

  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH (DrbgAxil32AddrWidth),
    .AXI_DATA_WIDTH (DrbgAxil32DataWidth),
    .axi_lite_req_t (drbg_axil32_req_t),
    .axi_lite_rsp_t (drbg_axil32_resp_t)
  ) u_csrng_axi_lite_to_tlul (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .axi_lite_req_i (csrng_axil32_req),
    .axi_lite_rsp_o (csrng_axil32_rsp),
    .tl_o           (csrng_tl_h2d),
    .tl_i           (csrng_tl_d2h),
    .err_o          (csrng_bus_err_o),
    .err_clr_i      (csrng_bus_err_clr_i)
  );

  drbg_axil64_lane_adapter #(
    .axil64_req_t(edn_axil_req_t),
    .axil64_rsp_t(edn_axil_rsp_t),
    .axil32_req_t(drbg_axil32_req_t),
    .axil32_rsp_t(drbg_axil32_resp_t)
  ) u_edn_axil_adapter (
    .clk_i                     (clk_i),
    .rst_ni                    (rst_ni),
    .axil64_req_i              (edn_axil_req_i),
    .axil64_rsp_o              (edn_axil_rsp_o),
    .axil32_req_o              (edn_axil32_req),
    .axil32_rsp_i              (edn_axil32_rsp),
    .unsupported_access_pulse_o(edn_bridge_unsupported_pulse),
    .forwarded_read_pulse_o    (edn_bridge_forwarded_read_pulse),
    .forwarded_write_pulse_o   (edn_bridge_forwarded_write_pulse)
  );

  axi_lite_to_tlul #(
    .AXI_ADDR_WIDTH (DrbgAxil32AddrWidth),
    .AXI_DATA_WIDTH (DrbgAxil32DataWidth),
    .axi_lite_req_t (drbg_axil32_req_t),
    .axi_lite_rsp_t (drbg_axil32_resp_t)
  ) u_edn_axi_lite_to_tlul (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .axi_lite_req_i (edn_axil32_req),
    .axi_lite_rsp_o (edn_axil32_rsp),
    .tl_o           (edn_tl_h2d),
    .tl_i           (edn_tl_d2h),
    .err_o          (edn_bus_err_o),
    .err_clr_i      (edn_bus_err_clr_i)
  );

  // =========================================================================
  // Wrapped CSRNG and EDN instances
  // =========================================================================

  assign csrng_hw_req[0] = edn_csrng_req;
  assign edn_csrng_rsp = csrng_hw_rsp[0];
  if (CsrngNumHwApps > 1) begin : gen_unused_hw_apps
    for (genvar i = 1; i < CsrngNumHwApps; i++) begin : gen_tieoff
      assign csrng_hw_req[i] = csrng_pkg::CSRNG_REQ_DEFAULT;
    end
  end

  csrng u_csrng (
    .clk_i                       (clk_i),
    .rst_ni                      (rst_ni),
    .tl_i                        (csrng_tl_h2d),
    .tl_o                        (csrng_tl_d2h),
    .otp_en_csrng_sw_app_read_i  (otp_en_csrng_sw_app_read_i),
    .lc_hw_debug_en_i            (lc_hw_debug_en_i),
    .entropy_src_hw_if_o         (csrng_entropy_req),
    .entropy_src_hw_if_i         (csrng_entropy_rsp),
    .csrng_cmd_i                 (csrng_hw_req),
    .csrng_cmd_o                 (csrng_hw_rsp),
    .alert_rx_i                  (csrng_alert_rx_i),
    .alert_tx_o                  (csrng_alert_tx_o),
    .intr_cs_cmd_req_done_o      (intr_cs_cmd_req_done_o),
    .intr_cs_entropy_req_o       (intr_cs_entropy_req_o),
    .intr_cs_hw_inst_exc_o       (intr_cs_hw_inst_exc_o),
    .intr_cs_fatal_err_o         (intr_cs_fatal_err_o)
  );

  edn #(
    .NumEndPoints(EdnTotalEndpoints)
  ) u_edn (
    .clk_i                  (clk_i),
    .rst_ni                 (rst_ni),
    .tl_i                   (edn_tl_h2d),
    .tl_o                   (edn_tl_d2h),
    .edn_i                  (edn_all_req),
    .edn_o                  (edn_all_rsp),
    .csrng_cmd_o            (edn_csrng_req),
    .csrng_cmd_i            (edn_csrng_rsp),
    .alert_rx_i             (edn_alert_rx_i),
    .alert_tx_o             (edn_alert_tx_o),
    .intr_edn_cmd_req_done_o(intr_edn_cmd_req_done_o),
    .intr_edn_fatal_err_o   (intr_edn_fatal_err_o)
  );

  // =========================================================================
  // Assertions
  // =========================================================================

  `OCAH_ASSERT_STATIC(SeedDepthValid_A, SEED_FIFO_DEPTH > 0)
  `OCAH_ASSERT_STATIC(EndpointCountValid_A, EDN_ENDPOINT_COUNT > 0)
  `OCAH_ASSERT_STATIC(TotalEndpointCountValid_A, EdnTotalEndpoints > 0)
  `OCAH_ASSERT_STATIC(EndpointDepthValid_A, ENDPOINT_FIFO_DEPTH > 0)

  `OCAH_OT_ASSERT(CsrngNoTlOnUnsupported_A,
                  csrng_bridge_unsupported_pulse |-> !csrng_tl_h2d.a_valid)
  `OCAH_OT_ASSERT(EdnNoTlOnUnsupported_A, edn_bridge_unsupported_pulse |-> !edn_tl_h2d.a_valid)
  `OCAH_OT_ASSERT(SeedFipsTopLevel_A,
                  seed_queue_valid |-> seed_queue_fips == DrbgCsrngSeedFipsProvisional)

  `OCAH_OT_ASSERT_KNOWN(CsrngAlertTxKnown_A, csrng_alert_tx_o)
  `OCAH_OT_ASSERT_KNOWN(EdnAlertTxKnown_A, edn_alert_tx_o)
  `OCAH_OT_ASSERT_KNOWN(IntrCsCmdReqDoneKnown_A, intr_cs_cmd_req_done_o)
  `OCAH_OT_ASSERT_KNOWN(IntrCsEntropyReqKnown_A, intr_cs_entropy_req_o)
  `OCAH_OT_ASSERT_KNOWN(IntrCsHwInstExcKnown_A, intr_cs_hw_inst_exc_o)
  `OCAH_OT_ASSERT_KNOWN(IntrCsFatalErrKnown_A, intr_cs_fatal_err_o)
  `OCAH_OT_ASSERT_KNOWN(IntrEdnCmdReqDoneKnown_A, intr_edn_cmd_req_done_o)
  `OCAH_OT_ASSERT_KNOWN(IntrEdnFatalErrKnown_A, intr_edn_fatal_err_o)

  for (genvar i = 0; i < EDN_ENDPOINT_COUNT; i++) begin : gen_edn_axis_known
    `OCAH_OT_ASSERT_KNOWN(EdnAxisTvalidKnown_A, edn_axis_o[i].tvalid)
    `OCAH_OT_ASSERT_KNOWN_IF(EdnAxisTdataKnown_A, edn_axis_o[i].tdata, edn_axis_o[i].tvalid)
    `OCAH_OT_ASSERT_KNOWN_IF(EdnAxisTstrbKnown_A, edn_axis_o[i].tstrb, edn_axis_o[i].tvalid)
  end

endmodule : drbg

