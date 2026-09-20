// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base virtual sequence of every SMC scenario: runs on smc_virtual_sequencer
// and starts reusable operation sequences on the handle each step needs
// (SEP_IN CSR accesses on p_sequencer.m_sep_in_seqr). It never touches a
// driver or a VIP virtual interface; the one written exception is tb_vif
// (the SMC-local TB interface: reset sequencing and DUT observables),
// plumbed by the base test.
//
// On top of the operations it keeps the SMC-local helpers: the bounded
// fuse-sense / warm-domain release wait every CSR scenario starts with, the
// clock-domain waits derived from the env periods, the CSR access counter
// behind the non-vacuity evidence, and the per-pass named evidence
// (CHK-*) through the protocol-neutral ocah_checker, attached with the
// scenario's required IDs and finalized after the scenario so a silently
// skipped check cannot report PASS. Every draw in a pass follows
// seed_scenario_rng() (first statement of body()). The cocotb twin is
// seq_lib/smc_base_test_seq.py.

class smc_base_test_seq extends ocah_sequence;
  `uvm_object_utils(smc_base_test_seq)
  `uvm_declare_p_sequencer(smc_virtual_sequencer)

  // Named-evidence IDs recorded by the shared helpers below.
  localparam string ChkFuseSense = "CHK-FUSE-SENSE-DONE";
  localparam string ChkCsrResp = "CHK-CSR-RESP";
  localparam string ChkMemResp = "CHK-MEM-RESP";
  localparam string ChkSbMinAct = "CHK-SB-MIN-ACTIVITY";

  // Plumbed by the test before start(): the SMC-local TB interface, the two
  // configuration levels, and the always-on scoreboard whose per-feature
  // comparison counts are the one activity number this sequence does not
  // produce itself.
  virtual smc_tb_if tb_vif;
  smc_test_cfg      test_cfg;
  smc_env_cfg       env_cfg;
  smc_scoreboard    scoreboard;

  // Per-pass named evidence and the access counts it certifies, kept apart so
  // a scenario's non-vacuity claim names the access shape it actually issued.
  ocah_checker m_check;
  int unsigned csr_accesses;
  int unsigned mem_accesses;

  function new(string name = "smc_base_test_seq");
    super.new(name);
  endfunction

  // ------------------------------------------------------------------
  // Evidence plumbing.
  // ------------------------------------------------------------------

  function void attach_evidence(string required_ids[$]);
    if (tb_vif == null || test_cfg == null || env_cfg == null || scoreboard == null)
      `uvm_fatal(get_type_name(), "tb_vif/test_cfg/env_cfg/scoreboard not plumbed by the test")
    m_check = ocah_checker::type_id::create({get_name(), ".csr"});
    m_check.name_tag     = "smc_csr";
    m_check.required_ids = required_ids;
    csr_accesses = 0;
    mem_accesses = 0;
  endfunction

  function void finalize_evidence();
    if (m_check == null) `uvm_fatal(get_type_name(), "evidence checker was never attached")
    m_check.finalize(1'b1);
  endfunction

  // Record one completed-with-OKAY response. is_ok() is the predicate, NOT
  // worst_resp(): ocah_axi_worst_resp() returns OKAY for an EMPTY response
  // list, which is exactly what a watchdog expiry leaves behind, so comparing
  // the worst response would record PASS for an access that got no response
  // at all. ocah_axi_resp_ok() returns 0 on an empty list.
  function void check_response(string check_id, ocah_axi_item result, string name,
                               string context_s = "");
    void'(m_check.expect_true(
        check_id,
        result.is_ok(),
        $sformatf(
            "%s %s resp=%s beats=%0d timed_out=%0b",
            name,
            context_s,
            result.worst_resp().name(),
            result.resp_list.size(),
            result.timed_out)
    ));
  endfunction

  // Record one named evidence comparison (uvm_error on mismatch).
  function void check_evidence(string check_id, string name, bit [63:0] observed,
                               bit [63:0] expected, string context_s = "");
    void'(m_check.expect_equal(check_id, observed, expected,
                               {name, context_s.len() ? " " : "", context_s}));
  endfunction

  // ------------------------------------------------------------------
  // Observed minimum activity. csr_accesses / mem_accesses are produced by
  // this sequence on both sides of their compare, so they reconcile the body
  // against its own loop bounds and catch a truncated pass -- they cannot
  // catch a monitor that saw nothing. This one takes its left operand from
  // the always-on scoreboard, which is fed by the PASSIVE monitor and the
  // reference models, and its right operand from the scenario's construction.
  //
  // It reads the count as it stood when this pass STARTED, so the compare is
  // against `loop_index` completed passes and never races the pairing of an
  // item this pass has not issued yet. A floor rather than an equality: this
  // is the minimum-activity count the stimulus implies, and other features
  // may legitimately record more.
  // ------------------------------------------------------------------
  function void check_min_activity(string feature, int unsigned per_pass);
    int unsigned observed = scoreboard.compare_count(feature);
    int unsigned floor_v  = loop_index * per_pass;
    void'(m_check.expect_true(
        ChkSbMinAct,
        observed >= floor_v,
        $sformatf(
            {
              "feature=%s scoreboard compares=%0d after %0d completed passes, ",
              "floor=%0d (%0d predicted reads per pass)"
            },
            feature,
            observed,
            loop_index,
            floor_v,
            per_pass)
    ));
  endfunction

  // ------------------------------------------------------------------
  // smc-clock wait (period from the env cfg the test plumbed); the ref-clock
  // ladder belongs to the base test.
  // ------------------------------------------------------------------

  task wait_smc_cycles(int unsigned cycles);
    #(cycles * env_cfg.clk_period_ns * 1ns);
  endtask

  // ------------------------------------------------------------------
  // Warm-domain release. SCRATCH_COLD_WARM and the other warm-reset CSRs
  // stay in reset until rst_warm deasserts; that path is fuse_sense_done
  // -> delayed fuse_reset_n -> rst_warm sync, so all three observables are
  // waited on in order, each bounded by test_cfg.fuse_sense_timeout_cycles
  // smc clocks (cocotb wait_fuse_sense_done parity).
  // ------------------------------------------------------------------
  task wait_fuse_sense_done();
    bit ok = 1'b1;
    bit reached;
    wait_observable_high("fuse_sense_done", reached);
    ok &= reached;
    wait_observable_high("fuse_reset_n", reached);
    ok &= reached;
    wait_observable_high("rst_warm_smc_clk_n", reached);
    ok &= reached;
    void'(m_check.expect_true(
        ChkFuseSense,
        ok,
        $sformatf(
            "fuse_sense_done=%0b fuse_reset_n=%0b rst_warm_smc_clk_n=%0b",
            tb_vif.fuse_sense_done,
            tb_vif.fuse_reset_n,
            tb_vif.rst_warm_smc_clk_n)
    ));
  endtask

  protected function bit observable(string which);
    case (which)
      "fuse_sense_done":    return tb_vif.fuse_sense_done === 1'b1;
      "fuse_reset_n":       return tb_vif.fuse_reset_n === 1'b1;
      "rst_warm_smc_clk_n": return tb_vif.rst_warm_smc_clk_n === 1'b1;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown observable %s", which))
        return 1'b0;
      end
    endcase
  endfunction

  // Bounded poll of one observable; returns 0 (and errors) on expiry.
  protected task wait_observable_high(string which, output bit reached);
    int unsigned cycles = 0;
    while (!observable(
        which
    )) begin
      if (cycles >= test_cfg.fuse_sense_timeout_cycles) begin
        `uvm_error(get_type_name(), $sformatf("%s never asserted within %0d smc clocks", which,
                                              cycles))
        reached = 1'b0;
        return;
      end
      wait_smc_cycles(1);
      cycles++;
    end
    `uvm_info(get_type_name(), $sformatf("%s high after %0d smc clocks", which, cycles), UVM_MEDIUM)
    reached = 1'b1;
  endtask

  // ------------------------------------------------------------------
  // CSR operations: one reusable sequence per operation on the SEP_IN
  // sequencer. Both record CHK-CSR-RESP and count toward csr_accesses.
  // ------------------------------------------------------------------

  task csr_write(bit [63:0] addr, bit [31:0] data, string label = "");
    smc_axi_csr_write_seq op = smc_axi_csr_write_seq::type_id::create("csr_write");
    op.addr = addr;
    op.data = data;
    op.start(p_sequencer.m_sep_in_seqr);
    csr_accesses++;
    check_response(ChkCsrResp, op.result, label.len() ? label : $sformatf("wr_0x%0h", addr),
                   $sformatf("write addr=0x%0h data=0x%08h", addr, data));
    `uvm_info(get_type_name(), $sformatf("SEP_IN CSR WRITE %-24s addr=0x%014h data=0x%08h resp=%s",
                                         label, addr, data, op.result.worst_resp().name()),
              UVM_MEDIUM)
  endtask

  task csr_read(bit [63:0] addr, output bit [31:0] data, input string label = "");
    smc_axi_csr_read_seq op = smc_axi_csr_read_seq::type_id::create("csr_read");
    op.addr = addr;
    op.start(p_sequencer.m_sep_in_seqr);
    csr_accesses++;
    data = op.data;
    check_response(ChkCsrResp, op.result, label.len() ? label : $sformatf("rd_0x%0h", addr),
                   $sformatf("read addr=0x%0h data=0x%08h", addr, data));
    `uvm_info(get_type_name(), $sformatf("SEP_IN CSR READ  %-24s addr=0x%014h data=0x%08h resp=%s",
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

  // ------------------------------------------------------------------
  // Memory operations: one reusable sequence per operation on the SEP_IN
  // sequencer, full-width 64-bit single beats (AxSIZE = 3) rather than the
  // 32-bit CSR shape above. Both record CHK-MEM-RESP and count toward
  // mem_accesses.
  // ------------------------------------------------------------------

  task mem_write(bit [63:0] addr, bit [63:0] data, string label = "");
    smc_axi_mem_write_seq op = smc_axi_mem_write_seq::type_id::create("mem_write");
    op.addr = addr;
    op.data = data;
    op.start(p_sequencer.m_sep_in_seqr);
    mem_accesses++;
    check_response(ChkMemResp, op.result, label.len() ? label : $sformatf("wr_0x%0h", addr),
                   $sformatf("write addr=0x%0h data=0x%016h", addr, data));
    `uvm_info(get_type_name(),
              $sformatf("SEP_IN MEM WRITE %-24s addr=0x%014h data=0x%016h resp=%s", label, addr,
                        data, op.result.worst_resp().name()), UVM_MEDIUM)
  endtask

  task mem_read(bit [63:0] addr, output bit [63:0] data, input string label = "");
    smc_axi_mem_read_seq op = smc_axi_mem_read_seq::type_id::create("mem_read");
    op.addr = addr;
    op.start(p_sequencer.m_sep_in_seqr);
    mem_accesses++;
    data = op.data;
    check_response(ChkMemResp, op.result, label.len() ? label : $sformatf("rd_0x%0h", addr),
                   $sformatf("read addr=0x%0h data=0x%016h", addr, data));
    `uvm_info(get_type_name(),
              $sformatf("SEP_IN MEM READ  %-24s addr=0x%014h data=0x%016h resp=%s", label, addr,
                        data, op.result.worst_resp().name()), UVM_MEDIUM)
  endtask

  // Read one 64-bit word and compare it against an expected value.
  task mem_read_check(string check_id, bit [63:0] addr, bit [63:0] expected, string label = "");
    bit [63:0] observed;
    mem_read(addr, observed, label);
    check_evidence(check_id, label.len() ? label : $sformatf("mem_0x%0h", addr), observed, expected,
                   $sformatf("addr=0x%0h", addr));
  endtask

endclass : smc_base_test_seq
