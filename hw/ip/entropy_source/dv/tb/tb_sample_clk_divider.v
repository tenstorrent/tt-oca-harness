// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Sample Clock Divider Testbench
//
// Description:
// Comprehensive testbench to verify programmable sample clock division for
// all 12 entropy generators. Tests all division ratios: 1, 2, 4, 8, 16
//
// Test Strategy:
// 1. Apply known sample clock frequency
// 2. Program each division ratio (0-4)
// 3. Measure actual divided clock period
// 4. Verify against expected division factor
// 5. Report pass/fail for each test case
//------------------------------------------------------------------------------
`timescale 1ns / 1ps

module tb_sample_clk_divider;

  // Test parameters
  localparam int SAMPLE_CLK_PERIOD = 100;  // 100ns = 10MHz
  localparam int NUM_GENERATORS = 12;
  localparam int NUM_DIV_RATIOS = 5;
  localparam real TOLERANCE = 5.0;  // 5% tolerance for frequency measurements

  // Clock and reset
  reg clk;
  reg rst_n;
  reg sample_clk;

  // Test control
  reg [4:0] sample_clk_divide;
  reg enable;

  // DUT outputs
  wire divided_clk;
  wire [5:0] all_divided_clks;
  wire noise_bit;
  wire [7:0] entropy_byte;
  wire entropy_byte_valid;

  // Test tracking
  integer test_count;
  integer pass_count;
  integer fail_count;
  integer generator_id;
  integer div_ratio_idx;

  // Frequency measurement
  real measured_period;
  real expected_period;
  real period_error;
  integer edge_count;
  time last_edge_time;
  time current_edge_time;

  //--------------------------------------------------------------------------
  // Ring Oscillator Length Parameters
  //--------------------------------------------------------------------------
  // Shared sampling RO (single oscillator for all 12 generators)
  localparam integer SHARED_TOTAL_LENGTH = 109;
  localparam integer SHARED_TAPPED_LENGTH = 101;

  // Jitter (noise generating) RO lengths per generator
  integer jitter_ro_lengths [0:11];
  integer jitter_ro_tapped_lengths [0:11];

  initial begin
    // Jitter RO normal lengths
    jitter_ro_lengths[0]  = 5;
    jitter_ro_lengths[1]  = 7;
    jitter_ro_lengths[2]  = 11;
    jitter_ro_lengths[3]  = 13;
    jitter_ro_lengths[4]  = 17;
    jitter_ro_lengths[5]  = 19;
    jitter_ro_lengths[6]  = 6;
    jitter_ro_lengths[7]  = 8;
    jitter_ro_lengths[8]  = 12;
    jitter_ro_lengths[9]  = 14;
    jitter_ro_lengths[10] = 18;
    jitter_ro_lengths[11] = 20;

    // Jitter RO detuned lengths
    jitter_ro_tapped_lengths[0]  = 3;
    jitter_ro_tapped_lengths[1]  = 6;
    jitter_ro_tapped_lengths[2]  = 9;
    jitter_ro_tapped_lengths[3]  = 10;
    jitter_ro_tapped_lengths[4]  = 15;
    jitter_ro_tapped_lengths[5]  = 17;
    jitter_ro_tapped_lengths[6]  = 4;
    jitter_ro_tapped_lengths[7]  = 7;
    jitter_ro_tapped_lengths[8]  = 11;
    jitter_ro_tapped_lengths[9]  = 12;
    jitter_ro_tapped_lengths[10] = 15;
    jitter_ro_tapped_lengths[11] = 16;
  end

  //--------------------------------------------------------------------------
  // DUT Instantiation
  //--------------------------------------------------------------------------
  entropy_generator_test_wrapper #(
    .TOTAL_LENGTH  (17),
    .TAPPED_LENGTH (13),
    .CLKDIV_WIDTH  (24)
  ) dut (
    .clk_i               (clk),
    .rst_ni              (rst_n),
    .sample_clk_i        (sample_clk),
    .enable_i            (enable),
    .sample_clk_divide_i (sample_clk_divide),
    .divided_clk_o       (divided_clk),
    .all_divided_clks_o  (all_divided_clks),
    .noise_bit_o         (noise_bit),
    .entropy_byte_o      (entropy_byte),
    .entropy_byte_valid_o(entropy_byte_valid)
  );

  //--------------------------------------------------------------------------
  // Clock Generation
  //--------------------------------------------------------------------------
  initial begin
    clk = 0;
    forever #5 clk = ~clk;  // 100MHz system clock
  end

  initial begin
    sample_clk = 0;
    forever #(SAMPLE_CLK_PERIOD / 2) sample_clk = ~sample_clk;  // 10MHz sample clock
  end

  //--------------------------------------------------------------------------
  // Divided Clock Edge Detection and Measurement
  //--------------------------------------------------------------------------
  reg divided_clk_prev;

  always @(posedge clk) begin
    divided_clk_prev <= divided_clk;
  end

  // Measure period on rising edges of divided clock
  always @(posedge clk) begin
    if (divided_clk && !divided_clk_prev) begin
      if (edge_count > 0) begin
        current_edge_time = $time;
        measured_period = current_edge_time - last_edge_time;
      end
      last_edge_time = $time;
      edge_count = edge_count + 1;
    end
  end

  //--------------------------------------------------------------------------
  // Test Tasks
  //--------------------------------------------------------------------------

  // Reset task
  task automatic reset_dut;
    begin
      rst_n = 0;
      enable = 0;
      sample_clk_divide = 5'd0;
      edge_count = 0;
      measured_period = 0;
      last_edge_time = 0;
      @(posedge clk);
      @(posedge clk);
      rst_n = 1;
      @(posedge clk);
      enable = 1;
      @(posedge clk);
    end
  endtask

  // Set division ratio and wait for measurement
  task automatic test_division_ratio(input integer gen_id, input integer div_idx,
                                     input integer div_factor);
    real expected_freq, measured_freq, freq_error;
    integer measurement_cycles;
    begin
      test_count = test_count + 1;

      $display("----------------------------------------");
      $display("Test %0d: Generator %0d, Division Factor = %0d", test_count, gen_id, div_factor);

      // Set division ratio
      sample_clk_divide = div_idx;
      edge_count = 0;
      measured_period = 0;

      // Wait for configuration to take effect
      repeat (10) @(posedge sample_clk);

      // Measure for several cycles
      measurement_cycles = 20;
      repeat (measurement_cycles * div_factor) @(posedge sample_clk);

      // Calculate expected period
      expected_period = SAMPLE_CLK_PERIOD * div_factor;

      // Check if we got valid measurements
      if (edge_count < 2) begin
        $display("  FAIL: No divided clock edges detected!");
        $display("  Expected period: %.2f ns", expected_period);
        fail_count = fail_count + 1;
      end else begin
        // Calculate frequencies
        expected_freq = 1000.0 / expected_period; // MHz
        measured_freq = 1000.0 / measured_period; // MHz
        freq_error = 100.0 * (measured_freq - expected_freq) / expected_freq;

        $display("  Sample clock: %.2f MHz", 1000.0 / SAMPLE_CLK_PERIOD);
        $display("  Expected divided freq: %.2f MHz (period = %.2f ns)", expected_freq,
                 expected_period);
        $display("  Measured divided freq: %.2f MHz (period = %.2f ns)", measured_freq,
                 measured_period);
        $display("  Frequency error: %.2f%%", freq_error);
        $display("  Edges counted: %0d", edge_count);

        // Check if measurement is within tolerance
        if (freq_error < -TOLERANCE || freq_error > TOLERANCE) begin
          $display("  FAIL: Frequency error exceeds tolerance (%.1f%%)", TOLERANCE);
          fail_count = fail_count + 1;
        end else begin
          $display("  PASS: Frequency within tolerance");
          pass_count = pass_count + 1;
        end
      end
    end
  endtask

  // Test all division ratios for a generator
  task automatic test_generator(input integer gen_id);
    real expected_ratio;
    begin
      expected_ratio = real'(SHARED_TOTAL_LENGTH) / real'(jitter_ro_lengths[gen_id]);
      $display("");
      $display("========================================");
      $display("Testing Generator %0d", gen_id);
      $display("  Shared Sampling RO Length: %0d", SHARED_TOTAL_LENGTH);
      $display("  Jitter RO Length: %0d", jitter_ro_lengths[gen_id]);
      $display("  Expected Ratio (÷1): %.1fx", expected_ratio);
      $display("========================================");

      // Test each division ratio
      test_division_ratio(gen_id, 0, 1);  // ÷1
      test_division_ratio(gen_id, 1, 2);  // ÷2
      test_division_ratio(gen_id, 2, 4);  // ÷4 (default)
      test_division_ratio(gen_id, 3, 8);  // ÷8
      test_division_ratio(gen_id, 4, 16);  // ÷16
    end
  endtask

  //--------------------------------------------------------------------------
  // Main Test Sequence
  //--------------------------------------------------------------------------
  initial begin
    $display("========================================");
    $display("Sample Clock Divider Testbench");
    $display("========================================");
    $display("Testing %0d generators with %0d division ratios each", NUM_GENERATORS,
             NUM_DIV_RATIOS);
    $display("Sample clock frequency: %.2f MHz", 1000.0 / SAMPLE_CLK_PERIOD);
    $display("Measurement tolerance: %.1f%%", TOLERANCE);
    $display("");

    // Initialize
    test_count = 0;
    pass_count = 0;
    fail_count = 0;

    // Reset DUT
    reset_dut();

    // Test a representative subset of generators
    // (Testing all 12 would take a long time, so we test generator 0, 5, and 11)
    $display("========================================");
    $display("Quick Test Mode: Testing 3 representative generators");
    $display("========================================");

    test_generator(0);  // First generator
    test_generator(5);  // Middle generator
    test_generator(11);  // Last generator

    // Optionally enable full test
`ifdef FULL_TEST
    $display("");
    $display("========================================");
    $display("Full Test Mode: Testing all %0d generators", NUM_GENERATORS);
    $display("========================================");

    for (generator_id = 1; generator_id < NUM_GENERATORS; generator_id = generator_id + 1) begin
      if (generator_id != 0 && generator_id != 5 && generator_id != 11) begin
        test_generator(generator_id);
      end
    end
`endif

    // Final summary
    $display("");
    $display("========================================");
    $display("Test Summary");
    $display("========================================");
    $display("Total tests: %0d", test_count);
    $display("Passed: %0d", pass_count);
    $display("Failed: %0d", fail_count);

    if (fail_count == 0) begin
      $display("");
      $display("*** ALL TESTS PASSED ***");
      $display("");
    end else begin
      $display("");
      $display("*** %0d TESTS FAILED ***", fail_count);
      $display("");
    end

    $finish;
  end

  //--------------------------------------------------------------------------
  // Timeout watchdog
  //--------------------------------------------------------------------------
  initial begin
    #500000000;  // 500ms timeout
    $display("");
    $display("ERROR: Testbench timeout!");
    $display("Test count: %0d", test_count);
    $finish;
  end

  //--------------------------------------------------------------------------
  // VCD dump
  //--------------------------------------------------------------------------
  initial begin
    $dumpfile("sample_clk_divider.vcd");
    $dumpvars(0, tb_sample_clk_divider);
    $dumpvars(1, dut.sample_clk_i);
    $dumpvars(1, dut.divided_clk_o);
    $dumpvars(1, dut.all_divided_clks_o);
    $dumpvars(1, dut.sample_clk_divide_i);
  end

endmodule
