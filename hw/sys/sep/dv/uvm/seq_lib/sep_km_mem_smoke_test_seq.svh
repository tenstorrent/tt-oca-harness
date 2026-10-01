// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP Key Manager memory smoke scenario sequence, carrying the cocotb
// sep_km_mem_smoke_test semantics. The KM ROM image
// (cocotb/tests/km_fw/km_rom.S, loaded by +km_rom_hex) fetches from the KM
// ROM, writes four plaintexts to four KM SRAM words through the enabled
// scrambler, reads them back with four consecutive loads, clears the
// scrambler enable, stores the loaded values to SRAM words 1..4, and stores
// the marker to word 0 last. Each pass:
//   * pass 1 and later walk the primary reset first (tb_vif.rst_n), so the
//     KM restarts from reset and the tb_top KM monitors restart from 0;
//   * wait for fuse sense done; with the KM held in reset (SW_RESET_N reset
//     value), the KM ROM request count is 0 (control for CHK-KM-MEM);
//   * release the KM: SW_RESET_N = reset value | KM_SW_RST_N (CHK-CSR-RESP);
//   * poll, bounded, for the marker in SRAM word 0 together with the
//     image's nine SRAM stores (four scrambled stores, four result stores,
//     the marker; km_rom.S). Pass 1 and later start with the SRAM holding
//     the words of the pass before, so the marker alone does not show that
//     this pass finished;
//   * CHK-KM-MEM: KM ROM requests, KM SRAM requests and KM SRAM writes are
//     each non-zero, and word 0 holds the marker;
//   * CHK-KM-SRAM-SCR-RT: at least four KM SRAM reads are accepted with the
//     scrambler enabled, and SRAM words 1..4 hold the four plaintexts;
//   * CHK-KM-SRAM-SCR-STORED: exactly four writes are accepted with the
//     scrambler enabled; their physical rows are distinct and not all their
//     logical words; no written word is a plaintext; the macro array word at
//     each row equals the written word (the control: the store landed); no
//     probed SRAM word other than words 1..4 holds a plaintext;
//   * KM-SRAM-RD-LAT: the read-latency monitor counts, logged and not graded.
// Expected values are the stimulus the image writes: the plaintexts, cell
// offsets and marker are the literals of km_rom.S, mirrored in
// cocotb/seq_lib/sep_km_mem_smoke_seq.py. No ciphertext or physical row is
// predicted. Observables are the sep_tb_if mirrors of the tb_top KM probes
// (observation-only). RAND-NONE: the scenario draws no random stimulus.

class sep_km_mem_smoke_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_km_mem_smoke_test_seq)

  localparam string ChkKmMem = "CHK-KM-MEM";
  localparam string ChkKmSramScrRt = "CHK-KM-SRAM-SCR-RT";
  localparam string ChkKmSramScrStored = "CHK-KM-SRAM-SCR-STORED";

  // km_rom.S literals (KM_SMOKE_* in cocotb/seq_lib/sep_km_mem_smoke_seq.py).
  localparam bit [31:0] KmSmokeSramWord0 = 32'h0000_005A;
  localparam int unsigned NumScr = 4;
  localparam bit [31:0] KmSmokeScrPlaintext[NumScr] = '{
      32'h1E2D_3C4B,
      32'hA596_8778,
      32'h0F1E_2D3C,
      32'hC3B4_A596
  };
  // Byte offsets from the KM SRAM base of the scrambled cells (km_rom.S
  // CELL0..CELL3); the logical word index of an offset is offset / 4.
  localparam int unsigned KmSmokeScrCellOffsets[NumScr] = '{'h0100, 'h0104, 'h3FF8, 'h7FFC};
  // SRAM words the image stores the loaded values to.
  localparam int unsigned KmSmokeScrResultWords[NumScr] = '{1, 2, 3, 4};
  // SRAM stores of the image: four scrambled stores, four result stores and
  // the marker (km_rom.S).
  localparam int unsigned KmSmokeImageSramStores = 9;

  // Polling bound after the KM release, and the settle after the marker
  // (cocotb _MAX_KM_CYCLES and ClockCycles(4)).
  localparam int unsigned MaxKmCycles = 20_000;
  localparam int unsigned DoneSettleCycles = 4;
  // System clocks the KM stays in reset before the held-KM ROM count is read.
  localparam int unsigned HeldCycles = 16;

  function new(string name = "sep_km_mem_smoke_test_seq");
    super.new(name);
  endfunction

  function bit is_plaintext(logic [31:0] word);
    foreach (KmSmokeScrPlaintext[i]) if (word === KmSmokeScrPlaintext[i]) return 1'b1;
    return 1'b0;
  endfunction

  // A probe count that is known (no X or Z bit) and at least min_count.
  function bit known_at_least(logic [31:0] count, int unsigned min_count);
    return !$isunknown(count) && count >= min_count;
  endfunction

  function logic [31:0] probe_word(int unsigned index);
    return tb_vif.km_sram_probe[32*index+:32];
  endfunction

  function bit is_result_word(int unsigned index);
    foreach (KmSmokeScrResultWords[i]) if (index == KmSmokeScrResultWords[i]) return 1'b1;
    return 1'b0;
  endfunction

  // Primary reset for pass 1 and later (same hold and post-release windows
  // as the base-test bring-up ladder).
  task primary_reset();
    `uvm_info(get_type_name(), "asserting rst_n for this pass (CPU held off)", UVM_LOW)
    tb_vif.rst_n <= 1'b0;
    wait_sys_cycles(test_cfg.reset_hold_cycles);
    tb_vif.rst_n <= 1'b1;
    wait_sys_cycles(test_cfg.post_reset_cycles);
  endtask

  task body();
    int unsigned polled;
    bit          done;
    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkKmMem, ChkKmSramScrRt, ChkKmSramScrStored});
    `uvm_info(get_type_name(), $sformatf("SEP SV-UVM KM memory smoke: pass %0d scenario_seed=%0d",
                                         loop_index, scenario_seed), UVM_LOW)

    if (loop_index > 0) primary_reset();
    wait_fuse_sense_done();

    log_step("1", "KM held in reset fetches nothing");
    wait_sys_cycles(HeldCycles);
    void'(m_check.expect_true(
        ChkKmMem,
        tb_vif.km_rom_req_count === 32'd0,
        $sformatf(
            "KM in software reset (SW_RESET_N reset value): KM ROM requests=%0d, want 0",
            tb_vif.km_rom_req_count)
    ));

    log_step("2", "release the KM from software reset");
    csr_write(
        SEP_RESET_CTRL_SW_RESET_N_REG_ADDR,
        32'(SEP_RESET_CTRL_SW_RESET_N_REG_DEFAULT | SEP_RESET_CTRL_SW_RESET_N_KM_SW_RST_N_MASK),
        "SW_RESET_N.release_km");

    log_step("3", "poll SRAM word 0 for the marker");
    done = 1'b0;
    for (polled = 1; polled <= MaxKmCycles; polled++) begin
      wait_sys_cycles(1);
      if (tb_vif.km_sram_word0 === KmSmokeSramWord0 &&
          tb_vif.km_sram_write_count >= KmSmokeImageSramStores) begin
        done = 1'b1;
        break;
      end
    end
    void'(m_check.expect_true(
        ChkKmMem,
        done,
        $sformatf(
            "marker 0x%08h and %0d SRAM writes within %0d cycles: word0=0x%08h writes=%0d polled=%0d",
            KmSmokeSramWord0,
            KmSmokeImageSramStores,
            MaxKmCycles,
            tb_vif.km_sram_word0,
            tb_vif.km_sram_write_count,
            polled)
    ));
    wait_sys_cycles(DoneSettleCycles);

    log_step("4", "KM memory checks");
    chk_km_mem();
    chk_scrambled_readback();
    chk_scrambled_store();
    log_read_latency();
    finalize_evidence();
  endtask

  task chk_km_mem();
    logic [31:0] rom_count = tb_vif.km_rom_req_count;
    logic [31:0] sram_count = tb_vif.km_sram_req_count;
    logic [31:0] sram_writes = tb_vif.km_sram_write_count;
    logic [31:0] word0 = tb_vif.km_sram_word0;
    void'(m_check.expect_true(
        ChkKmMem,
        known_at_least(
            rom_count, 1
        ),
        $sformatf(
            "KM ROM requests rom=%0d, want > 0", rom_count)
    ));
    void'(m_check.expect_true(
        ChkKmMem,
        known_at_least(
            sram_count, 1
        ),
        $sformatf(
            "KM SRAM requests sram=%0d, want > 0", sram_count)
    ));
    void'(m_check.expect_true(
        ChkKmMem,
        known_at_least(
            sram_writes, 1
        ),
        $sformatf(
            "KM SRAM writes writes=%0d, want > 0", sram_writes)
    ));
    void'(m_check.expect_true(
        ChkKmMem,
        word0 === KmSmokeSramWord0,
        $sformatf(
            "KM SRAM word0=0x%08h, want the marker 0x%08h (the image's last store)",
            word0,
            KmSmokeSramWord0)
    ));
  endtask

  task chk_scrambled_readback();
    logic [31:0] scr_reads = tb_vif.km_sram_scr_rd_count;
    void'(m_check.expect_true(
        ChkKmSramScrRt,
        known_at_least(
            scr_reads, NumScr
        ),
        $sformatf(
            "%0d KM SRAM reads accepted with the scrambler enabled, want >= %0d", scr_reads, NumScr)
    ));
    foreach (KmSmokeScrResultWords[i]) begin
      logic [31:0] got = probe_word(KmSmokeScrResultWords[i]);
      void'(m_check.expect_true(
          ChkKmSramScrRt,
          got === KmSmokeScrPlaintext[i],
          $sformatf(
              "scrambled load %0d of cell offset 0x%0h returned 0x%08h (SRAM word %0d), want the plaintext 0x%08h",
              i,
              KmSmokeScrCellOffsets[i],
              got,
              KmSmokeScrResultWords[i],
              KmSmokeScrPlaintext[i])
      ));
    end
  endtask

  task chk_scrambled_store();
    logic [31:0] wr_count = tb_vif.km_sram_scr_wr_count;
    // Physical word-address width of one kept row (tb_top KmSramAw).
    int unsigned aw = $bits(tb_vif.km_sram_scr_wr_addr) / NumScr;
    logic [31:0] rows[NumScr];
    logic [31:0] data[NumScr];
    logic [31:0] held[NumScr];
    bit all_logical = 1'b1;
    bit distinct = 1'b1;
    int unsigned probe_words = $bits(tb_vif.km_sram_probe) / 32;
    int unsigned stray = 0;
    string stray_s = "";

    void'(m_check.expect_true(
        ChkKmSramScrStored,
        wr_count === 32'(NumScr),
        $sformatf(
            "%0d SRAM writes accepted with the scrambler enabled, want the image's %0d plaintext stores",
            wr_count,
            NumScr)
    ));
    foreach (rows[i]) begin
      rows[i] = 32'((tb_vif.km_sram_scr_wr_addr >> (aw * i)) & ((1 << aw) - 1));
      data[i] = tb_vif.km_sram_scr_wr_data[32*i+:32];
      held[i] = tb_vif.km_sram_scr_wr_cell[32*i+:32];
      if (rows[i] !== 32'(KmSmokeScrCellOffsets[i] / 4)) all_logical = 1'b0;
      for (int j = 0; j < i; j++) if (rows[i] === rows[j]) distinct = 1'b0;
      if ($isunknown(rows[i])) distinct = 1'b0;
    end
    void'(m_check.expect_true(
        ChkKmSramScrStored,
        !all_logical,
        $sformatf(
            "physical rows 0x%0h 0x%0h 0x%0h 0x%0h are not all the logical words 0x%0h 0x%0h 0x%0h 0x%0h",
            rows[0],
            rows[1],
            rows[2],
            rows[3],
            KmSmokeScrCellOffsets[0] / 4,
            KmSmokeScrCellOffsets[1] / 4,
            KmSmokeScrCellOffsets[2] / 4,
            KmSmokeScrCellOffsets[3] / 4)
    ));
    void'(m_check.expect_true(
        ChkKmSramScrStored,
        distinct,
        $sformatf(
            "the %0d stores reach %0d distinct physical rows", NumScr, NumScr)
    ));
    foreach (data[i]) begin
      bit cipher_ok = !$isunknown(data[i]) && !is_plaintext(data[i]);
      bit landed = !$isunknown(held[i]) && held[i] === data[i];
      void'(m_check.expect_true(
          ChkKmSramScrStored,
          cipher_ok,
          $sformatf(
              "store %0d (plaintext 0x%08h) wrote 0x%08h to row 0x%0h, not a plaintext",
              i,
              KmSmokeScrPlaintext[i],
              data[i],
              rows[i])
      ));
      void'(m_check.expect_true(
          ChkKmSramScrStored,
          landed,
          $sformatf(
              "row 0x%0h holds 0x%08h, want the written 0x%08h", rows[i], held[i], data[i])
      ));
    end
    for (int unsigned w = 0; w < probe_words; w++) begin
      if (!is_result_word(w) && is_plaintext(probe_word(w))) begin
        stray++;
        stray_s = {stray_s, $sformatf(" word%0d=0x%08h", w, probe_word(w))};
      end
    end
    check_evidence(ChkKmSramScrStored, "plaintext_words", 64'(stray), 64'(0), $sformatf(
                   "SRAM words 0..%0d outside the result words 1..4 holding a plaintext:%s",
                   probe_words - 1,
                   stray ? stray_s : " none"
                   ));
  endtask

  function void log_read_latency();
    `uvm_info(get_type_name(), $sformatf(
              {
                "KM-SRAM-RD-LAT (measured precondition, not graded): %0d KM SRAM reads accepted, ",
                "%0d returned rvalid one cycle after the accept, %0d cycles where rvalid and the ",
                "one-cycle-earlier accept disagree; rvalid cycles that also accepted a read of a ",
                "different address: %0d"
              },
              tb_vif.km_sram_rd_accept_count,
              tb_vif.km_sram_rd_lat1_count,
              tb_vif.km_sram_rd_lat_err_count,
              tb_vif.km_sram_rd_b2b_diff_count
              ), UVM_LOW)
    `uvm_info(get_type_name(), $sformatf(
              "KM memory counters: rom=%0d sram=%0d writes=%0d word0=0x%08h scr_rd=%0d scr_wr=%0d",
              tb_vif.km_rom_req_count,
              tb_vif.km_sram_req_count,
              tb_vif.km_sram_write_count,
              tb_vif.km_sram_word0,
              tb_vif.km_sram_scr_rd_count,
              tb_vif.km_sram_scr_wr_count
              ), UVM_LOW)
  endfunction

endclass : sep_km_mem_smoke_test_seq
