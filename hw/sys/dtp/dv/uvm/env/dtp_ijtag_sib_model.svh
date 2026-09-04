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

endclass : dtp_ijtag_sib_model
