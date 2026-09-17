// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base virtual sequence of every SMU scenario: runs on smu_virtual_sequencer
// and starts reusable operation sequences on the handle each step needs
// (primary-TAP JTAG operations on p_sequencer.m_jtag_seqr). It never
// touches a driver or a VIP virtual interface; the written exceptions are
// tb_vif (the SMU-local TB interface: power-good and cold reset, reset
// observables) and dtp_tb_vif (the embedded DTP's TAP-state and decoded-IR
// observables), both plumbed by the base test. TRST is driven through the
// VIP's TRST operation like every other TAP operation.
//
// The scenario layer tracks the TAP state itself (m_tap_state) and hands it
// to every JTAG operation, since the VIP sequence's model lives inside the
// operation sequence. On top of the operations it keeps the SMU-local
// helpers: TAP-state checks against the DTP one-hot observable, bounded
// waits (TCK-stepped or ref-clock polled) that record one TIMEOUT-PATH line
// each with a finite bound and the last state seen, the TRST and power-good
// controls with the re-bring-up wait a power-on reset needs before the next
// pass, ordered step marks for the non-vacuity fence, and the per-pass named
// evidence (CHK-*) through the protocol-neutral ocah_checker, attached with
// the scenario's required IDs and finalized after the scenario so a silently
// skipped check cannot report PASS. Every draw in a pass follows
// seed_scenario_rng() (first statement of body()). The cocotb twin is the
// helper layer of seq_lib/smu_dtp_jtag_smoke_test_seq.py.

class smu_base_test_seq extends ocah_sequence;
  `uvm_object_utils(smu_base_test_seq)
  `uvm_declare_p_sequencer(smu_virtual_sequencer)

  localparam int unsigned IrWidth = SmuPtapIrWidth;
  // TCK cycles TRST stays released before the model re-syncs (cocotb
  // smoke sequence: four ref cycles after TRST release; one TCK period
  // spans at least that at the choice sets).
  localparam int unsigned TrstReleaseRefCycles = 4;

  // Plumbed by the test before start(): the SMU TB interface, the embedded
  // DTP TB interface, and the two cfg levels.
  virtual smu_tb_if tb_vif;
  virtual dtp_tb_if dtp_tb_vif;
  smu_test_cfg      test_cfg;
  smu_env_cfg       env_cfg;
  // Env-owned aggregate JTAG recorder (TAP reset evidence lands there too).
  ocah_jtag_checker evidence;

  // Per-pass named evidence.
  ocah_checker m_check;

  // TAP state tracked across operations (each operation re-syncs the VIP
  // model from it and hands the landing state back).
  protected ocah_jtag_tap_state_e m_tap_state = OCAH_JTAG_TEST_LOGIC_RESET;
  // TRST level tracked across operations (released at construction).
  protected bit m_trst_asserted = 1'b0;

  // Bounded-wait inventory of the pass: one line per wait site, and the
  // count that expired (an expiry is also an error at the site).
  protected string       m_timeout_paths[$];
  protected int unsigned m_timeouts_expired;
  // Ordered step marks (simulation time) for the non-vacuity fence.
  protected string       m_step_order[$];
  protected realtime     m_step_time[string];

  function new(string name = "smu_base_test_seq");
    super.new(name);
  endfunction

  // ------------------------------------------------------------------
  // Evidence plumbing.
  // ------------------------------------------------------------------

  function void attach_evidence(string required_ids[$]);
    if (tb_vif == null || dtp_tb_vif == null || test_cfg == null || env_cfg == null)
      `uvm_fatal(get_type_name(), "tb_vif/dtp_tb_vif/test_cfg/env_cfg not plumbed by the test")
    m_check = ocah_checker::type_id::create({get_name(), ".scenario"});
    m_check.name_tag     = "smu_scenario";
    m_check.required_ids = required_ids;
    m_timeout_paths.delete();
    m_timeouts_expired = 0;
    m_step_order.delete();
    m_step_time.delete();
  endfunction

  function void finalize_evidence();
    if (m_check == null) `uvm_fatal(get_type_name(), "evidence checker was never attached")
    m_check.finalize(1'b1);
  endfunction

  // Record one named evidence comparison (uvm_error on mismatch).
  function void check_evidence(string check_id, string name, bit [63:0] observed,
                               bit [63:0] expected, string context_s = "");
    void'(m_check.expect_equal(check_id, observed, expected,
                               {name, context_s.len() ? " " : "", context_s}));
  endfunction

  // ------------------------------------------------------------------
  // Step marks and the bounded-wait inventory.
  // ------------------------------------------------------------------

  // Mark the start of a scenario step (cocotb STEP <id> parity).
  function void mark_step(string step_id, string detail);
    m_step_order.push_back(step_id);
    m_step_time[step_id] = $realtime;
    log_step(step_id, detail);
  endfunction

  // Consecutive step marks in non-decreasing simulation time: the ordered
  // fence of the cocotb scenario, whose wall-clock marks always advance; in
  // simulation a step that consumes no time shares the time of the next
  // mark, so the fence is order plus non-decreasing time.
  function int unsigned ordered_step_deltas();
    int unsigned ordered = 0;
    for (int unsigned i = 1; i < m_step_order.size(); i++)
    if (m_step_time[m_step_order[i]] >= m_step_time[m_step_order[i-1]]) ordered++;
    return ordered;
  endfunction

  function int unsigned timeout_path_count();
    return m_timeout_paths.size();
  endfunction

  function int unsigned timeouts_expired();
    return m_timeouts_expired;
  endfunction

  function void log_timeout_paths();
    foreach (m_timeout_paths[i])
      `uvm_info(get_type_name(), {"TIMEOUT-PATH ", m_timeout_paths[i]}, UVM_LOW)
  endfunction

  protected function void record_timeout_path(string label, int unsigned bound, bit ok,
                                              bit [15:0] last);
    m_timeout_paths.push_back(
        $sformatf("%s: bound=%0d %s last=0x%04h", label, bound, ok ? "ok" : "EXPIRED", last));
    if (!ok) begin
      m_timeouts_expired++;
      `uvm_error(get_type_name(), $sformatf("TIMEOUT %s: bound=%0d last_state=0x%04h", label,
                                            bound, last))
    end
  endfunction

  // ------------------------------------------------------------------
  // JTAG operations: one reusable sequence per operation on the primary
  // TAP sequencer.
  // ------------------------------------------------------------------

  function ocah_jtag_tap_state_e current_state();
    return m_tap_state;
  endfunction

  // Re-align tracking after externally driven TAP movement (POR, TRST).
  function void sync_model(ocah_jtag_tap_state_e state);
    m_tap_state = state;
  endfunction

  task tap_reset_op();
    smu_jtag_tap_reset_seq op = smu_jtag_tap_reset_seq::type_id::create("tap_reset");
    run_jtag_op(op);
  endtask

  // One raw TCK step from any state.
  task step(bit tms, bit tdi = 1'b0);
    bit tms_bits[] = new[1];
    bit tdi_bits[] = new[1];
    bit tdo_bits[];
    tms_bits[0] = tms;
    tdi_bits[0] = tdi;
    raw_walk(tms_bits, tdi_bits, tdo_bits);
  endtask

  // Raw TMS/TDI walk returning the TDO of every cycle.
  task raw_walk(input bit tms_bits[], input bit tdi_bits[], output bit tdo_bits[]);
    smu_jtag_tms_walk_seq op = smu_jtag_tms_walk_seq::type_id::create("tms_walk");
    op.tms_bits = tms_bits;
    op.tdi_bits = tdi_bits;
    run_jtag_op(op);
    tdo_bits = op.tdo_bits;
  endtask

  task goto_state(ocah_jtag_tap_state_e target);
    smu_jtag_goto_state_seq op = smu_jtag_goto_state_seq::type_id::create("goto_state");
    op.target_state = target;
    run_jtag_op(op);
  endtask

  task ir_scan(input bit [63:0] value, input int unsigned width, output bit [63:0] captured);
    smu_jtag_ir_scan_seq op = smu_jtag_ir_scan_seq::type_id::create("ir_scan");
    op.value = value;
    op.width = width;
    run_jtag_op(op);
    captured = op.captured;
  endtask

  task dr_scan(input bit [63:0] pattern, input int unsigned width, output bit [63:0] observed);
    smu_jtag_dr_scan_seq op = smu_jtag_dr_scan_seq::type_id::create("dr_scan");
    op.pattern = pattern;
    op.width   = width;
    run_jtag_op(op);
    observed = op.observed;
  endtask

  // Hand the tracked state to an operation, start it on the JTAG agent
  // sequencer, and take the landing state back.
  protected task run_jtag_op(smu_jtag_op_seq op);
    if (p_sequencer.m_jtag_seqr == null)
      `uvm_fatal(get_type_name(), "smu_virtual_sequencer.m_jtag_seqr is null")
    op.entry_state = m_tap_state;
    op.start(p_sequencer.m_jtag_seqr, this);
    m_tap_state = op.current_state();
  endtask

  // ------------------------------------------------------------------
  // TAP helpers and checks on the embedded DTP observables.
  // ------------------------------------------------------------------

  // Plain PTAP instruction load from Run-Test/Idle, back to Run-Test/Idle.
  task load_ir(bit [IrWidth-1:0] instr);
    bit [63:0] captured;
    `uvm_info(get_type_name(), $sformatf("IR scan: loading 0x%02h (%0d bits)", instr, IrWidth),
              UVM_MEDIUM)
    ir_scan(64'(instr), IrWidth, captured);
  endtask

  // The DUT one-hot TAP state (dtp_tb_if.tap_state).
  function bit [15:0] tap_state();
    return dtp_tb_vif.tap_state;
  endfunction

  // One-hot encoding of a VIP TAP state.
  static function bit [15:0] onehot(ocah_jtag_tap_state_e state);
    return 16'h1 << int'(state);
  endfunction

  // `checker_tag` because bare `checker` is an IEEE 1800 reserved word.
  function void check_state(ocah_jtag_tap_state_e expected, string checker_tag, string what);
    if (tap_state() !== onehot(expected))
      `uvm_error(checker_tag, $sformatf(
                 "%s: expected TAP state %s (0x%04h), got 0x%04h",
                 what,
                 expected.name(),
                 onehot(
                     expected
                 ),
                 tap_state()
                 ))
    else
      `uvm_info(checker_tag, $sformatf("%s: TAP state %s as expected", what, expected.name()),
                UVM_MEDIUM)
  endfunction

  // TAP reset: TRST pulse via the driver -> Test-Logic-Reset, recorded in
  // the aggregate JTAG evidence.
  task tap_reset();
    `uvm_info(get_type_name(), "asserting TRST for TAP reset", UVM_MEDIUM)
    tap_reset_op();
    if (evidence != null) void'(evidence.check_reset_to_tlr(tap_state(), "after TRST release"));
    check_state(OCAH_JTAG_TEST_LOGIC_RESET, "smu_tap_reset_chk", "after TRST release");
  endtask

  // Bounded TCK-stepped confirmation of a TAP state (cocotb _wait_state
  // parity): already there records an ok path; otherwise TCK steps with
  // `hold_tms` until the observable matches or test_cfg.bound_tck expires.
  // Returns the last state seen.
  task confirm_state_tck(input ocah_jtag_tap_state_e expected, input string label,
                         input bit hold_tms, output bit [15:0] last);
    int unsigned bound = test_cfg.bound_tck;
    last = tap_state();
    for (int unsigned i = 0; i < bound; i++) begin
      if (last === onehot(expected)) begin
        record_timeout_path(label, bound, 1'b1, last);
        return;
      end
      step(hold_tms);
      last = tap_state();
    end
    record_timeout_path(label, bound, last === onehot(expected), last);
  endtask

  // Bounded ref-clock poll of a TAP state without TCK activity (the
  // asynchronous TRST and power-on paths). Returns the last state seen.
  task wait_tap_eq_ref(input ocah_jtag_tap_state_e expected, input string label,
                       output bit [15:0] last);
    int unsigned bound = test_cfg.bound_ref;
    last = tap_state();
    for (int unsigned i = 0; i < bound; i++) begin
      if (last === onehot(expected)) begin
        record_timeout_path(label, bound, 1'b1, last);
        return;
      end
      wait_ref_cycles(1);
      last = tap_state();
    end
    record_timeout_path(label, bound, last === onehot(expected), last);
  endtask

  // Hold or release TRST (`value` is the trst_n level, 0 = asserted)
  // through the VIP TRST operation, stepping TCK with TMS=1 so the env's
  // per-cycle FSM checker prediction (TLR self-loop) stays valid while the
  // asynchronous reset dominates.
  task set_trst(bit value, int unsigned cycles = 1);
    smu_jtag_trst_seq op = smu_jtag_trst_seq::type_id::create("set_trst");
    op.asserted   = (value == 1'b0);
    op.tck_cycles = cycles > 0 ? cycles : 1;
    run_jtag_op(op);
    m_trst_asserted = op.asserted;
    if (op.asserted && evidence != null) evidence.reset_model();
  endtask

  // Release TRST held by set_trst(0): no TCK activity while the DTP TAP
  // settles, then the tracked state is Test-Logic-Reset.
  task release_trst();
    smu_jtag_trst_seq op = smu_jtag_trst_seq::type_id::create("release_trst");
    op.asserted   = 1'b0;
    op.tck_cycles = 0;
    run_jtag_op(op);
    m_trst_asserted = 1'b0;
    wait_ref_cycles(TrstReleaseRefCycles);
    sync_model(OCAH_JTAG_TEST_LOGIC_RESET);
  endtask

  function bit trst_released();
    return !m_trst_asserted;
  endfunction

  // Drop power-good: the SMC reset unit re-asserts every reset and the
  // embedded DTP sees its power-on reset (pwr_on_rst_ni = powergood_stable).
  task drop_powergood();
    `uvm_info(get_type_name(), "dropping power-good (power-on reset path)", UVM_MEDIUM)
    tb_vif.powergood <= 1'b0;
  endtask

  // Restore power-good and re-establish the released-reset baseline the
  // next pass starts from: the cocotb recovery wait, then the same bounded
  // reset-release polls the base test walks at bring-up.
  task restore_powergood();
    tb_vif.powergood <= 1'b1;
    wait_ref_cycles(test_cfg.por_recover_ref_cycles);
    tb_vif.rst_cold_n <= 1'b1;
    sync_model(OCAH_JTAG_TEST_LOGIC_RESET);
    if (evidence != null) evidence.reset_model();
    wait_resets_released();
  endtask

  // Bounded polls of the cold-stable and primary reset releases
  // (test_cfg.reset_release_timeout_cycles each); expiry is an error.
  task wait_resets_released();
    bit reached;
    wait_observable_high("rst_cold_stable_ref_clk_n", reached);
    wait_observable_high("rst_primary_smc_clk_n", reached);
  endtask

  protected function bit observable(string which);
    case (which)
      "rst_cold_stable_ref_clk_n": return tb_vif.rst_cold_stable_ref_clk_n === 1'b1;
      "rst_primary_smc_clk_n":     return tb_vif.rst_primary_smc_clk_n === 1'b1;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown observable %s", which))
        return 1'b0;
      end
    endcase
  endfunction

  // Bounded poll of one reset observable on the ref clock; 0 (and an
  // error) on expiry.
  protected task wait_observable_high(string which, output bit reached);
    int unsigned cycles = 0;
    while (!observable(
        which
    )) begin
      if (cycles >= test_cfg.reset_release_timeout_cycles) begin
        `uvm_error(get_type_name(), $sformatf("%s never asserted within %0d ref clocks", which,
                                              cycles))
        reached = 1'b0;
        return;
      end
      wait_ref_cycles(1);
      cycles++;
    end
    `uvm_info(get_type_name(), $sformatf("%s high after %0d ref clocks", which, cycles), UVM_MEDIUM)
    reached = 1'b1;
  endtask

  // ------------------------------------------------------------------
  // Clock-domain waits (periods from the env cfg the test plumbed); the
  // bring-up ladder belongs to the base test.
  // ------------------------------------------------------------------

  task wait_ref_cycles(int unsigned cycles);
    #(cycles * env_cfg.ref_clk_period_ns * 1ns);
  endtask

  task wait_smu_cycles(int unsigned cycles);
    #(cycles * env_cfg.clk_period_ns * 1ns);
  endtask

endclass : smu_base_test_seq
