// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Completed-transaction history of one JTAG2AXI bridge port: counts every
// write and read the shared AXI monitor completes on that port and keeps the
// newest item of each direction, so a scenario can wait for the transaction
// an operation put on the port, judge it and prove that no other one
// appeared (CHK-J2A-BUS-REQ), and compare an errored read beat with its
// capture (CHK-J2A-ERR-RDATA). The mark holds the counts the last ledgered
// pass closed with. Publishes nothing and checks nothing. The cocotb twin is
// env/dtp_axi_port_history.py.

class dtp_axi_port_history extends ocah_subscriber #(ocah_axi_item);
  `uvm_component_utils(dtp_axi_port_history)

  protected int unsigned  m_write_count;
  protected int unsigned  m_read_count;
  protected ocah_axi_item m_last_write;
  protected ocah_axi_item m_last_read;

  // Counts at the close of the last ledgered pass; `marked` is 0 before the
  // first one.
  bit                     marked;
  int unsigned            mark_writes;
  int unsigned            mark_reads;

  function new(string name = "dtp_axi_port_history", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // The monitor publishes a write at its B and a read at its last R.
  function void write(ocah_axi_item t);
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      m_write_count++;
      m_last_write = t;
    end else begin
      m_read_count++;
      m_last_read = t;
    end
  endfunction

  function int unsigned count(bit is_read);
    return is_read ? m_read_count : m_write_count;
  endfunction

  // The newest completed item of one direction; 0 when none was observed.
  function bit last(bit is_read, output ocah_axi_item item);
    item = is_read ? m_last_read : m_last_write;
    return item != null;
  endfunction

endclass : dtp_axi_port_history
