// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// PTAP 3DCR + STAP configuration chain + downstream TAP reference model
// (env/dtp_scan_ref_model.py parity). The TAP_3DCR data register is the
// 2-bit PTAP 3DCR followed serially by the STAP configuration chain (IEEE
// 1838 Section 5.4): one SIB flop per STAP, with the STAP's 3-bit 3DCR
// spliced TDI-side of its SIB while the SIB is open. Scan registers shift
// MSB-first, so within each register the MSB field is TDI-nearest. A
// selected STAP splices its host port into the chain: the downstream TAP's
// IR (IR scans) or selected data register (DR scans) when a device is
// attached, and one extra full-cycle flop on ports with a TDI lockup latch
// (the I/O STAP). The PTAP forwards its scan controls to the STAP chain on
// every IR and DR scan only while the PTAP 3DCR select is set, and then
// routes the instruction register's scan-out into the chain, so an IR scan
// is the 6-bit PTAP IR followed by the STAP chain and Update-IR commits
// SIB/3DCR fields and the downstream IRs exactly as Update-DR does. A data
// scan under any other PTAP instruction runs through the STAP chain as well
// while the select is set, and its Update-DR commits the chain fields
// without reaching the PTAP 3DCR: under BYPASS the one-bit bypass register,
// which captures 0, precedes the chain (DTP_SCAN_BYPASS), and
// ZERO_LENGTH_BYPASS (DTP_SCAN_ZLB) is BYPASS while the select is set; with
// the select clear it is the zero-length TDI-to-TDO path. An attached host
// segment (tb_top) follows the last STAP, at the TDO end of every scan,
// while stap_host is enabled; with
// stap_host disabled the last STAP's scan-out is the chain return and the
// segment holds its value. While the PTAP select is clear the chain, host
// segment included, holds through every scan and a scan covers only the
// PTAP segment, so the select must be set by a scan of its own before a
// scan can write the chain. Plain model class, built with new(); no
// reporting. Types come from dtp_types.svh.

// Reference state for the PTAP 3DCR, the STAP 3DCRs, and downstream TAPs.
class dtp_stap_3dcr_model;

  typedef enum int unsigned {
    FLD_STAP_SEL,
    FLD_CONFIG_HOLD,
    FLD_TMS_HOLD,
    FLD_SIB,
    FLD_SPLICE,
    FLD_IR,           // PTAP instruction register bit (IR scans)
    FLD_DS,           // downstream TAP segment bit
    FLD_HOST_SEGMENT, // host segment bit
    FLD_BYPASS        // PTAP bypass register bit (BYPASS data scans)
  } field_e;

  // layout_entry_t.owner of the host segment's flops.
  localparam int HostSegmentOwner = int'(DtpStapCount);

  typedef struct {
    int          owner;    // -1 = PTAP, HostSegmentOwner, otherwise dtp_stap_e index
    field_e      field;
    int unsigned bit_idx;  // FLD_IR / FLD_DS / FLD_HOST_SEGMENT: bit of the segment value
  } layout_entry_t;

  // Extra full-cycle flops a STAP's selected splice inserts into the chain.
  protected static function int unsigned splice_extra(int unsigned stap);
    return (stap == int'(ST_IO)) ? 1 : 0;
  endfunction

  bit ptap_config_hold;
  bit ptap_select;
  dtp_stap_3dcr_state_t staps[DtpStapCount];
  bit sib_en[DtpStapCount];
  // Downstream TAPs (null = no device behind that STAP host port).
  dtp_stap_ds_state ds[DtpStapCount];
  bit host_segment_attached;
  // The host segment's update register; every capture presents it.
  bit [DtpStapHostSegmentWidth-1:0] host_segment;

  function new();
    trst();
  endfunction

  // --- extended STAP host segment ---------------------------------------------
  // Place the bench's host segment behind the extended STAP host scan
  // interface.
  function void attach_host_segment();
    host_segment_attached = 1'b1;
    host_segment          = '0;
  endfunction

  // True while the host segment is the chain return: attached and stap_host
  // enabled.
  function bit host_segment_in_chain(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    return host_segment_attached && !dtp_dbg_path_disabled(d, DTP_DBG_PATH_STAP_HOST);
  endfunction

  // Update-x for the host segment: a new value (non-negative) lands only when
  // the segment was in the chain during the scan.
  protected function void latch_host_segment(bit in_chain, int new_host_segment);
    if (in_chain && new_host_segment >= 0)
      host_segment = DtpStapHostSegmentWidth'(new_host_segment);
  endfunction

  // Per-STAP gate state from the direct disables (1 = STAP gated).
  static function void gates(sep_lifecycle_ctrl_pkg::dbg_disable_t d, output bit g[DtpStapCount]);
    for (int unsigned s = 0; s < DtpStapCount; s++)
    g[s] = dtp_dbg_path_disabled(d, dtp_stap_dbg_path(s));
  endfunction

  // --- downstream TAPs -------------------------------------------------------
  // Seed the downstream TAP behind STAP `stap` from its device configuration.
  function void attach(int unsigned stap, ocah_jtag_slave_config cfg);
    if (stap >= DtpStapCount)
      `uvm_fatal("dtp_stap_3dcr_model", $sformatf("unknown STAP index %0d", stap))
    ds[stap] = new(cfg);
  endfunction

  function bit attached(int unsigned stap);
    return (stap < DtpStapCount) && (ds[stap] != null);
  endfunction

  // True while STAP `stap` is selected and ungated (its host port is in the chain).
  function bit spliced(int unsigned stap, sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    bit g[DtpStapCount];
    gates(d, g);
    return staps[stap].stap_sel && !g[stap];
  endfunction

  // Attached STAPs whose downstream TAP is currently in the chain.
  function void spliced_downstream(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                   ref int unsigned list[$]);
    list.delete();
    for (int unsigned s = 0; s < DtpStapCount; s++)
    if (attached(s) && spliced(s, d)) list.push_back(s);
  endfunction

  // A deselected or gated STAP parks its host TMS at the stored tms_hold:
  // parked high, the downstream TAP walks into Test-Logic-Reset (IDCODE
  // selected) within five TCKs; parked low it idles in Run-Test/Idle and
  // keeps its instruction.
  protected function void park_downstream(bit g[DtpStapCount]);
    for (int unsigned s = 0; s < DtpStapCount; s++)
    if (ds[s] != null && (g[s] || !staps[s].stap_sel) && staps[s].tms_hold)
      ds[s].reset_instruction();
  endfunction

  // True when the next scan moves the STAP chain (PTAP select set). A STAP
  // left selected while the PTAP select is clear still forwards the live TMS
  // and scan data to its downstream TAP, whose registers the model does not
  // predict, so such a scan is fatal.
  protected function bit chain_live(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    int unsigned spliced_list[$];
    if (ptap_select) return 1'b1;
    spliced_downstream(d, spliced_list);
    if (spliced_list.size() != 0)
      `uvm_fatal(
          "dtp_stap_3dcr_model", $sformatf(
          "scan with the PTAP select clear while downstream TAPs %p are spliced", spliced_list))
    return 1'b0;
  endfunction

  // --- composed-chain layout -------------------------------------------------
  // (owner, field, bit) per chain flop in TDI-to-TDO order, current state.
  // With the PTAP select clear the chain is out of the scan path, and a
  // DTP_SCAN_ZLB layout is empty.
  function void chain_layout(sep_lifecycle_ctrl_pkg::dbg_disable_t d, ref layout_entry_t layout[$],
                             input dtp_scan_kind_e kind = DTP_SCAN_DR);
    bit g[DtpStapCount];
    gates(d, g);
    layout.delete();
    if (kind == DTP_SCAN_IR) begin
      for (int b = DtpPtapIrWidth - 1; b >= 0; b--) layout.push_back('{-1, FLD_IR, b});
    end else if (kind == DTP_SCAN_DR) begin
      layout.push_back('{-1, FLD_STAP_SEL, 0});
      layout.push_back('{-1, FLD_CONFIG_HOLD, 0});
    end else if (kind == DTP_SCAN_BYPASS || (kind == DTP_SCAN_ZLB && ptap_select)) begin
      layout.push_back('{-1, FLD_BYPASS, 0});
    end
    if (!ptap_select) return;
    for (int unsigned s = 0; s < DtpStapCount; s++) begin
      if (staps[s].stap_sel && !g[s]) begin
        if (ds[s] != null)
          for (int b = ds[s].selected_width(kind) - 1; b >= 0; b--)
          layout.push_back('{int'(s), FLD_DS, b});
        repeat (splice_extra(s)) layout.push_back('{int'(s), FLD_SPLICE, 0});
      end
      if (sib_en[s]) begin
        layout.push_back('{int'(s), FLD_TMS_HOLD, 0});
        layout.push_back('{int'(s), FLD_STAP_SEL, 0});
        layout.push_back('{int'(s), FLD_CONFIG_HOLD, 0});
      end
      layout.push_back('{int'(s), FLD_SIB, 0});
    end
    if (host_segment_in_chain(d))
      for (int b = DtpStapHostSegmentWidth - 1; b >= 0; b--)
      layout.push_back('{HostSegmentOwner, FLD_HOST_SEGMENT, b});
  endfunction

  protected function bit field_value(
      layout_entry_t entry, dtp_scan_kind_e kind, int new_ptap_select, int new_ptap_config_hold,
      bit [63:0] ptap_instr, int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int],
      bit [63:0] new_ds_values[int], int new_host_segment);
    bit eff_ptap_sel  = (new_ptap_select < 0) ? ptap_select
                                                  : bit'(new_ptap_select);
    bit eff_ptap_hold = (new_ptap_config_hold < 0) ? ptap_config_hold
                                                       : bit'(new_ptap_config_hold);
    bit [63:0] seg;
    if (entry.owner < 0) begin
      if (entry.field == FLD_IR) return ptap_instr[entry.bit_idx];
      if (entry.field == FLD_BYPASS) return 1'b0;
      return (entry.field == FLD_STAP_SEL) ? eff_ptap_sel : eff_ptap_hold;
    end
    if (entry.field == FLD_HOST_SEGMENT) begin
      seg = (new_host_segment < 0) ? 64'(host_segment) : 64'(new_host_segment);
      return seg[entry.bit_idx];
    end
    case (entry.field)
      FLD_SIB:
                return new_sib_en.exists(entry.owner)
                     ? bit'(new_sib_en[entry.owner]) : sib_en[entry.owner];
      FLD_SPLICE:
                return 1'b0;
      FLD_DS: begin
                seg = new_ds_values.exists(entry.owner)
                    ? new_ds_values[entry.owner] : ds[entry.owner].shift_default(kind);
                return seg[entry.bit_idx];
            end
      FLD_TMS_HOLD:
                return new_payloads.exists(entry.owner)
                     ? new_payloads[entry.owner].tms_hold
                     : staps[entry.owner].tms_hold;
      FLD_STAP_SEL:
                return new_payloads.exists(entry.owner)
                     ? new_payloads[entry.owner].stap_sel
                     : staps[entry.owner].stap_sel;
      default:
                return new_payloads.exists(entry.owner)
                     ? new_payloads[entry.owner].config_hold
                     : staps[entry.owner].config_hold;
    endcase
  endfunction

  protected function bit [63:0] compose(
      ref layout_entry_t layout[$], input int unsigned width, input dtp_scan_kind_e kind,
      input int new_ptap_select, input int new_ptap_config_hold, input bit [63:0] ptap_instr,
      input int new_sib_en[int], input dtp_stap_3dcr_state_t new_payloads[int],
      input bit [63:0] new_ds_values[int], input int new_host_segment);
    bit [63:0] value = '0;
    if (width < layout.size())
      `uvm_fatal("dtp_stap_3dcr_model", $sformatf(
                 "scan width %0d < chain length %0d", width, layout.size()))
    foreach (layout[depth])
    if (field_value(
            layout[depth],
            kind,
            new_ptap_select,
            new_ptap_config_hold,
            ptap_instr,
            new_sib_en,
            new_payloads,
            new_ds_values,
            new_host_segment
        ))
      value |= 64'h1 << (width - 1 - depth);
    return value;
  endfunction

  // Data scan value that writes the given end-state through the current
  // chain: a TAP_3DCR scan, or with kind DTP_SCAN_ZLB or DTP_SCAN_BYPASS a
  // scan under that PTAP instruction, whose layout holds no PTAP 3DCR
  // field. Negative ptap args, a negative new_host_segment, and absent
  // associative entries keep stored values; a spliced downstream register
  // re-latches its stored value unless new_ds_values names a new one. The
  // layout is the chain as it exists during the scan (updates land at
  // Update-DR).
  function bit [63:0] compose_scan_ds(
      int unsigned width, sep_lifecycle_ctrl_pkg::dbg_disable_t d, int new_ptap_select,
      int new_ptap_config_hold, int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int],
      bit [63:0] new_ds_values[int], int new_host_segment = -1, dtp_scan_kind_e kind = DTP_SCAN_DR);
    layout_entry_t layout[$];
    chain_layout(d, layout, kind);
    return compose(
        layout,
        width,
        kind,
        new_ptap_select,
        new_ptap_config_hold,
        '0,
        new_sib_en,
        new_payloads,
        new_ds_values,
        new_host_segment
    );
  endfunction

  function bit [63:0] compose_scan(int unsigned width, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                   int new_ptap_select, int new_ptap_config_hold,
                                   int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int]);
    bit [63:0] no_ds[int];
    return compose_scan_ds(
        width, d, new_ptap_select, new_ptap_config_hold, new_sib_en, new_payloads, no_ds
    );
  endfunction

  // Instruction scan value over the full network: the PTAP IR segment
  // first, then the STAP chain with each spliced downstream TAP's IR
  // (new_ds_ir names new instructions; others keep the active one).
  function bit [63:0] compose_ir_scan(int unsigned width, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                      bit [63:0] ptap_instr, bit [63:0] new_ds_ir[int],
                                      int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int],
                                      int new_host_segment = -1);
    layout_entry_t layout[$];
    chain_layout(d, layout, DTP_SCAN_IR);
    return compose(
        layout,
        width,
        DTP_SCAN_IR,
        -1,
        -1,
        ptap_instr,
        new_sib_en,
        new_payloads,
        new_ds_ir,
        new_host_segment
    );
  endfunction

  // Update-x for the STAP fields: a gated STAP ignores its 3DCR payload
  // write; SIB bits always update; payload flops were in the chain only if
  // the SIB was open during the scan (pre-update state).
  protected function void apply_chain_update(bit g[DtpStapCount], bit in_chain[DtpStapCount],
                                             int new_sib_en[int],
                                             dtp_stap_3dcr_state_t new_payloads[int]);
    foreach (new_sib_en[s]) if (s >= 0 && s < int'(DtpStapCount)) sib_en[s] = bit'(new_sib_en[s]);
    foreach (new_payloads[s])
    if (s >= 0 && s < int'(DtpStapCount) && !g[s] && in_chain[s]) staps[s] = new_payloads[s];
  endfunction

  // Commit a composed data scan's Update-DR: a TAP_3DCR scan updates the
  // PTAP 3DCR, and a scan under another instruction passes negative ptap
  // args and leaves the PTAP 3DCR as it is; SIB/3DCR fields per the gating
  // rules; a spliced downstream TAP latches its (writable) selected
  // register, and the host segment its value; deselected or gated ports
  // park their downstream TAP. The chain fields, downstream TAPs and host
  // segment take part only when the PTAP select was set before the scan.
  function void apply_scan_ds(sep_lifecycle_ctrl_pkg::dbg_disable_t d, int new_ptap_select,
                              int new_ptap_config_hold, int new_sib_en[int],
                              dtp_stap_3dcr_state_t new_payloads[int],
                              bit [63:0] new_ds_values[int], int new_host_segment = -1);
    bit g[DtpStapCount];
    bit in_chain[DtpStapCount];
    int unsigned spliced_list[$];
    bit segment_in_chain = host_segment_in_chain(d);
    bit live = chain_live(d);
    gates(d, g);
    for (int unsigned s = 0; s < DtpStapCount; s++) in_chain[s] = sib_en[s];
    spliced_downstream(d, spliced_list);
    if (new_ptap_select >= 0) ptap_select = bit'(new_ptap_select);
    if (new_ptap_config_hold >= 0) ptap_config_hold = bit'(new_ptap_config_hold);
    if (live) begin
      apply_chain_update(g, in_chain, new_sib_en, new_payloads);
      foreach (spliced_list[i]) begin
        int unsigned s = spliced_list[i];
        ds[s].latch(new_ds_values.exists(int'(s)) ? new_ds_values[int'(s)] : ds[s].shift_default(
                    DTP_SCAN_DR));
      end
      latch_host_segment(segment_in_chain, new_host_segment);
    end
    park_downstream(g);
  endfunction

  function void apply_scan(sep_lifecycle_ctrl_pkg::dbg_disable_t d, int new_ptap_select,
                           int new_ptap_config_hold, int new_sib_en[int],
                           dtp_stap_3dcr_state_t new_payloads[int]);
    bit [63:0] no_ds[int];
    apply_scan_ds(d, new_ptap_select, new_ptap_config_hold, new_sib_en, new_payloads, no_ds);
  endfunction

  // Commit a composed instruction scan's Update-IR: SIB/3DCR fields per
  // the gating rules (the PTAP 3DCR is untouched), each spliced downstream
  // TAP takes its new instruction, the host segment latches as for a data
  // scan, then parking as for a data scan.
  function void apply_ir_scan(sep_lifecycle_ctrl_pkg::dbg_disable_t d, bit [63:0] new_ds_ir[int],
                              int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int],
                              int new_host_segment = -1);
    bit g[DtpStapCount];
    bit in_chain[DtpStapCount];
    int unsigned spliced_list[$];
    bit segment_in_chain = host_segment_in_chain(d);
    gates(d, g);
    if (chain_live(d)) begin
      for (int unsigned s = 0; s < DtpStapCount; s++) in_chain[s] = sib_en[s];
      spliced_downstream(d, spliced_list);
      apply_chain_update(g, in_chain, new_sib_en, new_payloads);
      foreach (spliced_list[i]) begin
        int unsigned s = spliced_list[i];
        if (new_ds_ir.exists(int'(s))) ds[s].update_ir(new_ds_ir[int'(s)]);
      end
      latch_host_segment(segment_in_chain, new_host_segment);
    end
    park_downstream(g);
  endfunction

  // Commit an all-zero over-length data scan: the PTAP 3DCR cleared and,
  // when the PTAP select was set before the scan, every in-chain field
  // cleared and a spliced downstream's writable register and the host
  // segment latched to zero.
  function void flush_scan(sep_lifecycle_ctrl_pkg::dbg_disable_t d = '0);
    int unsigned spliced_list[$];
    if (chain_live(d)) begin
      spliced_downstream(d, spliced_list);
      foreach (spliced_list[i]) ds[spliced_list[i]].latch('0);
      latch_host_segment(host_segment_in_chain(d), 0);
      for (int unsigned s = 0; s < DtpStapCount; s++) begin
        sib_en[s] = 1'b0;
        staps[s]  = '{1'b0, 1'b0, 1'b0};
      end
    end
    ptap_select      = 1'b0;
    ptap_config_hold = 1'b0;
  endfunction

  // (expected, care_mask, chain_len) for a readback with PTAP select=1.
  // Captured bit j of the TDO stream is the flop at depth chain_len-1-j.
  // Splice flops capture unknown data and the PTAP IR capture is
  // design-specific: both are masked out. A downstream segment captures
  // the device's IDCODE, its stored register, zero for BYPASS, or the
  // IEEE 1149.1 IR capture on an IR scan; the host segment captures its
  // update register, and the PTAP bypass register 0. A STAP captures its
  // masked stap_sel: 0 while its disable is asserted, even though the
  // stored bit survives the gate.
  function void expected_capture(
      sep_lifecycle_ctrl_pkg::dbg_disable_t d, output bit [63:0] expected, output bit [63:0] care,
      output int unsigned chain_len, input dtp_scan_kind_e kind = DTP_SCAN_DR);
    layout_entry_t layout[$];
    int unsigned bit_pos;
    int no_sib[int];
    dtp_stap_3dcr_state_t no_pl[int];
    bit [63:0] no_ds[int];
    bit [63:0] ds_cap[DtpStapCount];
    bit g[DtpStapCount];
    bit value;
    gates(d, g);
    chain_layout(d, layout, kind);
    for (int unsigned s = 0; s < DtpStapCount; s++)
    ds_cap[s] = (ds[s] != null) ? ds[s].capture(kind) : '0;
    chain_len = layout.size();
    expected  = '0;
    care      = '0;
    foreach (layout[depth]) begin
      bit_pos = chain_len - 1 - depth;
      if (layout[depth].field == FLD_SPLICE || layout[depth].field == FLD_IR) continue;
      care |= 64'h1 << bit_pos;
      if (layout[depth].field == FLD_DS) value = ds_cap[layout[depth].owner][layout[depth].bit_idx];
      else begin
        value = field_value(layout[depth], kind, -1, -1, '0, no_sib, no_pl, no_ds, -1);
        if (layout[depth].owner >= 0 &&
                    layout[depth].field == FLD_STAP_SEL && g[layout[depth].owner])
          value = 1'b0;
      end
      if (value) expected |= 64'h1 << bit_pos;
    end
  endfunction

  // (lsb, width) of STAP `stap`'s downstream segment inside a capture of
  // the current chain, so (captured >> lsb) & mask is the register value
  // in natural bit order.
  function void ds_capture_slice(int unsigned stap, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                 dtp_scan_kind_e kind, output int unsigned lsb,
                                 output int unsigned width);
    layout_entry_t layout[$];
    int max_depth = -1;
    chain_layout(d, layout, kind);
    width = 0;
    foreach (layout[depth])
    if (layout[depth].owner == int'(stap) && layout[depth].field == FLD_DS) begin
      width++;
      if (depth > max_depth) max_depth = depth;
    end
    if (width == 0)
      `uvm_fatal("dtp_stap_3dcr_model", $sformatf(
                 "STAP %0d has no downstream TAP in the chain", stap))
    lsb = layout.size() - 1 - max_depth;
  endfunction

  // PTAP 3DCR is LSB-first: config_hold then stap_select.
  static function bit [63:0] ptap_3dcr_value(bit config_hold, bit stap_sel);
    return {62'b0, stap_sel, config_hold};
  endfunction

  function void update_ptap(bit [63:0] value);
    ptap_config_hold = value[0];
    ptap_select      = value[1];
  endfunction

  // SIB bits have no config_hold protection and clear in Test-Logic-Reset;
  // a 3DCR survives when its config_hold is set. A downstream TAP that
  // follows the live TMS (selected) or is parked high reaches
  // Test-Logic-Reset as well and re-selects IDCODE. The host segment's
  // update register resets on the host scan control's rst_n, which the
  // stap_host gate leaves live.
  function void tlr();
    for (int unsigned s = 0; s < DtpStapCount; s++)
    if (ds[s] != null && (staps[s].stap_sel || staps[s].tms_hold)) ds[s].reset_instruction();
    if (!ptap_config_hold) ptap_select = 1'b0;
    for (int unsigned s = 0; s < DtpStapCount; s++) begin
      sib_en[s] = 1'b0;
      if (!staps[s].config_hold) begin
        staps[s].stap_sel = 1'b0;
        staps[s].tms_hold = 1'b0;
      end
    end
    host_segment = '0;
  endfunction

  // TRST is forwarded to every STAP host port: the downstream TAPs reset
  // too (IDCODE selected; their data registers keep their values).
  function void trst();
    ptap_config_hold = 1'b0;
    ptap_select      = 1'b0;
    for (int unsigned s = 0; s < DtpStapCount; s++) begin
      sib_en[s] = 1'b0;
      staps[s]  = '{1'b0, 1'b0, 1'b0};
      if (ds[s] != null) ds[s].reset_instruction();
    end
    host_segment = '0;
  endfunction

endclass : dtp_stap_3dcr_model
