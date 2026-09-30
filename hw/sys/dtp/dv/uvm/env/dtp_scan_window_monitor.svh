// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Temporal scan-control window monitor: counts high samples of named
// dtp_scan_if scan observables once per TCK cycle while a window is open, so
// a gated resource proves ZERO control pulses across a whole scan and an
// enabled one proves the expected pulses occurred (post-scan snapshots
// cannot). Samples ride the shared JTAG monitor's STEP events, which land
// on the falling TCK edge where every control has settled: the same
// one-sample-per-cycle semantics as the cocotb post-edge ReadOnly monitor
// (env/dtp_scan_window_monitor.py). One window at a time; the scan
// scenarios open it around one composed scan and close it before judging.
// A window holds the TCK cycles whose rising edge follows its opening. The
// driver returns from an operation before that operation's last TCK fall,
// so the STEP published in the time step the window opens belongs to the
// cycle before it, and closing a window first waits for the STEP of every
// cycle that rose inside it (close_window).
// Alongside the pin counts it counts the cycles the DUT's exported TAP state
// spent in Shift-DR or Shift-IR, the DUT-side witness that the window
// covered a scan, and classifies each sample by that exported state: the
// samples in Capture-DR through Update-DR, and those in Run-Test/Idle, each
// with every observable's high count among them; it keeps the state and the
// observable values of the latest sample too. Publishes nothing and checks
// nothing: the scenario reads the counts and records the evidence.

class dtp_scan_window_monitor extends ocah_subscriber #(ocah_jtag_event);
  `uvm_component_utils(dtp_scan_window_monitor)

  // Handed by dtp_env: the scan-control observables, the TAP state, and the
  // primary TAP pins whose TCK the STEP events follow.
  virtual dtp_scan_if  scan_vif;
  virtual dtp_tb_if    tb_vif;
  virtual ocah_jtag_if jtag_vif;

  protected bit          m_active;
  protected string       m_signals[$];
  protected int unsigned m_counts[string];
  protected int unsigned m_rises;
  protected int unsigned m_edges;
  protected int unsigned m_dut_shift_cycles;
  protected int unsigned m_dr_scan_edges;
  protected int unsigned m_dr_scan_counts[string];
  protected int unsigned m_rti_edges;
  protected int unsigned m_rti_counts[string];
  protected logic [15:0] m_final_state;
  protected bit          m_final_high[string];
  protected bit          m_x_reported[string];

  function new(string name = "dtp_scan_window_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (scan_vif == null)
      `uvm_fatal(get_type_name(), "virtual dtp_scan_if `scan_vif` not set by the env")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    if (jtag_vif == null)
      `uvm_fatal(get_type_name(), "virtual ocah_jtag_if `jtag_vif` not set by the env")
  endfunction

  // TCK rising edges while the window is open; each one's STEP publishes at
  // the falling edge that follows.
  task run_phase(uvm_phase phase);
    forever begin
      @(posedge jtag_vif.tck);
      if (m_active) m_rises++;
    end
  endtask

  // The DR-column states in which the selected data register captures,
  // shifts, and updates.
  static function bit tap_state_in_dr_scan(logic [15:0] state);
    if ($isunknown(state)) return 1'b0;
    return state inside {CAPTURE_DR, SHIFT_DR, EXIT1_DR, PAUSE_DR, EXIT2_DR, UPDATE_DR};
  endfunction

  // One sample per TCK cycle while the window is open. An observable that
  // samples X is an error once per window: the counts would otherwise read
  // it as low.
  function void write(ocah_jtag_event t);
    bit in_dr_scan, in_rti;
    if (!m_active || t.kind != OCAH_JTAG_EV_STEP || m_edges >= m_rises) return;
    m_edges++;
    if (dtp_tap_state_is_shift(
            tb_vif.tap_state, 1'b0
        ) || dtp_tap_state_is_shift(
            tb_vif.tap_state, 1'b1
        ))
      m_dut_shift_cycles++;
    in_dr_scan = tap_state_in_dr_scan(tb_vif.tap_state);
    in_rti = (tb_vif.tap_state === RUN_TEST_IDLE);
    if (in_dr_scan) m_dr_scan_edges++;
    if (in_rti) m_rti_edges++;
    m_final_state = tb_vif.tap_state;
    foreach (m_signals[i]) begin
      logic sampled = sample_scan_signal(m_signals[i]);
      m_final_high[m_signals[i]] = (sampled === 1'b1);
      if ($isunknown(sampled)) begin
        if (!m_x_reported.exists(m_signals[i])) begin
          m_x_reported[m_signals[i]] = 1'b1;
          `uvm_error(get_type_name(), $sformatf("scan observable %s sampled X inside a window",
                                                m_signals[i]))
        end
      end else if (sampled) begin
        m_counts[m_signals[i]]++;
        if (in_dr_scan) m_dr_scan_counts[m_signals[i]]++;
        if (in_rti) m_rti_counts[m_signals[i]]++;
      end
    end
  endfunction

  function bit is_active();
    return m_active;
  endfunction

  // Begin counting high samples of the named observables.
  function void start_window(string signals[$]);
    if (m_active) `uvm_fatal(get_type_name(), "scan window is already open")
    m_signals = signals;
    m_counts.delete();
    m_dr_scan_counts.delete();
    m_rti_counts.delete();
    m_final_high.delete();
    m_x_reported.delete();
    foreach (signals[i]) begin
      m_counts[signals[i]]         = 0;
      m_dr_scan_counts[signals[i]] = 0;
      m_rti_counts[signals[i]]     = 0;
    end
    m_rises            = 0;
    m_edges            = 0;
    m_dut_shift_cycles = 0;
    m_dr_scan_edges    = 0;
    m_rti_edges        = 0;
    m_final_state      = '0;
    m_active           = 1'b1;
  endfunction

  // End the window once the STEP of every TCK cycle that rose inside it has
  // arrived; return the TCK-cycle count and per-signal high counts.
  task close_window(output int unsigned edges, output int unsigned counts[string]);
    if (!m_active) `uvm_fatal(get_type_name(), "scan window was never opened")
    wait (m_edges >= m_rises);
    stop_window(edges, counts);
  endtask

  // End the window; return the TCK-cycle count and per-signal high counts.
  function void stop_window(output int unsigned edges, output int unsigned counts[string]);
    if (!m_active) `uvm_fatal(get_type_name(), "scan window was never opened")
    m_active = 1'b0;
    edges    = m_edges;
    counts   = m_counts;
    foreach (counts[name])
      `uvm_info(get_type_name(), $sformatf(
                "scan window %s=%0d/%0d dr_scan=%0d/%0d rti=%0d/%0d",
                name,
                counts[name],
                edges,
                m_dr_scan_counts[name],
                m_dr_scan_edges,
                m_rti_counts[name],
                m_rti_edges
                ), UVM_MEDIUM)
    `uvm_info(get_type_name(), $sformatf(
              "scan window dut_shift_cycles=%0d/%0d", m_dut_shift_cycles, edges), UVM_MEDIUM)
  endfunction

  // TCK cycles of the last closed window in which the DUT's exported TAP
  // state was Shift-DR or Shift-IR.
  function int unsigned last_dut_shift_cycles();
    return m_dut_shift_cycles;
  endfunction

  // Samples of the last closed window whose exported TAP state was
  // Capture-DR through Update-DR, and one observable's high count among
  // them.
  function int unsigned last_dr_scan_edges();
    return m_dr_scan_edges;
  endfunction

  function int unsigned last_dr_scan_count(string name);
    return m_dr_scan_counts.exists(name) ? m_dr_scan_counts[name] : 0;
  endfunction

  // One observable's high count among the samples of the last closed window
  // whose exported TAP state was Run-Test/Idle.
  function int unsigned last_rti_count(string name);
    return m_rti_counts.exists(name) ? m_rti_counts[name] : 0;
  endfunction

  // Exported TAP state and one observable's value at the final sample of the
  // last closed window.
  function logic [15:0] last_final_state();
    return m_final_state;
  endfunction

  function bit last_final_high(string name);
    return m_final_high.exists(name) ? m_final_high[name] : 1'b0;
  endfunction

  // Named scan observable (boundary-scan controls, iJTAG SIB controls, STAP
  // forwarding pins and their TMS mismatch flags, STAP host scan controls),
  // four-state as sampled.
  function logic sample_scan_signal(string name);
    case (name)
      "jtag_bsr_select":            return scan_vif.jtag_bsr_select;
      "jtag_bsr_shift_en":          return scan_vif.jtag_bsr_shift_en;
      "jtag_bsr_capture_en":        return scan_vif.jtag_bsr_capture_en;
      "jtag_bsr_update_en":         return scan_vif.jtag_bsr_update_en;
      "jtag_bsr_run_test_idle":     return scan_vif.jtag_bsr_run_test_idle;
      "jtag_bsr_test_logic_reset":  return scan_vif.jtag_bsr_test_logic_reset;
      "jtag_bsr_runbist":           return scan_vif.jtag_bsr_runbist;
      "jtag_bsr_chrst_n":           return scan_vif.jtag_bsr_chrst_n;
      "jtag_dft_secure_select":     return scan_vif.jtag_dft_secure_select;
      "jtag_dft_secure_shift_en":   return scan_vif.jtag_dft_secure_shift_en;
      "jtag_dft_secure_capture_en": return scan_vif.jtag_dft_secure_capture_en;
      "jtag_dft_secure_update_en":  return scan_vif.jtag_dft_secure_update_en;
      "jtag_dft_select":            return scan_vif.jtag_dft_select;
      "jtag_dft_shift_en":          return scan_vif.jtag_dft_shift_en;
      "jtag_dft_capture_en":        return scan_vif.jtag_dft_capture_en;
      "jtag_dft_update_en":         return scan_vif.jtag_dft_update_en;
      "jtag_dft_run_test_idle":     return scan_vif.jtag_dft_run_test_idle;
      "jtag_dft_test_logic_reset":  return scan_vif.jtag_dft_test_logic_reset;
      "jtag_dft_runbist":           return scan_vif.jtag_dft_runbist;
      "jtag_dfd_select":            return scan_vif.jtag_dfd_select;
      "jtag_dfd_shift_en":          return scan_vif.jtag_dfd_shift_en;
      "jtag_dfd_capture_en":        return scan_vif.jtag_dfd_capture_en;
      "jtag_dfd_update_en":         return scan_vif.jtag_dfd_update_en;
      "jtag_stap_io_tms":           return scan_vif.jtag_stap_io_tms;
      "jtag_stap_io_tdo_oen":       return scan_vif.jtag_stap_io_tdo_oen;
      "jtag_stap_smc_tms":          return scan_vif.jtag_stap_smc_tms;
      "jtag_stap_smc_tdo_oen":      return scan_vif.jtag_stap_smc_tdo_oen;
      "jtag_stap_sep_tms":          return scan_vif.jtag_stap_sep_tms;
      "jtag_stap_sep_tdo_oen":      return scan_vif.jtag_stap_sep_tdo_oen;
      "jtag_stap_extra0_tms":       return scan_vif.jtag_stap_extra0_tms;
      "jtag_stap_extra0_tdo_oen":   return scan_vif.jtag_stap_extra0_tdo_oen;
      "jtag_stap_io_tms_mismatch":     return scan_vif.jtag_stap_io_tms_mismatch;
      "jtag_stap_smc_tms_mismatch":    return scan_vif.jtag_stap_smc_tms_mismatch;
      "jtag_stap_sep_tms_mismatch":    return scan_vif.jtag_stap_sep_tms_mismatch;
      "jtag_stap_extra0_tms_mismatch": return scan_vif.jtag_stap_extra0_tms_mismatch;
      "jtag_stap_io_trst_n":        return scan_vif.jtag_stap_io_trst_n;
      "jtag_stap_smc_trst_n":       return scan_vif.jtag_stap_smc_trst_n;
      "jtag_stap_sep_trst_n":       return scan_vif.jtag_stap_sep_trst_n;
      "jtag_stap_extra0_trst_n":    return scan_vif.jtag_stap_extra0_trst_n;
      "jtag_stap_host_select":      return scan_vif.jtag_stap_host_select;
      "jtag_stap_host_shift_en":    return scan_vif.jtag_stap_host_shift_en;
      "jtag_stap_host_capture_en":  return scan_vif.jtag_stap_host_capture_en;
      "jtag_stap_host_update_en":   return scan_vif.jtag_stap_host_update_en;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown scan observable '%s'", name))
        return 1'b0;
      end
    endcase
  endfunction

endclass : dtp_scan_window_monitor
