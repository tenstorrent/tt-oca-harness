// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_axi_id_match_test (the SV-UVM twin of the
// cocotb selftest): randomized single-beat write/read pairs with independent
// random AWID/ARID (the first two iterations pin the 0x00/0xFF ID-space
// corners), a default-ID transaction, and a 4-beat burst whose RID is
// sampled on the completing RLAST beat. Every result must carry a live
// captured response ID equal to the issued one, and data integrity is
// cross-checked through the responder's backdoor so an ID-only pass cannot
// mask a data defect.
//
// Stimulus intent is armed on the passive cfg per operation
// (arm_expected_write/arm_expected_read), so the wire-level scoreboard also
// scores every transaction (CHK-AXI-RESP/WADDR/WDATA/STRB/RADDR/RDATA); the
// burst write arms no write intent (single-beat intent contract).

class ocah_axi_id_match_test_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(ocah_axi_id_match_test_seq)

  // Bound by the test before start().
  ocah_axi_checker        evidence;
  ocah_axi_config         axi_cfg;
  ocah_axi_slave_sequence slave_seq;

  int unsigned n_ops = 12;

  function new(string name = "ocah_axi_id_match_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [7:0] full_strb;
    bit [15:0] awid, arid, burst_id;
    bit [63:0] addr, data, burst_base;
    bit [63:0] words[$];
    ocah_axi_item wres, rres;
    string ctx;

    if (evidence == null || axi_cfg == null || slave_seq == null)
      `uvm_fatal(get_type_name(), "evidence/axi_cfg/slave_seq handles not bound")
    if (n_ops < 2)
      `uvm_fatal(get_type_name(), $sformatf("n_ops must be >= 2 (ID-space corners); got %0d", n_ops
                 ))
    full_strb = 8'((64'd1 << axi_cfg.beat_bytes()) - 1);

    // Randomized write/read pairs; iterations 0/1 pin the ID corners.
    for (int unsigned index = 0; index < n_ops; index++) begin
      case (index)
        0: begin
          awid = 16'h00;
          arid = 16'hFF;
        end
        1: begin
          awid = 16'hFF;
          arid = 16'h00;
        end
        default: begin
          awid = 16'($urandom_range(255));
          arid = 16'($urandom_range(255));
        end
      endcase
      addr = 64'($urandom_range(16383)) & ~64'h3;
      data = 64'($urandom());
      ctx  = $sformatf("op=%0d addr=0x%0h awid=0x%0h arid=0x%0h",
                             index, addr, awid, arid);

      axi_cfg.arm_expected_write(addr, data, full_strb);
      write_result(addr, data, wres, awid);
      void'(evidence.expect_true(
          "CHK-AXI-ID-WR",
          wres.observed_id_valid && wres.id_match(),
          $sformatf(
              "%s observed=0x%0h valid=%0d", ctx, wres.observed_id, wres.observed_id_valid)
      ));
      void'(evidence.expect_equal("CHK-AXI-BACKDOOR-WR", 64'(slave_seq.read32(addr)), data, ctx));

      axi_cfg.arm_expected_read(addr);
      read_result(addr, rres, arid);
      void'(evidence.expect_equal("CHK-AXI-RDBK", rres.first_data(), data, ctx));
      void'(evidence.expect_true(
          "CHK-AXI-ID-RD",
          rres.observed_id_valid && rres.id_match(),
          $sformatf(
              "%s observed=0x%0h valid=%0d", ctx, rres.observed_id, rres.observed_id_valid)
      ));
    end

    // Default-ID transaction: the result must report the driven 0 as a
    // captured ID, not as a capture miss.
    addr = 64'h40;
    data = 64'($urandom());
    axi_cfg.arm_expected_write(addr, data, full_strb);
    write_result(addr, data, wres);
    void'(evidence.expect_true(
        "CHK-AXI-ID-DEFAULT",
        wres.observed_id_valid && wres.observed_id == '0 && wres.id_match(),
        $sformatf(
            "addr=0x%0h observed=0x%0h valid=%0d", addr, wres.observed_id, wres.observed_id_valid)
    ));

    // Burst: the RID is sampled on the completing (RLAST) beat. No write
    // intent (single-beat intent contract); the read intent and the
    // ref-model shadow score the burst readback on the wire level too.
    burst_id   = 16'($urandom_range(255));
    burst_base = (64'($urandom_range(16383)) & ~64'hFF) | 64'h10;
    words.delete();
    repeat (4) words.push_back(64'($urandom()));
    ctx = $sformatf("burst base=0x%0h id=0x%0h", burst_base, burst_id);
    burst_write_result(burst_base, words, wres, burst_id);
    void'(evidence.expect_true(
        "CHK-AXI-ID-BURST-WR",
        wres.observed_id_valid && wres.id_match(),
        $sformatf(
            "%s observed=0x%0h valid=%0d", ctx, wres.observed_id, wres.observed_id_valid)
    ));
    axi_cfg.arm_expected_read(burst_base);
    burst_read_result(burst_base, 4, rres, burst_id);
    void'(evidence.expect_equal_words("CHK-AXI-BURST-RDATA", rres.data_words, words, ctx));
    void'(evidence.expect_true(
        "CHK-AXI-ID-BURST-RD",
        rres.observed_id_valid && rres.id_match(),
        $sformatf(
            "%s observed=0x%0h valid=%0d (RLAST-beat sample)",
            ctx,
            rres.observed_id,
            rres.observed_id_valid)
    ));

    `uvm_info(get_type_name(), $sformatf("done: writes=%0d reads=%0d ID-checked results",
                                         write_transactions, read_transactions), UVM_LOW)
  endtask

endclass : ocah_axi_id_match_test_seq
