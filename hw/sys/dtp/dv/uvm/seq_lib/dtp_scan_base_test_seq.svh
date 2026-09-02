// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared iJTAG/STAP scan helper base sequence — the SV analogue of the
// cocotb dtp_scan_base_test_seq, layered on the JTAG command library with
// the dtp_scan_ref_model classes:
//
//   * temporal scan-control windows: a forked sampler counts high samples
//     of named dtp_tb_if observables once per TCK cycle, so a gated
//     operation proves ZERO pulses over a whole scan and an enabled one
//     proves the expected pulses occurred (post-scan snapshots cannot).
//     Samples land on the falling TCK edge, where every control has
//     settled — the same one-sample-per-cycle semantics as the cocotb
//     post-edge ReadOnly monitor;
//   * iJTAG SIB programming (SELECT_IJTAG) with requested/gated/effective
//     prediction from the SIB model and window-proved outcomes;
//   * STAP/3DCR access: PTAP 3DCR read/write, composed TAP_3DCR chain
//     scans through the 3DCR model (compose/apply/expected-capture), the
//     forwarding checks (tdo_oen pulses + tms follows live TMS vs parked),
//     and TLR/TRST model synchronization.
//
// Scenario checks land named family evidence (CHK-SCAN-WIN for the
// temporal windows, CHK-SCAN-OBS for sampled observables, CHK-SCAN-CHAIN
// for chain readbacks), honoring +DTP_JTAG_FAMILY_CHECKER_NEGATIVE. The
// scan scenarios navigate Shift-x with sequence-owned exits, so tests
// attach the family checker with use_scan_crosscheck=0.

class dtp_scan_base_test_seq extends dtp_jtag_cmd_lib_seq;
  `uvm_object_utils(dtp_scan_base_test_seq)

  localparam int unsigned Ptap3dcrWidth = 2;
  localparam int unsigned StapChainScanWidth = 32;

  // The UVM harness system clock is fixed at 100 MHz (tb_top).
  localparam time SysClkPeriod = 10ns;

  dtp_stap_3dcr_model    stap_model;

  // Window-monitor state (one window at a time, mirroring cocotb usage).
  protected string       m_win_signals        [$];
  protected int unsigned m_win_counts[string];
  protected int unsigned m_win_edges;
  protected process      m_win_proc;

  function new(string name = "dtp_scan_base_test_seq");
    super.new(name);
    stap_model = new();
  endfunction

  // --- system helpers -------------------------------------------------------
  task wait_sys_cycles(int unsigned cycles = 4);
    #(cycles * SysClkPeriod);
  endtask

  // Drive the full lifecycle disable vector, then settle through the
  // DUT's 2-stage TCK-domain synchronizers.
  task set_dbg_disable_full(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    tb_vif.dbg_disable <= d;
    for (int unsigned i = 0; i < 4; i++) step(1'b0);
    wait_sys_cycles(4);
    `uvm_info(get_type_name(), $sformatf("dbg_disable=0x%03h", d), UVM_MEDIUM)
  endtask

  task enable_all_debug();
    set_dbg_disable_full('0);
  endtask

  // --- generic TDR access ----------------------------------------------------
  task read_tdr64(input bit [IrWidth-1:0] instr, input int unsigned width,
                  output bit [63:0] observed, input bit [63:0] shift_value = '0);
    load_ir(instr);
    shift_dr(shift_value & bit_mask(width), width, observed);
    observed &= bit_mask(width);
  endtask

  task write_tdr64(input bit [IrWidth-1:0] instr, input int unsigned width, input bit [63:0] value);
    bit [63:0] unused;
    load_ir(instr);
    shift_dr(value & bit_mask(width), width, unused);
  endtask

  // --- observable sampling and temporal windows ------------------------------
  function bit sample_scan_signal(string name);
    case (name)
      "jtag_dft_secure_select":     return tb_vif.jtag_dft_secure_select;
      "jtag_dft_secure_shift_en":   return tb_vif.jtag_dft_secure_shift_en;
      "jtag_dft_secure_capture_en": return tb_vif.jtag_dft_secure_capture_en;
      "jtag_dft_secure_update_en":  return tb_vif.jtag_dft_secure_update_en;
      "jtag_dft_select":            return tb_vif.jtag_dft_select;
      "jtag_dft_shift_en":          return tb_vif.jtag_dft_shift_en;
      "jtag_dft_capture_en":        return tb_vif.jtag_dft_capture_en;
      "jtag_dft_update_en":         return tb_vif.jtag_dft_update_en;
      "jtag_dfd_select":            return tb_vif.jtag_dfd_select;
      "jtag_dfd_shift_en":          return tb_vif.jtag_dfd_shift_en;
      "jtag_dfd_capture_en":        return tb_vif.jtag_dfd_capture_en;
      "jtag_dfd_update_en":         return tb_vif.jtag_dfd_update_en;
      "jtag_stap_io_tms":           return tb_vif.jtag_stap_io_tms;
      "jtag_stap_io_tdo_oen":       return tb_vif.jtag_stap_io_tdo_oen;
      "jtag_stap_smc_tms":          return tb_vif.jtag_stap_smc_tms;
      "jtag_stap_smc_tdo_oen":      return tb_vif.jtag_stap_smc_tdo_oen;
      "jtag_stap_sep_tms":          return tb_vif.jtag_stap_sep_tms;
      "jtag_stap_sep_tdo_oen":      return tb_vif.jtag_stap_sep_tdo_oen;
      "jtag_stap_extra0_tms":       return tb_vif.jtag_stap_extra0_tms;
      "jtag_stap_extra0_tdo_oen":   return tb_vif.jtag_stap_extra0_tdo_oen;
      "jtag_stap_host_select":      return tb_vif.jtag_stap_host_select;
      "jtag_stap_host_shift_en":    return tb_vif.jtag_stap_host_shift_en;
      "jtag_stap_host_capture_en":  return tb_vif.jtag_stap_host_capture_en;
      "jtag_stap_host_update_en":   return tb_vif.jtag_stap_host_update_en;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown scan observable '%s'", name))
        return 1'b0;
      end
    endcase
  endfunction

  // Begin counting high samples of the named observables once per TCK
  // cycle (falling edge, all controls settled).
  task start_scan_window(string signals[$]);
    if (m_win_proc != null) `uvm_fatal(get_type_name(), "scan window monitor is already running")
    m_win_signals = signals;
    m_win_counts.delete();
    foreach (signals[i]) m_win_counts[signals[i]] = 0;
    m_win_edges = 0;
    fork
      begin
        m_win_proc = process::self();
        forever begin
          @(negedge jtag_vif.tck);
          m_win_edges++;
          foreach (m_win_signals[i])
          if (sample_scan_signal(m_win_signals[i])) m_win_counts[m_win_signals[i]]++;
        end
      end
    join_none
  endtask

  // End the window; return the TCK-cycle count and per-signal high counts.
  function void stop_scan_window(output int unsigned edges, output int unsigned counts[string]);
    if (m_win_proc == null) `uvm_fatal(get_type_name(), "scan window monitor was never started")
    m_win_proc.kill();
    m_win_proc = null;
    edges = m_win_edges;
    counts = m_win_counts;
    foreach (counts[name])
      `uvm_info(get_type_name(), $sformatf("scan window %s=%0d/%0d", name, counts[name], edges),
                UVM_MEDIUM)
  endfunction

  // Quiet signals must never pulse inside the window; active ones must.
  function void check_window_counts(int unsigned edges, int unsigned counts[string],
                                    string quiet[$], string active[$], string context_s);
    family_check("CHK-SCAN-WIN", "window edges nonvacuous", 64'(edges > 0), 64'd1, context_s);
    foreach (quiet[i])
    family_check("CHK-SCAN-WIN", {quiet[i], " quiet"}, 64'(counts[quiet[i]]), 64'd0, $sformatf(
                 "%s edges=%0d", context_s, edges));
    foreach (active[i])
    family_check("CHK-SCAN-WIN", {active[i], " active"}, 64'(counts[active[i]] > 0), 64'd1,
                 $sformatf("%s count=%0d/%0d", context_s, counts[active[i]], edges));
  endfunction

  // Stop the running window and apply the quiet/active checks in one step.
  function void check_scan_window(string quiet[$], string active[$], string context_s);
    int unsigned edges;
    int unsigned counts[string];
    stop_scan_window(edges, counts);
    check_window_counts(edges, counts, quiet, active, context_s);
  endfunction

  // --- iJTAG ------------------------------------------------------------------
  static function string ijtag_prefix(int unsigned sib);
    case (sib)
      int'(IJ_DFT_SECURE): return "jtag_dft_secure";
      int'(IJ_DFT):        return "jtag_dft";
      default:             return "jtag_dfd";
    endcase
  endfunction

  static function string ijtag_name(int unsigned sib);
    case (sib)
      int'(IJ_DFT_SECURE): return "dft_secure";
      int'(IJ_DFT):        return "dft";
      default:             return "dfd";
    endcase
  endfunction

  // Update the three iJTAG SIB bits in LSB-first RTL order.
  task program_ijtag_sibs(bit [DtpIjtagSibCount-1:0] pattern, string context_s);
    bit [63:0] unused;
    `uvm_info(get_type_name(), $sformatf("%s SIB pattern=0b%03b", context_s, pattern), UVM_MEDIUM)
    load_ir(6'(SELECT_IJTAG_INSTR));
    shift_dr(64'(pattern), DtpIjtagSibCount, unused);
  endtask

  // Program a SIB pattern under a disable mask and prove the outcome with
  // a temporal window across a second observation scan: a requested-but-
  // gated SIB's scan controls must never pulse, an effective SIB's select
  // must be seen high, and any closed SIB's select stays quiet.
  task check_ijtag_pattern(bit [DtpIjtagSibCount-1:0] pattern,
                           sep_lifecycle_ctrl_pkg::dbg_disable_t d, string context_s);
    bit requested[DtpIjtagSibCount];
    bit gated[DtpIjtagSibCount];
    bit effective[DtpIjtagSibCount];
    int unsigned chain_len;
    string quiet[$], active[$];
    bit [63:0] unused;
    dtp_ijtag_sib_model::state(pattern, d, requested, gated, effective, chain_len);
    `uvm_info(get_type_name(), $sformatf("%s SIB pattern=0b%03b requested=%p gated=%p effective=%p",
                                         context_s, pattern, requested, gated, effective), UVM_LOW)
    set_dbg_disable_full(d);
    program_ijtag_sibs(pattern, {context_s, ".program"});

    for (int unsigned sib = 0; sib < DtpIjtagSibCount; sib++) begin
      if (effective[sib]) active.push_back({ijtag_prefix(sib), "_select"});
      else if (requested[sib] && gated[sib]) begin
        quiet.push_back({ijtag_prefix(sib), "_select"});
        quiet.push_back({ijtag_prefix(sib), "_shift_en"});
        quiet.push_back({ijtag_prefix(sib), "_capture_en"});
        quiet.push_back({ijtag_prefix(sib), "_update_en"});
      end else quiet.push_back({ijtag_prefix(sib), "_select"});
    end
    start_scan_window({quiet, active});
    load_ir(6'(SELECT_IJTAG_INSTR));
    shift_dr(64'(pattern), DtpIjtagSibCount, unused);
    check_scan_window(quiet, active, {context_s, ".window"});
    family_check("CHK-SCAN-OBS", {context_s, ".chain_len"}, 64'(chain_len), 64'd3);
  endtask

  // --- STAP / 3DCR -------------------------------------------------------------
  static function string stap_prefix(int unsigned stap);
    case (stap)
      int'(ST_IO):  return "jtag_stap_io";
      int'(ST_SMC): return "jtag_stap_smc";
      int'(ST_SEP): return "jtag_stap_sep";
      default:      return "jtag_stap_extra0";
    endcase
  endfunction

  static function string stap_name(int unsigned stap);
    case (stap)
      int'(ST_IO):  return "io";
      int'(ST_SMC): return "smc";
      int'(ST_SEP): return "sep";
      default:      return "extra0";
    endcase
  endfunction

  task write_ptap_3dcr(bit config_hold, bit stap_sel, string context_s);
    bit [63:0] value = dtp_stap_3dcr_model::ptap_3dcr_value(config_hold, stap_sel);
    `uvm_info(get_type_name(), $sformatf("%s PTAP_3DCR config_hold=%0d select=%0d raw=0x%0h",
                                         context_s, config_hold, stap_sel, value), UVM_MEDIUM)
    stap_model.update_ptap(value);
    write_tdr64(6'(TAP_3DCR_INSTR), Ptap3dcrWidth, value);
    step(1'b0);
    step(1'b0);
  endtask

  task read_ptap_3dcr(output bit [63:0] observed, input bit [63:0] shift_value = '0);
    read_tdr64(6'(TAP_3DCR_INSTR), Ptap3dcrWidth, observed, shift_value);
  endtask

  // Load TAP_3DCR and zero the whole PTAP+STAP configuration chain.
  task stap_chain_flush(string context_s);
    bit [63:0] unused;
    `uvm_info(get_type_name(), $sformatf("%s flush TAP_3DCR configuration chain", context_s),
              UVM_MEDIUM)
    load_ir(6'(TAP_3DCR_INSTR));
    shift_dr('0, StapChainScanWidth, unused);
    stap_model.flush_scan();
  endtask

  // One composed TAP_3DCR scan driving the full chain state. TAP_3DCR
  // must already be loaded (stap_chain_flush). Negative ptap args and
  // absent associative entries keep stored values, so a bare call is a
  // maintain scan whose captured bits read back the pre-scan chain state.
  task stap_chain_write(input sep_lifecycle_ctrl_pkg::dbg_disable_t d, input int new_ptap_select,
                        input int new_ptap_config_hold, input int new_sib_en[int],
                        input dtp_stap_3dcr_state_t new_payloads[int], input string context_s,
                        output bit [63:0] captured);
    bit [63:0] value = stap_model.compose_scan(
        StapChainScanWidth, d, new_ptap_select, new_ptap_config_hold, new_sib_en, new_payloads
    );
    `uvm_info(get_type_name(), $sformatf("%s TAP_3DCR chain scan value=0x%08h", context_s, value),
              UVM_MEDIUM)
    shift_dr(value, StapChainScanWidth, captured);
    stap_model.apply_scan(d, new_ptap_select, new_ptap_config_hold, new_sib_en, new_payloads);
  endtask

  // State-preserving chain scan; the capture reads back stored state.
  task stap_chain_maintain(input sep_lifecycle_ctrl_pkg::dbg_disable_t d, input string context_s,
                           output bit [63:0] captured);
    int no_sib[int];
    dtp_stap_3dcr_state_t no_pl[int];
    stap_chain_write(d, -1, -1, no_sib, no_pl, context_s, captured);
  endtask

  // Compare a maintain scan's captured bits against the model state.
  // Valid only while the PTAP 3DCR select was already 1 before the scan
  // (otherwise TDO carries the PTAP TDR path, not the chain return).
  function void check_stap_chain_readback(
      bit [63:0] captured, sep_lifecycle_ctrl_pkg::dbg_disable_t d, string context_s);
    bit [63:0] expected, care;
    int unsigned chain_len;
    stap_model.expected_capture(d, expected, care, chain_len);
    family_check("CHK-SCAN-CHAIN", "stap_chain_readback", captured & care, expected & care,
                 $sformatf("%s len=%0d care=0x%0h", context_s, chain_len, care));
  endfunction

  // A selected STAP forwards: tdo_oen pulses during shifts and tms follows
  // the live TMS (mixed samples). A deselected or gated STAP with
  // tms_hold=1 stored parks its tms high and never drives tdo_oen.
  function void check_stap_forwarding(int unsigned edges, int unsigned counts[string],
                                      int unsigned stap, bit forwarding, string context_s);
    string       prefix = stap_prefix(stap);
    int unsigned tdo_oen = counts[{prefix, "_tdo_oen"}];
    int unsigned tms = counts[{prefix, "_tms"}];
    if (forwarding) begin
      family_check("CHK-SCAN-WIN", {prefix, "_tdo_oen forwarding"}, 64'(tdo_oen > 0), 64'd1,
                   $sformatf("%s count=%0d/%0d", context_s, tdo_oen, edges));
      family_check("CHK-SCAN-WIN", {prefix, "_tms follows live TMS"},
                   64'((tms > 0) && (tms < edges)), 64'd1, $sformatf(
                   "%s count=%0d/%0d", context_s, tms, edges));
    end else begin
      family_check("CHK-SCAN-WIN", {prefix, "_tdo_oen quiet"}, 64'(tdo_oen), 64'd0, context_s);
      family_check("CHK-SCAN-WIN", {prefix, "_tms parked at tms_hold=1"}, 64'(tms), 64'(edges),
                   context_s);
    end
  endfunction

  // --- reset helpers with model synchronization --------------------------------
  task apply_tlr();
    goto_tlr_via_tms();
    step(1'b0);
    check_state(RUN_TEST_IDLE, "scan_seq_chk", "after TMS TLR->RTI");
    stap_model.tlr();
  endtask

  task apply_trst();
    set_trst(1'b0, 5);  // assert (active-low pin)
    set_trst(1'b1, 2);  // release
    step(1'b0);
    check_state(RUN_TEST_IDLE, "scan_seq_chk", "after TRST release");
    stap_model.trst();
  endtask

endclass : dtp_scan_base_test_seq
