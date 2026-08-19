// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP TAP FSM checker (sanity_fsm_visit_chk): subscribes to the shared JTAG
// agent's monitor event stream and, on every completed TCK cycle, checks the
// DUT-produced one-hot TAP state (dtp_tb_if.tap_state, a DUT top-level
// output) against the VIP's IEEE 1149.1 next-state reference model. Also
// accumulates state/edge closure; scenario tests that require closure (VPLAN
// 0.1) call check_fsm_closure() after their stimulus completes.
//
// Events arrive on the TCK falling edge (monitor contract), when the
// rising-edge state transition has settled, so sampling tb_vif.tap_state
// inside write() is race-free. The DUT one-hot encoding's bit index equals
// the VIP enum value (IEEE state numbering 0..15).

class dtp_tap_fsm_checker extends uvm_subscriber #(ocah_jtag_event);
    `uvm_component_utils(dtp_tap_fsm_checker)

    virtual dtp_tb_if tb_vif;

    // Shared named-evidence sink (set by the env); report_evidence() turns
    // the per-cycle legality result into one aggregate CHK-TAP-STATE record.
    ocah_jtag_checker m_evidence;

    protected ocah_jtag_tap_state_e m_model = OCAH_JTAG_TEST_LOGIC_RESET;
    protected bit m_state_seen [16];
    protected bit m_edge_seen  [16][2];
    protected int unsigned m_cycles;
    protected int unsigned m_mismatches;

    function new(string name = "dtp_tap_fsm_checker", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if (tb_vif == null &&
            !uvm_config_db#(virtual dtp_tb_if)::get(this, "", "tb_vif", tb_vif))
            `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not found")
    endfunction

    function void write(ocah_jtag_event t);
        ocah_jtag_tap_state_e expected;
        logic [15:0] expected_onehot;

        if (t.kind == OCAH_JTAG_EV_TRST) begin
            // Asynchronous TAP reset: re-baseline the model (reset-aware flush).
            if (t.trst_asserted) begin
                m_model = OCAH_JTAG_TEST_LOGIC_RESET;
                m_state_seen[OCAH_JTAG_TEST_LOGIC_RESET] = 1'b1;
            end
            return;
        end

        if (t.trst_n === 1'b0) begin
            expected = OCAH_JTAG_TEST_LOGIC_RESET;
        end else begin
            expected = ocah_jtag_next_state(m_model, t.tms);
            // Record the legal edge taken (deterministic closure bookkeeping).
            m_edge_seen[int'(m_model)][t.tms] = 1'b1;
        end
        expected_onehot = 16'h1 << int'(expected);
        m_cycles++;

        if (!is_onehot(tb_vif.tap_state) || !is_valid_tap_state(tb_vif.tap_state)) begin
            m_mismatches++;
            `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "step %0d: TAP state not a valid one-hot IEEE 1149.1 state: got 0x%04h (from %s, tms=%0b)",
                t.index, tb_vif.tap_state, m_model.name(), t.tms))
        end
        else if (tb_vif.tap_state !== expected_onehot) begin
            m_mismatches++;
            `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "step %0d: illegal TAP transition: from %s with tms=%0b expected %s (0x%04h), got 0x%04h",
                t.index, m_model.name(), t.tms, expected.name(), expected_onehot, tb_vif.tap_state))
        end

        m_model = expected;
        m_state_seen[int'(m_model)] = 1'b1;
    endfunction

    // One aggregate named-evidence record for the always-on per-cycle
    // reference-model comparison (each mismatch already errored inline with
    // the exact broken transition).
    function void report_evidence();
        if (m_evidence == null) return;
        void'(m_evidence.expect_true("CHK-TAP-STATE",
            (m_cycles > 0) && (m_mismatches == 0),
            $sformatf("tck_cycles=%0d mismatches=%0d", m_cycles, m_mismatches)));
    endfunction

    // Scenario-invoked closure gate: all 16 states visited AND all 32 legal
    // edges taken. Not run unconditionally — only VPLAN 0.1-style scenarios
    // demand full closure.
    function void check_fsm_closure();
        int unsigned states_hit = 0, edges_hit = 0;
        ocah_jtag_tap_state_e state;
        foreach (m_state_seen[s]) begin
            state = ocah_jtag_tap_state_e'(s);
            if (m_state_seen[s]) states_hit++;
            else `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "TAP state never visited: %s", state.name()))
        end
        foreach (m_edge_seen[s, t]) begin
            state = ocah_jtag_tap_state_e'(s);
            if (m_edge_seen[s][t]) edges_hit++;
            else `uvm_error("sanity_fsm_visit_chk", $sformatf(
                "legal TAP transition never taken: %s with tms=%0d",
                state.name(), t))
        end
        `uvm_info("sanity_fsm_visit_chk", $sformatf(
            "FSM closure: %0d/16 states visited, %0d/32 legal edges taken",
            states_hit, edges_hit), UVM_LOW)
    endfunction

endclass : dtp_tap_fsm_checker
