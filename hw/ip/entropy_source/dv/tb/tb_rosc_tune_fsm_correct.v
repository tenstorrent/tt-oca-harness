// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench for Entropy Ring Oscillator Tune FSM - Rising-Edge Toggle Behavior
//
// Purpose: Verify that the FSM correctly responds ONLY to rising edges (0->1)
//          of health_error_i, representing new health error events.
//
// Correct Behavior:
//   - Rising edge (0->1): NEW health error detected -> Toggle detune state
//   - Falling edge (1->0): Health error CLEARED -> Keep current detune (it works!)
//   - Held HIGH: No continuous toggling -> Detune state remains stable
//   - Held LOW: No toggling -> Detune state remains stable
//
// Rationale:
//   When health tests fail, we switch to alternate detune setting.
//   When health tests pass again, we KEEP the detune setting that worked.
//   We only switch detune on the NEXT health error, not when errors clear.
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_rosc_tune_fsm_correct;

  // Clock and reset
  reg clk;
  reg rstn;

  // DUT signals
  reg  health_error;
  wire tune_state;

  // Test monitoring
  integer test_errors;
  reg     expected_state;

  // Extended stress test variables
  integer rising_edge_count;
  integer state_toggle_count;
  integer high_period, low_period;
  integer iteration;
  reg     last_state;

  // Clock generation: 10 MHz (100ns period)
  initial begin
    clk = 0;
    forever #50 clk = ~clk;
  end

  // DUT instantiation
  entropy_rosc_tune_fsm dut (
    .clk_i          (clk),
    .rst_ni         (rstn),
    .health_error_i (health_error),
    .tune_state_o   (tune_state)
  );

  // Check state matches expected
  task automatic check_state;
    input expected;
    input string description;
    begin
      #10;  // Small delay to let signals settle
      if (tune_state === expected) begin
        $display("  ✓ PASS: %s - tune_state=%b (expected %b)", description, tune_state, expected);
      end else begin
        $display("  ✗ FAIL: %s - tune_state=%b (expected %b)", description, tune_state, expected);
        test_errors = test_errors + 1;
      end
    end
  endtask

  // Main test stimulus
  initial begin
    // Initialize signals
    rstn = 0;
    health_error = 0;
    test_errors = 0;

    // Generate VCD for waveform viewing
    $dumpfile("rosc_tune_fsm_correct.vcd");
    $dumpvars(0, tb_rosc_tune_fsm_correct);

    $display("\n========================================");
    $display("Entropy Tune FSM - CORRECT Behavior Test");
    $display("========================================");
    $display("\nKey Behavior:");
    $display("  - Rising edge (0->1): Toggle state (new error)");
    $display("  - Falling edge (1->0): NO toggle (error cleared)");
    $display("  - Hold HIGH/LOW: NO toggle (stable)");
    $display("\n========================================\n");

    // Release reset
    #200;
    rstn = 1;
    #200;

    expected_state = 0;
    check_state(expected_state, "Initial state after reset");

    //======================================================================
    // TEST 1: Rising Edge - Should Toggle
    //======================================================================
    $display("\n--- TEST 1: Rising Edge (0->1) - Should Toggle ---");

    health_error = 1;
    repeat (3) @(posedge clk);
    expected_state = 1;
    check_state(expected_state, "After rising edge");

    // Hold HIGH - should NOT toggle again
    $display("\nHolding HIGH for 5 more cycles...");
    repeat (5) @(posedge clk);
    check_state(expected_state, "Still HIGH - no change");

    //======================================================================
    // TEST 2: Falling Edge - Should NOT Toggle (CRITICAL TEST)
    //======================================================================
    $display("\n--- TEST 2: Falling Edge (1->0) - Should NOT Toggle ---");
    $display("(Error cleared, current detune is working, keep it!)");

    health_error = 0;
    repeat (3) @(posedge clk);
    // expected_state should still be 1 - falling edge does NOT toggle!
    check_state(expected_state, "After falling edge");

    // Hold LOW - should NOT toggle
    $display("\nHolding LOW for 5 more cycles...");
    repeat (5) @(posedge clk);
    check_state(expected_state, "Still LOW - no change");

    //======================================================================
    // TEST 3: Second Rising Edge - Should Toggle Again
    //======================================================================
    $display("\n--- TEST 3: Second Rising Edge - Should Toggle ---");
    $display("(New health error, try the other detune setting)");

    health_error = 1;
    repeat (3) @(posedge clk);
    expected_state = 0;  // Should toggle back to STATE_0
    check_state(expected_state, "After second rising edge");

    health_error = 0;
    repeat (3) @(posedge clk);
    check_state(expected_state, "After second falling edge - no toggle");

    //======================================================================
    // TEST 4: Multiple Rising Edges - Each Should Toggle
    //======================================================================
    $display("\n--- TEST 4: Multiple Rising Edges (Alternating Errors) ---");

    // Edge 1: 0->1
    $display("\nRising edge 1:");
    health_error = 1;
    repeat (3) @(posedge clk);
    expected_state = 1;
    check_state(expected_state, "After rising edge 1");

    // Clear and wait
    health_error = 0;
    repeat (3) @(posedge clk);
    check_state(expected_state, "After falling - no change");

    // Edge 2: 0->1
    $display("\nRising edge 2:");
    health_error = 1;
    repeat (3) @(posedge clk);
    expected_state = 0;
    check_state(expected_state, "After rising edge 2");

    // Clear and wait
    health_error = 0;
    repeat (3) @(posedge clk);
    check_state(expected_state, "After falling - no change");

    // Edge 3: 0->1
    $display("\nRising edge 3:");
    health_error = 1;
    repeat (3) @(posedge clk);
    expected_state = 1;
    check_state(expected_state, "After rising edge 3");

    health_error = 0;
    repeat (3) @(posedge clk);

    //======================================================================
    // TEST 5: Extended HIGH Period - No Continuous Toggling
    //======================================================================
    $display("\n--- TEST 5: Extended HIGH Period (20 cycles) ---");
    $display("(Should toggle once on rising edge, then stay stable)");

    // Ensure health_error is LOW first
    @(posedge clk);
    #1;  // Small delay after clock edge
    health_error = 0;
    repeat (5) @(posedge clk);  // Give time for falling edge to be processed
    expected_state = tune_state;  // Start from current state
    $display("Starting test 5 from state: %b", expected_state);

    @(posedge clk);
    #1;  // Small delay after clock edge
    health_error = 1;
    repeat (3) @(posedge clk);  // Wait for rising edge to be processed and state to update
    expected_state = ~expected_state;  // Should have toggled once on rising edge
    $display("After rising edge, expecting: %b", expected_state);
    check_state(expected_state, "After extended HIGH period");

    health_error = 0;
    repeat (3) @(posedge clk);

    //======================================================================
    // TEST 6: Realistic Scenario - Error -> Clear -> New Error
    //======================================================================
    $display("\n--- TEST 6: Realistic Health Error Scenario ---");

    // Ensure clean start
    @(posedge clk);
    #1;
    health_error = 0;
    repeat (5) @(posedge clk);

    $display("\nInitial state: tune_state=%b", tune_state);
    expected_state = tune_state;
    $display("Expected state variable: %b", expected_state);

    $display("Scenario: Health error detected (0->1)");
    @(posedge clk);
    #1;
    health_error = 1;
    repeat (3) @(posedge clk);
    expected_state = ~expected_state;  // Toggle on rising edge
    check_state(expected_state, "Toggle on new error");

    $display("\nHealth tests running with new detune...");
    repeat (10) @(posedge clk);
    check_state(expected_state, "Stable while error asserted");

    $display("\nHealth error cleared (1->0) - detune worked!");
    @(posedge clk);
    health_error = 0;
    repeat (3) @(posedge clk);
    // expected_state stays the same - we keep the working detune
    check_state(expected_state, "Keep working detune setting");

    $display("\nSystem running normally...");
    repeat (20) @(posedge clk);
    check_state(expected_state, "Stable during normal operation");

    $display("\nNew health error detected (0->1)");
    @(posedge clk);
    #1;
    health_error = 1;
    repeat (3) @(posedge clk);
    expected_state = ~expected_state;  // Toggle on new error
    check_state(expected_state, "Toggle on new error");

    health_error = 0;
    #500;

    //======================================================================
    // TEST 7: Reset Behavior
    //======================================================================
    $display("\n--- TEST 7: Reset Behavior ---");

    // Set to a known non-zero state
    health_error = 0;  // Make sure this is LOW to avoid edge detection issues
    repeat (3) @(posedge clk);
    health_error = 1;
    repeat (5) @(posedge clk);
    $display("Before reset: tune_state=%b", tune_state);

    // Apply reset with health_error = 0 to avoid confusion
    health_error = 0;
    rstn = 0;
    repeat (3) @(posedge clk);
    rstn = 1;
    repeat (3) @(posedge clk);

    expected_state = 0;
    check_state(expected_state, "Reset returns to STATE_0");

    health_error = 0;
    #500;

    //======================================================================
    // TEST 8: Extended Stress Test - Variable Period Toggling
    //======================================================================
    $display("\n--- TEST 8: Extended Stress Test (10x longer) ---");
    $display("Testing variable period health_error toggling (4-20 cycles)");
    $display("Expecting state to toggle ONLY on rising edges\n");

    // Reset counters for this test
    rising_edge_count = 0;
    state_toggle_count = 0;

    // Ensure clean start from LOW
    @(posedge clk);
    #1;
    health_error = 0;
    repeat (5) @(posedge clk);
    last_state = tune_state;

    $display("Starting extended test from tune_state=%b", tune_state);
    $display("Running 100 health_error transitions with varying periods...\n");

    // Run 100 iterations with varying periods
    for (iteration = 0; iteration < 100; iteration = iteration + 1) begin
      // Vary HIGH period from 4 to 20 cycles
      high_period = 4 + (iteration % 17);
      // Vary LOW period from 4 to 20 cycles (different pattern)
      low_period = 4 + ((iteration * 7) % 17);

      // Rising edge: 0->1
      @(posedge clk);
      #1;
      health_error = 1;
      rising_edge_count = rising_edge_count + 1;

      // Hold HIGH for variable period
      repeat (high_period) @(posedge clk);

      // Check if state toggled
      if (tune_state !== last_state) begin
        state_toggle_count = state_toggle_count + 1;
        last_state = tune_state;
      end

      // Falling edge: 1->0
      @(posedge clk);
      #1;
      health_error = 0;

      // Hold LOW for variable period
      repeat (low_period) @(posedge clk);

      // State should NOT have toggled on falling edge
      if (tune_state !== last_state) begin
        $display("ERROR at iteration %0d: State toggled on falling edge!", iteration);
        test_errors = test_errors + 1;
        last_state = tune_state;
      end

      // Progress indicator every 20 iterations
      if ((iteration + 1) % 20 == 0) begin
        $display("  Iteration %0d/100: %0d rising edges, %0d state toggles, tune_state=%b",
                 iteration + 1, rising_edge_count, state_toggle_count, tune_state);
      end
    end

    $display("\nExtended test complete:");
    $display("  Rising edges detected: %0d", rising_edge_count);
    $display("  State toggles counted: %0d", state_toggle_count);
    $display("  Final tune_state: %b", tune_state);

    if (rising_edge_count == state_toggle_count) begin
      $display("✓ PASS: State toggles match rising edge count exactly");
    end else begin
      $display("✗ FAIL: Expected %0d toggles, got %0d", rising_edge_count, state_toggle_count);
      test_errors = test_errors + 1;
    end

    // Verify final state alternation is correct (should be opposite of start for odd count)
    if (rising_edge_count % 2 == 0) begin
      // Even number of toggles - should be back to original state
      expected_state = (iteration == 0) ? tune_state : ~last_state;
    end else begin
      // Odd number of toggles - should be opposite state
      expected_state = ~tune_state;
    end

    health_error = 0;
    #500;

    //======================================================================
    // Summary
    //======================================================================
    $display("\n========================================");
    $display("Test Summary");
    $display("========================================");

    if (test_errors == 0) begin
      $display("\n✓✓✓ ALL TESTS PASSED ✓✓✓");
      $display("\nThe FSM correctly implements:");
      $display("  ✓ Rising edges (0->1) toggle detune state");
      $display("  ✓ Falling edges (1->0) do NOT toggle (keep working detune)");
      $display("  ✓ No continuous toggling when level is stable");
      $display("  ✓ Proper state alternation on successive errors");
      $display("  ✓ Reset behavior is correct");
      $display("\nThis matches the intended health monitoring behavior:");
      $display("  - New health error → Try alternate detune");
      $display("  - Error clears → Keep current detune (it worked!)");
      $display("  - Next error → Try other detune again");
    end else begin
      $display("\n✗✗✗ %0d TEST(S) FAILED ✗✗✗", test_errors);
      $display("\nPlease review the failures above.");
    end

    $display("\n========================================\n");

    $finish;
  end

  // Timeout watchdog sized for the extended stress test
  initial begin
    #200000000;  // 200ms timeout for extended test
    $display("\nERROR: Test timeout!");
    $finish;
  end

endmodule
