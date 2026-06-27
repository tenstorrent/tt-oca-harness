// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//----------------------------------------------------------
// Copyright 2026 Tenstorrent Inc.
// drbg
//
// Top-level DRBG wrapper around entropy_source, CSRNG, and EDN glue.
//----------------------------------------------------------

`default_nettype none


/**
 * @file drbg.sv
 * @brief Top-level DRBG wrapper around CSRNG, EDN, and wrapper-local datapaths.
 *
 * @details Integrates the wrapper-local entropy router, CSRNG seed adapter,
 *          EDN endpoint AXI-Stream adapters, and separate CSRNG/EDN 64-bit
 *          AXI-Lite control ports. All wrapper logic stays in the single
 *          `clk_i` / `rst_ni` domain. Reset may assert asynchronously but must
 *          deassert synchronously to `clk_i`; the wrapper adds no internal
 *          reset-domain crossings or autonomous CSR control sequencing.
 *
 * @param INGRESS_FIFO_DEPTH Shared depth for the distribution and CSRNG-word FIFOs.
 * @param SEED_FIFO_DEPTH Depth of the complete-seed queue feeding CSRNG.
 * @param EDN_ENDPOINT_COUNT Number of exposed EDN endpoint AXI-Stream outputs.
 * @param EDN_NATIVE_ENDPOINT_COUNT Number of native EDN req/rsp endpoints (bypass AXI-Stream).
 * @param ENDPOINT_FIFO_DEPTH Depth of each EDN endpoint AXI-Stream FIFO.
 */
module drbg import drbg_pkg::*; #(
    parameter int unsigned INGRESS_FIFO_DEPTH = DRBG_DEFAULT_INGRESS_FIFO_DEPTH,
    parameter int unsigned SEED_FIFO_DEPTH = DRBG_DEFAULT_SEED_FIFO_DEPTH,
    parameter int unsigned EDN_ENDPOINT_COUNT = DRBG_DEFAULT_EDN_ENDPOINT_COUNT,
    parameter int unsigned EDN_NATIVE_ENDPOINT_COUNT = DRBG_DEFAULT_EDN_NATIVE_ENDPOINT_COUNT,
    // VCS UCTLAB: unsigned `(N-1)` underflows when N==0 in a packed-array bound. Use a
    // port-width proxy that stays >= 1 and tie the (unused) slot off when COUNT==0.
    localparam int unsigned EDN_NATIVE_PORT_WIDTH =
        (EDN_NATIVE_ENDPOINT_COUNT == 0) ? 1 : EDN_NATIVE_ENDPOINT_COUNT,
    parameter int unsigned ENDPOINT_FIFO_DEPTH = DRBG_DEFAULT_ENDPOINT_FIFO_DEPTH,
    parameter type csrng_axil_req_t = drbg_axil64_req_t,
    parameter type csrng_axil_rsp_t = drbg_axil64_resp_t,
    parameter type edn_axil_req_t = drbg_axil64_req_t,
    parameter type edn_axil_rsp_t = drbg_axil64_resp_t
) (
    input  wire logic clk_i,
    input  wire logic rst_ni,

    input  wire logic [31:0] entropy_stream_data_i,
    input  wire logic   entropy_stream_vld_i,

    output drbg_axis_req_t entropy_axis_o,
    input  wire drbg_axis_rsp_t entropy_axis_i,

    output drbg_axis_req_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_o,
    input  wire drbg_axis_rsp_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_i,

    // Native EDN endpoints (bypass AXI-Stream adapter). Port width is 1 when COUNT==0.
    input  wire edn_pkg::edn_req_t [EDN_NATIVE_PORT_WIDTH-1:0] edn_native_req_i,
    output edn_pkg::edn_rsp_t [EDN_NATIVE_PORT_WIDTH-1:0] edn_native_rsp_o,

    input  wire csrng_axil_req_t csrng_axil_req_i,
    output csrng_axil_rsp_t csrng_axil_rsp_o,
    input  wire edn_axil_req_t edn_axil_req_i,
    output edn_axil_rsp_t   edn_axil_rsp_o,

    input  wire prim_mubi_pkg::mubi8_t otp_en_csrng_sw_app_read_i,
    input  wire lc_ctrl_pkg::lc_tx_t   lc_hw_debug_en_i,

    input  wire prim_alert_pkg::alert_rx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_rx_i,
    output prim_alert_pkg::alert_tx_t [csrng_reg_pkg::NumAlerts-1:0] csrng_alert_tx_o,
    input  wire prim_alert_pkg::alert_rx_t [edn_reg_pkg::NumAlerts-1:0] edn_alert_rx_i,
    output prim_alert_pkg::alert_tx_t [edn_reg_pkg::NumAlerts-1:0]   edn_alert_tx_o,

    output logic intr_cs_cmd_req_done_o,
    output logic intr_cs_entropy_req_o,
    output logic intr_cs_hw_inst_exc_o,
    output logic intr_cs_fatal_err_o,
    output logic intr_edn_cmd_req_done_o,
    output logic intr_edn_fatal_err_o
);

    `include "prim_assert.sv"

    localparam int unsigned CSRNG_NUM_HW_APPS = csrng_reg_pkg::NumApps - 1;
    localparam int unsigned EDN_TOTAL_ENDPOINTS = EDN_ENDPOINT_COUNT + EDN_NATIVE_ENDPOINT_COUNT;

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

    logic entropy_route_distribution_pulse;
    logic entropy_route_csrng_pulse;
    logic entropy_drop_pulse;
    logic distribution_fifo_full;
    logic csrng_fifo_full;
    logic [$clog2(INGRESS_FIFO_DEPTH + 1)-1:0] distribution_fifo_depth;
    logic [$clog2(INGRESS_FIFO_DEPTH + 1)-1:0] csrng_fifo_depth;

    logic csrng_word_valid;
    logic [31:0] csrng_word_data;
    logic csrng_word_ready;

    entropy_src_pkg::entropy_src_hw_if_req_t csrng_entropy_req;
    entropy_src_pkg::entropy_src_hw_if_rsp_t csrng_entropy_rsp;

    logic seed_queue_valid;
    logic [383:0] seed_queue_bits;
    logic seed_queue_fips;
    logic seed_push_pulse;
    logic [4:0] seed_packer_word_count;
    logic [$clog2(SEED_FIFO_DEPTH + 1)-1:0] seed_queue_depth;

    csrng_pkg::csrng_req_t [CSRNG_NUM_HW_APPS-1:0] csrng_hw_req;
    csrng_pkg::csrng_rsp_t [CSRNG_NUM_HW_APPS-1:0] csrng_hw_rsp;
    csrng_pkg::csrng_req_t edn_csrng_req;
    csrng_pkg::csrng_rsp_t edn_csrng_rsp;

    // Total EDN endpoints: AXI-Stream (for Key Manager) + native (for crypto blocks)
    edn_pkg::edn_req_t [EDN_TOTAL_ENDPOINTS-1:0] edn_all_req;
    edn_pkg::edn_rsp_t [EDN_TOTAL_ENDPOINTS-1:0] edn_all_rsp;

    // AXI-Stream adapter subset
    edn_pkg::edn_req_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_endpoint_req;
    edn_pkg::edn_rsp_t [EDN_ENDPOINT_COUNT-1:0] edn_axis_endpoint_rsp;
    logic [EDN_ENDPOINT_COUNT-1:0] endpoint_fifo_full;
    logic [EDN_ENDPOINT_COUNT-1:0][$clog2(ENDPOINT_FIFO_DEPTH + 1)-1:0] endpoint_fifo_depth;

    // =========================================================================
    // Entropy ingress, seed packing, and endpoint AXI-Stream adaptation
    // =========================================================================

    drbg_entropy_router #(
        .INGRESS_FIFO_DEPTH(INGRESS_FIFO_DEPTH)
    ) u_entropy_router (
        .clk_i                    (clk_i),
        .rst_ni                   (rst_ni),
        .entropy_stream_vld_i     (entropy_stream_vld_i),
        .entropy_stream_data_i    (entropy_stream_data_i),
        .entropy_axis_o           (entropy_axis_o),
        .entropy_axis_i           (entropy_axis_i),
        .csrng_word_valid_o       (csrng_word_valid),
        .csrng_word_data_o        (csrng_word_data),
        .csrng_word_ready_i       (csrng_word_ready),
        .distribution_accept_o    (entropy_route_distribution_pulse),
        .csrng_accept_o           (entropy_route_csrng_pulse),
        .entropy_drop_o           (entropy_drop_pulse),
        .distribution_fifo_full_o (distribution_fifo_full),
        .csrng_fifo_full_o        (csrng_fifo_full),
        .distribution_fifo_depth_o(distribution_fifo_depth),
        .csrng_fifo_depth_o       (csrng_fifo_depth)
    );

    drbg_csrng_seed_adapter #(
        .SEED_FIFO_DEPTH(SEED_FIFO_DEPTH)
    ) u_csrng_seed_adapter (
        .clk_i                 (clk_i),
        .rst_ni                (rst_ni),
        .csrng_word_valid_i    (csrng_word_valid),
        .csrng_word_data_i     (csrng_word_data),
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

    // Map native endpoints to EDN indices [EDN_ENDPOINT_COUNT .. EDN_TOTAL_ENDPOINTS-1]
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
        .AXI_ADDR_WIDTH (DRBG_AXIL32_ADDR_WIDTH),
        .AXI_DATA_WIDTH (DRBG_AXIL32_DATA_WIDTH),
        .axi_lite_req_t (drbg_axil32_req_t),
        .axi_lite_rsp_t (drbg_axil32_resp_t)
    ) u_csrng_axi_lite_to_tlul (
        .clk_i          (clk_i),
        .rst_ni         (rst_ni),
        .axi_lite_req_i (csrng_axil32_req),
        .axi_lite_rsp_o (csrng_axil32_rsp),
        .tl_o           (csrng_tl_h2d),
        .tl_i           (csrng_tl_d2h),
        .err_o          (/* unused */)
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
        .AXI_ADDR_WIDTH (DRBG_AXIL32_ADDR_WIDTH),
        .AXI_DATA_WIDTH (DRBG_AXIL32_DATA_WIDTH),
        .axi_lite_req_t (drbg_axil32_req_t),
        .axi_lite_rsp_t (drbg_axil32_resp_t)
    ) u_edn_axi_lite_to_tlul (
        .clk_i          (clk_i),
        .rst_ni         (rst_ni),
        .axi_lite_req_i (edn_axil32_req),
        .axi_lite_rsp_o (edn_axil32_rsp),
        .tl_o           (edn_tl_h2d),
        .tl_i           (edn_tl_d2h),
        .err_o          (/* unused */)
    );

    // =========================================================================
    // Wrapped CSRNG and EDN instances
    // =========================================================================

    assign csrng_hw_req[0] = edn_csrng_req;
    assign edn_csrng_rsp = csrng_hw_rsp[0];
    if (CSRNG_NUM_HW_APPS > 1) begin : gen_unused_hw_apps
        for (genvar i = 1; i < CSRNG_NUM_HW_APPS; i++) begin : gen_tieoff
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
        .NumEndPoints(EDN_TOTAL_ENDPOINTS)
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

    `ASSERT_INIT(IngressDepthValid_A, INGRESS_FIFO_DEPTH > 0)
    `ASSERT_INIT(SeedDepthValid_A, SEED_FIFO_DEPTH > 0)
    `ASSERT_INIT(EndpointCountValid_A, EDN_ENDPOINT_COUNT > 0)
    `ASSERT_INIT(TotalEndpointCountValid_A, EDN_TOTAL_ENDPOINTS > 0)
    `ASSERT_INIT(EndpointDepthValid_A, ENDPOINT_FIFO_DEPTH > 0)

    `ASSERT(CsrngNoTlOnUnsupported_A, csrng_bridge_unsupported_pulse |-> !csrng_tl_h2d.a_valid)
    `ASSERT(EdnNoTlOnUnsupported_A, edn_bridge_unsupported_pulse |-> !edn_tl_h2d.a_valid)
    `ASSERT(EntropyAxisStrbFull_A, entropy_axis_o.tvalid |-> entropy_axis_o.tstrb == 4'hF)
    `ASSERT(SeedFipsTopLevel_A, seed_queue_valid |-> seed_queue_fips == DRBG_CSRNG_SEED_FIPS_PROVISIONAL)

    `ASSERT_KNOWN(EntropyAxisTvalidKnown_A, entropy_axis_o.tvalid)
    `ASSERT_KNOWN_IF(EntropyAxisTdataKnown_A, entropy_axis_o.tdata, entropy_axis_o.tvalid)
    `ASSERT_KNOWN_IF(EntropyAxisTstrbKnown_A, entropy_axis_o.tstrb, entropy_axis_o.tvalid)
    `ASSERT_KNOWN(CsrngAlertTxKnown_A, csrng_alert_tx_o)
    `ASSERT_KNOWN(EdnAlertTxKnown_A, edn_alert_tx_o)
    `ASSERT_KNOWN(IntrCsCmdReqDoneKnown_A, intr_cs_cmd_req_done_o)
    `ASSERT_KNOWN(IntrCsEntropyReqKnown_A, intr_cs_entropy_req_o)
    `ASSERT_KNOWN(IntrCsHwInstExcKnown_A, intr_cs_hw_inst_exc_o)
    `ASSERT_KNOWN(IntrCsFatalErrKnown_A, intr_cs_fatal_err_o)
    `ASSERT_KNOWN(IntrEdnCmdReqDoneKnown_A, intr_edn_cmd_req_done_o)
    `ASSERT_KNOWN(IntrEdnFatalErrKnown_A, intr_edn_fatal_err_o)

    for (genvar i = 0; i < EDN_ENDPOINT_COUNT; i++) begin : gen_edn_axis_known
        `ASSERT_KNOWN(EdnAxisTvalidKnown_A, edn_axis_o[i].tvalid)
        `ASSERT_KNOWN_IF(EdnAxisTdataKnown_A, edn_axis_o[i].tdata, edn_axis_o[i].tvalid)
        `ASSERT_KNOWN_IF(EdnAxisTstrbKnown_A, edn_axis_o[i].tstrb, edn_axis_o[i].tvalid)
    end

endmodule : drbg

`default_nettype wire
