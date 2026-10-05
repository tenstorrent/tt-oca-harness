// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Decorrelate and downsample ring-oscillator noise into masked entropy bytes.
//
// Feeds noise through a prime-length delay chain (default LENGTH 29) and emits one byte
// every sample_clk_div_i+1 cycles. sample_clk_div_i is one less than the division factor
// (counts down through 0 inclusive).
//
// Controls:
//
// - LFSR_MODE is declared but not read; the feedback is always prime-length.
// - bypass_i breaks the feedback path for raw-output testing.
// - byte_mask_i masks the emitted byte.
//
// entropy_byte_valid_o deasserts whenever enable_i is low so stale data cannot overflow
// the downstream FIFO.

module entropy_decorrelator #(
  parameter int unsigned LENGTH       = 29,  // Decorrelator delay-chain length.
  parameter int unsigned CLKDIV_WIDTH = 24,  // Downsample divider counter width.
  parameter bit          LFSR_MODE    = 1'b0  // Intended to select LFSR rather than prime-length
                                              // feedback; the feedback logic does not read it.
) (
  input       logic                    clk_i,  // System clock.
  input       logic                    rst_ni,  // Active-low asynchronous reset.
  input       logic                    enable_i,  // Enables shifting and sampling; while low the
                                                  // chain holds and the divider reloads from
                                                  // sample_clk_div_i.
  input       logic                    noise_i,  // Synchronized ring-oscillator noise bit shifted
                                                 // into the delay chain each clk_i cycle.
  input       logic                    bypass_i,  // High removes the XOR feedback so raw noise
                                                  // shifts through the chain unmixed.
  input       logic [7:0]              byte_mask_i,  // AND mask applied to each emitted byte; a
                                                     // clear bit forces that output bit to zero.
  input       logic [CLKDIV_WIDTH-1:0] sample_clk_div_i,  // Downsample period minus one, in clk_i
                                                          // cycles between emitted bytes.
  output      logic [7:0]              entropy_byte_sample_o,  // Masked top eight delay-chain
                                                               // stages, held until the next
                                                               // sample.
  output      logic                    entropy_byte_valid_o  // Single-cycle strobe marking a new
                                                             // entropy_byte_sample_o; low while
                                                             // enable_i is low.
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
