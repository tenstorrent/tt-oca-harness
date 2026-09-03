// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Debug Monitor iverilog Testbench
//
// Description:
// Testbench to verify entropy_debug_monitor with 16 coprime oscillating inputs
// Tests signal selection and frequency division functionality
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_debug_monitor ();

  // Test parameters
  localparam int unsigned NSIGNALS = 16;
  localparam int unsigned FREQ_DIV_WIDTH = 7;

  // Coprime periods for TAPPED_LENGTH=13 based ring oscillators (in ns)
  // These are coprime to minimize correlation between signals
  real PERIODS[0:15];
  initial begin
    PERIODS[0] = 31.0;   // ~32.3 MHz
    PERIODS[1] = 37.0;   // ~27.0 MHz
    PERIODS[2] = 41.0;   // ~24.4 MHz
    PERIODS[3] = 43.0;   // ~23.3 MHz
    PERIODS[4] = 47.0;   // ~21.3 MHz
    PERIODS[5] = 53.0;   // ~18.9 MHz
    PERIODS[6] = 59.0;   // ~16.9 MHz
    PERIODS[7] = 61.0;   // ~16.4 MHz
    PERIODS[8] = 67.0;   // ~14.9 MHz
    PERIODS[9] = 71.0;   // ~14.1 MHz
    PERIODS[10] = 73.0;  // ~13.7 MHz
    PERIODS[11] = 79.0;  // ~12.7 MHz
    PERIODS[12] = 83.0;  // ~12.0 MHz
    PERIODS[13] = 89.0;  // ~11.2 MHz
    PERIODS[14] = 97.0;  // ~10.3 MHz
    PERIODS[15] = 101.0; // ~9.9 MHz
  end

  // Test signals
  reg rst_ni;
  reg [$clog2(NSIGNALS)-1:0] select_signal_i;
  reg [NSIGNALS-1:0] signal_i;
  reg [$clog2(FREQ_DIV_WIDTH):0] select_freq_div_i;
  wire sig_monitor_o;

  // Frequency measurement variables
  integer monitor_edges = 0;
  integer measurement_time = 0;
  integer start_time = 0;
  integer end_time = 0;
  real expected_freq = 0;
  real measured_freq = 0;
  real tolerance = 0;
  reg measurement_active = 0;
  reg sig_monitor_last = 0;

  // Test control variables
  integer test_phase = 0;
  integer signal_index = 0;
  integer freq_div_index = 0;
  integer random_signal = 7; // Random signal for frequency division test

  // Instantiate the DUT
  entropy_debug_monitor #(
    .NSIGNALS(NSIGNALS),
    .FREQ_DIV_WIDTH(FREQ_DIV_WIDTH)
  ) u_debug_monitor (
    .rst_ni,
    .select_signal_i(select_signal_i),
    .signal_i(signal_i),
    .select_freq_div_i(select_freq_div_i),
    .sig_monitor_o(sig_monitor_o)
  );

  // Generate 16 coprime oscillating signals
  genvar i;
  generate
    for (i = 0; i < NSIGNALS; i = i + 1) begin : gen_oscillators
      initial begin
        signal_i[i] = 0;
        forever begin
          #(PERIODS[i] / 2.0);
          signal_i[i] = ~signal_i[i];
        end
      end
    end
  endgenerate

  // Edge counting for frequency measurement
  always @(posedge sig_monitor_o) begin
    if (measurement_active) begin
      monitor_edges = monitor_edges + 1;
    end
  end

  // Test sequence
  initial begin
    $display("=== Entropy Debug Monitor Test ===");
    $display("Time=%0t: Starting test with %0d signals", $time, NSIGNALS);

    // Initialize
    rst_ni = 0;
    select_signal_i = 0;
    select_freq_div_i = 2; // Default to divide by 4 (2^2)
    monitor_edges = 0;

    // Reset sequence
    #100;
    rst_ni = 1;
    #50;

    $display("Time=%0t: Reset released", $time);

    // Wait for oscillators to stabilize
    #1000;

    // Display oscillator frequencies for reference
    $display("\nReference oscillator frequencies:");
    $display("Signal[ 0]: Period=31.0ns, Freq=32.26 MHz");
    $display("Signal[ 1]: Period=37.0ns, Freq=27.03 MHz");
    $display("Signal[ 2]: Period=41.0ns, Freq=24.39 MHz");
    $display("Signal[ 3]: Period=43.0ns, Freq=23.26 MHz");
    $display("Signal[ 4]: Period=47.0ns, Freq=21.28 MHz");
    $display("Signal[ 5]: Period=53.0ns, Freq=18.87 MHz");
    $display("Signal[ 6]: Period=59.0ns, Freq=16.95 MHz");
    $display("Signal[ 7]: Period=61.0ns, Freq=16.39 MHz");
    $display("Signal[ 8]: Period=67.0ns, Freq=14.93 MHz");
    $display("Signal[ 9]: Period=71.0ns, Freq=14.08 MHz");
    $display("Signal[10]: Period=73.0ns, Freq=13.70 MHz");
    $display("Signal[11]: Period=79.0ns, Freq=12.66 MHz");
    $display("Signal[12]: Period=83.0ns, Freq=12.05 MHz");
    $display("Signal[13]: Period=89.0ns, Freq=11.24 MHz");
    $display("Signal[14]: Period=97.0ns, Freq=10.31 MHz");
    $display("Signal[15]: Period=101.0ns, Freq=9.90 MHz");

    //===========================================
    // TEST PHASE 1: Signal Selection with /4 frequency division
    //===========================================
    $display("\n=== TEST PHASE 1: Signal Selection (Freq Div = 4) ===");
    test_phase = 1;
    select_freq_div_i = 2; // Divide by 4 (2^2)

    for (signal_index = 0; signal_index < NSIGNALS; signal_index = signal_index + 1) begin
      $display("\nTesting Signal[%0d] with frequency division of 4:", signal_index);

      select_signal_i = signal_index;

      // Wait for selection to propagate and dividers to settle
      #500;

      // Start frequency measurement
      monitor_edges = 0;
      start_time = $time;
      measurement_active = 1;

      // Measure for sufficient time to get accurate frequency
      #50000;  // 50us measurement window

      measurement_active = 0;
      end_time = $time;
      measurement_time = end_time - start_time;

      // Calculate frequencies
      expected_freq = (1000.0/PERIODS[signal_index]) / 4.0; // MHz, divided by 4
      measured_freq = (monitor_edges * 1000.0) / measurement_time; // MHz

      $display("  Expected: %.3f MHz, Measured: %.3f MHz (%0d edges in %0dns)", expected_freq,
               measured_freq, monitor_edges, measurement_time);

      // Check measurement quality and display appropriate message
      if (measured_freq > expected_freq * 0.98 && measured_freq < expected_freq * 1.02) begin
        $display("  ✓ PASS - Signal[%0d] frequency division working correctly (%.2f%% error)",
                 signal_index, 100.0 * ((measured_freq - expected_freq) / expected_freq));
      end else if (measured_freq > expected_freq * 0.90 && measured_freq < expected_freq * 1.10) begin
        $display("  ℹ INFO - Signal[%0d] frequency within 10%% tolerance (%.2f%% error)",
                 signal_index, 100.0 * ((measured_freq - expected_freq) / expected_freq));
      end else begin
        $display("  ✗ FAIL - Signal[%0d] frequency mismatch (%.2f%% error)", signal_index,
                 100.0 * ((measured_freq - expected_freq) / expected_freq));
      end

      #100;  // Brief pause between tests
    end

    //===========================================
    // TEST PHASE 2: Frequency Division Range Test
    //===========================================
    $display("\n=== TEST PHASE 2: Frequency Division Range (Signal[%0d]) ===", random_signal);
    test_phase = 2;
    select_signal_i = random_signal;

    for (
        freq_div_index = 0; freq_div_index < FREQ_DIV_WIDTH; freq_div_index = freq_div_index + 1
    ) begin
      $display("\nTesting frequency division by %0d (select_freq_div_i=%0d):", 1 << freq_div_index,
               freq_div_index);

      select_freq_div_i = freq_div_index;

      // Wait for selection to propagate and dividers to settle
      #1000;

      // Start frequency measurement
      monitor_edges = 0;
      start_time = $time;
      measurement_active = 1;

      // Adjust measurement time based on expected frequency
      // Use longer measurement for slower signals
      if (freq_div_index <= 2) begin
        #50000;  // 50us for faster signals (div 1,2,4)
      end else if (freq_div_index <= 4) begin
        #100000;  // 100us for medium signals (div 8,16)
      end else begin
        #200000;  // 200us for slower signals (div 32,64,128)
      end

      measurement_active = 0;
      end_time = $time;
      measurement_time = end_time - start_time;

      // Calculate frequencies
      expected_freq = (1000.0/PERIODS[random_signal]) / (1 << freq_div_index); // MHz
      measured_freq = (monitor_edges * 1000.0) / measurement_time; // MHz

      $display("  Divider: %3d, Expected: %.3f MHz, Measured: %.3f MHz (%0d edges in %0dns)",
               1 << freq_div_index, expected_freq, measured_freq, monitor_edges, measurement_time);

      // Check measurement quality and display appropriate message
      if (monitor_edges < 3) begin
        $display("  ⚠ WARNING - Too few edges (%0d) for accurate measurement", monitor_edges);
      end else if (measured_freq > expected_freq * 0.98 && measured_freq < expected_freq * 1.02) begin
        $display("  ✓ PASS - Frequency division by %0d working correctly (%.2f%% error)",
                 1 << freq_div_index, 100.0 * ((measured_freq - expected_freq) / expected_freq));
      end else if (measured_freq > expected_freq * 0.90 && measured_freq < expected_freq * 1.10) begin
        $display("  ℹ INFO - Frequency division by %0d within 10%% tolerance (%.2f%% error)",
                 1 << freq_div_index, 100.0 * ((measured_freq - expected_freq) / expected_freq));
      end else begin
        $display("  ✗ FAIL - Frequency division by %0d failed (%.2f%% error)",
                 1 << freq_div_index, 100.0 * ((measured_freq - expected_freq) / expected_freq));
      end

      #500;  // Brief pause between tests
    end

    //===========================================
    // TEST SUMMARY
    //===========================================
    $display("\n=== TEST COMPLETE ===");
    $display("Test Phase 1: Signal selection with /4 frequency division completed");
    $display("Test Phase 2: Frequency division range 1-128 completed");
    $display("Final state: signal_select=%0d, freq_div_select=%0d", select_signal_i,
             select_freq_div_i);

    $finish;
  end

  // Continuous verification that binary decode signals are one-hot
  integer signal_decode_count, freq_decode_count, check_i;

  always @(posedge u_debug_monitor.rst_ni) begin
    $display("=== Debug Monitor One-Hot Verification Enabled ===");
    $display("Signal selection: %0d signals, %0d-bit select", NSIGNALS, $clog2(NSIGNALS));
    $display("Frequency selection: %0d divisions, %0d-bit select", FREQ_DIV_WIDTH, $clog2
             (FREQ_DIV_WIDTH) + 1);
  end

  always_comb begin
    if (u_debug_monitor.rst_ni) begin
      // Check signal selection binary decode is one-hot
      signal_decode_count = 0;
      for (check_i = 0; check_i < NSIGNALS; check_i = check_i + 1) begin
        if (u_debug_monitor.select_signal_binary_decode[check_i])
          signal_decode_count = signal_decode_count + 1;
      end

      if (signal_decode_count != 1) begin
        $error(
            "Time=%0t: Signal selection binary decode not one-hot! Count=%0d, select_signal_i=%0d, decode=%b",
            $time, signal_decode_count, select_signal_i,
            u_debug_monitor.select_signal_binary_decode);
      end

      // Check frequency selection binary decode is one-hot
      freq_decode_count = 0;
      for (check_i = 0; check_i < FREQ_DIV_WIDTH; check_i = check_i + 1) begin
        if (u_debug_monitor.select_freq_binary_decode[check_i])
          freq_decode_count = freq_decode_count + 1;
      end

      if (freq_decode_count != 1) begin
        $error(
            "Time=%0t: Frequency selection binary decode not one-hot! Count=%0d, select_freq_div_i=%0d, decode=%b",
            $time, freq_decode_count, select_freq_div_i, u_debug_monitor.select_freq_binary_decode);
      end
    end
  end

  // VCD dump for waveform analysis
  initial begin
    $dumpfile("debug_monitor.vcd");
    $dumpvars(0, tb_debug_monitor);
    $dumpvars(1, u_debug_monitor.signal_i);
    $dumpvars(1, u_debug_monitor.div_signals);
    $dumpvars(1, u_debug_monitor.select_signal);
    $dumpvars(1, u_debug_monitor.select_signal_binary_decode);
    $dumpvars(1, u_debug_monitor.select_freq_binary_decode);
  end

endmodule
