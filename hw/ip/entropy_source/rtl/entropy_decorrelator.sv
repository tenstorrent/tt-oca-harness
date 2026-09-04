// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * @file entropy_decorrelator.sv
 * @brief Entropy noise source decorrelator and extractor.
 *
 * @details Reduces serial correlation in RO samples by feeding back through
 *          a prime-length (29-deep) delay chain, then downsampling one byte
 *          every sample_clk_div_i+1 cycles. bypass_i breaks the feedback path
 *          and halves the downsampling period for raw-output testing.
 *          entropy_byte_valid_o is deasserted whenever enable_i is LOW to
 *          prevent stale data from overflowing the downstream FIFO.
 *          sample_clk_div_i is one less than the actual division factor
 *          (counts sample_clk_div_i down to 0 inclusive).
 *
 * @param LENGTH       Delay chain length in stages (default: 29)
 * @param CLKDIV_WIDTH Width of downsampler clock divider counter (default: 24)
 * @param LFSR_MODE    Selects feedback mode: prime-length or LFSR (default: 0)
 */

module entropy_decorrelator #(
  parameter int unsigned LENGTH       = 29,
  parameter int unsigned CLKDIV_WIDTH = 24,
  parameter bit          LFSR_MODE    = 1'b0
) (
  input       logic                    clk_i,
  input       logic                    rst_ni,
  input       logic                    enable_i,
  input       logic                    noise_i,
  input       logic                    bypass_i,
  input       logic [7:0]              byte_mask_i,
  input       logic [CLKDIV_WIDTH-1:0] sample_clk_div_i,
  output      logic [7:0]              entropy_byte_sample_o,
  output      logic                    entropy_byte_valid_o
);

  /////////////
  // Signals
  /////////////

  logic [CLKDIV_WIDTH-1:0] clk_divider;
  logic [LENGTH-1:0]       ff_stage;
  logic                    feedback;

  ///////////////
  // Sequential
  ///////////////

  // Shift register with optional XOR feedback for decorrelation
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ff_stage <= LENGTH'(0);
    end else if (enable_i) begin
      for (int i = 0; i < LENGTH; i++) begin
        if (i == 0) begin
          ff_stage[0] <= bypass_i ? noise_i : noise_i ^ feedback;
        end else begin
          ff_stage[i] <= ff_stage[i-1];
        end
      end
    end
  end

  // Downsampler — output one masked byte every sample_clk_div_i+1 cycles
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      entropy_byte_valid_o  <= 1'b0;
      entropy_byte_sample_o <= '0;
      // Preload the full division count so the first sample fires only
      // after the feedback chain has been filled with fresh noise —
      // firing at 0 would emit a byte from the reset-state shift register.
      clk_divider           <= sample_clk_div_i;
    end else if (enable_i) begin
      if (clk_divider == CLKDIV_WIDTH'(0)) begin
        clk_divider           <= sample_clk_div_i;
        entropy_byte_sample_o <= ff_stage[LENGTH-1:LENGTH-8] & byte_mask_i;
        entropy_byte_valid_o  <= 1'b1;
      end else begin
        clk_divider           <= clk_divider - CLKDIV_WIDTH'(1);
        entropy_byte_valid_o  <= 1'b0;
      end
    end else begin
      // Keep the divider primed from the programmed value while idle so
      // configuration writes made before enable govern the first sample.
      clk_divider          <= sample_clk_div_i;
      entropy_byte_valid_o <= 1'b0;
    end
  end

  /////////////////
  // Combinational
  /////////////////

  assign feedback = bypass_i ? 1'b0 : ff_stage[LENGTH-1];

endmodule
