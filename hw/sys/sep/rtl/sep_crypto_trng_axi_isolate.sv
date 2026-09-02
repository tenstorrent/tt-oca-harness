// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Coordinated AXI isolation for the internal TRNG complex.
//
// The entropy source, CSRNG, and EDN have independent AXI apertures but share
// one functional reset domain. A software reset request therefore isolates all
// three ports, waits until every accepted transaction has drained, and only
// then asserts the common TRNG reset.

`include "prim_assert.sv"

module sep_crypto_trng_axi_isolate #(
  parameter int unsigned ADDR_WIDTH  = 32,
  parameter int unsigned DATA_WIDTH  = 64,
  parameter int unsigned ID_WIDTH    = 6,
  parameter int unsigned USER_WIDTH  = 12,
  parameter int unsigned NUM_PENDING = 4,
  parameter type axi_req_t  = logic,
  parameter type axi_resp_t = logic
) (
  input logic clk_i,
  input logic rst_ni,

  // Active-low reset request from sep_reset_ctrl.
  input logic trng_sw_rst_req_ni,

  input  axi_req_t  esrc_slv_req_i,
  output axi_resp_t esrc_slv_resp_o,
  output axi_req_t  esrc_mst_req_o,
  input  axi_resp_t esrc_mst_resp_i,

  input  axi_req_t  csrng_slv_req_i,
  output axi_resp_t csrng_slv_resp_o,
  output axi_req_t  csrng_mst_req_o,
  input  axi_resp_t csrng_mst_resp_i,

  input  axi_req_t  edn_slv_req_i,
  output axi_resp_t edn_slv_resp_o,
  output axi_req_t  edn_mst_req_o,
  input  axi_resp_t edn_mst_resp_i,

  // Shared, active-low reset for ESRC, DRBG, and their CSR converters.
  output logic trng_gated_rst_no
);

  typedef enum logic [1:0] {
    StReset,
    StRelease,
    StRun,
    StDrain
  } isolate_state_e;

  isolate_state_e state_q, state_d;
  logic isolate_req;
  logic trng_rst_n_q, trng_rst_n_d;
  logic esrc_isolated, csrng_isolated, edn_isolated;
  logic all_isolated;
  logic any_downstream_request;

  assign all_isolated = esrc_isolated & csrng_isolated & edn_isolated;
  assign any_downstream_request =
        esrc_mst_req_o.aw_valid || esrc_mst_req_o.w_valid || esrc_mst_req_o.ar_valid ||
        csrng_mst_req_o.aw_valid || csrng_mst_req_o.w_valid || csrng_mst_req_o.ar_valid ||
        edn_mst_req_o.aw_valid || edn_mst_req_o.w_valid || edn_mst_req_o.ar_valid;

  always_comb begin
    state_d = state_q;

    unique case (state_q)
      StRun: begin
        if (!trng_sw_rst_req_ni) begin
          state_d = StDrain;
        end
      end
      StDrain: begin
        // Complete a reset even if software releases the request early.
        // This guarantees at least one clean reset cycle per request.
        if (all_isolated) begin
          state_d = StReset;
        end
      end
      StReset: begin
        if (trng_sw_rst_req_ni) begin
          state_d = StRelease;
        end
      end
      StRelease: begin
        // Give the complete TRNG domain one clock out of reset before
        // admitting a new control-plane transaction.
        state_d = StRun;
      end
      default: state_d = StReset;
    endcase
  end

  assign isolate_req  = (state_q != StRun);
  assign trng_rst_n_d = (state_d != StReset);

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= StReset;
    end else begin
      state_q <= state_d;
    end
  end

  // Flop the active-low reset so assertion and deassertion are clock-aligned
  // during a local reset. POR still asserts it asynchronously through rst_ni.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      trng_rst_n_q <= 1'b0;
    end else begin
      trng_rst_n_q <= trng_rst_n_d;
    end
  end

  assign trng_gated_rst_no = trng_rst_n_q;

  axi_isolate #(
    .NumPending          (NUM_PENDING),
    .TerminateTransaction(1'b1),
    .AtopSupport         (1'b0),
    .AxiAddrWidth        (ADDR_WIDTH),
    .AxiDataWidth        (DATA_WIDTH),
    .AxiIdWidth          (ID_WIDTH),
    .AxiUserWidth        (USER_WIDTH),
    .axi_req_t           (axi_req_t),
    .axi_resp_t          (axi_resp_t)
  ) u_esrc_axi_isolate (
    .clk_i,
    .rst_ni,
    .slv_req_i (esrc_slv_req_i),
    .slv_resp_o(esrc_slv_resp_o),
    .mst_req_o (esrc_mst_req_o),
    .mst_resp_i(esrc_mst_resp_i),
    .isolate_i (isolate_req),
    .isolated_o(esrc_isolated)
  );

  axi_isolate #(
    .NumPending          (NUM_PENDING),
    .TerminateTransaction(1'b1),
    .AtopSupport         (1'b0),
    .AxiAddrWidth        (ADDR_WIDTH),
    .AxiDataWidth        (DATA_WIDTH),
    .AxiIdWidth          (ID_WIDTH),
    .AxiUserWidth        (USER_WIDTH),
    .axi_req_t           (axi_req_t),
    .axi_resp_t          (axi_resp_t)
  ) u_csrng_axi_isolate (
    .clk_i,
    .rst_ni,
    .slv_req_i (csrng_slv_req_i),
    .slv_resp_o(csrng_slv_resp_o),
    .mst_req_o (csrng_mst_req_o),
    .mst_resp_i(csrng_mst_resp_i),
    .isolate_i (isolate_req),
    .isolated_o(csrng_isolated)
  );

  axi_isolate #(
    .NumPending          (NUM_PENDING),
    .TerminateTransaction(1'b1),
    .AtopSupport         (1'b0),
    .AxiAddrWidth        (ADDR_WIDTH),
    .AxiDataWidth        (DATA_WIDTH),
    .AxiIdWidth          (ID_WIDTH),
    .AxiUserWidth        (USER_WIDTH),
    .axi_req_t           (axi_req_t),
    .axi_resp_t          (axi_resp_t)
  ) u_edn_axi_isolate (
    .clk_i,
    .rst_ni,
    .slv_req_i (edn_slv_req_i),
    .slv_resp_o(edn_slv_resp_o),
    .mst_req_o (edn_mst_req_o),
    .mst_resp_i(edn_mst_resp_i),
    .isolate_i (isolate_req),
    .isolated_o(edn_isolated)
  );

  `OCAH_OT_ASSERT(ResetOnlyWhenAllIsolated_A, !trng_gated_rst_no |-> all_isolated, clk_i, !rst_ni)
  `OCAH_OT_ASSERT(IsolationHeldThroughReset_A, !trng_gated_rst_no |-> isolate_req, clk_i, !rst_ni)
  `OCAH_OT_ASSERT(ReleaseKeepsIsolation_A, state_q == StRelease |-> isolate_req, clk_i, !rst_ni)
  `OCAH_OT_ASSERT(NoDownstreamRequestDuringReset_A, !trng_gated_rst_no |-> !any_downstream_request,
                  clk_i, !rst_ni)

endmodule
