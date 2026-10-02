// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// xtrig_csr reference model: every OKAY read of a cross-trigger CSR with a
// readback contract (CTM selects, CTP CONFIG and STRETCH_MULT) returns the
// value rebuilt from the writes the passive monitor observed on the XTRIG
// AXI-Lite port, under the register's byte strobes and implemented-bit
// mask, cleared on every system or power-on reset (dtp_tb_if reset
// counters). Consumes the XTRIG monitor stream (write) through a
// dtp_xtrig_csr_model and publishes one dtp_expected_item per observed
// transaction so the scoreboard pairs the two streams in lockstep. An OKAY
// read of a hole reads 0 across the full word; writes, STATUS reads,
// unmapped accesses, and non-OKAY completions carry no contract, and a
// write to a hole leaves the shadow unchanged. No comparison, no reporting.
// In the cocotb realization the scenarios record each CSR readback against
// the written value as CHK-XTRIG-CSR evidence.

class dtp_xtrig_csr_ref_model extends ocah_ref_model #(ocah_axi_item, dtp_expected_item);
  `uvm_component_utils(dtp_xtrig_csr_ref_model)

  virtual dtp_tb_if tb_vif;

  protected dtp_xtrig_csr_model m_model;
  protected bit [31:0]          m_sys_rst_seen;
  protected bit [31:0]          m_por_seen;

  function new(string name = "dtp_xtrig_csr_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    m_model = new();
  endfunction

  function void write(ocah_axi_item t);
    dtp_xtrig_csr_kind_e kind;
    bit [31:0]           mask;
    dtp_expected_item    exp = dtp_expected_item::type_id::create("exp");
    exp.timestamp = t.end_time;
    exp.compare   = 1'b0;
    sync_reset();
    kind = dtp_xtrig_csr_decode(t.address, mask);
    if ((kind == DTP_XTRIG_CSR_UNMAPPED) || (kind == DTP_XTRIG_CSR_CTP_STATUS) ||
            !t.is_ok() || (t.data_words.size() == 0)) begin
      expected_ap.write(exp);
      return;
    end
    if (kind == DTP_XTRIG_CSR_HOLE) begin
      if (t.direction != OCAH_AXI_DIR_WRITE) begin
        exp.compare   = 1'b1;
        exp.mask      = 64'hFFFF_FFFF;
        exp.expected  = '0;
        exp.context_s = $sformatf("%s addr=0x%03h", kind.name(), t.address);
      end
      expected_ap.write(exp);
      return;
    end
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      bit [7:0] strb = (t.strobes.size() != 0) ? t.strobes[0] : 8'hFF;
      m_model.write(t.address, t.data_words[0][31:0], strb[3:0], mask, dtp_xtrig_csr_default(kind));
      expected_ap.write(exp);
      return;
    end
    exp.compare   = 1'b1;
    exp.mask      = 64'(mask);
    exp.expected  = 64'(m_model.read(t.address, mask, dtp_xtrig_csr_default(kind)));
    exp.context_s = $sformatf("%s addr=0x%03h", kind.name(), t.address);
    expected_ap.write(exp);
  endfunction

  // Every system or power-on reset clears the CSR block.
  protected function void sync_reset();
    if ((tb_vif.sys_rst_assert_count === m_sys_rst_seen) &&
            (tb_vif.por_assert_count === m_por_seen))
      return;
    m_sys_rst_seen = tb_vif.sys_rst_assert_count;
    m_por_seen     = tb_vif.por_assert_count;
    m_model.clear();
  endfunction

endclass : dtp_xtrig_csr_ref_model
