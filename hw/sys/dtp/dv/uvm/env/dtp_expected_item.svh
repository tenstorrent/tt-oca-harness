// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// One scalar expectation published by a DTP reference model for the
// scoreboard to pair with the observed item it was predicted from: the
// expected value under a mask, the evidence context, and whether the pair
// carries a contract at all (compare = 0 pairs and drops without a record,
// so a reference model can publish one item per observed item and keep the
// two streams in lockstep). Used by ir_decode, idcode, bypass, xtrig_csr,
// and xtrig_decode. The cocotb twin is DtpExpectedItem in
// env/dtp_expected_item.py.

class dtp_expected_item extends ocah_sequence_item;
  `uvm_object_utils(dtp_expected_item)

  // 0: the observed item this pairs with is outside the feature's contract.
  bit        compare = 1'b1;
  bit [63:0] expected;
  bit [63:0] mask = '1;

  function new(string name = "dtp_expected_item");
    super.new(name);
  endfunction

  function void do_copy(uvm_object rhs);
    dtp_expected_item rhs_item;
    super.do_copy(rhs);
    if (!$cast(rhs_item, rhs)) `uvm_fatal(get_type_name(), "do_copy type mismatch")
    compare  = rhs_item.compare;
    expected = rhs_item.expected;
    mask     = rhs_item.mask;
  endfunction

  virtual function string convert2string();
    if (!compare) return $sformatf("no-contract @%0t %s", timestamp, context_s);
    return $sformatf("expected=0x%0h mask=0x%0h @%0t %s", expected, mask, timestamp, context_s);
  endfunction

endclass : dtp_expected_item
