
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
// Committed source, configured for NUM_CT_SRC = 26, NUM_CT_DST = 26. Upstream
// expanded this module from a template; that generator was not carried into
// this tree, so the per-source select decode below is edited by hand and must
// stay in step with the registers in regs/cross_trigger_matrix.rdl.
//------------------------------------------------------------------------------


module cross_trigger_matrix #(
    // Number of CT_Src output ports (must match generated registers)
    parameter int unsigned NUM_CT_SRC = 26,
    // Number of CT_Dst input ports (1-64)
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

    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumCtSrcMatchesGen_A, NUM_CT_SRC == 26)
    `OCAH_OT_ASSERT_STATIC_LINT_ERROR(NumCtDstInRange_A,
                              NUM_CT_DST >= MIN_NUM_CT_DST && NUM_CT_DST <= MAX_NUM_CT_DST)

    // Register interface (no hwif_in needed - all registers are write-only from software)
    cross_trigger_matrix_reg_pkg::cross_trigger_matrix__out_t reg_out;

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

            // Map register fields to select mask (combine CONFIG_0 and CONFIG_1)
            // CONFIG_0 handles CT_Dst[31:0], CONFIG_1 handles CT_Dst[63:32]
            always_comb begin
                if (i == 0) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC0_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 1) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC1_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 2) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC2_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 3) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC3_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 4) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC4_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 5) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC5_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 6) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC6_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 7) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC7_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 8) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC8_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 9) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC9_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 10) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC10_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 11) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC11_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 12) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC12_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 13) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC13_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 14) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC14_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 15) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC15_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 16) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC16_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 17) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC17_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 18) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC18_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 19) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC19_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 20) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC20_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 21) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC21_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 22) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC22_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 23) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC23_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 24) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC24_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else if (i == 25) begin
                    // Only CONFIG_0 needed for <= 32 ports
                    select_mask = reg_out.CT_SRC25_CONFIG_0.CT_DST_SELECT.value[NUM_CT_DST-1:0];
                end
                else begin
                    select_mask = '0;
                end
            end

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
