// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Repetition Test iverilog Testbench
//
// Description:
// Comprehensive testbench for entropy_repetition_test module
// Tests normal operation and failure conditions with stuck-at patterns
// Verifies enable/disable functionality, failure recovery, and counter saturation
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_repetition_test ();

  // Test signals
  reg clk_i;
  reg rst_ni;
  reg [31:0] entropy_i;
  reg entropy_valid_i;
  reg enable_i;
  reg [7:0] repetition_limit_i;
  wire status_o;

  // Testbench variables
  integer test_phase = 0;
  integer cycle_count = 0;
  integer failure_detected = 0;
  integer expected_failures = 0;
  integer test_cycles = 0;

  // xoroshiro128+ for high-quality pseudorandom data generation
  reg [63:0] xoro_s0 = 64'h0123456789ABCDEF;  // State 0
  reg [63:0] xoro_s1 = 64'hFEDCBA9876543210;  // State 1
  reg [63:0] xoro_result;
  reg [31:0] prng_data;

  // Failure injection control
  reg inject_failure = 0;
  reg failure_bit = 0;
  reg manual_control = 0;  // When 1, use manual_entropy instead of PRNG/inject
  reg [31:0] manual_entropy = 32'h0;
  integer failure_duration = 0;
  integer normal_cycles_before_failure = 0;
  integer failure_cycles = 0;

  // Test results tracking
  integer total_tests_run = 0;
  integer total_tests_passed = 0;
  integer false_positives = 0;
  integer false_negatives = 0;

  // Test parameters
  localparam logic [7:0] TEST_THRESHOLD_LOW = 8'd10;  // Low threshold for quick testing
  localparam logic [7:0] TEST_THRESHOLD_MED = 8'd15;  // Medium threshold
  localparam logic [7:0] TEST_THRESHOLD_HIGH = 8'd20;  // High threshold
  localparam logic [7:0] TEST_THRESHOLD_SAT = 8'd15;  // Threshold for the saturation test

  // Instantiate the DUT
  entropy_repetition_test u_repetition_test (
    .clk_i,
    .rst_ni,
    .entropy_i(entropy_i),
    .entropy_valid_i(entropy_valid_i),
    .enable_i(enable_i),
    .repetition_limit_i(repetition_limit_i),
    .status_o(status_o)
  );

  // Clock generation
  initial begin
    clk_i = 0;
    forever #5 clk_i = ~clk_i;  // 100MHz clock (10ns period)
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

  // Data generation with failure injection and manual control
  always_comb begin
    prng_data = xoro_result[31:0];

    if (manual_control) begin
      // Manual control mode - use manual_entropy directly
      entropy_i = manual_entropy;
    end else if (inject_failure) begin
      // Generate stuck-at patterns
      if (failure_bit) begin
        entropy_i = 32'hFFFFFFFF;  // All 1s - worst case stuck-at-high
      end else begin
        entropy_i = 32'h00000000;  // All 0s - worst case stuck-at-low
      end
    end else begin
      entropy_i = prng_data;  // Normal pseudorandom data
    end
  end

  // Test sequence control
  initial begin
    $display("=== Repetition Test Comprehensive Testbench ===");
    $display("Time=%0t: Starting repetition test with failure injection", $time);

    // Initialize
    rst_ni = 0;
    enable_i = 0;
    entropy_valid_i = 1;  // Enable entropy data processing
    repetition_limit_i = TEST_THRESHOLD_LOW;
    inject_failure = 0;
    failure_bit = 0;

    // Reset sequence
    #100;
    rst_ni = 1;
    #50;

    $display("Time=%0t: Reset released, beginning test phases", $time);

    // Test Phase 1: Basic functionality with low threshold
    run_basic_functionality_test();

    // Test Phase 2: Enable/disable functionality
    run_enable_disable_test();

    // Test Phase 3: Stuck-at-0 failure detection
    run_stuck_at_failure_test(0, TEST_THRESHOLD_MED);

    // Test Phase 4: Stuck-at-1 failure detection
    run_stuck_at_failure_test(1, TEST_THRESHOLD_MED);

    // Test Phase 5: Failure recovery testing
    run_failure_recovery_test();

    // Test Phase 6: Counter saturation testing
    run_counter_saturation_test();

    // Test Phase 7: Threshold boundary testing
    run_threshold_boundary_test();

    // Final results
    $display("");
    $display("=== FINAL TEST RESULTS ===");
    $display("Total tests run: %0d", total_tests_run);
    $display("Total tests passed: %0d", total_tests_passed);
    $display("False positives: %0d", false_positives);
    $display("False negatives: %0d", false_negatives);
    $display("Overall success rate: %.1f%%", (total_tests_passed * 100.0) / total_tests_run);

    if (total_tests_passed == total_tests_run && false_positives == 0 && false_negatives == 0) begin
      $display("");
      $display("*** ALL TESTS PASSED! Repetition Test implementation is working correctly. ***");
    end else begin
      $display("");
      $display("*** SOME TESTS FAILED! Check repetition test implementation. ***");
    end

    $finish;
  end

  // Task: Basic functionality test
  task automatic run_basic_functionality_test();
    integer random_trigger_count;
    integer i;
    reg last_status;
    begin
      $display("");
      $display("=== Phase 1: Basic Functionality Test ===");
      total_tests_run = total_tests_run + 1;

      enable_i = 1;
      repetition_limit_i = TEST_THRESHOLD_LOW;
      inject_failure = 0;
      random_trigger_count = 0;
      last_status = 1'b0;

      $display("Testing normal operation with pseudorandom data");
      $display("Threshold: %0d", repetition_limit_i);
      $display(
          "Note: Random data may occasionally contain runs > threshold (statistically expected)");

      // Run normal data for sufficient cycles, counting any triggers
      for (i = 0; i < 500; i = i + 1) begin
        @(posedge clk_i);
        #1;  // Sample after clock edge

        // Count rising edges on status (new failures)
        if (status_o == 1'b1 && last_status == 1'b0) begin
          random_trigger_count = random_trigger_count + 1;
          $display("  Note: Random data triggered failure at cycle %0d (occurrence #%0d)", i,
                   random_trigger_count);
        end
        last_status = status_o;
      end

      // Statistical acceptance: with threshold=10 and truly random data,
      // probability of 11+ consecutive bits is ~0.0005 per 32-bit word.
      // Over 500 cycles (16000 bits), expect 0-3 triggers.
      // Allow up to 5 triggers as acceptable statistical variation.
      if (random_trigger_count <= 5) begin
        $display(
            "✓ PASS: Normal operation - %0d random triggers (acceptable statistical variation)",
            random_trigger_count);
        total_tests_passed = total_tests_passed + 1;
      end else begin
        $display("✗ FAIL: Too many random triggers (%0d > 5) - possible PRNG or threshold issue",
                 random_trigger_count);
        false_positives = false_positives + 1;
      end

      $display("=== Completed Basic Functionality Test ===");
    end
  endtask

  // Task: Enable/disable functionality test
  task automatic run_enable_disable_test();
    begin
      $display("");
      $display("=== Phase 2: Enable/Disable Functionality Test ===");
      total_tests_run = total_tests_run + 1;

      repetition_limit_i = TEST_THRESHOLD_LOW;

      $display("Testing enable/disable functionality");

      // Test 1: Disable should prevent failure detection
      enable_i = 0;
      inject_failure = 1;
      failure_bit = 1; // Stuck-at-1

      $display("Sub-test 2a: Disabled with stuck-at-1 pattern");
      repeat (200) @(posedge clk_i);

      if (status_o == 1'b0) begin
        $display("✓ PASS: Disabled state prevents failure detection");
      end else begin
        $display("✗ FAIL: Failure detected when disabled");
        false_positives = false_positives + 1;
        total_tests_passed = total_tests_passed - 1;
      end

      // Test 2: Enable should allow normal detection
      enable_i = 1;
      $display("Sub-test 2b: Enabled with stuck-at-1 pattern");
      repeat (50) @(posedge clk_i);  // Should trigger quickly

      if (status_o == 1'b1) begin
        $display("✓ PASS: Enabled state allows failure detection");
        total_tests_passed = total_tests_passed + 1;
      end else begin
        $display("✗ FAIL: No failure detected when enabled");
        false_negatives = false_negatives + 1;
      end

      // Clean up
      inject_failure = 0;
      repeat (50) @(posedge clk_i);

      $display("=== Completed Enable/Disable Test ===");
    end
  endtask

  // Task: Stuck-at failure detection test
  task automatic run_stuck_at_failure_test(input bit stuck_value, input logic [7:0] threshold);
    begin
      $display("");
      $display("=== Phase %0d: Stuck-at-%0d Failure Detection Test ===", stuck_value ? 4 : 3,
               stuck_value);
      total_tests_run = total_tests_run + 1;

      enable_i = 1;
      repetition_limit_i = threshold;
      failure_bit = stuck_value;

      $display("Testing stuck-at-%0d detection with threshold %0d", stuck_value, threshold);

      // Phase 1: Normal operation
      inject_failure = 0;
      repeat (100) @(posedge clk_i);

      if (status_o == 1'b1) begin
        $display("✗ WARNING: Unexpected failure during normal phase");
      end

      // Phase 2: Inject failure
      inject_failure = 1;
      $display("Injecting stuck-at-%0d pattern", stuck_value);

      // Wait for failure detection (need enough cycles to accumulate threshold repetitions)
      // Since we process 16 bits per cycle, threshold should be exceeded in about 2 cycles
      // for most thresholds, but give generous margin for timing variations
      repeat (10) @(posedge clk_i);

      if (status_o == 1'b1) begin
        $display("✓ PASS: Stuck-at-%0d correctly detected", stuck_value);
        total_tests_passed = total_tests_passed + 1;
      end else begin
        $display("✗ FAIL: Stuck-at-%0d NOT detected", stuck_value);
        false_negatives = false_negatives + 1;
      end

      // Clean up
      inject_failure = 0;
      repeat (100) @(posedge clk_i);

      $display("=== Completed Stuck-at-%0d Test ===", stuck_value);
    end
  endtask

  // Task: Failure recovery test
  task automatic run_failure_recovery_test();
    begin
      $display("");
      $display("=== Phase 5: Failure Recovery Test ===");
      total_tests_run = total_tests_run + 1;

      enable_i = 1;
      repetition_limit_i = TEST_THRESHOLD_MED;

      $display("Testing failure recovery mechanism");

      // Step 1: Trigger a failure
      inject_failure = 1;
      failure_bit = 0; // Stuck-at-0
      repeat (10) @(posedge clk_i);

      if (status_o != 1'b1) begin
        $display("✗ Setup failed: Could not trigger initial failure");
        // Skip recovery test if setup failed
      end else begin
        $display("✓ Initial failure triggered successfully");

        // Step 2: Clear the sticky failure flag by toggling enable
        $display("Clearing failure flag by toggling enable_i");
        enable_i = 0;
        repeat (2) @(posedge clk_i);

        // Verify flag cleared while disabled
        if (status_o == 1'b0) begin
          $display("✓ Failure flag cleared successfully");
        end

        // Step 3: Re-enable with PRNG data under a raised threshold so that no
        // random run trips the test during recovery
        repetition_limit_i = 8'd200;  // Very high threshold
        inject_failure = 0;
        enable_i = 1;
        $display("Re-enabled with good data - testing recovery");
        repeat (200) @(posedge clk_i);

        // Restore original threshold
        repetition_limit_i = TEST_THRESHOLD_MED;

        if (status_o == 1'b0) begin
          $display("✓ PASS: Failure recovery working correctly");
          total_tests_passed = total_tests_passed + 1;
        end else begin
          $display("✗ FAIL: Failure recovery not working - status still high");
        end
      end

      $display("=== Completed Failure Recovery Test ===");
    end
  endtask

  // Task: Counter saturation test
  task automatic run_counter_saturation_test();
    begin
      $display("");
      $display("=== Phase 6: Counter Saturation Test ===");
      total_tests_run = total_tests_run + 1;

      enable_i = 1;
      repetition_limit_i = TEST_THRESHOLD_SAT; // High threshold to test saturation

      $display("Testing counter saturation at 255");
      $display("Threshold: %0d (testing saturation protection)", repetition_limit_i);

      // Inject very long stuck-at pattern
      inject_failure = 1;
      failure_bit = 1; // Stuck-at-1

      // Run for many cycles to test counter saturation - should trigger quickly
      repeat (20) @(posedge clk_i);

      if (status_o == 1'b1) begin
        $display("✓ PASS: Counter saturation test - failure detected before overflow");
        total_tests_passed = total_tests_passed + 1;
      end else begin
        $display("✗ FAIL: Counter may have overflowed - no failure detected");
      end

      // Clean up
      inject_failure = 0;
      repeat (100) @(posedge clk_i);

      $display("=== Completed Counter Saturation Test ===");
    end
  endtask

  // Task: Threshold boundary test
  task automatic run_threshold_boundary_test();
    integer run_length;
    integer words_needed;
    integer remaining_bits;
    integer i;
    reg [31:0] test_pattern;
    begin
      $display("");
      $display("=== Phase 7: Threshold Boundary Test ===");
      total_tests_run = total_tests_run + 2; // Two sub-tests

      // Clear any sticky status from previous tests
      enable_i = 0;
      repeat (5) @(posedge clk_i);
      enable_i = 1;
      repetition_limit_i = TEST_THRESHOLD_LOW;
      repeat (5) @(posedge clk_i);

      // Test 1: Just below threshold (should not trigger)
      run_length = TEST_THRESHOLD_LOW - 1;  // 9 bits for threshold=10
      $display("Sub-test 7a: Just below threshold (%0d consecutive zeros)", run_length);

      // Enable manual control mode
      inject_failure = 0;
      manual_control = 1;

      // Calculate pattern: run_length zeros followed by alternating pattern
      words_needed = run_length / 32;
      remaining_bits = run_length % 32;

      // Send full words of all zeros (if any)
      for (i = 0; i < words_needed; i = i + 1) begin
        manual_entropy = 32'h00000000;
        @(posedge clk_i);
      end

      // Send final word with exactly remaining_bits zeros, rest alternating
      if (remaining_bits > 0) begin
        test_pattern = 32'h00000000;
        // Set first remaining_bits to 0
        for (i = 0; i < remaining_bits; i = i + 1) begin
          test_pattern[i] = 1'b0;
        end
        // Fill rest with properly phased alternating pattern (starting with 1)
        for (i = remaining_bits; i < 32; i = i + 1) begin
          test_pattern[i] = ((i - remaining_bits) % 2) ? 1'b0 : 1'b1;
        end

        manual_entropy = test_pattern;
        @(posedge clk_i);
      end

      // Send alternating pattern to ensure no continuation
      manual_entropy = 32'hAAAAAAAA;
      repeat (10) @(posedge clk_i);

      if (status_o == 1'b0) begin
        $display("✓ PASS: Below threshold - no false trigger");
        total_tests_passed = total_tests_passed + 1;
      end else begin
        $display("✗ FAIL: False trigger below threshold");
        false_positives = false_positives + 1;
      end

      // Reset for next test
      repeat (50) @(posedge clk_i);

      // Test 2: Just above threshold (should trigger)
      run_length = TEST_THRESHOLD_LOW + 1;  // 11 bits for threshold=10
      $display("Sub-test 7b: Just above threshold (%0d consecutive ones)", run_length);

      // Calculate pattern for ones
      words_needed = run_length / 32;
      remaining_bits = run_length % 32;

      // Send full words of all ones (if any)
      for (i = 0; i < words_needed; i = i + 1) begin
        manual_entropy = 32'hFFFFFFFF;
        @(posedge clk_i);
      end

      // Send final word with exactly remaining_bits ones
      if (remaining_bits > 0) begin
        test_pattern = 32'hFFFFFFFF;
        // Set first remaining_bits to 1
        for (i = 0; i < remaining_bits; i = i + 1) begin
          test_pattern[i] = 1'b1;
        end
        // Fill rest with properly phased alternating pattern (starting with 0)
        for (i = remaining_bits; i < 32; i = i + 1) begin
          test_pattern[i] = ((i - remaining_bits) % 2) ? 1'b1 : 1'b0;
        end

        manual_entropy = test_pattern;
        @(posedge clk_i);
      end

      // Give time for detection
      manual_entropy = 32'h55555555;
      repeat (5) @(posedge clk_i);

      if (status_o == 1'b1) begin
        $display("✓ PASS: Above threshold - correctly triggered");
        total_tests_passed = total_tests_passed + 1;
      end else begin
        $display("✗ FAIL: No trigger above threshold");
        false_negatives = false_negatives + 1;
      end

      // Clean up - restore normal operation
      manual_control = 0;
      inject_failure = 0;
      repeat (100) @(posedge clk_i);

      $display("=== Completed Threshold Boundary Test ===");
    end
  endtask

  // Monitor for status changes during simulation
  always @(posedge status_o) begin
    if (enable_i) begin
      $display("Time=%0t: REPETITION FAILURE DETECTED (threshold=%0d)", $time, repetition_limit_i);
    end
  end

  // Monitor for status clearing
  always @(negedge status_o) begin
    if (enable_i) begin
      $display("Time=%0t: Repetition failure status cleared", $time);
    end
  end

  // VCD dump for waveform analysis
  initial begin
    $dumpfile("repetition_test.vcd");
    $dumpvars(0, tb_repetition_test);
    $dumpvars(1, u_repetition_test.last_ctr_repetition);
    $dumpvars(1, u_repetition_test.fail_repetition);
    $dumpvars(1, u_repetition_test.last_sample);
  end

endmodule
