// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP no-CPU OTBN memory smoke scenario sequence, carrying the cocotb
// sep_otbn_mem_smoke_seq semantics on the CPU-LSU AXI4 splice:
//   * wait for fuse sense done, since the local fabric answers only after
//     it;
//   * read OTBN STATUS and require it to be neither LOCKED nor
//     BUSY_EXECUTE (CHK-PRECOND): a LOCKED OTBN fails memory accesses, and
//     an executing OTBN diverts a bus access to IMEM/DMEM as illegal;
//   * write the cocotb directed word to the IMEM base and to the DMEM base
//     as 32-bit beats and read each back, then random_count seeded random
//     words per memory IN ADDITION (+SEP_RANDOM_COUNT, default 5), each
//     written and read back at the same base;
//   * named evidence through the base-sequence ocah_checker: every write
//     response OKAY (CHK-WRESP); every read response OKAY and every
//     readback equal to the written word, and the DUT-side OTBN SRAM
//     request and write counters (sep_tb_if probes) advanced by exactly the
//     accesses this pass issued (CHK-OTBN-MEM). The counters make the
//     check fail if a write never reached the SRAM, or if one access split
//     into extra SRAM requests.
// Expected values come from the stimulus (written words, access counts),
// the RDL header (addresses, the STATUS field mask), and the OTBN STATUS
// encoding table of the STATUS field description in
// hw/sys/sep/regs/gen/ipxact/sep.xml. The cocotb twin is
// seq_lib/sep_otbn_mem_smoke_seq.py with tests/otbn/sep_otbn_mem_smoke_test.py.

class sep_otbn_mem_smoke_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_otbn_mem_smoke_test_seq)

  localparam string ChkPrecond = "CHK-PRECOND";
  localparam string ChkWresp = "CHK-WRESP";
  localparam string ChkOtbnMem = "CHK-OTBN-MEM";

  // Directed words of the cocotb scenario.
  localparam bit [31:0] ImemSmokeWord = 32'h0000_0013;
  localparam bit [31:0] DmemSmokeWord = 32'hA5A5_5A5A;

  // OTBN STATUS encodings, from the STATUS field description in
  // hw/sys/sep/regs/gen/ipxact/sep.xml.
  localparam bit [7:0] OtbnStatusBusyExecute = 8'h01;
  localparam bit [7:0] OtbnStatusLocked = 8'hFF;

  // SRAM accesses per word: one 32-bit write and one 32-bit readback give
  // two SRAM requests, of which one is a write. The STATUS read targets the
  // OTBN register map and does not reach either SRAM.
  localparam int unsigned ReqsPerWord = 2;
  localparam int unsigned WritesPerWord = 1;

  // System clocks between the last readback and the counter sample.
  localparam int unsigned CounterSettleCycles = 20;

  function new(string name = "sep_otbn_mem_smoke_test_seq");
    super.new(name);
  endfunction

  // One 32-bit write and readback of a memory word.
  task mem_word(bit [63:0] addr, bit [31:0] data, string label);
    bit [31:0] observed;
    csr_write_expect(ChkWresp, addr, data, OCAH_AXI_RESP_OKAY, label);
    csr_read_expect(ChkOtbnMem, addr, OCAH_AXI_RESP_OKAY, observed, label);
    check_evidence(ChkOtbnMem, label, 64'(observed), 64'(data), $sformatf(
                   "readback addr=0x%0h", addr));
  endtask

  task body();
    bit [31:0] status_word;
    bit [7:0] status;
    bit [31:0] imem_words[$];
    bit [31:0] dmem_words[$];
    bit [31:0] imem_req0, imem_wr0, dmem_req0, dmem_wr0;
    bit [31:0] imem_req, imem_wr, dmem_req, dmem_wr;

    seed_scenario_rng();
    attach_evidence('{ChkCsrResp, ChkPrecond, ChkWresp, ChkOtbnMem});
    imem_words.push_back(ImemSmokeWord);
    dmem_words.push_back(DmemSmokeWord);
    for (int unsigned r = 0; r < random_count; r++) begin
      imem_words.push_back(32'(random_pattern(32)));
      dmem_words.push_back(32'(random_pattern(32)));
    end
    `uvm_info(get_type_name(),
              $sformatf(
                  {"SEP SV-UVM OTBN memory smoke: STATUS precondition then %0d IMEM and %0d DMEM ",
                   "32-bit write/readbacks; scenario_seed=%0d random_count=%0d"},
                    imem_words.size(), dmem_words.size(), scenario_seed, random_count), UVM_LOW)

    wait_fuse_sense_done();

    log_step("1", "OTBN STATUS precondition");
    csr_read(OTBN_STATUS_REG_ADDR, status_word, "OTBN.STATUS");
    status = 8'((status_word & OTBN_STATUS_STATUS_MASK) >> OTBN_STATUS_STATUS_SHIFT);
    void'(m_check.expect_true(
        ChkPrecond,
        status != OtbnStatusLocked,
        $sformatf(
            "OTBN STATUS=0x%02h is not LOCKED (0x%02h)", status, OtbnStatusLocked)
    ));
    void'(m_check.expect_true(
        ChkPrecond,
        status != OtbnStatusBusyExecute,
        $sformatf(
            "OTBN STATUS=0x%02h is not BUSY_EXECUTE (0x%02h)", status, OtbnStatusBusyExecute)
    ));

    // Counter values at the start of the pass; the counters reset only with
    // the primary reset, so each pass checks its own increments.
    imem_req0 = tb_vif.otbn_imem_req_count;
    imem_wr0  = tb_vif.otbn_imem_write_count;
    dmem_req0 = tb_vif.otbn_dmem_req_count;
    dmem_wr0  = tb_vif.otbn_dmem_write_count;

    log_step("2", "IMEM write/readback");
    foreach (imem_words[i])
      mem_word(OTBN_IMEM_MEM_BASE_ADDR, imem_words[i], $sformatf("OTBN.IMEM[0].w%0d", i));

    log_step("3", "DMEM write/readback");
    foreach (dmem_words[i])
      mem_word(OTBN_DMEM_MEM_BASE_ADDR, dmem_words[i], $sformatf("OTBN.DMEM[0].w%0d", i));

    log_step("4", "OTBN SRAM request and write counters");
    wait_sys_cycles(CounterSettleCycles);
    imem_req = tb_vif.otbn_imem_req_count - imem_req0;
    imem_wr  = tb_vif.otbn_imem_write_count - imem_wr0;
    dmem_req = tb_vif.otbn_dmem_req_count - dmem_req0;
    dmem_wr  = tb_vif.otbn_dmem_write_count - dmem_wr0;
    check_evidence(ChkOtbnMem, "otbn_imem_req_count", 64'(imem_req),
                   64'(ReqsPerWord * imem_words.size()), $sformatf(
                   "IMEM SRAM requests this pass (start %0d)", imem_req0));
    check_evidence(ChkOtbnMem, "otbn_imem_write_count", 64'(imem_wr),
                   64'(WritesPerWord * imem_words.size()), $sformatf(
                   "IMEM SRAM writes this pass (start %0d)", imem_wr0));
    check_evidence(ChkOtbnMem, "otbn_dmem_req_count", 64'(dmem_req),
                   64'(ReqsPerWord * dmem_words.size()), $sformatf(
                   "DMEM SRAM requests this pass (start %0d)", dmem_req0));
    check_evidence(ChkOtbnMem, "otbn_dmem_write_count", 64'(dmem_wr),
                   64'(WritesPerWord * dmem_words.size()), $sformatf(
                   "DMEM SRAM writes this pass (start %0d)", dmem_wr0));
    finalize_evidence();
  endtask

endclass : sep_otbn_mem_smoke_test_seq
