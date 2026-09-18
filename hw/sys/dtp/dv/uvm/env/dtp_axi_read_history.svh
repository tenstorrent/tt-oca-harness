// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Observed-read history of one JTAG2AXI bridge port: retains the most
// recent completed read items the shared AXI monitor publishes on that
// port, so a scenario can compare a SINGLE_OP capture with the beat the
// bus returned (CHK-J2A-ERR-RDATA). Publishes nothing and checks nothing.
// The cocotb realization reads the same history from the shared monitor's
// get_read_transactions().

class dtp_axi_read_history extends ocah_subscriber #(ocah_axi_item);
  `uvm_component_utils(dtp_axi_read_history)

  // History depth; the oldest read is dropped beyond it.
  localparam int unsigned Depth = 16;

  protected ocah_axi_item m_reads[$];
  protected int unsigned  m_read_count;

  function new(string name = "dtp_axi_read_history", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void write(ocah_axi_item t);
    if (t.direction != OCAH_AXI_DIR_READ) return;
    m_read_count++;
    m_reads.push_back(t);
    if (m_reads.size() > Depth) void'(m_reads.pop_front());
  endfunction

  function int unsigned read_count();
    return m_read_count;
  endfunction

  // The most recent completed read; 0 when none was observed.
  function bit last_read(output ocah_axi_item item);
    if (m_reads.size() == 0) return 1'b0;
    item = m_reads[$];
    return 1'b1;
  endfunction

endclass : dtp_axi_read_history
