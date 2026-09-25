// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Efuse Token Processing
//
//-----------------------------------------------------------------------------

module efuse_token_processing #(
  parameter bit [255:0] SEP_SEC_DISABLE_TOKEN = 256'b0,
  parameter logic [5:0] TOKEN_MATCH_CODE = 6'b010101,

  parameter int unsigned LC_STATE_WIDTH = 4,
  localparam logic [2*LC_STATE_WIDTH-1:0] LC_STATE_INVALID = (2*LC_STATE_WIDTH)'({{LC_STATE_WIDTH{1'b0}}, {LC_STATE_WIDTH{1'b1}}}),

  parameter type efuse_apb_req_t = logic,
  parameter type efuse_apb_resp_t = logic,

  parameter type efuse_map_t = logic
) (
  input  logic                     clk_i,
  input  logic                     rst_ni,

  input  logic                     test_en_i,

  input  logic                     fuse_sense_done_i,

  input  efuse_apb_req_t           apb_req_i,
  output efuse_apb_resp_t          apb_resp_o,

  output logic[5:0]                rma_sip_token_match_q_o,
  output logic[5:0]                rma_chiplet_token_match_q_o,

  output logic [7:0][31:0]         sec_disable_token_o,

  output logic                     security_disable_o,

  output logic                     token_match_fault_o,

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
  logic [5:0] rma_sip_token_match_q_n0_scan;
  logic [5:0] rma_chiplet_token_match_q_n0_scan;
  logic [5:0] sec_disable_token_match_q;
  // Comparator redundancy faults, indexed {sec_disable, rma_chiplet, rma_sip}
  logic [2:0] token_match_fault;
  logic [2:0] token_match_fault_sticky_q;

  logic [7:0][31:0] sip_rma_token_raw_n0_scan;
  logic [7:0][31:0] chiplet_rma_token_raw_n0_scan;
  logic [7:0][31:0] sec_disable_token_raw_n0_scan;
  logic [7:0][31:0] sip_rma_token, chiplet_rma_token, sec_disable_token;

  logic [255:0]
      rma_sip_token_sha256_digest,
      rma_chiplet_token_sha256_digest,
      sec_disable_token_sha256_digest_sticky;
  // Sticky valid bits for the RMA tokens and SEC_DISABLE token
  logic
      rma_sip_token_digest_vld_sticky_raw,
      rma_chiplet_token_digest_vld_sticky_raw,
      sec_disable_token_digest_vld_sticky_raw;
  logic
      rma_sip_token_digest_vld_sticky,
      rma_chiplet_token_digest_vld_sticky,
      sec_disable_token_digest_vld_sticky;
  logic compute_rma_sip_token_match, compute_rma_chiplet_token_match;

  // Rev-cell reconstruction of the 256-bit secure-disable expected token
  logic [255:0] sec_disable_token_rev;
  logic [255:0] sec_disable_rev_lo;
  logic [255:0] sec_disable_rev_hi;
  logic [255:0] sec_disable_rev_in_sel;

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
  assign mmr_hwif_in.SEC_DISABLE_TOKEN_MATCH.token_match_status.next = sec_disable_token_match_q;

  assign mmr_hwif_in.TOKEN_MATCH_FAULT.rma_sip_token_fault.next = token_match_fault_sticky_q[0];
  assign mmr_hwif_in.TOKEN_MATCH_FAULT.rma_chiplet_token_fault.next = token_match_fault_sticky_q[1];
  assign mmr_hwif_in.TOKEN_MATCH_FAULT.secure_disable_token_fault.next = token_match_fault_sticky_q[2];

  // The plaintext token registers are external in the RDL so their Class 1
  // storage can be implemented explicitly at the RTL boundary.
  for (genvar i = 0; i < 8; i++) begin : gen_token_storage_n0_scan
    always_ff @(posedge clk_i) begin
      if (mmr_hwif_out.RMA_SIP_TOKEN_I[i].req && mmr_hwif_out.RMA_SIP_TOKEN_I[i].req_is_wr) begin
        sip_rma_token_raw_n0_scan[i] <=
                    (sip_rma_token_raw_n0_scan[i] &
                     ~mmr_hwif_out.RMA_SIP_TOKEN_I[i].wr_biten.token) |
                    (mmr_hwif_out.RMA_SIP_TOKEN_I[i].wr_data.token &
                     mmr_hwif_out.RMA_SIP_TOKEN_I[i].wr_biten.token);
      end
      if (mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].req &&
                mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].req_is_wr) begin
        chiplet_rma_token_raw_n0_scan[i] <=
                    (chiplet_rma_token_raw_n0_scan[i] &
                     ~mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].wr_biten.token) |
                    (mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].wr_data.token &
                     mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].wr_biten.token);
      end
      if (mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].req &&
                mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].req_is_wr) begin
        sec_disable_token_raw_n0_scan[i] <=
                    (sec_disable_token_raw_n0_scan[i] &
                     ~mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].wr_biten.token) |
                    (mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].wr_data.token &
                     mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].wr_biten.token);
      end
    end

    assign mmr_hwif_in.RMA_SIP_TOKEN_I[i].wr_ack =
            mmr_hwif_out.RMA_SIP_TOKEN_I[i].req &&
            mmr_hwif_out.RMA_SIP_TOKEN_I[i].req_is_wr;
    assign mmr_hwif_in.RMA_SIP_TOKEN_I[i].rd_ack =
            mmr_hwif_out.RMA_SIP_TOKEN_I[i].req &&
            !mmr_hwif_out.RMA_SIP_TOKEN_I[i].req_is_wr;
    assign mmr_hwif_in.RMA_SIP_TOKEN_I[i].rd_data.token =
            sip_rma_token_raw_n0_scan[i];

    assign mmr_hwif_in.RMA_CHIPLET_TOKEN_I[i].wr_ack =
            mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].req &&
            mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].req_is_wr;
    assign mmr_hwif_in.RMA_CHIPLET_TOKEN_I[i].rd_ack =
            mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].req &&
            !mmr_hwif_out.RMA_CHIPLET_TOKEN_I[i].req_is_wr;
    assign mmr_hwif_in.RMA_CHIPLET_TOKEN_I[i].rd_data.token =
            chiplet_rma_token_raw_n0_scan[i];

    assign mmr_hwif_in.SEC_DISABLE_TOKEN_I[i].wr_ack =
            mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].req &&
            mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].req_is_wr;
    assign mmr_hwif_in.SEC_DISABLE_TOKEN_I[i].rd_ack =
            mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].req &&
            !mmr_hwif_out.SEC_DISABLE_TOKEN_I[i].req_is_wr;
    assign mmr_hwif_in.SEC_DISABLE_TOKEN_I[i].rd_data.token =
            sec_disable_token_raw_n0_scan[i];
  end

  assign rma_sip_token_go = mmr_hwif_out.TOKEN_EOP.rma_sip_token_go.value;
  assign rma_chiplet_token_go = mmr_hwif_out.TOKEN_EOP.rma_chiplet_token_go.value;
  assign secure_disable_token_go = mmr_hwif_out.TOKEN_EOP.secure_disable_token_go.value;

  /////////////////////////////// SHA256 HASHING ENGINES ///////////////////////////////
  // A single `*_go` pulse from the CSR triggers the hashing engine.
  efuse_token_digest_sha256 u_sha256_rma_sip_token (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),
    .test_en_i           (test_en_i),
    .start_i             (rma_sip_token_go),
    .token_i             (sip_rma_token),
    .digest_vld_sticky_o (rma_sip_token_digest_vld_sticky_raw),
    .sha_digest_sticky_o (rma_sip_token_sha256_digest)
  );

  efuse_token_digest_sha256 u_sha256_rma_chiplet_token (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),
    .test_en_i           (test_en_i),
    .start_i             (rma_chiplet_token_go),
    .token_i             (chiplet_rma_token),
    .digest_vld_sticky_o (rma_chiplet_token_digest_vld_sticky_raw),
    .sha_digest_sticky_o (rma_chiplet_token_sha256_digest)
  );

  efuse_token_digest_sha256 u_sha256_sec_disable_token (
    .clk_i               (clk_i),
    .rst_ni              (rst_ni),
    .test_en_i           (test_en_i),
    .start_i             (secure_disable_token_go),
    .token_i             (sec_disable_token),
    .digest_vld_sticky_o (sec_disable_token_digest_vld_sticky_raw),
    .sha_digest_sticky_o (sec_disable_token_sha256_digest_sticky)
  );

  /////////////////////////////// TRIPLE-REDUNDANT MATCHING LOGIC ///////////////////////////////
  assign compute_rma_sip_token_match = rma_sip_token_digest_vld_sticky && fuse_sense_done_i;
  assign compute_rma_chiplet_token_match = rma_chiplet_token_digest_vld_sticky && fuse_sense_done_i;

  efuse_triple_redundant_comparator u_triple_redundant_comparator_rma_sip_token (
    .compute_comparison_vld_i(compute_rma_sip_token_match),
    .token_digest_i(rma_sip_token_sha256_digest),
    .token_expected_i(shadow_regs_i.fields.rma_sip_token_digest.token_digest),
    .token_match_o(rma_sip_token_match),
    .redundancy_fault_o(token_match_fault[0])
  );

  efuse_triple_redundant_comparator u_triple_redundant_comparator_rma_chiplet_token (
    .compute_comparison_vld_i(compute_rma_chiplet_token_match),
    .token_digest_i(rma_chiplet_token_sha256_digest),
    .token_expected_i(shadow_regs_i.fields.rma_chiplet_token_digest.token_digest),
    .token_match_o(rma_chiplet_token_match),
    .redundancy_fault_o(token_match_fault[1])
  );

  // Reconstruct the 256-bit secure-disable token from 32 rev cells (8 bits each) so the
  // expected value is configurable at top metal via a metal-only ECO without a full re-spin.
  // SEP_SEC_DISABLE_TOKEN encodes the real first-silicon value; PD can flip individual bits
  // by re-routing the per-bit IN tap from the LO rail to HI (or vice versa) at top metal.
  genvar g;
  for (g = 0; g < 256; g++) begin : gen_sec_disable_in_sel
    if (SEP_SEC_DISABLE_TOKEN[g]) begin : gen_hi
      assign sec_disable_rev_in_sel[g] = sec_disable_rev_hi[g];
    end else begin : gen_lo
      assign sec_disable_rev_in_sel[g] = sec_disable_rev_lo[g];
    end
  end

  prim_rev_cell u_sec_disable_rev[31:0] (
    .lo_o      (sec_disable_rev_lo),
    .hi_o      (sec_disable_rev_hi),
    .in_i      (sec_disable_rev_in_sel),
    .out_o     (sec_disable_token_rev),
    .src_low_i (1'b0),
    .src_high_i(1'b1)
  );

  efuse_triple_redundant_comparator u_triple_redundant_comparator_sec_disable_token (
    // Do not need to wait for fuse sense done; sec_disable_token_rev is a metal-fixed constant
    .compute_comparison_vld_i(sec_disable_token_digest_vld_sticky),
    .token_digest_i(sec_disable_token_sha256_digest_sticky),
    .token_expected_i(sec_disable_token_rev),
    .token_match_o(sec_disable_token_match),
    .redundancy_fault_o(token_match_fault[2])
  );

  // Flop the match results to the output ports, helps with timing closure and prevents glitches on the output ports
  always_ff @(posedge clk_i) begin
    if (~rst_ni) begin
      rma_sip_token_match_q_n0_scan <= '0;
      rma_chiplet_token_match_q_n0_scan <= '0;
      sec_disable_token_match_q <= '0;
      token_match_fault_sticky_q <= '0;
    end else begin
      rma_sip_token_match_q_n0_scan <= rma_sip_token_match;
      rma_chiplet_token_match_q_n0_scan <= rma_chiplet_token_match;
      sec_disable_token_match_q <= sec_disable_token_match;
      // Set-only: a tamper indication survives until the next reset so a
      // transient glitch attack cannot be papered over by a later retry.
      token_match_fault_sticky_q <= token_match_fault_sticky_q | token_match_fault;
    end
  end

  assign token_match_fault_o = |token_match_fault_sticky_q;

  /////////////////////
  // Security Disable
  /////////////////////

  logic final_sec_disable;
  logic [7:0] tt_rev_d_out;
  // Disable sec_disable_feature during A2/B1
  logic [7:0] low, high;

  prim_rev_cell u_sep_sec_disable (
    .lo_o(low[7:0]),
    .hi_o(high[7:0]),
    .in_i({low[7],low[6], low[5], low[4], low[3], low[2], low[1], high[0]}),
    .out_o(tt_rev_d_out[7:0]),
    .src_low_i(1'b0),
    .src_high_i(1'b1)
  );

  assign final_sec_disable = tt_rev_d_out[0] && (sec_disable_token_match == TOKEN_MATCH_CODE);
  assign security_disable_o = final_sec_disable;

  always_comb begin
    // Default: zero the output and set LC state to invalid
    shadow_regs_o = efuse_map_t'(0);
    shadow_regs_o.fields.lc_state.lc_state = LC_STATE_INVALID;

    // Guard shadow registers from being exposed downstream until fuse sensing is complete,
    // Unless we are in security disable mode, then expose the shadow registers downstream.
    if (fuse_sense_done_i || final_sec_disable) begin
      shadow_regs_o = shadow_regs_i;
    end
  end

  assign rma_sip_token_match_q_o = rma_sip_token_match_q_n0_scan;
  assign rma_chiplet_token_match_q_o = rma_chiplet_token_match_q_n0_scan;

  // Expose sec_disable_token for test access
  assign sec_disable_token_o = sec_disable_token;


  ///////////////////////////////////////////////////////
  // Simulation handling: no-reset elements power up as X
  ///////////////////////////////////////////////////////

`ifdef SIMULATION
  initial begin
    $display(
        "[INFO] Initialize the tokens and token digest valid bits for simulation. They don't have a reset value.");
  end
  always_comb begin
    for (int i = 0; i < 8; i++) begin
      if (sip_rma_token_raw_n0_scan[i] === 32'bXXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX) begin
        sip_rma_token[i] = 32'b0;
      end else begin
        sip_rma_token[i] = sip_rma_token_raw_n0_scan[i];
      end
      if (chiplet_rma_token_raw_n0_scan[i] === 32'bXXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX) begin
        chiplet_rma_token[i] = 32'b0;
      end else begin
        chiplet_rma_token[i] = chiplet_rma_token_raw_n0_scan[i];
      end
      if (sec_disable_token_raw_n0_scan[i] === 32'bXXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX_XXXX) begin
        sec_disable_token[i] = 32'b0;
      end else begin
        sec_disable_token[i] = sec_disable_token_raw_n0_scan[i];
      end
    end

    if (sec_disable_token_digest_vld_sticky_raw === 1'bX) begin
      sec_disable_token_digest_vld_sticky = 1'b0;
    end else begin
      sec_disable_token_digest_vld_sticky = sec_disable_token_digest_vld_sticky_raw;
    end
    if (rma_sip_token_digest_vld_sticky_raw === 1'bX) begin
      rma_sip_token_digest_vld_sticky = 1'b0;
    end else begin
      rma_sip_token_digest_vld_sticky = rma_sip_token_digest_vld_sticky_raw;
    end
    if (rma_chiplet_token_digest_vld_sticky_raw === 1'bX) begin
      rma_chiplet_token_digest_vld_sticky = 1'b0;
    end else begin
      rma_chiplet_token_digest_vld_sticky = rma_chiplet_token_digest_vld_sticky_raw;
    end
  end
`else
  always_comb begin
    for (int i = 0; i < 8; i++) begin
      sip_rma_token[i] = sip_rma_token_raw_n0_scan[i];
      chiplet_rma_token[i] = chiplet_rma_token_raw_n0_scan[i];
      sec_disable_token[i] = sec_disable_token_raw_n0_scan[i];
    end
    sec_disable_token_digest_vld_sticky = sec_disable_token_digest_vld_sticky_raw;
    rma_sip_token_digest_vld_sticky = rma_sip_token_digest_vld_sticky_raw;
    rma_chiplet_token_digest_vld_sticky = rma_chiplet_token_digest_vld_sticky_raw;
  end
`endif

endmodule : efuse_token_processing
