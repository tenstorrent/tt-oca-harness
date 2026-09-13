// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Noise Source iverilog Testbench
//
// Description:
// Verilog testbench with frequency measurement and metastability detection
// Tests the entropy_noise_source module which instantiates a ring oscillator and
// performs sampling with metastable D flip-flops
//------------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_ring_oscillator ();

  // Test signals
  reg clk_i;
  reg rst_ni;
  reg sample_clk_i;
  reg enable_i;
  reg detune_i;
  wire noise_o;

  // Debug signals
  wire rosc_async;
  wire feedback;
  wire stage_0;
  wire [16:0] stage_o;

  // Frequency measurement variables
  integer clk_i_edges = 0;
  integer sample_clk_i_edges = 0;
  integer rosc_async_edges = 0;
  integer noise_o_edges = 0;

  reg clk_i_last = 0;
  reg sample_clk_i_last = 0;
  reg rosc_async_last = 0;
  reg noise_o_last = 0;

  integer start_time = 0;
  integer end_time = 0;
  real measurement_period = 0;
  reg measurement_active = 0;

  // Metastable event estimation variables
  integer potential_metastable_events = 0;
  integer sample_clock_edges = 0;
  reg rosc_async_prev = 0;

  // Instantiate the DUT
  entropy_noise_source #(
    .TOTAL_LENGTH(17),
    .TAPPED_LENGTH(13)
  ) u_entropy_noise_src (
    .clk_i,
    .rst_ni,
    .sample_clk_i(sample_clk_i),
    .enable_i(enable_i),
    .detune_i(detune_i),
    .noise_o(noise_o)
  );

  // Connect debug signals
  assign rosc_async = u_entropy_noise_src.noise_async;
  assign feedback = u_entropy_noise_src.u_ring_oscillator.feedback;
  assign stage_0 = u_entropy_noise_src.u_ring_oscillator.stage_o[0];
  assign stage_o = u_entropy_noise_src.u_ring_oscillator.stage_o;

  // Clock generation
  initial begin
    clk_i = 0;
    forever #50 clk_i = ~clk_i;  // 10MHz clock (100ns period)
  end

  // Sample clock generation (1/10 of ring oscillator frequency)
  initial begin
    sample_clk_i = 0;
    forever #138.89 sample_clk_i = ~sample_clk_i;  // ~3.6MHz sample clock (277.78ns period)
  end

  // Frequency measurement: count edges using flag-based detection
  always @(posedge clk_i) begin
    if (measurement_active) begin
      clk_i_edges = clk_i_edges + 1;
    end
  end

  always @(posedge sample_clk_i) begin
    if (measurement_active) begin
      sample_clk_i_edges = sample_clk_i_edges + 1;
    end
  end

  always @(posedge rosc_async) begin
    if (measurement_active) begin
      rosc_async_edges = rosc_async_edges + 1;
    end
  end

  always @(posedge noise_o) begin
    if (measurement_active) begin
      noise_o_edges = noise_o_edges + 1;
    end
  end

  // Test sequence
  initial begin
    $display("=== Enhanced Entropy Noise Source Test with Frequency Measurement ===");
    $display("Time=%0t: Starting test", $time);

    // Initialize
    rst_ni = 0;
    enable_i = 0;
    detune_i = 0;

    // Reset sequence
    #100;
    rst_ni = 1;
    #50;

    $display("Time=%0t: Reset released", $time);

    // Enable oscillator with tap length (detune_i = 0)
    enable_i = 1;
    detune_i = 0;

    $display("Time=%0t: Oscillator enabled (enable_i=%b, detune_i=%b)", $time, enable_i, detune_i);

    // Wait for startup and begin frequency measurement
    #1000;
    start_time = $time;
    measurement_active = 1;  // Start measuring
    $display("Time=%0t: Starting frequency measurement period", $time);

    // Monitor for startup and oscillation
    $display("Time | enable_i | detune_i | stage_0 | feedback | rosc_async | noise_o");
    $display("-----|----------|----------|---------|----------|------------|--------");

    // Monitor first 50 time units for startup
    repeat (50) begin
      #10;
      $display("%4d |        %b |        %b |       %b |        %b |          %b |       %b",
               $time, enable_i, detune_i, stage_0, feedback, rosc_async, noise_o);
    end

    $display("");
    $display("Time=%0t: Extended monitoring for frequency measurement and metastability...", $time);

    // Extended monitoring to capture frequency and metastable events
    // Run for ~4ms to get at least 1000 edges on the synchronized output
    repeat (400000) begin
      #10;
      if ($time % 100000 == 0) begin
        $display("Time=%0dus: stage[0-4]=%b%b%b%b%b feedback=%b async=%b noise_o=%b edges=%0d",
                 $time / 1000, stage_o[0], stage_o[1], stage_o[2], stage_o[3], stage_o[4],
                 feedback, rosc_async, noise_o, noise_o_edges);
      end
    end

    // End frequency measurement
    measurement_active = 0;  // Stop measuring
    end_time = $time;
    measurement_period = (end_time - start_time) * 1e-9; // Convert from ns to seconds

    $display("");
    $display("=== Frequency Analysis Results ===");
    $display("Measurement period: %.3f ms (%.0f ns to %.0f ns)", measurement_period * 1000,
             start_time, end_time);

    if (measurement_period > 0) begin
      $display("System Clock (clk_i):     %0d edges, %.3f MHz", clk_i_edges,
               clk_i_edges / measurement_period / 1000000.0);
      $display("Sample Clock:             %0d edges, %.3f MHz", sample_clk_i_edges,
               sample_clk_i_edges / measurement_period / 1000000.0);
      $display("Ring Oscillator (async):  %0d edges, %.3f MHz", rosc_async_edges,
               rosc_async_edges / measurement_period / 1000000.0);
      $display("Synchronized Output:      %0d edges, %.3f MHz", noise_o_edges,
               noise_o_edges / measurement_period / 1000000.0);

      $display("");
      $display("=== Metastability Analysis ===");
      $display("Estimated metastable events: %0d", potential_metastable_events);
      $display("Sample clock edges:          %0d", sample_clock_edges);
      if (sample_clock_edges > 0) begin
        $display("Metastable event rate:       %.3f%% (events per sample)",
                 (potential_metastable_events * 100.0) / sample_clock_edges);
      end
      $display("Ring/Sample frequency ratio: %.2f (theoretical metastability)",
               (rosc_async_edges * 1.0) / sample_clk_i_edges);
    end

    $display("");
    $display("=== Test Complete ===");
    $display("Final state: enable_i=%b, stage_0=%b, feedback=%b, rosc_async=%b, noise_o=%b",
             enable_i, stage_0, feedback, rosc_async, noise_o);

    $finish;
  end

  // Metastable event estimation based on setup/hold violations
  always @(posedge sample_clk_i) begin
    if (measurement_active && rst_ni) begin
      sample_clock_edges = sample_clock_edges + 1;
      rosc_async_prev = rosc_async;

      // Check for transitions near sample clock edge (within setup/hold window)
      // This estimates potential metastable events
      #1;  // Small delay to check if rosc_async changed near the edge
      if (rosc_async !== rosc_async_prev) begin
        potential_metastable_events = potential_metastable_events + 1;
        if (potential_metastable_events <= 10) begin  // Show first 10 events
          $display(
              "Time=%0t: Estimated metastable event #%0d (rosc_async transition near sample edge)",
              $time - 1, potential_metastable_events);
        end
      end
    end
  end

  // Additional check for transitions just before sample clock edge
  always @(rosc_async) begin
    if (measurement_active && rst_ni) begin
      // Check if we're close to a sample clock rising edge (within ~2ns)
      if ($time % int'(277.78) > int'(275.78) || $time % int'(277.78) < int'(2.0)) begin
        potential_metastable_events = potential_metastable_events + 1;
        if (potential_metastable_events <= 10) begin
          $display({"Time=%0t: Estimated metastable event #%0d ",
                    "(rosc_async transition in setup/hold window)"}, $time,
                     potential_metastable_events);
        end
      end
    end
  end

  // VCD dump for waveform analysis
  initial begin
    $dumpfile("ring_oscillator.vcd");
    $dumpvars(0, tb_ring_oscillator);
    $dumpvars(1, u_entropy_noise_src.u_ring_oscillator.stage_o);
    $dumpvars(1, u_entropy_noise_src.noise_sample);
    $dumpvars(1, u_entropy_noise_src.noise_sync);
  end

endmodule
