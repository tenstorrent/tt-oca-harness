// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base virtual sequence of every DTP scenario: runs on dtp_virtual_sequencer
// and starts reusable operation sequences on the handle each step needs
// (JTAG operations on p_sequencer.m_jtag_seqr, CSR AXI-Lite operations on
// p_sequencer.m_xtrig_seqr in the XTRIG family, responder backdoor through
// the slave sequences). It never touches a driver or a VIP virtual
// interface; the written exceptions are the DTP-local TB interfaces tb_vif
// (reset sequencing, dbg_disable stimulus, control-domain observables),
// scan_vif (scan-network observables and downstream-TAP attach), xtrig_vif
// (cross-trigger pins), and jtag_vif (the reset-family scenarios hold TRST
// across TCK cycles), all plumbed by the base test.
//
// The scenario layer tracks the TAP state itself (m_tap_state) and hands it
// to every JTAG operation, since the VIP sequence's model lives inside the
// operation sequence. On top of the operations it keeps the DTP-local
// checks: TAP-state checks against the one-hot observable, scan-length
// evidence through the env scan builder, the BYPASS latency check, the
// lifecycle dbg_disable settle rule, and system-domain waits derived from
// the env clock period. Every draw in a pass follows seed_scenario_rng()
// (first statement of body()). The cocotb twin is
// seq_lib/dtp_base_test_seq.py; feature families extend this class
// (dtp_jtag_base_test_seq, dtp_jtag2axi_base_test_seq,
// dtp_debug_tdr_base_test_seq, dtp_scan_base_test_seq,
// dtp_xtrig_base_test_seq).

class dtp_base_test_seq extends ocah_sequence;
  `uvm_object_utils(dtp_base_test_seq)
  `uvm_declare_p_sequencer(dtp_virtual_sequencer)

  localparam int unsigned IrWidth = DtpIrWidth;
  // Cycles the reset ladder holds each reset (cocotb _bring_up parity).
  localparam int unsigned PorHoldCycles = 5;
  localparam int unsigned SysResetHoldCycles = 5;
  localparam int unsigned PostResetCycles = 10;
  // dbg_disable settle: the DUT synchronizes dbg_disable through 2-stage
  // TCK-domain flops; four toggling idle TCK cycles plus four system
  // cycles are the TB margin.
  localparam int unsigned DbgDisableTckCycles = 4;
  localparam int unsigned DbgDisableSysCycles = 4;

  // Plumbed by the test before start(): the DTP-local TB interface (reset
  // ladder, dbg_disable stimulus, observables) and the test configuration.
  virtual dtp_tb_if    tb_vif;
  virtual dtp_scan_if  scan_vif;
  virtual dtp_xtrig_if xtrig_vif;
  dtp_test_cfg         test_cfg;
  // Plumbed by the test for scenarios that hold or sequence TRST directly
  // (reset family). Safe alongside the VIP driver, which drives trst_n only
  // while executing a TAP_RESET item.
  virtual ocah_jtag_if jtag_vif;
  // Env-owned evidence and observation handles: the aggregate JTAG
  // recorder, the pin-level scan reconstruction (a scenario clears the
  // handle to skip scan-length evidence), and the scan-window monitor.
  ocah_jtag_checker       evidence;
  ocah_jtag_scan_builder  scan_builder;
  dtp_scan_window_monitor scan_window;

  // TAP state tracked across operations (each operation re-syncs the VIP
  // model from it and hands the landing state back).
  protected ocah_jtag_tap_state_e m_tap_state = OCAH_JTAG_TEST_LOGIC_RESET;
  // TAP state sampled by set_trst with TRST_N low and no TCK edge since.
  protected bit [15:0] m_trst_async_state;

  function new(string name = "dtp_base_test_seq");
    super.new(name);
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
    dtp_jtag_tap_reset_seq op = dtp_jtag_tap_reset_seq::type_id::create("tap_reset");
    run_jtag_op(op);
  endtask

  // One raw TCK step from any state.
  task step(bit tms, bit tdi = 1'b0);
    bit tms_bits[] = new[1];
    bit tdi_bits[] = new[1];
    tms_bits[0] = tms;
    tdi_bits[0] = tdi;
    raw_walk(tms_bits, tdi_bits);
  endtask

  task raw_walk(bit tms_bits[], bit tdi_bits[]);
    dtp_jtag_tms_walk_seq op = dtp_jtag_tms_walk_seq::type_id::create("tms_walk");
    op.tms_bits = tms_bits;
    op.tdi_bits = tdi_bits;
    run_jtag_op(op);
  endtask

  task goto_state(ocah_jtag_tap_state_e target);
    dtp_jtag_goto_state_seq op = dtp_jtag_goto_state_seq::type_id::create("goto_state");
    op.target_state = target;
    run_jtag_op(op);
  endtask

  // Walk to a seeded random state outside `exclude`.
  task goto_random_state(output ocah_jtag_tap_state_e reached,
                         input ocah_jtag_tap_state_e exclude[$] = {});
    ocah_jtag_tap_state_e pool[$];
    for (int unsigned s = 0; s < 16; s++) begin
      ocah_jtag_tap_state_e st = ocah_jtag_tap_state_e'(s);
      if (!(st inside {exclude})) pool.push_back(st);
    end
    if (pool.size() == 0) `uvm_fatal(get_type_name(), "goto_random_state: every TAP state excluded")
    reached = pool[$urandom_range(pool.size()-1)];
    goto_state(reached);
  endtask

  // Seeded random TMS walk (TDI = 0); read the landing state with
  // current_state().
  task random_tms_walk(int unsigned cycles);
    bit tms_bits[] = new[cycles];
    bit tdi_bits[] = new[cycles];
    if (cycles == 0) return;
    foreach (tms_bits[i]) begin
      tms_bits[i] = $urandom_range(1);
      tdi_bits[i] = 1'b0;
    end
    raw_walk(tms_bits, tdi_bits);
  endtask

  task ir_scan(input bit [63:0] value, input int unsigned width, output bit [63:0] captured);
    dtp_jtag_ir_scan_seq op = dtp_jtag_ir_scan_seq::type_id::create("ir_scan");
    op.value = value;
    op.width = width;
    run_jtag_op(op);
    captured = op.captured;
  endtask

  task dr_scan(input bit [63:0] pattern, input int unsigned width, output bit [63:0] observed);
    dtp_jtag_dr_scan_seq op = dtp_jtag_dr_scan_seq::type_id::create("dr_scan");
    op.pattern = pattern;
    op.width   = width;
    run_jtag_op(op);
    observed = op.observed;
  endtask

  task dr_scan_wide(input bit pattern[], output bit observed[]);
    dtp_jtag_dr_scan_seq op = dtp_jtag_dr_scan_seq::type_id::create("dr_scan_wide");
    op.pattern_bits = pattern;
    run_jtag_op(op);
    observed = op.observed_bits;
  endtask

  // Hand the tracked state to an operation, start it on the JTAG agent
  // sequencer, and take the landing state back.
  protected task run_jtag_op(dtp_jtag_op_seq op);
    if (p_sequencer.m_jtag_seqr == null)
      `uvm_fatal(get_type_name(), "dtp_virtual_sequencer.m_jtag_seqr is null")
    op.entry_state = m_tap_state;
    op.start(p_sequencer.m_jtag_seqr, this);
    m_tap_state = op.current_state();
  endtask

  // ------------------------------------------------------------------
  // DTP-local TAP helpers and checks.
  // ------------------------------------------------------------------

  // `checker_tag` because bare `checker` is an IEEE 1800 reserved word.
  function void check_state(tap_state_e expected, string checker_tag, string what);
    if (tb_vif.tap_state !== expected)
      `uvm_error(checker_tag, $sformatf(
                 "%s: expected TAP state %s (0x%04h), got 0x%04h",
                 what,
                 expected.name(),
                 expected,
                 tb_vif.tap_state
                 ))
    else
      `uvm_info(checker_tag, $sformatf("%s: TAP state %s as expected", what, expected.name()),
                UVM_MEDIUM)
  endfunction

  // Power-on/system reset sequencing (DTP-local, via dtp_tb_if), the same
  // ladder the base test walks at bring-up. The JTAG pins idle under the
  // VIP driver (tck=0, tms=1, trst_n=1); tap_reset() follows.
  task sys_reset();
    `uvm_info(get_type_name(), "sequencing power-on and system resets", UVM_MEDIUM)
    tb_vif.por_rst_n <= 1'b0;
    tb_vif.sys_rst_n <= 1'b0;
    wait_sys_cycles(PorHoldCycles);
    tb_vif.por_rst_n <= 1'b1;
    wait_sys_cycles(SysResetHoldCycles);
    tb_vif.sys_rst_n <= 1'b1;
    wait_sys_cycles(PostResetCycles);
  endtask

  // TAP reset: TRST pulse via the driver -> Test-Logic-Reset.
  task tap_reset();
    `uvm_info(get_type_name(), "asserting TRST for TAP reset", UVM_MEDIUM)
    tap_reset_op();
    if (evidence != null)
      void'(evidence.check_reset_to_tlr(tb_vif.tap_state, "after TRST release"));
    check_state(TEST_LOGIC_RESET, "sanity_fsm_visit_chk", "after TRST release");
  endtask

  // Return to Test-Logic-Reset from any state via five TMS=1 cycles.
  task goto_tlr_via_tms();
    bit tms[] = '{1'b1, 1'b1, 1'b1, 1'b1, 1'b1};
    bit tdi[] = '{1'b0, 1'b0, 1'b0, 1'b0, 1'b0};
    raw_walk(tms, tdi);
    if (evidence != null)
      void'(evidence.check_tms_ones_to_tlr(5, tb_vif.tap_state, "after 5x TMS=1"));
    check_state(TEST_LOGIC_RESET, "sanity_scan_path_chk", "after 5x TMS=1");
  endtask

  // Hold or release TRST directly (active-low). Asserting samples the TAP
  // state once the pin has settled and before any TCK edge (the driver
  // idles TCK between items), then clocks TCK with TMS low, which leaves
  // Test-Logic-Reset unless the reset holds the controller there. Releasing
  // clocks TCK with TMS high, the Test-Logic-Reset self-loop.
  task set_trst(bit value, int unsigned cycles = 1);
    if (jtag_vif == null)
      `uvm_fatal(get_type_name(), "set_trst() needs jtag_vif plumbed by the test")
    jtag_vif.trst_n <= value;
    if (value == 1'b0) begin
      wait_sys_cycles(1);
      m_trst_async_state = tb_vif.tap_state;
    end
    repeat (cycles > 0 ? cycles : 1) step(value);
    if (value == 1'b0) begin
      sync_model(OCAH_JTAG_TEST_LOGIC_RESET);
      if (evidence != null) evidence.reset_model();
    end
  endtask

  // The TAP state set_trst sampled under TRST_N before any TCK edge.
  function bit [15:0] trst_async_state();
    return m_trst_async_state;
  endfunction

  // Pulse power-on reset while TCK keeps stepping with TMS=1 (the TAP's
  // POR independence contract is checked by the caller from tb_vif state).
  task pulse_por(int unsigned cycles = 5);
    tb_vif.por_rst_n <= 1'b0;
    repeat (cycles > 0 ? cycles : 1) step(1'b1);
    tb_vif.por_rst_n <= 1'b1;
    wait_sys_cycles(DbgDisableSysCycles);
  endtask

  // IR scan from Run-Test/Idle (LSB-first), back to Run-Test/Idle.
  virtual task load_ir(bit [IrWidth-1:0] instr);
    bit [63:0] captured;
    `uvm_info(get_type_name(), $sformatf("IR scan: loading 0x%02h (%0d bits)", instr, IrWidth),
              UVM_MEDIUM)
    ir_scan(64'(instr), IrWidth, captured);
    check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after IR scan");
    check_last_scan_length(1'b1, IrWidth, $sformatf("ir=0x%02h", instr));
    note_scan(1'b1, IrWidth);
  endtask

  // IR scan of any width from Run-Test/Idle (LSB-first), returning the
  // captured TDO. The PTAP forwards its scan controls to the STAP chain on
  // IR scans too, so a network-wide instruction scan (PTAP IR followed by
  // the STAP chain and any spliced downstream TAP IRs) is longer than the
  // PTAP's own IR; load_ir() stays the plain 6-bit load.
  virtual task ir_scan_raw(input bit [63:0] value, input int unsigned width,
                           output bit [63:0] captured);
    ir_scan(value, width, captured);
    check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after raw IR scan");
    check_last_scan_length(1'b1, width, $sformatf("raw ir width=%0d", width));
    note_scan(1'b1, width);
  endtask

  // DR scan from Run-Test/Idle (LSB-first), returning observed TDO.
  virtual task shift_dr(input bit [63:0] pattern, input int unsigned width,
                        output bit [63:0] observed);
    dr_scan(pattern, width, observed);
    check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after DR scan");
    check_last_scan_length(1'b0, width, $sformatf("pattern=0x%0h", pattern));
    note_scan(1'b0, width);
  endtask

  // Wide DR scan (>64 bits) through the VIP wide-scan path.
  virtual task shift_dr_wide(input bit pattern[], output bit observed[]);
    dr_scan_wide(pattern, observed);
    check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after wide DR scan");
    check_last_scan_length(1'b0, pattern.size(), $sformatf("wide width=%0d", pattern.size()));
    note_scan(1'b0, pattern.size());
  endtask

  // Read a test data register by instruction (6-bit IR load + DR scan).
  task read_tdr(input bit [IrWidth-1:0] instr, input int unsigned width, output bit [63:0] value,
                input bit [63:0] shift_value = '0);
    dtp_jtag_read_tdr_seq op = dtp_jtag_read_tdr_seq::type_id::create("read_tdr");
    op.instr       = instr;
    op.width       = width;
    op.shift_value = shift_value;
    run_jtag_op(op);
    value = op.value;
    check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after TDR read");
    note_tdr_access(width, $sformatf("read ir=0x%02h", instr));
  endtask

  // Write a test data register by instruction (6-bit IR load + DR scan).
  task write_tdr(input bit [IrWidth-1:0] instr, input int unsigned width, input bit [63:0] value);
    dtp_jtag_write_tdr_seq op = dtp_jtag_write_tdr_seq::type_id::create("write_tdr");
    op.instr = instr;
    op.width = width;
    op.value = value;
    run_jtag_op(op);
    check_state(RUN_TEST_IDLE, "sanity_scan_path_chk", "after TDR write");
    note_tdr_access(width, $sformatf("write ir=0x%02h", instr));
  endtask

  // Scan-length evidence and intent for the two scans of a TDR access.
  protected function void note_tdr_access(int unsigned width, string context_s);
    check_last_scan_length(1'b1, IrWidth, context_s);
    check_last_scan_length(1'b0, width, context_s);
    note_scan(1'b1, IrWidth);
    note_scan(1'b0, width);
  endfunction

  // Scan-intent hook: the family layer records every issued scan for its
  // pin-level cross-check.
  virtual function void note_scan(bit is_ir, int unsigned width);
  endfunction

  // CHK-SCAN-IR-LEN / CHK-SCAN-DR-LEN: the newest reconstructed scan of
  // this kind (published on the Shift->Exit1 edge, cycles before the
  // driver's back-to-RTI leg completes) must span exactly the driven width.
  function void check_last_scan_length(bit is_ir, int unsigned width, string context_s);
    ocah_jtag_scan_item item;
    if (evidence == null || scan_builder == null) return;
    if (is_ir ? scan_builder.ir_items.size() == 0 : scan_builder.dr_items.size() == 0) begin
      `uvm_error("sanity_scan_len_chk", $sformatf("no reconstructed %s scan observed (%s)",
                                                  is_ir ? "IR" : "DR", context_s))
      return;
    end
    item = is_ir ? scan_builder.ir_items[$] : scan_builder.dr_items[$];
    void'(evidence.check_scan_length(item, width, context_s));
  endfunction

  // Read the 32-bit device-identification register via IDCODE.
  task read_idcode(output bit [63:0] observed);
    load_ir(IDCODE_INSTR);
    shift_dr(64'h0, 32, observed);
  endtask

  // sanity_bypass_latency_chk: BYPASS (IR 0x00) => exactly 1-TCK
  // TDI-to-TDO delay: observed = {pattern[width-2:0], 1'b0} LSB-first.
  task check_bypass_latency(bit [63:0] pattern, int unsigned width);
    bit [63:0] observed, expected;
    expected = ocah_jtag_checker::predict_bypass_tdo(pattern, width);
    shift_dr(pattern, width, observed);
    if (evidence != null) begin
      void'(evidence.check_bypass_latency(observed, pattern, width));
    end else if (observed !== expected)
      `uvm_error("sanity_bypass_latency_chk", $sformatf(
                 "BYPASS TDI-to-TDO latency not 1 TCK: pattern=0x%016h width=%0d expected=0x%016h observed=0x%016h",
                 pattern,
                 width,
                 expected,
                 observed
                 ))
    else
      `uvm_info("sanity_bypass_latency_chk", $sformatf(
                "BYPASS 1-TCK latency OK: pattern=0x%016h width=%0d observed=0x%016h",
                pattern,
                width,
                observed
                ), UVM_MEDIUM)
  endtask

  // ------------------------------------------------------------------
  // System domain and lifecycle debug disables (through dtp_tb_if).
  // ------------------------------------------------------------------

  // System-clock cycles: the sequence layer holds no clock handle, so the
  // wait is derived from the period the env published on tb_if.
  task wait_sys_cycles(int unsigned cycles = 4);
    if (tb_vif.clk_period_ns == 0)
      `uvm_fatal(get_type_name(), "tb_if.clk_period_ns is 0; the env did not publish it")
    #(cycles * tb_vif.clk_period_ns * 1ns);
  endtask

  // Idle for whole TCK periods with no TCK edge (the driver holds TCK
  // low between items): the POR-independence scenario holds power-on
  // reset across TCK periods without clocking the TAP.
  task wait_tck_periods(int unsigned periods);
    if (test_cfg == null || test_cfg.tck_period_ns == 0)
      `uvm_fatal(get_type_name(), "test_cfg.tck_period_ns not available")
    #(periods * test_cfg.tck_period_ns * 1ns);
  endtask

  // System-clock cycles per TCK period, rounded up (bounds for waits that
  // span a TCK-domain operation in system-domain cycles).
  function int unsigned tck_sys_ratio();
    if (test_cfg == null || tb_vif.clk_period_ns == 0)
      `uvm_fatal(get_type_name(), "timing not available for tck_sys_ratio()")
    return (test_cfg.tck_period_ns + tb_vif.clk_period_ns - 1) / tb_vif.clk_period_ns;
  endfunction

  // Pulse rst_n_i without POR/TRST, preserving TAP accessibility.
  task pulse_system_reset(int unsigned cycles = 5);
    tb_vif.sys_rst_n <= 1'b0;
    wait_sys_cycles(cycles);
    tb_vif.sys_rst_n <= 1'b1;
    wait_sys_cycles(cycles);
  endtask

  // Drive the lifecycle disable vector, then settle through the DUT's
  // 2-stage TCK-domain synchronizers.
  task set_dbg_disable(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    tb_vif.drive_dbg_disable(d);
    for (int unsigned i = 0; i < DbgDisableTckCycles; i++) step(1'b0);
    wait_sys_cycles(DbgDisableSysCycles);
    `uvm_info(get_type_name(), $sformatf("dbg_disable=0x%03h", d), UVM_MEDIUM)
  endtask

  task enable_all_debug();
    set_dbg_disable('0);
  endtask

endclass : dtp_base_test_seq
