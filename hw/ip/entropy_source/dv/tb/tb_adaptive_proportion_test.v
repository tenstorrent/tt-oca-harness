// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//------------------------------------------------------------------------------
// Adaptive Proportion Test (APT) iverilog Testbench
//
// Description:
// Comprehensive testbench for entropy_adaptive_proportion_test module
// Tests pseudorandom data with periodic failure injection for all sample sizes
// Verifies threshold detection and proper APT functionality
//------------------------------------------------------------------------------

`timescale 1ns/1ps

module tb_adaptive_proportion_test();

    // Test signals
    reg clk_i;
    reg rst_ni;
    reg [31:0] entropy_i;
    reg enable_i;
    reg [2:0] sample_size_i;
    reg [9:0] proportion_limit_i;
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
    reg [3:0] failure_pattern = 4'b0;
    integer failure_injection_count = 0;
    integer normal_data_count = 0;

    // Test parameters for different sample sizes
    reg [9:0] test_thresholds [1:4];
    reg [15:0] test_cycles_per_phase [1:4];

    // Statistics tracking
    integer phase_failures [1:4];
    integer total_tests_run = 0;
    integer total_tests_passed = 0;

    // Instantiate the DUT
    entropy_adaptive_proportion_test u_apt (
        .clk_i,
        .rst_ni,
        .entropy_i(entropy_i),
        .enable_i(enable_i),
        .sample_size_i(sample_size_i),
        .proportion_limit_i(proportion_limit_i),
        .status_o(status_o)
    );

    // Clock generation
    initial begin
        clk_i = 0;
        forever #5 clk_i = ~clk_i;  // 100MHz clock (10ns period)
    end

    // xoroshiro128+ high-quality PRNG
    function [63:0] rotl64;
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
    always @(*) begin
        prng_data = xoro_result[31:0];

        if (inject_failure) begin
            // Inject biased patterns based on sample size and failure pattern
            case (sample_size_i)
                3'd1: begin
                    // For 1-bit samples, bias toward 0 or 1
                    if (failure_pattern[0]) begin
                        entropy_i = 32'hFFFFFFFF; // All 1s
                    end else begin
                        entropy_i = 32'h00000000; // All 0s
                    end
                end
                3'd2: begin
                    // For 2-bit samples, repeat the 2-bit failure pattern
                    case (failure_pattern[1:0])
                        2'b00: entropy_i = 32'h00000000; // 00 00 00 00 00 00 00 00
                        2'b01: entropy_i = 32'h55555555; // 01 01 01 01 01 01 01 01
                        2'b10: entropy_i = 32'hAAAAAAAA; // 10 10 10 10 10 10 10 10
                        2'b11: entropy_i = 32'hFFFFFFFF; // 11 11 11 11 11 11 11 11
                    endcase
                end
                3'd3: begin
                    // For 3-bit samples, repeat the 3-bit failure pattern
                    case (failure_pattern[2:0])
                        3'b000: entropy_i = 32'h00000000; // 000 000 000 000 000 0
                        3'b001: entropy_i = 32'h12491249; // 001 001 001 001 001 0
                        3'b010: entropy_i = 32'h24922492; // 010 010 010 010 010 0
                        3'b011: entropy_i = 32'h36DB36DB; // 011 011 011 011 011 0
                        3'b100: entropy_i = 32'h49244924; // 100 100 100 100 100 1
                        3'b101: entropy_i = 32'h5B6D5B6D; // 101 101 101 101 101 1
                        3'b110: entropy_i = 32'h6DB66DB6; // 110 110 110 110 110 1
                        3'b111: entropy_i = 32'hFFFFFFFF; // 111 111 111 111 111 1
                    endcase
                end
                3'd4: begin
                    // For 4-bit samples, repeat the 4-bit failure pattern
                    entropy_i = {failure_pattern, failure_pattern, failure_pattern, failure_pattern};
                end
                default: begin
                    entropy_i = prng_data;
                end
            endcase
        end else begin
            entropy_i = prng_data;
        end
    end

    // Test sequence control
    initial begin
        $display("=== Adaptive Proportion Test (APT) Comprehensive Testbench ===");
        $display("Time=%0t: Starting APT test with failure injection", $time);

        // Initialize test thresholds (conservative values for testing)
        test_thresholds[1] = 10'd600;  // For 1-bit samples (out of 1024)
        test_thresholds[2] = 10'd300;  // For 2-bit samples (out of 512)
        test_thresholds[3] = 10'd200;  // For 3-bit samples (out of 512)
        test_thresholds[4] = 10'd150;  // For 4-bit samples (out of 512)

        // Test cycles per phase
        test_cycles_per_phase[1] = 16'd2000;  // 1-bit: need 1024+ samples
        test_cycles_per_phase[2] = 16'd1500;  // 2-bit: need 512+ samples
        test_cycles_per_phase[3] = 16'd1200;  // 3-bit: need 512+ samples
        test_cycles_per_phase[4] = 16'd1000;  // 4-bit: need 512+ samples

        // Initialize all failure counters
        phase_failures[1] = 0;
        phase_failures[2] = 0;
        phase_failures[3] = 0;
        phase_failures[4] = 0;

        // Initialize
        rst_ni = 0;
        enable_i = 0;
        sample_size_i = 3'd1;
        proportion_limit_i = 10'd100;
        inject_failure = 0;
        failure_pattern = 4'b0;

        // Reset sequence
        #100;
        rst_ni = 1;
        #50;

        $display("Time=%0t: Reset released, beginning test phases", $time);

        // Test Phase 1: 1-bit samples
        run_sample_size_test(1);

        // Test Phase 2: 2-bit samples
        run_sample_size_test(2);

        // Test Phase 3: 3-bit samples
        run_sample_size_test(3);

        // Test Phase 4: 4-bit samples
        run_sample_size_test(4);

        // Final results
        $display("");
        $display("=== FINAL TEST RESULTS ===");
        $display("Total tests run: %0d", total_tests_run);
        $display("Total tests passed: %0d", total_tests_passed);
        $display("Overall success rate: %.1f%%", (total_tests_passed * 100.0) / total_tests_run);
        $display("");
        $display("Failures detected per sample size:");
        $display("  1-bit samples: %0d failures detected", phase_failures[1]);
        $display("  2-bit samples: %0d failures detected", phase_failures[2]);
        $display("  3-bit samples: %0d failures detected", phase_failures[3]);
        $display("  4-bit samples: %0d failures detected", phase_failures[4]);

        if (total_tests_passed == total_tests_run) begin
            $display("");
            $display("*** ALL TESTS PASSED! APT implementation is working correctly. ***");
        end else begin
            $display("");
            $display("*** SOME TESTS FAILED! Check APT implementation. ***");
        end

        $finish;
    end

    // Task to run tests for a specific sample size
    task run_sample_size_test(input integer sample_bits);
        integer pattern;
        integer max_patterns;

        begin
            $display("");
            $display("=== Testing %0d-bit samples ===", sample_bits);

            // Configure for this sample size
            sample_size_i = sample_bits[2:0];
            proportion_limit_i = test_thresholds[sample_bits];
            max_patterns = (1 << sample_bits);

            $display("Sample size: %0d bits", sample_bits);
            $display("Threshold: %0d", proportion_limit_i);
            $display("Expected patterns: %0d", max_patterns);

            // Test each possible pattern for bias
            for (pattern = 0; pattern < max_patterns; pattern = pattern + 1) begin
                $display("");
                $display("--- Testing pattern %0d (binary: %b) ---", pattern, pattern);
                test_pattern_bias(sample_bits, pattern);
            end

            $display("=== Completed %0d-bit sample tests ===", sample_bits);
        end
    endtask

    // Task to test bias for a specific pattern
    task test_pattern_bias(input integer sample_bits, input integer pattern);
        integer i;
        integer normal_cycles;
        integer bias_cycles;
        integer status_changes;
        reg last_status;

        begin
            total_tests_run = total_tests_run + 1;

            // Reset the module
            enable_i = 0;
            #20;
            enable_i = 1;
            inject_failure = 0;
            failure_pattern = pattern[3:0];

            // Phase 1: Normal operation (should not trigger)
            normal_cycles = test_cycles_per_phase[sample_bits] / 4;
            status_changes = 0;
            last_status = status_o;

            $display("Phase 1: %0d cycles of normal data", normal_cycles);
            for (i = 0; i < normal_cycles; i = i + 1) begin
                @(posedge clk_i);
                if (status_o !== last_status) begin
                    status_changes = status_changes + 1;
                    last_status = status_o;
                end
            end

            if (status_o == 1'b1) begin
                $display("WARNING: APT triggered during normal operation (unexpected)");
            end else begin
                $display("✓ Normal operation: No false positives");
            end

            // Phase 2: Inject biased data (should trigger)
            bias_cycles = test_cycles_per_phase[sample_bits] * 3 / 4;
            inject_failure = 1;

            $display("Phase 2: %0d cycles with biased pattern %b", bias_cycles, pattern);
            for (i = 0; i < bias_cycles && status_o !== 1'b1; i = i + 1) begin
                @(posedge clk_i);
                if (status_o !== last_status) begin
                    status_changes = status_changes + 1;
                    last_status = status_o;
                    if (status_o == 1'b1) begin
                        $display("✓ APT correctly detected bias at cycle %0d", i);
                        phase_failures[sample_bits] = phase_failures[sample_bits] + 1;
                    end
                end
            end

            if (status_o == 1'b1) begin
                $display("✓ PASS: Pattern %b bias correctly detected", pattern);
                total_tests_passed = total_tests_passed + 1;
            end else begin
                $display("✗ FAIL: Pattern %b bias NOT detected", pattern);
            end

            // Stop failure injection
            inject_failure = 0;

            // Small delay before next test
            repeat(50) @(posedge clk_i);
        end
    endtask

    // Monitor for status changes during simulation
    always @(posedge status_o) begin
        if (enable_i) begin
            $display("Time=%0t: APT FAILURE DETECTED (sample_size=%0d, pattern=%b, threshold=%0d)",
                     $time, sample_size_i, failure_pattern, proportion_limit_i);
        end
    end

    // Monitor for status clearing
    always @(negedge status_o) begin
        if (enable_i) begin
            $display("Time=%0t: APT status cleared", $time);
        end
    end

    // VCD dump for waveform analysis
    initial begin
        $dumpfile("apt_test.vcd");
        $dumpvars(0, tb_adaptive_proportion_test);
        $dumpvars(1, u_apt.pattern_count_o);
        $dumpvars(1, u_apt.target_pattern_o);
        $dumpvars(1, u_apt.samples_processed_o);
        $dumpvars(1, u_apt.status_o);
        // Note: pattern_count is an array and cannot be dumped with $dumpvars in iverilog
    end

endmodule