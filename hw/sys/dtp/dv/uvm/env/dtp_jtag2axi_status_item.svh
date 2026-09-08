// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Expected capture of a JTAG2AXI SINGLE_OP or SERIES_CTRL scan, published
// by dtp_jtag2axi_status_ref_model for the scoreboard to pair with the
// reconstructed scan: the status field the bridge must present and, for a
// completed read, the read data. compare = 0 pairs and drops without a
// record (a scan that is not a status capture, or one inside the CDC settle
// window after a completion). No cocotb twin (see DTP_TB_ARCH).

class dtp_jtag2axi_status_item extends ocah_sequence_item;
  `uvm_object_utils(dtp_jtag2axi_status_item)

  bit                 compare = 1'b1;
  string              target;
  dtp_j2a_scan_kind_e kind = DTP_J2A_SCAN_NONE;
  dtp_j2a_status_e    status = DTP_J2A_SUCCESS;
  // Read data is part of the contract only after a completed OKAY read.
  bit                 compare_rdata;
  bit [63:0]          rdata;
  bit [63:0]          rdata_mask;

  function new(string name = "dtp_jtag2axi_status_item");
    super.new(name);
  endfunction

  function void do_copy(uvm_object rhs);
    dtp_jtag2axi_status_item rhs_item;
    super.do_copy(rhs);
    if (!$cast(rhs_item, rhs)) `uvm_fatal(get_type_name(), "do_copy type mismatch")
    compare       = rhs_item.compare;
    target        = rhs_item.target;
    kind          = rhs_item.kind;
    status        = rhs_item.status;
    compare_rdata = rhs_item.compare_rdata;
    rdata         = rhs_item.rdata;
    rdata_mask    = rhs_item.rdata_mask;
  endfunction

  virtual function string convert2string();
    if (!compare)
      return $sformatf("no-contract %s %s @%0t %s", target, kind.name(), timestamp, context_s);
    return $sformatf(
        "%s %s status=%s%s @%0t %s",
        target,
        kind.name(),
        status.name(),
        compare_rdata ? $sformatf(
            " rdata=0x%0h", rdata & rdata_mask
        ) : "",
        timestamp,
        context_s
    );
  endfunction

endclass : dtp_jtag2axi_status_item
