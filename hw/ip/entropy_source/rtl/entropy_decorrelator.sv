// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Noise Source Decorrelator and Extractor
//
// Description:
// Ring oscillators suffer from serial correlation. The decorrelator reduces
// it by feeding back samples after a prime number (29) of delays. 64 bits of
// serial data is pushed into the delay chain and 8 bits are sampled after
// every 64 cycles. This results in a bit rate reduction by a factor of 8.
// The decorrelator can be bypassed for testing purposes. In this case the
// feedback path is broken and the downsampling rate is reduced from 64 to
// 8, resulting in no bit rate reduction.
// The functional behaviour is programmed by the host software via the CSR
// configuration registers.
// Note: the sample_clk_div_i value is one less that the actual division value
// so for a divider of 64, we set that value to 63, counting from 63 to 0.
// Note: ensure that the entropy_byte_valid_o is deasserted to 0 whenever
// the enable_i is deasserted, otherwise we continue pushing non-valid data
// into the FIFO and eventually causing an overflow condition. The output
// stream should also not indicate valid entropy data under this condition.
//------------------------------------------------------------------------------


module entropy_decorrelator #(
    parameter int unsigned LENGTH       = 29,
    parameter int unsigned CLKDIV_WIDTH = 24,
    parameter bit          LFSR_MODE    = 1'b0 ///DEFER: feature
) (
    input  logic                    clk_i,
    input  logic                    rst_ni,
    input  logic                    enable_i,
    input  logic                    noise_i,
    input  logic                    bypass_i,
    input  logic [7:0]              byte_mask_i,
    input  logic [CLKDIV_WIDTH-1:0] sample_clk_div_i,
    output logic [7:0]              entropy_byte_sample_o,
    output logic                    entropy_byte_valid_o
);

    logic [CLKDIV_WIDTH-1:0] clk_divider;
    logic [LENGTH-1:0]       ff_stage;
    logic                    feedback;

    // shift register with feedback
    always @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
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

    assign feedback = bypass_i ? 1'b0 : ff_stage[LENGTH-1];

    // downsampler - extract one byte every sample_clk_div_i cycles
    always @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            entropy_byte_valid_o <= 1'b0;
            clk_divider          <= sample_clk_div_i;
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
            // When disabled, clear the valid signal to prevent it from staying stuck HIGH
            entropy_byte_valid_o <= 1'b0;
        end
    end

endmodule
