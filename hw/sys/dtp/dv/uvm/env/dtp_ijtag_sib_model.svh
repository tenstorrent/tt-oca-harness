// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP iJTAG SIB reference model (cocotb twin: env/dtp_ijtag_sib_model.py):
// the three SIBs and the instrument stubs tb_top places behind them. The
// SELECT_IJTAG data register is, TDI to TDO, one SIB flop per SIB with the
// SIB's instrument spliced TDO-side of its flop while the SIB is open; scan
// registers shift MSB-first, so an instrument's MSB is TDI-nearest. A SIB's
// update register holds the sanctioned open bit through a gate: the gate
// masks the effective state to closed and blocks Update-DR, and the stored
// bit takes effect again when the gate clears. Test-Logic-Reset clears the
// SIB and instrument update registers. A scan's chain layout is the
// effective state before its Update-DR. Plain model class, built with
// new(); it records no evidence and reports only a fatal on misuse. Types
// come from dtp_types.svh.

// Reference state for the iJTAG SIBs and their instrument stubs.
class dtp_ijtag_sib_model;

  typedef struct {
    int unsigned owner;    // dtp_ijtag_sib_e index
    bit          is_inst;  // 0 = the SIB flop, 1 = an instrument flop
    int unsigned bit_idx;  // instrument register bit held by the flop
  } layout_entry_t;

  // Predicted outcome of programming one SIB pattern under a disable mask.
  typedef struct {
    bit          requested[DtpIjtagSibCount];
    bit          gated[DtpIjtagSibCount];
    bit          effective[DtpIjtagSibCount];
    int unsigned chain_len;
  } sib_state_t;

  bit stored[DtpIjtagSibCount];
  bit [63:0] instruments[DtpIjtagSibCount];

  function new();
    reset();
  endfunction

  // Test-Logic-Reset: every SIB closed, every instrument register zero.
  function void reset();
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++) begin
      stored[s]      = 1'b0;
      instruments[s] = '0;
    end
  endfunction

  // Per-SIB gate state from the direct disables (1 = SIB gated).
  static function void gates(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                             output bit g[DtpIjtagSibCount]);
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++)
    g[s] = dtp_dbg_path_disabled(d, dtp_ijtag_sib_dbg_path(s));
  endfunction

  // Bits shift LSB-first through the serial chain: after a full update
  // the first scanned bit is resident in the final SIB and the last
  // scanned bit in the first SIB.
  static function void pattern_bits(bit [DtpIjtagSibCount-1:0] pattern,
                                    output bit req[DtpIjtagSibCount]);
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) req[i] = pattern[DtpIjtagSibCount-1-i];
  endfunction

  static function bit [63:0] instrument_mask(int unsigned sib);
    return (64'h1 << DtpIjtagInstrumentWidths[sib]) - 64'h1;
  endfunction

  // requested/gated/effective per SIB and the chain length after
  // programming `pattern` under `d`: a gated SIB reads closed whatever it
  // stores, so the outcome follows the request masked by the gates.
  static function sib_state_t state(bit [DtpIjtagSibCount-1:0] pattern,
                                    sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    sib_state_t s;
    pattern_bits(pattern, s.requested);
    gates(d, s.gated);
    s.chain_len = DtpIjtagSibCount;
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) begin
      s.effective[i] = s.requested[i] & ~s.gated[i];
      if (s.effective[i]) s.chain_len += DtpIjtagInstrumentWidths[i];
    end
    return s;
  endfunction

  // Stored SIB state masked by the gates: the chain as it shifts.
  function void effective(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                          output bit eff[DtpIjtagSibCount]);
    bit g[DtpIjtagSibCount];
    gates(d, g);
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++) eff[s] = stored[s] & ~g[s];
  endfunction

  // Chain flops in TDI-to-TDO order for the current effective state.
  function void chain_layout(sep_lifecycle_ctrl_pkg::dbg_disable_t d, ref layout_entry_t layout[$]);
    bit eff[DtpIjtagSibCount];
    effective(d, eff);
    layout.delete();
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++) begin
      layout.push_back('{s, 1'b0, 0});
      if (eff[s])
        for (int b = int'(DtpIjtagInstrumentWidths[s]) - 1; b >= 0; b--)
        layout.push_back('{s, 1'b1, unsigned'(b)});
    end
  endfunction

  function int unsigned chain_len(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    layout_entry_t layout[$];
    chain_layout(d, layout);
    return layout.size();
  endfunction

  // SELECT_IJTAG scan value that writes `new_pattern` (negative = keep the
  // stored bits) into the SIBs and `new_inst` into the open instruments
  // through the current chain; absent entries keep their stored values.
  function bit [63:0] compose_scan(int unsigned width, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                   int new_pattern, bit [63:0] new_inst[int]);
    layout_entry_t layout[$];
    bit sib_bits[DtpIjtagSibCount];
    bit [63:0] value = '0;
    bit [63:0] seg;
    bit flop_bit;
    chain_layout(d, layout);
    if (width < layout.size())
      `uvm_fatal("dtp_ijtag_sib_model", $sformatf(
                 "scan width %0d < chain length %0d", width, layout.size()))
    if (new_pattern >= 0) pattern_bits(DtpIjtagSibCount'(new_pattern), sib_bits);
    else sib_bits = stored;
    foreach (layout[depth]) begin
      if (layout[depth].is_inst) begin
        seg = new_inst.exists(int'(layout[depth].owner)) ? new_inst[int'(layout[depth].owner)] :
            instruments[layout[depth].owner];
        flop_bit = seg[layout[depth].bit_idx];
      end else flop_bit = sib_bits[layout[depth].owner];
      if (flop_bit) value |= 64'h1 << (width - 1 - depth);
    end
    return value;
  endfunction

  // Commit a composed scan's Update-DR: an ungated SIB stores its
  // requested bit; an instrument that was in the chain latches its
  // segment; a gated SIB and its instrument ignore the update.
  function void apply_scan(sep_lifecycle_ctrl_pkg::dbg_disable_t d, int new_pattern,
                           bit [63:0] new_inst[int]);
    bit g[DtpIjtagSibCount];
    bit in_chain[DtpIjtagSibCount];
    bit sib_bits[DtpIjtagSibCount];
    gates(d, g);
    effective(d, in_chain);
    if (new_pattern >= 0) pattern_bits(DtpIjtagSibCount'(new_pattern), sib_bits);
    else sib_bits = stored;
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++) begin
      if (in_chain[s] && new_inst.exists(int'(s)))
        instruments[s] = new_inst[int'(s)] & instrument_mask(s);
      if (!g[s]) stored[s] = sib_bits[s];
    end
  endfunction

  // (expected, chain_len) of a scan's captured TDO bits: captured bit j is
  // the flop at depth chain_len-1-j; a SIB captures its effective state and
  // an instrument its stored register.
  function void expected_capture(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                 output bit [63:0] expected, output int unsigned chain_len);
    layout_entry_t layout[$];
    bit eff[DtpIjtagSibCount];
    bit flop_bit;
    chain_layout(d, layout);
    effective(d, eff);
    chain_len = layout.size();
    expected  = '0;
    foreach (layout[depth]) begin
      if (layout[depth].is_inst) flop_bit = instruments[layout[depth].owner][layout[depth].bit_idx];
      else flop_bit = eff[layout[depth].owner];
      if (flop_bit) expected |= 64'h1 << (chain_len - 1 - depth);
    end
  endfunction

  // Inverse of pattern_bits: the scan value that stores `bits`.
  static function bit [DtpIjtagSibCount-1:0] pattern_value(bit bits[DtpIjtagSibCount]);
    bit [DtpIjtagSibCount-1:0] value = '0;
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) value[DtpIjtagSibCount-1-i] = bits[i];
    return value;
  endfunction

  // Commit the Update-DR of a `width`-bit scan of `value` through the current
  // chain. Shift-DR moves the Capture-DR contents `width` flops toward TDO
  // while the value enters at TDI, so a scan narrower than the chain leaves
  // the deeper flops holding what shallower flops captured; a gated SIB and
  // its instrument ignore the update.
  function void apply_raw_scan(int unsigned width, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                               bit [63:0] value);
    layout_entry_t layout[$];
    bit g[DtpIjtagSibCount];
    bit sib_bits[DtpIjtagSibCount];
    bit [63:0] inst[DtpIjtagSibCount];
    bit touched[DtpIjtagSibCount];
    bit [63:0] capture;
    int unsigned len;
    chain_layout(d, layout);
    expected_capture(d, capture, len);
    gates(d, g);
    sib_bits = stored;
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++) begin
      inst[s]    = '0;
      touched[s] = 1'b0;
    end
    foreach (layout[depth]) begin
      bit flop_bit = (depth < width) ? value[width-1-depth] : capture[len-1-(depth-width)];
      if (layout[depth].is_inst) begin
        inst[layout[depth].owner][layout[depth].bit_idx] = flop_bit;
        touched[layout[depth].owner] = 1'b1;
      end else sib_bits[layout[depth].owner] = flop_bit;
    end
    for (int unsigned s = 0; s < DtpIjtagSibCount; s++) begin
      if (touched[s]) instruments[s] = inst[s];
      if (!g[s]) stored[s] = sib_bits[s];
    end
  endfunction

  // TDO of a `width`-bit scan, LSB first: the chain's capture bits nearest
  // TDO, then the scanned value one TCK per chain flop behind TDI.
  function bit [63:0] expected_scan_tdo(int unsigned width, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                        bit [63:0] value);
    bit [63:0] capture;
    int unsigned len;
    expected_capture(d, capture, len);
    return ((value << len) | capture) & ((64'h1 << width) - 1);
  endfunction

endclass : dtp_ijtag_sib_model
