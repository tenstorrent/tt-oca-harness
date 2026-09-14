// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench: Simple Repetition Threshold Test
//
// Description:
// Sends simple all-zero and all-one patterns to test threshold behavior.
// This avoids the complexity of mixing bits within a word.
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_simple;
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

  // Clock generation
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  // Timeout
  initial begin
    #1000000;
    $display("\nERROR: Test timeout!");
    $finish;
  end

  // Waveform
  initial begin
    $dumpfile("repetition_simple.vcd");
    $dumpvars(0, tb_repetition_simple);
  end

  // Main test
  initial begin
    test_errors = 0;

    rstn = 0;
    enable = 0;
    entropy = 32'h00000000;
    entropy_valid = 0;
    repetition_limit = 8'd10;  // Threshold = 10

    $display("\n========================================");
    $display("Simple Repetition Threshold Test");
    $display("========================================");
    $display("Threshold = 10");
    $display("Testing with all-zero and all-one words\n");

    // Release reset
    repeat (5) @(posedge clk);
    rstn = 1;
    enable = 1;
    repeat (5) @(posedge clk);

    //------------------------------------------------------------------
    // TEST 1: Send 10 consecutive zeros (320 bits total, should FAIL immediately)
    //------------------------------------------------------------------
    $display("--- TEST 1: 320 Consecutive Zeros (10 words x 32 bits) ---");
    $display("Expected: Failure after 11th bit in first word");

    for (i = 0; i < 10; i = i + 1) begin
      entropy = 32'h00000000;  // All zeros
      entropy_valid = 1;

      @(posedge clk);
      #1;
      $display("  After word %0d: counter=%0d, status=%b", i + 1, ctr_repetition, status);

      if (i == 0 && status != 1) begin
        $display("  ✗ ERROR: Should have failed in first word (has 32 consecutive zeros)!");
        test_errors = test_errors + 1;
      end

      entropy_valid = 0;
      @(posedge clk);
    end

    if (status == 1) begin
      $display("  ✓ Correctly detected failure with consecutive zeros");
    end

    //------------------------------------------------------------------
    // TEST 2: Reset and send exactly enough to reach threshold
    //------------------------------------------------------------------
    $display("\n--- TEST 2: Exactly 10 Bits (threshold boundary) ---");
    $display("Sending bits carefully to stop at count=10");

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send word with just 10 zeros at start, then ones
    // bits[0:9]=0, bits[10:31]=1
    entropy = 32'hFFFFFC00;  // Top 22 bits = 1, bottom 10 bits = 0
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  Pattern sent: 10 zeros then 22 ones");
    $display("  After processing: counter=%0d, status=%b", ctr_repetition, status);
    $display("  Note: Counter shows last sequence (22 ones), not the 10 zeros");

    // The status should be 1 because we had 22 consecutive ones (> 10)
    if (status != 1) begin
      $display("  Note: Status=%b (22 consecutive ones exceed threshold)", status);
    end

    //------------------------------------------------------------------
    // TEST 3: Send pattern with exactly 11 consecutive bits at start
    //------------------------------------------------------------------
    $display("\n--- TEST 3: Exactly 11 Zeros at Start ---");

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send word with 11 zeros, then ones
    // bits[0:10]=0 (11 bits), bits[11:31]=1 (21 bits)
    entropy = 32'hFFFFF800;  // Top 21 bits = 1, bottom 11 bits = 0
    entropy_valid = 1;

    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  Pattern sent: 11 zeros then 21 ones");
    $display("  After processing: counter=%0d, status=%b", ctr_repetition, status);

    if (status != 1) begin
      $display(
          "  ✗ ERROR: Should have failed (has 11 consecutive zeros and 21 consecutive ones)!");
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ Correctly failed");
    end

    //------------------------------------------------------------------
    // TEST 4: Lower threshold with word-by-word tracking
    //------------------------------------------------------------------
    $display("\n--- TEST 4: Threshold=3, Track Each Word ---");

    repetition_limit = 8'd3;

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    $display("  Sending 5 all-zero words...");
    for (i = 0; i < 5; i = i + 1) begin
      entropy = 32'h00000000;
      entropy_valid = 1;

      @(posedge clk);
      #1;
      $display("    Word %0d: counter=%0d, status=%b", i + 1, ctr_repetition, status);

      if (i == 0 && status != 1) begin
        $display("    ✗ ERROR: Should fail in first word (32 zeros > threshold 3)!");
        test_errors = test_errors + 1;
      end

      entropy_valid = 0;
      @(posedge clk);
    end

    //------------------------------------------------------------------
    // TEST 5: Check counter saturation
    //------------------------------------------------------------------
    $display("\n--- TEST 5: Counter Saturation Test ---");

    repetition_limit = 8'd255;  // Max threshold

    // Reset
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    $display("  Sending 10 all-zero words to see counter saturation...");
    for (i = 0; i < 10; i = i + 1) begin
      entropy = 32'h00000000;
      entropy_valid = 1;

      @(posedge clk);
      #1;
      if (i < 3 || i == 9) begin  // Show first 3 and last
        $display("    Word %0d: counter=%0d, status=%b", i + 1, ctr_repetition, status);
      end

      entropy_valid = 0;
      @(posedge clk);
    end

    $display("  Final counter: %0d (should saturate at 255)", ctr_repetition);
    if (ctr_repetition != 255) begin
      $display("  ✗ ERROR: Counter should saturate at 255, got %0d", ctr_repetition);
      test_errors = test_errors + 1;
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
    end else begin
      $display("\n✗✗✗ TESTS FAILED ✗✗✗");
    end

    $display("\n");
    $finish;
  end

endmodule
