// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP iJTAG SIB reference model (env/dtp_scan_ref_model.py parity): the
// public OSS loopback shape, where the SIB model checks routing, security
// gating, and observable control signals without an instrument behind
// the loopback. iJTAG SIB order (TDI to TDO): dft_secure, dft, dfd.
// Stateless: every function is static. Types come from dtp_types.svh.

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

  // --- stored SIB bits across any instruction that scans the chain --------

  // Stored SIB bits after Test-Logic-Reset: every SIB closed.
  static function void closed(output bit stored[DtpIjtagSibCount]);
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) stored[i] = 1'b0;
  endfunction

  // Inverse of pattern_bits: the scan value that stores `bits`.
  static function bit [DtpIjtagSibCount-1:0] pattern_value(bit bits[DtpIjtagSibCount]);
    bit [DtpIjtagSibCount-1:0] value = '0;
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) value[DtpIjtagSibCount-1-i] = bits[i];
    return value;
  endfunction

  // Capture-DR value of the chain: each SIB presents its stored bit, a
  // gated SIB presents 0.
  static function bit [DtpIjtagSibCount-1:0] capture_value(bit stored[DtpIjtagSibCount],
                                                           sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    bit g[DtpIjtagSibCount];
    bit visible[DtpIjtagSibCount];
    gates(d, g);
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) visible[i] = stored[i] & ~g[i];
    return pattern_value(visible);
  endfunction

  // Stored bits after Update-DR of a `width`-bit scan through the chain: the
  // last three bits scanned in are resident in the SIBs; a gated SIB ignores
  // the update and keeps its stored bit.
  static function void update(ref bit stored[DtpIjtagSibCount], input bit [63:0] scan_value,
                              input int unsigned width,
                              input sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    bit g[DtpIjtagSibCount];
    bit tail[DtpIjtagSibCount];
    if (width < DtpIjtagSibCount)
      `uvm_fatal("dtp_ijtag_sib_model", $sformatf(
                 "a chain scan needs at least %0d bits, got %0d", DtpIjtagSibCount, width))
    pattern_bits(DtpIjtagSibCount'(scan_value >> (width - DtpIjtagSibCount)), tail);
    gates(d, g);
    for (int unsigned i = 0; i < DtpIjtagSibCount; i++) if (!g[i]) stored[i] = tail[i];
  endfunction

  // TDO of a `width`-bit DR scan through the chain, LSB first: the three
  // captured SIB bits come out first, then the scanned-in value follows
  // three TCK behind TDI (one stage per SIB).
  static function bit [63:0] expected_dr_tdo(bit stored[DtpIjtagSibCount], bit [63:0] scan_value,
                                             int unsigned width,
                                             sep_lifecycle_ctrl_pkg::dbg_disable_t d);
    bit [63:0] mask = (width >= 64) ? '1 : ((64'h1 << width) - 64'h1);
    return ((scan_value << DtpIjtagSibCount) & mask) | 64'(capture_value(stored, d));
  endfunction

endclass : dtp_ijtag_sib_model
