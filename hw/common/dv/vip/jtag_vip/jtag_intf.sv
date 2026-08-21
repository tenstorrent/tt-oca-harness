// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

/**
 * JTAG Interface
 *
 * Comprehensive JTAG interface for use with CocoTB BFM and Monitor.
 * Compatible with jtag_mst_bfm.py and jtag_mon.py signal definitions.
 * Follows IEEE 1149.1 JTAG specification.
 *
 * Features:
 * - Standard 4-wire JTAG interface (TCK, TMS, TDI, TDO)
 * - Optional TRST (Test Reset) signal
 * - Master and slave modports
 * - Monitor modport for passive observation
 * - Utility tasks for common operations
 * - Optional protocol assertions
 * - Signal naming compatible with Python BFM/Monitor
 */

interface jtag_intf #(
        parameter bit ENABLE_TRST = 1'b1,    // Enable TRST signal (0 = disable, 1 = enable)
        parameter int JTAG_IR_WIDTH = 6,     // JTAG Instruction Register Width
        parameter int JTAG_DR_WIDTH = 64     // JTAG Data Register Width
    )(
        // No clock or reset inputs - JTAG is self-timed via TCK
    );

    //==========================================================================
    // JTAG Signal Definitions (IEEE 1149.1)
    // STANDARD NAMING CONVENTION - Used by all BFM and Monitor components
    //==========================================================================

    logic tck;      // Test Clock - JTAG clock signal
    logic tms;      // Test Mode Select - controls TAP state machine transitions
    logic tdi;      // Test Data In - serial data input to JTAG chain
    logic tdo;      // Test Data Out - serial data output from JTAG chain
    logic tdo_oen;  // Test Data Out Output Enable - indicates when TDO is valid
    logic trst;     // Test Reset - optional active-low asynchronous reset

    // NOTE: These signal names (tck, tms, tdi, tdo, tdo_oen, trst) are the standard
    // naming convention used by jtag_mst_bfm.py and jtag_mon.py components.
    // Do not change these names without updating all dependent files.

    //==========================================================================
    // Master Modport (for JTAG Controller/Master/BFM perspective)
    // Used by devices that drive JTAG signals (test equipment, BFMs)
    //==========================================================================
    modport master (
        output tck,     // Controller drives the clock
        output tms,     // Controller drives mode select
        output tdi,     // Controller drives data in
        input  tdo,     // Controller reads data out
        input  tdo_oen, // Controller reads TDO output enable
        output trst     // Controller drives reset (if enabled)
    );

    //==========================================================================
    // Slave Modport (for JTAG Target/Slave perspective)
    // Used by devices that respond to JTAG signals (DUT, TAP controllers)
    //==========================================================================
    modport slave (
        input  tck,     // Target receives the clock
        input  tms,     // Target receives mode select
        input  tdi,     // Target receives data in
        output tdo,     // Target drives data out
        output tdo_oen, // Target drives TDO output enable
        input  trst     // Target receives reset (if enabled)
    );

    //==========================================================================
    // Monitor Modport (for passive monitoring)
    // Used by monitors that observe but don't drive any signals
    //==========================================================================
    modport monitor (
        input  tck,     // Monitor observes clock
        input  tms,     // Monitor observes mode select
        input  tdi,     // Monitor observes data in
        input  tdo,     // Monitor observes data out
        input  tdo_oen, // Monitor observes TDO output enable
        input  trst     // Monitor observes reset
    );

    //==========================================================================
    // JTAG TAP State Enumeration
    //==========================================================================
    typedef enum logic [3:0] {
        TEST_LOGIC_RESET = 4'd0,
        RUN_TEST_IDLE    = 4'd1,
        SELECT_DR_SCAN   = 4'd2,
        CAPTURE_DR       = 4'd3,
        SHIFT_DR         = 4'd4,
        EXIT1_DR         = 4'd5,
        PAUSE_DR         = 4'd6,
        EXIT2_DR         = 4'd7,
        UPDATE_DR        = 4'd8,
        SELECT_IR_SCAN   = 4'd9,
        CAPTURE_IR       = 4'd10,
        SHIFT_IR         = 4'd11,
        EXIT1_IR         = 4'd12,
        PAUSE_IR         = 4'd13,
        EXIT2_IR         = 4'd14,
        UPDATE_IR        = 4'd15
    } jtag_tap_state_t;

    // Current TAP state (for monitoring/debugging)
    jtag_tap_state_t current_tap_state = TEST_LOGIC_RESET;

    //==========================================================================
    // Debug and Information Functions
    //==========================================================================
    logic [JTAG_IR_WIDTH-1:0] ir_capture_reg = 0;
    logic [JTAG_IR_WIDTH-1:0] ir_shift_reg = 0;
    logic [JTAG_IR_WIDTH-1:0] ir_update_reg = 0;
    logic [JTAG_DR_WIDTH-1:0] dr_capture_reg = 0;
    logic [JTAG_DR_WIDTH-1:0] dr_shift_reg = 0;
    logic [JTAG_DR_WIDTH-1:0] dr_update_reg = 0;

    //==========================================================================
    // Utility Tasks for Common Operations
    //==========================================================================

    // Initialize all signals to safe defaults
    task automatic init_controller_signals();
        tck <= 1'b0;
        tms <= 1'b1;      // TMS high forces to Test-Logic-Reset
        tdi <= 1'b0;
        if (ENABLE_TRST) begin
            trst <= 1'b0;  // Assert reset initially
        end
    endtask

    // Initialize target output signals
    task automatic init_target_signals();
        tdo <= 1'b0;      // Target drives TDO
        tdo_oen <= 1'b0;  // TDO output enable initially disabled
    endtask

    // Perform JTAG reset using TRST (if available)
    task automatic reset_via_trst();
        if (ENABLE_TRST) begin
            trst <= 1'b0;
            repeat(5) @(posedge tck);  // Hold reset for several cycles
            trst <= 1'b1;
            @(posedge tck);
            current_tap_state <= TEST_LOGIC_RESET;
            $display("[%0t] JTAG Reset via TRST completed", $time);
        end else begin
            $warning("[%0t] TRST not enabled, cannot perform TRST reset", $time);
        end
    endtask

    // Perform JTAG reset using TMS (software reset)
    task automatic reset_via_tms();
        // Hold TMS high for 5+ cycles to guarantee Test-Logic-Reset state
        tms <= 1'b1;
        repeat(5) begin
            tck <= 1'b0;
            #1;
            tck <= 1'b1;
            #1;
        end
        current_tap_state <= TEST_LOGIC_RESET;
        $display("[%0t] JTAG Reset via TMS completed", $time);
    endtask

    // Navigate to Run-Test/Idle state from any state
    task automatic goto_run_test_idle();
        // First go to Test-Logic-Reset
        reset_via_tms();

        // Then move to Run-Test/Idle (TMS=0 from Test-Logic-Reset)
        tms <= 1'b0;
        tck <= 1'b0;
        #1;
        tck <= 1'b1;
        #1;
        current_tap_state <= RUN_TEST_IDLE;
        $display("[%0t] JTAG state: Run-Test/Idle", $time);
    endtask

    // Generate a single TCK cycle
    task automatic cycle_tck();
        tck <= 1'b0;
        #1;
        tck <= 1'b1;
        #1;
    endtask

    // Shift data through JTAG chain (basic shift operation)
    task automatic shift_data(input logic [31:0] data_in,
            input int length,
            output logic [31:0] data_out);
        int i;
        data_out = 32'h0;

        for (i = 0; i < length; i++) begin
            // Set TDI for this bit
            tdi <= data_in[i];

            // Set TMS high on last bit to exit shift state
            if (i == length - 1) begin
                tms <= 1'b1;
            end else begin
                tms <= 1'b0;
            end

            // Generate clock edge and capture TDO
            tck <= 1'b0;
            #1;
            data_out[i] = tdo;  // Capture on falling edge
            tck <= 1'b1;
            #1;
        end
        $display("[%0t] JTAG shift: TDI=0x%0h, TDO=0x%0h, length=%0d",
            $time, data_in, data_out, length);
    endtask

    //==========================================================================
    // TAP State Machine Tracking (for debugging/monitoring)
    //==========================================================================

    // Update TAP state based on TMS transitions
    always @(posedge tck or negedge trst) begin
        if (ENABLE_TRST && !trst) begin
            current_tap_state <= TEST_LOGIC_RESET;
        end else begin
            case (current_tap_state)
                TEST_LOGIC_RESET: current_tap_state <= tms ? TEST_LOGIC_RESET : RUN_TEST_IDLE;
                RUN_TEST_IDLE:    current_tap_state <= tms ? SELECT_DR_SCAN : RUN_TEST_IDLE;
                SELECT_DR_SCAN:   current_tap_state <= tms ? SELECT_IR_SCAN : CAPTURE_DR;
                CAPTURE_DR:       current_tap_state <= tms ? EXIT1_DR : SHIFT_DR;
                SHIFT_DR:         current_tap_state <= tms ? EXIT1_DR : SHIFT_DR;
                EXIT1_DR:         current_tap_state <= tms ? UPDATE_DR : PAUSE_DR;
                PAUSE_DR:         current_tap_state <= tms ? EXIT2_DR : PAUSE_DR;
                EXIT2_DR:         current_tap_state <= tms ? UPDATE_DR : SHIFT_DR;
                UPDATE_DR:        current_tap_state <= tms ? SELECT_DR_SCAN : RUN_TEST_IDLE;
                SELECT_IR_SCAN:   current_tap_state <= tms ? TEST_LOGIC_RESET : CAPTURE_IR;
                CAPTURE_IR:       current_tap_state <= tms ? EXIT1_IR : SHIFT_IR;
                SHIFT_IR:         current_tap_state <= tms ? EXIT1_IR : SHIFT_IR;
                EXIT1_IR:         current_tap_state <= tms ? UPDATE_IR : PAUSE_IR;
                PAUSE_IR:         current_tap_state <= tms ? EXIT2_IR : PAUSE_IR;
                EXIT2_IR:         current_tap_state <= tms ? UPDATE_IR : SHIFT_IR;
                UPDATE_IR:        current_tap_state <= tms ? SELECT_DR_SCAN : RUN_TEST_IDLE;
                default:          current_tap_state <= TEST_LOGIC_RESET;
            endcase
        end
    end

    //==========================================================================
    // Debug and Information Functions
    //==========================================================================

    // Get current TAP state as string
    function string get_tap_state_name();
        case (current_tap_state)
            TEST_LOGIC_RESET: return "Test-Logic-Reset";
            RUN_TEST_IDLE:    return "Run-Test/Idle";
            SELECT_DR_SCAN:   return "Select-DR-Scan";
            CAPTURE_DR:       return "Capture-DR";
            SHIFT_DR:         return "Shift-DR";
            EXIT1_DR:         return "Exit1-DR";
            PAUSE_DR:         return "Pause-DR";
            EXIT2_DR:         return "Exit2-DR";
            UPDATE_DR:        return "Update-DR";
            SELECT_IR_SCAN:   return "Select-IR-Scan";
            CAPTURE_IR:       return "Capture-IR";
            SHIFT_IR:         return "Shift-IR";
            EXIT1_IR:         return "Exit1-IR";
            PAUSE_IR:         return "Pause-IR";
            EXIT2_IR:         return "Exit2-IR";
            UPDATE_IR:        return "Update-IR";
            default:          return "UNKNOWN";
        endcase
    endfunction

    // Display current JTAG signal states
    task automatic display_signals();
        $display("[%0t] JTAG Signals: TCK=%b, TMS=%b, TDI=%b, TDO=%b, TDO_OEN=%b, TRST=%b, State=%s",
            $time, tck, tms, tdi, tdo, tdo_oen, trst, get_tap_state_name());
    endtask

    //==========================================================================
    // Protocol Assertions (Optional - can be disabled for performance)
    //==========================================================================

    // TRST should be stable during normal operation
    property trst_stable_during_operation;
        @(posedge tck) disable iff (!ENABLE_TRST)
            current_tap_state != TEST_LOGIC_RESET |-> $stable(trst);
    endproperty

    // TDO should only change on falling edge of TCK (in shift states)
    property tdo_changes_on_falling_tck;
        @(negedge tck)
        (current_tap_state == SHIFT_DR || current_tap_state == SHIFT_IR)
        |=>
        $stable(tdo);
        //$stable(tdo) throughout @(posedge tck);
    endproperty

    // Enable assertions (can be disabled for performance)
    `ifdef JTAG_ENABLE_ASSERTIONS
    assert_trst_stable: assert property (trst_stable_during_operation)
    else $error("JTAG: TRST changed during normal operation");

    assert_tdo_timing: assert property (tdo_changes_on_falling_tck)
    else $warning("JTAG: TDO timing may not follow standard");
    `endif

    //==========================================================================
    // Coverage Collection (Optional)
    //==========================================================================

    `ifdef JTAG_ENABLE_COVERAGE
    // Cover all TAP states
    covergroup tap_states_cg @(posedge tck);
        tap_state: coverpoint current_tap_state {
            bins all_states[] = {[TEST_LOGIC_RESET:UPDATE_IR]};
            bins reset_state = {TEST_LOGIC_RESET};
            bins shift_states = {SHIFT_DR, SHIFT_IR};
            bins update_states = {UPDATE_DR, UPDATE_IR};
        }
    endgroup

    tap_states_cg tap_states_cg_inst = new();

    // Cover state transitions
    covergroup tap_transitions_cg @(posedge tck);
        transition: coverpoint current_tap_state {
            bins reset_to_idle = (TEST_LOGIC_RESET => RUN_TEST_IDLE);
            bins idle_to_dr = (RUN_TEST_IDLE => SELECT_DR_SCAN);
            bins idle_to_ir = (RUN_TEST_IDLE => SELECT_IR_SCAN);
            bins dr_shift_sequence = (SELECT_DR_SCAN => CAPTURE_DR => SHIFT_DR => EXIT1_DR => UPDATE_DR);
            bins ir_shift_sequence = (SELECT_IR_SCAN => CAPTURE_IR => SHIFT_IR => EXIT1_IR => UPDATE_IR);
        }
    endgroup

    tap_transitions_cg tap_transitions_cg_inst = new();
    `endif

endinterface : jtag_intf
