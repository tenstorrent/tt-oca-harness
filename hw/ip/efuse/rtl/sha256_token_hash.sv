// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// SHA-256 Token Hash (OpenTitan prim_sha2 feeder)
//
//
// Description:
// Generic single-block SHA-256 helper for hashing a fixed 256-bit token.
// Wraps the OpenTitan `prim_sha2_32` engine (SHA-256 only, MultimodeEn = 0)
// and provides a small feeder FSM that drives the streaming FIFO interface:
//   1. pulse `hash_start_i` (the real "go")
//   2. stream the eight 32-bit token words through the FIFO handshake,
//      most-significant word first (token_i[7] -> message schedule w[0])
//   3. assert `hash_process_i` to mark the message complete
//   4. wait for `hash_done_o`
// The 256-bit message always fits in a single 512-bit block.
//
// The produced digest is the standard SHA-256 of the token byte stream (no
// endianness swap), with H0 placed in the most-significant bits of digest_o.
//-----------------------------------------------------------------------------

module sha256_token_hash
    import prim_sha2_pkg::*;
(
    input  logic             clk_i,
    input  logic             rst_ni,

    // input scan_en / test_en ?

    input  logic             start_i,              // start a hash of token_i
    input  logic [7:0][31:0] token_i,              // 256-bit token, MSW = token_i[7]

    output logic             digest_vld_sticky_o, // sticky valid when digest_o is valid
    output logic [255:0]     sha_digest_sticky_o
);

    // Match the encoding used by triple_redundent_comparator (PASS = 2'b01).
    localparam logic [1:0] SHA256_PASS = 2'b01;

    typedef enum logic [2:0] {
        StIdle,
        StStart,
        StStream,
        StWait
    } feeder_st_e;

    feeder_st_e state_q, state_d;
    logic [2:0] word_idx_q, word_idx_d;

    // engine control / status
    logic              hash_start;
    logic              hash_process;
    logic              fifo_rvalid;
    logic              fifo_rready;
    logic              hash_done;
    logic              hash_done_q;
    logic              idle;
    sha_fifo32_t       fifo_rdata;

    sha_word64_t [7:0] sha_digest;
    logic [255:0] sha_digest_formatted;
    logic              digest_vld_sticky_n0_scan;
    logic [255:0]      sha_digest_sticky_n0_scan;

    // Feed the token most-significant word first so that token_i[7] lands in
    // message-schedule word w[0], which is the most-significant word of the token.
    assign fifo_rdata.data = token_i[3'd7 - word_idx_q];
    assign fifo_rdata.mask = 4'hF; // word-aligned: all bytes valid

    always_comb begin
        state_d      = state_q;
        word_idx_d   = word_idx_q;
        hash_start   = 1'b0;
        hash_process = 1'b0;
        fifo_rvalid  = 1'b0;

        unique case (state_q)
            StIdle: begin
                word_idx_d = 3'd0;
                if (start_i && idle) begin
                    state_d = StStart;
                end
            end

            StStart: begin
                hash_start = 1'b1;
                word_idx_d = 3'd0;
                state_d    = StStream;
            end

            StStream: begin
                fifo_rvalid = 1'b1;
                if (fifo_rready) begin
                    if (word_idx_q == 3'd7) begin
                        // 8th / last word consumed this cycle
                        state_d = StWait;
                    end else begin
                        word_idx_d = word_idx_q + 3'd1;
                    end
                end
            end

            StWait: begin
                // Start the hash process to pad and hash the block. Wait for the hash to complete.
                hash_process = 1'b1;
                if (hash_done) begin 
                    state_d = StIdle;
                end
            end

            default: state_d = StIdle;
        endcase
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            state_q    <= StIdle;
            word_idx_q <= 3'd0;
        end else begin
            state_q    <= state_d;
            word_idx_q <= word_idx_d;
        end
    end

    prim_sha2_32 #(
        .MultimodeEn(0)
    ) u_prim_sha2_32_n0_scan (
        .clk_i            (clk_i),
        .rst_ni           (rst_ni),
        .wipe_secret_i    (1'b0),
        .wipe_v_i         (32'b0),
        .fifo_rvalid_i    (fifo_rvalid),
        .fifo_rdata_i     (fifo_rdata),
        .fifo_rready_o    (fifo_rready),
        .sha_en_i         (1'b1),
        .hash_start_i     (hash_start),
        .hash_stop_i      (1'b0),
        .hash_continue_i  (1'b0),
        .digest_mode_i    (SHA2_None),       // unused in MultimodeEn = 0
        .hash_process_i   (hash_process),
        .hash_done_o      (hash_done),
        .message_length_i (64'd256),         // single 256-bit block
        .digest_i         ('0),
        .digest_we_i      ('0),
        .digest_o         (sha_digest),
        .digest_on_blk_o  (),                // unused
        .hash_running_o   (),                // unused
        .idle_o           (idle)
    );

    // Map the engine digest (H0..H7 in digest words 0..7, lower 32 bits each)
    // into a 256-bit vector with H0 in the most-significant bits.
    for (genvar i = 0; i < 8; i++) begin : gen_digest_map
        assign sha_digest_formatted[255 - 32*i -: 32] = sha_digest[i][31:0];
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

    // When hash_done_q is asserted (digest_o now valid), latch the value of
    // digest_o so it persists across cold reset.
    always_latch begin
        if (hash_done_q) begin
            sha_digest_sticky_n0_scan <= sha_digest_formatted;
        end else begin
            sha_digest_sticky_n0_scan <= sha_digest_sticky_n0_scan;
        end
    end

    // Sticky valid for the retained digest. Set on hash_done_q, cleared on start_i (a new token is being hashed).
    // Don't continuously check the token match while the digest is being computed. 
    always_latch begin
        if (start_i) begin
            digest_vld_sticky_n0_scan <= 1'b0;
        end else if (hash_done_q) begin
            digest_vld_sticky_n0_scan <= 1'b1;
        end else begin
            digest_vld_sticky_n0_scan <= digest_vld_sticky_n0_scan;
        end
    end

    assign sha_digest_sticky_o = sha_digest_sticky_n0_scan;
    assign digest_vld_sticky_o = digest_vld_sticky_n0_scan;

endmodule : sha256_token_hash
