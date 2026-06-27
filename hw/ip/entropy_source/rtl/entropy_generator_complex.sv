// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//------------------------------------------------------------------------------
// Entropy Generator Complex
//
// Description:
// Combine all entropy noise sources with decorrelators using the
// using Barak-Impagliazzo-Wigderson (BIW) extractor which is
// simply a multiply-adder in GF(2^8) i.e. y=a*b+c
//------------------------------------------------------------------------------

module entropy_generator_complex #(
    parameter int unsigned NRINGS       = 12,
    parameter int unsigned CLKDIV_WIDTH = 24
) (
    input  logic                    clk_i,
    input  logic                    rst_ni,
    input  logic                    sample_clk_i,
    output logic [31:0]             entropy_stream_o,              // to collection FIFO and debug monitor
    output logic [NRINGS-1:0][7:0]  entropy_stream_uncompressed_o, // to collection FIFO and debug monitor
    output logic                    entropy_stream_valid_o,        // to collection FIFO
    output logic [NRINGS-1:0]       noise_bit_monitor_o,           // to debug monitor
    output logic [NRINGS-1:0]       sample_clk_monitor_o,          // to debug monitor

    // health test status vector for each invidual noise generator
    output logic [7:0]              generator_0_test_status_o,
    output logic [7:0]              generator_1_test_status_o,
    output logic [7:0]              generator_2_test_status_o,
    output logic [7:0]              generator_3_test_status_o,
    output logic [7:0]              generator_4_test_status_o,
    output logic [7:0]              generator_5_test_status_o,
    output logic [7:0]              generator_6_test_status_o,
    output logic [7:0]              generator_7_test_status_o,
    output logic [7:0]              generator_8_test_status_o,
    output logic [7:0]              generator_9_test_status_o,
    output logic [7:0]              generator_10_test_status_o,
    output logic [7:0]              generator_11_test_status_o,

    // from programmable configuration registers
    input  logic [NRINGS-1:0]       jitter_ro_enable_i,
    input  logic [NRINGS-1:0]       jitter_ro_detune_i,
    input  logic [NRINGS-1:0]       jitter_ro_auto_tune_enable_i,

    input  logic [NRINGS-1:0]       sample_clk_select_i,
    input  logic [NRINGS-1:0]       sample_clk_ro_detune_i,
    input  logic [NRINGS-1:0]       sample_clk_enable_i,
    input  logic [NRINGS-1:0][4:0]  sample_clk_divide_i, // Per-generator clock division: 0=÷1, 1=÷2, 2=÷4, 3=÷8, 4=÷16, 5=÷32

    input  logic [NRINGS-1:0]       decorrelator_bypass_i,
    input  logic [CLKDIV_WIDTH-1:0] decorrelator_sample_clk_div_i,
    input  logic [7:0]              decorrelator_entropy_byte_mask_i,

    input  logic [7:0]              health_test_enable_i,
    input  logic [7:0]              health_test_repetition_limit_i,
    input  logic [15:0]             health_test_proportion_limit_1bit_i,
    input  logic [15:0]             health_test_proportion_limit_lo_i,
    input  logic [9:0]              health_test_proportion_limit_2bit_i,
    input  logic [9:0]              health_test_proportion_limit_3bit_i,
    input  logic [9:0]              health_test_proportion_limit_4bit_i,
    input  logic [15:0]             health_test_markov_prob_01_threshold_i,
    input  logic [15:0]             health_test_markov_prob_10_threshold_i,
    input  logic [15:0]             health_test_window_size_i,  // Window size for health tests (default 2048)

    // Window wrap pulse for external health tests
    output logic                    window_wrap_pulse_o
);
/*
    // The jittery ring oscillator lengths are primes beginning at 13.
    // They are sampled with another set of ring oscillators also having
    // prime lengths which are an approximate 10x multiple of these periods
    // or 9x multiple if detuned.
    localparam int unsigned TOTALlength_0  = 13, TOTALlength_1  = 17,
                            TOTALlength_2  = 19, TOTALlength_3  = 23,
                            TOTALlength_4  = 29, TOTALlength_5  = 31,
                            TOTALlength_6  = 37, TOTALlength_7  = 41,
                            TOTALlength_8  = 43, TOTALlength_9  = 47,
                            TOTALlength_10 = 53, TOTALlength_11 = 59;

    // The detuned ring oscillator lengths are shorter values
    // which are not exclusively prime.
    localparam int unsigned TAPPEDlength_0  = 7,  TAPPEDlength_1  = 9,
                            TAPPEDlength_2  = 11, TAPPEDlength_3  = 19,
                            TAPPEDlength_4  = 24, TAPPEDlength_5  = 25,
                            TAPPEDlength_6  = 31, TAPPEDlength_7  = 33,
                            TAPPEDlength_8  = 36, TAPPEDlength_9  = 39,
                            TAPPEDlength_10 = 45, TAPPEDlength_11 = 49;
*/
    // The jittery ring oscillator lengths are sampled with another set of 
    // oscillators. Sampling ratio is approximately 10-20x with default configuration
    localparam int unsigned TOTALlength_0  = 5 , TOTALlength_1  = 7,
                            TOTALlength_2  = 11, TOTALlength_3  = 13,
                            TOTALlength_4  = 17, TOTALlength_5  = 19,
                            TOTALlength_6  = 6 , TOTALlength_7  = 8,
                            TOTALlength_8  = 12, TOTALlength_9  = 15,
                            TOTALlength_10 = 18, TOTALlength_11 = 23;

    // The detuned ring oscillator lengths are shorter values increasing frequency
    localparam int unsigned TAPPEDlength_0  = 3,  TAPPEDlength_1  = 5,
                            TAPPEDlength_2  = 9,  TAPPEDlength_3  = 10,
                            TAPPEDlength_4  = 14, TAPPEDlength_5  = 16,
                            TAPPEDlength_6  = 4,  TAPPEDlength_7  = 7,
                            TAPPEDlength_8  = 11, TAPPEDlength_9  = 13,
                            TAPPEDlength_10 = 15, TAPPEDlength_11 = 21;

    
    function automatic int get_total_length(input int idx);
        case (idx)
            0:  get_total_length = TOTALlength_0;   1:  get_total_length = TOTALlength_1;
            2:  get_total_length = TOTALlength_2;   3:  get_total_length = TOTALlength_3;
            4:  get_total_length = TOTALlength_4;   5:  get_total_length = TOTALlength_5;
            6:  get_total_length = TOTALlength_6;   7:  get_total_length = TOTALlength_7;
            8:  get_total_length = TOTALlength_8;   9:  get_total_length = TOTALlength_9;
            10: get_total_length = TOTALlength_10;  11: get_total_length = TOTALlength_11;
            default: get_total_length = 29;
        endcase
    endfunction

    function automatic int get_tapped_length(input int idx);
        case (idx)
            0:  get_tapped_length = TAPPEDlength_0;   1:  get_tapped_length = TAPPEDlength_1;
            2:  get_tapped_length = TAPPEDlength_2;   3:  get_tapped_length = TAPPEDlength_3;
            4:  get_tapped_length = TAPPEDlength_4;   5:  get_tapped_length = TAPPEDlength_5;
            6:  get_tapped_length = TAPPEDlength_6;   7:  get_tapped_length = TAPPEDlength_7;
            8:  get_tapped_length = TAPPEDlength_8;   9:  get_tapped_length = TAPPEDlength_9;
            10: get_tapped_length = TAPPEDlength_10;  11: get_tapped_length = TAPPEDlength_11;
            default: get_tapped_length = 19;
        endcase
    endfunction

    logic [NRINGS-1:0]      entropy_byte_valid;
    logic [NRINGS-1:0][7:0] decorrelator_entropy_bytes;
    logic [NRINGS-1:0]      sample_clk;

    assign entropy_stream_uncompressed_o = decorrelator_entropy_bytes;
    assign sample_clk_monitor_o          = sample_clk;

    entropy_sampler_clocks #(
        .NRINGS              (NRINGS)
    ) sclk (
        .clk_i,
        .rst_ni,
        .sample_clk_i        (sample_clk_i),
        .enable_i            (sample_clk_enable_i),
        .detune_ro_i         (sample_clk_ro_detune_i),
        .sample_clk_select_i (sample_clk_select_i),
        .sample_clk_divide_i (sample_clk_divide_i), // Per-generator clock division
        .sample_clk_o        (sample_clk)
    );

    logic [7:0] test_status [NRINGS];
    assign generator_0_test_status_o  = test_status[0];
    assign generator_1_test_status_o  = test_status[1];
    assign generator_2_test_status_o  = test_status[2];
    assign generator_3_test_status_o  = test_status[3];
    assign generator_4_test_status_o  = test_status[4];
    assign generator_5_test_status_o  = test_status[5];
    assign generator_6_test_status_o  = test_status[6];
    assign generator_7_test_status_o  = test_status[7];
    assign generator_8_test_status_o  = test_status[8];
    assign generator_9_test_status_o  = test_status[9];
    assign generator_10_test_status_o = test_status[10];
    assign generator_11_test_status_o = test_status[11];

    // Window counter for health test synchronization (OpenTitan pattern)
    logic [15:0] window_cntr;
    logic        window_cntr_err;
    logic        window_wrap_pulse;
    logic        health_test_enable;

    assign health_test_enable = |health_test_enable_i; // Any test enabled
    assign window_wrap_pulse  = (window_cntr >= health_test_window_size_i);
    assign window_wrap_pulse_o = window_wrap_pulse;  // Export for external health tests

    prim_count #(
        .Width      (16)
    ) u_window_cntr (
        .clk_i      (clk_i),
        .rst_ni     (rst_ni),
        .clr_i      (~health_test_enable),          // Clear when disabled
        .set_i      (window_wrap_pulse),            // Reset on window wrap
        .set_cnt_i  (16'h0),                        // Reset to 0
        .incr_en_i  (|entropy_byte_valid),          // Increment when any generator valid
        .decr_en_i  (1'b0),                         // Never decrement
        .step_i     (16'd1),                        // Increment by 1
        .commit_i   (1'b1),                         // Always commit immediately
        .cnt_o      (window_cntr),                  // Counter output
        .cnt_after_commit_o (),                     // Unused
        .err_o      (window_cntr_err)               // Counter error (overflow)
    );

    // each entropy generator is a noise source followed by a serial decorrelator
    generate
        for (genvar i = 0; i < NRINGS; i++) begin : g_ecmplx
            entropy_generator #(
                .TOTAL_LENGTH               (get_total_length (i)),
                .TAPPED_LENGTH              (get_tapped_length(i)),
                .CLKDIV_WIDTH               (CLKDIV_WIDTH)
            ) gen_inst (
                .clk_i,
                .rst_ni,
                .enable_i                   (jitter_ro_enable_i          [i]),
                .auto_tune_enable_i         (jitter_ro_auto_tune_enable_i[i]),
                .detune_ro_i                (jitter_ro_detune_i          [i]),
                .sample_clk_i               (sample_clk                  [i]), // Already divided by entropy_sampler_clocks
                .sample_clk_div_i           (decorrelator_sample_clk_div_i),
                .bypass_decorrelator_i      (decorrelator_bypass_i       [i]),
                .entropy_byte_mask_i        (decorrelator_entropy_byte_mask_i),
                // health tester configurations
                .test_enable_i              (health_test_enable_i),
                .repetition_limit_i         (health_test_repetition_limit_i),
                .proportion_limit_1bit_i    (health_test_proportion_limit_1bit_i),
                .proportion_limit_lo_i      (health_test_proportion_limit_lo_i),
                .proportion_limit_2bit_i    (health_test_proportion_limit_2bit_i),
                .proportion_limit_3bit_i    (health_test_proportion_limit_3bit_i),
                .proportion_limit_4bit_i    (health_test_proportion_limit_4bit_i),
                .markov_prob_01_threshold_i (health_test_markov_prob_01_threshold_i),
                .markov_prob_10_threshold_i (health_test_markov_prob_10_threshold_i),
                .window_wrap_pulse_i        (window_wrap_pulse),
                .noise_bit_monitor_o        (noise_bit_monitor_o         [i]),
                .test_status_o              (test_status                 [i]),
                .entropy_byte_o             (decorrelator_entropy_bytes  [i]),
                .entropy_byte_valid_o       (entropy_byte_valid          [i])
            );
        end
    endgenerate

    // BIW extractor combines 12 entropy byte streams into 4 byte streams
    logic [7:0] biw_entropy [4];

    generate
        for (genvar i = 0; i < 4; i++) begin : g_biw
            gf_muladd muladd (
                .a (decorrelator_entropy_bytes[i]),
                .b (decorrelator_entropy_bytes[i+4]),
                .c (decorrelator_entropy_bytes[i+8]),
                .y (biw_entropy               [i])
            );
        end
    endgenerate

    // Pack BIW bytes into 32-bit word
    // Output BIW data directly - SHA-256 whitener is instantiated in entropy_source.sv
    // after the 32-bit health test, so health test monitors pre-whitened entropy
    logic [31:0] biw_data;
    logic        biw_valid;
    assign biw_data  = {biw_entropy[0], biw_entropy[1], biw_entropy[2], biw_entropy[3]};
    assign biw_valid = |entropy_byte_valid;

    // Final output: BIW stream (pre-whitened)
    assign entropy_stream_o       = biw_data;
    assign entropy_stream_valid_o = biw_valid;

endmodule
