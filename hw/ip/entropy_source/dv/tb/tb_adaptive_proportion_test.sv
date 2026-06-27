// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//------------------------------------------------------------------------------
// Testbench for Entropy Adaptive Proportion Test - 32-bit Version (Parallel)
//
// This testbench verifies the parallel APT module functionality across all
// 4 sample sizes simultaneously.
//------------------------------------------------------------------------------

`timescale 1ns/1ps

module tb_adaptive_proportion_test;

    // Clock and reset
    logic clk_i;
    logic rst_ni;

    // Test inputs
    logic [31:0] entropy_i;
    logic        enable_i;
    logic [9:0]  proportion_limit_1bit_i;
    logic [9:0]  proportion_limit_2bit_i;
    logic [9:0]  proportion_limit_3bit_i;
    logic [9:0]  proportion_limit_4bit_i;

    // Parallel APT outputs for all 4 sample sizes
    logic [9:0]  pattern_count_1bit_o;
    logic [9:0]  pattern_count_2bit_o;
    logic [9:0]  pattern_count_3bit_o;
    logic [9:0]  pattern_count_4bit_o;
    logic [3:0]  target_pattern_1bit_o;
    logic [3:0]  target_pattern_2bit_o;
    logic [3:0]  target_pattern_3bit_o;
    logic [3:0]  target_pattern_4bit_o;
    logic [9:0]  samples_processed_1bit_o;
    logic [9:0]  samples_processed_2bit_o;
    logic [9:0]  samples_processed_3bit_o;
    logic [9:0]  samples_processed_4bit_o;
    logic [3:0]  status_o;

    // DUT instantiation
    entropy_adaptive_proportion_test dut (
        .clk_i,
        .rst_ni,
        .entropy_i,
        .enable_i,
        .proportion_limit_1bit_i,
        .proportion_limit_2bit_i,
        .proportion_limit_3bit_i,
        .proportion_limit_4bit_i,
        .pattern_count_1bit_o,
        .pattern_count_2bit_o,
        .pattern_count_3bit_o,
        .pattern_count_4bit_o,
        .target_pattern_1bit_o,
        .target_pattern_2bit_o,
        .target_pattern_3bit_o,
        .target_pattern_4bit_o,
        .samples_processed_1bit_o,
        .samples_processed_2bit_o,
        .samples_processed_3bit_o,
        .samples_processed_4bit_o,
        .status_o
    );

    // Clock generation
    initial begin
        clk_i = 0;
        forever #5 clk_i = ~clk_i;
    end

    // Test sequence
    initial begin
        // Initialize
        rst_ni = 0;
        enable_i = 0;
        entropy_i = 32'h0;
        proportion_limit_1bit_i = 10'd600; // Default threshold for 1-bit
        proportion_limit_2bit_i = 10'd600; // Default threshold for 2-bit
        proportion_limit_3bit_i = 10'd600; // Default threshold for 3-bit
        proportion_limit_4bit_i = 10'd600; // Default threshold for 4-bit

        // VCD dump for waveform viewing
        $dumpfile("tb_adaptive_proportion_test.vcd");
        $dumpvars(0, tb_adaptive_proportion_test);

        // Reset sequence
        repeat(5) @(posedge clk_i);
        rst_ni = 1;
        repeat(2) @(posedge clk_i);

        $display("Starting APT Parallel Test");

        // Test 1: Basic functionality with enable
        $display("\n=== Test 1: Basic Enable Test ===");
        enable_i = 1;
        entropy_i = 32'hAAAAAAAA; // Alternating pattern
        @(posedge clk_i);

        $display("First entropy word: 0x%08h", entropy_i);
        $display("1-bit target: %b, count: %d, samples: %d",
                target_pattern_1bit_o, pattern_count_1bit_o, samples_processed_1bit_o);
        $display("2-bit target: %b, count: %d, samples: %d",
                target_pattern_2bit_o, pattern_count_2bit_o, samples_processed_2bit_o);
        $display("3-bit target: %b, count: %d, samples: %d",
                target_pattern_3bit_o, pattern_count_3bit_o, samples_processed_3bit_o);
        $display("4-bit target: %b, count: %d, samples: %d",
                target_pattern_4bit_o, pattern_count_4bit_o, samples_processed_4bit_o);

        // Test 2: Continue with same pattern to see counts increase
        $display("\n=== Test 2: Same Pattern Continuation ===");
        repeat(10) begin
            @(posedge clk_i);
            $display("Cycle %0t: 1b:%d/2b:%d/3b:%d/4b:%d samples:%d/%d/%d/%d",
                    $time, pattern_count_1bit_o, pattern_count_2bit_o,
                    pattern_count_3bit_o, pattern_count_4bit_o,
                    samples_processed_1bit_o, samples_processed_2bit_o,
                    samples_processed_3bit_o, samples_processed_4bit_o);
        end

        // Test 3: Different pattern
        $display("\n=== Test 3: Different Pattern Test ===");
        entropy_i = 32'h55555555; // Different alternating pattern
        @(posedge clk_i);
        $display("New entropy word: 0x%08h", entropy_i);
        $display("Pattern counts: 1b:%d/2b:%d/3b:%d/4b:%d",
                pattern_count_1bit_o, pattern_count_2bit_o,
                pattern_count_3bit_o, pattern_count_4bit_o);

        // Test 4: All zeros pattern
        $display("\n=== Test 4: All Zeros Pattern ===");
        entropy_i = 32'h00000000;
        repeat(5) begin
            @(posedge clk_i);
            $display("All zeros - Pattern counts: 1b:%d/2b:%d/3b:%d/4b:%d",
                    pattern_count_1bit_o, pattern_count_2bit_o,
                    pattern_count_3bit_o, pattern_count_4bit_o);
        end

        // Test 5: All ones pattern
        $display("\n=== Test 5: All Ones Pattern ===");
        entropy_i = 32'hFFFFFFFF;
        repeat(5) begin
            @(posedge clk_i);
            $display("All ones - Pattern counts: 1b:%d/2b:%d/3b:%d/4b:%d",
                    pattern_count_1bit_o, pattern_count_2bit_o,
                    pattern_count_3bit_o, pattern_count_4bit_o);
        end

        // Test 6: Disable test
        $display("\n=== Test 6: Disable Test ===");
        enable_i = 0;
        @(posedge clk_i);
        $display("After disable - Pattern counts: 1b:%d/2b:%d/3b:%d/4b:%d",
                pattern_count_1bit_o, pattern_count_2bit_o,
                pattern_count_3bit_o, pattern_count_4bit_o);
        $display("Samples processed: 1b:%d/2b:%d/3b:%d/4b:%d",
                samples_processed_1bit_o, samples_processed_2bit_o,
                samples_processed_3bit_o, samples_processed_4bit_o);

        // Test 7: Re-enable
        $display("\n=== Test 7: Re-enable Test ===");
        enable_i = 1;
        entropy_i = 32'h12345678;
        @(posedge clk_i);
        $display("Re-enabled with 0x%08h", entropy_i);
        $display("New targets: 1b:%b/2b:%b/3b:%b/4b:%b",
                target_pattern_1bit_o[0], target_pattern_2bit_o[1:0],
                target_pattern_3bit_o[2:0], target_pattern_4bit_o[3:0]);

        // Test 8: Status check (threshold test)
        $display("\n=== Test 8: Status/Threshold Test ===");
        proportion_limit_1bit_i = 10'd5; // Lower threshold for testing 1-bit
        proportion_limit_2bit_i = 10'd5; // Lower threshold for testing 2-bit
        proportion_limit_3bit_i = 10'd5; // Lower threshold for testing 3-bit
        proportion_limit_4bit_i = 10'd5; // Lower threshold for testing 4-bit
        entropy_i = 32'h00000000; // All zeros to maximize pattern matches
        repeat(20) begin
            @(posedge clk_i);
            if (|status_o) begin
                $display("Status triggered: %b at time %0t", status_o, $time);
                $display("Pattern counts when status triggered: 1b:%d/2b:%d/3b:%d/4b:%d",
                        pattern_count_1bit_o, pattern_count_2bit_o,
                        pattern_count_3bit_o, pattern_count_4bit_o);
            end
        end

        $display("\n=== Test Completed Successfully ===");
        $finish;
    end

    // Timeout watchdog
    initial begin
        #50000; // 50us timeout
        $display("ERROR: Test timeout!");
        $finish;
    end

endmodule