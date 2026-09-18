// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench: Exhaustive Repetition Test
//
// Description:
// Exhaustively tests all run lengths from 5 to 25 for both 0s and 1s.
// Verifies that:
// - Run length <= threshold → PASS (status=0)
// - Run length > threshold → FAIL (status=1)
//
// For each threshold value from 5 to 25:
//   For each run length from 5 to 25:
//     Test runs of 0s and runs of 1s
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_exhaustive;
  reg clk, rstn, enable, entropy_valid;
  reg [31:0] entropy;
  reg [7:0] repetition_limit;
  wire [7:0] ctr_repetition;
  wire status;

  integer test_errors;
  integer threshold;
  integer run_length;
  integer i, j;
  integer expected_status;
  integer bit_value;  // 0 or 1

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

  // Clock generation
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  // Waveform
  initial begin
    $dumpfile("repetition_exhaustive.vcd");
    $dumpvars(0, tb_repetition_exhaustive);
  end

  // Timeout
  initial begin
    #100000000;  // 100ms timeout for exhaustive test
    $display("\nERROR: Test timeout!");
    $finish;
  end

  // Function to create a pattern with exactly N consecutive bits of given value
  // followed by alternating pattern to break the sequence
  function automatic [31:0] create_pattern;
    input integer num_bits;  // Number of consecutive bits (1-32)
    input integer bit_val;  // 0 or 1
    integer k;
    begin
      create_pattern = 32'h00000000;

      // Set the consecutive bits
      for (k = 0; k < num_bits && k < 32; k = k + 1) begin
        if (bit_val == 1) create_pattern[k] = 1'b1;
        else create_pattern[k] = 1'b0;
      end

      // Fill remaining bits with alternating pattern to break sequence
      for (k = num_bits; k < 32; k = k + 1) begin
        if (k % 2 == 0) create_pattern[k] = bit_val ? 1'b0 : 1'b1;
        else create_pattern[k] = bit_val ? 1'b1 : 1'b0;
      end
    end
  endfunction

  // Function to create random pattern with no runs exceeding max_run_length
  function automatic [31:0] create_safe_random;
    input integer max_run_length;
    integer k;
    integer current_run;
    reg last_bit;
    begin
      create_safe_random = 32'h00000000;
      current_run = 0;
      last_bit = $urandom & 1;
      create_safe_random[0] = last_bit;

      for (k = 1; k < 32; k = k + 1) begin
        if (current_run >= max_run_length) begin
          // Force a transition to break the run
          create_safe_random[k] = ~last_bit;
          last_bit = ~last_bit;
          current_run = 1;
        end else begin
          // Random bit
          create_safe_random[k] = $urandom & 1;
          if (create_safe_random[k] == last_bit) begin
            current_run = current_run + 1;
          end else begin
            current_run = 1;
            last_bit = create_safe_random[k];
          end
        end
      end
    end
  endfunction

  // Main test
  initial begin
    test_errors = 0;

    rstn = 0;
    enable = 0;
    entropy = 0;
    entropy_valid = 0;
    repetition_limit = 10;

    $display("\n========================================");
    $display("Exhaustive Repetition Threshold Test");
    $display("========================================");
    $display("Testing all run lengths from 5 to 25");
    $display("Testing thresholds from 5 to 25\n");

    // Release reset
    repeat (5) @(posedge clk);
    rstn = 1;
    enable = 1;
    repeat (5) @(posedge clk);

    // Test each threshold value from 5 to 25
    for (threshold = 5; threshold <= 25; threshold = threshold + 1) begin
      $display("================================================");
      $display("Testing Threshold = %0d", threshold);
      $display("================================================");

      repetition_limit = threshold;

      // Test each run length from 5 to 25
      for (run_length = 5; run_length <= 25; run_length = run_length + 1) begin

        // Test runs of 0s
        bit_value = 0;

        // Reset module
        enable = 0;
        @(posedge clk);
        enable = 1;
        @(posedge clk);

        // Send 3 random safe patterns BEFORE the test pattern
        for (i = 0; i < 3; i = i + 1) begin
          entropy = create_safe_random(threshold);  // Random but no runs > threshold
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);

          // Verify random patterns don't trigger failure
          if (status != 0) begin
            $display("  ✗ ERROR: Random pattern before test triggered failure!");
            $display("    Threshold=%0d, Pattern=0x%08X, Status=%0d", threshold, entropy, status);
            test_errors = test_errors + 1;
          end
        end

        // Now send the test pattern with exactly run_length consecutive 0s
        entropy = create_pattern(run_length, bit_value);
        entropy_valid = 1;

        @(posedge clk);
        #1;
        entropy_valid = 0;
        @(posedge clk);
        #1;

        // Determine expected result for the TEST pattern
        // Run length > threshold should FAIL
        expected_status = (run_length > threshold) ? 1 : 0;

        // Check result
        if (status != expected_status) begin
          $display("  ✗ ERROR: Run of %0d zeros, threshold=%0d", run_length, threshold);
          $display("    Expected status=%0d, got status=%0d", expected_status, status);
          $display("    Counter=%0d, Pattern=0x%08X", ctr_repetition, entropy);
          test_errors = test_errors + 1;
        end else if (threshold == 10 && (run_length == 10 || run_length == 11)) begin
          // Show key boundary cases for threshold=10
          $display("  ✓ Run of %0d zeros: status=%0d (correct)", run_length, status);
        end

        // Send 3 random safe patterns AFTER the test pattern
        for (i = 0; i < 3; i = i + 1) begin
          entropy = create_safe_random(threshold);  // Random but no runs > threshold
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);

          // After a failure, status should stay HIGH (sticky failure)
          // After a pass, random safe patterns should not trigger failure
          if (expected_status == 0 && status != 0) begin
            $display("  ✗ ERROR: Random pattern after PASS test triggered failure!");
            $display("    Threshold=%0d, Pattern=0x%08X", threshold, entropy);
            test_errors = test_errors + 1;
          end
        end

        // Test runs of 1s
        bit_value = 1;

        // Reset module
        enable = 0;
        @(posedge clk);
        enable = 1;
        @(posedge clk);

        // Send 3 random safe patterns BEFORE the test pattern
        for (i = 0; i < 3; i = i + 1) begin
          entropy = create_safe_random(threshold);
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);

          if (status != 0) begin
            $display("  ✗ ERROR: Random pattern before test triggered failure!");
            $display("    Threshold=%0d, Pattern=0x%08X, Status=%0d", threshold, entropy, status);
            test_errors = test_errors + 1;
          end
        end

        // Now send the test pattern with exactly run_length consecutive 1s
        entropy = create_pattern(run_length, bit_value);
        entropy_valid = 1;

        @(posedge clk);
        #1;
        entropy_valid = 0;
        @(posedge clk);
        #1;

        // Determine expected result
        expected_status = (run_length > threshold) ? 1 : 0;

        // Check result
        if (status != expected_status) begin
          $display("  ✗ ERROR: Run of %0d ones, threshold=%0d", run_length, threshold);
          $display("    Expected status=%0d, got status=%0d", expected_status, status);
          $display("    Counter=%0d, Pattern=0x%08X", ctr_repetition, entropy);
          test_errors = test_errors + 1;
        end else if (threshold == 10 && (run_length == 10 || run_length == 11)) begin
          // Show key boundary cases for threshold=10
          $display("  ✓ Run of %0d ones:  status=%0d (correct)", run_length, status);
        end

        // Send 3 random safe patterns AFTER the test pattern
        for (i = 0; i < 3; i = i + 1) begin
          entropy = create_safe_random(threshold);
          entropy_valid = 1;
          @(posedge clk);
          #1;
          entropy_valid = 0;
          @(posedge clk);

          if (expected_status == 0 && status != 0) begin
            $display("  ✗ ERROR: Random pattern after PASS test triggered failure!");
            $display("    Threshold=%0d, Pattern=0x%08X", threshold, entropy);
            test_errors = test_errors + 1;
          end
        end
      end

      $display("");  // Blank line between thresholds
    end

    //------------------------------------------------------------------
    // Summary Statistics
    //------------------------------------------------------------------
    $display("\n========================================");
    $display("Test Summary");
    $display("========================================");
    $display("Thresholds tested: 5 to 25 (21 values)");
    $display("Run lengths tested: 5 to 25 (21 values)");
    $display("Bit values tested: 0 and 1 (2 values)");
    $display("Total specific test cases: %0d", 21 * 21 * 2);
    $display("Random patterns per test: 6 (3 before + 3 after)");
    $display("Total random patterns: %0d", 21 * 21 * 2 * 6);
    $display("Grand total operations: %0d", 21 * 21 * 2 * 7);
    $display("Test errors: %0d", test_errors);

    if (test_errors == 0) begin
      $display("\n✓✓✓ ALL TESTS PASSED ✓✓✓");
      $display("\nVerified:");
      $display("  - All run lengths <= threshold correctly PASS");
      $display("  - All run lengths > threshold correctly FAIL");
      $display("  - Behavior is consistent for both 0s and 1s");
      $display("  - Threshold boundary is correct (> not >=)");
      $display("  - Random patterns with runs <= threshold do NOT trigger false failures");
      $display("  - Random patterns interspersed between test patterns work correctly");
    end else begin
      $display("\n✗✗✗ %0d TESTS FAILED ✗✗✗", test_errors);
      $display("\nThe repetition test has incorrect threshold behavior!");
    end

    $display("\n");
    $finish;
  end

endmodule
