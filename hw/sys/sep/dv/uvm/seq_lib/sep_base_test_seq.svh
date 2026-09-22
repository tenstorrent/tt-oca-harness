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
// period, the CSR access counter behind the non-vacuity evidence, and the
// per-pass named evidence (CHK-*) through the protocol-neutral
// ocah_checker, attached with the scenario's required IDs and finalized
// after the scenario so a silently skipped check cannot report PASS. Every
// draw in a pass follows seed_scenario_rng() (first statement of body()).
// The cocotb twin is tests/sep_base_test.py (bring-up helpers) with
// seq_lib/sep_axi_access_seq.py (operations).

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

  // Per-pass named evidence and the CSR access count it certifies.
  ocah_checker m_check;
  int unsigned csr_accesses;

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
    csr_accesses = 0;
  endfunction

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
    #(cycles * env_cfg.clk_period_ns * 1ns);
  endtask

  // ------------------------------------------------------------------
  // Fabric release. The SEP-local fabric answers CSR accesses only after
  // sep_fuse_sense_done_o rises (a cycle after reset release under
  // +skip_fuse_sense, after the full OTP sense otherwise), so the poll is
  // bounded by test_cfg.fuse_sense_timeout_cycles system clocks and
  // followed by the cocotb settle window; the OTP JTAG2AXIL disable bits
  // must both read 0 once sense is done (the fuse controller enforces
  // access, the lifecycle controller ties both to 0).
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
    void'(m_check.expect_true(
        ChkFuseSense,
        tb_vif.fuse_sense_done === 1'b1,
        $sformatf(
            "fuse_sense_done=%0b after %0d system clocks", tb_vif.fuse_sense_done, cycles)
    ));
  endtask

  // ------------------------------------------------------------------
  // CSR operations: one reusable sequence per operation on the CPU-LSU
  // sequencer. Both record CHK-CSR-RESP and count toward csr_accesses.
  // ------------------------------------------------------------------

  task csr_write(bit [63:0] addr, bit [31:0] data, string label = "");
    sep_axi_csr_write_seq op = sep_axi_csr_write_seq::type_id::create("csr_write");
    op.addr = addr;
    op.data = data;
    op.start(p_sequencer.m_lsu_seqr);
    csr_accesses++;
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
    csr_accesses++;
    data = op.data;
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

endclass : sep_base_test_seq
