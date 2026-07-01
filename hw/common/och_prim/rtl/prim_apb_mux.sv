// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// APB Multiplexer
//
//--------------------------------------------------

module prim_apb_mux #(
    // Interface configuration parameters
    parameter int unsigned NUM_MASTERS = 2,
    parameter int unsigned ADDR_WIDTH  = 32,
    parameter int unsigned DATA_WIDTH  = 32,

    // Derived parameters
    localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8,
    localparam type addr_t = logic [ADDR_WIDTH-1:0],
    localparam type data_t = logic [DATA_WIDTH-1:0],
    localparam type strb_t = logic [STRB_WIDTH-1:0]
) (
    // Global Interface
    input  logic                          clk_i,
    input  logic                          rst_ni,

    // APB master interfaces (inputs from multiple masters)
    input  logic [NUM_MASTERS-1:0]        mst_psel_i,
    input  logic [NUM_MASTERS-1:0]        mst_penable_i,
    input  addr_t [NUM_MASTERS-1:0]       mst_paddr_i,
    input  data_t [NUM_MASTERS-1:0]       mst_pwdata_i,
    input  strb_t [NUM_MASTERS-1:0]       mst_pstrb_i,
    input  logic [NUM_MASTERS-1:0]        mst_pwrite_i,
    input  apb_pkg::prot_t [NUM_MASTERS-1:0] mst_pprot_i,
    output logic [NUM_MASTERS-1:0]        mst_pready_o,
    output data_t [NUM_MASTERS-1:0]       mst_prdata_o,
    output logic [NUM_MASTERS-1:0]        mst_pslverr_o,

    // APB slave interface (output to single slave)
    output logic                          slv_psel_o,
    output logic                          slv_penable_o,
    output addr_t                         slv_paddr_o,
    output data_t                         slv_pwdata_o,
    output strb_t                         slv_pstrb_o,
    output apb_pkg::prot_t                slv_pprot_o,
    output logic                          slv_pwrite_o,
    input  logic                          slv_pready_i,
    input  data_t                         slv_prdata_i,
    input  logic                          slv_pslverr_i
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


    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    logic single_psel;


    ///////////////
    // Mux Logic //
    ///////////////


    if (NUM_MASTERS == 1) begin : gen_single_master
        // Direct connection for single master case
        assign slv_penable_o = mst_penable_i[0];
        assign slv_psel_o    = mst_psel_i[0];
        assign slv_paddr_o   = mst_paddr_i[0];
        assign slv_pwdata_o  = mst_pwdata_i[0];
        assign slv_pstrb_o   = mst_pstrb_i[0];
        assign slv_pwrite_o  = mst_pwrite_i[0];
        assign slv_pprot_o   = mst_pprot_i[0];

        assign mst_pready_o[0]  = slv_pready_i;
        assign mst_prdata_o[0]  = slv_prdata_i;
        assign mst_pslverr_o[0] = slv_pslverr_i;
    end else begin : gen_multiple_masters

        apb_req_t [NUM_MASTERS-1:0] master_reqs;
        logic [NUM_MASTERS-1:0]     master_valid;
        logic [NUM_MASTERS-1:0]     master_ready;
        apb_req_t                   arbiter_payload;
        logic                       arbiter_valid;

        // Package master requests into structures
        for (genvar i = 0; i < NUM_MASTERS; i++) begin : gen_request_packaging
            assign master_reqs[i].paddr  = mst_paddr_i[i];
            assign master_reqs[i].pprot  = mst_pprot_i[i];
            assign master_reqs[i].pwrite = mst_pwrite_i[i];
            assign master_reqs[i].pwdata = mst_pwdata_i[i];
            assign master_reqs[i].pstrb  = mst_pstrb_i[i];

            // Valid when psel is asserted (APB spec: psel indicates transaction)
            assign master_valid[i] = mst_psel_i[i];

            // Response routing - broadcast to all masters
            assign mst_pslverr_o[i] = slv_pslverr_i;
            assign mst_prdata_o[i]  = slv_prdata_i;
            assign mst_pready_o[i]  = master_ready[i];
        end

        // TODO: replace with prim_arbiter_tree
        // Stream arbiter for APB request arbitration
        stream_arbiter #(
            .DATA_T (apb_req_t),
            .N_INP  (NUM_MASTERS)
        ) u_stream_arbiter (
            .clk_i       (clk_i),
            .rst_ni      (rst_ni),
            .inp_data_i  (master_reqs),
            .inp_valid_i (master_valid),
            .inp_ready_o (master_ready),
            .oup_data_o  (arbiter_payload),
            .oup_valid_o (arbiter_valid),
            .oup_ready_i (slv_pready_i)
        );

        // Check for single master selection (no conflicts)
        assign single_psel = ((mst_psel_i & (mst_psel_i - 1'b1)) == '0);

        // APB slave interface assignments
        assign slv_psel_o    = arbiter_valid;
        assign slv_penable_o = arbiter_valid & (|mst_penable_i);
        assign slv_paddr_o   = arbiter_payload.paddr;
        assign slv_pprot_o   = arbiter_payload.pprot;
        assign slv_pwrite_o  = arbiter_payload.pwrite;
        assign slv_pwdata_o  = arbiter_payload.pwdata;
        assign slv_pstrb_o   = arbiter_payload.pstrb;

    end

endmodule
