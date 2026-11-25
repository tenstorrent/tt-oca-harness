// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Seeded delay source for the responder's READY stalls and response delays.
// Each next() draws a cycle count: from [long_min, long_max] with
// long_percent percent probability, otherwise from [short_min, short_max].
// The generator is a 32-bit xorshift owned by the object, so a seed gives the
// same values on every simulator and in the cocotb twin OcahAxiDelays,
// independent of process RNG state.

class ocah_axi_delays;

  protected int unsigned m_short_min;
  protected int unsigned m_short_max;
  protected int unsigned m_long_percent;
  protected int unsigned m_long_min;
  protected int unsigned m_long_max;
  protected bit [31:0]   m_state;

  function new(int unsigned seed, int unsigned short_min = 0, int unsigned short_max = 0,
               int unsigned long_percent = 0, int unsigned long_min = 0, int unsigned long_max = 0);
    if (short_min > short_max)
      `uvm_fatal("ocah_axi_delays", $sformatf(
                 "short_min %0d exceeds short_max %0d", short_min, short_max))
    if (long_percent > 100)
      `uvm_fatal("ocah_axi_delays", $sformatf("long_percent %0d exceeds 100", long_percent))
    if (long_percent != 0 && long_min > long_max)
      `uvm_fatal("ocah_axi_delays", $sformatf(
                 "long_min %0d exceeds long_max %0d", long_min, long_max))
    m_short_min    = short_min;
    m_short_max    = short_max;
    m_long_percent = long_percent;
    m_long_min     = long_min;
    m_long_max     = long_max;
    m_state        = 32'(seed) ^ 32'h9E37_79B9;
    if (m_state == '0) m_state = 32'h6D2B_79F5;
  endfunction

  // The largest value next() can return.
  function int unsigned max_value();
    return (m_long_percent != 0 && m_long_max > m_short_max) ? m_long_max : m_short_max;
  endfunction

  function int unsigned next();
    int unsigned lo = m_short_min;
    int unsigned hi = m_short_max;
    if (m_long_percent != 0 && u32() % 100 < m_long_percent) begin
      lo = m_long_min;
      hi = m_long_max;
    end
    return lo + 32'(64'(u32()) % (64'(hi) - 64'(lo) + 64'd1));
  endfunction

  protected function bit [31:0] u32();
    bit [31:0] x = m_state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    m_state = x;
    return x;
  endfunction

endclass : ocah_axi_delays
