// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Mux NUM_MASTERS struct-typed APB slave ports onto one master port.
//
// Select one requesting slave and steer the master response back to it.
// req_t and resp_t set the APB request and response struct shapes.
// With NUM_MASTERS equal to one, pass the structs straight through.

module prim_apb_mux_struct #(
    parameter int unsigned NUM_MASTERS = 2,  // Number of APB slave ports into the mux.
    parameter type req_t  = logic,  // APB request struct type.
    parameter type resp_t = logic,  // APB response struct type.

    localparam int unsigned ADDR_WIDTH = $bits(req_t'(0).paddr),  // Address width derived from req_t.
    localparam int unsigned DATA_WIDTH = $bits(req_t'(0).pwdata),  // Data width derived from req_t.
    localparam int unsigned STRB_WIDTH = $bits(req_t'(0).pstrb),  // Strobe width derived from req_t.
    localparam type addr_t = logic [ADDR_WIDTH-1:0],  // Address type alias.
    localparam type data_t = logic [DATA_WIDTH-1:0],  // Data type alias.
    localparam type strb_t = logic [STRB_WIDTH-1:0]  // Strobe type alias.
) (
    input  logic                    clk_i,  // APB clock.
    input  logic                    rst_ni,  // Async reset, active-low.

    input  req_t  [NUM_MASTERS-1:0] slv_req_i,  // Per-slave APB requests.
    output resp_t [NUM_MASTERS-1:0] slv_resp_o,  // Per-slave APB responses.

    output req_t                    mst_req_o,  // Muxed APB request toward the bus.
    input  resp_t                   mst_resp_i  // APB response from the bus.
);

    /////////////////
    // Definitions //
    /////////////////

    typedef struct packed {
        addr_t          paddr;
        apb_pkg::prot_t pprot;
        logic           pwrite;
        data_t          pwdata;
        strb_t          pstrb;
    } apb_req_t;

    typedef enum logic {
        ST_IDLE   = 1'd0,
        ST_ACCESS = 1'd1
    } fsm_state_t;


    ///////////////
    // Mux Logic //
    ///////////////

    if (NUM_MASTERS == 1) begin : gen_apb_passthrough

        assign mst_req_o = slv_req_i[0];
        assign slv_resp_o[0] = mst_resp_i;

    end else begin : gen_apb_mux

        /////////////////////////
        // Signal Declarations //
        /////////////////////////

        logic             [NUM_MASTERS-1:0] arb_valids;
        logic             [NUM_MASTERS-1:0] arb_readies;
        apb_req_payload_t [NUM_MASTERS-1:0] arb_data_in;

        logic             arb_valid;
        apb_req_payload_t arb_data_out;


        /////////////
        // Arbiter //
        /////////////

        always_comb begin
            for (int i = 0; i < NUM_MASTERS; i++) begin : gen_request_packaging
                arb_valids[i] = slv_req_i[i].psel;
                arb_data_in[i].paddr  = slv_req_i[i].paddr;
                arb_data_in[i].pprot  = slv_req_i[i].pprot;
                arb_data_in[i].pwrite = slv_req_i[i].pwrite;
                arb_data_in[i].pwdata = slv_req_i[i].pwdata;
                arb_data_in[i].pstrb  = slv_req_i[i].pstrb;

                slv_resp_o[i].pready = arb_readies[i];
                slv_resp_o[i].prdata  = mst_resp_i.prdata;  // Broadcast
                slv_resp_o[i].pslverr = mst_resp_i.pslverr; // Broadcast
            end
        end

        stream_arbiter #(
            .DATA_T      (apb_req_payload_t),
            .N_INP       (NUM_MASTERS)
        ) u_stream_arbiter (
            .clk_i,
            .rst_ni,
            .inp_data_i  (arb_data_in),
            .inp_valid_i (arb_valids),
            .inp_ready_o (arb_readies),
            .oup_data_o  (arb_data_out),
            .oup_valid_o (arb_valid),
            .oup_ready_i (mst_resp_i.pready)
        );


        /////////
        // FSM //
        /////////

        fsm_state_t fsm_state, fsm_state_next;

        always_comb begin
            mst_req_o.psel    = 1'b0;
            mst_req_o.penable = 1'b0;
            mst_req_o.paddr  = arb_data_out.paddr;
            mst_req_o.pprot  = arb_data_out.pprot;
            mst_req_o.pwrite = arb_data_out.pwrite;
            mst_req_o.pwdata = arb_data_out.pwdata;
            mst_req_o.pstrb  = arb_data_out.pstrb;

            fsm_state_next = fsm_state;

            case (fsm_state)
                ST_IDLE: begin
                    if (arb_valid) begin
                        mst_req_o.psel = 1'b1;

                        fsm_state_next = ST_ACCESS;
                    end
                end
                ST_ACCESS: begin
                    mst_req_o.psel    = 1'b1;
                    mst_req_o.penable = 1'b1;

                    if (mst_resp_i.pready) begin
                        fsm_state_next = ST_IDLE;
                    end
                end
                default: begin
                    fsm_state_next = ST_IDLE;
                end
            endcase
        end

        always_ff @(posedge clk_i or negedge rst_ni) begin
            if (~rst_ni) begin
                fsm_state <= ST_IDLE;
            end else begin
                fsm_state <= fsm_state_next;
            end
        end

    end

endmodule
