// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP scan reconstruction: the shared ocah_jtag_scan_builder plus two DTP
// additions read from dtp_tb_if. A power-on reset moves the TAP to
// Test-Logic-Reset without a TCK edge or a TRST event, so the JTAG event
// stream carries nothing the shared builder could react to; the interface's
// assertion counter does. And the DUT exports its TAP state on
// jtag_ptap_state_o: this class counts the TCK cycles that state spends in
// Shift-IR and Shift-DR, one episode per visit, which is the scan length the
// DUT performed rather than the length the driver requested. The scan-length
// and scan-count evidence compares those episodes with the sequence's intent.
// The cocotb twin is env/dtp_jtag_scan_builder.py.

class dtp_jtag_scan_builder extends ocah_jtag_scan_builder;
  `uvm_component_utils(dtp_jtag_scan_builder)

  virtual dtp_tb_if tb_vif;

  // One entry per Shift-IR / Shift-DR visit of the exported TAP state: the
  // TCK cycles the DUT spent there. The DUT moves one bit per cycle in a
  // Shift state, so an episode is the scan length the DUT executed.
  int unsigned dut_ir_shift_lens[$];
  int unsigned dut_dr_shift_lens[$];
  // Every closed episode of each kind and the length of the newest one,
  // counted across the whole run whatever the queues above hold.
  int unsigned dut_ir_episodes;
  int unsigned dut_dr_episodes;
  int unsigned dut_last_ir_len;
  int unsigned dut_last_dr_len;

  protected logic [31:0] m_por_count = '0;
  protected int unsigned m_dut_shift_run;
  protected bit          m_dut_in_shift_ir;
  protected bit          m_dut_in_shift_dr;

  function new(string name = "dtp_jtag_scan_builder", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
  endfunction

  function void write(ocah_jtag_event t);
    if (tb_vif.por_assert_count !== m_por_count) begin
      m_por_count = tb_vif.por_assert_count;
      reset_reconstruction();
      drop_dut_shift_run();
    end
    if (t.kind == OCAH_JTAG_EV_TRST || t.trst_n === 1'b0) drop_dut_shift_run();
    else if (t.kind == OCAH_JTAG_EV_STEP) track_dut_shift();
    super.write(t);
  endfunction

  // Clear the reconstructed items and the DUT episodes together.
  function void clear_scan_history();
    clear_history();
    dut_ir_shift_lens.delete();
    dut_dr_shift_lens.delete();
  endfunction

  // Sample the exported TAP state once per TCK cycle: extend the running
  // Shift episode, or close it into its queue when the DUT left the state.
  protected function void track_dut_shift();
    bit in_ir = dtp_tap_state_is_shift(tb_vif.tap_state, 1'b1);
    bit in_dr = dtp_tap_state_is_shift(tb_vif.tap_state, 1'b0);
    if (m_dut_in_shift_ir && !in_ir) begin
      dut_ir_episodes++;
      dut_last_ir_len = m_dut_shift_run;
      if (dut_ir_shift_lens.size() < max_history) dut_ir_shift_lens.push_back(m_dut_shift_run);
    end
    if (m_dut_in_shift_dr && !in_dr) begin
      dut_dr_episodes++;
      dut_last_dr_len = m_dut_shift_run;
      if (dut_dr_shift_lens.size() < max_history) dut_dr_shift_lens.push_back(m_dut_shift_run);
    end
    if (in_ir || in_dr)
      m_dut_shift_run = ((in_ir == m_dut_in_shift_ir) && (in_dr == m_dut_in_shift_dr)) ?
          m_dut_shift_run + 1 : 1;
    else m_dut_shift_run = 0;
    m_dut_in_shift_ir = in_ir;
    m_dut_in_shift_dr = in_dr;
  endfunction

  // A reset ends any Shift visit without a scan to credit it to.
  protected function void drop_dut_shift_run();
    m_dut_shift_run   = 0;
    m_dut_in_shift_ir = 1'b0;
    m_dut_in_shift_dr = 1'b0;
  endfunction

endclass : dtp_jtag_scan_builder
