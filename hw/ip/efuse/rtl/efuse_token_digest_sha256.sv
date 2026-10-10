// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Hash a fixed 256-bit token through OpenTitan prim_sha2_32 into a sticky digest.
//
// Feeder FSM pulses hash_start, streams eight 32-bit words MSW-first (token_i[7] →
// message schedule w[0]), asserts hash_process, and waits for hash_done.
// The 256-bit message always fits in one 512-bit block; MultimodeEn is 0 (SHA-256 only).
// Digest is standard SHA-256 of the token byte stream with no endianness swap; H0 sits in
// the MSBs of the sticky digest.
// test_en_i freezes the retained digest for DFT; digest_vld_sticky_o marks validity.

`include "prim_assert.sv"

module efuse_token_digest_sha256 (
  input logic clk_i,                    // System clock.
  input logic rst_ni,                   // Active-low asynchronous reset of the feeder and the SHA
                                        // engine; the digest and valid latches are not reset.

  input logic test_en_i,                // DFT test-enable: freeze the retained digest.

  input logic             start_i,      // Starts a hash of token_i when the feeder and engine are
                                        // idle; while high it also clears digest_vld_sticky_o.
  input logic [7:0][31:0] token_i,      // 256-bit token, MSW = token_i[7].

  output logic         digest_vld_sticky_o,  // High when the retained digest is valid; cleared by
                                             // start_i, set one cycle after the engine finishes,
                                             // and held in a latch across reset.
  output logic [255:0] sha_digest_sticky_o  // SHA-256 digest of the last hashed token, H0 in the
                                            // MSBs; held in a latch across reset and frozen while
                                            // test_en_i is high.
);

  typedef enum logic [2:0] {
    ST_IDLE,
    ST_START,
    ST_STREAM,
    ST_WAIT
  } feeder_st_e;

  feeder_st_e state_q, state_d;
  logic [2:0] word_idx_q, word_idx_d;

  // engine control / status
  logic                hash_start;
  logic                hash_process;
  logic                fifo_rvalid;
  logic                fifo_rready;
  logic                hash_done;
  logic                hash_done_q;
  logic                idle;
  prim_sha2_pkg::sha_fifo32_t         fifo_rdata;

  prim_sha2_pkg::sha_word64_t [7:0] sha_digest;
  logic        [255:0] sha_digest_formatted;
  logic                digest_vld_sticky_n0_scan;
  logic        [255:0] sha_digest_sticky_n0_scan;
  logic                digest_latch_en_pre;
  logic                digest_latch_en;
  logic                vld_latch_en_pre;
  logic                vld_latch_en;
  logic                vld_latch_d;

  // Feed the token most-significant word first so that token_i[7] lands in
  // message-schedule word w[0], which is the most-significant word of the token.
  assign fifo_rdata.data = token_i[3'd7-word_idx_q];
  assign fifo_rdata.mask = 4'hF;  // word-aligned: all bytes valid

  always_comb begin
    state_d      = state_q;
    word_idx_d   = word_idx_q;
    hash_start   = 1'b0;
    hash_process = 1'b0;
    fifo_rvalid  = 1'b0;

    unique case (state_q)
      ST_IDLE: begin
        word_idx_d = 3'd0;
        if (start_i && idle) begin
          state_d = ST_START;
        end
      end

      ST_START: begin
        hash_start = 1'b1;
        word_idx_d = 3'd0;
        state_d    = ST_STREAM;
      end

      ST_STREAM: begin
        fifo_rvalid = 1'b1;
        if (fifo_rready) begin
          if (word_idx_q == 3'd7) begin
            // 8th / last word consumed this cycle
            state_d = ST_WAIT;
          end else begin
            word_idx_d = word_idx_q + 3'd1;
          end
        end
      end

      ST_WAIT: begin
        // Start the hash process to pad and hash the block. Wait for the hash to complete.
        hash_process = 1'b1;
        if (hash_done) begin
          state_d = ST_IDLE;
        end
      end

      default: state_d = ST_IDLE;
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q    <= ST_IDLE;
      word_idx_q <= 3'd0;
    end else begin
      state_q    <= state_d;
      word_idx_q <= word_idx_d;
    end
  end

  prim_sha2_32 #(
    .MultimodeEn(0)
  ) u_prim_sha2_32 (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .wipe_secret_i   (1'b0),
    .wipe_v_i        (32'b0),
    .fifo_rvalid_i   (fifo_rvalid),
    .fifo_rdata_i    (fifo_rdata),
    .fifo_rready_o   (fifo_rready),
    .sha_en_i        (1'b1),
    .hash_start_i    (hash_start),
    .hash_stop_i     (1'b0),
    .hash_continue_i (1'b0),
    .digest_mode_i   (prim_sha2_pkg::SHA2_None),     // unused in MultimodeEn = 0
    .hash_process_i  (hash_process),
    .hash_done_o     (hash_done),
    .message_length_i(64'd256),       // single 256-bit block
    .digest_i        ('0),
    .digest_we_i     ('0),
    .digest_o        (sha_digest),
    .digest_on_blk_o (),              // unused
    .hash_running_o  (),              // unused
    .idle_o          (idle)
  );

  // Map the engine digest (H0..H7 in digest words 0..7, lower 32 bits each)
  // into a 256-bit vector with H0 in the most-significant bits.
  for (genvar i = 0; i < 8; i++) begin : gen_digest_map
    assign sha_digest_formatted[255-32*i-:32] = sha_digest[i][31:0];
  end

  // The prim_sha2 engine pulses hash_done_o one cycle before it writes the
  // final digest_o, so the updated digest_o is only visible the following cycle.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      hash_done_q <= 1'b0;
    end else begin
      hash_done_q <= hash_done;
    end
  end

  // Ungated latch controls. The digest is captured when hash_done_q marks digest_o valid.
  // The sticky valid opens on either event, with start_i taking priority so that launching a
  // new hash clears the valid bit rather than setting it, which stops the token match being
  // evaluated while a digest is still being computed.
  always_comb begin
    digest_latch_en_pre = hash_done_q;
    vld_latch_en_pre    = start_i || hash_done_q;
    vld_latch_d         = ~start_i;
  end

  // test_en_i holds both latches closed for the whole of scan test. The latches are off the
  // scan chain, but their enables and the engine feeding them are not, so without this a
  // shifted pattern could write through and forge or clobber a token digest.
  //
  // The gate is an instantiated AND cell rather than inferred logic so synthesis cannot
  // restructure test_en_i out of the final stage. test_en_i is then a controlling input and
  // the enable is a hazard-free constant zero throughout test, which matters because these
  // are level-sensitive.
  prim_and2 #(
    .Width(1)
  ) u_digest_latch_en_d0nt_touch (
    .in0_i(digest_latch_en_pre),
    .in1_i(~test_en_i),
    .out_o(digest_latch_en)
  );

  prim_and2 #(
    .Width(1)
  ) u_vld_latch_en_d0nt_touch (
    .in0_i(vld_latch_en_pre),
    .in1_i(~test_en_i),
    .out_o(vld_latch_en)
  );

  // Retain the digest so it persists across cold reset.
  always_latch begin
    if (digest_latch_en) begin
      sha_digest_sticky_n0_scan <= sha_digest_formatted;
    end
  end

  // Sticky valid for the retained digest.
  always_latch begin
    if (vld_latch_en) begin
      digest_vld_sticky_n0_scan <= vld_latch_d;
    end
  end

  assign sha_digest_sticky_o = sha_digest_sticky_n0_scan;
  assign digest_vld_sticky_o = digest_vld_sticky_n0_scan;

  `OCAH_OT_ASSERT(StickyDigestHold_A, (!digest_latch_en && $past(!digest_latch_en)) |-> $stable
                                      (sha_digest_sticky_n0_scan), clk_i, 1'b0)
  `OCAH_OT_ASSERT(StickyDigestValidHold_A, (!vld_latch_en && $past(!vld_latch_en)) |-> $stable
                                           (digest_vld_sticky_n0_scan), clk_i, 1'b0)
  `OCAH_OT_ASSERT(StickyDigestCapture_A, digest_latch_en |=> sha_digest_sticky_n0_scan == $past
                                         (sha_digest_formatted), clk_i, !rst_ni)
  `OCAH_OT_ASSERT(StickyDigestValidCapture_A, vld_latch_en |=> digest_vld_sticky_n0_scan == $past
                                              (vld_latch_d), clk_i, !rst_ni)
  `OCAH_OT_ASSERT(StickyDigestFrozenInTest_A, test_en_i |=> $stable(sha_digest_sticky_n0_scan)
                                              && $stable(digest_vld_sticky_n0_scan), clk_i, !rst_ni)

endmodule : efuse_token_digest_sha256
