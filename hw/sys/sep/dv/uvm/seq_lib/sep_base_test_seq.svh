// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base virtual sequence of every SEP scenario: runs on sep_virtual_sequencer
// and starts reusable operation sequences on the handle each step needs
// (CPU-LSU CSR accesses on p_sequencer.m_lsu_seqr). It never touches a
// driver or a VIP virtual interface; the one written exception is tb_vif
// (the SEP-local TB interface: reset sequencing and DUT observables),
// plumbed by the base test.
//
// On top of the operations it keeps the SEP-local helpers: the bounded
// fuse-sense-done wait every CSR scenario starts with (the local fabric
// answers only after it), the system-clock waits derived from the env
// period, the scoreboard compare count behind the non-vacuity evidence, and
// the per-pass named evidence (CHK-*) through the protocol-neutral
// ocah_checker, attached with the scenario's required IDs and finalized
// after the scenario so a silently skipped check cannot report PASS. Every
// draw in a pass follows seed_scenario_rng() (first statement of body()).
// The cocotb twin is cocotb/tests/sep_base_test.py (bring-up helpers) with
// cocotb/seq_lib/sep_axi_access_seq.py (operations).

class sep_base_test_seq extends ocah_sequence;
  `uvm_object_utils(sep_base_test_seq)
  `uvm_declare_p_sequencer(sep_virtual_sequencer)

  // Named-evidence IDs recorded by the shared helpers below.
  localparam string ChkFuseSense = "CHK-FUSE-SENSE-DONE";
  localparam string ChkCsrResp = "CHK-CSR-RESP";

  // Plumbed by the test before start(): the SEP-local TB interface and the
  // two configuration levels.
  virtual sep_tb_if tb_vif;
  sep_test_cfg      test_cfg;
  sep_env_cfg       env_cfg;

  // Per-pass named evidence, and the scoreboard compare counts at attach
  // time (per feature) that the non-vacuity check measures from.
  ocah_checker m_check;
  int unsigned m_sb_compares_at_attach[string];

  function new(string name = "sep_base_test_seq");
    super.new(name);
  endfunction

  // ------------------------------------------------------------------
  // Evidence plumbing.
  // ------------------------------------------------------------------

  function void attach_evidence(string required_ids[$]);
    if (tb_vif == null || test_cfg == null || env_cfg == null)
      `uvm_fatal(get_type_name(), "tb_vif/test_cfg/env_cfg not plumbed by the test")
    m_check = ocah_checker::type_id::create({get_name(), ".csr"});
    m_check.name_tag     = "sep_csr";
    m_check.required_ids = required_ids;
    m_sb_compares_at_attach.delete();
  endfunction

  // Mark the start of a pass for the scoreboard non-vacuity check of one
  // feature.
  function void mark_scoreboard_feature(string feature);
    m_sb_compares_at_attach[feature] = p_sequencer.m_scoreboard.compare_count(feature);
  endfunction

  // Non-vacuity on the DUT side: the scoreboard compares this pass added for
  // the feature must equal the predicted reads the pass issued. The count
  // only grows when the passive monitor observes an OKAY read on the DUT
  // bus and the reference model predicts it, so a read that never reached
  // the bus, or that the predictor dropped, makes this fail. The wait lets
  // the monitor publish the last read of the pass.
  task check_scoreboard_compares(string check_id, string feature, int unsigned expected_reads);
    int unsigned delta;
    if (!m_sb_compares_at_attach.exists(feature))
      `uvm_fatal(get_type_name(), {"mark_scoreboard_feature() not called for ", feature})
    wait_sys_cycles(2);
    delta = p_sequencer.m_scoreboard.compare_count(feature) - m_sb_compares_at_attach[feature];
    check_evidence(check_id, {feature, "_compares"}, 64'(delta), 64'(expected_reads),
                   "scoreboard compares this pass vs predicted reads issued");
  endtask

  function void finalize_evidence();
    if (m_check == null) `uvm_fatal(get_type_name(), "evidence checker was never attached")
    m_check.finalize(1'b1);
  endfunction

  // Record one named evidence comparison (uvm_error on mismatch).
  function void check_evidence(string check_id, string name, bit [63:0] observed,
                               bit [63:0] expected, string context_s = "");
    void'(m_check.expect_equal(check_id, observed, expected,
                               {name, context_s.len() ? " " : "", context_s}));
  endfunction

  // ------------------------------------------------------------------
  // System-clock wait (period from the env cfg the test plumbed); the reset
  // ladder belongs to the base test.
  // ------------------------------------------------------------------

  task wait_sys_cycles(int unsigned cycles);
    #(cycles * env_cfg.sys_clk_period_ns * 1ns);
  endtask

  // ------------------------------------------------------------------
  // Fabric release. The SEP-local fabric answers CSR accesses only after
  // sep_fuse_sense_done_o rises (a cycle after reset release under
  // +skip_fuse_sense, after the full OTP sense otherwise), so the poll is
  // bounded by test_cfg.fuse_sense_timeout_cycles system clocks and
  // followed by the cocotb settle window.
  //
  // CHK-FUSE-SENSE-DONE is recorded only for a real sense. Under
  // +skip_fuse_sense, efuse_shadow_regs.sv sets fuse_sense_done one cycle
  // after reset with no sense FSM, so the wait is a bring-up gate there and
  // proves nothing about the sense; a scenario that runs with the plusarg
  // must not require the ID.
  // ------------------------------------------------------------------
  task wait_fuse_sense_done();
    int unsigned cycles = 0;
    while (tb_vif.fuse_sense_done !== 1'b1) begin
      if (cycles >= test_cfg.fuse_sense_timeout_cycles) begin
        `uvm_error(get_type_name(),
                   $sformatf("sep_fuse_sense_done_o never asserted within %0d system clocks",
                             cycles))
        break;
      end
      wait_sys_cycles(1);
      cycles++;
    end
    `uvm_info(get_type_name(), $sformatf("fuse sense done after %0d system clocks", cycles),
              UVM_MEDIUM)
    wait_sys_cycles(test_cfg.fuse_sense_settle_cycles);
    if ($test$plusargs("skip_fuse_sense")) begin
      `uvm_info(get_type_name(), {
                "+skip_fuse_sense: fuse_sense_done is set by the simulation bypass, ",
                "not by a sense; no ", ChkFuseSense, " record"}, UVM_LOW)
      return;
    end
    void'(m_check.expect_true(
        ChkFuseSense,
        tb_vif.fuse_sense_done === 1'b1,
        $sformatf(
            "fuse_sense_done=%0b after %0d system clocks", tb_vif.fuse_sense_done, cycles)
    ));
  endtask

  // ------------------------------------------------------------------
  // Read-data knownness. The VIP stores RDATA two-state, so an X or Z bit
  // reads as 0 and a compare that expects 0 would pass on it. Every read
  // whose data a check grades must have known data on the lanes it
  // addressed; result.data_xz_masks holds the X/Z bits of each beat.
  // ------------------------------------------------------------------

  // Bits of the LSU beat that an access of 2**size bytes at addr covers.
  function bit [63:0] lane_bits(bit [63:0] addr, int size);
    int unsigned bytes = 1 << size;
    int unsigned first = int'(addr % SepLsuBeatBytes) & ~(bytes - 1);
    if (bytes >= SepLsuBeatBytes) return '1;
    return ((64'd1 << (8 * bytes)) - 1) << (8 * first);
  endfunction

  // Every BRESP/RRESP must be known: the VIP stores it two-state, so an X
  // or Z response would read as a legal code (X reads as OKAY).
  function void check_resp_known(ocah_axi_item result, string label);
    if (result.any_resp_xz())
      `uvm_error(get_type_name(), $sformatf(
                 "%s: response at 0x%0h has an X or Z bit", label, result.address))
  endfunction

  function void check_read_known(ocah_axi_item result, bit [63:0] addr, int size, string label);
    bit [63:0] xz = result.first_xz_mask() & lane_bits(addr, size);
    if (xz != '0)
      `uvm_error(
          get_type_name(), $sformatf(
          "%s: read data at 0x%0h has X/Z on bits 0x%016h of the addressed lanes", label, addr, xz))
  endfunction

  // ------------------------------------------------------------------
  // CSR operations: one reusable sequence per operation on the CPU-LSU
  // sequencer. Both record CHK-CSR-RESP; csr_read also requires known data.
  // ------------------------------------------------------------------

  task csr_write(bit [63:0] addr, bit [31:0] data, string label = "");
    sep_axi_csr_write_seq op = sep_axi_csr_write_seq::type_id::create("csr_write");
    op.addr = addr;
    op.data = data;
    op.start(p_sequencer.m_lsu_seqr);
    check_resp_known(op.result, label);
    check_evidence(ChkCsrResp, label.len() ? label : $sformatf("wr_0x%0h", addr),
                   64'(op.result.worst_resp()), 64'(OCAH_AXI_RESP_OKAY), $sformatf(
                   "write addr=0x%0h data=0x%08h", addr, data));
    `uvm_info(get_type_name(), $sformatf("LSU CSR WRITE %-24s addr=0x%08h data=0x%08h resp=%s",
                                         label, addr, data, op.result.worst_resp().name()),
              UVM_MEDIUM)
  endtask

  task csr_read(bit [63:0] addr, output bit [31:0] data, input string label = "");
    sep_axi_csr_read_seq op = sep_axi_csr_read_seq::type_id::create("csr_read");
    op.addr = addr;
    op.start(p_sequencer.m_lsu_seqr);
    check_resp_known(op.result, label);
    data = op.data;
    check_read_known(op.result, addr, SepCsrSize, label.len() ? label : $sformatf("rd_0x%0h", addr
                     ));
    check_evidence(ChkCsrResp, label.len() ? label : $sformatf("rd_0x%0h", addr),
                   64'(op.result.worst_resp()), 64'(OCAH_AXI_RESP_OKAY), $sformatf(
                   "read addr=0x%0h data=0x%08h", addr, data));
    `uvm_info(get_type_name(), $sformatf("LSU CSR READ  %-24s addr=0x%08h data=0x%08h resp=%s",
                                         label, addr, data, op.result.worst_resp().name()),
              UVM_MEDIUM)
  endtask

  // Read and compare against an expected value under one named check.
  task csr_read_check(string check_id, bit [63:0] addr, bit [31:0] expected, string label = "");
    bit [31:0] observed;
    csr_read(addr, observed, label);
    check_evidence(check_id, label.len() ? label : $sformatf("csr_0x%0h", addr), 64'(observed),
                   64'(expected), $sformatf("addr=0x%0h", addr));
  endtask

  // CSR access whose expected response the caller gives (a refusal check
  // expects SLVERR or DECERR). The response is recorded under check_id, not
  // CHK-CSR-RESP, and a non-OKAY response does not raise an error by itself.
  task csr_write_expect(string check_id, bit [63:0] addr, bit [31:0] data, ocah_axi_resp_e expected,
                        string label = "");
    sep_axi_csr_write_seq op = sep_axi_csr_write_seq::type_id::create("csr_write");
    op.addr = addr;
    op.data = data;
    op.check_response = 1'b0;
    op.start(p_sequencer.m_lsu_seqr);
    check_resp_known(op.result, label);
    check_evidence(check_id, label.len() ? label : $sformatf("wr_0x%0h", addr),
                   64'(op.result.worst_resp()), 64'(expected), $sformatf(
                   "write addr=0x%0h data=0x%08h resp=%s", addr, data, op.result.worst_resp().name()
                   ));
  endtask

  task csr_read_expect(string check_id, bit [63:0] addr, ocah_axi_resp_e expected,
                       output bit [31:0] data, input string label = "");
    sep_axi_csr_read_seq op = sep_axi_csr_read_seq::type_id::create("csr_read");
    op.addr = addr;
    op.check_response = 1'b0;
    op.start(p_sequencer.m_lsu_seqr);
    check_resp_known(op.result, label);
    data = op.data;
    check_read_known(op.result, addr, SepCsrSize, label.len() ? label : $sformatf("rd_0x%0h", addr
                     ));
    check_evidence(check_id, label.len() ? label : $sformatf("rd_0x%0h", addr),
                   64'(op.result.worst_resp()), 64'(expected), $sformatf(
                   "read addr=0x%0h data=0x%08h resp=%s", addr, data, op.result.worst_resp().name()
                   ));
  endtask

  // Raw single-beat access at any address and size (memory words, narrow or
  // misaligned beats). Neither records evidence nor escalates the response:
  // the caller grades the returned item's data and response.
  task bus_write(bit [63:0] addr, bit [63:0] word, bit [7:0] strb, int size,
                 output ocah_axi_item result, input string label = "");
    sep_axi_bus_write_seq op = sep_axi_bus_write_seq::type_id::create("bus_write");
    op.addr = addr;
    op.word = word;
    op.strb = strb;
    op.size = size;
    op.start(p_sequencer.m_lsu_seqr);
    check_resp_known(op.result, label);
    result = op.result;
    `uvm_info(get_type_name(),
              $sformatf("LSU BUS WRITE %-24s addr=0x%08h size=%0d strb=0x%02h data=0x%016h resp=%s",
                        label, addr, size, strb, word, result.worst_resp().name()), UVM_MEDIUM)
  endtask

  task bus_read(bit [63:0] addr, int size, output ocah_axi_item result, input string label = "");
    sep_axi_bus_read_seq op = sep_axi_bus_read_seq::type_id::create("bus_read");
    op.addr = addr;
    op.size = size;
    op.start(p_sequencer.m_lsu_seqr);
    check_resp_known(op.result, label);
    result = op.result;
    `uvm_info(get_type_name(),
              $sformatf("LSU BUS READ  %-24s addr=0x%08h size=%0d data=0x%016h resp=%s", label,
                        addr, size, result.first_data(), result.worst_resp().name()), UVM_MEDIUM)
  endtask

endclass : sep_base_test_seq
