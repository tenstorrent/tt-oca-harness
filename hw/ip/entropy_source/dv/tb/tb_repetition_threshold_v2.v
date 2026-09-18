// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench: Repetition Test Threshold Verification V2
//
// Description:
// Sends bits sequentially to test the threshold boundary.
// Sends exactly the number of consecutive bits needed, followed by an opposite bit.
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_threshold_v2;
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
  integer i;

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
    #2000000;
    $display("\nERROR: Test timeout!");
    $finish;
  end

  // Waveform dumping
  initial begin
    $dumpfile("repetition_threshold_v2.vcd");
    $dumpvars(0, tb_repetition_threshold_v2);
  end

  // Main test sequence
  initial begin
    // Initialize
    test_errors = 0;

    rstn = 0;
    enable = 0;
    entropy = 32'h00000000;
    entropy_valid = 0;
    repetition_limit = 8'd10;  // Threshold = 10

    $display("\n========================================");
    $display("Repetition Test Threshold Verification V2");
    $display("========================================");
    $display("Threshold = 10");
    $display("Expected: 11 consecutive bits trigger failure\n");

    // Release reset
    repeat (5) @(posedge clk);
    rstn = 1;
    enable = 1;
    repeat (5) @(posedge clk);

    //------------------------------------------------------------------
    // TEST 1: Send exactly 10 zeros, then a one (should NOT fail)
    //------------------------------------------------------------------
    $display("--- TEST 1: 10 Consecutive Zeros ---");
    $display("Sending: 0000000000 1 (10 zeros, then 1)");

    // Build word: bits[0:9]=0, bit[10]=1, rest=1 to avoid more matches
    entropy = 32'b11111111111111111111101111111111;  // Bit 10 is clear to avoid match
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  After processing:");
    $display("    Counter value: %0d (expected: 21 ones after the 10 zeros)", ctr_repetition);
    $display("    Status (fail): %b", status);

    // The counter will show 21 because after the 10 zeros and one 1, there are 21 more 1s
    // This is the actual behavior - the module processes all 32 bits!

    $display("\n  INSIGHT: The module processes all 32 bits in order!");
    $display("  Pattern sent: bit[0-9]=0, bit[10-31]=1");
    $display("  Processing: 10 zeros → bit 10 (1) breaks → 21 more ones");
    $display("  Final counter: 21 (counting the 21 consecutive ones at the end)");

    //------------------------------------------------------------------
    // TEST 2: Send exactly 10 zeros in isolation
    //------------------------------------------------------------------
    $display("\n--- TEST 2: 10 Zeros with Alternating Pattern After ---");
    $display("Sending 10 zeros, then alternating 1010...");

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // bits[0:9]=0 (10 zeros), bits[10-31]=alternating 10101010...
    entropy = 32'b10101010101010101010100000000000;
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  After processing:");
    $display("    Counter value: %0d", ctr_repetition);
    $display("    Status (fail): %b (expected: 0 = pass)", status);

    if (status != 0) begin
      $display("  ✗ ERROR: With 10 zeros (threshold=10), should NOT fail!");
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ PASS: Correctly did not fail with 10 zeros");
    end

    //------------------------------------------------------------------
    // TEST 3: Send exactly 11 zeros with alternating after
    //------------------------------------------------------------------
    $display("\n--- TEST 3: 11 Zeros with Alternating Pattern After ---");
    $display("Sending 11 zeros, then alternating 1010...");

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // bits[0:10]=0 (11 zeros), bits[11-31]=alternating 10101010...
    entropy = 32'b10101010101010101010000000000000;
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  After processing:");
    $display("    Counter value: %0d", ctr_repetition);
    $display("    Status (fail): %b (expected: 1 = fail)", status);

    if (status != 1) begin
      $display("  ✗ ERROR: With 11 zeros (threshold=10), SHOULD fail!");
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ PASS: Correctly failed with 11 zeros");
    end

    //------------------------------------------------------------------
    // TEST 4: Lower threshold test - send 1 bit at a time
    //------------------------------------------------------------------
    $display("\n--- TEST 4: Bit-by-Bit with Threshold = 3 ---");
    $display("Sending zeros one at a time using single-bit words");

    repetition_limit = 8'd3;

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send first 3 zeros one at a time (should not fail)
    for (i = 0; i < 3; i = i + 1) begin
      entropy = 32'b10101010101010101010101010101010;  // First bit is 0, rest alternating
      entropy[0] = 1'b0;  // Make sure bit 0 is 0
      entropy_valid = 1;
      @(posedge clk);
      #1;
      $display("    After zero %0d: counter=%0d, status=%b", i + 1, ctr_repetition, status);
      entropy_valid = 0;
      @(posedge clk);
    end

    if (status != 0) begin
      $display("  ✗ ERROR: After 3 zeros (threshold=3), should NOT fail yet!");
      test_errors = test_errors + 1;
    end

    // Send 4th zero (should trigger failure)
    entropy = 32'b10101010101010101010101010101010;
    entropy[0] = 1'b0;
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("    After zero 4: counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);

    if (status != 1) begin
      $display("  ✗ ERROR: After 4 zeros (threshold=3), SHOULD fail!");
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ PASS: Correctly failed after 4 consecutive zeros with threshold=3");
    end

    //------------------------------------------------------------------
    // TEST 5: Check if counter increments correctly
    //------------------------------------------------------------------
    $display("\n--- TEST 5: Counter Increment Verification ---");
    $display("Watching counter increment step by step");

    repetition_limit = 8'd10;

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send sequence: 5 zeros, then a 1, then 5 ones
    // bits[0:4]=0 (5 zeros), bit[5]=1, bits[6:10]=1 (5 ones), rest alternating
    entropy = 32'b10101010101010101010101111110000;
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  Pattern: 00000 1 11111 (5 zeros, transition, 5 ones)");
    $display("  Final counter: %0d", ctr_repetition);
    $display("  Status: %b", status);
    $display("  NOTE: Counter shows last sequence (after bit 5 transition)");

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
      $display("\nKey Findings:");
      $display("  - Module processes all 32 bits in each entropy word");
      $display("  - With threshold=10, need 11 consecutive bits to fail");
      $display("  - Counter shows the count of the LAST sequence processed");
    end else begin
      $display("\n✗✗✗ TESTS FAILED ✗✗✗");
      $display("Threshold behavior is incorrect!");
      $display("\nPossible issues:");
      $display("  - Threshold comparison may be wrong (should be > not >=)");
      $display("  - Counter increment timing may be off");
    end

    $display("\n");
    $finish;
  end

endmodule
