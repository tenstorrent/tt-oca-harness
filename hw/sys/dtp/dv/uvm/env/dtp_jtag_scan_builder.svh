// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP scan reconstruction: the shared ocah_jtag_scan_builder plus a
// re-baseline on the bench's power-on reset. A power-on reset moves the TAP
// to Test-Logic-Reset without a TCK edge or a TRST event, so the JTAG event
// stream carries nothing the shared builder could react to; the DTP
// interface's assertion counter does.

class dtp_jtag_scan_builder extends ocah_jtag_scan_builder;
  `uvm_component_utils(dtp_jtag_scan_builder)

  virtual dtp_tb_if tb_vif;

  protected logic [31:0] m_por_count = '0;

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
    end
    super.write(t);
  endfunction

endclass : dtp_jtag_scan_builder
