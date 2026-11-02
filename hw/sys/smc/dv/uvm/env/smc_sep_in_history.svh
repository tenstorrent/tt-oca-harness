// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Counts completed SEP_IN transactions published by the AXI environment.
class smc_sep_in_history extends ocah_subscriber #(ocah_axi_item);
  `uvm_component_utils(smc_sep_in_history)
  protected int unsigned m_read_count;
  protected int unsigned m_write_count;

  function new(string name = "smc_sep_in_history", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void write(ocah_axi_item t);
    if (t.direction == OCAH_AXI_DIR_READ) m_read_count++;
    else if (t.direction == OCAH_AXI_DIR_WRITE) m_write_count++;
  endfunction

  function int unsigned count(bit is_read);
    return is_read ? m_read_count : m_write_count;
  endfunction
endclass : smc_sep_in_history
