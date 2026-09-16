// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Repetition Test Byte Stream Testbench
//
// Description:
// Comprehensive testbench for entropy_repetition_test_byte_stream module
// Tests catastrophic failure detection on 8-bit byte streams
// Verifies enable/disable functionality and threshold behavior
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_test_byte_stream ();

  // Test parameters
  parameter int unsigned CLOCK_PERIOD = 10;

  // Test signals
  reg clk_i;
  reg rst_ni;
  reg [7:0] entropy_i;
  reg enable_i;
  reg [7:0] repetition_limit_i;
  wire status_o;

  // Test tracking
  integer test_cycles = 0;
  integer total_tests = 0;
  integer passed_tests = 0;
  integer false_positives = 0;
  integer false_negatives = 0;

  // xoroshiro128+ for high-quality pseudorandom data generation
  reg [63:0] xoro_s0 = 64'h0123456789ABCDEF;  // State 0
  reg [63:0] xoro_s1 = 64'hFEDCBA9876543210;  // State 1
  reg [63:0] xoro_result;
  reg [7:0] prng_data;

  // Failure injection control
  reg inject_failure = 0;
  reg failure_bit = 0;

  // Instantiate the DUT
  entropy_repetition_test_byte_stream u_repetition_test (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .entropy_i(entropy_i),
    .enable_i(enable_i),
    .repetition_limit_i(repetition_limit_i),
    .ctr_repetition_o(ctr_repetition_o),
    .status_o(status_o)
  );

  wire [7:0] ctr_repetition_o;

  // Clock generation
  always begin
    clk_i = 0;
    #(CLOCK_PERIOD / 2);
    clk_i = 1;
    #(CLOCK_PERIOD / 2);
    test_cycles = test_cycles + 1;
  end

  // xoroshiro128+ high-quality PRNG
  function automatic [63:0] rotl64;
    input [63:0] x;
    input [5:0] k;
    begin
      rotl64 = (x << k) | (x >> (64 - k));
    end
  endfunction

  always @(posedge clk_i) begin
    if (~rst_ni) begin
      xoro_s0 <= 64'h0123456789ABCDEF;
      xoro_s1 <= 64'hFEDCBA9876543210;
      xoro_result <= 64'h0;
    end else begin
      // xoroshiro128+ algorithm
      xoro_result <= xoro_s0 + xoro_s1;  // Result is sum of two states

      // Update states
      xoro_s1 <= xoro_s1 ^ xoro_s0;
      xoro_s0 <= rotl64(xoro_s0, 24) ^ xoro_s1 ^ (xoro_s1 << 16);
      xoro_s1 <= rotl64(xoro_s1, 37);
    end
  end

  // Data generation with failure injection
  always_comb begin
    prng_data = xoro_result[7:0];

    if (inject_failure) begin
      // Generate stuck-at patterns
      if (failure_bit) begin
        entropy_i = 8'hFF;  // All 1s - worst case stuck-at-high
      end else begin
        entropy_i = 8'h00;  // All 0s - worst case stuck-at-low
      end
    end else begin
      entropy_i = prng_data;  // Normal pseudorandom data
    end
  end

  // Test sequence
  initial begin
    $display("=== Repetition Test Byte Stream Comprehensive Testbench ===");
    $display("Time=%0t: Starting repetition test with failure injection", $time);

    // Initialize signals
    rst_ni = 0;
    enable_i = 0;
    repetition_limit_i = 8'd15; // Default threshold
    inject_failure = 0;
    failure_bit = 0;

    // Reset sequence
    #(CLOCK_PERIOD * 10);
    rst_ni = 1;
    #(CLOCK_PERIOD * 5);

    //=== Test 1: Normal Operation Baseline ===
    $display("\n=== Test 1: Normal Operation Baseline ===");
    enable_i = 1;
    inject_failure = 0;

    #(CLOCK_PERIOD * 500);  // Run for sufficient cycles
    total_tests = total_tests + 1;
    if (status_o == 0) begin
      $display("✓ PASS: Normal operation - no false positives");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Normal operation - unexpected failure detection");
      false_positives = false_positives + 1;
    end

    //=== Test 2: Enable/Disable Functionality ===
    $display("\n=== Test 2: Enable/Disable Functionality ===");
    inject_failure = 1;
    failure_bit = 1; // Stuck-at-1

    // Test with disabled
    enable_i = 0;
    #(CLOCK_PERIOD * 100);
    total_tests = total_tests + 1;
    if (status_o == 0) begin
      $display("✓ PASS: Disabled mode - no failure detection");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Disabled mode - unexpected failure detection");
    end

    // Test with enabled
    enable_i = 1;
    #(CLOCK_PERIOD * 100);
    total_tests = total_tests + 1;
    if (status_o == 1) begin
      $display("✓ PASS: Enabled mode - failure correctly detected");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Enabled mode - failure not detected");
      false_negatives = false_negatives + 1;
    end

    //=== Test 3: Stuck-at-0 Detection ===
    $display("\n=== Test 3: Stuck-at-0 Detection ===");
    inject_failure = 1;
    failure_bit = 0; // Stuck-at-0
    enable_i = 1;

    #(CLOCK_PERIOD * 100);
    total_tests = total_tests + 1;
    if (status_o == 1) begin
      $display("✓ PASS: Stuck-at-0 - failure correctly detected");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Stuck-at-0 - failure not detected");
      false_negatives = false_negatives + 1;
    end

    //=== Test 4: Stuck-at-1 Detection ===
    $display("\n=== Test 4: Stuck-at-1 Detection ===");
    inject_failure = 1;
    failure_bit = 1; // Stuck-at-1
    enable_i = 1;

    #(CLOCK_PERIOD * 100);
    total_tests = total_tests + 1;
    if (status_o == 1) begin
      $display("✓ PASS: Stuck-at-1 - failure correctly detected");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Stuck-at-1 - failure not detected");
      false_negatives = false_negatives + 1;
    end

    //=== Test 5: Recovery After Failure ===
    $display("\n=== Test 5: Recovery After Failure ===");
    inject_failure = 0;  // Switch back to normal data
    #(CLOCK_PERIOD * 200);  // Allow time for recovery

    total_tests = total_tests + 1;
    if (status_o == 0) begin
      $display("✓ PASS: Recovery - failure status cleared");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Recovery - failure status not cleared");
    end

    //=== Test 6: Threshold Boundary Tests ===
    $display("\n=== Test 6: Threshold Boundary Tests ===");

    // Test 6a: Just below threshold (should not trigger)
    repetition_limit_i = 8'd10;
    inject_failure = 0;
    #(CLOCK_PERIOD * 50);

    // Force a pattern that should trigger exactly at threshold
    inject_failure = 1;
    failure_bit = 1;
    #(CLOCK_PERIOD * 8);  // Less than threshold

    inject_failure = 0;
    #(CLOCK_PERIOD * 20);

    total_tests = total_tests + 1;
    if (status_o == 0) begin
      $display("✓ PASS: Below threshold - no false trigger");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Below threshold - unexpected trigger");
      false_positives = false_positives + 1;
    end

    // Test 6b: At threshold (should trigger)
    inject_failure = 1;
    failure_bit = 1;
    #(CLOCK_PERIOD * 15);  // Above threshold

    total_tests = total_tests + 1;
    if (status_o == 1) begin
      $display("✓ PASS: At threshold - correctly triggered");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: At threshold - not triggered");
      false_negatives = false_negatives + 1;
    end

    //=== Test 7: Reset During Operation ===
    $display("\n=== Test 7: Reset During Operation ===");
    inject_failure = 1;
    failure_bit = 1;
    #(CLOCK_PERIOD * 20);  // Build up some repetition count

    // Apply reset and check immediate state
    rst_ni = 0;
    enable_i = 0; // Disable during reset
    #(CLOCK_PERIOD * 5);
    rst_ni = 1;
    #(CLOCK_PERIOD * 2);  // Wait for reset to take effect

    total_tests = total_tests + 1;
    if (status_o == 0 && ctr_repetition_o == 0) begin
      $display("✓ PASS: Reset - all state cleared");
      passed_tests = passed_tests + 1;
    end else begin
      $display("✗ FAIL: Reset - state not properly cleared, status=%d, counter=%d", status_o,
               ctr_repetition_o);
    end

    // Re-enable for normal operation
    enable_i = 1;
    inject_failure = 0; // Turn off failure injection
    #(CLOCK_PERIOD * 10);  // Allow normal operation to resume

    //=== Final Results ===
    $display("\n=== FINAL TEST RESULTS ===");
    $display("Total tests run: %0d", total_tests);
    $display("Total tests passed: %0d", passed_tests);
    $display("False positives: %0d", false_positives);
    $display("False negatives: %0d", false_negatives);
    $display("Overall success rate: %0.1f%%", (100.0 * passed_tests) / total_tests);

    if (passed_tests == total_tests) begin
      $display(
          "\n*** ALL TESTS PASSED! Repetition Test Byte Stream implementation is working correctly. ***");
    end else begin
      $display("\n*** SOME TESTS FAILED! Check implementation. ***");
    end

    $finish;
  end

  // VCD dump for waveform analysis
  initial begin
    $dumpfile("repetition_test_byte_stream.vcd");
    $dumpvars(0, tb_repetition_test_byte_stream);
  end

endmodule
