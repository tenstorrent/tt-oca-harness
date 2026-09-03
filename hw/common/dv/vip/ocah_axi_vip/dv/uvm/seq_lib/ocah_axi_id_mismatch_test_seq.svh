// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_axi_id_mismatch_test (the SV-UVM twin of the
// cocotb selftest): the master proves a wrong returned response ID is
// distinguishable from the issued one. Against the fault slave with armed
// one-shot response-ID corruption, each affected result reports
// observed_id == issued ^ mask (ID-width truncated), the data path stays
// untouched, the very next transaction matches again (one-shot), a
// corrupted RID is observable on the completing RLAST beat of a burst, and
// clear_errors() disarms a pending corruption.
//
// Unlike the cocotb twin (wire-level driven because the cocotbext backend
// polices response-ID pairing), this runs entirely front-door through the
// master sequence API: the OCAH master reports wire truth instead of
// policing it. The passive observation stack is disabled by the test — a
// corrupted response ID is an orphan completion to a passive observer.

class ocah_axi_id_mismatch_test_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(ocah_axi_id_mismatch_test_seq)

  // Bound by the test before start().
  ocah_axi_checker        evidence;
  ocah_axi_slave_sequence slave_seq;

  int unsigned n_rounds = 3;

  function new(string name = "ocah_axi_id_mismatch_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [15:0] awid, arid, mask, expected_id;
    bit [63:0] addr, data, last_data, burst_base;
    bit [63:0] words[$];
    ocah_axi_item res;
    string ctx;

    if (evidence == null || slave_seq == null)
      `uvm_fatal(get_type_name(), "evidence/slave_seq handles not bound")

    addr = 64'($urandom_range(16383)) & ~64'h3;
    awid = 16'($urandom_range(255));
    arid = 16'($urandom_range(255));

    // Baseline write: unarmed responder echoes the issued AWID.
    data = 64'($urandom());
    write_result(addr, data, res, awid);
    void'(evidence.expect_true(
        "CHK-AXI-IDC-BASE-WR",
        res.observed_id_valid && res.id_match(),
        $sformatf(
            "addr=0x%0h awid=0x%0h observed=0x%0h", addr, awid, res.observed_id)
    ));
    last_data = data;

    // Armed one-shot BID corruption over random masks: each returned BID
    // equals issued ^ mask, the data path is untouched, and the following
    // unarmed write matches again (one-shot).
    for (int unsigned round = 0; round < n_rounds; round++) begin
      mask = 16'($urandom_range(1, 255));
      expected_id = resolve_cfg().mask_id(awid ^ mask);
      slave_seq.inject_id_corruption(mask, .for_read(1'b0), .for_write(1'b1));
      data = 64'($urandom());
      write_result(addr, data, res, awid);
      ctx = $sformatf("round=%0d awid=0x%0h mask=0x%0h", round, awid, mask);
      void'(evidence.expect_true("CHK-AXI-IDC-WR-CAP", res.observed_id_valid, ctx));
      void'(evidence.expect_equal("CHK-AXI-IDC-WR", 64'(res.observed_id), 64'(expected_id), ctx));
      void'(evidence.expect_true(
          "CHK-AXI-IDC-WR-DIFF",
          res.observed_id != resolve_cfg().mask_id(
              awid
          ),
          {
            ctx, " corrupted BID must be distinguishable"
          }
      ));
      void'(evidence.expect_equal(
          "CHK-AXI-IDC-WR-DATA",
          64'(slave_seq.read32(
              addr
          )),
          data,
          {
            ctx, " corruption must not disturb the write data path"
          }
      ));
      data = 64'($urandom());
      write_result(addr, data, res, awid);
      void'(evidence.expect_true(
          "CHK-AXI-IDC-WR-ONESHOT", res.observed_id_valid && res.id_match(), ctx
      ));
      last_data = data;
    end

    // Baseline read: unarmed responder echoes the issued ARID.
    read_result(addr, res, arid);
    void'(evidence.expect_true(
        "CHK-AXI-IDC-BASE-RD",
        res.observed_id_valid && res.id_match() && res.first_data() == last_data,
        $sformatf(
            "addr=0x%0h arid=0x%0h observed=0x%0h data=0x%0h",
            addr,
            arid,
            res.observed_id,
            res.first_data())
    ));

    // Armed one-shot RID corruption, sampled on the completing beat; each
    // following unarmed read matches again (one-shot).
    for (int unsigned round = 0; round < n_rounds; round++) begin
      mask = 16'($urandom_range(1, 255));
      expected_id = resolve_cfg().mask_id(arid ^ mask);
      data = 64'($urandom());
      slave_seq.write32(addr, data[31:0]);
      slave_seq.inject_id_corruption(mask, .for_read(1'b1), .for_write(1'b0));
      read_result(addr, res, arid);
      ctx = $sformatf("round=%0d arid=0x%0h mask=0x%0h", round, arid, mask);
      void'(evidence.expect_true("CHK-AXI-IDC-RD-CAP", res.observed_id_valid, ctx));
      void'(evidence.expect_equal("CHK-AXI-IDC-RD", 64'(res.observed_id), 64'(expected_id), ctx));
      void'(evidence.expect_true(
          "CHK-AXI-IDC-RD-DIFF",
          res.observed_id != resolve_cfg().mask_id(
              arid
          ),
          {
            ctx, " corrupted RID must be distinguishable"
          }
      ));
      void'(evidence.expect_equal(
          "CHK-AXI-IDC-RD-DATA",
          res.first_data(),
          data,
          {
            ctx, " corruption must not disturb the read data path"
          }
      ));
      read_result(addr, res, arid);
      void'(evidence.expect_true(
          "CHK-AXI-IDC-RD-ONESHOT", res.observed_id_valid && res.id_match(), ctx
      ));
    end

    // A corrupted RID is observable on the completing RLAST beat of a
    // burst, with the burst data path untouched.
    burst_base = (64'($urandom_range(16383)) & ~64'hFF) | 64'h10;
    words.delete();
    repeat (4) words.push_back(64'($urandom()));
    burst_write_result(burst_base, words, res, awid);
    mask = 16'($urandom_range(1, 255));
    expected_id = resolve_cfg().mask_id(arid ^ mask);
    slave_seq.inject_id_corruption(mask, .for_read(1'b1), .for_write(1'b0));
    burst_read_result(burst_base, 4, res, arid);
    ctx = $sformatf("burst base=0x%0h arid=0x%0h mask=0x%0h", burst_base, arid, mask);
    void'(evidence.expect_true(
        "CHK-AXI-IDC-BURST-RD",
        res.observed_id_valid && res.observed_id == expected_id,
        $sformatf(
            "%s observed=0x%0h (RLAST-beat sample)", ctx, res.observed_id)
    ));
    void'(evidence.expect_equal_words("CHK-AXI-IDC-BURST-RDATA", res.data_words, words, ctx));

    // clear_errors() disarms a pending corruption in both directions.
    slave_seq.inject_id_corruption(16'h5A);
    slave_seq.clear_errors();
    data = 64'($urandom());
    write_result(addr, data, res, awid);
    void'(evidence.expect_true(
        "CHK-AXI-IDC-DISARM-WR", res.observed_id_valid && res.id_match(), "after clear_errors"
    ));
    read_result(addr, res, arid);
    void'(evidence.expect_true(
        "CHK-AXI-IDC-DISARM-RD", res.observed_id_valid && res.id_match(), "after clear_errors"
    ));
  endtask

endclass : ocah_axi_id_mismatch_test_seq
