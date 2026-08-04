// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base JTAG sequence: pin-level TAP driving tasks, IEEE 1149.1 next-state
// reference model, FSM state/edge-closure bookkeeping, and the three VPLAN
// 0.1 checkers (sanity_fsm_visit_chk / sanity_bypass_latency_chk /
// sanity_scan_path_chk). Compiled into dtp_seq_lib_pkg.

class dtp_jtag_base_seq extends uvm_sequence;
    `uvm_object_utils(dtp_jtag_base_seq)

    localparam time TckHalf = 50ns;   // 10 MHz TCK, bit-banged
    localparam int unsigned IrWidth = 6;

    // Plumbed by the test from dtp_uvm_env before start(null).
    virtual ocah_jtag_if jtag_vif;
    virtual dtp_tb_if    tb_vif;

    // FSM reference model + coverage bookkeeping (sanity_fsm_visit_chk).
    tap_state_e  model_state;
    bit          state_seen [16];
    bit          edge_seen  [16][2];
    int unsigned step_num;   // global TCK-cycle index, for debuggable error context

    function new(string name = "dtp_jtag_base_seq");
        super.new(name);
    endfunction

    // -----------------------------------------------------------------
    // IEEE 1149.1 next-state reference table (one-hot in, one-hot out)
    // -----------------------------------------------------------------
    static function tap_state_e next_state(tap_state_e cur, bit tms);
        case (cur)
            TEST_LOGIC_RESET: return tms ? TEST_LOGIC_RESET : RUN_TEST_IDLE;
            RUN_TEST_IDLE:    return tms ? SELECT_DR_SCAN   : RUN_TEST_IDLE;
            SELECT_DR_SCAN:   return tms ? SELECT_IR_SCAN   : CAPTURE_DR;
            CAPTURE_DR:       return tms ? EXIT1_DR         : SHIFT_DR;
            SHIFT_DR:         return tms ? EXIT1_DR         : SHIFT_DR;
            EXIT1_DR:         return tms ? UPDATE_DR        : PAUSE_DR;
            PAUSE_DR:         return tms ? EXIT2_DR         : PAUSE_DR;
            EXIT2_DR:         return tms ? UPDATE_DR        : SHIFT_DR;
            UPDATE_DR:        return tms ? SELECT_DR_SCAN   : RUN_TEST_IDLE;
            SELECT_IR_SCAN:   return tms ? TEST_LOGIC_RESET : CAPTURE_IR;
            CAPTURE_IR:       return tms ? EXIT1_IR         : SHIFT_IR;
            SHIFT_IR:         return tms ? EXIT1_IR         : SHIFT_IR;
            EXIT1_IR:         return tms ? UPDATE_IR        : PAUSE_IR;
            PAUSE_IR:         return tms ? EXIT2_IR         : PAUSE_IR;
            EXIT2_IR:         return tms ? UPDATE_IR        : SHIFT_IR;
            UPDATE_IR:        return tms ? SELECT_DR_SCAN   : RUN_TEST_IDLE;
            default:          return TEST_LOGIC_RESET;
        endcase
    endfunction

    static function int state_idx(tap_state_e s);
        return $clog2(int'(s));
    endfunction

    // -----------------------------------------------------------------
    // One TCK cycle: drive tms/tdi at TCK low, sample TDO just before the
    // rising edge (stable since the DUT's previous falling edge), then
    // pulse TCK. After the cycle, check the DUT state against the model.
    // -----------------------------------------------------------------
    task tck_cycle(bit tms, bit tdi, output bit tdo_s);
        tap_state_e expected;
        jtag_vif.tms <= tms;
        jtag_vif.tdi <= tdi;
        #(TckHalf);
        tdo_s = jtag_vif.tdo;
        jtag_vif.tck <= 1'b1;
        #(TckHalf);
        jtag_vif.tck <= 1'b0;

        if (jtag_vif.trst_n === 1'b0) begin
            expected = TEST_LOGIC_RESET;
        end else begin
            expected = next_state(model_state, tms);
            // Record the legal edge taken (sanity_fsm_visit_chk closure).
            edge_seen[state_idx(model_state)][tms] = 1'b1;
        end

        if (!is_onehot(tb_vif.tap_state) || !is_valid_tap_state(tb_vif.tap_state))
            `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "step %0d: TAP state not a valid one-hot IEEE 1149.1 state: got 0x%04h (from %s, tms=%0b)",
                step_num, tb_vif.tap_state, model_state.name(), tms))
        else if (tb_vif.tap_state !== expected)
            `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "step %0d: illegal TAP transition: from %s with tms=%0b expected %s (0x%04h), got 0x%04h",
                step_num, model_state.name(), tms, expected.name(), expected, tb_vif.tap_state))

        step_num++;
        model_state = expected;
        state_seen[state_idx(model_state)] = 1'b1;
    endtask

    task step(bit tms, bit tdi = 1'b0);
        bit unused;
        tck_cycle(tms, tdi, unused);
    endtask

    function void check_state(tap_state_e expected, string checker, string what);
        if (tb_vif.tap_state !== expected)
            `uvm_error(checker, $sformatf(
                "%s: expected TAP state %s (0x%04h), got 0x%04h",
                what, expected.name(), expected, tb_vif.tap_state))
        else
            `uvm_info(checker, $sformatf("%s: TAP state %s as expected", what, expected.name()),
                      UVM_MEDIUM)
    endfunction

    // -----------------------------------------------------------------
    // Power-on/system reset sequencing, then pin idle values.
    // -----------------------------------------------------------------
    task sys_reset();
        `uvm_info(get_type_name(), "sequencing power-on and system resets", UVM_MEDIUM)
        tb_vif.por_rst_n <= 1'b0;
        tb_vif.sys_rst_n <= 1'b0;
        jtag_vif.trst_n  <= 1'b0;
        jtag_vif.tck     <= 1'b0;
        jtag_vif.tms     <= 1'b1;
        jtag_vif.tdi     <= 1'b0;
        #200ns;
        tb_vif.por_rst_n <= 1'b1;
        #100ns;
        tb_vif.sys_rst_n <= 1'b1;
        #100ns;
    endtask

    // TAP reset: async TRST low -> Test-Logic-Reset, then release.
    task tap_reset();
        `uvm_info(get_type_name(), "asserting TRST for TAP reset", UVM_MEDIUM)
        jtag_vif.trst_n <= 1'b0;
        repeat (3) step(1'b1);
        jtag_vif.trst_n <= 1'b1;
        model_state = TEST_LOGIC_RESET;
        state_seen[state_idx(TEST_LOGIC_RESET)] = 1'b1;
        #(2 * TckHalf);
        check_state(TEST_LOGIC_RESET, "sanity_fsm_visit_chk", "after TRST release");
    endtask

    // Return to Test-Logic-Reset from any state via five TMS=1 cycles.
    task goto_tlr_via_tms();
        repeat (5) step(1'b1);
        check_state(TEST_LOGIC_RESET, "sanity_scan_path_chk", "after 5x TMS=1");
    endtask

    // -----------------------------------------------------------------
    // IR scan from Run-Test/Idle (LSB-first), back to Run-Test/Idle.
    // -----------------------------------------------------------------
    task load_ir(bit [IrWidth-1:0] instr);
        `uvm_info(get_type_name(), $sformatf("IR scan: loading 0x%02h (%0d bits)", instr, IrWidth),
                  UVM_MEDIUM)
        step(1'b1);                                    // RTI        -> Select-DR
        step(1'b1);                                    // Select-DR  -> Select-IR
        step(1'b0);                                    // Select-IR  -> Capture-IR
        step(1'b0);                                    // Capture-IR -> Shift-IR
        for (int i = 0; i < IrWidth; i++)
            step(i == IrWidth - 1, instr[i]);          // last bit: Shift-IR -> Exit1-IR
        step(1'b1);                                    // Exit1-IR   -> Update-IR
        step(1'b0);                                    // Update-IR  -> RTI
        check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after IR scan");
    endtask

    // -----------------------------------------------------------------
    // DR scan from Run-Test/Idle (LSB-first), returning observed TDO.
    // -----------------------------------------------------------------
    task shift_dr(input bit [63:0] pattern, input int unsigned width,
                  output bit [63:0] observed);
        observed = '0;
        step(1'b1);                                    // RTI        -> Select-DR
        step(1'b0);                                    // Select-DR  -> Capture-DR
        step(1'b0);                                    // Capture-DR -> Shift-DR
        for (int i = 0; i < width; i++) begin
            bit tdo_s;
            tck_cycle(i == width - 1, pattern[i], tdo_s);
            observed[i] = tdo_s;                       // last bit: Shift-DR -> Exit1-DR
        end
        step(1'b1);                                    // Exit1-DR   -> Update-DR
        step(1'b0);                                    // Update-DR  -> RTI
        check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after DR scan");
    endtask

    // -----------------------------------------------------------------
    // sanity_bypass_latency_chk: BYPASS (IR 0x00) => exactly 1-TCK
    // TDI-to-TDO delay: observed = {pattern[width-2:0], 1'b0} LSB-first.
    // -----------------------------------------------------------------
    task check_bypass_latency(bit [63:0] pattern, int unsigned width);
        bit [63:0] observed, expected;
        expected = ((pattern << 1) & ((width < 64) ? ((64'h1 << width) - 1) : '1));
        shift_dr(pattern, width, observed);
        if (observed !== expected)
            `uvm_error("sanity_bypass_latency_chk", $sformatf(
                "BYPASS TDI-to-TDO latency not 1 TCK: pattern=0x%016h width=%0d expected=0x%016h observed=0x%016h",
                pattern, width, expected, observed))
        else
            `uvm_info("sanity_bypass_latency_chk", $sformatf(
                "BYPASS 1-TCK latency OK: pattern=0x%016h width=%0d observed=0x%016h",
                pattern, width, observed), UVM_MEDIUM)
    endtask

    // Final closure: all 16 states visited AND all 32 legal edges taken.
    function void check_fsm_closure();
        int unsigned states_hit = 0, edges_hit = 0;
        foreach (state_seen[s]) begin
            if (state_seen[s]) states_hit++;
            else `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "TAP state never visited: %s", tap_state_e'(16'h1 << s).name()))
        end
        foreach (edge_seen[s, t]) begin
            if (edge_seen[s][t]) edges_hit++;
            else `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "legal TAP transition never taken: %s with tms=%0d",
                tap_state_e'(16'h1 << s).name(), t))
        end
        `uvm_info("sanity_fsm_visit_chk", $sformatf(
            "FSM closure: %0d/16 states visited, %0d/32 legal edges taken",
            states_hit, edges_hit), UVM_LOW)
    endfunction

endclass : dtp_jtag_base_seq
