// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`timescale 1ns / 1ps

module RO_Jitter_Array #(
  parameter int N = 16,
  parameter int PROB_SCALE = 1_000_000
) (
  input  logic         clk_i,
  input  logic         rstn_i,
  // Per-lane enable from DUT (connected at TB top level)
  input  logic [N-1:0] enable_i,
  // Config interface
  ro_cfg_if            cfg,
  // Outputs
  output logic [N-1:0] bit_o,
  output logic [N-1:0] vld_o
);
  genvar i;
  generate
    for (i = 0; i < N; i++) begin : gen_ro
      RO_Jitter_Model #(
        .PROB_SCALE(PROB_SCALE)
      ) u_ro (
        .clk_i            (clk_i),
        .rstn_i           (rstn_i),
        .cfg_enable_i     (enable_i[i]),  // Use per-lane enable from DUT
        .cfg_seed_en_i    (cfg.seed_en),
        .cfg_seed_i       (cfg.seed[i]),
        .cfg_p_bias_i     (cfg.p_bias[i]),
        .cfg_p_corr_i     (cfg.p_corr[i]),
        .cfg_stuck_en_i   (cfg.stuck_en[i]),
        .cfg_stuck_value_i(cfg.stuck_val[i]),
        .bit_o            (bit_o[i]),
        .vld_o            (vld_o[i])
      );
    end
  endgenerate

  // ============================================================================
  // 32-bit Word Generation for Health Test Direct Injection
  // ============================================================================
  // Generates 32-bit words continuously when enabled
  // Produces 1 word every 64 cycles (matching decorrelator sample rate)
  // Activated when cfg.word32_enable is high

  logic        word32_bit;         // Single bit from word32 generator
  logic        word32_bit_vld;     // Valid signal from word32 generator
  logic [31:0] word32_data_stage;  // Staging register for bit accumulation
  logic [31:0] word32_data_q;      // Output register (only updates when word complete)
  logic        word32_valid_q;     // Pulsed when word is complete
  logic [4:0]  bit_counter;        // Counts 0-31 for word accumulation
  logic        sample_toggle;      // Toggle to sample every other bit

  // Instantiate dedicated RO_Jitter_Model for word32 generation
  // This reuses all existing bias/correlation/stuck-at logic
  // Enable continuously to produce bits every cycle
  RO_Jitter_Model #(
    .PROB_SCALE(PROB_SCALE)
  ) u_word32_gen (
    .clk_i            (clk_i),
    .rstn_i           (rstn_i),
    .cfg_enable_i     (cfg.word32_enable),       // Enable continuously when word32 mode active
    .cfg_seed_en_i    (1'b0),                    // No seed control for word32
    .cfg_seed_i       (32'h0),
    .cfg_p_bias_i     (cfg.word32_p_bias),
    .cfg_p_corr_i     (cfg.word32_p_corr),
    .cfg_stuck_en_i   (1'b0),                    // No stuck-at for word32
    .cfg_stuck_value_i(1'b0),
    .bit_o            (word32_bit),
    .vld_o            (word32_bit_vld)
  );

  // Accumulate bits into staging register, transfer to output when complete
  // RO_Jitter_Model produces bits every cycle, but we sample every other bit
  // This gives us 64 cycles per word (32 bits × 2 cycles/bit) matching decorrelator rate
  // word32_data_q only updates when word32_valid_q pulses (synchronized)
  always_ff @(posedge clk_i or negedge rstn_i) begin
    if (!rstn_i) begin
      word32_data_stage <= 32'h0;
      word32_data_q     <= 32'h0;
      word32_valid_q    <= 1'b0;
      bit_counter       <= 5'd0;
      sample_toggle     <= 1'b0;
    end else begin
      word32_valid_q <= 1'b0;  // Default: pulse for one cycle

      if (word32_bit_vld) begin
        // Toggle every time we see a valid bit
        sample_toggle <= ~sample_toggle;

        // Only accumulate on every other valid bit (when toggle is high)
        if (sample_toggle) begin
          // Shift new bit into staging register (LSB first)
          word32_data_stage <= {word32_data_stage[30:0], word32_bit};

          // When 32 bits complete, transfer to output register
          if (bit_counter == 5'd31) begin
            word32_data_q  <= {word32_data_stage[30:0], word32_bit};  // Complete word
            word32_valid_q <= 1'b1;
            bit_counter    <= 5'd0;
          end else begin
            bit_counter <= bit_counter + 5'd1;
          end
        end
      end
    end
  end

  // Connect to cfg interface
  // Select between fixed value or probabilistically generated value
  assign cfg.word32_data  = cfg.word32_use_fixed ? cfg.word32_fixed_value : word32_data_q;
  assign cfg.word32_valid = word32_valid_q;

endmodule
