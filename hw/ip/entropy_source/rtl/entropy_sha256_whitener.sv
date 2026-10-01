// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Condition a 32-bit entropy stream with SHA-256 whitening per NIST SP 800-90B.
//
// Accumulates 16 words (512 bits) into a SHA-256 block and streams the 256-bit digest as
// eight 32-bit words.
// When enable_i is low the module bypasses hashing and passes entropy through with
// ready/valid.
// busy_o, input_count_o, and output_count_o report hasher progress.

module entropy_sha256_whitener (
  input       logic       clk_i,        // System clock.
  input       logic       rst_ni,       // Active-low asynchronous reset.

  input       logic       entropy_valid_i,  // Qualifies entropy_data_i on the input handshake.
  input       logic [31:0] entropy_data_i,  // Raw entropy word to hash, or to pass through in
                                            // bypass.
  output      logic       entropy_ready_o,  // Input handshake ready; low while hashing or
                                            // streaming a digest.

  output      logic       whitened_valid_o,  // Qualifies whitened_data_o on the output handshake.
  output      logic [31:0] whitened_data_o,  // Digest word in order from word 0, or the input word
                                             // in bypass.
  input       logic       whitened_ready_i,  // Output handshake ready; advances to the next digest
                                             // word.

  input       logic       enable_i,     // High hashes the stream; low bypasses hashing and passes
                                        // entropy_data_i straight through.

  output      logic       busy_o,       // High while enabled and a digest is being computed or
                                        // streamed.
  output      logic [3:0] input_count_o,  // Words accepted into the current 16-word block.
  output      logic [3:0] output_count_o  // Digest words still to be streamed; zero while
                                          // enable_i is low.
);

  /////////////////////
  // Local parameters
  /////////////////////
  localparam int unsigned SHA256_BLOCK_WORDS = 16;  // SHA-256 input: 512 bits = 16 × 32-bit words
  localparam int unsigned SHA256_DIGEST_WORDS = 8;  // SHA-256 output: 256 bits = 8 × 32-bit words

  /////////////
  // Signals
  /////////////

  logic bypass_mode;
  assign bypass_mode = !enable_i;

  logic [3:0] input_word_count_q, input_word_count_d;
  logic [3:0] output_words_remaining_q, output_words_remaining_d;
  logic hashing_q, hashing_d;
  logic input_phase_q, input_phase_d;
  logic       sha_hash_done_q;

  logic [31:0] output_buffer_q [8];
  logic [31:0] output_buffer_d [8];

  logic                            sha_fifo_valid;
  prim_sha2_pkg::sha_fifo32_t      sha_fifo_data;
  logic                            sha_fifo_ready;
  logic                            sha_hash_start;
  logic                            sha_hash_process;
  logic                            sha_hash_done;
  prim_sha2_pkg::sha_word64_t [7:0] sha_digest;

  /////////////////
  // Sub-instances
  /////////////////
  prim_sha2_32 #(
    .MultimodeEn(1'b0)  // SHA-256 only
  ) u_sha2 (
    .clk_i              (clk_i),
    .rst_ni             (rst_ni),
    .wipe_secret_i      (1'b0),
    .wipe_v_i           (32'h0),
    .fifo_rvalid_i      (sha_fifo_valid),
    .fifo_rdata_i       (sha_fifo_data),
    .fifo_rready_o      (sha_fifo_ready),
    .sha_en_i           (1'b1),
    .hash_start_i       (sha_hash_start),
    .hash_stop_i        (1'b0),
    .hash_continue_i    (1'b0),
    .digest_mode_i      (prim_sha2_pkg::SHA2_256),
    .hash_process_i     (sha_hash_process),
    .hash_done_o        (sha_hash_done),
    .message_length_i   (64'd512),  // Always 512-bit blocks
    .digest_i           ('0),
    .digest_we_i        ('0),
    .digest_o           (sha_digest),
    .digest_on_blk_o    (),
    .hash_running_o     (),
    .idle_o             ()
  );

  /////////////////
  // Combinational
  /////////////////
  always_comb begin
    // Defaults
    input_word_count_d = input_word_count_q;
    output_words_remaining_d = output_words_remaining_q;
    hashing_d = hashing_q;
    input_phase_d = input_phase_q;
    output_buffer_d = output_buffer_q;

    sha_fifo_valid = 1'b0;
    sha_fifo_data.data = 32'h0;
    sha_fifo_data.mask = 4'hF;  // All bytes valid
    sha_hash_start = 1'b0;
    sha_hash_process = 1'b0;

    entropy_ready_o = 1'b0;
    whitened_valid_o = 1'b0;
    whitened_data_o = 32'h0;

    if (bypass_mode) begin
      // Bypass: direct passthrough
      entropy_ready_o = whitened_ready_i;
      whitened_valid_o = entropy_valid_i;
      whitened_data_o = entropy_data_i;
      input_phase_d = 1'b0;
      output_words_remaining_d = 4'd0;
    end else if (output_words_remaining_q != 4'd0) begin
      // Output phase: stream digest words
      whitened_valid_o = 1'b1;
      whitened_data_o = output_buffer_q[
          3'(4'(SHA256_DIGEST_WORDS) - output_words_remaining_q)
      ];
      input_phase_d = 1'b0;

      if (whitened_ready_i) begin
        output_words_remaining_d = output_words_remaining_q - 4'd1;
      end
    end else if (!hashing_q) begin
      // Input phase: stream to SHA-256 (not hashing, output complete)
      // Pulse hash_start when entering input phase to initialize SHA-2 FIFO state machine
      // prim_sha2_pad requires hash_start to transition from StIdle to StFifoReceive
      // before fifo_rready_o goes high
      if (!input_phase_q) begin
        sha_hash_start = 1'b1;
        input_phase_d = 1'b1;
      end

      sha_fifo_valid = entropy_valid_i;
      sha_fifo_data.data = entropy_data_i;
      entropy_ready_o = sha_fifo_ready;

      if (entropy_valid_i && sha_fifo_ready) begin
        input_word_count_d = input_word_count_q + 4'd1;

        // Trigger hash processing on 16th word
        if (input_word_count_q == 4'(SHA256_BLOCK_WORDS - 1)) begin
          sha_hash_process = 1'b1;
          hashing_d = 1'b1;
          input_phase_d = 1'b0;
          input_word_count_d = 4'd0;
        end
      end
    end else begin
      // Hashing phase: wait for completion.
      input_phase_d = 1'b0;
      if (sha_hash_done_q) begin
        hashing_d = 1'b0;
        output_words_remaining_d = 4'(SHA256_DIGEST_WORDS);

        // Load digest into output buffer (extract lower 32 bits)
        for (int i = 0; i < SHA256_DIGEST_WORDS; i++) begin
          output_buffer_d[i] = sha_digest[i][31:0];
        end
      end
    end
  end

  ///////////////
  // Sequential
  ///////////////
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      input_word_count_q <= 4'h0;
      output_words_remaining_q <= 4'd0;
      hashing_q <= 1'b0;
      input_phase_q <= 1'b0;
      output_buffer_q <= '{default: '0};
      sha_hash_done_q <= 1'b0;
    end else begin
      input_word_count_q <= input_word_count_d;
      output_words_remaining_q <= output_words_remaining_d;
      hashing_q <= hashing_d;
      input_phase_q <= input_phase_d;
      output_buffer_q <= output_buffer_d;
      sha_hash_done_q <= sha_hash_done;
    end
  end

  ///////////
  // Output
  ///////////
  assign busy_o = enable_i && (hashing_q || output_words_remaining_q != 4'd0);
  assign input_count_o = input_word_count_q;
  assign output_count_o = enable_i ? output_words_remaining_q : 4'd0;

endmodule
