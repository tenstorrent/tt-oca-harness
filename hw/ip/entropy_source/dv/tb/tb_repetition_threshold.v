// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench: Repetition Test Threshold Verification
//
// Description:
// Verifies exact threshold behavior of the repetition test.
// Tests the specific case: threshold = 10 requires exactly 11 consecutive
// identical bits to trigger failure.
//
// Test Strategy:
// 1. Set threshold to 10
// 2. Send exactly 10 consecutive zeros → Should NOT fail
// 3. Send exactly 11 consecutive zeros → Should FAIL
// 4. Send exactly 10 consecutive ones → Should NOT fail
// 5. Send exactly 11 consecutive ones → Should FAIL
// 6. Verify counter values at each step
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_threshold;
  // Clock and reset
  reg clk;
  reg rstn;

  // DUT signals
  reg [31:0] entropy;
  reg        entropy_valid;
  reg        enable;
  reg [7:0]  repetition_limit;
  wire [7:0] ctr_repetition;
  wire       status;

  // Test monitoring
  integer test_errors;
  integer cycle_count;

  // Instantiate DUT
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

  // Clock generation: 10ns period (100MHz)
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  // Timeout watchdog
  initial begin
    #1000000;
    $display("\nERROR: Test timeout!");
    $finish;
  end

  // Waveform dumping
  initial begin
    $dumpfile("repetition_threshold.vcd");
    $dumpvars(0, tb_repetition_threshold);
  end

  // Main test sequence
  initial begin
    // Initialize
    test_errors = 0;
    cycle_count = 0;

    rstn = 0;
    enable = 0;
    entropy = 32'h00000000;
    entropy_valid = 0;
    repetition_limit = 8'd10;  // Threshold = 10

    $display("\n========================================");
    $display("Repetition Test Threshold Verification");
    $display("========================================");
    $display("Threshold = 10");
    $display("Expected: 11 consecutive bits trigger failure\n");

    // Release reset
    repeat (5) @(posedge clk);
    rstn = 1;
    enable = 1;
    repeat (5) @(posedge clk);

    //------------------------------------------------------------------
    // TEST 1: Send 10 consecutive zeros (should NOT fail)
    //------------------------------------------------------------------
    $display("--- TEST 1: 10 Consecutive Zeros ---");
    $display("Expected: Counter reaches 10, NO failure");

    // Send 10 zeros in a single 32-bit word (bits 0-9 are zero, rest are one)
    entropy = 32'b11111111111111111111110000000000;  // Bits [9:0] = 0
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  After 10 zeros:");
    $display("    Counter value: %0d", ctr_repetition);
    $display("    Status (fail): %b", status);

    if (ctr_repetition != 10) begin
      $display("  ✗ ERROR: Counter should be 10, got %0d", ctr_repetition);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Counter = 10 (correct)");
    end

    if (status != 0) begin
      $display("  ✗ ERROR: Status should be 0 (pass), got %b", status);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Status = 0 (pass, correct)");
    end

    //------------------------------------------------------------------
    // TEST 2: Send 11th consecutive zero (should FAIL)
    //------------------------------------------------------------------
    $display("\n--- TEST 2: 11th Consecutive Zero ---");
    $display("Expected: Counter reaches 11, FAILURE triggered");

    // Reset to start fresh
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send 11 zeros in a single 32-bit word (bits 0-10 are zero, rest are one)
    entropy = 32'b11111111111111111111100000000000;  // Bits [10:0] = 0 (11 zeros)
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  After 11 zeros:");
    $display("    Counter value: %0d", ctr_repetition);
    $display("    Status (fail): %b", status);

    if (ctr_repetition != 11) begin
      $display("  ✗ ERROR: Counter should be 11, got %0d", ctr_repetition);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Counter = 11 (correct)");
    end

    if (status != 1) begin
      $display("  ✗ ERROR: Status should be 1 (fail), got %b", status);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Status = 1 (fail, correct)");
    end

    //------------------------------------------------------------------
    // TEST 3: Send 10 consecutive ones (should NOT fail)
    //------------------------------------------------------------------
    $display("\n--- TEST 3: 10 Consecutive Ones ---");
    $display("Expected: Counter reaches 10, NO new failure");

    // Reset to start fresh
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send 10 ones in a single 32-bit word (bits 0-9 are one, rest are zero)
    entropy = 32'b00000000000000000000001111111111;  // Bits [9:0] = 1
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  After 10 ones:");
    $display("    Counter value: %0d", ctr_repetition);
    $display("    Status (fail): %b", status);

    if (ctr_repetition != 10) begin
      $display("  ✗ ERROR: Counter should be 10, got %0d", ctr_repetition);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Counter = 10 (correct)");
    end

    if (status != 0) begin
      $display("  ✗ ERROR: Status should be 0 (pass), got %b", status);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Status = 0 (pass, correct)");
    end

    //------------------------------------------------------------------
    // TEST 4: Send 11th consecutive one (should FAIL)
    //------------------------------------------------------------------
    $display("\n--- TEST 4: 11th Consecutive One ---");
    $display("Expected: Counter reaches 11, FAILURE triggered");

    // Reset to start fresh
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send 11 ones in a single 32-bit word (bits 0-10 are one, rest are zero)
    entropy = 32'b00000000000000000000011111111111;  // Bits [10:0] = 1 (11 ones)
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  After 11 ones:");
    $display("    Counter value: %0d", ctr_repetition);
    $display("    Status (fail): %b", status);

    if (ctr_repetition != 11) begin
      $display("  ✗ ERROR: Counter should be 11, got %0d", ctr_repetition);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Counter = 11 (correct)");
    end

    if (status != 1) begin
      $display("  ✗ ERROR: Status should be 1 (fail), got %b", status);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Status = 1 (fail, correct)");
    end

    //------------------------------------------------------------------
    // TEST 5: Detailed step-by-step with threshold = 3
    //------------------------------------------------------------------
    $display("\n--- TEST 5: Detailed Step-by-Step (Threshold = 3) ---");
    $display("Expected: 4 consecutive bits trigger failure");

    repetition_limit = 8'd3;  // Lower threshold for easier tracing

    // Reset to start fresh
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send bits one at a time
    $display("\n  Sending zeros one bit at a time:");

    // Bit 0: First zero
    entropy = 32'b11111111111111111111111111111110;  // Only bit 0 = 0
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("    After bit 0 (0): counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);

    // Bit 1: Second zero (sent as new word)
    entropy = 32'b11111111111111111111111111111110;  // Only bit 0 = 0
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("    After bit 1 (0): counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);

    // Bit 2: Third zero
    entropy = 32'b11111111111111111111111111111110;  // Only bit 0 = 0
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("    After bit 2 (0): counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);

    // Bit 3: Fourth zero (should trigger failure)
    entropy = 32'b11111111111111111111111111111110;  // Only bit 0 = 0
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("    After bit 3 (0): counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);

    if (ctr_repetition != 4) begin
      $display("  ✗ ERROR: After 4 zeros, counter should be 4, got %0d", ctr_repetition);
      test_errors = test_errors + 1;
    end

    if (status != 1) begin
      $display("  ✗ ERROR: After 4 zeros with threshold=3, should fail, got status=%b", status);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Correct: 4 consecutive zeros with threshold=3 triggered failure");
    end

    //------------------------------------------------------------------
    // Final Summary
    //------------------------------------------------------------------
    repeat (10) @(posedge clk);

    $display("\n========================================");
    $display("Test Summary");
    $display("========================================");
    $display("Total test errors: %0d", test_errors);

    if (test_errors == 0) begin
      $display("\n✓✓✓ ALL TESTS PASSED ✓✓✓");
      $display("\nVerified Behavior:");
      $display("  - Threshold = 10 requires 11 consecutive bits to fail");
      $display("  - Counter correctly tracks consecutive identical bits");
      $display("  - Status flag triggers when counter > threshold");
    end else begin
      $display("\n✗✗✗ TESTS FAILED ✗✗✗");
      $display("Threshold behavior may be incorrect!");
    end

    $display("\n");
    $finish;
  end

endmodule
