// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP TAP FSM checker (sanity_fsm_visit_chk): the always-on invariant
// subscriber on the shared JTAG agent's monitor event stream. On every
// completed TCK cycle it checks the DUT-produced one-hot TAP state
// (dtp_tb_if.tap_state, a DUT top-level output) against the VIP's IEEE
// 1149.1 next-state reference model, and accumulates the closure of the
// states and legal edges the DUT took;
// scenario tests that require closure (VPLAN 0.1) call check_fsm_closure(),
// which records CHK-TAP-VISIT-ALL, at the end of each pass and
// clear_closure() before the next. report_evidence() turns the run into one
// aggregate CHK-TAP-STATE record through the env's evidence recorder.
// trst_n() reports the TRST_N level of the last TRST edge on the pin, which
// the scenario layer samples under a power-on reset.
//
// Events arrive on the TCK falling edge (monitor contract), when the
// rising-edge state transition has settled, so sampling tb_vif.tap_state
// inside write() is race-free. The DUT one-hot encoding's bit index equals
// the VIP enum value (IEEE state numbering 0..15). The cocotb counterparts
// are the per-step CHK-TAP-STATE of the checker dtp_jtag_base_test_seq
// attaches (tms_expect) and CHK-TAP-VISIT-ALL in seq_lib/dtp_sanity_test_seq.py.

class dtp_tap_fsm_checker extends ocah_subscriber #(ocah_jtag_event);
  `uvm_component_utils(dtp_tap_fsm_checker)

  // Handed by dtp_env: the TAP-state observable.
  virtual dtp_tb_if tb_vif;

  // JTAG scenarios must show TCK activity (a zero-cycle CHK-TAP-STATE is
  // vacuous and fails). The cross-trigger group drives no JTAG at all and
  // clears this through the env cfg; any TCK activity that does occur is
  // still checked per cycle and recorded.
  bit require_activity = 1'b1;

  protected ocah_jtag_tap_state_e m_model = OCAH_JTAG_TEST_LOGIC_RESET;
  protected bit m_state_seen [16];
  protected bit m_edge_seen  [16][2];
  protected int unsigned m_cycles;
  protected int unsigned m_mismatches;
  // Power-on reset forces Test-Logic-Reset without a TCK edge or a TRST
  // event; the tb_top assertion counter marks it, and the model
  // re-baselines before the next step is judged.
  protected logic [31:0] m_por_count = '0;
  // TRST_N after the last TRST edge; the JTAG driver idles it high.
  protected bit m_trst_n = 1'b1;

  function new(string name = "dtp_tap_fsm_checker", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
  endfunction

  function void write(ocah_jtag_event t);
    ocah_jtag_tap_state_e expected;
    logic [15:0] expected_onehot;

    if (t.kind == OCAH_JTAG_EV_TRST) begin
      // Asynchronous TAP reset: re-baseline the model (reset-aware flush).
      m_trst_n = t.trst_n;
      if (t.trst_asserted) m_model = OCAH_JTAG_TEST_LOGIC_RESET;
      return;
    end

    if (tb_vif.por_assert_count !== m_por_count) begin
      m_por_count = tb_vif.por_assert_count;
      m_model = OCAH_JTAG_TEST_LOGIC_RESET;
    end

    if (t.trst_n === 1'b0) expected = OCAH_JTAG_TEST_LOGIC_RESET;
    else expected = ocah_jtag_next_state(m_model, t.tms);
    expected_onehot = 16'h1 << int'(expected);
    m_cycles++;

    if (!dtp_tap_state_is_valid(tb_vif.tap_state)) begin
      m_mismatches++;
      `uvm_error(
          "sanity_fsm_visit_chk",
          $sformatf(
              "step %0d: TAP state not a valid one-hot IEEE 1149.1 state: got 0x%04h (from %s, tms=%0b)",
              t.index, tb_vif.tap_state, m_model.name(), t.tms))
    end else if (tb_vif.tap_state !== expected_onehot) begin
      m_mismatches++;
      `uvm_error(
          "sanity_fsm_visit_chk",
          $sformatf(
              "step %0d: illegal TAP transition: from %s with tms=%0b expected %s (0x%04h), got 0x%04h",
              t.index, m_model.name(), t.tms, expected.name(), expected_onehot, tb_vif.tap_state))
    end else begin
      // Closure counts a state or a legal edge only once the DUT took it.
      m_state_seen[int'(expected)] = 1'b1;
      if (t.trst_n !== 1'b0) m_edge_seen[int'(m_model)][t.tms] = 1'b1;
    end

    m_model = expected;
  endfunction

  // The TRST_N level of the last TRST edge the monitor published.
  function bit trst_n();
    return m_trst_n;
  endfunction

  // One aggregate named-evidence record for the always-on per-cycle
  // reference-model comparison (each mismatch already errored inline with
  // the exact broken transition).
  function void report_evidence();
    if (evidence == null) return;
    if (!require_activity && m_cycles == 0) return;
    void'(evidence.expect_true(
        "CHK-TAP-STATE",
        (m_cycles > 0) && (m_mismatches == 0),
        $sformatf(
            "tck_cycles=%0d mismatches=%0d", m_cycles, m_mismatches)
    ));
  endfunction

  // Scenario-invoked closure gate: all 16 states visited AND all 32 legal
  // edges taken since the last clear_closure(), recorded as
  // CHK-TAP-VISIT-ALL. Only VPLAN 0.1-style scenarios demand full closure.
  function void check_fsm_closure(string context_s = "");
    int unsigned states_hit = 0, edges_hit = 0;
    ocah_jtag_tap_state_e state;
    string missing_states = "", missing_edges = "";
    foreach (m_state_seen[s]) begin
      state = ocah_jtag_tap_state_e'(s);
      if (m_state_seen[s]) states_hit++;
      else begin
        `uvm_error("sanity_fsm_visit_chk", $sformatf("TAP state never visited: %s", state.name()))
        missing_states = {missing_states, missing_states.len() ? "," : "", state.name()};
      end
    end
    foreach (m_edge_seen[s, t]) begin
      state = ocah_jtag_tap_state_e'(s);
      if (m_edge_seen[s][t]) edges_hit++;
      else begin
        `uvm_error("sanity_fsm_visit_chk", $sformatf(
                   "legal TAP transition never taken: %s with tms=%0d", state.name(), t))
        missing_edges = {
          missing_edges, missing_edges.len() ? "," : "", $sformatf("%s/tms=%0d", state.name(), t)
        };
      end
    end
    `uvm_info("sanity_fsm_visit_chk", $sformatf(
              "FSM closure: %0d/16 states visited, %0d/32 legal edges taken", states_hit, edges_hit
              ), UVM_LOW)
    if (evidence == null) return;
    void'(evidence.expect_equal(
        "CHK-TAP-VISIT-ALL",
        64'(states_hit),
        64'd16,
        $sformatf(
            "IEEE 1149.1 TAP states visited missing=%s %s",
            missing_states.len() ? missing_states : "none",
            context_s)
    ));
    void'(evidence.expect_equal(
        "CHK-TAP-VISIT-ALL",
        64'(edges_hit),
        64'd32,
        $sformatf(
            "IEEE 1149.1 legal TAP transitions taken missing=%s %s",
            missing_edges.len() ? missing_edges : "none",
            context_s)
    ));
  endfunction

  // Start a new closure window; the reference model keeps tracking the DUT.
  function void clear_closure();
    foreach (m_state_seen[s]) m_state_seen[s] = 1'b0;
    foreach (m_edge_seen[s, t]) m_edge_seen[s][t] = 1'b0;
  endfunction

endclass : dtp_tap_fsm_checker
