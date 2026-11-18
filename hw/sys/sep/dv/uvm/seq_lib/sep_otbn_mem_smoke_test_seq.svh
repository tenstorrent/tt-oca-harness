// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP no-CPU OTBN memory smoke scenario sequence, carrying the cocotb
// sep_otbn_mem_smoke_seq semantics on the CPU-LSU AXI4 splice:
//   * wait for fuse sense done, since the local fabric answers only after
//     it;
//   * read OTBN STATUS (response under CHK-CSR-RESP) and require its status
//     field to be BUSY_SEC_WIPE_INT, the post-reset internal wipe that lasts
//     the whole no_cpu run: `CTRL-OTBN-MEM-PRECOND seen: ...`, or
//     `CTRL-MISSING OTBN-MEM-PRECOND: ...` as a UVM_ERROR;
//   * write the cocotb directed word to the IMEM base and to the DMEM base
//     as 32-bit beats and read each back, then random_count seeded random
//     words per memory IN ADDITION (+SEP_RANDOM_COUNT, default 5), each
//     written and read back at the same base;
//   * log the response codes, the readbacks and the DUT-side OTBN SRAM
//     request and write counter increments (sep_tb_if probes) on one
//     OBS-OTBN-MEM-BUSY-ACCESS line per memory. They are not graded: the
//     OTBN register text states that while OTBN is busy a memory read
//     returns 0, a write is ignored and the access raises
//     ILLEGAL_BUS_ACCESS; during the internal wipe the result is logged
//     under the OTBN wipe-state memory access exception
//     (docs/test_contracts/smoke_uvm.adoc). An X/Z response or read data and a timed-out access
//     still raise a UVM_ERROR.
// Addresses and the STATUS field mask come from the RDL header; the STATUS
// encoding from the STATUS field description in
// hw/sys/sep/regs/gen/ipxact/sep.xml. The cocotb twin is
// cocotb/seq_lib/sep_otbn_mem_smoke_seq.py with cocotb/tests/otbn/sep_otbn_mem_smoke_test.py.

class sep_otbn_mem_smoke_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_otbn_mem_smoke_test_seq)

  // Directed words of the cocotb scenario.
  localparam bit [31:0] ImemSmokeWord = 32'h0000_0013;
  localparam bit [31:0] DmemSmokeWord = 32'hA5A5_5A5A;

  // OTBN STATUS encoding, from the STATUS field description in
  // hw/sys/sep/regs/gen/ipxact/sep.xml.
  localparam bit [7:0] OtbnStatusBusySecWipeInt = 8'h04;

  // System clocks between the last readback and the counter sample.
  localparam int unsigned CounterSettleCycles = 20;

  function new(string name = "sep_otbn_mem_smoke_test_seq");
    super.new(name);
  endfunction

  // One 32-bit write and readback of a memory word; responses and data are
  // returned for the OBS line, not graded.
  task mem_word(bit [63:0] addr, bit [31:0] data, string label, output string fields);
    sep_axi_csr_write_seq wr = sep_axi_csr_write_seq::type_id::create("mem_write");
    sep_axi_csr_read_seq rd = sep_axi_csr_read_seq::type_id::create("mem_read");
    wr.addr = addr;
    wr.data = data;
    wr.check_response = 1'b0;
    wr.start(p_sequencer.m_lsu_seqr);
    check_resp_known(wr.result, label);
    rd.addr = addr;
    rd.check_response = 1'b0;
    rd.start(p_sequencer.m_lsu_seqr);
    check_resp_known(rd.result, label);
    check_read_known(rd.result, addr, SepCsrSize, label);
    fields = $sformatf(
        "%s wr_resp=%0d rd_resp=%0d written=0x%08h readback=0x%08h",
        label,
        wr.result.worst_resp(),
        rd.result.worst_resp(),
        data,
        rd.data
    );
  endtask

  task body();
    bit [31:0] status_word;
    bit [7:0] status;
    bit [31:0] imem_words[$];
    bit [31:0] dmem_words[$];
    string imem_fields[$];
    string dmem_fields[$];
    string f;
    bit [31:0] imem_req0, imem_wr0, dmem_req0, dmem_wr0;
    string ctrl_fields;

    seed_scenario_rng();
    attach_evidence('{ChkCsrResp});
    imem_words.push_back(ImemSmokeWord);
    dmem_words.push_back(DmemSmokeWord);
    for (int unsigned r = 0; r < random_count; r++) begin
      imem_words.push_back(32'(random_pattern(32)));
      dmem_words.push_back(32'(random_pattern(32)));
    end
    `uvm_info(
        get_type_name(),
        $sformatf({"SEP SV-UVM OTBN memory smoke: STATUS control then %0d IMEM and %0d DMEM ",
                   "32-bit write/readbacks; scenario_seed=%0d random_count=%0d"},
                    imem_words.size(), dmem_words.size(), scenario_seed, random_count), UVM_LOW)

    wait_fuse_sense_done();

    log_step("1", "OTBN STATUS control");
    csr_read(OTBN_STATUS_REG_ADDR, status_word, "OTBN.STATUS");
    status = 8'((status_word & OTBN_STATUS_STATUS_MASK) >> OTBN_STATUS_STATUS_SHIFT);
    ctrl_fields = $sformatf("status=0x%08h status_code=0x%02h expect=0x%02h", status_word, status,
                            OtbnStatusBusySecWipeInt);
    if (status != OtbnStatusBusySecWipeInt)
      `uvm_error(get_type_name(), {"CTRL-MISSING OTBN-MEM-PRECOND: ", ctrl_fields})
    else `uvm_info(get_type_name(), {"CTRL-OTBN-MEM-PRECOND seen: ", ctrl_fields}, UVM_LOW)

    // Counter values at the start of the pass; the counters reset only with
    // the primary reset, so each pass logs its own increments.
    imem_req0 = tb_vif.otbn_imem_req_count;
    imem_wr0  = tb_vif.otbn_imem_write_count;
    dmem_req0 = tb_vif.otbn_dmem_req_count;
    dmem_wr0  = tb_vif.otbn_dmem_write_count;

    log_step("2", "IMEM write/readback");
    foreach (imem_words[i]) begin
      mem_word(OTBN_IMEM_MEM_BASE_ADDR, imem_words[i], $sformatf("w%0d", i), f);
      imem_fields.push_back(f);
    end

    log_step("3", "DMEM write/readback");
    foreach (dmem_words[i]) begin
      mem_word(OTBN_DMEM_MEM_BASE_ADDR, dmem_words[i], $sformatf("w%0d", i), f);
      dmem_fields.push_back(f);
    end

    log_step("4", "OTBN SRAM request and write counters");
    wait_sys_cycles(CounterSettleCycles);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "OBS-OTBN-MEM-BUSY-ACCESS mem=imem status=0x%08h reqs=%0d writes=%0d words=%0d %p",
            status_word, tb_vif.otbn_imem_req_count - imem_req0,
            tb_vif.otbn_imem_write_count - imem_wr0, imem_words.size(), imem_fields), UVM_LOW)
    `uvm_info(
        get_type_name(),
        $sformatf(
            "OBS-OTBN-MEM-BUSY-ACCESS mem=dmem status=0x%08h reqs=%0d writes=%0d words=%0d %p",
            status_word, tb_vif.otbn_dmem_req_count - dmem_req0,
            tb_vif.otbn_dmem_write_count - dmem_wr0, dmem_words.size(), dmem_fields), UVM_LOW)
    finalize_evidence();
  endtask

endclass : sep_otbn_mem_smoke_test_seq
