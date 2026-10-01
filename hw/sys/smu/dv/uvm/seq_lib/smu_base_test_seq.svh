// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base virtual sequence of every SMU scenario: runs on smu_virtual_sequencer
// and starts reusable operation sequences on the handle each step needs
// (primary-TAP JTAG operations on p_sequencer.m_jtag_seqr). It never
// touches a driver or a VIP virtual interface; the written exceptions are
// tb_vif (the SMU-local TB interface: power-good, cold reset, the boot gate,
// the GPIO boot-stall pad, and the reset, fuse-sense and debug-control
// observables) and dtp_tb_vif (the embedded DTP's TAP-state and decoded-IR
// observables), both plumbed by the base test. TRST is driven through the
// VIP's TRST operation like every other TAP operation.
//
// The scenario layer tracks the TAP state itself (m_tap_state) and hands it
// to every JTAG operation, since the VIP sequence's model lives inside the
// operation sequence. On top of the operations it keeps the SMU-local
// helpers: TAP-state checks against the DTP one-hot observable, the TDR
// accesses (IC_RESET, DEBUG_CONTROL) and the SMC-fabric JTAG2AXI accesses
// (SINGLE_OP, SERIES) through the dtp_env_pkg codec, bounded waits
// (TCK-stepped or clock polled) that record one TIMEOUT-PATH line each with
// a finite bound and the last state seen, the TRST, power-good and
// cold-reset controls with the re-bring-up wait a reset needs before the
// next pass, the STEP marks of the scenario's log, the scoreboard
// activity floor, and the per-pass named evidence (CHK-*) through the
// protocol-neutral ocah_checker, attached with the scenario's required IDs
// and finalized after the scenario so a silently skipped check cannot
// report PASS. Every draw in a pass follows seed_scenario_rng() (first
// statement of body()). The cocotb twins are the helper layers of
// cocotb/seq_lib and cocotb_wrapper/seq_lib.

class smu_base_test_seq extends ocah_sequence;
  `uvm_object_utils(smu_base_test_seq)
  `uvm_declare_p_sequencer(smu_virtual_sequencer)

  localparam int unsigned IrWidth = SmuPtapIrWidth;
  // TCK cycles TRST stays released before the model re-syncs (cocotb
  // smoke sequence: four ref cycles after TRST release; one TCK period
  // spans at least that at the choice sets).
  localparam int unsigned TrstReleaseRefCycles = 4;
  // SMU clocks the SMC needs to take a DEBUG_CONTROL or IC_RESET update
  // across the TCK-to-system boundary before its exports are sampled
  // (cocotb ClockCycles(clk_smu_i, 16) after each TDR write).
  localparam int unsigned TdrExportSettleCycles = 16;
  // Idle TCK cycles after a series-data shift for the op to launch in the
  // system domain (bridge series pipeline, cocotb parity).
  localparam int unsigned J2aSeriesLaunchCycles = 5;
  // SMU clocks between the series-data shift and the first SERIES_CTRL poll
  // (cocotb jtag2axi_series_incr_write: ClockCycles(clk_smu_i, 64)).
  localparam int unsigned J2aSeriesSettleCycles = 64;

  // Plumbed by the test before start(): the SMU TB interface, the embedded
  // DTP TB interface, the two cfg levels, and the always-on scoreboard the
  // activity floor reads.
  virtual smu_tb_if tb_vif;
  virtual dtp_tb_if dtp_tb_vif;
  smu_test_cfg      test_cfg;
  smu_env_cfg       env_cfg;
  smu_scoreboard    scoreboard;
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
  // Scoreboard activity floor: feature -> minimum comparisons this pass adds.
  protected int unsigned m_min_activity[string];
  protected int unsigned m_activity_baseline[string];

  function new(string name = "smu_base_test_seq");
    super.new(name);
  endfunction

  // ------------------------------------------------------------------
  // Evidence plumbing.
  // ------------------------------------------------------------------

  function void attach_evidence(string required_ids[$]);
    if (tb_vif == null || dtp_tb_vif == null || test_cfg == null || env_cfg == null ||
        scoreboard == null)
      `uvm_fatal(get_type_name(),
                 "tb_vif/dtp_tb_vif/test_cfg/env_cfg/scoreboard not plumbed by the test")
    m_check = ocah_checker::type_id::create({get_name(), ".scenario"});
    m_check.name_tag     = "smu_scenario";
    m_check.required_ids = required_ids;
    m_timeout_paths.delete();
    m_timeouts_expired = 0;
    m_min_activity.delete();
    m_activity_baseline.delete();
  endfunction

  // Every scenario ends here: the scoreboard floor, then the checker
  // finalization that fails on a missing required ID.
  function void finalize_evidence();
    if (m_check == null) `uvm_fatal(get_type_name(), "evidence checker was never attached")
    check_scoreboard_activity();
    m_check.finalize(1'b1);
  endfunction

  // Record one named evidence comparison (uvm_error on mismatch).
  function void check_evidence(string check_id, string name, bit [63:0] observed,
                               bit [63:0] expected, string context_s = "");
    void'(m_check.expect_equal(check_id, observed, expected,
                               {name, context_s.len() ? " " : "", context_s}));
  endfunction

  // Comparison of a value wider than 64 bits, four-state on the observed
  // side: an X lane can satisfy no expectation. The record carries both
  // values in hex.
  function void check_evidence_wide(string check_id, string name, logic [255:0] observed,
                                    bit [255:0] expected, string context_s = "");
    void'(m_check.expect_true(
        check_id,
        observed === expected,
        $sformatf(
            "%s observed=0x%0h expected=0x%0h%s%s",
            name,
            observed,
            expected,
            context_s.len() ? " " : "",
            context_s)
    ));
  endfunction

  // One named TB-interface pin against a level, four-state: X or Z is
  // neither level, so a floating export cannot pass a zero expectation.
  function void check_pin(string check_id, string name, string which, bit level,
                          string context_s = "");
    logic observed = pin(which);
    void'(m_check.expect_true(
        check_id,
        observed === level,
        $sformatf(
            "%s observed=%b expected=%b%s%s",
            name,
            observed,
            level,
            context_s.len() ? " " : "",
            context_s)
    ));
  endfunction

  // ------------------------------------------------------------------
  // Scoreboard activity floor (CHK-SB-MIN-ACTIVITY): the named feature must
  // gain at least `min_compares` comparisons during this pass, taken from
  // the always-on scoreboard rather than from this sequence's bookkeeping.
  // ------------------------------------------------------------------

  localparam string ChkSbMinAct = "CHK-SB-MIN-ACTIVITY";

  function void check_min_activity(string feature, int unsigned min_compares);
    m_min_activity[feature]      = min_compares;
    m_activity_baseline[feature] = scoreboard.feature_compare_count(feature);
  endfunction

  protected function void check_scoreboard_activity();
    foreach (m_min_activity[f]) begin
      int unsigned gained = scoreboard.feature_compare_count(f) - m_activity_baseline[f];
      void'(m_check.expect_true(
          ChkSbMinAct,
          gained >= m_min_activity[f],
          $sformatf(
              "feature=%s compares_this_pass=%0d floor=%0d mismatches=%0d",
              f,
              gained,
              m_min_activity[f],
              scoreboard.feature_mismatch_count(
                  f
              ))
      ));
    end
  endfunction

  // ------------------------------------------------------------------
  // Step marks and the bounded-wait inventory.
  // ------------------------------------------------------------------

  // Mark the start of a scenario step (cocotb STEP <id> parity).
  function void mark_step(string step_id, string detail);
    log_step(step_id, detail);
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

  // The timeout inventory step every scenario closes with: every bounded
  // wait named a finite bound and its last state, none expired, and the
  // site count equals the scenario's declared count.
  task run_timeout_inventory(string check_id, int unsigned expected_paths);
    mark_step("TIMEOUT",
              "TIMEOUT: every bounded wait names finite bound + fail-on-expiry + last state");
    log_timeout_paths();
    check_evidence(check_id, "bounded wait sites", 64'(timeout_path_count()), 64'(expected_paths),
                   $sformatf(
                   "expired=%0d bound_tck=%0d bound_ref=%0d",
                   timeouts_expired(),
                   test_cfg.bound_tck,
                   test_cfg.bound_ref
                   ));
    check_evidence(check_id, "expired wait sites", 64'(timeouts_expired()), 64'd0);
  endtask

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

  // Idle TCK cycles in Run-Test/Idle (TMS = 0).
  task idle_tck(int unsigned cycles);
    bit tms_bits[] = new[cycles];
    bit tdi_bits[] = new[cycles];
    bit tdo_bits[];
    if (cycles == 0) return;
    foreach (tms_bits[i]) begin
      tms_bits[i] = 1'b0;
      tdi_bits[i] = 1'b0;
    end
    raw_walk(tms_bits, tdi_bits, tdo_bits);
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

  task dr_scan_wide(input bit pattern[], output bit observed[]);
    smu_jtag_dr_scan_wide_seq op = smu_jtag_dr_scan_wide_seq::type_id::create("dr_scan_wide");
    op.pattern = pattern;
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

  // The VIP scan operations start from Run-Test/Idle; a TAP reset leaves
  // the tracked state in Test-Logic-Reset, so a scan that follows one walks
  // to Run-Test/Idle first.
  task ensure_run_test_idle();
    if (m_tap_state != OCAH_JTAG_RUN_TEST_IDLE) goto_state(OCAH_JTAG_RUN_TEST_IDLE);
  endtask

  // Plain PTAP instruction load from Run-Test/Idle, back to Run-Test/Idle.
  task load_ir(bit [IrWidth-1:0] instr);
    bit [63:0] captured;
    ensure_run_test_idle();
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

  // ------------------------------------------------------------------
  // TDR accesses on the primary TAP: IC_RESET (wide) and DEBUG_CONTROL.
  // Each returns the image captured at Capture-DR, i.e. the register
  // content before this scan's update; the always-on scoreboard compares
  // that capture independently (ic_reset_tdr / debug_control_tdr).
  // ------------------------------------------------------------------

  task ic_reset_scan(input smu_ic_reset_image_t image, output smu_ic_reset_image_t captured);
    bit pattern[] = new[SmuIcResetLen];
    bit observed[];
    foreach (pattern[i]) pattern[i] = image[i];
    load_ir(dtp_env_pkg::IC_RESET_INSTR);
    dr_scan_wide(pattern, observed);
    captured = '0;
    foreach (observed[i]) if (i < SmuIcResetLen) captured[i] = observed[i];
    `uvm_info(get_type_name(), $sformatf("IC_RESET scan: wrote 0x%0h captured 0x%0h", image,
                                         captured), UVM_MEDIUM)
  endtask

  task debug_control_scan(input bit [SmuDebugControlLen-1:0] image,
                          output bit [SmuDebugControlLen-1:0] captured);
    bit [63:0] observed;
    load_ir(dtp_env_pkg::DEBUG_CONTROL_INSTR);
    dr_scan(64'(image), SmuDebugControlLen, observed);
    captured = SmuDebugControlLen'(observed);
    `uvm_info(get_type_name(), $sformatf("DEBUG_CONTROL scan: wrote 0x%02h captured 0x%02h", image,
                                         captured), UVM_MEDIUM)
  endtask

  // Write one TDR image and let the SMC take the update across the
  // TCK-to-system boundary before the exports are sampled.
  task ic_reset_write(smu_ic_reset_image_t image);
    smu_ic_reset_image_t unused;
    ic_reset_scan(image, unused);
    wait_smu_cycles(TdrExportSettleCycles);
  endtask

  task debug_control_write(bit [SmuDebugControlLen-1:0] image);
    bit [SmuDebugControlLen-1:0] unused;
    debug_control_scan(image, unused);
    wait_smu_cycles(TdrExportSettleCycles);
  endtask

  // ------------------------------------------------------------------
  // SMC-fabric JTAG2AXI operations (smu_jtag2axi_single_op_seq /
  // smu_jtag2axi_single_status_seq on the primary TAP sequencer): the
  // dtp_env_pkg codec and bridge geometry the embedded DTP's own bench uses
  // for this bridge, reused unchanged.
  // ------------------------------------------------------------------

  static function dtp_env_pkg::dtp_j2a_target_t j2a_target_smc_axi();
    return dtp_env_pkg::dtp_j2a_target_smc_axi();
  endfunction

  // Launch one SINGLE_OP request; the bridge starts the AXI transaction
  // after the shift.
  task issue_single_j2a(dtp_env_pkg::dtp_j2a_target_t t, dtp_env_pkg::dtp_j2a_op_e op,
                        bit [63:0] addr, bit [63:0] data, bit [7:0] wstrb, int unsigned size);
    smu_jtag2axi_single_op_seq req = smu_jtag2axi_single_op_seq::type_id::create("j2a_single_op");
    req.target = t;
    req.op     = op;
    req.addr   = addr;
    req.data   = data;
    req.wstrb  = wstrb;
    req.size   = size;
    ensure_run_test_idle();
    run_jtag_op(req);
  endtask

  // Bounded poll of the SINGLE_OP status register (cocotb
  // jtag2axi_single_write/read parity): shifts zeros until the bridge
  // leaves BUSY_OR_FULL. One TIMEOUT-PATH site per call, `label` naming the
  // site; the last observed status is the "last state" the site records.
  task poll_single_j2a(dtp_env_pkg::dtp_j2a_target_t t, string label,
                       output dtp_env_pkg::dtp_j2a_status_e status, output bit [63:0] rdata);
    bit ok = 1'b0;
    status = dtp_env_pkg::DTP_J2A_BUSY_OR_FULL;
    rdata  = '0;
    for (int unsigned poll = 0; poll < test_cfg.j2a_max_status_polls; poll++) begin
      smu_jtag2axi_single_status_seq st = smu_jtag2axi_single_status_seq::type_id::create(
          "j2a_single_status"
      );
      st.target = t;
      ensure_run_test_idle();
      run_jtag_op(st);
      status = st.status;
      rdata  = st.rdata;
      if (status != dtp_env_pkg::DTP_J2A_BUSY_OR_FULL) begin
        ok = 1'b1;
        break;
      end
      wait_smu_cycles(TdrExportSettleCycles);
    end
    record_timeout_path(label, test_cfg.j2a_max_status_polls, ok, 16'(status));
  endtask

  task single_write_j2a(dtp_env_pkg::dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                        bit [7:0] wstrb, int unsigned size, string label,
                        output dtp_env_pkg::dtp_j2a_status_e status);
    bit [63:0] unused_rdata;
    issue_single_j2a(t, dtp_env_pkg::DTP_J2A_OP_WRITE, addr, data, wstrb, size);
    poll_single_j2a(t, label, status, unused_rdata);
  endtask

  task single_read_j2a(dtp_env_pkg::dtp_j2a_target_t t, bit [63:0] addr, int unsigned size,
                       string label, output dtp_env_pkg::dtp_j2a_status_e status,
                       output bit [63:0] rdata);
    issue_single_j2a(t, dtp_env_pkg::DTP_J2A_OP_READ, addr, '0, '0, size);
    poll_single_j2a(t, label, status, rdata);
  endtask

  // *_JTAG2AXI_CAPS readback of one bridge (14 bits).
  task read_j2a_caps(dtp_env_pkg::dtp_j2a_target_t t, output bit [SmuJ2aCapsLen-1:0] caps);
    bit [63:0] observed;
    load_ir(t.caps_instr);
    dr_scan(64'h0, SmuJ2aCapsLen, observed);
    caps = SmuJ2aCapsLen'(observed);
  endtask

  // SERIES_CTRL programming: op, size, pipeline depth and address latched at
  // Update-DR (dtp_env_pkg codec).
  task series_ctrl_j2a(dtp_env_pkg::dtp_j2a_target_t t, dtp_env_pkg::dtp_j2a_op_e op,
                       bit [63:0] addr, int unsigned pipeline_depth, int unsigned size);
    bit [63:0] unused;
    load_ir(t.series_ctrl_instr);
    dr_scan(dtp_env_pkg::dtp_j2a_pack_series_ctrl(t, op, addr, pipeline_depth, size, 1'b0),
            dtp_env_pkg::dtp_j2a_series_ctrl_len(t), unused);
  endtask

  // Bounded poll of SERIES_CTRL until its status leaves BUSY_OR_FULL (a
  // NOP image keeps the latched programming). One TIMEOUT-PATH site.
  task poll_series_ctrl_j2a(dtp_env_pkg::dtp_j2a_target_t t, int unsigned size, string label,
                            output dtp_env_pkg::dtp_j2a_status_e status);
    bit        ok = 1'b0;
    bit [63:0] nop = dtp_env_pkg::dtp_j2a_pack_series_ctrl(t, dtp_env_pkg::DTP_J2A_OP_NOP, '0, 0,
                                                            size, 1'b0);
    status = dtp_env_pkg::DTP_J2A_BUSY_OR_FULL;
    load_ir(t.series_ctrl_instr);
    for (int unsigned poll = 0; poll < test_cfg.j2a_max_status_polls; poll++) begin
      bit [63:0] observed, addr_u;
      bit rst_u;
      int unsigned pl_u, size_u;
      dr_scan(nop, dtp_env_pkg::dtp_j2a_series_ctrl_len(t), observed);
      dtp_env_pkg::dtp_j2a_unpack_series_ctrl(t, observed, rst_u, addr_u, pl_u, size_u, status);
      if (status != dtp_env_pkg::DTP_J2A_BUSY_OR_FULL) begin
        ok = 1'b1;
        break;
      end
      wait_smu_cycles(TdrExportSettleCycles);
    end
    record_timeout_path(label, test_cfg.j2a_max_status_polls, ok, 16'(status));
  endtask

  // One SERIES_DATA_INCR shift under the latched series size, returning the
  // captured payload.
  task series_data_incr_j2a(dtp_env_pkg::dtp_j2a_target_t t, bit [63:0] data, int unsigned size,
                            output bit [63:0] captured);
    int unsigned width = 8 * dtp_env_pkg::dtp_j2a_size_bytes(size);
    load_ir(t.series_data_incr_instr);
    dr_scan(data & dtp_env_pkg::dtp_j2a_data_mask(size), width, captured);
    idle_tck(J2aSeriesLaunchCycles);
    captured &= dtp_env_pkg::dtp_j2a_data_mask(size);
  endtask

  // Series INCR write of one word, then the CTRL status (cocotb
  // jtag2axi_series_incr_write parity).
  task series_incr_write_j2a(dtp_env_pkg::dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                             int unsigned size, string label,
                             output dtp_env_pkg::dtp_j2a_status_e status);
    bit [63:0] unused;
    series_ctrl_j2a(t, dtp_env_pkg::DTP_J2A_OP_WRITE, addr, 1, size);
    series_data_incr_j2a(t, data, size, unused);
    wait_smu_cycles(J2aSeriesSettleCycles);
    poll_series_ctrl_j2a(t, size, label, status);
  endtask

  // Series INCR read of one word: programme, one data shift to launch the
  // read, the CTRL status, then the data shift that returns the word. That
  // last shift launches the next pipelined read of the series (the budget is
  // pipeline_depth + 1 per programming), so the CTRL status is polled once
  // more (`drain_label`) and the bridge is idle when the task returns.
  task series_incr_read_j2a(dtp_env_pkg::dtp_j2a_target_t t, bit [63:0] addr, int unsigned size,
                            string label, string drain_label,
                            output dtp_env_pkg::dtp_j2a_status_e status, output bit [63:0] rdata);
    bit [63:0] unused;
    dtp_env_pkg::dtp_j2a_status_e drain_status;
    series_ctrl_j2a(t, dtp_env_pkg::DTP_J2A_OP_READ, addr, 1, size);
    series_data_incr_j2a(t, '0, size, unused);
    wait_smu_cycles(J2aSeriesSettleCycles);
    poll_series_ctrl_j2a(t, size, label, status);
    series_data_incr_j2a(t, '0, size, rdata);
    wait_smu_cycles(J2aSeriesSettleCycles);
    poll_series_ctrl_j2a(t, size, drain_label, drain_status);
  endtask

  // ------------------------------------------------------------------
  // Power-good, cold reset and the reset-release baseline.
  // ------------------------------------------------------------------

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

  // Cold-reset pulse on rst_cold_ni with TRST held high (the DTP TAP and
  // its TDRs are not in this reset domain); the caller waits for whatever
  // release it observes.
  task pulse_cold_reset();
    `uvm_info(get_type_name(), "asserting cold reset", UVM_MEDIUM)
    tb_vif.rst_cold_n <= 1'b0;
    wait_ref_cycles(test_cfg.cold_pulse_ref_cycles);
    tb_vif.rst_cold_n <= 1'b1;
    `uvm_info(get_type_name(), "cold reset released", UVM_MEDIUM)
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
  // Pin-level bounded waits on the SMU clock, each one TIMEOUT-PATH site.
  // The signal is named, not passed, so the wait reads the live level.
  // ------------------------------------------------------------------

  protected function logic pin(string which);
    case (which)
      "fuse_reset_n_delayed":    return tb_vif.fuse_reset_n_delayed;
      "fuse_sense_done":         return tb_vif.fuse_sense_done;
      "rst_primary_smc_clk_n":   return tb_vif.rst_primary_smc_clk_n;
      "rst_cold_stable_ref_clk_n": return tb_vif.rst_cold_stable_ref_clk_n;
      "ext_boot_seq_done":       return tb_vif.ext_boot_seq_done;
      "jtag_boot_stall":         return tb_vif.jtag_boot_stall;
      "jtag_boot_stall_ovrd":    return tb_vif.jtag_boot_stall_ovrd;
      "jtag_ic_reset_ext_ovrd":  return tb_vif.jtag_ic_reset_ext_ovrd;
      "jtag_ic_reset_ext_ctrl_n": return tb_vif.jtag_ic_reset_ext_ctrl_n;
      "jtag_ic_reset_smc_ovrd":  return tb_vif.jtag_ic_reset_smc_ovrd;
      "jtag_ic_reset_smc_ctrl_n": return tb_vif.jtag_ic_reset_smc_ctrl_n;
      "smc_jtag2axi_security_disable": return tb_vif.smc_jtag2axi_security_disable;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown pin %s", which))
        return 1'bx;
      end
    endcase
  endfunction

  // Four-state sample: X/Z is neither level, so it can satisfy no compare.
  function bit pin_is(string which, bit level);
    return pin(which) === level;
  endfunction

  // Cycles until `which` reads `level`, 0 when it already does; the last
  // level seen goes into the site record. `cycles` is -1 on expiry.
  task wait_pin_level(string which, bit level, int unsigned bound, string label, output int cycles);
    logic last = pin(which);
    cycles = 0;
    if (last === level) begin
      record_timeout_path(label, bound, 1'b1, 16'(last));
      return;
    end
    for (int unsigned c = 1; c <= bound; c++) begin
      @(posedge tb_vif.clk_smu);
      last = pin(which);
      if (last === level) begin
        cycles = c;
        record_timeout_path(label, bound, 1'b1, 16'(last));
        return;
      end
    end
    cycles = -1;
    record_timeout_path(label, bound, 1'b0, 16'(last));
  endtask

  // Cycles until a 0 -> 1 transition of `which`, the wait having read it 0
  // first; a level already high fails (no transition observed) and expiry
  // fails. -1 on either.
  task wait_pin_rise(string which, int unsigned bound, string label, output int cycles);
    if (pin(which) === 1'b1) begin
      `uvm_error(get_type_name(), $sformatf("%s already 1 before the wait: no 0->1 observed",
                                            which))
      record_timeout_path(label, bound, 1'b0, 16'h1);
      cycles = -1;
      return;
    end
    wait_pin_level(which, 1'b1, bound, label, cycles);
  endtask

  // Consecutive SMU clocks `which` reads `level`; the count of edges that
  // did not is returned (0 = held).
  task hold_pin_level(string which, bit level, int unsigned cycles, output int unsigned breaks);
    breaks = 0;
    for (int unsigned c = 0; c < cycles; c++) begin
      @(posedge tb_vif.clk_smu);
      if (pin(which) !== level) breaks++;
    end
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
