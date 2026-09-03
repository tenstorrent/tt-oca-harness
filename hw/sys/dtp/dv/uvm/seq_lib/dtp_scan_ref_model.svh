// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP-local iJTAG and STAP/3DCR reference models — the SV analogue of the
// cocotb dtp_scan_ref_model. The models intentionally describe the public
// OSS DTP testbench shape: the external iJTAG instrument scan inputs are
// looped back from their scan outputs, so the SIB model checks routing,
// security gating, and observable control signals without pretending there
// is an instrument behind the loopback.
//
// iJTAG SIB order (TDI to TDO): dft_secure, dft, dfd — all zero-width
// looped instruments, so the observable DR stream is the SIB chain itself.
//
// The TAP_3DCR data register is the 2-bit PTAP 3DCR followed serially by
// the STAP configuration chain (IEEE 1838 Section 5.4): one SIB flop per
// STAP, with the STAP's 3-bit 3DCR spliced TDI-side of its SIB while the
// SIB is open. Scan registers shift MSB-first (scan-in enters the MSB), so
// within each register the MSB field is TDI-nearest. A selected STAP
// splices its host port into the chain: the downstream TAP's IR (IR scans)
// or selected data register (DR scans) when a device is attached, and one
// extra full-cycle flop on ports with a TDI lockup latch (the I/O STAP).
//
// The PTAP forwards its scan controls to the STAP chain on every IR and DR
// scan and, with the PTAP 3DCR select set, routes the instruction
// register's scan-out into the chain: an IR scan is then the 6-bit PTAP IR
// followed by the STAP chain (the PTAP 3DCR itself is a data register and
// stays out of IR scans), and Update-IR commits SIB/3DCR fields and the
// downstream IRs exactly as Update-DR does. Every scan issued while a STAP
// is selected must therefore be composed over the full network.
//
// The downstream contribution is predicted here from IEEE 1149.1 (the
// cocotb StapDownstream parity), never read back from the VIP's device
// engine: Test-Logic-Reset selects IDCODE, an unknown instruction selects
// the one-bit BYPASS, Capture-IR presents 01 in the IR LSBs, and a writable
// register latches the shifted-in value on Update-DR.

// Index order for the iJTAG SIBs and the STAP ports (TDI to TDO).
typedef enum int unsigned {
  IJ_DFT_SECURE = 0,
  IJ_DFT        = 1,
  IJ_DFD        = 2
} dtp_ijtag_sib_e;

typedef enum int unsigned {
  ST_IO     = 0,
  ST_SMC    = 1,
  ST_SEP    = 2,
  ST_EXTRA0 = 3
} dtp_stap_e;

localparam int unsigned DtpIjtagSibCount = 3;
localparam int unsigned DtpStapCount = 4;
localparam int unsigned DtpPtapIrWidth = 6;
// IEEE 1149.1: a TAP's IR capture presents 01 in its two LSBs.
localparam bit [63:0] DtpStapDsIrCapture = 64'h1;

// Composed-scan kind: TAP_3DCR data scan (PTAP 3DCR first) or instruction
// scan (PTAP IR first, PTAP 3DCR absent).
typedef enum int unsigned {
  DTP_SCAN_DR = 0,
  DTP_SCAN_IR = 1
} dtp_scan_kind_e;

// One data register of a downstream TAP.
typedef struct {
  string       name;
  bit [63:0]   opcode;
  int unsigned width;
  bit          writable;
} dtp_stap_ds_reg_t;

typedef struct {
  bit config_hold;
  bit stap_sel;
  bit tms_hold;
} dtp_stap_3dcr_state_t;

// Predict iJTAG SIB state for the DTP public loopback environment.
class dtp_ijtag_sib_model;

  // Per-SIB gate state from the direct disables (1 = SIB gated).
  static function void gates(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                             output bit g[DtpIjtagSibCount]);
    g[IJ_DFT_SECURE] = d.dft_secure;
    g[IJ_DFT]        = d.dft_nonsecure;
    g[IJ_DFD]        = d.dfd;
  endfunction

  // Bits shift LSB-first through the serial chain: after a full update
  // the first scanned bit is resident in the final SIB and the last
  // scanned bit in the first SIB.
  static function void pattern_bits(bit [DtpIjtagSibCount-1:0] pattern,
                                    output bit req[DtpIjtagSibCount]);
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) req[i] = pattern[DtpIjtagSibCount-1-i];
  endfunction

  // requested/gated/effective per SIB for a pattern under a disable mask.
  static function void state(
      bit [DtpIjtagSibCount-1:0] pattern, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
      output bit requested[DtpIjtagSibCount], output bit gated[DtpIjtagSibCount],
      output bit effective[DtpIjtagSibCount], output int unsigned chain_len);
    pattern_bits(pattern, requested);
    gates(d, gated);
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) effective[i] = requested[i] & ~gated[i];
    // Zero-width looped instruments: the chain is always the SIB flops.
    chain_len = DtpIjtagSibCount;
  endfunction

endclass : dtp_ijtag_sib_model

// Tracked state of the downstream TAP spliced behind one STAP host port,
// seeded from the attached device's ocah_jtag_slave_config (IR width, IDCODE,
// register map).
class dtp_stap_ds_state;

  int unsigned      ir_width;
  bit [31:0]        idcode;
  bit [63:0]        idcode_opcode;
  dtp_stap_ds_reg_t regs[bit [63:0]];   // keyed by IR opcode; IDCODE and BYPASS included
  bit [63:0]        active_ir;
  bit [63:0]        values[string];     // writable registers, keyed by name

  function new(ocah_jtag_slave_config cfg);
    dtp_stap_ds_reg_t r;
    if (!cfg.has_idcode) `uvm_fatal("dtp_stap_ds_state", "downstream device has no IDCODE register")
    ir_width      = cfg.ir_width;
    idcode        = cfg.idcode;
    idcode_opcode = cfg.idcode_opcode;
    r = '{"IDCODE", cfg.idcode_opcode, 32, 1'b0};
    regs[cfg.idcode_opcode] = r;
    foreach (cfg.reg_name[op]) begin
      r = '{cfg.reg_name[op], op, cfg.reg_width[op], cfg.reg_writable[op]};
      regs[op] = r;
      if (cfg.reg_writable[op]) values[cfg.reg_name[op]] = cfg.reg_reset_value[op];
    end
    if (!regs.exists(bypass_opcode())) begin
      r = '{"BYPASS", bypass_opcode(), 1, 1'b0};
      regs[bypass_opcode()] = r;
    end
    reset_instruction();
  endfunction

  function bit [63:0] bypass_opcode();
    return (ir_width >= 64) ? '1 : ((64'h1 << ir_width) - 1);
  endfunction

  function bit [63:0] width_mask(int unsigned width);
    return (width >= 64) ? '1 : ((64'h1 << width) - 1);
  endfunction

  // Resolve a register name to its opcode.
  function bit opcode_of(string name, output bit [63:0] opcode);
    foreach (regs[op])
    if (regs[op].name == name) begin
      opcode = op;
      return 1'b1;
    end
    return 1'b0;
  endfunction

  // The register the active instruction selects (0 = BYPASS behavior).
  function bit selected(output dtp_stap_ds_reg_t r);
    bit [63:0] op = active_ir & bypass_opcode();
    if (!regs.exists(op) || regs[op].name == "BYPASS") return 1'b0;
    r = regs[op];
    return 1'b1;
  endfunction

  // Chain segment width the downstream contributes to a composed scan.
  function int unsigned selected_width(dtp_scan_kind_e kind);
    dtp_stap_ds_reg_t r;
    if (kind == DTP_SCAN_IR) return ir_width;
    if (selected(r) && r.width > 0) return r.width;
    return 1;
  endfunction

  // Segment value a maintain scan shifts in: the stored value of a
  // writable register (re-latched unchanged), the active IR for an IR
  // scan, zero otherwise.
  function bit [63:0] shift_default(dtp_scan_kind_e kind);
    dtp_stap_ds_reg_t r;
    if (kind == DTP_SCAN_IR) return active_ir;
    if (selected(r) && r.writable) return values[r.name];
    return '0;
  endfunction

  // Segment value the downstream captures at Capture-IR / Capture-DR.
  function bit [63:0] capture(dtp_scan_kind_e kind);
    dtp_stap_ds_reg_t r;
    if (kind == DTP_SCAN_IR) return DtpStapDsIrCapture & width_mask(ir_width);
    if (!selected(r)) return '0;
    if (r.name == "IDCODE") return {32'h0, idcode};
    return values.exists(r.name) ? values[r.name] : '0;
  endfunction

  // Update-DR: a writable selected register takes the shifted value.
  function void latch(bit [63:0] value);
    dtp_stap_ds_reg_t r;
    if (selected(r) && r.writable) values[r.name] = value & width_mask(r.width);
  endfunction

  function void update_ir(bit [63:0] opcode);
    active_ir = opcode & bypass_opcode();
  endfunction

  // Test-Logic-Reset (TRST, or five parked TMS=1 cycles) selects IDCODE.
  function void reset_instruction();
    active_ir = idcode_opcode;
  endfunction

endclass : dtp_stap_ds_state

// Reference state for the PTAP 3DCR, the STAP 3DCRs, and downstream TAPs.
class dtp_stap_3dcr_model;

  typedef enum int unsigned {
    FLD_STAP_SEL,
    FLD_CONFIG_HOLD,
    FLD_TMS_HOLD,
    FLD_SIB,
    FLD_SPLICE,
    FLD_IR,     // PTAP instruction register bit (IR scans)
    FLD_DS      // downstream TAP segment bit
  } field_e;

  typedef struct {
    int          owner;    // -1 = PTAP, otherwise dtp_stap_e index
    field_e      field;
    int unsigned bit_idx;  // FLD_IR / FLD_DS: bit of the segment value
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

  function new();
    trst();
  endfunction

  // Per-STAP gate state from the direct disables (1 = STAP gated).
  static function void gates(sep_lifecycle_ctrl_pkg::dbg_disable_t d, output bit g[DtpStapCount]);
    g[ST_IO]     = d.stap_io;
    g[ST_SMC]    = d.stap_smc;
    g[ST_SEP]    = d.stap_sep;
    g[ST_EXTRA0] = d.stap_extra;
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

  // --- composed-chain layout -------------------------------------------------
  // (owner, field, bit) per chain flop in TDI-to-TDO order, current state.
  function void chain_layout(sep_lifecycle_ctrl_pkg::dbg_disable_t d, ref layout_entry_t layout[$],
                             input dtp_scan_kind_e kind = DTP_SCAN_DR);
    bit g[DtpStapCount];
    gates(d, g);
    layout.delete();
    if (kind == DTP_SCAN_IR) begin
      for (int b = DtpPtapIrWidth - 1; b >= 0; b--) layout.push_back('{-1, FLD_IR, b});
    end else begin
      layout.push_back('{-1, FLD_STAP_SEL, 0});
      layout.push_back('{-1, FLD_CONFIG_HOLD, 0});
    end
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
  endfunction

  protected function bit field_value(
      layout_entry_t entry, dtp_scan_kind_e kind, int new_ptap_select, int new_ptap_config_hold,
      bit [63:0] ptap_instr, int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int],
      bit [63:0] new_ds_values[int]);
    bit eff_ptap_sel  = (new_ptap_select < 0) ? ptap_select
                                                  : bit'(new_ptap_select);
    bit eff_ptap_hold = (new_ptap_config_hold < 0) ? ptap_config_hold
                                                       : bit'(new_ptap_config_hold);
    bit [63:0] seg;
    if (entry.owner < 0) begin
      if (entry.field == FLD_IR) return ptap_instr[entry.bit_idx];
      return (entry.field == FLD_STAP_SEL) ? eff_ptap_sel : eff_ptap_hold;
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
      input bit [63:0] new_ds_values[int]);
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
            new_ds_values
        ))
      value |= 64'h1 << (width - 1 - depth);
    return value;
  endfunction

  // TAP_3DCR data scan value that writes the given end-state through the
  // current chain. Negative ptap args and absent associative entries keep
  // stored values; a spliced downstream register re-latches its stored
  // value unless new_ds_values names a new one. The layout is the chain as
  // it exists during the scan (updates land at Update-DR).
  function bit [63:0] compose_scan_ds(int unsigned width, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                      int new_ptap_select, int new_ptap_config_hold,
                                      int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int],
                                      bit [63:0] new_ds_values[int]);
    layout_entry_t layout[$];
    chain_layout(d, layout, DTP_SCAN_DR);
    return compose(
        layout,
        width,
        DTP_SCAN_DR,
        new_ptap_select,
        new_ptap_config_hold,
        '0,
        new_sib_en,
        new_payloads,
        new_ds_values
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
                                      int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int]);
    layout_entry_t layout[$];
    chain_layout(d, layout, DTP_SCAN_IR);
    return compose(
        layout, width, DTP_SCAN_IR, -1, -1, ptap_instr, new_sib_en, new_payloads, new_ds_ir
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

  // Commit a composed data scan's Update-DR: the PTAP 3DCR always
  // updates; SIB/3DCR fields per the gating rules; a spliced downstream
  // TAP latches its (writable) selected register; deselected or gated
  // ports park their downstream TAP.
  function void apply_scan_ds(
      sep_lifecycle_ctrl_pkg::dbg_disable_t d, int new_ptap_select, int new_ptap_config_hold,
      int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int], bit [63:0] new_ds_values[int]);
    bit g[DtpStapCount];
    bit in_chain[DtpStapCount];
    int unsigned spliced_list[$];
    gates(d, g);
    for (int unsigned s = 0; s < DtpStapCount; s++) in_chain[s] = sib_en[s];
    spliced_downstream(d, spliced_list);
    if (new_ptap_select >= 0) ptap_select = bit'(new_ptap_select);
    if (new_ptap_config_hold >= 0) ptap_config_hold = bit'(new_ptap_config_hold);
    apply_chain_update(g, in_chain, new_sib_en, new_payloads);
    foreach (spliced_list[i]) begin
      int unsigned s = spliced_list[i];
      ds[s].latch(new_ds_values.exists(int'(s)) ? new_ds_values[int'(s)] : ds[s].shift_default(
                  DTP_SCAN_DR));
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
  // TAP takes its new instruction, then parking as for a data scan.
  function void apply_ir_scan(sep_lifecycle_ctrl_pkg::dbg_disable_t d, bit [63:0] new_ds_ir[int],
                              int new_sib_en[int], dtp_stap_3dcr_state_t new_payloads[int]);
    bit g[DtpStapCount];
    bit in_chain[DtpStapCount];
    int unsigned spliced_list[$];
    gates(d, g);
    for (int unsigned s = 0; s < DtpStapCount; s++) in_chain[s] = sib_en[s];
    spliced_downstream(d, spliced_list);
    apply_chain_update(g, in_chain, new_sib_en, new_payloads);
    foreach (spliced_list[i]) begin
      int unsigned s = spliced_list[i];
      if (new_ds_ir.exists(int'(s))) ds[s].update_ir(new_ds_ir[int'(s)]);
    end
    park_downstream(g);
  endfunction

  // Commit an all-zero over-length data scan: every in-chain field
  // cleared, a spliced downstream's writable register latched to zero.
  function void flush_scan(sep_lifecycle_ctrl_pkg::dbg_disable_t d = '0);
    int unsigned spliced_list[$];
    spliced_downstream(d, spliced_list);
    foreach (spliced_list[i]) ds[spliced_list[i]].latch('0);
    ptap_select      = 1'b0;
    ptap_config_hold = 1'b0;
    for (int unsigned s = 0; s < DtpStapCount; s++) begin
      sib_en[s] = 1'b0;
      staps[s]  = '{1'b0, 1'b0, 1'b0};
    end
  endfunction

  // (expected, care_mask, chain_len) for a readback with PTAP select=1.
  // Captured bit j of the TDO stream is the flop at depth chain_len-1-j.
  // Splice flops capture unknown data and the PTAP IR capture is
  // design-specific: both are masked out. A downstream segment captures
  // the device's IDCODE, its stored register, zero for BYPASS, or the
  // IEEE 1149.1 IR capture on an IR scan. A STAP captures its masked
  // stap_sel: 0 while its disable is asserted, even though the stored bit
  // survives the gate.
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
        value = field_value(layout[depth], kind, -1, -1, '0, no_sib, no_pl, no_ds);
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
  // Test-Logic-Reset as well and re-selects IDCODE.
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
  endfunction

endclass : dtp_stap_3dcr_model
