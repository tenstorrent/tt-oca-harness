// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Expected capture of one primary-TAP DR scan under a TDR the SMU bench
// models (IC_RESET, DEBUG_CONTROL), published by the TDR reference models
// for the scoreboard to pair with the reconstructed scan: the register
// image the DUT must present at Capture-DR under the mask of the bits
// software owns. compare = 0 pairs and drops without a record (a scan that
// is not a capture of that TDR). No cocotb twin: the cocotb leaves compare
// each readback inline.

class smu_tdr_expected_item extends uvm_object;
  `uvm_object_utils(smu_tdr_expected_item)

  bit          compare = 1'b0;
  string       tdr_name;
  int unsigned width;
  bit [255:0]  expected;
  bit [255:0]  mask;
  string       context_s;
  time         timestamp;

  function new(string name = "smu_tdr_expected_item");
    super.new(name);
  endfunction

  virtual function string convert2string();
    if (!compare) return $sformatf("no-contract %s @%0t %s", tdr_name, timestamp, context_s);
    return $sformatf(
        "%s width=%0d expected=0x%0h mask=0x%0h @%0t %s",
        tdr_name,
        width,
        expected & mask,
        mask,
        timestamp,
        context_s
    );
  endfunction

endclass : smu_tdr_expected_item
