// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// Efuse Security Tokens
//
//-----------------------------------------------------------------------------


module efuse_security_tokens
#(
    parameter bit [255:0] SEP_SEC_DISABLE_TOKEN = 256'b0,
    parameter logic [5:0] TOKEN_MATCH_CODE = 6'b010101,

    parameter int unsigned LC_STATE_WIDTH = 4,
    localparam logic [2*LC_STATE_WIDTH-1:0] LC_STATE_INVALID = (2*LC_STATE_WIDTH)'({{LC_STATE_WIDTH{1'b0}}, {LC_STATE_WIDTH{1'b1}}}),


    parameter type efuse_apb_req_t = logic,
    parameter type efuse_apb_resp_t = logic,

    parameter type efuse_map_t = logic,

    localparam logic[1:0] SHA256_PASS = 2'b01,
    localparam logic[1:0] SHA256_FAIL = 2'b10
) (
    input  logic                     clk_i,
    input  logic                     rst_ni,

    input  logic                     fuse_sense_done_i,

    input  logic                     secure_tm_i,

    input  efuse_apb_req_t           apb_req_i,
    output efuse_apb_resp_t          apb_resp_o,

    output logic[5:0]                rma_sip_token_match_q_o,
    output logic[5:0]                rma_chiplet_token_match_q_o,

    output logic [7:0][31:0]         sec_disable_token_o,

    output logic                     security_disable_o,

    input  efuse_map_t               shadow_regs_i,
    output efuse_map_t               shadow_regs_o
);

    ///////////////////////////////////////////////
    // Efuse MMR CSR - SEP Only
    ///////////////////////////////////////////////

    efuse_mmr_reg_pkg::efuse_mmr__in_t mmr_hwif_in;
    efuse_mmr_reg_pkg::efuse_mmr__out_t mmr_hwif_out;
    logic rma_sip_token_go, rma_chiplet_token_go, secure_disable_token_go;
    logic [5:0] rma_sip_token_match, rma_chiplet_token_match, sec_disable_token_match;
    logic [5:0] rma_sip_token_match_q_n0_scan, rma_chiplet_token_match_q_n0_scan, sec_disable_token_match_q_n0_scan;

    logic [7:0][31:0] sip_rma_token_raw, chiplet_rma_token_raw, sec_disable_token_raw;
    logic [7:0][31:0] sip_rma_token, chiplet_rma_token, sec_disable_token;

    logic [255:0] rma_sip_token_sha256_digest, rma_chiplet_token_sha256_digest, sec_disable_token_sha256_digest_sticky;
    // Sticky valid bits for the RMA tokens and SEC_DISABLE token
    logic rma_sip_token_digest_vld_sticky_raw, rma_chiplet_token_digest_vld_sticky_raw, sec_disable_token_digest_vld_sticky_raw;
    logic rma_sip_token_digest_vld_sticky, rma_chiplet_token_digest_vld_sticky, sec_disable_token_digest_vld_sticky;
    logic compute_rma_sip_token_match, compute_rma_chiplet_token_match;

    // Note: the APB read back path does not flop read only registers
    efuse_mmr_reg u_efuse_mmr_reg (
        .clk           (clk_i),
        .arst_n        (rst_ni),

        .s_apb_psel    (apb_req_i.psel),
        .s_apb_penable (apb_req_i.penable),
        .s_apb_pwrite  (apb_req_i.pwrite),
        .s_apb_pprot   (apb_req_i.pprot),
        .s_apb_paddr   (apb_req_i.paddr[6:0]),
        .s_apb_pwdata  (apb_req_i.pwdata),
        .s_apb_pstrb   (apb_req_i.pstrb),
        .s_apb_pready  (apb_resp_o.pready),
        .s_apb_prdata  (apb_resp_o.prdata),
        .s_apb_pslverr (apb_resp_o.pslverr),

        // SEC Disable Tokens, RMA Chiplet Tokens, RMA SiP Tokens
        .hwif_in       (mmr_hwif_in),
        .hwif_out      (mmr_hwif_out)
    );

    assign mmr_hwif_in.RMA_SIP_TOKEN_MATCH.token_match_status.next = rma_sip_token_match_q_n0_scan;
    assign mmr_hwif_in.RMA_CHIPLET_TOKEN_MATCH.token_match_status.next = rma_chiplet_token_match_q_n0_scan;
    assign mmr_hwif_in.SEC_DISABLE_TOKEN_MATCH.token_match_status.next = sec_disable_token_match_q_n0_scan;

    always_comb begin
        for (int i = 0; i < 8; i++) begin
            sip_rma_token_raw[i] = mmr_hwif_out.RMA_SIP_TOKEN_I[i].token.value;
            chiplet_rma_token_raw[i] = mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].token.value;
            sec_disable_token_raw[i] = mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].token.value;
        end
        rma_sip_token_go = mmr_hwif_out.TOKEN_EOP.rma_sip_token_go.value;
        rma_chiplet_token_go = mmr_hwif_out.TOKEN_EOP.rma_chiplet_token_go.value;
        secure_disable_token_go = mmr_hwif_out.TOKEN_EOP.secure_disable_token_go.value;
    end

    /////////////////////////////// SHA256 HASHING ENGINES ///////////////////////////////
    // A single `*_go` pulse from the CSR triggers the hashing engine.
    sha256_token_hash u_sha256_rma_sip_token (
        .clk_i               (clk_i),
        .rst_ni              (rst_ni),
        .start_i             (rma_sip_token_go),
        .token_i             (sip_rma_token),
        .digest_vld_sticky_o (rma_sip_token_digest_vld_sticky_raw),
        .sha_digest_sticky_o (rma_sip_token_sha256_digest)
    );

    sha256_token_hash u_sha256_rma_chiplet_token (
        .clk_i               (clk_i),
        .rst_ni              (rst_ni),
        .start_i             (rma_chiplet_token_go),
        .token_i             (chiplet_rma_token),
        .digest_vld_sticky_o (rma_chiplet_token_digest_vld_sticky_raw),
        .sha_digest_sticky_o (rma_chiplet_token_sha256_digest)
    );

    sha256_token_hash u_sha256_sec_disable_token (
        .clk_i               (clk_i),
        .rst_ni              (rst_ni),
        .start_i             (secure_disable_token_go),
        .token_i             (sec_disable_token),
        .digest_vld_sticky_o (sec_disable_token_digest_vld_sticky_raw),
        .sha_digest_sticky_o (sec_disable_token_sha256_digest_sticky)
    );

    /////////////////////////////// TRIPLE-REDUNDANT MATCHING LOGIC ///////////////////////////////
    assign compute_rma_sip_token_match = rma_sip_token_digest_vld_sticky && fuse_sense_done_i;
    assign compute_rma_chiplet_token_match = rma_chiplet_token_digest_vld_sticky && fuse_sense_done_i;

    triple_redundent_comparator #(
        .HASH_PASS(SHA256_PASS),
        .HASH_FAIL(SHA256_FAIL),
        .DATA_WIDTH(256)
    ) u_triple_redundent_comparator_rma_sip_token (
        .compute_comparison_vld_i(compute_rma_sip_token_match),
        .token_digest_i(rma_sip_token_sha256_digest),
        .token_expected_i(shadow_regs_i.f.rma_sip_token_digest.token_digest),
        .token_match_o(rma_sip_token_match)
    );

    triple_redundent_comparator #(
        .HASH_PASS(SHA256_PASS),
        .HASH_FAIL(SHA256_FAIL),
        .DATA_WIDTH(256)
    ) u_triple_redundent_comparator_rma_chiplet_token (
        .compute_comparison_vld_i(compute_rma_chiplet_token_match),
        .token_digest_i(rma_chiplet_token_sha256_digest),
        .token_expected_i(shadow_regs_i.f.rma_chiplet_token_digest.token_digest),
        .token_match_o(rma_chiplet_token_match)
    );

    triple_redundent_comparator #(
        .HASH_PASS(SHA256_PASS),
        .HASH_FAIL(SHA256_FAIL),
        .DATA_WIDTH(256)
    ) u_triple_redundent_comparator_sec_disable_token (
        // Do not need to wait for fuse sense done because SEP_SEC_DISABLE_TOKEN is a constant 
        .compute_comparison_vld_i(sec_disable_token_digest_vld_sticky),
        .token_digest_i(sec_disable_token_sha256_digest_sticky),
        .token_expected_i(SEP_SEC_DISABLE_TOKEN),
        .token_match_o(sec_disable_token_match)
    );

    // Flop the match results to the output ports, helps with timing closure and prevents glitches on the output ports
    always_ff @(posedge clk_i) begin
        if (~rst_ni) begin
            rma_sip_token_match_q_n0_scan <= '0;
            rma_chiplet_token_match_q_n0_scan <= '0;
            sec_disable_token_match_q_n0_scan <= '0;
        end else begin
            rma_sip_token_match_q_n0_scan <= rma_sip_token_match;
            rma_chiplet_token_match_q_n0_scan <= rma_chiplet_token_match;
            sec_disable_token_match_q_n0_scan <= sec_disable_token_match;
        end
    end

    /////////////////////
    // Security Disable
    /////////////////////

    logic final_sec_disable;
    logic [7:0] tt_rev_d_out;
    // Disable sec_disable_feature during A2/B1
    logic [7:0] low, high;

    prim_rev_cell sep_sec_disable(
        .LO(low[7:0]),
        .HI(high[7:0]),
        .IN({low[7],low[6], low[5], low[4], low[3], low[2], low[1], high[0]}),
        .OUT(tt_rev_d_out[7:0]),
        .SRC_LOW(1'b0),
        .SRC_HIGH(1'b1)
    );

    assign final_sec_disable = tt_rev_d_out[0] && (sec_disable_token_match == TOKEN_MATCH_CODE);
    assign security_disable_o = final_sec_disable;

    always_comb begin
        // Default: zero the output and set LC state to invalid
        shadow_regs_o = efuse_map_t'(0);
        shadow_regs_o.f.lc_state.lc_state = LC_STATE_INVALID;

        // Gaurd shadow registers from being exposed downstream until fuse sensing is complete, 
        // Unless we are in security disable mode, then expose the shadow registers downstream.
        if (fuse_sense_done_i || final_sec_disable) begin
            shadow_regs_o = shadow_regs_i;
        end

        // If secure test mode: disconnect RMA tokens to prevent exposure
        if (secure_tm_i) begin
            shadow_regs_o.f.rma_sip_token_digest.token_digest = 256'h0;
            shadow_regs_o.f.rma_chiplet_token_digest.token_digest = 256'h0;
        end
    end

    assign rma_sip_token_match_q_o = rma_sip_token_match_q_n0_scan;
    assign rma_chiplet_token_match_q_o = rma_chiplet_token_match_q_n0_scan;

    // TODO: Probably remove? Expose sec_disable_token for test access
    assign sec_disable_token_o = sec_disable_token;


    ///////////////////////////////////////////////////////
    // Simulation handling: no-reset elements power up as X
    ///////////////////////////////////////////////////////

    `ifdef SIM
        initial begin
            $display("[INFO] Initialize the tokens and token digest valid bits for simulation. They don't have a reset value.");
        end
        always_comb begin
            for (int i = 0; i< 8 ; i++) begin
                if (sip_rma_token_raw[i] === 32'bXXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX) begin
                    sip_rma_token[i] = 32'b0;
                end
                else begin
                    sip_rma_token[i] = sip_rma_token_raw[i];
                end
                if (chiplet_rma_token_raw[i] === 32'bXXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX) begin
                    chiplet_rma_token[i] = 32'b0;
                end
                else begin
                    chiplet_rma_token[i] = chiplet_rma_token_raw[i];
                end
                if (sec_disable_token_raw[i] === 32'bXXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX) begin
                    sec_disable_token[i] = 32'b0;
                end
                else begin
                    sec_disable_token[i] = sec_disable_token_raw[i];
                end
            end

            if (sec_disable_token_digest_vld_sticky_raw === 1'bX) begin
                sec_disable_token_digest_vld_sticky = 1'b0;
            end
            else begin
                sec_disable_token_digest_vld_sticky = sec_disable_token_digest_vld_sticky_raw;
            end
            if (rma_sip_token_digest_vld_sticky_raw === 1'bX) begin
                rma_sip_token_digest_vld_sticky = 1'b0;
            end
            else begin
                rma_sip_token_digest_vld_sticky = rma_sip_token_digest_vld_sticky_raw;
            end
            if (rma_chiplet_token_digest_vld_sticky_raw === 1'bX) begin
                rma_chiplet_token_digest_vld_sticky = 1'b0;
            end
            else begin
                rma_chiplet_token_digest_vld_sticky = rma_chiplet_token_digest_vld_sticky_raw;
            end
        end
    `else
        always_comb begin
            for (int i = 0; i< 8 ; i++) begin
                sip_rma_token[i] = sip_rma_token_raw[i];
                chiplet_rma_token[i] = chiplet_rma_token_raw[i];
                sec_disable_token[i] = sec_disable_token_raw[i];
            end
            sec_disable_token_digest_vld_sticky = sec_disable_token_digest_vld_sticky_raw;
            rma_sip_token_digest_vld_sticky = rma_sip_token_digest_vld_sticky_raw;
            rma_chiplet_token_digest_vld_sticky = rma_chiplet_token_digest_vld_sticky_raw;
        end
    `endif

endmodule : efuse_security_tokens
