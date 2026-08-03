// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP Crypto AXI Isolate
//
// Software-reset isolation for the crypto accelerator AXI ports (HMAC, OTBN,
// AES, KMAC). Sits between the sep_crypto demux master ports and the
// accelerator wrappers. On a software reset request, isolates the requesting
// accelerator's AXI port (drains in-flight transactions, terminates new ones
// with DECERR), then asserts that wrapper's reset. Each port is sequenced
// independently by a sep_crypto_axi_isolate_unit.

module sep_crypto_axi_isolate
#(
    parameter int unsigned ADDR_WIDTH  = 32,
    parameter int unsigned DATA_WIDTH  = 64,
    parameter int unsigned ID_WIDTH    = 6,
    parameter int unsigned USER_WIDTH  = 12,
    // Must cover the maximum outstanding transactions of the upstream demux
    parameter int unsigned NUM_PENDING = 4,
    parameter type axi_req_t  = logic,
    parameter type axi_resp_t = logic
) (
    input  logic      clk_i,
    input  logic      rst_ni,

    // HMAC
    input  logic      hmac_sw_rst_req_ni,
    input  axi_req_t  hmac_slv_req_i,
    output axi_resp_t hmac_slv_resp_o,
    output axi_req_t  hmac_mst_req_o,
    input  axi_resp_t hmac_mst_resp_i,
    output logic      hmac_gated_rst_no,

    // OTBN
    input  logic      otbn_sw_rst_req_ni,
    input  axi_req_t  otbn_slv_req_i,
    output axi_resp_t otbn_slv_resp_o,
    output axi_req_t  otbn_mst_req_o,
    input  axi_resp_t otbn_mst_resp_i,
    output logic      otbn_gated_rst_no,

    // AES
    input  logic      aes_sw_rst_req_ni,
    input  axi_req_t  aes_slv_req_i,
    output axi_resp_t aes_slv_resp_o,
    output axi_req_t  aes_mst_req_o,
    input  axi_resp_t aes_mst_resp_i,
    output logic      aes_gated_rst_no,

    // KMAC
    input  logic      kmac_sw_rst_req_ni,
    input  axi_req_t  kmac_slv_req_i,
    output axi_resp_t kmac_slv_resp_o,
    output axi_req_t  kmac_mst_req_o,
    input  axi_resp_t kmac_mst_resp_i,
    output logic      kmac_gated_rst_no
);

    sep_crypto_axi_isolate_unit #(
        .ADDR_WIDTH  (ADDR_WIDTH),
        .DATA_WIDTH  (DATA_WIDTH),
        .ID_WIDTH    (ID_WIDTH),
        .USER_WIDTH  (USER_WIDTH),
        .NUM_PENDING (NUM_PENDING),
        .axi_req_t   (axi_req_t),
        .axi_resp_t  (axi_resp_t)
    ) u_hmac_iso (
        .clk_i         (clk_i),
        .rst_ni        (rst_ni),
        .sw_rst_req_ni (hmac_sw_rst_req_ni),
        .slv_req_i     (hmac_slv_req_i),
        .slv_resp_o    (hmac_slv_resp_o),
        .mst_req_o     (hmac_mst_req_o),
        .mst_resp_i    (hmac_mst_resp_i),
        .gated_rst_no  (hmac_gated_rst_no)
    );

    sep_crypto_axi_isolate_unit #(
        .ADDR_WIDTH  (ADDR_WIDTH),
        .DATA_WIDTH  (DATA_WIDTH),
        .ID_WIDTH    (ID_WIDTH),
        .USER_WIDTH  (USER_WIDTH),
        .NUM_PENDING (NUM_PENDING),
        .axi_req_t   (axi_req_t),
        .axi_resp_t  (axi_resp_t)
    ) u_otbn_iso (
        .clk_i         (clk_i),
        .rst_ni        (rst_ni),
        .sw_rst_req_ni (otbn_sw_rst_req_ni),
        .slv_req_i     (otbn_slv_req_i),
        .slv_resp_o    (otbn_slv_resp_o),
        .mst_req_o     (otbn_mst_req_o),
        .mst_resp_i    (otbn_mst_resp_i),
        .gated_rst_no  (otbn_gated_rst_no)
    );

    sep_crypto_axi_isolate_unit #(
        .ADDR_WIDTH  (ADDR_WIDTH),
        .DATA_WIDTH  (DATA_WIDTH),
        .ID_WIDTH    (ID_WIDTH),
        .USER_WIDTH  (USER_WIDTH),
        .NUM_PENDING (NUM_PENDING),
        .axi_req_t   (axi_req_t),
        .axi_resp_t  (axi_resp_t)
    ) u_aes_iso (
        .clk_i         (clk_i),
        .rst_ni        (rst_ni),
        .sw_rst_req_ni (aes_sw_rst_req_ni),
        .slv_req_i     (aes_slv_req_i),
        .slv_resp_o    (aes_slv_resp_o),
        .mst_req_o     (aes_mst_req_o),
        .mst_resp_i    (aes_mst_resp_i),
        .gated_rst_no  (aes_gated_rst_no)
    );

    sep_crypto_axi_isolate_unit #(
        .ADDR_WIDTH  (ADDR_WIDTH),
        .DATA_WIDTH  (DATA_WIDTH),
        .ID_WIDTH    (ID_WIDTH),
        .USER_WIDTH  (USER_WIDTH),
        .NUM_PENDING (NUM_PENDING),
        .axi_req_t   (axi_req_t),
        .axi_resp_t  (axi_resp_t)
    ) u_kmac_iso (
        .clk_i         (clk_i),
        .rst_ni        (rst_ni),
        .sw_rst_req_ni (kmac_sw_rst_req_ni),
        .slv_req_i     (kmac_slv_req_i),
        .slv_resp_o    (kmac_slv_resp_o),
        .mst_req_o     (kmac_mst_req_o),
        .mst_resp_i    (kmac_mst_resp_i),
        .gated_rst_no  (kmac_gated_rst_no)
    );

endmodule
