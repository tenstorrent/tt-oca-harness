// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench: Simple Direct Repetition Test
//
// Description:
// Very simple approach - send multiple words of all 0s or all 1s to create
// exact run lengths. No complex pattern generation.
//
// To create a run of N bits:
// - Send floor(N/32) words of all 0s (or all 1s)
// - Send one final word with (N mod 32) bits, then break with opposite value
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_simple_runs;
  reg clk, rstn, enable, entropy_valid;
  reg [31:0] entropy;
  reg [7:0] repetition_limit;
  wire [7:0] ctr_repetition;
  wire status;

  integer test_errors;
  integer threshold;
  integer run_length;
  integer words_needed;
  integer remaining_bits;
  integer i;
  reg [31:0] final_word;

  entropy_repetition_test #(
    .DATA_WIDTH(32)
  ) dut (
    .clk_i(clk),
    .rst_ni(rstn),
    .entropy_i(entropy),
    .entropy_valid_i(entropy_valid),
    .enable_i(enable),
    .repetition_limit_i(repetition_limit),
    .ctr_repetition_o(ctr_repetition),
    .status_o(status)
  );

  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end
  initial begin
    $dumpfile("repetition_simple_runs.vcd");
    $dumpvars(0, tb_repetition_simple_runs);
  end
  initial begin
    #50000000;
    $display("TIMEOUT!");
    $finish;
  end

  initial begin
    test_errors = 0;
    rstn = 0;
    enable = 0;
    entropy = 0;
    entropy_valid = 0;
    repetition_limit = 10;

    $display("\n========================================");
    $display("Simple Direct Repetition Test");
    $display("========================================\n");

    repeat (5) @(posedge clk);
    rstn = 1;
    enable = 1;
    repeat (5) @(posedge clk);

    //------------------------------------------------------------------
    // Test all thresholds from 5 to 25
    //------------------------------------------------------------------
    for (threshold = 5; threshold <= 25; threshold = threshold + 1) begin
      $display("Testing Threshold = %0d", threshold);
      repetition_limit = threshold;

      // Test run lengths from threshold-1 to threshold+2
      for (
          run_length = threshold - 1; run_length <= threshold + 2; run_length = run_length + 1
      ) begin

        //--------------------------------------------------------------
        // Test with ZEROS
        //--------------------------------------------------------------
        enable = 0;
        @(posedge clk);
        enable = 1;
        @(posedge clk);

        // Calculate how many full words and remaining bits
        words_needed = run_length / 32;
        remaining_bits = run_length % 32;

        // Send full words of all zeros
        for (i = 0; i < words_needed; i = i + 1) begin
          entropy = 32'h00000000;
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);
        end

        // Send final word with exact remaining bits
        if (remaining_bits > 0) begin
          // Create word with 'remaining_bits' zeros, rest alternating starting with 1
          final_word = 32'h00000000;
          for (i = 0; i < remaining_bits; i = i + 1) begin
            final_word[i] = 1'b0;
          end
          // Fill rest with alternating pattern starting with 1 to break the zero run
          for (i = remaining_bits; i < 32; i = i + 1) begin
            final_word[i] = ((i - remaining_bits) % 2) ? 1'b0 : 1'b1;
          end

          entropy = final_word;
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);
          #1;
        end else begin
          // Exact multiple of 32 - send alternating pattern to break
          entropy = 32'hAAAAAAAA;  // Alternating 1010...
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);
          #1;
        end

        // Check result
        if (run_length <= threshold) begin
          // Should PASS
          if (status != 0) begin
            $display("  ✗ ERROR: %0d zeros, threshold=%0d → status=%0d (expected 0)",
                     run_length, threshold, status);
            test_errors = test_errors + 1;
          end else begin
            $display("  ✓ %0d zeros → PASS (correct)", run_length);
          end
        end else begin
          // Should FAIL
          if (status != 1) begin
            $display("  ✗ ERROR: %0d zeros, threshold=%0d → status=%0d (expected 1)",
                     run_length, threshold, status);
            test_errors = test_errors + 1;
          end else begin
            $display("  ✓ %0d zeros → FAIL (correct)", run_length);
          end
        end

        //--------------------------------------------------------------
        // Test with ONES
        //--------------------------------------------------------------
        enable = 0;
        @(posedge clk);
        enable = 1;
        @(posedge clk);

        // Send full words of all ones
        for (i = 0; i < words_needed; i = i + 1) begin
          entropy = 32'hFFFFFFFF;
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);
        end

        // Send final word with exact remaining bits
        if (remaining_bits > 0) begin
          // Create word with 'remaining_bits' ones, rest alternating starting with 0
          final_word = 32'hFFFFFFFF;
          for (i = 0; i < remaining_bits; i = i + 1) begin
            final_word[i] = 1'b1;
          end
          // Fill rest with alternating pattern starting with 0 to break the one run
          for (i = remaining_bits; i < 32; i = i + 1) begin
            final_word[i] = ((i - remaining_bits) % 2) ? 1'b1 : 1'b0;
          end

          entropy = final_word;
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);
          #1;
        end else begin
          // Exact multiple of 32 - send alternating pattern to break
          entropy = 32'hAAAAAAAA;  // Alternating 1010...
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);
          #1;
        end

        // Check result
        if (run_length <= threshold) begin
          // Should PASS
          if (status != 0) begin
            $display("  ✗ ERROR: %0d ones, threshold=%0d → status=%0d (expected 0)",
                     run_length, threshold, status);
            test_errors = test_errors + 1;
          end else begin
            $display("  ✓ %0d ones → PASS (correct)", run_length);
          end
        end else begin
          // Should FAIL
          if (status != 1) begin
            $display("  ✗ ERROR: %0d ones, threshold=%0d → status=%0d (expected 1)",
                     run_length, threshold, status);
            test_errors = test_errors + 1;
          end else begin
            $display("  ✓ %0d ones → FAIL (correct)", run_length);
          end
        end
      end

      $display("");
    end

    //------------------------------------------------------------------
    // Summary
    //------------------------------------------------------------------
    $display("\n========================================");
    $display("Test Summary");
    $display("========================================");
    $display("Thresholds tested: 5 to 25 (21 values)");
    $display("Run lengths per threshold: 4 (threshold-1 to threshold+2)");
    $display("Bit values tested: 0 and 1 (2 values)");
    $display("Total test cases: %0d", 21 * 4 * 2);
    $display("Test errors: %0d", test_errors);

    if (test_errors == 0) begin
      $display("\n✓✓✓ ALL TESTS PASSED ✓✓✓");
      $display("\nThreshold behavior is CORRECT!");
    end else begin
      $display("\n✗✗✗ %0d TESTS FAILED ✗✗✗", test_errors);
      $display("\nThreshold behavior is INCORRECT!");
    end

    $display("\n");
    $finish;
  end
endmodule
