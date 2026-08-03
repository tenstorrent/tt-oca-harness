// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP Crypto AXI Isolate Unit
//
// Single-port isolation unit: axi_isolate plus the reset sequencing FSM for
// one accelerator port. On a software reset request, isolates the AXI port
// (drains in-flight transactions, terminates new ones with DECERR), then
// asserts the wrapper reset.

`include "prim_assert.sv"

module sep_crypto_axi_isolate_unit
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
    // Software reset request (active low), from sep_reset_ctrl
    input  logic      sw_rst_req_ni,

    // Slave port (from sep_crypto demux)
    input  axi_req_t  slv_req_i,
    output axi_resp_t slv_resp_o,
    // Master port (to accelerator wrapper)
    output axi_req_t  mst_req_o,
    input  axi_resp_t mst_resp_i,

    // Sequenced reset to the accelerator wrapper (active low)
    output logic      gated_rst_no
);

    typedef enum logic [1:0] {
        StReset,    // wrapper in reset, port isolated
        StDrain,    // isolation requested, waiting for in-flight drain
        StRun       // normal operation
    } isolate_state_e;

    isolate_state_e state_q, state_d;
    logic isolate_req, isolated;
    logic gated_rst_d, gated_rst_q;

    always_comb begin
        state_d = state_q;

        unique case (state_q)
            StRun: begin
                if (~sw_rst_req_ni) begin
                    state_d = StDrain;
                end
            end
            StDrain: begin
                if (isolated) begin
                    state_d = StReset;
                end
            end
            StReset: begin
                if (sw_rst_req_ni) begin
                    state_d = StRun;
                end
            end
            default: state_d = StReset;
        endcase
    end

    assign isolate_req = (state_q != StRun);
    assign gated_rst_d = (state_d == StReset);

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            state_q <= StReset;
        end else begin
            state_q <= state_d;
        end
    end

    // Flopped so the wrapper reset only makes clean, clock-aligned transitions.
    // Reset value 1 = wrapper reset asserted while rst_ni is asserted.
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            gated_rst_q <= 1'b1;
        end else begin
            gated_rst_q <= gated_rst_d;
        end
    end

    assign gated_rst_no = ~gated_rst_q;

    axi_isolate #(
        .NumPending           (NUM_PENDING),
        .TerminateTransaction (1'b1),
        .AtopSupport          (1'b0),
        .AxiAddrWidth         (ADDR_WIDTH),
        .AxiDataWidth         (DATA_WIDTH),
        .AxiIdWidth           (ID_WIDTH),
        .AxiUserWidth         (USER_WIDTH),
        .axi_req_t            (axi_req_t),
        .axi_resp_t           (axi_resp_t)
    ) u_axi_isolate (
        .clk_i      (clk_i),
        .rst_ni     (rst_ni),
        .slv_req_i  (slv_req_i),
        .slv_resp_o (slv_resp_o),
        .mst_req_o  (mst_req_o),
        .mst_resp_i (mst_resp_i),
        .isolate_i  (isolate_req),
        .isolated_o (isolated)
    );

    // The wrapper reset must never assert while the port is still open
    `OCAH_OT_ASSERT(ResetOnlyWhenIsolated_A, !gated_rst_no |-> isolated, clk_i, !rst_ni)

    // Isolation must be held for the entire duration of the wrapper reset
    `OCAH_OT_ASSERT(IsolateHeldThroughReset_A, !gated_rst_no |-> isolate_req, clk_i, !rst_ni)

endmodule
