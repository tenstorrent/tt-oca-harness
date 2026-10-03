// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP no-CPU IP-interrupt to aggregator scenario sequence, carrying the
// cocotb sep_irq_ip_to_aggregator_test semantics on the CPU-LSU AXI4 splice:
//   * per covered source (CSRNG, EDN, HMAC error, Secure DMA done / chunk /
//     error), the 3-phase walk through the IP's own INTR_ENABLE / INTR_TEST /
//     INTR_STATE registers, observed on the sep_internal_interrupts aggregate
//     through the sep_tb_if observation probe:
//       CHK-BASE  INTR_TEST=0 and W1C INTR_STATE, then the aggregate bit is 0;
//       CHK-SET   INTR_ENABLE + INTR_TEST, then the aggregate bit is 1 and the
//                 INTR_STATE bit is 1;
//       CHK-ISO   in one sample while the source is asserted, the other
//                 covered bits are 0 (each of them is 1 in its own CHK-SET of
//                 the same pass, which is the control);
//       CHK-CLR   Event: INTR_TEST=0 alone leaves the aggregate bit at 1 for
//                 StickyHoldCycles clocks and the INTR_STATE bit at 1, then
//                 W1C INTR_STATE; Status: INTR_TEST=0; then the aggregate bit
//                 and the INTR_STATE bit are 0;
//     then INTR_ENABLE returns to 0, so each pass starts from the reset
//     enables; CHK-AGG requires every covered source to pass all four;
//   * one in-window unmapped read through the Secure DMA adapter, the same
//     hole written with a seeded random word, and one read through each of
//     the HMAC, KMAC and OTBN adapters: each completes SLVERR, latches
//     exactly its DMA_BUS_ERR_STATUS / PERIPH_BUS_ERR_STATUS bit, raises
//     aggregator bit 40 or 42 and not the other, and clears on the matching
//     CLEAR write (CHK-BUSERR-*).
// Every aggregate-bit check requires the sampled bit to be 0 or 1, so an
// undriven (X) bit cannot satisfy "== 0". Expected values come from the
// generated register header (addresses, field masks), the DV-owned PIC
// table below, and the stimulus. The cocotb twin is
// tests/system/sep_irq_ip_to_aggregator_test.py with
// seq_lib/sep_irq_aggregator_seq.py.

class sep_irq_ip_to_aggregator_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_irq_ip_to_aggregator_test_seq)

  localparam string ChkBase = "CHK-BASE";
  localparam string ChkSet = "CHK-SET";
  localparam string ChkIso = "CHK-ISO";
  localparam string ChkClr = "CHK-CLR";
  localparam string ChkAgg = "CHK-AGG";
  localparam string ChkBusErrBase = "CHK-BUSERR-BASE";
  localparam string ChkBusErrDma = "CHK-BUSERR-DMA";
  localparam string ChkBusErrDmaWr = "CHK-BUSERR-DMA-WR";
  localparam string ChkBusErrDmaWrClr = "CHK-BUSERR-DMA-WR-CLR";
  localparam string ChkBusErrPeriph = "CHK-BUSERR-PERIPH";
  localparam string ChkBusErrClr = "CHK-BUSERR-CLR";

  // DV-owned PIC source table, transcribed from hw/sys/sep/doc/interrupts.adoc
  // (sep-pic-source-assignments-table; PIC sources are 1-based). The same doc
  // ("Sources and Routing") states that bit i of sep_internal_interrupts is
  // PIC source i + 1.
  localparam int unsigned PicDmaDone = 9;
  localparam int unsigned PicDmaChunkDone = 10;
  localparam int unsigned PicDmaError = 11;
  localparam int unsigned PicHmacError = 20;
  localparam int unsigned PicCsrngCmdReqDone = 24;
  localparam int unsigned PicCsrngEntropyReq = 25;
  localparam int unsigned PicCsrngHwInstExc = 26;
  localparam int unsigned PicCsrngFatalErr = 27;
  localparam int unsigned PicEdnCmdReqDone = 28;
  localparam int unsigned PicEdnFatalErr = 29;
  localparam int unsigned PicDmaRegPathErr = 41;
  localparam int unsigned PicDmaHostPathErr = 42;
  localparam int unsigned PicPeriphBridgeFault = 43;

  localparam int unsigned AggDmaRegPath = PicDmaRegPathErr - 1;
  localparam int unsigned AggDmaHostPath = PicDmaHostPathErr - 1;
  localparam int unsigned AggPeriphOr = PicPeriphBridgeFault - 1;

  // System clocks an aggregate-bit poll waits (cocotb _poll_agg parity).
  localparam int unsigned AggPollCycles = 200;
  // System clocks an Event source must hold its aggregate bit at 1 after
  // INTR_TEST=0 and before the W1C (cocotb _STICKY_HOLD).
  localparam int unsigned StickyHoldCycles = 32;

  // One covered interrupt source: its IP INTR_* registers, its bit in each,
  // and its aggregate bit. A Status source has a read-only INTR_STATE and
  // deasserts on INTR_TEST=0; an Event source deasserts on W1C INTR_STATE.
  typedef struct {
    string       name;
    bit [63:0]   state_addr;
    bit [63:0]   enable_addr;
    bit [63:0]   test_addr;
    bit [31:0]   state_mask;
    bit [31:0]   enable_mask;
    bit [31:0]   test_mask;
    int unsigned agg_idx;
    bit          is_status;
  } irq_src_t;

  // One in-window adapter hole and the PERIPH_BUS_ERR_* bits it must raise.
  typedef struct {
    string     name;
    bit [63:0] addr;
    bit [31:0] status_mask;
    bit [31:0] clear_mask;
  } periph_hole_t;

  function new(string name = "sep_irq_ip_to_aggregator_test_seq");
    super.new(name);
  endfunction

  // The covered sources (cocotb IRQ_TABLE). HMAC/KMAC fifo_empty Status
  // bits are idle-true and are not walked.
  function void irq_sources(ref irq_src_t srcs[$]);
    srcs.delete();
    srcs.push_back('{"csrng_cmd_req_done", 64'(CSRNG_INTR_STATE_REG_ADDR),
                   64'(CSRNG_INTR_ENABLE_REG_ADDR), 64'(CSRNG_INTR_TEST_REG_ADDR),
                   CSRNG_INTR_STATE_CS_CMD_REQ_DONE_MASK, CSRNG_INTR_ENABLE_CS_CMD_REQ_DONE_MASK,
                   CSRNG_INTR_TEST_CS_CMD_REQ_DONE_MASK, PicCsrngCmdReqDone - 1, 1'b0});
    srcs.push_back('{"csrng_entropy_req", 64'(CSRNG_INTR_STATE_REG_ADDR),
                   64'(CSRNG_INTR_ENABLE_REG_ADDR), 64'(CSRNG_INTR_TEST_REG_ADDR),
                   CSRNG_INTR_STATE_CS_ENTROPY_REQ_MASK, CSRNG_INTR_ENABLE_CS_ENTROPY_REQ_MASK,
                   CSRNG_INTR_TEST_CS_ENTROPY_REQ_MASK, PicCsrngEntropyReq - 1, 1'b0});
    srcs.push_back('{"csrng_hw_inst_exc", 64'(CSRNG_INTR_STATE_REG_ADDR),
                   64'(CSRNG_INTR_ENABLE_REG_ADDR), 64'(CSRNG_INTR_TEST_REG_ADDR),
                   CSRNG_INTR_STATE_CS_HW_INST_EXC_MASK, CSRNG_INTR_ENABLE_CS_HW_INST_EXC_MASK,
                   CSRNG_INTR_TEST_CS_HW_INST_EXC_MASK, PicCsrngHwInstExc - 1, 1'b0});
    srcs.push_back('{"csrng_fatal_err", 64'(CSRNG_INTR_STATE_REG_ADDR),
                   64'(CSRNG_INTR_ENABLE_REG_ADDR), 64'(CSRNG_INTR_TEST_REG_ADDR),
                   CSRNG_INTR_STATE_CS_FATAL_ERR_MASK, CSRNG_INTR_ENABLE_CS_FATAL_ERR_MASK,
                   CSRNG_INTR_TEST_CS_FATAL_ERR_MASK, PicCsrngFatalErr - 1, 1'b0});
    srcs.push_back('{"edn_cmd_req_done", 64'(EDN_INTR_STATE_REG_ADDR),
                   64'(EDN_INTR_ENABLE_REG_ADDR), 64'(EDN_INTR_TEST_REG_ADDR),
                   EDN_INTR_STATE_EDN_CMD_REQ_DONE_MASK, EDN_INTR_ENABLE_EDN_CMD_REQ_DONE_MASK,
                   EDN_INTR_TEST_EDN_CMD_REQ_DONE_MASK, PicEdnCmdReqDone - 1, 1'b0});
    srcs.push_back('{"edn_fatal_err", 64'(EDN_INTR_STATE_REG_ADDR), 64'(EDN_INTR_ENABLE_REG_ADDR),
                   64'(EDN_INTR_TEST_REG_ADDR), EDN_INTR_STATE_EDN_FATAL_ERR_MASK,
                   EDN_INTR_ENABLE_EDN_FATAL_ERR_MASK, EDN_INTR_TEST_EDN_FATAL_ERR_MASK,
                   PicEdnFatalErr - 1, 1'b0});
    srcs.push_back('{"hmac_err", 64'(HMAC_INTR_STATE_REG_ADDR), 64'(HMAC_INTR_ENABLE_REG_ADDR),
                   64'(HMAC_INTR_TEST_REG_ADDR), HMAC_INTR_STATE_HMAC_ERR_MASK,
                   HMAC_INTR_ENABLE_HMAC_ERR_MASK, HMAC_INTR_TEST_HMAC_ERR_MASK, PicHmacError - 1,
                   1'b0});
    srcs.push_back('{"dma_done", 64'(SECURE_DMA_INTR_STATE_REG_ADDR),
                   64'(SECURE_DMA_INTR_ENABLE_REG_ADDR), 64'(SECURE_DMA_INTR_TEST_REG_ADDR),
                   SECURE_DMA_INTR_STATE_DMA_DONE_MASK, SECURE_DMA_INTR_ENABLE_DMA_DONE_MASK,
                   SECURE_DMA_INTR_TEST_DMA_DONE_MASK, PicDmaDone - 1, 1'b1});
    srcs.push_back('{"dma_chunk_done", 64'(SECURE_DMA_INTR_STATE_REG_ADDR),
                   64'(SECURE_DMA_INTR_ENABLE_REG_ADDR), 64'(SECURE_DMA_INTR_TEST_REG_ADDR),
                   SECURE_DMA_INTR_STATE_DMA_CHUNK_DONE_MASK,
                   SECURE_DMA_INTR_ENABLE_DMA_CHUNK_DONE_MASK,
                   SECURE_DMA_INTR_TEST_DMA_CHUNK_DONE_MASK, PicDmaChunkDone - 1, 1'b1});
    srcs.push_back('{"dma_error", 64'(SECURE_DMA_INTR_STATE_REG_ADDR),
                   64'(SECURE_DMA_INTR_ENABLE_REG_ADDR), 64'(SECURE_DMA_INTR_TEST_REG_ADDR),
                   SECURE_DMA_INTR_STATE_DMA_ERROR_MASK, SECURE_DMA_INTR_ENABLE_DMA_ERROR_MASK,
                   SECURE_DMA_INTR_TEST_DMA_ERROR_MASK, PicDmaError - 1, 1'b1});
  endfunction

  // First unused word after `last_reg` and before `next_base`: an address
  // inside the adapter window that owns no register, so the adapter (not the
  // crossbar) answers it. A closed gap is a configuration defect.
  function bit [63:0] hole_after(string name, bit [63:0] last_reg, bit [63:0] next_base);
    bit [63:0] hole = last_reg + SepCsrBytes;
    if (hole >= next_base)
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s register gap closed: 0x%08h >= 0x%08h", name, hole, next_base))
    return hole;
  endfunction

  // Secure DMA: between the last INTR_SRC_ADDR word and the first
  // INTR_SRC_WR_VAL word.
  function bit [63:0] dma_hole();
    return hole_after(
        "SECURE_DMA",
        64'(SECURE_DMA_INTR_SRC_ADDR_0_10__REG_ADDR),
        64'(SECURE_DMA_INTR_SRC_WR_VAL_0_0__REG_ADDR)
    );
  endfunction

  // HMAC CSR/MSG_FIFO, KMAC CSR/STATE and OTBN CSR/IMEM gaps.
  function void periph_holes(ref periph_hole_t holes[$]);
    holes.delete();
    holes.push_back(
        '{"hmac",
        hole_after("HMAC", 64'(HMAC_MSG_LENGTH_UPPER_REG_ADDR), 64'(HMAC_MSG_FIFO_MEM_BASE_ADDR)),
        32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_HMAC_MASK),
        32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_CLEAR_HMAC_MASK)});
    holes.push_back('{"kmac",
                    hole_after("KMAC", 64'(KMAC_ERR_CODE_REG_ADDR), 64'(KMAC_STATE_MEM_BASE_ADDR)),
                    32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_KMAC_MASK),
                    32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_CLEAR_KMAC_MASK)});
    holes.push_back(
        '{"otbn",
        hole_after("OTBN", 64'(OTBN_LOAD_CHECKSUM_REG_ADDR), 64'(OTBN_IMEM_MEM_BASE_ADDR)),
        32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_OTBN_MASK),
        32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_CLEAR_OTBN_MASK)});
  endfunction

  // ------------------------------------------------------------------
  // Aggregate-vector observation (sep_tb_if probe, 4-state).
  // ------------------------------------------------------------------

  // One sample of the aggregate vector, one system clock after the call.
  task sample_agg(output logic [63:0] vec);
    wait_sys_cycles(1);
    vec = tb_vif.sep_internal_interrupts;
  endtask

  // Poll aggregate bit idx until it reads `expected` (0 or 1, never X), for
  // at most AggPollCycles system clocks, and record the result under
  // check_id.
  task check_agg_bit(string check_id, int unsigned idx, bit expected, string label,
                     output bit passed);
    logic [63:0] vec;
    int unsigned cycles;
    for (cycles = 1; cycles <= AggPollCycles; cycles++) begin
      sample_agg(vec);
      if (vec[idx] === expected) break;
    end
    passed = m_check.expect_true(
        check_id,
        vec[idx] === expected,
        $sformatf(
            "%s agg[%0d]=%b expected=%0b cycles=%0d vec=0x%011h",
            label,
            idx,
            vec[idx],
            expected,
            cycles,
            vec)
    );
  endtask

  // One fresh sample: the bits of `mask` equal `expected` and are known.
  task check_agg_masked(string check_id, bit [63:0] mask, bit [63:0] expected, string label,
                        output bit passed);
    logic [63:0] vec;
    sample_agg(vec);
    passed = m_check.expect_true(
        check_id,
        (vec & mask) === (expected & mask),
        $sformatf(
            "%s mask=0x%011h expected=0x%011h masked=0x%011h vec=0x%011h",
            label,
            mask,
            expected & mask,
            vec & mask,
            vec)
    );
  endtask

  // ------------------------------------------------------------------
  // CSR helpers.
  // ------------------------------------------------------------------

  // Read a CSR and record whether the bits of `mask` equal `expected`.
  task check_csr_bits(string check_id, bit [63:0] addr, bit [31:0] mask, bit [31:0] expected,
                      string label, output bit passed);
    bit [31:0] data;
    csr_read(addr, data, label);
    passed = m_check.expect_equal(
        check_id,
        64'(data & mask),
        64'(expected),
        $sformatf(
            "%s addr=0x%08h data=0x%08h mask=0x%08h", label, addr, data, mask)
    );
  endtask

  // Both bus-error STATUS words, each against its expected value.
  task check_bus_err_status(string check_id, bit [31:0] dma_expected, bit [31:0] periph_expected,
                            string label);
    bit ok;
    check_csr_bits(check_id, 64'(SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_ADDR), '1, dma_expected, {
                   label, ".DMA_BUS_ERR_STATUS"}, ok);
    check_csr_bits(check_id, 64'(SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_REG_ADDR), '1, periph_expected,
                   {label, ".PERIPH_BUS_ERR_STATUS"}, ok);
  endtask

  // ------------------------------------------------------------------
  // Scenario.
  // ------------------------------------------------------------------

  task body();
    irq_src_t     srcs[$];
    periph_hole_t holes[$];
    bit [63:0]    covered_mask = '0;
    int unsigned  walked = 0;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkBase, ChkSet, ChkIso, ChkClr, ChkAgg,
                    ChkBusErrBase, ChkBusErrDma, ChkBusErrDmaWr, ChkBusErrDmaWrClr, ChkBusErrPeriph,
                    ChkBusErrClr});
    irq_sources(srcs);
    periph_holes(holes);
    foreach (srcs[i]) covered_mask |= 64'(1) << srcs[i].agg_idx;
    `uvm_info(get_type_name(),
              $sformatf(
                  {"SEP SV-UVM IRQ aggregator: %0d INTR_TEST sources (covered mask 0x%011h), ",
                   "DMA hole 0x%08h, %0d peripheral holes; scenario_seed=%0d"}, srcs.size(),
                    covered_mask, dma_hole(), holes.size(), scenario_seed), UVM_LOW)

    wait_fuse_sense_done();

    log_step("1", "INTR_TEST walk of every covered source into the aggregate");
    foreach (srcs[i]) begin
      bit src_ok;
      walk_source(srcs[i], covered_mask, src_ok);
      if (src_ok) walked++;
    end
    check_evidence(ChkAgg, "sources_walked", 64'(walked), 64'(srcs.size()),
                   "covered sources with BASE, SET, ISO and CLR all PASS");

    log_step("2", "adapter SLVERR into DMA_BUS_ERR_STATUS / PERIPH_BUS_ERR_STATUS");
    check_bus_err_paths(holes);

    finalize_evidence();
  endtask

  // The 3-phase walk of one source; all_ok is 1 when all its checks pass.
  task walk_source(irq_src_t src, bit [63:0] covered_mask, output bit all_ok);
    bit ok;
    bit [63:0] own_bit = 64'(1) << src.agg_idx;
    all_ok = 1'b1;

    // CHK-BASE: a known-clear start; a stuck-high aggregate bit fails here.
    csr_write(src.test_addr, '0, {src.name, ".INTR_TEST=0"});
    csr_write(src.state_addr, src.state_mask, {src.name, ".INTR_STATE.w1c"});
    check_agg_bit(ChkBase, src.agg_idx, 1'b0, {src.name, ".baseline"}, ok);
    all_ok &= ok;

    // CHK-SET: INTR_TEST -> INTR_STATE -> intr_o -> the mapped aggregate bit.
    csr_write(src.enable_addr, src.enable_mask, {src.name, ".INTR_ENABLE"});
    csr_write(src.test_addr, src.test_mask, {src.name, ".INTR_TEST"});
    check_agg_bit(ChkSet, src.agg_idx, 1'b1, {src.name, ".inject"}, ok);
    all_ok &= ok;
    check_csr_bits(ChkSet, src.state_addr, src.state_mask, src.state_mask, {
                   src.name, ".INTR_STATE.set"}, ok);
    all_ok &= ok;

    // CHK-ISO: with the source still asserted, one sample of the covered
    // bits is one-hot on this source.
    check_agg_masked(ChkIso, covered_mask, own_bit, {src.name, ".iso"}, ok);
    all_ok &= ok;

    // CHK-CLR: Event sources W1C INTR_STATE; Status sources drop INTR_TEST.
    csr_write(src.test_addr, '0, {src.name, ".INTR_TEST=0"});
    if (!src.is_status) begin
      // The INTR_TEST release alone must not clear an Event source, so the
      // W1C is what the clear checks below credit.
      logic [63:0] vec;
      int unsigned held;
      for (held = 0; held < StickyHoldCycles; held++) begin
        sample_agg(vec);
        if (vec[src.agg_idx] !== 1'b1) break;
      end
      ok = m_check.expect_true(
          ChkClr,
          held == StickyHoldCycles,
          $sformatf(
              "%s.sticky INTR_TEST=0 without W1C agg[%0d] held=%0d of %0d last=%b",
              src.name,
              src.agg_idx,
              held,
              StickyHoldCycles,
              vec[src.agg_idx])
      );
      all_ok &= ok;
      check_csr_bits(ChkClr, src.state_addr, src.state_mask, src.state_mask, {
                     src.name, ".INTR_STATE.sticky"}, ok);
      all_ok &= ok;
      csr_write(src.state_addr, src.state_mask, {src.name, ".INTR_STATE.w1c"});
    end
    check_agg_bit(ChkClr, src.agg_idx, 1'b0, {src.name, src.is_status ? ".release" : ".w1c"}, ok);
    all_ok &= ok;
    check_csr_bits(ChkClr, src.state_addr, src.state_mask, '0, {src.name, ".INTR_STATE.clr"}, ok);
    all_ok &= ok;

    csr_write(src.enable_addr, '0, {src.name, ".INTR_ENABLE=0"});
    `uvm_info(get_type_name(), $sformatf("%s: INTR_TEST -> sep_internal_interrupts[%0d] 0->1->0 %s",
                                         src.name, src.agg_idx, all_ok ? "PASS" : "FAIL"), UVM_LOW)
  endtask

  // The adapter bus-error legs. Each fault is raised and cleared on its own.
  task check_bus_err_paths(periph_hole_t holes[$]);
    bit        ok;
    bit [31:0] data;
    bit [31:0] wdata;
    bit [63:0] hole = dma_hole();
    bit [63:0] excl_dma = (64'(1) << AggDmaHostPath) | (64'(1) << AggPeriphOr);

    // CHK-BUSERR-BASE: no fault latched; a stuck-high latch fails here.
    check_bus_err_status(ChkBusErrBase, '0, '0, "baseline");
    check_agg_masked(ChkBusErrBase, (64'(1) << AggDmaRegPath) | (64'(1) << AggPeriphOr), '0,
                     "baseline.agg[40,42]", ok);

    // CHK-BUSERR-DMA: the read leg of the DMA register-path fault. Bits 41
    // and 42 are the exclusivity check. The PERIPH leg below is the control
    // of bit 42. Bit 41 has no control in this pass (no DMA transfer is
    // started), so its check proves only that the bit is driven and 0.
    csr_read_expect(ChkBusErrDma, hole, OCAH_AXI_RESP_SLVERR, data, "dma_hole.read");
    check_bus_err_status(ChkBusErrDma, 32'(SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_PATH_ERR_MASK), '0,
                         "dma_hole.read");
    check_agg_bit(ChkBusErrDma, AggDmaRegPath, 1'b1, "dma_hole.read", ok);
    check_agg_masked(ChkBusErrDma, excl_dma, '0, "dma_hole.read.agg[41,42]", ok);

    // CHK-BUSERR-CLR: DMA_BUS_ERR_CLEAR is write-only single-pulse, so the
    // clear is graded on STATUS and the aggregate bit, not on its read.
    csr_write(64'(SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_REG_ADDR),
              32'(SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_CLR_MASK), "DMA_BUS_ERR_CLEAR.clr");
    check_bus_err_status(ChkBusErrClr, '0, '0, "dma_hole.read.clear");
    check_agg_bit(ChkBusErrClr, AggDmaRegPath, 1'b0, "dma_hole.read.clear", ok);

    // CHK-BUSERR-DMA-WR: the write leg (BRESP) to the same hole, with a
    // seeded random word.
    wdata = 32'(random_pattern(32));
    csr_write_expect(ChkBusErrDmaWr, hole, wdata, OCAH_AXI_RESP_SLVERR, "dma_hole.write");
    check_bus_err_status(ChkBusErrDmaWr, 32'(SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_PATH_ERR_MASK), '0,
                         "dma_hole.write");
    check_agg_bit(ChkBusErrDmaWr, AggDmaRegPath, 1'b1, "dma_hole.write", ok);
    check_agg_masked(ChkBusErrDmaWr, excl_dma, '0, "dma_hole.write.agg[41,42]", ok);

    // CHK-BUSERR-DMA-WR-CLR.
    csr_write(64'(SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_REG_ADDR),
              32'(SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_CLR_MASK), "DMA_BUS_ERR_CLEAR.clr");
    check_bus_err_status(ChkBusErrDmaWrClr, '0, '0, "dma_hole.write.clear");
    check_agg_bit(ChkBusErrDmaWrClr, AggDmaRegPath, 1'b0, "dma_hole.write.clear", ok);

    // CHK-BUSERR-PERIPH and CHK-BUSERR-CLR per peripheral hole. Bit 40 is
    // the exclusivity check; the DMA legs above are its control.
    foreach (holes[i]) begin
      csr_read_expect(ChkBusErrPeriph, holes[i].addr, OCAH_AXI_RESP_SLVERR, data, {
                      holes[i].name, "_hole.read"});
      check_bus_err_status(ChkBusErrPeriph, '0, holes[i].status_mask, {holes[i].name, "_hole.read"
                           });
      check_agg_bit(ChkBusErrPeriph, AggPeriphOr, 1'b1, {holes[i].name, "_hole.read"}, ok);
      check_agg_masked(ChkBusErrPeriph, 64'(1) << AggDmaRegPath, '0, {
                       holes[i].name, "_hole.read.agg[40]"}, ok);

      csr_write(64'(SEP_CPU_CTRL_PERIPH_BUS_ERR_CLEAR_REG_ADDR), holes[i].clear_mask, {
                "PERIPH_BUS_ERR_CLEAR.", holes[i].name});
      check_bus_err_status(ChkBusErrClr, '0, '0, {holes[i].name, "_hole.read.clear"});
      check_agg_bit(ChkBusErrClr, AggPeriphOr, 1'b0, {holes[i].name, "_hole.read.clear"}, ok);
    end
  endtask

endclass : sep_irq_ip_to_aggregator_test_seq
