// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Programmed CONFIG.MODE and CONFIG.INVERT of every external CTP (the cocotb
// DtpXtrigCtpShadow twin). Held by the virtual sequencer, so it outlives a
// scenario pass: the DUT keeps its CTP configuration from one pass to the
// next. A system reset or a CONFIG clear returns every CTP to wire-OR, not
// inverted (the register reset value). Written by the XTRIG sequences when
// they program a CTP; read when a route window is judged, because a P2P port
// drives its request output enable constantly and signals a request on the
// request level. Plain class built with new(); no reporting.

class dtp_xtrig_ctp_shadow;

  protected bit [31:0] m_p2p;
  protected bit [31:0] m_inverted;

  function new();
    clear();
  endfunction

  function void clear();
    m_p2p = '0;
    m_inverted = '0;
  endfunction

  function void note(int unsigned ctp_idx, int unsigned mode, bit invert);
    m_p2p[ctp_idx] = (mode == DtpCtpModeP2p);
    m_inverted[ctp_idx] = invert;
  endfunction

  function bit [31:0] p2p_mask();
    return m_p2p;
  endfunction

  function bit [31:0] invert_mask();
    return m_inverted;
  endfunction

endclass : dtp_xtrig_ctp_shadow
