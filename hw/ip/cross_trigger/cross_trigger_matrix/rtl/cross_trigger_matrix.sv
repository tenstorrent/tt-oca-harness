
// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Copyright 2025 Tenstorrent Inc.
// Cross Trigger Matrix Top Module
//
// Description:
// Top-level module for the Cross Trigger Matrix IP. Provides a configurable
// crossbar to route cross trigger pulses between M source ports (CT_Dst) and
// N sink ports (CT_Src). Each CT_Src can be configured to select and OR together
// multiple CT_Dst sources.
//
// The port counts follow the register map: NUM_CT_SRC must equal the number of
// config registers declared by regs/cross_trigger_matrix.rdl, and NUM_CT_DST is
// bounded by the width of their select field. Resize the matrix by changing
// NUM_CT_SRC in that RDL and regenerating, rather than by editing this module.
//------------------------------------------------------------------------------


module cross_trigger_matrix #(
    // Number of CT_Src output ports (must equal the number of config registers)
    parameter int unsigned NUM_CT_SRC = 26,
    // Number of CT_Dst input ports (up to the select field width)
    parameter int unsigned NUM_CT_DST = 26,
    // Parameterized AXI-Lite bus interface types (default logic to force explicit definition)
    parameter type axil_req_t = cross_trigger_matrix_pkg::ctm_axil_req_t,
    parameter type axil_resp_t = cross_trigger_matrix_pkg::ctm_axil_resp_t
) (
    // Global Interface
    input  logic                    clk_i,
    input  logic                    rst_ni,

    // AXI4-Lite Register Interface
    input  axil_req_t               axil_req_i,
    output axil_resp_t              axil_resp_o,

    // Cross trigger destination inputs (sources for the matrix)
    input  logic [NUM_CT_DST-1:0]   ct_dst_i,

    // Cross trigger source outputs (sinks for the matrix)
    output logic [NUM_CT_SRC-1:0]   ct_src_o
);

    `include "prim_assert.sv"

    import cross_trigger_matrix_reg_pkg::*;
    import cross_trigger_matrix_pkg::*;

    // Register interface (no hwif_in needed - all registers are write-only from software)
    cross_trigger_matrix_reg_pkg::cross_trigger_matrix__out_t reg_out;

    // The register map provides one config register per CT_Src port and a select
    // bit per CT_Dst port, so both dimensions are bounded by what it declares.
    localparam int unsigned NUM_CT_SRC_REGS =
        cross_trigger_matrix_addrmap_pkg::CROSS_TRIGGER_MATRIX_CT_SRC_NUM;
    localparam int unsigned CT_DST_SELECT_WIDTH =
        $bits(reg_out.CT_SRC[0].CONFIG_0.CT_DST_SELECT.value);

    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumCtSrcMatchesRegs_A, NUM_CT_SRC == NUM_CT_SRC_REGS)
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumCtDstInRange_A,
                              NUM_CT_DST >= MIN_NUM_CT_DST && NUM_CT_DST <= CT_DST_SELECT_WIDTH)

    // Register module instantiation - wire AXI-Lite structs directly
    cross_trigger_matrix_reg u_reg (
        .clk           (clk_i),
        .arst_n        (rst_ni),

        // Write address channel
        .s_axil_awready (axil_resp_o.aw_ready),
        .s_axil_awvalid (axil_req_i.aw_valid),
        .s_axil_awaddr  (axil_req_i.aw.addr[7:0]),
        .s_axil_awprot  (axil_req_i.aw.prot),

        // Write data channel
        .s_axil_wready  (axil_resp_o.w_ready),
        .s_axil_wvalid  (axil_req_i.w_valid),
        .s_axil_wdata   (axil_req_i.w.data),
        .s_axil_wstrb   (axil_req_i.w.strb),

        // Write response channel
        .s_axil_bready  (axil_req_i.b_ready),
        .s_axil_bvalid  (axil_resp_o.b_valid),
        .s_axil_bresp   (axil_resp_o.b.resp),

        // Read address channel
        .s_axil_arready (axil_resp_o.ar_ready),
        .s_axil_arvalid (axil_req_i.ar_valid),
        .s_axil_araddr  (axil_req_i.ar.addr[7:0]),
        .s_axil_arprot  (axil_req_i.ar.prot),

        // Read data channel
        .s_axil_rready  (axil_req_i.r_ready),
        .s_axil_rvalid  (axil_resp_o.r_valid),
        .s_axil_rdata   (axil_resp_o.r.data),
        .s_axil_rresp   (axil_resp_o.r.resp),

        .hwif_out      (reg_out)
    );

    // Generate selector modules for each CT_Src port
    genvar i;
    generate
        for (i = 0; i < NUM_CT_SRC; i++) begin : gen_src_selectors
            // Extract the CT_DST_SELECT field for this CT_Src
            // Only use the bits corresponding to NUM_CT_DST
            logic [NUM_CT_DST-1:0] select_mask;

            // One config register per CT_Src port, indexed by the loop
            assign select_mask =
                reg_out.CT_SRC[i].CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];

            // Instantiate selector module for this CT_Src
            ctm_src_selector #(
                .NUM_CT_DST (NUM_CT_DST)
            ) u_src_selector (
                .clk_i      (clk_i),
                .rst_ni     (rst_ni),
                .ct_dst_i   (ct_dst_i),
                .select_i   (select_mask),
                .ct_src_o   (ct_src_o[i])
            );
        end
    endgenerate

endmodule : cross_trigger_matrix
