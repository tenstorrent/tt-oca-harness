// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP no-CPU partial-write scenario sequence, carrying the cocotb
// sep_periph_bus_err_misaligned_test semantics on the CPU-LSU AXI4 splice.
// sep_cpu_ctrl.rdl and doc/interrupts.adoc require a write that the block's
// register definition refuses to receive SLVERR and latch the owning block's
// bit: PERIPH_BUS_ERR_STATUS.hmac for an HMAC register, and
// DMA_BUS_ERR_STATUS.reg_path_err for a Secure DMA register. A partial write
// is one whose byte strobe misses a byte that the register owns. A narrow
// read inside a register is a legal access: OKAY, and no status bit.
//   * wait for fuse sense done, then require both status registers to read
//     0 (CHK-MISALIGN-BASE);
//   * per block, an aligned control read (AxSIZE=2, one beat) at the
//     register offset: one R beat answered OKAY and both status registers
//     unchanged (CHK-MISALIGN-CTRL, CHK-MISALIGN-DMA-CTRL);
//   * a narrow read at offset + 2 (AxSIZE=2, AxLEN=0): one R beat answered
//     OKAY and both status registers unchanged (CHK-MISALIGN-RD,
//     CHK-MISALIGN-DMA-RD);
//   * then the probe, a write of byte lanes 2 and 3 at offset + 2. Both
//     registers own byte 0, so the strobe misses an owned byte. The write
//     is answered SLVERR, both status registers read exactly the expected
//     value (the owning bit latched, the other register unchanged), and the
//     register reads back its control value (CHK-MISALIGN-LATCH,
//     CHK-MISALIGN-DMA-LATCH). The HMAC bit stays latched through the DMA
//     probe, so the DMA expectations carry it;
//   * clear both bits through PERIPH_BUS_ERR_CLEAR.hmac and
//     DMA_BUS_ERR_CLEAR.clr and require both status registers to read 0
//     (CHK-MISALIGN-CLEAR), so the next pass starts from the reset state.
// The R beats come from the master driver's live RRESP/RLAST sampling
// (result.resp_list, one entry per beat). The status registers are read
// with OKAY through csr_read (CHK-CSR-RESP) and graded here; they are not
// in the cpu_ctrl_csr predicted set. Expected values are the RDL field
// masks and reset values (sep_reg.svh) and SLVERR from the RDL field
// descriptions. The cocotb twin is
// cocotb/tests/system/sep_periph_bus_err_misaligned_test.py.

class sep_periph_bus_err_misaligned_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_periph_bus_err_misaligned_test_seq)

  localparam string ChkBase = "CHK-MISALIGN-BASE";
  localparam string ChkClear = "CHK-MISALIGN-CLEAR";

  // Probe size: AxSIZE=2 (four-byte beat). At a word offset + 2 the beat
  // ends on the word boundary; AxLEN=0 keeps it one beat, so no
  // burst-refusing path (doc/crypto.adoc "Single-Beat Access Only")
  // answers before the block.
  localparam int ProbeSize = 2;
  localparam bit [63:0] MisalignOffset = 64'd2;
  // Byte lanes 2 and 3 of the 32-bit register, before the bus-lane shift.
  localparam bit [7:0] PartialStrb = 8'h0C;
  localparam bit [31:0] PartialData = 32'hFFFF_0000;

  localparam bit [31:0] PeriphHmacBit = 32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_HMAC_MASK);
  localparam bit [31:0] DmaRegPathBit = 32'(SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_PATH_ERR_MASK);

  function new(string name = "sep_periph_bus_err_misaligned_test_seq");
    super.new(name);
  endfunction

  task read_status(output bit [31:0] periph, output bit [31:0] dma, input string tag);
    csr_read(SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_REG_ADDR, periph, {"PERIPH_BUS_ERR_STATUS.", tag});
    csr_read(SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_ADDR, dma, {"DMA_BUS_ERR_STATUS.", tag});
  endtask

  // Grade both status registers whole under one check, so a bit latched in
  // the other register fails too.
  task check_status(string check_id, string tag, bit [31:0] exp_periph, bit [31:0] exp_dma);
    bit [31:0] periph, dma;
    read_status(periph, dma, tag);
    check_evidence(check_id, "PERIPH_BUS_ERR_STATUS", 64'(periph), 64'(exp_periph), tag);
    check_evidence(check_id, "DMA_BUS_ERR_STATUS", 64'(dma), 64'(exp_dma), tag);
  endtask

  // Grade the R beats of one read: exactly one beat, answered `expected`.
  function void check_beats(string check_id, string tag, ocah_axi_item result,
                            ocah_axi_resp_e expected);
    ocah_axi_resp_e first = (result.resp_list.size() > 0) ? result.resp_list[0] :
        OCAH_AXI_RESP_OKAY;
    check_evidence(check_id, "r_beats", 64'(result.resp_list.size()), 64'd1, tag);
    check_evidence(check_id, "rresp", 64'(first), 64'(expected), $sformatf(
                   "%s addr=0x%0h resp=%s", tag, result.address, first.name()));
  endfunction

  // One block: the aligned control, the narrow read, then the partial write.
  // `before` is the (PERIPH, DMA) status the reads must leave unchanged;
  // `after` is the exact (PERIPH, DMA) status the partial write must leave.
  task probe_block(string tag, string block, bit [63:0] aligned, bit [31:0] before_periph,
                   bit [31:0] before_dma, bit [31:0] after_periph, bit [31:0] after_dma);
    ocah_axi_item result;
    bit [31:0] ctrl_value, readback;
    bit [63:0]    addr = aligned + MisalignOffset;
    string        chk_ctrl = {"CHK-MISALIGN", tag, "-CTRL"};
    string        chk_rd = {"CHK-MISALIGN", tag, "-RD"};
    string        chk_latch = {"CHK-MISALIGN", tag, "-LATCH"};

    bus_read(aligned, ProbeSize, result, {block, ".aligned"});
    check_beats(chk_ctrl, {block, ".aligned"}, result, OCAH_AXI_RESP_OKAY);
    check_status(chk_ctrl, {block, ".aligned"}, before_periph, before_dma);
    ctrl_value = sep_csr_from_bus(aligned, result.first_data());

    bus_read(addr, ProbeSize, result, {block, ".narrow"});
    check_beats(chk_rd, {block, ".narrow"}, result, OCAH_AXI_RESP_OKAY);
    check_status(chk_rd, {block, ".narrow"}, before_periph, before_dma);

    bus_write(addr, sep_csr_to_bus(aligned, PartialData), 8'(PartialStrb << sep_csr_lane(aligned)),
              ProbeSize, result, {block, ".partial"});
    // The status bit alone would pass on a DUT that latched the bit while
    // answering another code, so the response is graded with the latch.
    check_evidence(chk_latch, "probe_resp", 64'(result.worst_resp()), 64'(OCAH_AXI_RESP_SLVERR),
                   $sformatf("%s.partial addr=0x%0h", block, addr));
    check_status(chk_latch, {block, ".partial"}, after_periph, after_dma);
    csr_read(aligned, readback, {block, ".readback"});
    check_evidence(chk_latch, "register", 64'(readback), 64'(ctrl_value), {block, ".readback"});
  endtask

  task body();
    seed_scenario_rng();
    attach_evidence('{ChkCsrResp, ChkBase, "CHK-MISALIGN-CTRL", "CHK-MISALIGN-RD",
                    "CHK-MISALIGN-LATCH", "CHK-MISALIGN-DMA-CTRL", "CHK-MISALIGN-DMA-RD",
                    "CHK-MISALIGN-DMA-LATCH", ChkClear});
    `uvm_info(get_type_name(),
              $sformatf({"SEP SV-UVM partial write: HMAC CFG 0x%08h and Secure DMA INTR_STATE ",
                         "0x%08h + %0d; scenario_seed=%0d"}, HMAC_CFG_REG_ADDR,
                          SECURE_DMA_INTR_STATE_REG_ADDR, MisalignOffset, scenario_seed), UVM_LOW)

    wait_fuse_sense_done();

    log_step("1", "baseline status");
    check_status(ChkBase, "baseline", 32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_STATUS_REG_DEFAULT),
                 32'(SEP_CPU_CTRL_DMA_BUS_ERR_STATUS_REG_DEFAULT));

    log_step("2", "HMAC control, narrow read and partial write");
    probe_block("", "hmac", 64'(HMAC_CFG_REG_ADDR), '0, '0, PeriphHmacBit, '0);

    log_step("3", "Secure DMA control, narrow read and partial write");
    probe_block("-DMA", "dma", 64'(SECURE_DMA_INTR_STATE_REG_ADDR), PeriphHmacBit, '0,
                PeriphHmacBit, DmaRegPathBit);

    log_step("4", "clear both status bits");
    csr_write(SEP_CPU_CTRL_PERIPH_BUS_ERR_CLEAR_REG_ADDR,
              32'(SEP_CPU_CTRL_PERIPH_BUS_ERR_CLEAR_HMAC_MASK), "PERIPH_BUS_ERR_CLEAR.hmac");
    csr_write(SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_REG_ADDR, 32'(SEP_CPU_CTRL_DMA_BUS_ERR_CLEAR_CLR_MASK),
              "DMA_BUS_ERR_CLEAR.clr");
    check_status(ChkClear, "cleared", '0, '0);

    finalize_evidence();
  endtask

endclass : sep_periph_bus_err_misaligned_test_seq
