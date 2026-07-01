// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Source Component
//
// Description:
// This component generates a stream of random numbers with high entropy.
// Features:
// - 12 coprime ring oscillator array with metastable sampling
// - online entropy health testing (Repetition, APT, Markov)
// - debug monitoring for intermediate signals
// - APB interface for configuration and data access
//
// Cryptographic Applications:
// -IV, nonce, and key generation
// -noise generation for side-channel-analysis (SCA) and fault injection (FI)
//  countermeasures
// -random values for challenge-response protocols
// -random salt values for password hashes
//
// Health Tests:
// - Repetition Test: Detects catastrophic "stuck-at" failures
// - Adaptive Proportion Test: Detects bias in sample patterns
// - Markov Test: Detects bit-to-bit correlation and memoryless property violations
//------------------------------------------------------------------------------


module entropy_source
    import entropy_source_reg_pkg::*,
           entropy_source_pkg::*;
(
    // Global Interface
    input  logic        clk_i,
    input  logic        rst_ni,

    // AXI4-Lite Register Interface
    // Write Address Channel
    input  logic        s_axil_awvalid_i,
    output logic        s_axil_awready_o,
    input  logic [8:0]  s_axil_awaddr_i,
    input  logic [2:0]  s_axil_awprot_i,

    // Write Data Channel
    input  logic        s_axil_wvalid_i,
    output logic        s_axil_wready_o,
    input  logic [31:0] s_axil_wdata_i,
    input  logic [3:0]  s_axil_wstrb_i,

    // Write Response Channel
    output logic        s_axil_bvalid_o,
    input  logic        s_axil_bready_i,
    output logic [1:0]  s_axil_bresp_o,

    // Read Address Channel
    input  logic        s_axil_arvalid_i,
    output logic        s_axil_arready_o,
    input  logic [8:0]  s_axil_araddr_i,
    input  logic [2:0]  s_axil_arprot_i,

    // Read Data Channel
    output logic        s_axil_rvalid_o,
    input  logic        s_axil_rready_i,
    output logic [31:0] s_axil_rdata_o,
    output logic [1:0]  s_axil_rresp_o,

    output logic        signal_monitor_o,
    input  logic        rosc_sample_clk_i,

    output logic [31:0] entropy_stream_data_o,
    output logic        entropy_stream_vld_o,
    output logic        irq_o
);

    entropy_source_reg_pkg::entropy_source__in_t  reg_in;
    entropy_source_reg_pkg::entropy_source__out_t reg_out;

    logic rst_n;
    assign rst_n = rst_ni & ~reg_out.CTRL.RESET.value;

    logic [31:0]            entropy_stream;
    logic [NRINGS-1:0][7:0] entropy_stream_uncompressed;
    logic                   entropy_stream_valid;           // Not gated by the Startup Counter
    logic                   entropy_stream_valid_gated; // Gated by the Startup Counter
    logic [NRINGS-1:0]      noise_bit_monitor;
    logic [NRINGS-1:0]      sample_clk_monitor;
    logic [7:0]             health_status;
    logic                   window_wrap_pulse;

    // Individual generator health status signals
    logic [7:0]        generator_0_test_status, generator_1_test_status, generator_2_test_status, generator_3_test_status;
    logic [7:0]        generator_4_test_status, generator_5_test_status, generator_6_test_status, generator_7_test_status;
    logic [7:0]        generator_8_test_status, generator_9_test_status, generator_10_test_status, generator_11_test_status;

    // Health test counter signals
    logic [15:0]       ctr_repetition;
    // APT parallel outputs for all 4 sample sizes (1bit/2bit widened to 16-bit)
    logic [15:0]       apt_pattern_count_1bit, apt_pattern_count_2bit;
    logic [9:0]        apt_pattern_count_3bit, apt_pattern_count_4bit;
    logic [3:0]        apt_target_pattern_1bit, apt_target_pattern_2bit, apt_target_pattern_3bit, apt_target_pattern_4bit;
    logic [9:0]        apt_samples_processed_1bit, apt_samples_processed_2bit, apt_samples_processed_3bit, apt_samples_processed_4bit;
    // Markov test counters and probabilities
    logic [15:0]       count_01, count_10, count_00, count_11;
    logic [7:0]        prob_01,  prob_10,  prob_00,  prob_11;

    // Entropy FIFO
    logic              fifo_push;
    logic [31:0]       fifo_wdata, fifo_rdata;
    logic [6:0]        fifo_level;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [5:0]        fifo_wptr, fifo_rptr; // bit [5] unused - only [4:0] used for registers
    /* verilator lint_on UNUSEDSIGNAL */
    logic              fifo_error;
    logic              fifo_overflow, fifo_underflow;
    // Open signals for unused FIFO error outputs (to avoid PINCONNECTEMPTY warnings)
    /* verilator lint_off UNUSEDSIGNAL */
    logic              open_parity_error, open_pointer_error; // Intentionally unused - connected to avoid PINCONNECTEMPTY
    /* verilator lint_on UNUSEDSIGNAL */

    // SHA-256 whitener (optional stage AFTER health test, BEFORE FIFO)
    // When enabled, provides cryptographic conditioning per NIST SP 800-90B
    // When disabled (bypass mode), entropy_stream passes through directly
    logic [31:0] whitened_data;
    logic        whitened_valid;


    // provide external stream access to data pushed into collection FIFO
    assign entropy_stream_data_o = fifo_wdata;
    assign entropy_stream_vld_o  = fifo_push;

    entropy_generator_complex #(
        .NRINGS       (NRINGS),
        .CLKDIV_WIDTH (20)      // TODO: update to 24 as future feature
    ) egen (
        .clk_i,
        .rst_ni                                 (rst_n),
        .sample_clk_i                           (rosc_sample_clk_i),
        .entropy_stream_o                       (entropy_stream),
        .entropy_stream_uncompressed_o          (entropy_stream_uncompressed),
        .entropy_stream_valid_o                 (entropy_stream_valid),
        .noise_bit_monitor_o                    (noise_bit_monitor),
        .sample_clk_monitor_o                   (sample_clk_monitor),

        .jitter_ro_enable_i                     (reg_out.RING_OSC_ENABLE.ENABLE.value),
        .jitter_ro_detune_i                     (reg_out.RING_OSC_TUNE.DETUNE.value),
        .jitter_ro_auto_tune_enable_i           ({NRINGS{reg_out.CTRL.AUTOTUNE_ENABLE.value}}),

        .sample_clk_select_i                    (reg_out.RING_OSC_CTRL.SAMPLE_CLK_SELECT.value),
        .sample_clk_ro_detune_i                 (reg_out.RING_OSC_TUNE.SAMPLE_CLK_DETUNE.value),
        .sample_clk_enable_i                    (reg_out.RING_OSC_ENABLE.SAMPLE_CLK_ENABLE.value),
        .sample_clk_divide_i                    ({reg_out.GENERATOR_11_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_10_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_9_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_8_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_7_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_6_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_5_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_4_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_3_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_2_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_1_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
                                                  reg_out.GENERATOR_0_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value}),

        .decorrelator_bypass_i                  (reg_out.DECORRELATOR_CTRL.BYPASS.value),
        .decorrelator_sample_clk_div_i          (reg_out.DECORRELATOR_CTRL.SAMPLE_CLK_DIV.value),
        .decorrelator_entropy_byte_mask_i       (reg_out.DECORRELATOR_MASK.ENTROPY_BYTE_MASK.value),

        .health_test_enable_i                   (reg_out.HEALTH_TEST_CTRL.ENABLE.value),
        .health_test_repetition_limit_i         (reg_out.HEALTH_TEST_CTRL.REPETITION_LIMIT.value),
        .health_test_proportion_limit_1bit_i    (reg_out.APT_PROPORTION_1BIT.LIMIT.value),
        .health_test_proportion_limit_lo_i      (reg_out.APT_PROPORTION_LO.LIMIT.value),
        .health_test_proportion_limit_2bit_i    (reg_out.APT_PROPORTION_2BIT.LIMIT.value),
        .health_test_proportion_limit_3bit_i    (reg_out.APT_PROPORTION_3BIT.LIMIT.value),
        .health_test_proportion_limit_4bit_i    (reg_out.APT_PROPORTION_4BIT.LIMIT.value),
        .health_test_markov_prob_01_threshold_i (reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_01_THRESHOLD.value),
        .health_test_markov_prob_10_threshold_i (reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_10_THRESHOLD.value),
        .health_test_window_size_i              (reg_out.HEALTH_TEST_WINDOW_SIZE.SIZE.value),

        // Individual generator health status outputs
        .generator_0_test_status_o              (generator_0_test_status),
        .generator_1_test_status_o              (generator_1_test_status),
        .generator_2_test_status_o              (generator_2_test_status),
        .generator_3_test_status_o              (generator_3_test_status),
        .generator_4_test_status_o              (generator_4_test_status),
        .generator_5_test_status_o              (generator_5_test_status),
        .generator_6_test_status_o              (generator_6_test_status),
        .generator_7_test_status_o              (generator_7_test_status),
        .generator_8_test_status_o              (generator_8_test_status),
        .generator_9_test_status_o              (generator_9_test_status),
        .generator_10_test_status_o             (generator_10_test_status),
        .generator_11_test_status_o             (generator_11_test_status),

        // Window wrap pulse output
        .window_wrap_pulse_o                    (window_wrap_pulse)
    );

    entropy_debug_monitor #(
        .NSIGNALS          (256)
    ) dbg (
        .rst_ni            (rst_n),
        .select_signal_i   (reg_out.DEBUG_CTRL.SELECT_SIGNAL.value),
        .signal_i          ({32'h0, entropy_stream_uncompressed, 32'h0, whitened_data, entropy_stream, 4'h0, sample_clk_monitor, 4'h0, noise_bit_monitor}),
        .select_freq_div_i (reg_out.DEBUG_CTRL.SELECT_FREQ_DIV.value),
        .sig_monitor_o     (signal_monitor_o)
    );

    // Clock gating for 32-bit health tester
    // Disable when BIW compressor is bypassed (not normal operation mode)
    logic health_test_clk;
    logic health_test_enable;
    logic health_test_valid_gated;

    // Gate enable: active HIGH when NOT in bypass mode
    assign health_test_enable = ~reg_out.CTRL.BYPASS_ENTROPY_COMPRESSOR.value;

    prim_clkgater health_test_clk_gate (
        .i_clk  (clk_i),
        .i_en   (health_test_enable),  // Clock runs when NOT bypassed
        .i_te   (1'b0),                // No test enable in entropy source
        .o_clk  (health_test_clk)
    );

    // Gate health test valid when bypassed
    assign health_test_valid_gated = entropy_stream_valid & health_test_enable;

    entropy_health_test #(
        .DATA_WIDTH                   (32)
    ) htst (
        .clk_i                        (health_test_clk),
        .rst_ni                       (rst_n),
        .entropy_i                    (entropy_stream),
        .entropy_valid_i              (health_test_valid_gated),
        .enable_i                     (reg_out.HEALTH_TEST_CTRL.ENABLE.value),
        .repetition_limit_i           (reg_out.HEALTH_TEST_CTRL.REPETITION_LIMIT.value),
        .proportion_limit_1bit_i      (reg_out.APT_PROPORTION_1BIT.LIMIT.value),
        .proportion_limit_lo_i        (reg_out.APT_PROPORTION_LO.LIMIT.value),
        .proportion_limit_2bit_i      (reg_out.APT_PROPORTION_2BIT.LIMIT.value),
        .proportion_limit_3bit_i      (reg_out.APT_PROPORTION_3BIT.LIMIT.value),
        .proportion_limit_4bit_i      (reg_out.APT_PROPORTION_4BIT.LIMIT.value),
        // Markov test thresholds
        .markov_prob_01_threshold_i   (reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_01_THRESHOLD.value),
        .markov_prob_10_threshold_i   (reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_10_THRESHOLD.value),
        .window_wrap_pulse_i          (window_wrap_pulse),
        // Counter outputs - repetition test
        .ctr_repetition_o             (ctr_repetition),
        // Parallel APT outputs for all 4 sample sizes
        .apt_pattern_count_1bit_o     (apt_pattern_count_1bit),
        .apt_pattern_count_2bit_o     (apt_pattern_count_2bit),
        .apt_pattern_count_3bit_o     (apt_pattern_count_3bit),
        .apt_pattern_count_4bit_o     (apt_pattern_count_4bit),
        .apt_target_pattern_1bit_o    (apt_target_pattern_1bit),
        .apt_target_pattern_2bit_o    (apt_target_pattern_2bit),
        .apt_target_pattern_3bit_o    (apt_target_pattern_3bit),
        .apt_target_pattern_4bit_o    (apt_target_pattern_4bit),
        .apt_samples_processed_1bit_o (apt_samples_processed_1bit),
        .apt_samples_processed_2bit_o (apt_samples_processed_2bit),
        .apt_samples_processed_3bit_o (apt_samples_processed_3bit),
        .apt_samples_processed_4bit_o (apt_samples_processed_4bit),
        // Counter outputs - Markov test counters and probabilities
        .count_01_o                   (count_01),
        .count_10_o                   (count_10),
        .count_00_o                   (count_00),
        .count_11_o                   (count_11),
        .prob_01_o                    (prob_01),
        .prob_10_o                    (prob_10),
        .prob_00_o                    (prob_00),
        .prob_11_o                    (prob_11),
        .status_o                     (health_status) // Health test status output
    );

    entropy_sha256_whitener u_sha256_whitener (
        .clk_i               (clk_i),
        .rst_ni              (rst_n),
        .entropy_valid_i     (entropy_stream_valid_gated),
        .entropy_data_i      (entropy_stream),
        .entropy_ready_o     (),  // Not used - no backpressure
        .whitened_valid_o    (whitened_valid),
        .whitened_data_o     (whitened_data),
        .whitened_ready_i    (1'b1),  // Always ready to accept
        .enable_i            (reg_out.CTRL.SHA256_WHITENING_ENABLE.value),
        .busy_o              (reg_in.SHA256_STATUS.BUSY.next),
        .input_count_o       (reg_in.SHA256_STATUS.INPUT_COUNT.next),
        .output_count_o      (reg_in.SHA256_STATUS.OUTPUT_COUNT.next)
    );

    entropy_fifo #(
        .DEPTH(64)
    ) entropy_fifo (
        .clk_i,
        .rst_ni              (rst_n),
        .push_i              (reg_out.FIFO_CTRL.ENABLE.value && fifo_push),
        .pop_i               (reg_out.FIFO_RDATA.req &&
                              !reg_out.FIFO_RDATA.req_is_wr),  // Pop not gated by ENABLE - allow draining when frozen
        .wdata_i              (fifo_wdata),
        .entropy_churn_enable_i(reg_out.FIFO_CTRL.ENTROPY_CHURN_ENABLE.value),
        .rdata_o              (fifo_rdata),
        .level_o             (fifo_level),
        .wptr_o              (fifo_wptr),
        .rptr_o              (fifo_rptr),
        .overflow_o          (fifo_overflow),
        .underflow_o         (fifo_underflow),
        // Security error outputs (currently unused, connected to open signals)
        .parity_error_o      (open_parity_error),
        .pointer_error_o     (open_pointer_error),
        .security_alert_o    (fifo_error) // Logical OR of all FIFO error signals
    );

    logic [15:0] delay_count;

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            delay_count <= reg_out.STARTUP_CTRL.DELAY_CYCLES.value;
        end else if (reg_out.CTRL.RESET.value) begin
            delay_count <= reg_out.STARTUP_CTRL.DELAY_CYCLES.value;
        end else if (delay_count != 16'd0) begin
            delay_count <= delay_count - 16'd1;
        end
    end

    assign entropy_stream_valid_gated = (delay_count == 16'd0) && entropy_stream_valid;

    logic [9:0] downsample_count;

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            downsample_count <= reg_out.CTRL.DOWNSAMPLE_RATE.value;
        end else if (entropy_stream_valid_gated) begin
            if (downsample_count == 10'd0) begin
                downsample_count <= reg_out.CTRL.DOWNSAMPLE_RATE.value;
            end else begin
                downsample_count <= downsample_count - 10'd1;
            end
        end
    end

    logic fifo_stream_push;

    assign fifo_stream_push = entropy_stream_valid_gated && (downsample_count == 10'd0);

    typedef enum logic {
        ST_FIFO_PUSH_IDLE = 1'd0,
        ST_FIFO_PUSH      = 1'd1
    } fifo_push_fsm_state_e;

    logic [NRINGS-1:0][7:0] fifo_push_stream, fifo_push_stream_next;
    logic [1:0]             fifo_push_count,  fifo_push_count_next;
    fifo_push_fsm_state_e   fifo_push_state,  fifo_push_state_next;

    always_comb begin
        fifo_push = 1'b0;
        fifo_wdata = whitened_data;

        fifo_push_stream_next = fifo_push_stream;
        fifo_push_count_next  = fifo_push_count;
        fifo_push_state_next  = fifo_push_state;

        unique case (fifo_push_state)
            ST_FIFO_PUSH_IDLE: begin
                if (reg_out.CTRL.BYPASS_ENTROPY_COMPRESSOR.value) begin
                    if (fifo_stream_push) begin
                        fifo_push = 1'b1;
                        fifo_wdata = {entropy_stream_uncompressed[fifo_push_count * 4 + 3],
                                      entropy_stream_uncompressed[fifo_push_count * 4 + 2],
                                      entropy_stream_uncompressed[fifo_push_count * 4 + 1],
                                      entropy_stream_uncompressed[fifo_push_count * 4 + 0]}; // TODO: Make parameterizable

                        fifo_push_stream_next = entropy_stream_uncompressed;
                        fifo_push_count_next  = fifo_push_count + 2'd1;
                        fifo_push_state_next  = ST_FIFO_PUSH;
                    end else begin
                        fifo_push_state_next = ST_FIFO_PUSH_IDLE;
                    end
                end else begin
                    fifo_push  = whitened_valid;
                    fifo_wdata = whitened_data;

                    fifo_push_state_next = ST_FIFO_PUSH_IDLE;
                end
            end
            ST_FIFO_PUSH: begin
                if (reg_out.CTRL.BYPASS_ENTROPY_COMPRESSOR.value) begin
                    fifo_push  = 1'b1;
                    fifo_wdata = {fifo_push_stream[fifo_push_count * 4 + 3],
                                  fifo_push_stream[fifo_push_count * 4 + 2],
                                  fifo_push_stream[fifo_push_count * 4 + 1],
                                  fifo_push_stream[fifo_push_count * 4 + 0]}; // TODO: Make parameterizable

                    if (fifo_push_count == 2'd2) begin
                        fifo_push_count_next = 2'd0;
                        fifo_push_state_next = ST_FIFO_PUSH_IDLE;
                    end else begin
                        fifo_push_count_next = fifo_push_count + 2'd1;
                        fifo_push_state_next = ST_FIFO_PUSH;
                    end
                end else begin
                    fifo_push  = whitened_valid;
                    fifo_wdata = whitened_data;

                    fifo_push_count_next = 2'd0;
                    fifo_push_state_next = ST_FIFO_PUSH_IDLE;
                end
            end
            default: begin
                fifo_push_count_next = 2'd0;
                fifo_push_state_next = ST_FIFO_PUSH_IDLE;
            end
        endcase
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            fifo_push_stream <= '0;
            fifo_push_count  <= 2'd0;
            fifo_push_state  <= ST_FIFO_PUSH_IDLE;
        end else begin
            fifo_push_stream <= fifo_push_stream_next;
            fifo_push_count  <= fifo_push_count_next;
            fifo_push_state  <= fifo_push_state_next;
        end
    end

    assign reg_in.FIFO_RDATA.rd_data = fifo_rdata;
    assign reg_in.FIFO_RDATA.rd_ack  = reg_out.FIFO_RDATA.req && !reg_out.FIFO_RDATA.req_is_wr;


    // AXI4-Lite interface instance for register block
    axi4lite_intf #(
        .ADDR_WIDTH(9),
        .DATA_WIDTH(32)
    ) s_axil ();

    // Connect module ports to interface
    assign s_axil.AWVALID = s_axil_awvalid_i;
    assign s_axil_awready_o = s_axil.AWREADY;
    assign s_axil.AWADDR = s_axil_awaddr_i;
    assign s_axil.AWPROT = s_axil_awprot_i;

    assign s_axil.WVALID = s_axil_wvalid_i;
    assign s_axil_wready_o = s_axil.WREADY;
    assign s_axil.WDATA = s_axil_wdata_i;
    assign s_axil.WSTRB = s_axil_wstrb_i;

    assign s_axil_bvalid_o = s_axil.BVALID;
    assign s_axil.BREADY = s_axil_bready_i;
    assign s_axil_bresp_o = s_axil.BRESP;

    assign s_axil.ARVALID = s_axil_arvalid_i;
    assign s_axil_arready_o = s_axil.ARREADY;
    assign s_axil.ARADDR = s_axil_araddr_i;
    assign s_axil.ARPROT = s_axil_arprot_i;

    assign s_axil_rvalid_o = s_axil.RVALID;
    assign s_axil.RREADY = s_axil_rready_i;
    assign s_axil_rdata_o = s_axil.RDATA;
    assign s_axil_rresp_o = s_axil.RRESP;

    entropy_source_reg entropy_source_reg (
        .clk           (clk_i),
        .arst_n        (rst_ni),
        .s_axil        (s_axil.slave),
        .hwif_in       (reg_in),
        .hwif_out      (reg_out)
    );

    // Global Status Register
    assign reg_in.STATUS.RSVD.next = 1'b0; // TODO

    // Interrupt Registers
    assign reg_in.INTR_STATUS.HEALTH_TEST_FAILED.next =
        (|health_status || reg_out.INTR_TEST.HEALTH_TEST_FAILED.value) &&
        reg_out.INTR_ENABLE.HEALTH_TEST_FAILED.value;
    assign reg_in.INTR_STATUS.FIFO_ERROR.next =
        (fifo_error || reg_out.INTR_TEST.FIFO_ERROR.value) &&
        reg_out.INTR_ENABLE.FIFO_ERROR.value;
    assign reg_in.INTR_STATUS.FIFO_OVERFLOW.next =
        (fifo_overflow || reg_out.INTR_TEST.FIFO_OVERFLOW.value) &&
        reg_out.INTR_ENABLE.FIFO_OVERFLOW.value;
    assign reg_in.INTR_STATUS.FIFO_UNDERFLOW.next =
        (fifo_underflow || reg_out.INTR_TEST.FIFO_UNDERFLOW.value) &&
        reg_out.INTR_ENABLE.FIFO_UNDERFLOW.value;

    assign irq_o = reg_out.INTR_STATUS.intr; // Logical OR of all interrupt sources

    // FIFO Status Registers
    assign reg_in.FIFO_STATUS.LEVEL.next = fifo_level;
    assign reg_in.FIFO_STATUS.WPTR.next  = fifo_wptr[4:0]; // Truncate 6-bit to 5-bit
    assign reg_in.FIFO_STATUS.RPTR.next  = fifo_rptr[4:0]; // Truncate 6-bit to 5-bit

    // Health Test Status Registers
    assign reg_in.HEALTH_TEST_STATUS.HEALTH_STATUS.next = health_status;

    // Parallel APT: connect all 4 sample size registers
    assign reg_in.APT_PATTERN_COUNT_1BIT.PATTERN_COUNT.next     = apt_pattern_count_1bit;
    assign reg_in.APT_PATTERN_COUNT_1BIT.TARGET_PATTERN.next    = apt_target_pattern_1bit;
    assign reg_in.APT_PATTERN_COUNT_1BIT.SAMPLES_PROCESSED.next = apt_samples_processed_1bit;

    assign reg_in.APT_PATTERN_COUNT_2BIT.PATTERN_COUNT.next     = apt_pattern_count_2bit;
    assign reg_in.APT_PATTERN_COUNT_2BIT.TARGET_PATTERN.next    = apt_target_pattern_2bit;
    assign reg_in.APT_PATTERN_COUNT_2BIT.SAMPLES_PROCESSED.next = apt_samples_processed_2bit;

    assign reg_in.APT_PATTERN_COUNT_3BIT.PATTERN_COUNT.next     = apt_pattern_count_3bit;
    assign reg_in.APT_PATTERN_COUNT_3BIT.TARGET_PATTERN.next    = apt_target_pattern_3bit;
    assign reg_in.APT_PATTERN_COUNT_3BIT.SAMPLES_PROCESSED.next = apt_samples_processed_3bit;

    assign reg_in.APT_PATTERN_COUNT_4BIT.PATTERN_COUNT.next     = apt_pattern_count_4bit;
    assign reg_in.APT_PATTERN_COUNT_4BIT.TARGET_PATTERN.next    = apt_target_pattern_4bit;
    assign reg_in.APT_PATTERN_COUNT_4BIT.SAMPLES_PROCESSED.next = apt_samples_processed_4bit;

    assign reg_in.REPETITION_TEST_COUNT.REPETITION_COUNT.next = ctr_repetition;

    assign reg_in.MARKOV_TEST_COUNTS_0.COUNT_01.next = count_01;
    assign reg_in.MARKOV_TEST_COUNTS_0.COUNT_10.next = count_10;
    assign reg_in.MARKOV_TEST_COUNTS_1.COUNT_00.next = count_00;
    assign reg_in.MARKOV_TEST_COUNTS_1.COUNT_11.next = count_11;
    assign reg_in.MARKOV_TEST_PROBABILITIES.PROB_01.next = prob_01;
    assign reg_in.MARKOV_TEST_PROBABILITIES.PROB_10.next = prob_10;
    assign reg_in.MARKOV_TEST_PROBABILITIES.PROB_00.next = prob_00;
    assign reg_in.MARKOV_TEST_PROBABILITIES.PROB_11.next = prob_11;

    // Individual generator health status register connections
    assign reg_in.GENERATOR_0_HEALTH_STATUS.STATUS.next  = generator_0_test_status;
    assign reg_in.GENERATOR_1_HEALTH_STATUS.STATUS.next  = generator_1_test_status;
    assign reg_in.GENERATOR_2_HEALTH_STATUS.STATUS.next  = generator_2_test_status;
    assign reg_in.GENERATOR_3_HEALTH_STATUS.STATUS.next  = generator_3_test_status;
    assign reg_in.GENERATOR_4_HEALTH_STATUS.STATUS.next  = generator_4_test_status;
    assign reg_in.GENERATOR_5_HEALTH_STATUS.STATUS.next  = generator_5_test_status;
    assign reg_in.GENERATOR_6_HEALTH_STATUS.STATUS.next  = generator_6_test_status;
    assign reg_in.GENERATOR_7_HEALTH_STATUS.STATUS.next  = generator_7_test_status;
    assign reg_in.GENERATOR_8_HEALTH_STATUS.STATUS.next  = generator_8_test_status;
    assign reg_in.GENERATOR_9_HEALTH_STATUS.STATUS.next  = generator_9_test_status;
    assign reg_in.GENERATOR_10_HEALTH_STATUS.STATUS.next = generator_10_test_status;
    assign reg_in.GENERATOR_11_HEALTH_STATUS.STATUS.next = generator_11_test_status;

    //------------------------------//
    // WATERMARK AND FAIL COUNTERS  //
    //------------------------------//

    // Watermark selector state
    typedef enum logic [3:0] {
        REPCNT_HI   = 4'h0,
        APT_HI      = 4'h1,
        APT_LO      = 4'h2,
        MARKOV_HI   = 4'h3,
        MARKOV_LO   = 4'h4
    } watermark_test_e;

    watermark_test_e ht_watermark_num_q, ht_watermark_num_d;
    watermark_test_e ht_watermark_num_reg_if;
    logic            ht_watermark_high;
    logic            ht_watermark_event_pre;
    logic            ht_watermark_event;
    logic [15:0]     ht_watermark_cnt;
    logic [15:0]     ht_watermark;

    // Counter values
    logic [15:0] repcnt_event_cnt;
    logic [15:0] apt_hi_event_cnt, apt_lo_event_cnt;
    logic [15:0] markov_hi_event_cnt, markov_lo_event_cnt;

    // Clearing signals
    logic health_test_clr;
    logic alert_cntrs_clr;
    logic alert_cntr_clr_ok;

    // Fail pulse signals
    logic repcnt_fail_pulse;
    logic apt_hi_fail_pulse, apt_lo_fail_pulse;
    logic markov_hi_fail_pulse, markov_lo_fail_pulse;
    logic any_fail_pulse;

    // Total fail counter values
    logic [31:0] repcnt_total_fails;
    logic [31:0] apt_hi_total_fails, apt_lo_total_fails;
    logic [31:0] markov_hi_total_fails, markov_lo_total_fails;
    logic [15:0] any_fail_count;

    // Alert fail counter values (4-bit)
    logic [3:0] repcnt_fail_count;
    logic [3:0] apt_hi_fail_count, apt_lo_fail_count;
    logic [3:0] markov_hi_fail_count, markov_lo_fail_count;

    // Counter error signals
    logic repcnt_fails_cntr_err;
    logic apt_hi_fails_cntr_err, apt_lo_fails_cntr_err;
    logic markov_hi_fails_cntr_err, markov_lo_fails_cntr_err;
    logic any_fails_cntr_err;
    logic repcnt_alert_cntr_err;
    logic apt_hi_alert_cntr_err, apt_lo_alert_cntr_err;
    logic markov_hi_alert_cntr_err, markov_lo_alert_cntr_err;
    logic es_cntr_err;

    // Extract failure signals from health_status
    assign repcnt_fail_pulse     = health_status[0];
    assign apt_hi_fail_pulse     = health_status[3];  // Note: current design combines hi|lo
    assign apt_lo_fail_pulse     = 1'b0;              // Not separately available in current design
    assign markov_hi_fail_pulse  = health_status[4];
    assign markov_lo_fail_pulse  = health_status[5];

    // Any failure signal
    assign any_fail_pulse = repcnt_fail_pulse || apt_hi_fail_pulse || apt_lo_fail_pulse ||
                            markov_hi_fail_pulse || markov_lo_fail_pulse;

    // Clearing logic
    assign health_test_clr = reg_out.CTRL.RESET.value;  // Clear on module reset
    assign alert_cntr_clr_ok = 1'b1;  // TODO: Set based on passing health test window
    assign alert_cntrs_clr = health_test_clr || (window_wrap_pulse && alert_cntr_clr_ok && !any_fail_pulse);

    // Counter error aggregation
    assign es_cntr_err = repcnt_fails_cntr_err || apt_hi_fails_cntr_err || apt_lo_fails_cntr_err ||
                         markov_hi_fails_cntr_err || markov_lo_fails_cntr_err || any_fails_cntr_err ||
                         repcnt_alert_cntr_err || apt_hi_alert_cntr_err || apt_lo_alert_cntr_err ||
                         markov_hi_alert_cntr_err || markov_lo_alert_cntr_err;

    //--------------------------------------------
    // watermark register
    //--------------------------------------------

    // Get and resolve HT_WATERMARK_NUM values from register interface.
    assign ht_watermark_num_reg_if = watermark_test_e'(reg_out.HT_WATERMARK_NUM.WATERMARK_NUM.value);

    always_comb begin
        unique case (ht_watermark_num_reg_if)
            REPCNT_HI,
            APT_HI,
            APT_LO,
            MARKOV_HI,
            MARKOV_LO: ht_watermark_num_d = ht_watermark_num_reg_if;
            default:   ht_watermark_num_d = REPCNT_HI;  // Unsupported values are mapped to REPCNT_HI.
        endcase
    end

    // Register the resolved value
    always_ff @(posedge clk_i or negedge rst_n) begin
        if (!rst_n) begin
            ht_watermark_num_q <= REPCNT_HI;
        end else begin
            ht_watermark_num_q <= ht_watermark_num_d;
        end
    end

    // Write back the sanitized value to the register
    assign reg_in.HT_WATERMARK_NUM.WATERMARK_NUM.next = ht_watermark_num_d;

    // Select the health test for which we want to record the watermark based on the HT_WATERMARK_NUM
    // register.
    always_comb begin
        unique case (ht_watermark_num_q)
            REPCNT_HI: begin
                ht_watermark_high      = 1'b1;
                ht_watermark_event_pre = 1'b1;  // continuous
                ht_watermark_cnt       = repcnt_event_cnt;
            end
            APT_HI: begin
                ht_watermark_high      = 1'b1;
                ht_watermark_event_pre = window_wrap_pulse;
                ht_watermark_cnt       = apt_hi_event_cnt;
            end
            APT_LO: begin
                ht_watermark_high      = 1'b0;
                ht_watermark_event_pre = window_wrap_pulse;
                ht_watermark_cnt       = apt_lo_event_cnt;
            end
            MARKOV_HI: begin
                ht_watermark_high      = 1'b1;
                ht_watermark_event_pre = window_wrap_pulse;
                ht_watermark_cnt       = markov_hi_event_cnt;
            end
            MARKOV_LO: begin
                ht_watermark_high      = 1'b0;
                ht_watermark_event_pre = window_wrap_pulse;
                ht_watermark_cnt       = markov_lo_event_cnt;
            end
            default: begin  // Unsupported values are mapped to REPCNT_HI.
                ht_watermark_high      = 1'b1;
                ht_watermark_event_pre = 1'b1;  // continuous
                ht_watermark_cnt       = repcnt_event_cnt;
            end
        endcase
    end

    // Prevent watermark register updates while the module disabled. Upon enabling, we then clear
    // the watermark register before we start recording.
    assign ht_watermark_event = ht_watermark_event_pre && reg_out.HEALTH_TEST_CTRL.ENABLE.value;

    // Prepare counter values for watermark (all 16-bit now, direct assignment)
    assign repcnt_event_cnt    = ctr_repetition;              // 16-bit
    assign apt_hi_event_cnt    = apt_pattern_count_1bit;      // 16-bit
    assign apt_lo_event_cnt    = apt_pattern_count_2bit;      // 16-bit
    assign markov_hi_event_cnt = count_01;                    // 16-bit (0→1 transitions)
    assign markov_lo_event_cnt = count_10;                    // 16-bit (1→0 transitions)

    // Main watermark register with multiplexed input
    entropy_src_watermark_reg #(
        .RegWidth(16),
        .ResVal(16'h0)
    ) u_entropy_src_ht_watermark_reg (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .high_i(ht_watermark_high),
        .clear_i(health_test_clr),
        .oneway_i(1'b1),  // Always one-way
        .event_i(ht_watermark_event),
        .value_i(ht_watermark_cnt),
        .value_o(ht_watermark)
    );

    // Repetition test total fails
    entropy_src_cntr_reg #(.RegWidth(32))
        u_entropy_src_cntr_reg_repcnt (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(health_test_clr),
        .event_i(repcnt_fail_pulse),
        .step_i(32'd1),
        .value_o(repcnt_total_fails),
        .err_o(repcnt_fails_cntr_err)
    );

    // APT high total fails
    entropy_src_cntr_reg #(.RegWidth(32))
        u_entropy_src_cntr_reg_apt_hi (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(health_test_clr),
        .event_i(apt_hi_fail_pulse),
        .step_i(32'd1),
        .value_o(apt_hi_total_fails),
        .err_o(apt_hi_fails_cntr_err)
    );

    // APT low total fails
    entropy_src_cntr_reg #(.RegWidth(32))
        u_entropy_src_cntr_reg_apt_lo (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(health_test_clr),
        .event_i(apt_lo_fail_pulse),
        .step_i(32'd1),
        .value_o(apt_lo_total_fails),
        .err_o(apt_lo_fails_cntr_err)
    );

    // Markov high total fails
    entropy_src_cntr_reg #(.RegWidth(32))
        u_entropy_src_cntr_reg_markov_hi (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(health_test_clr),
        .event_i(markov_hi_fail_pulse),
        .step_i(32'd1),
        .value_o(markov_hi_total_fails),
        .err_o(markov_hi_fails_cntr_err)
    );

    // Markov low total fails
    entropy_src_cntr_reg #(.RegWidth(32))
        u_entropy_src_cntr_reg_markov_lo (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(health_test_clr),
        .event_i(markov_lo_fail_pulse),
        .step_i(32'd1),
        .value_o(markov_lo_total_fails),
        .err_o(markov_lo_fails_cntr_err)
    );

    // Alert summary counter - counts windows with any failure
    entropy_src_cntr_reg #(.RegWidth(16))
        u_entropy_src_cntr_reg_any_alert_fails (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(alert_cntrs_clr),  // Clears after passing window
        .event_i(any_fail_pulse),
        .step_i(16'd1),
        .value_o(any_fail_count),
        .err_o(any_fails_cntr_err)
    );

    // Repetition test alert counter
    entropy_src_cntr_reg #(.RegWidth(4))
        u_entropy_src_cntr_reg_repcnt_alert (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(alert_cntrs_clr),
        .event_i(repcnt_fail_pulse),
        .step_i(4'd1),
        .value_o(repcnt_fail_count),
        .err_o(repcnt_alert_cntr_err)
    );

    // APT high alert counter
    entropy_src_cntr_reg #(.RegWidth(4))
        u_entropy_src_cntr_reg_apt_hi_alert (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(alert_cntrs_clr),
        .event_i(apt_hi_fail_pulse),
        .step_i(4'd1),
        .value_o(apt_hi_fail_count),
        .err_o(apt_hi_alert_cntr_err)
    );

    // APT low alert counter
    entropy_src_cntr_reg #(.RegWidth(4))
        u_entropy_src_cntr_reg_apt_lo_alert (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(alert_cntrs_clr),
        .event_i(apt_lo_fail_pulse),
        .step_i(4'd1),
        .value_o(apt_lo_fail_count),
        .err_o(apt_lo_alert_cntr_err)
    );

    // Markov high alert counter
    entropy_src_cntr_reg #(.RegWidth(4))
        u_entropy_src_cntr_reg_markov_hi_alert (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(alert_cntrs_clr),
        .event_i(markov_hi_fail_pulse),
        .step_i(4'd1),
        .value_o(markov_hi_fail_count),
        .err_o(markov_hi_alert_cntr_err)
    );

    // Markov low alert counter
    entropy_src_cntr_reg #(.RegWidth(4))
        u_entropy_src_cntr_reg_markov_lo_alert (
        .clk_i(clk_i),
        .rst_ni(rst_n),
        .clear_i(alert_cntrs_clr),
        .event_i(markov_lo_fail_pulse),
        .step_i(4'd1),
        .value_o(markov_lo_fail_count),
        .err_o(markov_lo_alert_cntr_err)
    );

    // Watermark register connections
    assign reg_in.HT_WATERMARK.WATERMARK_VALUE.next = ht_watermark;

    // Total fail counters
    assign reg_in.REPCNT_TOTAL_FAILS.FAIL_COUNT.next = repcnt_total_fails;
    assign reg_in.APT_HI_TOTAL_FAILS.FAIL_COUNT.next = apt_hi_total_fails;
    assign reg_in.APT_LO_TOTAL_FAILS.FAIL_COUNT.next = apt_lo_total_fails;
    assign reg_in.MARKOV_HI_TOTAL_FAILS.FAIL_COUNT.next = markov_hi_total_fails;
    assign reg_in.MARKOV_LO_TOTAL_FAILS.FAIL_COUNT.next = markov_lo_total_fails;

    // Alert summary
    assign reg_in.ALERT_SUMMARY_FAIL_COUNTS.ANY_FAIL_COUNT.next = any_fail_count;

    // Alert per-test counters (packed into single register)
    assign reg_in.ALERT_FAIL_COUNTS.REPCNT_FAIL_COUNT.next = repcnt_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.APT_HI_FAIL_COUNT.next = apt_hi_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.APT_LO_FAIL_COUNT.next = apt_lo_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.MARKOV_HI_FAIL_COUNT.next = markov_hi_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.MARKOV_LO_FAIL_COUNT.next = markov_lo_fail_count;

    // TODO: Connect es_cntr_err to error reporting (ERR_CODE register or alert system)

endmodule
