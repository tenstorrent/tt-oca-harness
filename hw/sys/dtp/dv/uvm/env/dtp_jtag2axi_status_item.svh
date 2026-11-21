// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Expected capture of a JTAG2AXI DTMCS or DMI scan, published by
// dtp_jtag2axi_status_ref_model for the scoreboard to pair with the
// reconstructed scan: the captured value on the bits of `mask`. compare = 0
// pairs and drops without a record (a scan that is not a bridge capture, or
// one taken through the PTAP 3DCR select). The cocotb twin is
// env/dtp_jtag2axi_status_item.py.

class dtp_jtag2axi_status_item extends ocah_sequence_item;
  `uvm_object_utils(dtp_jtag2axi_status_item)

  bit                 compare = 1'b1;
  string              target;
  dtp_j2a_scan_kind_e kind = DTP_J2A_SCAN_NONE;
  bit [63:0]          expected;
  bit [63:0]          mask;

  function new(string name = "dtp_jtag2axi_status_item");
    super.new(name);
  endfunction

  function void do_copy(uvm_object rhs);
    dtp_jtag2axi_status_item rhs_item;
    super.do_copy(rhs);
    if (!$cast(rhs_item, rhs)) `uvm_fatal(get_type_name(), "do_copy type mismatch")
    compare  = rhs_item.compare;
    target   = rhs_item.target;
    kind     = rhs_item.kind;
    expected = rhs_item.expected;
    mask     = rhs_item.mask;
  endfunction

  virtual function string convert2string();
    if (!compare)
      return $sformatf("no-contract %s %s @%0t %s", target, kind.name(), timestamp, context_s);
    return $sformatf(
        "%s %s 0x%0h/0x%0h @%0t %s",
        target,
        kind.name(),
        expected & mask,
        mask,
        timestamp,
        context_s
    );
  endfunction

endclass : dtp_jtag2axi_status_item
