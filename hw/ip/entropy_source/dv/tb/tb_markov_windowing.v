// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench for Entropy Markov Test - Counter Windowing Verification
//
// Purpose: Verify that the windowing mechanism prevents counter saturation
//          and maintains responsive probability tracking over extended runtime.
//
// Tests:
//   1. Demonstrate that counters reach window threshold
//   2. Verify counters are scaled when threshold is reached
//   3. Confirm probabilities remain responsive after scaling
//   4. Test with changing entropy patterns (biased 0s, biased 1s, random)
//   5. Verify continuous operation without saturation
//
// Hazard guarded against:
//   Without windowing, counters saturate at max values, causing probabilities
//   to freeze. The test becomes unresponsive to new entropy data, resulting
//   in false failures or meaningless monitoring.
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_markov_windowing;

  // Clock and reset
  reg clk;
  reg rstn;

  // DUT signals
  reg [31:0] entropy;
  reg        entropy_valid;
  reg        enable;
  reg [7:0]  prob_01_threshold;
  reg [7:0]  prob_10_threshold;
  reg [7:0]  prob_00_threshold;
  reg [7:0]  prob_11_threshold;

  wire [15:0] count_01;
  wire [15:0] count_10;
  wire [15:0] count_00;
  wire [15:0] count_11;
  wire [7:0]  prob_01;
  wire [7:0]  prob_10;
  wire [7:0]  prob_00;
  wire [7:0]  prob_11;
  wire [3:0]  status;

  // Test monitoring
  integer test_errors;
  integer cycle_count;
  integer scaling_events;
  reg [15:0] prev_count_01;
  reg [31:0] total_samples;
  integer initial_scaling_events;
  integer final_scaling_events;
  integer new_scalings;

  // Additional test variables for overflow tests
  integer max_count_observed;
  integer samples_sent;
  integer initial_errors;
  integer prev_total_transitions;
  integer wraparound_detected;
  integer max_count_01, max_count_10, max_count_00, max_count_11;
  integer max_total;
  integer scaling_count_start;
  integer min_count_seen;
  integer samples_in_test;
  integer scaling_count_end;
  integer scalings_in_test;
  integer current_total;
  integer min_current;

  // Clock generation: 10 MHz (100ns period)
  initial begin
    clk = 0;
    forever #50 clk = ~clk;
  end

  // DUT instantiation with reduced window threshold for faster testing
  entropy_markov_test #(
    .DATA_WIDTH(32),
    .WINDOW_THRESHOLD(8000)  // Small window so scaling events occur within the run
  ) dut (
    .clk_i(clk),
    .rst_ni(rstn),
    .entropy_i(entropy),
    .entropy_valid_i(entropy_valid),
    .enable_i(enable),
    .prob_01_threshold_i(prob_01_threshold),
    .prob_10_threshold_i(prob_10_threshold),
    .prob_00_threshold_i(prob_00_threshold),
    .prob_11_threshold_i(prob_11_threshold),
    .count_01_o(count_01),
    .count_10_o(count_10),
    .count_00_o(count_00),
    .count_11_o(count_11),
    .prob_01_o(prob_01),
    .prob_10_o(prob_10),
    .prob_00_o(prob_00),
    .prob_11_o(prob_11),
    .status_o(status)
  );

  // Monitor for counter scaling events
  always @(posedge clk) begin
    if (rstn && enable && entropy_valid) begin
      // Detect scaling: count decreases significantly (halved)
      if (count_01 < (prev_count_01 >> 1) + 100 && prev_count_01 > 1000) begin
        scaling_events = scaling_events + 1;
        $display("  [Cycle %0d] SCALING EVENT #%0d detected!", cycle_count, scaling_events);
        $display("    count_01: %0d -> %0d", prev_count_01, count_01);
        $display("    Probabilities: 01=%0d, 10=%0d, 00=%0d, 11=%0d", prob_01, prob_10, prob_00,
                 prob_11);
      end
      prev_count_01 = count_01;
      cycle_count = cycle_count + 1;
    end
  end

  // Simple LFSR for pseudo-random entropy generation
  reg [31:0] lfsr;

  task automatic generate_random_entropy;
    begin
      // 32-bit Galois LFSR with feedback polynomial
      lfsr = {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
      entropy = lfsr;
    end
  endtask

  // Generate biased pattern (more 0->1 transitions)
  task automatic generate_biased_01_pattern;
    begin
      entropy = 32'h55555555;  // Alternating 01 pattern
    end
  endtask

  // Generate biased pattern (more 1->0 transitions)
  task automatic generate_biased_10_pattern;
    begin
      entropy = 32'hAAAAAAAA;  // Alternating 10 pattern
    end
  endtask

  // Generate biased pattern (more 0->0 transitions)
  task automatic generate_biased_00_pattern;
    begin
      entropy = 32'h00000000;  // All zeros
    end
  endtask

  // Generate biased pattern (more 1->1 transitions)
  task automatic generate_biased_11_pattern;
    begin
      entropy = 32'hFFFFFFFF;  // All ones
    end
  endtask

  // Check task
  task automatic check_probabilities;
    input string description;
    input integer expected_01_min;
    input integer expected_01_max;
    begin
      $display("  Check: %s", description);
      $display("    Probabilities: 01=%0d, 10=%0d, 00=%0d, 11=%0d", prob_01, prob_10, prob_00,
               prob_11);
      $display("    Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
               count_11);

      if (prob_01 >= expected_01_min && prob_01 <= expected_01_max) begin
        $display("    ✓ PASS: prob_01 in expected range [%0d, %0d]", expected_01_min,
                 expected_01_max);
      end else begin
        $display("    ✗ FAIL: prob_01=%0d outside expected range [%0d, %0d]", prob_01,
                 expected_01_min, expected_01_max);
        test_errors = test_errors + 1;
      end
    end
  endtask

  // Main test stimulus
  initial begin
    // Initialize signals
    rstn = 0;
    entropy = 32'd0;
    entropy_valid = 0;
    enable = 0;
    prob_01_threshold = 8'd200;  // High thresholds to avoid false failures
    prob_10_threshold = 8'd200;
    prob_00_threshold = 8'd200;
    prob_11_threshold = 8'd200;
    test_errors = 0;
    cycle_count = 0;
    scaling_events = 0;
    prev_count_01 = 16'd0;
    total_samples = 32'd0;
    lfsr = 32'hACE1;  // Initial LFSR seed

    // Generate VCD for waveform viewing
    $dumpfile("markov_windowing.vcd");
    $dumpvars(0, tb_markov_windowing);

    $display("\n========================================");
    $display("Markov Test - Windowing Mechanism Test");
    $display("========================================");
    $display("Window Threshold: 8000 transitions");
    $display("Testing counter scaling and probability responsiveness\n");

    // Release reset
    #200;
    rstn = 1;
    #200;
    enable = 1;
    entropy_valid = 1;

    //======================================================================
    // TEST 1: Fill counters to window threshold with balanced pattern
    //======================================================================
    $display("\n--- TEST 1: Fill Counters to Window Threshold ---");
    $display("Sending random entropy until first scaling event...\n");

    // Send ~250 samples (250 * 32 = 8000 transitions)
    for (int i = 0; i < 250; i++) begin
      generate_random_entropy();
      @(posedge clk);
      total_samples = total_samples + 1;

      if (i % 50 == 49) begin
        $display("  [Sample %0d] Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d, Total~%0d", i + 1,
                 count_01, count_10, count_00, count_11, count_01 + count_10 + count_00 + count_11);
      end
    end

    #500;

    if (scaling_events > 0) begin
      $display("\n✓ PASS: Scaling event occurred after ~8000 transitions");
    end else begin
      $display("\n✗ FAIL: No scaling event detected");
      test_errors = test_errors + 1;
    end

    //======================================================================
    // TEST 2: Verify Probabilities Responsive After Scaling
    //======================================================================
    $display("\n--- TEST 2: Probability Responsiveness After Scaling ---");
    $display("Switching to biased 0->1 pattern (expect high prob_01)...\n");

    // Reset scaling event counter
    prev_count_01 = count_01;

    // Send 100 samples of biased 01 pattern
    for (int i = 0; i < 100; i++) begin
      generate_biased_01_pattern();
      @(posedge clk);
      total_samples = total_samples + 1;
    end

    #500;
    check_probabilities("After biased 01 pattern", 50, 255);

    //======================================================================
    // TEST 3: Switch Pattern and Verify Response
    //======================================================================
    $display("\n--- TEST 3: Pattern Switch Response ---");
    $display("Switching to biased 1->0 pattern (expect high prob_10)...\n");

    // Send 100 samples of biased 10 pattern
    for (int i = 0; i < 100; i++) begin
      generate_biased_10_pattern();
      @(posedge clk);
      total_samples = total_samples + 1;
    end

    #500;

    $display("  Check: After biased 10 pattern");
    $display("    Probabilities: 01=%0d, 10=%0d, 00=%0d, 11=%0d", prob_01, prob_10, prob_00,
             prob_11);
    $display("    Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
             count_11);

    // Note: alternating patterns create equal 01 and 10 transitions
    // So we just verify both are high (> 80) and 00/11 are low (< 30)
    if (prob_01 > 80 && prob_10 > 80 && prob_00 < 30 && prob_11 < 30) begin
      $display("    ✓ PASS: Transition probabilities show alternating pattern");
    end else begin
      $display("    ✗ FAIL: Expected high 01/10, low 00/11");
      test_errors = test_errors + 1;
    end

    //======================================================================
    // TEST 4: Multiple Scaling Events
    //======================================================================
    $display("\n--- TEST 4: Multiple Scaling Events ---");
    $display("Running extended test with multiple scaling events...\n");

    initial_scaling_events = scaling_events;

    // Send 1000 samples to trigger multiple scalings (1000 * 32 = 32K transitions)
    for (int i = 0; i < 1000; i++) begin
      generate_random_entropy();
      @(posedge clk);
      total_samples = total_samples + 1;

      if (i % 200 == 199) begin
        $display("  [Sample %0d] Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", total_samples,
                 count_01, count_10, count_00, count_11);
        $display("              Probs: 01=%0d, 10=%0d, 00=%0d, 11=%0d", prob_01, prob_10, prob_00,
                 prob_11);
      end
    end

    #500;

    final_scaling_events = scaling_events;
    new_scalings = final_scaling_events - initial_scaling_events;

    $display("\nScaling events during test: %0d", new_scalings);

    if (new_scalings >= 3) begin
      $display("✓ PASS: Multiple scaling events occurred (%0d events)", new_scalings);
    end else begin
      $display("✗ FAIL: Expected at least 3 scaling events, got %0d", new_scalings);
      test_errors = test_errors + 1;
    end

    //======================================================================
    // TEST 5: Verify Counters Never Saturate
    //======================================================================
    $display("\n--- TEST 5: Counter Saturation Prevention ---");

    // Check that counters are well below saturation point
    if (count_01 < 16'hF000 && count_10 < 16'hF000 &&
            count_00 < 16'hF000 && count_11 < 16'hF000) begin
      $display("✓ PASS: All counters well below saturation (< 61,440)");
      $display("  Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
               count_11);
    end else begin
      $display("✗ FAIL: Counter(s) approaching saturation");
      $display("  Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
               count_11);
      test_errors = test_errors + 1;
    end

    //======================================================================
    // TEST 6: Final Pattern Switch Responsiveness
    //======================================================================
    $display("\n--- TEST 6: Final Responsiveness Check ---");
    $display("Switching to biased 00 pattern (expect high prob_00)...\n");

    // Send 150 samples of biased 00 pattern
    for (int i = 0; i < 150; i++) begin
      generate_biased_00_pattern();
      @(posedge clk);
      total_samples = total_samples + 1;
    end

    #500;

    $display("  Final probabilities: 01=%0d, 10=%0d, 00=%0d, 11=%0d", prob_01, prob_10, prob_00,
             prob_11);

    if (prob_00 > prob_01 && prob_00 > prob_10 && prob_00 > prob_11) begin
      $display("  ✓ PASS: prob_00 is dominant as expected");
    end else begin
      $display("  ✗ FAIL: prob_00 should be dominant after 00 pattern");
      test_errors = test_errors + 1;
    end

    #500;

    //======================================================================
    // TEST 7: Overflow Attack - Extreme Biased Pattern
    //======================================================================
    $display("\n--- TEST 7: Overflow Attack - Extreme Biased Pattern ---");
    $display("Attempting to saturate count_11 with all-ones pattern...");
    $display("Goal: Verify windowing prevents counter overflow\n");

    max_count_observed = 0;
    samples_sent = 0;

    // Send 2000 samples of all-ones (creates only 11 transitions)
    // This should maximize count_11 while others stay low
    for (int i = 0; i < 2000; i++) begin
      generate_biased_11_pattern();
      @(posedge clk);
      total_samples = total_samples + 1;
      samples_sent = samples_sent + 1;

      // Track maximum counter value seen
      if (count_11 > max_count_observed) begin
        max_count_observed = count_11;
      end

      // Monitor for any counter overflow
      if (count_01 == 16'hFFFF || count_10 == 16'hFFFF ||
                count_00 == 16'hFFFF || count_11 == 16'hFFFF) begin
        $display("  ✗ ERROR: Counter overflow detected at sample %0d!", samples_sent);
        $display("    Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
                 count_11);
        test_errors = test_errors + 1;
      end

      if (i % 400 == 399) begin
        $display("  [Sample %0d] count_11=%0d (max=%0d), scalings=%0d", samples_sent, count_11,
                 max_count_observed, scaling_events);
      end
    end

    #500;

    $display("\nOverflow attack results:");
    $display("  Samples sent: %0d", samples_sent);
    $display("  Total transitions: ~%0d", samples_sent * 32);
    $display("  Max count_11 observed: %0d", max_count_observed);
    $display("  Final counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
             count_11);

    if (max_count_observed < 16'hF000) begin
      $display("  ✓ PASS: count_11 stayed below 61,440 (< 94% of max)");
    end else begin
      $display("  ✗ FAIL: count_11 reached dangerous level: %0d", max_count_observed);
      test_errors = test_errors + 1;
    end

    //======================================================================
    // TEST 8: Overflow Attack - Massive Sample Count
    //======================================================================
    $display("\n--- TEST 8: Overflow Attack - Massive Sample Count ---");
    $display("Sending 5000 samples to stress test windowing...");
    $display("Goal: Verify no overflow even with extreme load\n");

    initial_errors = test_errors;
    wraparound_detected = 0;
    prev_total_transitions = 0;

    for (int i = 0; i < 5000; i++) begin
      generate_random_entropy();
      @(posedge clk);
      total_samples = total_samples + 1;

      // Check for total_transitions wraparound (should never happen)
      // A drop to about half is the windowing scale-down, not a wraparound
      // Only flag if sum increases but individual counter overflowed
      current_total = count_01 + count_10 + count_00 + count_11;
      if (current_total < (prev_total_transitions / 2) && prev_total_transitions < 16000) begin
        // Total dropped but not from scaling (which happens at ~8000)
        if (wraparound_detected == 0) begin
          $display("  ✗ ERROR: total_transitions wraparound detected at sample %0d!",
                   total_samples);
          wraparound_detected = 1;
          test_errors = test_errors + 1;
        end
      end
      prev_total_transitions = current_total;

      // Check for any counter overflow
      if (count_01 == 16'hFFFF || count_10 == 16'hFFFF ||
                count_00 == 16'hFFFF || count_11 == 16'hFFFF) begin
        $display("  ✗ ERROR: Counter overflow at sample %0d!", total_samples);
        test_errors = test_errors + 1;
      end

      if (i % 1000 == 999) begin
        $display("  [Sample %0d] Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d, scalings=%0d",
                 total_samples, count_01, count_10, count_00, count_11, scaling_events);
      end
    end

    #500;

    $display("\nMassive load test results:");
    $display("  Total samples processed: %0d", total_samples);
    $display("  Total transitions: ~%0d", total_samples * 32);
    $display("  Scaling events: %0d", scaling_events);
    $display("  Final counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
             count_11);

    if (test_errors == initial_errors) begin
      $display("  ✓ PASS: No overflows detected during massive load test");
    end else begin
      $display("  ✗ FAIL: %0d overflow(s) detected", test_errors - initial_errors);
    end

    //======================================================================
    // TEST 9: Hard Limit Verification
    //======================================================================
    $display("\n--- TEST 9: Hard Limit Verification ---");
    $display("Verifying absolute counter limits are respected...\n");

    max_count_01 = 0;
    max_count_10 = 0;
    max_count_00 = 0;
    max_count_11 = 0;
    max_total = 0;

    // Send another 1000 samples and track maximums
    for (int i = 0; i < 1000; i++) begin
      generate_random_entropy();
      @(posedge clk);
      total_samples = total_samples + 1;

      if (count_01 > max_count_01) max_count_01 = count_01;
      if (count_10 > max_count_10) max_count_10 = count_10;
      if (count_00 > max_count_00) max_count_00 = count_00;
      if (count_11 > max_count_11) max_count_11 = count_11;

      current_total = count_01 + count_10 + count_00 + count_11;
      if (current_total > max_total) max_total = current_total;
    end

    #500;

    $display("Maximum values observed:");
    $display("  max count_01: %0d (%.1f%% of 65535)", max_count_01,
             (max_count_01 * 100.0) / 65535.0);
    $display("  max count_10: %0d (%.1f%% of 65535)", max_count_10,
             (max_count_10 * 100.0) / 65535.0);
    $display("  max count_00: %0d (%.1f%% of 65535)", max_count_00,
             (max_count_00 * 100.0) / 65535.0);
    $display("  max count_11: %0d (%.1f%% of 65535)", max_count_11,
             (max_count_11 * 100.0) / 65535.0);
    $display("  max total transitions: %0d (%.1f%% of 262143)", max_total,
             (max_total * 100.0) / 262143.0);

    // Define "safe zone" as < 50% of maximum
    if (max_count_01 < 32768 && max_count_10 < 32768 &&
            max_count_00 < 32768 && max_count_11 < 32768 &&
            max_total < 131072) begin
      $display("  ✓ PASS: All counters stayed in safe zone (< 50% of max)");
    end else begin
      $display("  ✗ FAIL: Counter(s) exceeded safe zone");
      test_errors = test_errors + 1;
    end

    //======================================================================
    // TEST 10: Windowing Effectiveness Over Time
    //======================================================================
    $display("\n--- TEST 10: Windowing Effectiveness Over Time ---");
    $display("Verifying windowing keeps counters bounded over extended runtime...\n");

    scaling_count_start = scaling_events;
    min_count_seen = 65535;
    samples_in_test = 0;

    // Run for another 2000 samples
    for (int i = 0; i < 2000; i++) begin
      generate_random_entropy();
      @(posedge clk);
      total_samples = total_samples + 1;
      samples_in_test = samples_in_test + 1;

      // Track minimum counter value (should not go to zero from scaling too aggressively)
      min_current = count_01;
      if (count_10 < min_current) min_current = count_10;
      if (count_00 < min_current) min_current = count_00;
      if (count_11 < min_current) min_current = count_11;
      if (min_current < min_count_seen) min_count_seen = min_current;

      if (i % 500 == 499) begin
        $display("  [Sample %0d] Counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", samples_in_test,
                 count_01, count_10, count_00, count_11);
      end
    end

    #500;

    scaling_count_end = scaling_events;
    scalings_in_test = scaling_count_end - scaling_count_start;

    $display("\nWindowing effectiveness:");
    $display("  Samples processed: %0d", samples_in_test);
    $display("  Transitions: ~%0d", samples_in_test * 32);
    $display("  Scaling events: %0d", scalings_in_test);
    $display("  Minimum counter value: %0d", min_count_seen);
    $display("  Final counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
             count_11);

    // Verify windowing occurred
    if (scalings_in_test >= 6) begin
      $display("  ✓ PASS: Adequate windowing occurred (%0d events)", scalings_in_test);
    end else begin
      $display("  ✗ FAIL: Insufficient windowing (%0d events, expected >= 6)", scalings_in_test);
      test_errors = test_errors + 1;
    end

    // Verify counters didn't drop too low (would indicate over-aggressive scaling)
    if (min_count_seen > 100) begin
      $display("  ✓ PASS: Counters maintained reasonable minimum (%0d)", min_count_seen);
    end else begin
      $display("  ✗ FAIL: Counters dropped too low (%0d), scaling too aggressive",
               min_count_seen);
      test_errors = test_errors + 1;
    end

    #500;

    //======================================================================
    // Summary
    //======================================================================
    $display("\n========================================");
    $display("Test Summary");
    $display("========================================");
    $display("Total samples processed: %0d", total_samples);
    $display("Total transitions: ~%0d", total_samples * 32);
    $display("Scaling events: %0d", scaling_events);
    $display("Final counters: 01=%0d, 10=%0d, 00=%0d, 11=%0d", count_01, count_10, count_00,
             count_11);

    if (test_errors == 0) begin
      $display("\n✓✓✓ ALL TESTS PASSED ✓✓✓");
      $display("\nThe windowing mechanism correctly:");
      $display("  ✓ Triggers scaling at window threshold");
      $display("  ✓ Maintains probability responsiveness");
      $display("  ✓ Prevents counter saturation");
      $display("  ✓ Handles multiple scaling events");
      $display("  ✓ Responds to pattern changes");
      $display("  ✓ Resists overflow attacks with extreme patterns");
      $display("  ✓ Handles massive sample counts without wraparound");
      $display("  ✓ Maintains counters in safe zone (< 50%% of max)");
      $display("  ✓ Balances windowing frequency and counter stability");
    end else begin
      $display("\n✗✗✗ %0d TEST(S) FAILED ✗✗✗", test_errors);
      $display("\nPlease review the failures above.");
    end

    $display("\n========================================\n");

    $finish;
  end

  // Timeout watchdog - extended for overflow attack tests
  initial begin
    #2000000000;  // 2 second timeout for extended tests
    $display("\nERROR: Test timeout!");
    $finish;
  end

endmodule
