// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Run the OCTS credit-based primary/secondary timer counter.
//
// Primary emits sync and credit; secondary consumes them and may step by
// timer_cnt_step_i.
// A primary counts up by one per cycle from the preset loaded on reg_start_i and pulses
// timer_cnt_credit_o every reg_credit_val_i cycles. A secondary loads the preset on a sync
// pulse, adds timer_cnt_step_i each cycle until the steps since the last pulse reach
// reg_credit_val_i, and on each credit pulse jumps to the expected count, which grows by
// reg_credit_val_i per pulse. Inbound pulses are synchronized into clk_i and edge detected.
// Once started, the timer runs until reset.
// Register ports are bus-agnostic.
// credit_expired_o counts clk_i cycles a secondary spends without credits and clears on a
// credit or sync pulse or on credit_expired_clr_i.
// timer_cnt_step_i and credit_expired_* apply in secondary mode only.

module system_timer_octs_core
    import system_timer_octs_pkg::*;

    `include "prim_assert.sv"
(
    input  logic                  clk_i,                    // System clock.
    input  logic                  rst_ni,                   // Async reset, active-low.

    input  logic                  is_primary_i,             // Runtime primary/secondary mode
                                                            // select; 1 selects primary.

    input  logic                  reg_start_i,              // Software start pulse; in primary mode
                                                            // loads the preset and emits
                                                            // timer_sync_load_o.
    input  logic [7:0]            reg_credit_val_i,         // Credit period in cycles for a primary
                                                            // and count advance per credit pulse
                                                            // for a secondary; must exceed the
                                                            // pulse width.
    input  logic [DATA_WIDTH-1:0] reg_preset_lo_i,          // Preset count low half.
    input  logic [DATA_WIDTH-1:0] reg_preset_hi_i,          // Preset count high half.
    input  logic [7:0]            reg_pulse_width_i,        // Sync/credit pulse width in clk_i
                                                            // cycles; zero acts as one.

    output logic                  reg_mode_o,               // Reports mode: 0 for primary, 1 for
                                                            // secondary.
    output logic                  reg_running_o,            // Timer is started and its count is
                                                            // nonzero.
    output logic [DATA_WIDTH-1:0] reg_count_lo_o,           // Count low half.
    output logic [DATA_WIDTH-1:0] reg_count_hi_o,           // Count high half.

    input  logic                  timer_sync_load_i,        // Inbound sync-load pulse; ignored in
                                                            // primary mode.
    input  logic                  timer_cnt_credit_i,       // Inbound credit pulse; ignored in
                                                            // primary mode.
    output logic                  timer_sync_load_o,        // Outbound sync-load pulse; low in
                                                            // secondary mode.
    output logic                  timer_cnt_credit_o,       // Outbound credit pulse; low in
                                                            // secondary mode.

    input  logic [7:0]            timer_cnt_step_i,         // Secondary count increment per clk_i
                                                            // cycle while credits remain.

    input  logic                  credit_expired_clr_i,     // Clear the credit-expired counter.
    output logic [31:0]           credit_expired_o,         // Secondary clk_i cycles without
                                                            // credits since the last credit or sync
                                                            // pulse.

    output logic [63:0]           timer_count_o,            // Live 64-bit timer count.

    output logic [8:0]            cur_credits_debug_o,      // Secondary steps consumed since the
                                                            // last credit or sync pulse.
    output logic                  credits_left_debug_o      // High while cur_credits_debug_o is
                                                            // below reg_credit_val_i.
);

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    // Register enable signals
    logic                      enable;

    // Timer preset signals
    logic [63:0]               timer_preset;

    // Internal signals
    logic [63:0]               timer_count_q, timer_count_d;
    logic [7:0]                credit_counter_q, credit_counter_d;
    logic [63:0]               expected_count_q, expected_count_d;
    logic                      credit_gen_pulse;

    // Synchronized input signals (from edge detectors)
    logic                      timer_sync_load_sync_posedge_raw;
    logic                      timer_cnt_credit_sync_posedge_raw;
    logic                      timer_sync_load_sync_posedge;
    logic                      timer_cnt_credit_sync_posedge;

    // Credit counter signals (SECONDARY only)
    logic [8:0]                cur_credits; // 9 bits to handle the case where cur_credits = reg_credit_val_i
    logic                      credits_left;

    assign credits_left = (cur_credits < {1'b0, reg_credit_val_i});

    // Carry-select adder outputs
    logic [63:0]               timer_count_plus_one;
    logic [63:0]               expected_count_plus_credit;
    logic [63:0]               timer_count_plus_step;

    // Pulse generation signals
    typedef enum logic [1:0] {
        PULSE_IDLE = 2'b00,
        PULSE_SYNC_LOAD = 2'b01,
        PULSE_CREDIT = 2'b10
    } pulse_state_t;

    logic [7:0]                 pulse_counter;
    pulse_state_t               pulse_active;

    /////////////////////////////////////////
    // CDC Synchronization and Pulse Logic //
    /////////////////////////////////////////

    // First flop the inputs to the edge detectors to ensure they are stable when sampled.
    logic timer_sync_load_flopped;
    logic timer_cnt_credit_flopped;
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            timer_sync_load_flopped <= 1'b0;
            timer_cnt_credit_flopped <= 1'b0;
        end else begin
            timer_sync_load_flopped <= timer_sync_load_i;
            timer_cnt_credit_flopped <= timer_cnt_credit_i;
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            enable <= 1'b0;
        end else begin
            enable <= enable | reg_start_i | timer_sync_load_sync_posedge;
        end
    end

    // Always instantiate edge detectors (can't conditionally instantiate at runtime)
    prim_edge_detector u_sync_load_detector (
        .clk_i              (clk_i),
        .rst_ni             (rst_ni),
        .d_i                (timer_sync_load_flopped),
        .q_sync_o           (),
        .q_posedge_pulse_o  (timer_sync_load_sync_posedge_raw),
        .q_negedge_pulse_o  ()
    );

    prim_edge_detector u_credit_cnt_detector (
        .clk_i              (clk_i),
        .rst_ni             (rst_ni),
        .d_i                (timer_cnt_credit_flopped),
        .q_sync_o           (),
        .q_posedge_pulse_o  (timer_cnt_credit_sync_posedge_raw),
        .q_negedge_pulse_o  ()
    );

    // Gate outputs when in primary mode (primary doesn't use these sync signals)
    assign timer_sync_load_sync_posedge  = is_primary_i ? 1'b0 : timer_sync_load_sync_posedge_raw;
    assign timer_cnt_credit_sync_posedge = is_primary_i ? 1'b0 : timer_cnt_credit_sync_posedge_raw;

    ///////////////////////////
    // Carry-Select Adders   //
    ///////////////////////////

    // Carry-select adder for timer_count + 1 (PRIMARY mode)
    prim_carry_select_adder #(
        .DATA_WIDTH(64),
        .NUM_CHUNKS(2)
    ) u_adder_timer_inc (
        .a_i   (timer_count_q),
        .b_i   (64'h1),
        .sum_o (timer_count_plus_one),
        .c_o   ()  // unused
    );

    // Carry-select adder for expected_count + credit_val (SECONDARY mode)
    prim_carry_select_adder #(
        .DATA_WIDTH(64),
        .NUM_CHUNKS(2)
    ) u_adder_expected_credit (
        .a_i   (expected_count_q),
        .b_i   ({56'h0, reg_credit_val_i}),
        .sum_o (expected_count_plus_credit),
        .c_o   ()  // unused
    );

    // Carry-select adder for timer_count + step (SECONDARY mode)
    prim_carry_select_adder #(
        .DATA_WIDTH(64),
        .NUM_CHUNKS(2)
    ) u_adder_timer_step (
        .a_i   (timer_count_q),
        .b_i   ({56'h0, timer_cnt_step_i}),
        .sum_o (timer_count_plus_step),
        .c_o   ()  // unused
    );

    //////////////////////////////
    // Main Timer Counter Logic //
    //////////////////////////////

    assign timer_preset = {reg_preset_hi_i, reg_preset_lo_i};

    always_comb begin
        timer_count_d = timer_count_q;

        if (~enable && ~reg_start_i && ~timer_sync_load_sync_posedge) begin
            timer_count_d = 64'b0;
        end else if (is_primary_i) begin
            if (reg_start_i) begin
                timer_count_d = timer_preset;
            end else begin
                timer_count_d = timer_count_plus_one;
            end
        end else begin
            if (timer_sync_load_sync_posedge) begin
                timer_count_d = timer_preset;
            end else if (timer_cnt_credit_sync_posedge) begin
                timer_count_d = expected_count_plus_credit;
            end else if (credits_left) begin
                timer_count_d = timer_count_plus_step;
            end
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            timer_count_q <= 64'h0;
        end else begin
            timer_count_q <= timer_count_d;
        end
    end

    ////////////////////////
    // PRIMARY Mode Logic //
    ////////////////////////

    always_comb begin
        credit_counter_d = credit_counter_q;

        if (is_primary_i) begin
            // PRIMARY logic
            if (~enable || reg_start_i) begin
                credit_counter_d = 8'h0;
            end else begin
                if (credit_counter_q >= (reg_credit_val_i - 1)) begin
                    credit_counter_d = 8'h0;
                end else begin
                    credit_counter_d = credit_counter_q + 8'h1;
                end
            end
        end else begin
            // SECONDARY: hold at 0
            credit_counter_d = 8'h0;
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            credit_counter_q <= 8'h0;
        end else begin
            credit_counter_q <= credit_counter_d;
        end
    end

    assign credit_gen_pulse = is_primary_i && enable && (credit_counter_q == (reg_credit_val_i - 1));

    `OCAH_OT_ASSERT(CreditCounterValid_A, credit_counter_q <= reg_credit_val_i) // Credit counter should never exceed credit value

    //////////////////////////
    // SECONDARY Mode Logic //
    //////////////////////////

    always_comb begin
        expected_count_d = expected_count_q;

        if (~is_primary_i) begin
            // SECONDARY logic
            if (timer_sync_load_sync_posedge) begin
                expected_count_d = timer_preset;
            end else if (timer_cnt_credit_sync_posedge) begin
                expected_count_d = expected_count_plus_credit;
            end
        end else begin
            // PRIMARY: hold at 0
            expected_count_d = 64'h0;
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (~rst_ni) begin
            expected_count_q <= 64'h0;
            cur_credits      <= 8'h0;
            credit_expired_o <= 32'h0;
        end else if (is_primary_i) begin
            // PRIMARY: hold at 0
            expected_count_q <= 64'h0;
            cur_credits      <= 8'h0;
            credit_expired_o <= 32'h0;
        end else begin
            // SECONDARY logic
            expected_count_q <= expected_count_d;
            if (timer_cnt_credit_sync_posedge | timer_sync_load_sync_posedge) begin
                cur_credits <= 8'h0;
            end else if (credits_left) begin
                cur_credits <= cur_credits[7:0] + timer_cnt_step_i;
            end

            if (timer_cnt_credit_sync_posedge | timer_sync_load_sync_posedge | credit_expired_clr_i) begin
                credit_expired_o <= 32'h0;
            end else if (!credits_left) begin
                credit_expired_o <= credit_expired_o + 32'h1;
            end
        end
    end

    `OCAH_OT_ASSERT(ExpectedCountValid_A, is_primary_i || (timer_count_q - expected_count_q <= reg_credit_val_i)) // Expected count should never exceed timer count by more than credit value (SECONDARY only)

    ////////////////////////////
    // Pulse Generation Logic //
    ////////////////////////////

    // Set pulse width to 1 if pulse width is 0
    wire [7:0] pulse_width = (reg_pulse_width_i == 8'h0) ? 8'b1 : reg_pulse_width_i;

    // Logic to control the pulse counter
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            pulse_counter <= 8'h0;
            pulse_active  <= PULSE_IDLE;
        end else begin
            // Start a new pulse on trigger of sync load
            if (reg_start_i && pulse_active == PULSE_IDLE) begin
                pulse_counter <= 8'h0;
                pulse_active  <= PULSE_SYNC_LOAD;
            end
            // Start a new pulse on trigger of credit cnt
            else if (enable && credit_gen_pulse && pulse_active == PULSE_IDLE) begin
                pulse_counter   <= 8'h0;
                pulse_active    <= PULSE_CREDIT;
            end
            // Increment counter if pulse is active and hasn't reached width
            else if ((pulse_active != PULSE_IDLE) && (pulse_counter < (pulse_width - 8'b1))) begin
                pulse_counter   <= pulse_counter + 8'h1;
            end
            // End pulse when counter reaches the specified width
            else begin
                pulse_active    <= PULSE_IDLE;
                pulse_counter   <= 8'h0;
            end
        end
    end

    `OCAH_OT_ASSERT(PulseActiveValid_A, pulse_active inside {PULSE_IDLE, PULSE_SYNC_LOAD, PULSE_CREDIT}) // Pulse active should never be anything other than idle, sync load, or credit
    `OCAH_OT_ASSERT(PulseCounterValid_A, pulse_counter < pulse_width) // Pulse counter should never exceed pulse width
    `OCAH_OT_ASSERT(CreditValGreaterThanPulseWidth_A, reg_credit_val_i > pulse_width) // Credit value must be greater than pulse width, otherwise pulses will be missed

    ////////////////////////
    // Output Assignments //
    ////////////////////////

    assign timer_count_o            = timer_count_q;
    assign timer_sync_load_o        = is_primary_i ? pulse_active == PULSE_SYNC_LOAD  : 1'b0;
    assign timer_cnt_credit_o       = is_primary_i ? pulse_active == PULSE_CREDIT     : 1'b0;

    `OCAH_OT_ASSERT(TimerCountZero_A, (~enable && ~reg_start_i && ~timer_sync_load_sync_posedge) -> (timer_count_q == 64'h0)) // Timer count should be 0 when enable is 0 and not starting
    `OCAH_OT_ASSERT(TimerCntCreditZero_A, (~enable && ~reg_start_i) -> (~timer_cnt_credit_o)) // Timer credit should be 0 when enable is 0 and not starting
    `OCAH_OT_ASSERT(TimerSyncLoadZero_A, (~enable && ~reg_start_i) -> (~timer_sync_load_o)) // Timer sync load should be 0 when enable is 0 and not starting

    // Register interface outputs
    assign reg_mode_o               = is_primary_i ? 1'b0 : 1'b1;
    assign reg_running_o            = enable && (timer_count_q > 64'h0);
    assign reg_count_lo_o           = timer_count_q[31:0];
    assign reg_count_hi_o           = timer_count_q[63:32];

    // Debug outputs
    assign cur_credits_debug_o      = cur_credits;
    assign credits_left_debug_o     = credits_left;

endmodule
