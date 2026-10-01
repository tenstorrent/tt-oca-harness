// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross-trigger CSR shadow: the readback value of every CSR with a
// readback contract (CTM selects, CTP CONFIG and STRETCH_MULT), rebuilt
// from the writes observed on the XTRIG AXI-Lite port under their byte
// strobes and the register's implemented-bit mask, and cleared on every
// system or power-on reset. Plain class held by dtp_xtrig_csr_ref_model;
// no reporting. In the cocotb realization the scenarios record each CSR
// readback against the written value as CHK-XTRIG-CSR evidence.

class dtp_xtrig_csr_model;

  protected bit [31:0] m_shadow[bit [63:0]];

  function new();
  endfunction

  function void clear();
    m_shadow.delete();
  endfunction

  // An OKAY write: merge the strobed bytes into the shadow under the mask.
  function void write(bit [63:0] addr, bit [31:0] data, bit [3:0] wstrb, bit [31:0] mask,
                      bit [31:0] reset_value);
    bit [31:0] current = read(addr, mask, reset_value);
    m_shadow[addr] = dtp_xtrig_apply_wstrb(current, data, wstrb) & mask;
  endfunction

  // Expected readback: the shadow, or the register's reset value.
  function bit [31:0] read(bit [63:0] addr, bit [31:0] mask, bit [31:0] reset_value);
    return (m_shadow.exists(addr) ? m_shadow[addr] : reset_value) & mask;
  endfunction

endclass : dtp_xtrig_csr_model
