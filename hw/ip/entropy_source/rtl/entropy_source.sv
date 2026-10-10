// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Generate conditioned entropy from a ring-oscillator array with health tests and AXI-Lite control.
//
// A 12-lane array of ring oscillators of differing lengths, with metastable sampling,
// feeds a GF(2^8) extractor whose 32-bit stream runs online Repetition, Adaptive
// Proportion, and Markov health tests and an optional SHA-256 whitener.
// rosc_sample_clk_i is the external sample clock.
//
// Interfaces:
//
// - The AXI-Lite slave carries register-based configuration and data access.
// - signal_monitor_o observes intermediate signals.
// - irq_o aggregates sticky fault and health status for the SEP host.
//
// Boot-time validation uses the main_sm gate: entropy reaches the whitener, the main FIFO
// and the extracted-stream observe FIFO only after CTRL.MODULE_ENABLE is set and a boot
// health-test window passes, and new entropy stops entering when MODULE_ENABLE clears or
// the alert threshold trips.

module entropy_source
    import entropy_source_pkg::NRings;
    import entropy_source_pkg::entropy_source_err_bus_t;
    import entropy_src_main_sm_pkg::StateWidth;

    `include "prim_assert.sv"
(
    input       logic        clk_i,     // System clock.
    input       logic        rst_ni,    // Active-low asynchronous reset.

    input       logic        s_axil_awvalid_i,  // AXI-Lite write-address valid.
    output      logic        s_axil_awready_o,  // AXI-Lite write-address ready.
    input       logic [8:0]  s_axil_awaddr_i,  // AXI-Lite write byte address within the register
                                               // map.
    input       logic [2:0]  s_axil_awprot_i,  // AXI-Lite write protection attributes.

    input       logic        s_axil_wvalid_i,  // AXI-Lite write-data valid.
    output      logic        s_axil_wready_o,  // AXI-Lite write-data ready.
    input       logic [31:0] s_axil_wdata_i,  // AXI-Lite write data.
    input       logic [3:0]  s_axil_wstrb_i,  // AXI-Lite write byte strobes.

    output      logic        s_axil_bvalid_o,  // AXI-Lite write-response valid.
    input       logic        s_axil_bready_i,  // AXI-Lite write-response ready.
    output      logic [1:0]  s_axil_bresp_o,  // AXI-Lite write response code.

    input       logic        s_axil_arvalid_i,  // AXI-Lite read-address valid.
    output      logic        s_axil_arready_o,  // AXI-Lite read-address ready.
    input       logic [8:0]  s_axil_araddr_i,  // AXI-Lite read byte address within the register
                                               // map.
    input       logic [2:0]  s_axil_arprot_i,  // AXI-Lite read protection attributes.

    output      logic        s_axil_rvalid_o,  // AXI-Lite read-data valid.
    input       logic        s_axil_rready_i,  // AXI-Lite read-data ready.
    output      logic [31:0] s_axil_rdata_o,  // AXI-Lite read data.
    output      logic [1:0]  s_axil_rresp_o,  // AXI-Lite read response code.

    output      logic        signal_monitor_o,  // Debug observe signal chosen and divided by
                                                // DEBUG_CTRL.
    input       logic        rosc_sample_clk_i,  // External ring-oscillator sample clock,
                                                 // asynchronous to clk_i.

    output      logic [31:0] entropy_stream_data_o,  // Word offered to the main entropy FIFO:
                                                     // whitener output, which is the extracted
                                                     // stream itself while whitening is disabled,
                                                     // or packed lane bytes when the compressor is
                                                     // bypassed.
    output      logic        entropy_stream_vld_o,  // Qualifies entropy_stream_data_o; independent
                                                    // of FIFO_CTRL.ENABLE.
    output      logic        irq_o      // Level interrupt: OR of the INTR_STATUS sticky bits masked
                                        // by INTR_ENABLE.
);

    /////////////
    // Signals
    /////////////

    entropy_source_reg_pkg::entropy_source__in_t  reg_in;
    entropy_source_reg_pkg::entropy_source__out_t reg_out;

    logic [31:0]            entropy_stream;
    logic [NRings-1:0][7:0] entropy_stream_uncompressed;
    logic                   entropy_stream_valid;
    logic                   entropy_stream_valid_gated;
    logic [NRings-1:0]      noise_bit_monitor;
    logic [NRings-1:0]      sample_clk_monitor;
    logic [7:0]             health_status;
    logic                   window_wrap_pulse;

    logic [7:0] generator_0_test_status,  generator_1_test_status;
    logic [7:0] generator_2_test_status,  generator_3_test_status;
    logic [7:0] generator_4_test_status,  generator_5_test_status;
    logic [7:0] generator_6_test_status,  generator_7_test_status;
    logic [7:0] generator_8_test_status,  generator_9_test_status;
    logic [7:0] generator_10_test_status, generator_11_test_status;

    logic [15:0] ctr_repetition;
    logic [15:0] apt_pattern_count_1bit,  apt_pattern_count_2bit;
    logic [15:0] count_01, count_10;

    logic        fifo_push;
    logic [31:0] fifo_wdata, fifo_rdata;
    logic [6:0]  fifo_level;
    /* verilator lint_off UNUSEDSIGNAL */
    logic [5:0]  fifo_wptr, fifo_rptr;
    /* verilator lint_on UNUSEDSIGNAL */
    logic        fifo_error;
    logic        fifo_overflow, fifo_underflow;
    /* verilator lint_off UNUSEDSIGNAL */
    logic        open_parity_error, open_pointer_error;
    /* verilator lint_on UNUSEDSIGNAL */

    logic [31:0] whitened_data;
    logic        whitened_valid;

    logic        health_test_clk;
    logic        health_test_enable;
    logic        health_test_valid_gated;

    logic        ht_fail_pulse;
    logic        boot_phase_done;
    logic        alert_cntr_clr_ok_main_sm;
    logic        main_sm_alert, main_sm_idle, main_sm_err;
    logic [StateWidth-1:0] main_sm_state;

    logic [9:0]  downsample_count;
    logic        fifo_stream_push;

    typedef enum logic {
        ST_FIFO_PUSH_IDLE = 1'd0,
        ST_FIFO_PUSH      = 1'd1
    } fifo_push_fsm_state_e;

    logic [NRings-1:0][7:0] fifo_push_stream,     fifo_push_stream_next;
    logic [1:0]             fifo_push_count,      fifo_push_count_next;
    fifo_push_fsm_state_e   fifo_push_state,      fifo_push_state_next;

    // Watermark / fail counters
    typedef enum logic [3:0] {
        REPCNT_HI = 4'h0,
        APT_HI    = 4'h1,
        APT_LO    = 4'h2,
        MARKOV_HI = 4'h3,
        MARKOV_LO = 4'h4
    } watermark_test_e;

    watermark_test_e ht_watermark_num_q,      ht_watermark_num_d;
    watermark_test_e ht_watermark_num_reg_if;
    logic            ht_watermark_high;
    logic            ht_watermark_event_pre;
    logic            ht_watermark_event;
    logic [15:0]     ht_watermark_cnt;
    logic [15:0]     ht_watermark;

    logic [15:0] repcnt_event_cnt;
    logic [15:0] apt_hi_event_cnt,    apt_lo_event_cnt;
    logic [15:0] markov_hi_event_cnt, markov_lo_event_cnt;

    logic health_test_clr;
    logic alert_cntrs_clr;
    logic module_en_q;
    logic module_en_pulse;
    logic alert_cntr_clr_ok;

    logic repcnt_fail_pulse;
    logic apt_hi_fail_pulse,    apt_lo_fail_pulse;
    logic markov_hi_fail_pulse, markov_lo_fail_pulse;

    logic [31:0] repcnt_total_fails;
    logic [31:0] apt_hi_total_fails,    apt_lo_total_fails;
    logic [31:0] markov_hi_total_fails, markov_lo_total_fails;
    logic [15:0] any_fail_count;

    logic [3:0] repcnt_fail_count;
    logic [3:0] apt_hi_fail_count,    apt_lo_fail_count;
    logic [3:0] markov_hi_fail_count, markov_lo_fail_count;

    logic repcnt_fails_cntr_err;
    logic apt_hi_fails_cntr_err,    apt_lo_fails_cntr_err;
    logic markov_hi_fails_cntr_err, markov_lo_fails_cntr_err;
    logic any_fails_cntr_err;
    logic repcnt_alert_cntr_err;
    logic apt_hi_alert_cntr_err,    apt_lo_alert_cntr_err;
    logic markov_hi_alert_cntr_err, markov_lo_alert_cntr_err;
    logic es_cntr_err;
    logic generator_complex_cntr_err;
    logic health_test_cntr_err;

    // FIPS configuration lock: asserted once FIPS_LOCK.LOCK is written,
    // cleared only by reset. Drives swwel on every certified-config field.
    logic fips_lock;

    // Persistent-halt / error aggregation.
    logic        alert_thresh_fail;
    logic        persistent_failure;
    logic        autotune_fail;
    entropy_source_err_bus_t err_bus;

    // SP 800-90B recommended-threshold LUT outputs (combinational).
    logic [7:0]  min_entropy_h;
    logic [15:0] rec_rct_limit;
    logic [15:0] rec_apt_limit;

    // per-window sticky health-test-fail latch for the boot gate.
    logic ht_fail_sticky_q;

    // Post-BIW extracted-stream diagnostic observe FIFO (post-BIW, pre-SHA
    // copy-only tap). NOT the SP 800-90B raw source; see the raw per-lane
    // NOISE_OBS tap further below.
    logic        biw_obs_push, biw_obs_pop;
    logic [31:0] biw_obs_rdata;
    logic [6:0]  biw_obs_level;
    logic        biw_obs_overflow;  // drives INTR_STATUS.BIW_OBS_OVERFLOW
    /* verilator lint_off UNUSEDSIGNAL */
    logic [5:0]  biw_obs_wptr, biw_obs_rptr;
    logic        biw_obs_underflow;
    logic        biw_obs_parity_error, biw_obs_pointer_error, biw_obs_security_alert;
    /* verilator lint_on UNUSEDSIGNAL */

    // GetNoise raw per-lane observe FIFO (pre-decorrelator, packed copy-only
    // tap). This is the SP 800-90B raw noise source.
    logic        noise_obs_push, noise_obs_pop;
    logic [31:0] noise_obs_rdata;
    logic [6:0]  noise_obs_level;
    logic        noise_obs_overflow;  // drives INTR_STATUS.NOISE_OBS_OVERFLOW
    logic        noise_obs_flush;     // auto-flush on lane change + SW FLUSH strobe
    /* verilator lint_off UNUSEDSIGNAL */
    logic [5:0]  noise_obs_wptr, noise_obs_rptr;
    logic        noise_obs_underflow;
    logic        noise_obs_parity_error, noise_obs_pointer_error, noise_obs_security_alert;
    /* verilator lint_on UNUSEDSIGNAL */

    // Raw per-lane tap datapath: lane mux, sample-clock edge detector, packer.
    // 16-wide zero-padded views of the 12-lane monitors so a 4-bit LANE_SEL
    // (0-15) can index them without an out-of-range select.
    logic [15:0]             noise_bit_monitor_ext;
    logic [15:0]             sample_clk_monitor_ext;
    logic                    noise_obs_raw_bit;
    logic                    noise_obs_raw_sclk;
    logic [1:0]              noise_obs_sclk_sync;
    logic                    noise_obs_sample_stb;
    logic [31:0]             noise_obs_shift_q,  noise_obs_shift_d;
    logic [4:0]              noise_obs_bit_cnt_q, noise_obs_bit_cnt_d;
    logic [3:0]              noise_obs_lane_sel_eff;
    logic [3:0]              noise_obs_lane_sel_q;
    logic                    noise_obs_word_push;

    /////////////////
    // Combinational
    /////////////////

    // Expose each word pushed into the main FIFO for external monitoring
    assign entropy_stream_data_o = fifo_wdata;
    assign entropy_stream_vld_o  = fifo_push;

    assign entropy_stream_valid_gated = boot_phase_done && entropy_stream_valid;

    /////////////////
    // Sub-instances
    /////////////////

    entropy_generator_complex #(
        .NRINGS       (NRings),
        .CLKDIV_WIDTH (20)
    ) u_generator_complex (
        .clk_i,
        .rst_ni                                 (rst_ni),
        .sample_clk_i                           (rosc_sample_clk_i),
        .entropy_stream_o                       (entropy_stream),
        .entropy_stream_uncompressed_o          (entropy_stream_uncompressed),
        .entropy_stream_valid_o                 (entropy_stream_valid),
        .noise_bit_monitor_o                    (noise_bit_monitor),
        .sample_clk_monitor_o                   (sample_clk_monitor),

        .jitter_ro_enable_i                     (reg_out.RING_OSC_ENABLE.ENABLE.value),
        .jitter_ro_detune_i                     (reg_out.RING_OSC_TUNE.DETUNE.value),
        .jitter_ro_auto_tune_enable_i           ({NRings{reg_out.CTRL.AUTOTUNE_ENABLE.value}}),

        .sample_clk_select_i                    (reg_out.RING_OSC_CTRL.SAMPLE_CLK_SELECT.value),
        .sample_clk_ro_detune_i                 (reg_out.RING_OSC_TUNE.SAMPLE_CLK_DETUNE.value),
        .sample_clk_enable_i                    (reg_out.RING_OSC_ENABLE.SAMPLE_CLK_ENABLE.value),
        .sample_clk_divide_i ({
            reg_out.GENERATOR_11_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value,
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
            reg_out.GENERATOR_0_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.value
        }),

        .decorrelator_bypass_i                  (reg_out.DECORRELATOR_CTRL.BYPASS.value),
        .decorrelator_sample_clk_div_i          (reg_out.DECORRELATOR_CTRL.SAMPLE_CLK_DIV.value),
        .decorrelator_entropy_byte_mask_i       (reg_out.DECORRELATOR_MASK.ENTROPY_BYTE_MASK.value),

        .module_enable_i                        (reg_out.CTRL.MODULE_ENABLE.value),
        .health_test_enable_i                   (reg_out.HEALTH_TEST_CTRL.ENABLE.value),
        .health_test_repetition_limit_i         (reg_out.HEALTH_TEST_CTRL.REPETITION_LIMIT.value),
        .health_test_proportion_limit_1bit_i    (reg_out.APT_PROPORTION_1BIT.LIMIT.value),
        .health_test_proportion_limit_lo_i      (reg_out.APT_PROPORTION_LO.LIMIT.value),
        .health_test_markov_prob_01_threshold_i (
            reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_01_THRESHOLD.value),
        .health_test_markov_prob_10_threshold_i (
            reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_10_THRESHOLD.value),
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

        // Per-lane and window-counter self-check error, folded into es_cntr_err
        .count_err_o                            (generator_complex_cntr_err),

        // Window wrap pulse output
        .window_wrap_pulse_o                    (window_wrap_pulse)
    );

    entropy_debug_monitor #(
        .NSIGNALS          (256)
    ) u_debug_monitor (
        .rst_ni            (rst_ni),
        .select_signal_i   (reg_out.DEBUG_CTRL.SELECT_SIGNAL.value),
        .signal_i          ({32'h0, entropy_stream_uncompressed, 32'h0, whitened_data,
                             entropy_stream, 4'h0, sample_clk_monitor, 4'h0, noise_bit_monitor}),
        .select_freq_div_i (reg_out.DEBUG_CTRL.SELECT_FREQ_DIV.value),
        .sig_monitor_o     (signal_monitor_o)
    );

    // ----------------------------------------------------------------------
    // health-test tap point.
    //
    // The gating health test (u_health_test) runs on entropy_stream, the
    // post-BIW 32-bit digitised stream. The BIW extractor is noise-source
    // digitisation, so this tap is before conditioning (before SHA-256) as
    // required by SP 800-90B 4.3 req 6, and the post-BIW HT is authoritative
    // for the boot/output gate. Per-lane results (generator_N_test_status) are
    // exposed via GENERATOR_*_HEALTH_STATUS as monitor-only status.
    // ----------------------------------------------------------------------

    // Clock gating for 32-bit health test: disabled when BIW compressor is bypassed.
    assign health_test_enable      = ~reg_out.CTRL.BYPASS_ENTROPY_COMPRESSOR.value;
    assign health_test_valid_gated = entropy_stream_valid & health_test_enable;

    prim_clock_gating u_health_test_clk_gate (
        .clk_i  (clk_i),
        .en_i   (health_test_enable),
        .test_en_i (1'b0),
        .clk_o  (health_test_clk)
    );

    entropy_health_test #(
        .DATA_WIDTH                   (32)
    ) u_health_test (
        .clk_i                        (health_test_clk),
        .rst_ni                       (rst_ni),
        .entropy_i                    (entropy_stream),
        .entropy_valid_i              (health_test_valid_gated),
        .enable_i                     (reg_out.HEALTH_TEST_CTRL.ENABLE.value),
        .repetition_limit_i           (reg_out.HEALTH_TEST_CTRL.REPETITION_LIMIT.value),
        .proportion_limit_1bit_i      (reg_out.APT_PROPORTION_1BIT.LIMIT.value),
        .proportion_limit_lo_i        (reg_out.APT_PROPORTION_LO.LIMIT.value),
        // Markov test thresholds
        .markov_prob_01_threshold_i   (reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_01_THRESHOLD.value),
        .markov_prob_10_threshold_i   (reg_out.MARKOV_TEST_PROB_THRESHOLDS.PROB_10_THRESHOLD.value),
        .window_wrap_pulse_i          (window_wrap_pulse),
        .ctr_repetition_o             (ctr_repetition),
        .apt_pattern_count_1bit_o     (apt_pattern_count_1bit),
        .apt_pattern_count_2bit_o     (apt_pattern_count_2bit),
        .count_01_o                   (count_01),
        .count_10_o                   (count_10),
        .apt_fail_hi_o                (apt_hi_fail_pulse),
        .apt_fail_lo_o                (apt_lo_fail_pulse),
        .status_o                     (health_status),
        .count_err_o                  (health_test_cntr_err)
    );

    entropy_sha256_whitener u_sha256_whitener (
        .clk_i               (clk_i),
        .rst_ni              (rst_ni),
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
        .DEPTH (64)
    ) u_entropy_fifo (
        .clk_i,
        .rst_ni                 (rst_ni),
        .push_i                 (reg_out.FIFO_CTRL.ENABLE.value && fifo_push),
        .pop_i                  (reg_out.FIFO_RDATA.req && !reg_out.FIFO_RDATA.req_is_wr),
        .clr_i                  (1'b0),  // Main datapath FIFO is never flushed.
        .wdata_i                (fifo_wdata),
        .entropy_churn_enable_i (reg_out.FIFO_CTRL.ENTROPY_CHURN_ENABLE.value),
        .rdata_o                (fifo_rdata),
        .level_o                (fifo_level),
        .wptr_o                 (fifo_wptr),
        .rptr_o                 (fifo_rptr),
        .overflow_o             (fifo_overflow),
        .underflow_o            (fifo_underflow),
        .parity_error_o         (open_parity_error),
        .pointer_error_o        (open_pointer_error),
        .security_alert_o       (fifo_error)
    );

    // ----------------------------------------------------------------------
    // BIW post-extraction diagnostic observe FIFO.
    //
    // Copy-only fan-out of the post-BIW, pre-SHA entropy stream. The write
    // enable is a pure copy of the same (entropy_stream, entropy_stream_valid)
    // that feeds the SHA-256 whitener: the observe FIFO taps that pair without
    // introducing any mux or backpressure into the BIW->SHA main path, which
    // satisfies the SP 800-90B 3.2.1-5c "shall not feed conditioning" isolation
    // requirement. Gated by BIW_OBS_CTRL.RAW_ENABLE AND boot_phase_done.
    //
    // NOTE: entropy_stream is the EXTRACTED (conditioned) stream, downstream of
    // the decorrelators and the BIW GF(2^8) extractor. This tap is a
    // diagnostic / health-monitor observation point, NOT the SP 800-90B raw
    // noise source. The raw per-lane source is the NOISE_OBS tap below, which
    // observes the pre-decorrelator metastable samples.
    //
    // Churn is held off (the observe path must be the unmodified stream). If
    // the FIFO is full the sample is simply not pushed — a dropped observe
    // sample never stalls the main datapath.
    // ----------------------------------------------------------------------
    assign biw_obs_push = reg_out.BIW_OBS_CTRL.RAW_ENABLE.value
                          && boot_phase_done
                          && entropy_stream_valid;
    assign biw_obs_pop  = reg_out.BIW_OBS_RDATA.req && !reg_out.BIW_OBS_RDATA.req_is_wr;

    entropy_fifo #(
        .DEPTH (64)
    ) u_biw_obs_fifo (
        .clk_i,
        .rst_ni                 (rst_ni),
        .push_i                 (biw_obs_push),
        .pop_i                  (biw_obs_pop),
        .clr_i                  (1'b0),  // Diagnostic tap: no lane switch, no flush.
        .wdata_i                (entropy_stream),
        .entropy_churn_enable_i (1'b0),  // Observe path is the unmodified stream.
        .rdata_o                (biw_obs_rdata),
        .level_o                (biw_obs_level),
        .wptr_o                 (biw_obs_wptr),
        .rptr_o                 (biw_obs_rptr),
        .overflow_o             (biw_obs_overflow),
        .underflow_o            (biw_obs_underflow),
        .parity_error_o         (biw_obs_parity_error),
        .pointer_error_o        (biw_obs_pointer_error),
        .security_alert_o       (biw_obs_security_alert)
    );

    // BIW_OBS_STATUS feeds (mirrors FIFO_STATUS layout).
    assign reg_in.BIW_OBS_STATUS.LEVEL.next = biw_obs_level;
    assign reg_in.BIW_OBS_STATUS.WPTR.next  = biw_obs_wptr;
    assign reg_in.BIW_OBS_STATUS.RPTR.next  = biw_obs_rptr;

    // External auto-advancing read port (mirror of the FIFO_RDATA pattern):
    // reading BIW_OBS_RDATA pops one word. rd_ack is guarded with rst_ni so a
    // spurious ack cannot fire before the reg block initialises its out struct.
    assign reg_in.BIW_OBS_RDATA.rd_data.RDATA = biw_obs_rdata;
    assign reg_in.BIW_OBS_RDATA.rd_ack        =
        rst_ni && reg_out.BIW_OBS_RDATA.req && !reg_out.BIW_OBS_RDATA.req_is_wr;

    // ----------------------------------------------------------------------
    // GetNoise raw per-lane noise observe FIFO (SP 800-90B raw source).
    //
    // Selects one generator lane's PRE-decorrelator raw metastable sample
    // (noise_bit_monitor[LANE_SEL]) and captures exactly one bit per lane
    // sample-clock edge, packing 32 samples (LSB-first) into a word that is
    // pushed into a dedicated observe FIFO. Because noise_bit_monitor changes
    // only at the (slower) per-lane sample-clock rate, capture is paced by a
    // sample-clock edge detector — packing raw clk_i values would grossly
    // oversample the source and corrupt the min-entropy estimate.
    //
    // Copy-only: no mux/backpressure into the main datapath. Gated by
    // NOISE_OBS_CTRL.RAW_ENABLE only (NOT boot_phase_done) so raw samples can
    // be collected during startup to set health-test thresholds. Churn off; a
    // full FIFO simply drops the word (never stalls capture or the datapath).
    // ----------------------------------------------------------------------

    // Lane mux. LANE_SEL is 4 bits (0-15) but NRings==12. Clamp out-of-range
    // selects (>=12) to lane 0, matching the RDL contract. Zero-padding to 16
    // entries keeps the index within array bounds (no SELRANGE lint warning).
    assign noise_obs_lane_sel_eff =
        (reg_out.NOISE_OBS_CTRL.LANE_SEL.value >= 4'(NRings))
        ? 4'd0 : reg_out.NOISE_OBS_CTRL.LANE_SEL.value;
    assign noise_bit_monitor_ext  = {{(16 - NRings){1'b0}}, noise_bit_monitor};
    assign sample_clk_monitor_ext = {{(16 - NRings){1'b0}}, sample_clk_monitor};
    assign noise_obs_raw_bit  = noise_bit_monitor_ext [noise_obs_lane_sel_eff];
    assign noise_obs_raw_sclk = sample_clk_monitor_ext[noise_obs_lane_sel_eff];

    // Rising-edge strobe on the selected lane's sample clock: a fresh raw bit
    // is available once per rising edge of the (async, divided) sample clock.
    // noise_obs_sclk_sync is a 2-FF synchroniser of the async sample clock into
    // clk_i; the strobe is its rising-edge detect. noise_bit_monitor is held
    // stable across the whole slow sample period, so latching it on this strobe
    // captures exactly one valid raw sample per period (small clk_i phase skew
    // between the synced edge and the synced data bit is harmless).
    /* verilator lint_off UNUSEDSIGNAL */
    logic noise_obs_sclk_meta;  // metastable capture stage (intentional CDC)
    /* verilator lint_on UNUSEDSIGNAL */
    assign noise_obs_sample_stb = ~noise_obs_sclk_sync[1] & noise_obs_sclk_sync[0];

    // Packer next-state (bit_cnt counts packed bits 0..31; push at 31->wrap).
    assign noise_obs_word_push = reg_out.NOISE_OBS_CTRL.RAW_ENABLE.value
                                 && noise_obs_sample_stb
                                 && (noise_obs_bit_cnt_q == 5'd31);

    always_comb begin
        noise_obs_shift_d   = noise_obs_shift_q;
        noise_obs_bit_cnt_d = noise_obs_bit_cnt_q;

        if (!reg_out.NOISE_OBS_CTRL.RAW_ENABLE.value ||
            (noise_obs_lane_sel_eff != noise_obs_lane_sel_q)) begin
            // Disabled or lane switched: restart the packer so a word never
            // mixes samples from two lanes.
            noise_obs_shift_d   = 32'h0;
            noise_obs_bit_cnt_d = 5'd0;
        end else if (noise_obs_sample_stb) begin
            // Pack LSB-first: first sample of a word lands in bit 0.
            noise_obs_shift_d   = {noise_obs_raw_bit, noise_obs_shift_q[31:1]};
            noise_obs_bit_cnt_d = (noise_obs_bit_cnt_q == 5'd31)
                                  ? 5'd0
                                  : noise_obs_bit_cnt_q + 5'd1;
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            noise_obs_sclk_meta  <= 1'b0;
            noise_obs_sclk_sync  <= 2'b0;
            noise_obs_shift_q    <= 32'h0;
            noise_obs_bit_cnt_q  <= 5'd0;
            noise_obs_lane_sel_q <= 4'h0;
        end else begin
            // 2-FF CDC synchroniser for the async divided sample clock.
            noise_obs_sclk_meta <= noise_obs_raw_sclk;
            noise_obs_sclk_sync <= {noise_obs_sclk_sync[0], noise_obs_sclk_meta};
            noise_obs_shift_q    <= noise_obs_shift_d;
            noise_obs_bit_cnt_q  <= noise_obs_bit_cnt_d;
            noise_obs_lane_sel_q <= noise_obs_lane_sel_eff;
        end
    end

    assign noise_obs_push = noise_obs_word_push;
    assign noise_obs_pop  = reg_out.NOISE_OBS_RDATA.req && !reg_out.NOISE_OBS_RDATA.req_is_wr;

    // Flush the raw observe FIFO whenever the selected lane changes, so every
    // buffered word is guaranteed to belong to the current lane and LEVEL is
    // unambiguous (software never has to drain-and-discard stale-lane words
    // after a switch). The self-clearing NOISE_OBS_CTRL.FLUSH strobe also lets
    // software force a discard on demand. The packer already restarts on the
    // same lane-change edge (see above), so packer and FIFO stay consistent.
    assign noise_obs_flush =
        (noise_obs_lane_sel_eff != noise_obs_lane_sel_q)
        || reg_out.NOISE_OBS_CTRL.FLUSH.value;

    entropy_fifo #(
        .DEPTH (64)
    ) u_noise_obs_fifo (
        .clk_i,
        .rst_ni                 (rst_ni),
        .push_i                 (noise_obs_push),
        .pop_i                  (noise_obs_pop),
        .clr_i                  (noise_obs_flush),
        .wdata_i                (noise_obs_shift_q),
        .entropy_churn_enable_i (1'b0),  // Raw observe path is the unmodified stream.
        .rdata_o                (noise_obs_rdata),
        .level_o                (noise_obs_level),
        .wptr_o                 (noise_obs_wptr),
        .rptr_o                 (noise_obs_rptr),
        .overflow_o             (noise_obs_overflow),
        .underflow_o            (noise_obs_underflow),
        .parity_error_o         (noise_obs_parity_error),
        .pointer_error_o        (noise_obs_pointer_error),
        .security_alert_o       (noise_obs_security_alert)
    );

    // NOISE_OBS_STATUS feeds (mirrors FIFO_STATUS layout).
    assign reg_in.NOISE_OBS_STATUS.LEVEL.next = noise_obs_level;
    assign reg_in.NOISE_OBS_STATUS.WPTR.next  = noise_obs_wptr;
    assign reg_in.NOISE_OBS_STATUS.RPTR.next  = noise_obs_rptr;

    // External auto-advancing read port (mirror of the FIFO_RDATA pattern):
    // reading NOISE_OBS_RDATA pops one word. rd_ack is guarded with rst_ni so a
    // spurious ack cannot fire before the reg block initialises its out struct.
    assign reg_in.NOISE_OBS_RDATA.rd_data.RDATA = noise_obs_rdata;
    assign reg_in.NOISE_OBS_RDATA.rd_ack        =
        rst_ni && reg_out.NOISE_OBS_RDATA.req && !reg_out.NOISE_OBS_RDATA.req_is_wr;

    ///////////////
    // Sequential
    ///////////////

    // The SEP TRNG reset reloads the downsample cadence with the rest of ESRC.
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            downsample_count <= reg_out.CTRL.DOWNSAMPLE_RATE.value;
        end else if (entropy_stream_valid_gated) begin
            if (downsample_count == 10'd0) begin
                downsample_count <= reg_out.CTRL.DOWNSAMPLE_RATE.value;
            end else begin
                downsample_count <= downsample_count - 10'd1;
            end
        end
    end

    /////////////////
    // Combinational (FIFO push FSM)
    /////////////////

    assign fifo_stream_push = entropy_stream_valid_gated && (downsample_count == 10'd0);

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
                                      entropy_stream_uncompressed[fifo_push_count * 4 + 0]};

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
                                  fifo_push_stream[fifo_push_count * 4 + 0]};

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
        if (!rst_ni) begin
            fifo_push_stream <= '0;
            fifo_push_count  <= 2'd0;
            fifo_push_state  <= ST_FIFO_PUSH_IDLE;
        end else begin
            fifo_push_stream <= fifo_push_stream_next;
            fifo_push_count  <= fifo_push_count_next;
            fifo_push_state  <= fifo_push_state_next;
        end
    end

    // Guard rd_ack with rst_ni: prevents a spurious ack before reg-block initialises
    // its output struct (which would fire assert_bad_ext_rd_ack).
    assign reg_in.FIFO_RDATA.rd_data = fifo_rdata;
    assign reg_in.FIFO_RDATA.rd_ack  =
        rst_ni && reg_out.FIFO_RDATA.req && !reg_out.FIFO_RDATA.req_is_wr;

    ////////////////////
    // Register block
    ////////////////////

    axi4lite_intf #(
        .ADDR_WIDTH (9),
        .DATA_WIDTH (32)
    ) s_axil ();

    // Connect module ports to interface
    assign s_axil.AWVALID  = s_axil_awvalid_i;
    assign s_axil_awready_o = s_axil.AWREADY;
    assign s_axil.AWADDR   = s_axil_awaddr_i;
    assign s_axil.AWPROT   = s_axil_awprot_i;

    assign s_axil.WVALID   = s_axil_wvalid_i;
    assign s_axil_wready_o = s_axil.WREADY;
    assign s_axil.WDATA    = s_axil_wdata_i;
    assign s_axil.WSTRB    = s_axil_wstrb_i;

    assign s_axil_bvalid_o = s_axil.BVALID;
    assign s_axil.BREADY   = s_axil_bready_i;
    assign s_axil_bresp_o  = s_axil.BRESP;

    assign s_axil.ARVALID   = s_axil_arvalid_i;
    assign s_axil_arready_o = s_axil.ARREADY;
    assign s_axil.ARADDR    = s_axil_araddr_i;
    assign s_axil.ARPROT    = s_axil_arprot_i;

    assign s_axil_rvalid_o = s_axil.RVALID;
    assign s_axil.RREADY   = s_axil_rready_i;
    assign s_axil_rdata_o  = s_axil.RDATA;
    assign s_axil_rresp_o  = s_axil.RRESP;

    entropy_source_reg u_entropy_source_reg (
        .clk      (clk_i),
        .arst_n   (rst_ni),
        .s_axil   (s_axil.slave),
        .hwif_in  (reg_in),
        .hwif_out (reg_out)
    );

    ///////////////////
    // Register feeds
    ///////////////////

    // ----------------------------------------------------------------------
    // FIPS configuration lock (swwel REGWEN).
    //
    // FIPS_LOCK.LOCK is a woset sticky bit (set by SW writing 1, cleared only
    // by reset). While asserted it drives swwel=1 on every field that defines
    // the certified noise-source configuration or the health-test decision, so
    // SW writes to those fields are ignored by the reg block. The complete
    // lockable-asset inventory (SP 800-90B 4.3/4.4, 3.1.5.1.1, 3.2.2-6) is:
    //   Group A - health-test config; Group B - conditioning/digitisation;
    //   Group C - noise-source physical config; plus master enable +
    //   ALERT_THRESHOLD/MIN_ENTROPY_H; Group D - pre-conditioning observation
    //   taps (GetNoise-class) and the debug pin, which SP 800-90B 2.3.2/3.2.1
    //   allow disabling outside validation; Group E - FIFO_CTRL.ENABLE, whose
    //   FIFO holds the words that also seed the DRBG.
    // Left writable by design: NOISE_OBS_CTRL.{FLUSH,LANE_SEL} (inert while
    //   RAW_ENABLE is locked off), INTR_*, and the W1C status/fail-count
    //   fields — these support interrupt servicing and the on-demand
    //   health-test trigger (4.3 req 5) without altering the certified
    //   configuration.
    // ----------------------------------------------------------------------
    assign fips_lock = reg_out.FIPS_LOCK.LOCK.value;

    // Group A — health-test configuration.
    assign reg_in.HEALTH_TEST_CTRL.ENABLE.swwel                   = fips_lock;
    assign reg_in.HEALTH_TEST_CTRL.REPETITION_LIMIT.swwel         = fips_lock;
    assign reg_in.HEALTH_TEST_WINDOW_SIZE.SIZE.swwel              = fips_lock;
    assign reg_in.MARKOV_TEST_PROB_THRESHOLDS.PROB_01_THRESHOLD.swwel = fips_lock;
    assign reg_in.MARKOV_TEST_PROB_THRESHOLDS.PROB_10_THRESHOLD.swwel = fips_lock;
    assign reg_in.APT_PROPORTION_1BIT.LIMIT.swwel                = fips_lock;
    assign reg_in.APT_PROPORTION_LO.LIMIT.swwel                  = fips_lock;
    assign reg_in.ALERT_THRESHOLD.THRESHOLD.swwel                = fips_lock;
    assign reg_in.MIN_ENTROPY_H.H.swwel                          = fips_lock;

    // Group B — conditioning / digitisation controls.
    assign reg_in.CTRL.SHA256_WHITENING_ENABLE.swwel             = fips_lock;
    assign reg_in.CTRL.BYPASS_ENTROPY_COMPRESSOR.swwel           = fips_lock;
    assign reg_in.FIFO_CTRL.ENTROPY_CHURN_ENABLE.swwel           = fips_lock;

    // Group C — noise-source physical configuration.
    assign reg_in.CTRL.MODULE_ENABLE.swwel                       = fips_lock;
    assign reg_in.CTRL.AUTOTUNE_ENABLE.swwel                     = fips_lock;
    assign reg_in.CTRL.DOWNSAMPLE_RATE.swwel                     = fips_lock;
    assign reg_in.RING_OSC_ENABLE.ENABLE.swwel                   = fips_lock;
    assign reg_in.RING_OSC_ENABLE.SAMPLE_CLK_ENABLE.swwel        = fips_lock;
    assign reg_in.RING_OSC_TUNE.DETUNE.swwel                     = fips_lock;
    assign reg_in.RING_OSC_TUNE.SAMPLE_CLK_DETUNE.swwel          = fips_lock;
    assign reg_in.RING_OSC_CTRL.SAMPLE_CLK_SELECT.swwel          = fips_lock;
    assign reg_in.DECORRELATOR_CTRL.BYPASS.swwel                 = fips_lock;
    assign reg_in.DECORRELATOR_CTRL.SAMPLE_CLK_DIV.swwel         = fips_lock;
    assign reg_in.DECORRELATOR_MASK.ENTROPY_BYTE_MASK.swwel      = fips_lock;
    assign reg_in.GENERATOR_0_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_1_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_2_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_3_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_4_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_5_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_6_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_7_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_8_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_9_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel  = fips_lock;
    assign reg_in.GENERATOR_10_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel = fips_lock;
    assign reg_in.GENERATOR_11_SAMPLE_CLK_CONFIG.SAMPLE_CLK_DIVIDE.swwel = fips_lock;

    // Group D — pre-conditioning observation taps and debug pin.
    assign reg_in.BIW_OBS_CTRL.RAW_ENABLE.swwel                  = fips_lock;
    assign reg_in.NOISE_OBS_CTRL.RAW_ENABLE.swwel                = fips_lock;
    assign reg_in.DEBUG_CTRL.SELECT_SIGNAL.swwel                 = fips_lock;
    assign reg_in.DEBUG_CTRL.SELECT_FREQ_DIV.swwel              = fips_lock;

    // Group E — software read path of the conditioned output. FIFO_CTRL.ENABLE
    // gates only the main-FIFO push, so the DRBG seed stream is unaffected.
    assign reg_in.FIFO_CTRL.ENABLE.swwel                         = fips_lock;

    // ----------------------------------------------------------------------
    // SP 800-90B recommended-threshold LUT.
    //
    // Combinational map from the assessed per-sample min-entropy
    // MIN_ENTROPY_H.H (Q4.4) to the recommended RCT/APT cutoffs, exposed
    // read-only in RECOMMENDED_THRESHOLDS. Advisory only: firmware reads these
    // to program HEALTH_TEST_CTRL.REPETITION_LIMIT / APT_PROPORTION_* before
    // locking. The LUT module is auto-generated (single source of truth shared
    // with the DV reference) by gen_recommended_thresholds.py:
    //   RCT_LIMIT = 1 + ceil(20 / H)                          (4.4.1, a=2^-20)
    //   APT_LIMIT = binomial normal-approx upper cutoff, W=1024 (4.4.2)
    // ----------------------------------------------------------------------
    assign min_entropy_h = reg_out.MIN_ENTROPY_H.H.value;

    entropy_source_rec_thresh_lut u_rec_thresh_lut (
        .min_entropy_h_i (min_entropy_h),
        .rct_limit_o     (rec_rct_limit),
        .apt_limit_o     (rec_apt_limit)
    );

    assign reg_in.RECOMMENDED_THRESHOLDS.RCT_LIMIT.next = rec_rct_limit;
    assign reg_in.RECOMMENDED_THRESHOLDS.APT_LIMIT.next = rec_apt_limit;

    // ----------------------------------------------------------------------
    // error/fault aggregation bus.
    //
    // Every error and fault signal is collected here in one named place. The
    // four legacy INTR sources (health-test/FIFO) plus the previously-silent
    // main_sm alert/err and counter-fault escalation, plus the new
    // persistent-failure and autotune-fail events, all land in err_bus.
    // Each field drives its own INTR_STATUS sticky bit below; irq_o stays a
    // single aggregated bit to the SEP host.
    // ----------------------------------------------------------------------
    always_comb begin
        err_bus                     = '0;
        err_bus.health_test_failed  = |health_status;
        err_bus.fifo_error          = fifo_error;
        err_bus.fifo_overflow       = fifo_overflow;
        err_bus.fifo_underflow      = fifo_underflow;
        err_bus.es_cntr_err         = es_cntr_err;
        err_bus.main_sm_alert       = main_sm_alert;
        err_bus.main_sm_err         = main_sm_err;
        err_bus.persistent_failure  = persistent_failure;
        err_bus.autotune_fail       = autotune_fail;
        err_bus.biw_obs_overflow    = biw_obs_overflow;
        err_bus.noise_obs_overflow  = noise_obs_overflow;
    end

    // Persistent failure: main_sm entered AlertHang (permanent halt) via
    // the alert-threshold trip. This is the cert-required HW halt indication.
    assign persistent_failure = main_sm_alert;

    assign reg_in.INTR_STATUS.HEALTH_TEST_FAILED.next =
        err_bus.health_test_failed ||
        reg_out.INTR_TEST.HEALTH_TEST_FAILED.value;
    assign reg_in.INTR_STATUS.FIFO_ERROR.next =
        err_bus.fifo_error ||
        reg_out.INTR_TEST.FIFO_ERROR.value;
    assign reg_in.INTR_STATUS.FIFO_OVERFLOW.next =
        err_bus.fifo_overflow ||
        reg_out.INTR_TEST.FIFO_OVERFLOW.value;
    assign reg_in.INTR_STATUS.FIFO_UNDERFLOW.next =
        err_bus.fifo_underflow ||
        reg_out.INTR_TEST.FIFO_UNDERFLOW.value;
    // persistent-failure sticky bit (main_sm AlertHang / counter escalation).
    assign reg_in.INTR_STATUS.PERSISTENT_FAILURE.next =
        (err_bus.persistent_failure || err_bus.main_sm_err || err_bus.es_cntr_err) ||
        reg_out.INTR_TEST.PERSISTENT_FAILURE.value;
    // auto-detune-fail sticky bit.
    assign reg_in.INTR_STATUS.AUTOTUNE_FAIL.next =
        err_bus.autotune_fail ||
        reg_out.INTR_TEST.AUTOTUNE_FAIL.value;
    // Observe-FIFO overflow sticky bits (diagnostic BIW tap / raw NOISE tap).
    // A dropped observe word never affects the certified output path, but a
    // NOISE_OBS drop is a gap in the SP 800-90B raw-collection run, so surface
    // both the same way the main FIFO surfaces FIFO_OVERFLOW.
    assign reg_in.INTR_STATUS.BIW_OBS_OVERFLOW.next =
        err_bus.biw_obs_overflow ||
        reg_out.INTR_TEST.BIW_OBS_OVERFLOW.value;
    assign reg_in.INTR_STATUS.NOISE_OBS_OVERFLOW.next =
        err_bus.noise_obs_overflow ||
        reg_out.INTR_TEST.NOISE_OBS_OVERFLOW.value;

    // The status bits above latch whether or not the interrupt is enabled and
    // clear only on W1C; INTR_ENABLE masks the output (as prim_intr_hw does).
    assign irq_o =
        (reg_out.INTR_STATUS.HEALTH_TEST_FAILED.value && reg_out.INTR_ENABLE.HEALTH_TEST_FAILED.value) ||
        (reg_out.INTR_STATUS.FIFO_ERROR.value         && reg_out.INTR_ENABLE.FIFO_ERROR.value) ||
        (reg_out.INTR_STATUS.FIFO_OVERFLOW.value      && reg_out.INTR_ENABLE.FIFO_OVERFLOW.value) ||
        (reg_out.INTR_STATUS.FIFO_UNDERFLOW.value     && reg_out.INTR_ENABLE.FIFO_UNDERFLOW.value) ||
        (reg_out.INTR_STATUS.PERSISTENT_FAILURE.value && reg_out.INTR_ENABLE.PERSISTENT_FAILURE.value) ||
        (reg_out.INTR_STATUS.AUTOTUNE_FAIL.value      && reg_out.INTR_ENABLE.AUTOTUNE_FAIL.value) ||
        (reg_out.INTR_STATUS.BIW_OBS_OVERFLOW.value   && reg_out.INTR_ENABLE.BIW_OBS_OVERFLOW.value) ||
        (reg_out.INTR_STATUS.NOISE_OBS_OVERFLOW.value && reg_out.INTR_ENABLE.NOISE_OBS_OVERFLOW.value);

    assign reg_in.FIFO_STATUS.LEVEL.next = fifo_level;
    assign reg_in.FIFO_STATUS.WPTR.next  = fifo_wptr;
    assign reg_in.FIFO_STATUS.RPTR.next  = fifo_rptr;

    assign reg_in.HEALTH_TEST_STATUS.HEALTH_STATUS.next = health_status;

    assign reg_in.APT_PATTERN_COUNT_1BIT.PATTERN_COUNT.next = apt_pattern_count_1bit;
    assign reg_in.APT_PATTERN_COUNT_2BIT.PATTERN_COUNT.next = apt_pattern_count_2bit;

    assign reg_in.REPETITION_TEST_COUNT.REPETITION_COUNT.next = ctr_repetition;

    assign reg_in.MARKOV_TEST_COUNTS_0.COUNT_01.next = count_01;
    assign reg_in.MARKOV_TEST_COUNTS_0.COUNT_10.next = count_10;

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

    /////////////////////////////
    // Watermark / fail counter
    /////////////////////////////

    assign repcnt_fail_pulse    = health_status[0];
    assign markov_hi_fail_pulse = health_status[4];
    assign markov_lo_fail_pulse = health_status[5];

    // MODULE_ENABLE rising-edge detect (OpenTitan module_en_pulse).
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) module_en_q <= 1'b0;
        else         module_en_q <= reg_out.CTRL.MODULE_ENABLE.value;
    end
    assign module_en_pulse = reg_out.CTRL.MODULE_ENABLE.value && !module_en_q;

    assign health_test_clr  = module_en_pulse;
    assign alert_cntr_clr_ok = alert_cntr_clr_ok_main_sm;
    assign alert_cntrs_clr  = health_test_clr ||
                               (window_wrap_pulse && alert_cntr_clr_ok && !ht_fail_pulse);

    assign es_cntr_err = repcnt_fails_cntr_err    || apt_hi_fails_cntr_err  ||
                         apt_lo_fails_cntr_err     || markov_hi_fails_cntr_err ||
                         markov_lo_fails_cntr_err  || any_fails_cntr_err    ||
                         repcnt_alert_cntr_err     || apt_hi_alert_cntr_err ||
                         apt_lo_alert_cntr_err     || markov_hi_alert_cntr_err ||
                         markov_lo_alert_cntr_err  || generator_complex_cntr_err ||
                         health_test_cntr_err;

    // per-window sticky health-test-fail latch.
    //
    // ht_fail_pulse is the canonical "one assertion per failing window" signal:
    // it drives the boot gate, the ANY_FAIL_COUNT failing-window counter, and
    // the clean-window alert-counter clear. It samples health only at window
    // wrap. APT/Markov are window-aligned, but the RCT is *continuous* — a
    // mid-window failure that is not coincident with the wrap cycle would
    // otherwise be missed (slipping the boot gate, or under-counting failing
    // windows). This sticky latch records any |health_status assertion
    // occurring during the window and holds it until the wrap cycle samples it,
    // then clears for the next window. The sampled sticky value is OR'd into
    // ht_fail_pulse so any mid-window failure counts as one failing window.
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            ht_fail_sticky_q <= 1'b0;
        end else if (window_wrap_pulse) begin
            // Sampled this cycle by ht_fail_pulse; restart accumulation. Capture
            // a fresh failure landing exactly on the wrap cycle immediately.
            ht_fail_sticky_q <= health_test_enable && (|health_status);
        end else if (health_test_enable && (|health_status)) begin
            ht_fail_sticky_q <= 1'b1;
        end
    end

    // Qualify with health_test_enable: compressor-bypass mode freezes HT counters,
    // causing spurious low-side failures at every window wrap. Also trip on a
    // sticky mid-window failure, not just a failure present at the wrap cycle.
    assign ht_fail_pulse = window_wrap_pulse && health_test_enable &&
                           ((|health_status) || ht_fail_sticky_q);

    // alert-threshold comparator. When the aggregate failing-window count
    // reaches the locked ALERT_THRESHOLD, assert alert_thresh_fail_i so main_sm
    // transitions to AlertHang (permanent halt). THRESHOLD=0 disables the trip.
    assign alert_thresh_fail =
        (reg_out.ALERT_THRESHOLD.THRESHOLD.value != 16'd0) &&
        (any_fail_count >= reg_out.ALERT_THRESHOLD.THRESHOLD.value);

    // auto-detune fired.
    //
    // AUTOTUNE_FAIL flags that an automatic per-lane retune acted. Each lane's
    // tune FSM is driven by that lane's own health-test status, so the report is
    // the OR of the twelve per-lane HT-fail signals gated by AUTOTUNE_ENABLE.
    // When CTRL.AUTOTUNE_ENABLE=1 a per-lane HT failure triggers a self-heal
    // detune that changes the noise-source geometry, a certification-relevant
    // event surfaced via INTR_STATUS.AUTOTUNE_FAIL. In the certified config
    // AUTOTUNE_ENABLE is swwel-locked to 0, so this path stays idle.
    // autotune_fail feeds only the interrupt; the ALERT_THRESHOLD
    // persistent-halt path is separate.
    assign autotune_fail = reg_out.CTRL.AUTOTUNE_ENABLE.value &&
                           |{generator_0_test_status,  generator_1_test_status,
                             generator_2_test_status,  generator_3_test_status,
                             generator_4_test_status,  generator_5_test_status,
                             generator_6_test_status,  generator_7_test_status,
                             generator_8_test_status,  generator_9_test_status,
                             generator_10_test_status, generator_11_test_status};

    entropy_src_main_sm u_main_sm (
        .clk_i               (clk_i),
        .rst_ni              (rst_ni),
        .enable_i            (reg_out.CTRL.MODULE_ENABLE.value),
        .fw_ov_ent_insert_i  (1'b0),  // Firmware entropy injection not used.
        .fw_ov_sha3_start_i  (1'b0),
        .ht_done_pulse_i     (window_wrap_pulse),
        .pd_cntr_zero_i      (1'b1),  // Sha3Process state unreachable while bypass_mode_i=1
        .ht_fail_pulse_i     (ht_fail_pulse),
        .alert_thresh_fail_i (alert_thresh_fail),  // any_fail_count >= ALERT_THRESHOLD.
        .alert_cntr_clr_ok_o (alert_cntr_clr_ok_main_sm),
        .bypass_mode_i       (1'b1),
        .bypass_stage_rdy_i  (1'b1),  // No bypass-stage FIFO; downstream always ready.
        .sha3_state_vld_i    (1'b1),  // Sha3Valid state unreachable while bypass_mode_i=1
        .main_stage_push_o   (),      // Unused: no downstream main-stage FIFO.
        .bypass_stage_pop_o  (),      // Unused: no bypass-stage FIFO.
        .boot_phase_done_o   (boot_phase_done),
        .sha3_start_o        (),      // Unused: SHA-256 whitener used instead of SHA-3.
        .sha3_process_o      (),
        .sha3_done_o         (),
        .local_escalate_i    (es_cntr_err),
        .main_sm_alert_o     (main_sm_alert),
        .main_sm_idle_o      (main_sm_idle),
        .main_sm_state_o     (main_sm_state),
        .main_sm_err_o       (main_sm_err)
    );

    assign reg_in.MAIN_SM_STATUS.STATE.next             = main_sm_state;
    assign reg_in.MAIN_SM_STATUS.IDLE.next              = main_sm_idle;
    assign reg_in.MAIN_SM_STATUS.ALERT.next             = main_sm_alert;
    assign reg_in.MAIN_SM_STATUS.ERR.next               = main_sm_err;
    assign reg_in.MAIN_SM_STATUS.BOOT_PHASE_DONE.next   = boot_phase_done;
    assign reg_in.MAIN_SM_STATUS.ALERT_CNTR_CLR_OK.next = alert_cntr_clr_ok_main_sm;

    assign ht_watermark_num_reg_if =
        watermark_test_e'(reg_out.HT_WATERMARK_NUM.WATERMARK_NUM.value);

    always_comb begin
        unique case (ht_watermark_num_reg_if)
            REPCNT_HI,
            APT_HI,
            APT_LO,
            MARKOV_HI,
            MARKOV_LO: ht_watermark_num_d = ht_watermark_num_reg_if;
            default:   ht_watermark_num_d = REPCNT_HI;  // Unsupported values map to REPCNT_HI.
        endcase
    end

    // Register the resolved value; selector and watermark reset together.
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
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

    assign ht_watermark_event = ht_watermark_event_pre && (|reg_out.HEALTH_TEST_CTRL.ENABLE.value);

    assign repcnt_event_cnt    = ctr_repetition;
    assign apt_hi_event_cnt    = apt_pattern_count_1bit;
    assign apt_lo_event_cnt    = apt_pattern_count_2bit;
    assign markov_hi_event_cnt = count_01;
    assign markov_lo_event_cnt = count_10;

    entropy_src_watermark_reg #(
        .RegWidth (16),
        .ResVal   (16'h0)
    ) u_entropy_src_ht_watermark_reg (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .high_i   (ht_watermark_high),
        .clear_i  (health_test_clr),
        .oneway_i (1'b1),
        .event_i  (ht_watermark_event),
        .value_i  (ht_watermark_cnt),
        .value_o  (ht_watermark)
    );

    entropy_src_cntr_reg #(
        .RegWidth (32)
    ) u_entropy_src_cntr_reg_repcnt (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (health_test_clr),
        .event_i (repcnt_fail_pulse),
        .step_i  (32'd1),
        .value_o (repcnt_total_fails),
        .err_o   (repcnt_fails_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (32)
    ) u_entropy_src_cntr_reg_apt_hi (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (health_test_clr),
        .event_i (apt_hi_fail_pulse),
        .step_i  (32'd1),
        .value_o (apt_hi_total_fails),
        .err_o   (apt_hi_fails_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (32)
    ) u_entropy_src_cntr_reg_apt_lo (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (health_test_clr),
        .event_i (apt_lo_fail_pulse),
        .step_i  (32'd1),
        .value_o (apt_lo_total_fails),
        .err_o   (apt_lo_fails_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (32)
    ) u_entropy_src_cntr_reg_markov_hi (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (health_test_clr),
        .event_i (markov_hi_fail_pulse),
        .step_i  (32'd1),
        .value_o (markov_hi_total_fails),
        .err_o   (markov_hi_fails_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (32)
    ) u_entropy_src_cntr_reg_markov_lo (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (health_test_clr),
        .event_i (markov_lo_fail_pulse),
        .step_i  (32'd1),
        .value_o (markov_lo_total_fails),
        .err_o   (markov_lo_fails_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (16)
    ) u_entropy_src_cntr_reg_any_alert_fails (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (alert_cntrs_clr),
        .event_i (ht_fail_pulse),
        .step_i  (16'd1),
        .value_o (any_fail_count),
        .err_o   (any_fails_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (4)
    ) u_entropy_src_cntr_reg_repcnt_alert (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (alert_cntrs_clr),
        .event_i (repcnt_fail_pulse),
        .step_i  (4'd1),
        .value_o (repcnt_fail_count),
        .err_o   (repcnt_alert_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (4)
    ) u_entropy_src_cntr_reg_apt_hi_alert (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (alert_cntrs_clr),
        .event_i (apt_hi_fail_pulse),
        .step_i  (4'd1),
        .value_o (apt_hi_fail_count),
        .err_o   (apt_hi_alert_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (4)
    ) u_entropy_src_cntr_reg_apt_lo_alert (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (alert_cntrs_clr),
        .event_i (apt_lo_fail_pulse),
        .step_i  (4'd1),
        .value_o (apt_lo_fail_count),
        .err_o   (apt_lo_alert_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (4)
    ) u_entropy_src_cntr_reg_markov_hi_alert (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (alert_cntrs_clr),
        .event_i (markov_hi_fail_pulse),
        .step_i  (4'd1),
        .value_o (markov_hi_fail_count),
        .err_o   (markov_hi_alert_cntr_err)
    );

    entropy_src_cntr_reg #(
        .RegWidth (4)
    ) u_entropy_src_cntr_reg_markov_lo_alert (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .clear_i (alert_cntrs_clr),
        .event_i (markov_lo_fail_pulse),
        .step_i  (4'd1),
        .value_o (markov_lo_fail_count),
        .err_o   (markov_lo_alert_cntr_err)
    );

    ///////////
    // Output
    ///////////

    assign reg_in.HT_WATERMARK.WATERMARK_VALUE.next = ht_watermark;

    assign reg_in.REPCNT_TOTAL_FAILS.FAIL_COUNT.next   = repcnt_total_fails;
    assign reg_in.APT_HI_TOTAL_FAILS.FAIL_COUNT.next   = apt_hi_total_fails;
    assign reg_in.APT_LO_TOTAL_FAILS.FAIL_COUNT.next   = apt_lo_total_fails;
    assign reg_in.MARKOV_HI_TOTAL_FAILS.FAIL_COUNT.next = markov_hi_total_fails;
    assign reg_in.MARKOV_LO_TOTAL_FAILS.FAIL_COUNT.next = markov_lo_total_fails;

    assign reg_in.ALERT_SUMMARY_FAIL_COUNTS.ANY_FAIL_COUNT.next = any_fail_count;

    assign reg_in.ALERT_FAIL_COUNTS.REPCNT_FAIL_COUNT.next    = repcnt_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.APT_HI_FAIL_COUNT.next    = apt_hi_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.APT_LO_FAIL_COUNT.next    = apt_lo_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.MARKOV_HI_FAIL_COUNT.next = markov_hi_fail_count;
    assign reg_in.ALERT_FAIL_COUNTS.MARKOV_LO_FAIL_COUNT.next = markov_lo_fail_count;

    // ----------------------------------------------------------------------
    // health-test window-size floor assertion.
    //
    // Once FIPS_LOCK is asserted, the certified configuration must keep the
    // health-test window at >= 1024 samples (defends the >=1024 startup
    // guarantee; the field is RW down to 256 before lock). SIZE is swwel-locked
    // under FIPS_LOCK so it cannot change post-lock; this assertion catches a
    // config that locked with an out-of-spec window.
    // ----------------------------------------------------------------------
    `OCAH_OT_ASSERT(FipsWindowFloor_A,
            fips_lock |-> (reg_out.HEALTH_TEST_WINDOW_SIZE.SIZE.value >= 16'd1024))

endmodule
