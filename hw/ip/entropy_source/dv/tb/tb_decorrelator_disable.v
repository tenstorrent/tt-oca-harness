// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Testbench: Decorrelator Disable Behaviour
//
// Description:
// Verifies that entropy_byte_valid_o properly clears when enable_i goes LOW,
// even if valid was HIGH at the time of disable.
//
// Failure mode guarded against:
// A valid that stays HIGH after enable_i drops keeps entropy_stream_valid
// HIGH and fifo_push asserted; with fifo_full that yields continuous
// overflow (overflow = push_i & fifo_full).
//
// Test Strategy:
// 1. Enable decorrelator and wait for valid pulse
// 2. Disable while valid is HIGH
// 3. Verify valid goes LOW on next clock
// 4. Verify valid stays LOW while disabled
// 5. Re-enable and verify normal operation resumes
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_decorrelator_disable;
  // Clock and reset
  reg clk;
  reg rstn;

  // DUT signals
  reg        enable;
  reg        noise;
  reg        bypass;
  reg [7:0]  byte_mask;
  reg [23:0] sample_clk_div;
  wire [7:0] entropy_byte;
  wire       entropy_valid;

  // Test monitoring
  integer test_errors;
  integer cycle_count;
  integer valid_pulse_count;
  reg     captured_valid_high;
  integer stuck_count;
  integer i;

  // Instantiate DUT
  entropy_decorrelator #(
    .LENGTH(29),
    .CLKDIV_WIDTH(24),
    .LFSR_MODE(1'b0)
  ) dut (
    .clk_i(clk),
    .rst_ni(rstn),
    .enable_i(enable),
    .noise_i(noise),
    .bypass_i(bypass),
    .byte_mask_i(byte_mask),
    .sample_clk_div_i(sample_clk_div),
    .entropy_byte_sample_o(entropy_byte),
    .entropy_byte_valid_o(entropy_valid)
  );

  // Clock generation: 10ns period (100MHz)
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end

  // Random noise generation
  always @(posedge clk) begin
    if (rstn) begin
      noise <= $urandom;
    end
  end

  // Timeout watchdog - 500ms should be plenty
  initial begin
    #500000000;
    $display("\nERROR: Test timeout!");
    $finish;
  end

  // Waveform dumping
  initial begin
    $dumpfile("decorrelator_disable.vcd");
    $dumpvars(0, tb_decorrelator_disable);
  end

  // Main test sequence
  initial begin
    // Initialize
    test_errors = 0;
    cycle_count = 0;
    valid_pulse_count = 0;
    captured_valid_high = 0;

    rstn = 0;
    enable = 0;
    noise = 0;
    bypass = 0;
    byte_mask = 8'hFF;
    sample_clk_div = 24'd15;  // Short divider for faster testing

    $display("\n========================================");
    $display("Decorrelator Disable Test");
    $display("========================================\n");

    // Release reset
    repeat (5) @(posedge clk);
    rstn = 1;
    repeat (5) @(posedge clk);

    //------------------------------------------------------------------
    // TEST 1: Normal Operation - Verify Valid Pulses
    //------------------------------------------------------------------
    $display("--- TEST 1: Normal Operation ---");
    $display("Enabling decorrelator and waiting for valid pulses...");

    enable = 1;
    valid_pulse_count = 0;

    // Wait for 3 valid pulses to confirm normal operation
    while (valid_pulse_count < 3) begin
      @(posedge clk);
      cycle_count = cycle_count + 1;
      if (entropy_valid) begin
        valid_pulse_count = valid_pulse_count + 1;
        $display("  Valid pulse %0d detected at cycle %0d", valid_pulse_count, cycle_count);
      end

      // Safety timeout
      if (cycle_count > 200) begin
        $display("  ✗ ERROR: No valid pulses detected after 200 cycles!");
        test_errors = test_errors + 1;
        $finish;
      end
    end

    $display("  ✓ PASS: Normal valid pulse generation confirmed");

    //------------------------------------------------------------------
    // TEST 2: Disable While Valid is HIGH
    //------------------------------------------------------------------
    $display("\n--- TEST 2: Disable While Valid is HIGH ---");
    $display("Waiting for valid to go HIGH...");

    // Wait for valid to go HIGH and disable immediately
    captured_valid_high = 0;
    cycle_count = 0;
    while (!captured_valid_high) begin
      @(posedge clk);
      #1;  // Small delay to sample after clock edge
      cycle_count = cycle_count + 1;
      if (entropy_valid) begin
        $display("  Valid went HIGH at cycle %0d", cycle_count);
        $display("  Confirmed: valid is HIGH, disabling immediately...");
        captured_valid_high = 1;

        // Disable while valid is HIGH
        enable = 0;
      end

      if (cycle_count > 100) begin
        $display("  ✗ ERROR: Valid didn't go HIGH within 100 cycles!");
        test_errors = test_errors + 1;
        $finish;
      end
    end

    // Wait one clock cycle and check if valid cleared
    @(posedge clk);
    #1;

    if (entropy_valid) begin
      $display("  ✗ ERROR: Valid is still HIGH after disable!");
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ PASS: Valid cleared on first clock after disable");
    end

    //------------------------------------------------------------------
    // TEST 3: Valid Stays LOW While Disabled
    //------------------------------------------------------------------
    $display("\n--- TEST 3: Valid Stays LOW While Disabled ---");
    $display("Monitoring valid for 50 cycles while disabled...");

    for (int i = 0; i < 50; i++) begin
      @(posedge clk);
      #1;
      if (entropy_valid) begin
        $display("  ✗ ERROR: Valid went HIGH while disabled at cycle %0d!", i);
        test_errors = test_errors + 1;
      end
    end

    if (test_errors == 0) begin
      $display("  ✓ PASS: Valid remained LOW for 50 cycles while disabled");
    end

    //------------------------------------------------------------------
    // TEST 4: Re-enable and Verify Normal Operation
    //------------------------------------------------------------------
    $display("\n--- TEST 4: Re-enable and Verify Normal Operation ---");
    $display("Re-enabling decorrelator...");

    enable = 1;
    valid_pulse_count = 0;
    cycle_count = 0;

    // Wait for 2 valid pulses to confirm operation resumed
    while (valid_pulse_count < 2) begin
      @(posedge clk);
      cycle_count = cycle_count + 1;
      if (entropy_valid) begin
        valid_pulse_count = valid_pulse_count + 1;
        $display("  Valid pulse %0d detected at cycle %0d after re-enable", valid_pulse_count,
                 cycle_count);
      end

      if (cycle_count > 100) begin
        $display("  ✗ ERROR: Valid didn't resume after re-enable!");
        test_errors = test_errors + 1;
        $finish;
      end
    end

    $display("  ✓ PASS: Normal operation resumed after re-enable");

    //------------------------------------------------------------------
    // TEST 5: Rapid Enable/Disable Stress Test
    //------------------------------------------------------------------
    $display("\n--- TEST 5: Rapid Enable/Disable Stress Test ---");
    $display("Toggling enable rapidly and checking valid behavior...");

    stuck_count = 0;

    for (i = 0; i < 20; i = i + 1) begin
      // Enable for random period (5-15 cycles)
      enable = 1;
      repeat (5 + (i % 11)) @(posedge clk);

      // Disable for random period (3-10 cycles)
      enable = 0;

      // Check that valid goes LOW when disabled
      repeat (3 + (i % 8)) begin
        @(posedge clk);
        #1;
        if (entropy_valid) begin
          stuck_count = stuck_count + 1;
        end
      end
    end

    if (stuck_count > 0) begin
      $display("  ✗ ERROR: Valid was HIGH while disabled %0d times during stress test!",
               stuck_count);
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ PASS: Valid correctly cleared during 20 enable/disable cycles");
    end

    //------------------------------------------------------------------
    // TEST 6: Disable-Enable Boundary Timing
    //------------------------------------------------------------------
    $display("\n--- TEST 6: Disable-Enable Boundary Timing ---");
    $display("Testing immediate re-enable after disable...");

    enable = 1;
    // Wait for valid HIGH
    wait (entropy_valid);
    @(posedge clk);

    // Disable for exactly 1 cycle
    enable = 0;
    @(posedge clk);
    #1;

    if (entropy_valid) begin
      $display("  ✗ ERROR: Valid didn't clear during 1-cycle disable!");
      test_errors = test_errors + 1;
    end else begin
      $display("  ✓ PASS: Valid cleared during 1-cycle disable");
    end

    // Immediate re-enable
    enable = 1;

    // Verify operation continues
    valid_pulse_count = 0;
    cycle_count = 0;
    while (valid_pulse_count < 1 && cycle_count <= 100) begin
      @(posedge clk);
      cycle_count = cycle_count + 1;
      if (entropy_valid) begin
        valid_pulse_count = valid_pulse_count + 1;
      end
    end

    if (cycle_count > 100) begin
      $display("  ✗ ERROR: Valid didn't resume after immediate re-enable!");
      test_errors = test_errors + 1;
    end

    if (valid_pulse_count > 0) begin
      $display("  ✓ PASS: Operation resumed after immediate re-enable");
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
      $display("\nVerified:");
      $display("  - entropy_byte_valid_o clears when enable_i goes LOW");
      $display("  - Valid signal doesn't get stuck HIGH");
      $display("  - Normal operation resumes correctly after re-enable");
      $display("  - Rapid enable/disable transitions handled correctly");
    end else begin
      $display("\n✗✗✗ TESTS FAILED ✗✗✗");
      $display("Valid did not clear on disable in at least one test.");
    end

    $display("\n");
    $finish;
  end

endmodule
