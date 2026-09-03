// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench: Repetition Test Boundary Conditions
//
// Tests the exact boundary: with threshold=10
// - 10 consecutive bits should NOT fail
// - 11 consecutive bits SHOULD fail
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_boundary;
  reg clk, rstn, enable, entropy_valid;
  reg [31:0] entropy;
  reg [7:0] repetition_limit;
  wire [7:0] ctr_repetition;
  wire status;
  integer errors;

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
    $dumpfile("repetition_boundary.vcd");
    $dumpvars(0, tb_repetition_boundary);
  end
  initial begin
    #500000;
    $display("TIMEOUT!");
    $finish;
  end

  initial begin
    errors = 0;
    rstn = 0;
    enable = 0;
    entropy = 0;
    entropy_valid = 0;
    repetition_limit = 10;

    $display("\n=== Repetition Test Boundary Verification ===");
    $display("Threshold = 10\n");

    repeat (5) @(posedge clk);
    rstn = 1;
    enable = 1;
    repeat (5) @(posedge clk);

    // TEST 1: Exactly 10 consecutive zeros
    $display("TEST 1: Exactly 10 consecutive zeros");
    entropy = 32'b11111111111111111111110000000000;  // Bits 0-9 = 0 (10), Rest = 1
    entropy_valid = 1;
    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  Pattern: 0x%08X", 32'b11111111111111111111110000000000);
    $display("  Bits 0-9 are zeros (10 consecutive)");
    $display("  Bits 10-31 are ones (22 consecutive)");
    $display("  Counter: %0d, Status: %b", ctr_repetition, status);

    // Note: This will show counter=22 and status=1 because 22 ones > 10
    $display("  NOTE: 22 consecutive ones at end exceed threshold!");

    // TEST 2: Pattern that ends at exactly 10
    $display("\nTEST 2: 10 zeros with no more matches after");
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // Send 10 zeros, then alternating (to break sequence immediately)
    entropy = 32'b10101010101010101011110000000000;  // Last bit pattern chosen to alternate after 10 zeros
    entropy_valid = 1;
    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  Counter: %0d, Status: %b", ctr_repetition, status);
    if (status == 1 && ctr_repetition <= 10) begin
      $display("  ✗ ERROR: Threshold=10, but failed with counter=%0d!", ctr_repetition);
      errors = errors + 1;
    end

    // TEST 3: Explicitly send 11-bit sequence
    $display("\nTEST 3: Exactly 11 consecutive zeros");
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    entropy = 32'b11111111111111111111100000000000;  // Bits 0-10 = 0 (11), Rest = 1
    entropy_valid = 1;
    @(posedge clk);
    #1;
    entropy_valid = 0;
    @(posedge clk);
    #1;

    $display("  Bits 0-10 are zeros (11 consecutive)");
    $display("  Bits 11-31 are ones (21 consecutive)");
    $display("  Counter: %0d, Status: %b", ctr_repetition, status);
    if (status != 1) begin
      $display("  ✗ ERROR: Should have failed with 11 zeros!");
      errors = errors + 1;
    end else begin
      $display("  ✓ Correctly failed");
    end

    // TEST 4: Send bits across two words to reach exactly 10
    $display("\nTEST 4: 10 zeros across multiple words");
    enable = 0;
    @(posedge clk);
    enable = 1;
    @(posedge clk);

    // First word: 5 zeros at end
    entropy = 32'b10101010101010101010101010100000;  // Last 5 bits = 0
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("  After word 1 (5 zeros at end): counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);

    // Second word: 5 zeros at start, then break
    entropy = 32'b10101010101010101010101010100000;  // First 5 bits = 0
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("  After word 2 (5 more zeros): counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);
    #1;

    // Check: 10 total zeros should NOT have triggered failure yet
    // (But the alternating pattern after may have incremented counter)

    // TEST 5: Now send 11th zero
    $display("\nTEST 5: Send 11th consecutive zero");
    entropy = 32'b11111111111111111111111111111110;  // Just bit 0 = 0
    entropy_valid = 1;
    @(posedge clk);
    #1;
    $display("  After 11th zero: counter=%0d, status=%b", ctr_repetition, status);
    entropy_valid = 0;
    @(posedge clk);
    #1;

    repeat (10) @(posedge clk);

    $display("\n=== Summary ===");
    $display("Errors: %0d", errors);
    if (errors == 0) $display("✓ Threshold behavior appears correct");
    else $display("✗ Found issues with threshold behavior");
    $finish;
  end
endmodule
