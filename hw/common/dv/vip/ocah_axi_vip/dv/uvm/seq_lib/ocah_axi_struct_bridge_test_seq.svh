// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_axi_struct_bridge_test (the SV-UVM twin of the
// cocotb selftest): the shared master on the struct side of
// ocah_axi_struct_bridge against the shared slave agent on the interface side,
// with the passive env scoring every transaction. A backdoor preload reads
// back over the bus; random single beats of every transfer size with
// independent AWID/ARID read back under matching BID/RID and agree with the
// backdoor; INCR/FIXED/WRAP bursts land at the IHI 0022 A3.4.1 beat
// addresses; partial write strobes change only their lanes; one-shot read and
// write faults answer each programmed response code and retire, a write fault
// leaving the memory untouched; a deferred BREADY and a held RREADY keep the
// responses stable; bounded READY stalls on the agent, on every request
// channel and then on the write address channel alone, complete every
// transfer. Faults are programmed through the slave sequence and armed on the
// passive cfg so the wire-level scoreboard classifies them as expected; the
// backdoor preload is mirrored into the passive reference model so its
// readback prediction starts from the preloaded contents.

class ocah_axi_struct_bridge_test_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(ocah_axi_struct_bridge_test_seq)

  // Bound by the test before start(); `shadow` is the passive env's reference
  // model and stays null when the passive stack is off.
  ocah_axi_checker        evidence;
  ocah_axi_config         axi_cfg;
  ocah_axi_slave_sequence slave_seq;
  ocah_axi_ref_model      shadow;

  int unsigned n_ops = 16;
  int unsigned stall_cycles = 3;

  // Preload words, the scratch window of the random and burst phases, and the
  // dedicated words of the fault and backpressure phases.
  localparam bit [63:0] PreloadAddr[3] = '{64'h1000, 64'h1004, 64'h10FC};
  localparam bit [63:0] PreloadWord[3] = '{64'hC0DE_F00D, 64'h1234_5678, 64'hA500_0000};
  localparam bit [63:0] ScratchBase = 64'h2000;
  localparam bit [63:0] ScratchBytes = 64'h6000;
  localparam bit [63:0] FaultWord = ScratchBase + ScratchBytes + 64'h100;
  localparam bit [63:0] StallBase = ScratchBase + ScratchBytes + 64'h300;
  localparam bit [63:0] StrobeWord = ScratchBase + ScratchBytes + 64'h400;
  localparam bit [63:0] HoldWord = ScratchBase + ScratchBytes + 64'h500;
  localparam bit [63:0] DataMask = 64'hFFFF_FFFF;
  // INCR burst lengths: the shortest bursts, one half-page, and one that
  // exceeds four beats.
  localparam int unsigned BurstBeats[4] = '{2, 3, 4, 16};
  // Strobe patterns of the partial-write phase: single lanes, contiguous
  // pairs, and one sparse pair.
  localparam bit [7:0] StrobePatterns[5] = '{8'h1, 8'h8, 8'h3, 8'hC, 8'h9};

  function new(string name = "ocah_axi_struct_bridge_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [7:0] full_strb;
    if (evidence == null || axi_cfg == null || slave_seq == null)
      `uvm_fatal(get_type_name(), "evidence/axi_cfg/slave_seq handles not bound")
    full_strb = 8'((64'd1 << axi_cfg.beat_bytes()) - 1);
    check_preload();
    random_single_beats(full_strb);
    bursts();
    partial_strobes(full_strb);
    faults(full_strb);
    response_holds(full_strb);
    backpressure(full_strb);
    `uvm_info(get_type_name(), $sformatf("done: writes=%0d reads=%0d", write_transactions,
                                         read_transactions), UVM_LOW)
  endtask

  // Words written through the backdoor read back over the bus.
  protected task check_preload();
    ocah_axi_item rres;
    bit [7:0]     bytes[];
    foreach (PreloadAddr[i]) begin
      slave_seq.write32(PreloadAddr[i], PreloadWord[i][31:0]);
      if (shadow != null) begin
        bytes = new[4];
        for (int unsigned lane = 0; lane < 4; lane++) bytes[lane] = PreloadWord[i][8*lane+:8];
        shadow.backdoor_write(PreloadAddr[i], bytes);
      end
    end
    foreach (PreloadAddr[i]) begin
      axi_cfg.arm_expected_read(PreloadAddr[i]);
      read_result(PreloadAddr[i], rres);
      void'(evidence.expect_equal(
          "CHK-AXI-BRIDGE-PRELOAD",
          rres.first_data(),
          PreloadWord[i],
          $sformatf(
              "addr=0x%0h", PreloadAddr[i])
      ));
    end
  endtask

  // Random single beats of every transfer size with independent IDs,
  // cross-checked through the backdoor. Data rides the addressed lanes of
  // the raw bus word (the item's word semantics); the strobes name those
  // lanes and the comparisons mask to them.
  protected task random_single_beats(bit [7:0] full_strb);
    bit [15:0] awid, arid;
    bit [63:0] addr, data, lane_mask;
    bit [7:0] strb;
    int unsigned size, nbytes, lane_lo;
    ocah_axi_item wres, rres;
    string ctx;
    for (int unsigned index = 0; index < n_ops; index++) begin
      size      = $urandom_range(2);
      nbytes    = 1 << size;
      addr      = ScratchBase + (64'($urandom_range(32'(ScratchBytes - 1))) & ~64'(nbytes - 1));
      lane_lo   = int'(addr % 4);
      strb      = 8'(((1 << nbytes) - 1) << lane_lo);
      lane_mask = merge_lanes('0, '1, strb);
      data      = 64'($urandom()) & lane_mask;
      awid      = 16'($urandom_range(255));
      arid      = 16'($urandom_range(255));
      ctx = $sformatf("op=%0d addr=0x%0h size=%0d awid=0x%0h arid=0x%0h", index, addr, size, awid,
                      arid);

      axi_cfg.arm_expected_write(addr, data, strb);
      write_result(.addr(addr), .data(data), .result(wres), .id(awid), .strb(strb), .size(size));
      void'(evidence.expect_true(
          "CHK-AXI-BRIDGE-ID",
          wres.observed_id_valid && wres.id_match(),
          $sformatf(
              "%s BID observed=0x%0h", ctx, wres.observed_id)
      ));
      void'(evidence.expect_equal(
          "CHK-AXI-BRIDGE-BACKDOOR", 64'(slave_seq.read32(addr & ~64'h3)) & lane_mask, data, ctx
      ));

      axi_cfg.arm_expected_read(addr);
      read_result(.addr(addr), .result(rres), .id(arid), .size(size));
      void'(evidence.expect_equal(
          "CHK-AXI-BRIDGE-RDBACK", rres.first_data() & lane_mask, data, ctx
      ));
      void'(evidence.expect_true(
          "CHK-AXI-BRIDGE-ID",
          rres.observed_id_valid && rres.id_match(),
          $sformatf(
              "%s RID observed=0x%0h", ctx, rres.observed_id)
      ));
    end
  endtask

  // INCR bursts read back in order, FIXED repeats one address, WRAP folds at
  // its window. Bursts arm read intent only (single-beat write-intent contract).
  protected task bursts();
    bit [63:0] base, start;
    bit [15:0] burst_id;
    bit [63:0] words[$], folded[$], repeated[$];
    int unsigned beats;
    ocah_axi_item wres, rres;
    string ctx;

    foreach (BurstBeats[i]) begin
      beats = BurstBeats[i];
      base = ScratchBase + (64'($urandom_range(32'(ScratchBytes - 257))) & ~64'hFF);
      burst_id = 16'($urandom_range(255));
      words.delete();
      repeat (beats) words.push_back(64'($urandom()) & DataMask);
      ctx = $sformatf("INCR beats=%0d base=0x%0h id=0x%0h", beats, base, burst_id);
      burst_write_result(base, words, wres, burst_id);
      void'(evidence.expect_true(
          "CHK-AXI-BRIDGE-ID", wres.observed_id_valid && wres.id_match(), {ctx, " BID"}
      ));
      axi_cfg.arm_expected_read(base);
      burst_read_result(base, beats, rres, burst_id);
      void'(evidence.expect_equal_words("CHK-AXI-BRIDGE-BURST", rres.data_words, words, ctx));
      void'(evidence.expect_true(
          "CHK-AXI-BRIDGE-ID", rres.observed_id_valid && rres.id_match(), {ctx, " RID on RLAST"}
      ));
    end

    base = ScratchBase + (64'($urandom_range(32'(ScratchBytes - 257))) & ~64'hFF);
    words.delete();
    repeat (4) words.push_back(64'($urandom()) & DataMask);
    ctx = $sformatf("FIXED beats=4 base=0x%0h", base);
    burst_write_result(.addr(base), .data_words(words), .result(wres),
                       .burst(OCAH_AXI_BURST_FIXED));
    axi_cfg.arm_expected_read(base);
    read_result(base, rres);
    void'(evidence.expect_equal(
        "CHK-AXI-BRIDGE-BURST", rres.first_data(), words[3], {ctx, " last beat wins"}
    ));
    repeated.delete();
    repeat (4) repeated.push_back(words[3]);
    axi_cfg.arm_expected_read(base);
    burst_read_result(.addr(base), .beats(4), .result(rres), .burst(OCAH_AXI_BURST_FIXED));
    void'(evidence.expect_equal_words(
        "CHK-AXI-BRIDGE-BURST", rres.data_words, repeated, {ctx, " read repeats the word"}
    ));

    base  = ScratchBase + (64'($urandom_range(32'(ScratchBytes - 257))) & ~64'hFF);
    start = base + 64'h8;
    words.delete();
    repeat (4) words.push_back(64'($urandom()) & DataMask);
    folded = '{words[2], words[3], words[0], words[1]};
    ctx = $sformatf("WRAP beats=4 window=0x%0h start=0x%0h", base, start);
    burst_write_result(.addr(start), .data_words(words), .result(wres),
                       .burst(OCAH_AXI_BURST_WRAP));
    axi_cfg.arm_expected_read(base);
    burst_read_result(base, 4, rres);
    void'(evidence.expect_equal_words(
        "CHK-AXI-BRIDGE-WRAP", rres.data_words, folded, {ctx, " INCR readback of the window"}
    ));
    axi_cfg.arm_expected_read(start);
    burst_read_result(.addr(start), .beats(4), .result(rres), .burst(OCAH_AXI_BURST_WRAP));
    void'(evidence.expect_equal_words(
        "CHK-AXI-BRIDGE-WRAP", rres.data_words, words, {ctx, " WRAP readback"}
    ));
  endtask

  // Partial write strobes on a full-width beat change only the strobed lanes
  // of the stored word; the passive scoreboard scores the wire strobes
  // against the armed intent.
  protected task partial_strobes(bit [7:0] full_strb);
    bit [63:0] base, data, expected;
    ocah_axi_item wres, rres;
    string ctx;
    foreach (StrobePatterns[i]) begin
      base = 64'($urandom()) & DataMask;
      data = 64'($urandom()) & DataMask;
      expected = merge_lanes(base, data, StrobePatterns[i]);
      ctx = $sformatf("strb=0x%0h addr=0x%0h base=0x%0h data=0x%0h", StrobePatterns[i],
                      StrobeWord, base, data);
      axi_cfg.arm_expected_write(StrobeWord, base, full_strb);
      write_result(StrobeWord, base, wres);
      axi_cfg.arm_expected_write(StrobeWord, data, StrobePatterns[i]);
      write_result(.addr(StrobeWord), .data(data), .result(wres), .strb(StrobePatterns[i]));
      void'(evidence.expect_equal(
          "CHK-AXI-BRIDGE-STRB", 64'(slave_seq.read32(StrobeWord)), expected, {ctx, " backdoor"}
      ));
      axi_cfg.arm_expected_read(StrobeWord);
      read_result(StrobeWord, rres);
      void'(evidence.expect_equal(
          "CHK-AXI-BRIDGE-STRB", rres.first_data(), expected, {ctx, " readback"}
      ));
    end
  endtask

  // The word `base` holds after a strobed write of `data`.
  protected function bit [63:0] merge_lanes(bit [63:0] base, bit [63:0] data, bit [7:0] strb);
    bit [63:0] merged = base;
    for (int unsigned lane = 0; lane < 8; lane++) begin
      if (strb[lane]) merged[8*lane+:8] = data[8*lane+:8];
    end
    return merged & DataMask;
  endfunction

  // One-shot read and write faults programmed through the slave sequence,
  // each direction once per error response code.
  protected task faults(bit [7:0] full_strb);
    ocah_axi_resp_e codes[2] = '{OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR};
    bit [63:0] stored;
    ocah_axi_item wres;
    stored = 64'($urandom()) & DataMask;
    axi_cfg.arm_expected_write(FaultWord, stored, full_strb);
    write_result(FaultWord, stored, wres);
    foreach (codes[i]) begin
      read_fault(codes[i], stored);
      write_fault(codes[1-i], stored, full_strb);
    end
  endtask

  // A one-shot read fault answers `code` once, then the word reads back.
  protected task read_fault(ocah_axi_resp_e code, bit [63:0] stored);
    ocah_axi_item rres;
    slave_seq.inject_error(FaultWord, code, 1'b1, 1'b0);
    axi_cfg.arm_expected_resp(FaultWord, code, .for_read(1'b1), .for_write(1'b0));
    axi_cfg.arm_expected_read(FaultWord);
    read_result(.addr(FaultWord), .result(rres), .check_response(1'b0));
    void'(evidence.expect_true(
        "CHK-AXI-BRIDGE-FAULT-RD",
        rres.worst_resp() == code,
        $sformatf(
            "read fault resp=%s expected=%s", rres.worst_resp().name(), code.name())
    ));
    axi_cfg.arm_expected_read(FaultWord);
    read_result(FaultWord, rres);
    void'(evidence.expect_true(
        "CHK-AXI-BRIDGE-FAULT-RD",
        rres.is_ok() && rres.first_data() == stored,
        $sformatf(
            "%s one-shot retired, data intact", code.name())
    ));
  endtask

  // A one-shot write fault answers `code` once and leaves the word untouched.
  protected task write_fault(ocah_axi_resp_e code, bit [63:0] stored, bit [7:0] full_strb);
    bit [63:0] other;
    ocah_axi_item wres, rres;
    other = 64'($urandom()) & DataMask;
    slave_seq.inject_error(FaultWord, code, 1'b0, 1'b1);
    axi_cfg.arm_expected_resp(FaultWord, code, .for_read(1'b0), .for_write(1'b1));
    axi_cfg.arm_expected_write(FaultWord, other, full_strb);
    write_result(.addr(FaultWord), .data(other), .result(wres), .check_response(1'b0));
    void'(evidence.expect_true(
        "CHK-AXI-BRIDGE-FAULT-WR",
        wres.worst_resp() == code,
        $sformatf(
            "write fault resp=%s expected=%s", wres.worst_resp().name(), code.name())
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-BRIDGE-FAULT-WR",
        64'(slave_seq.read32(
            FaultWord
        )),
        stored,
        $sformatf(
            "%s backdoor: untouched", code.name())
    ));
    axi_cfg.arm_expected_read(FaultWord);
    read_result(FaultWord, rres);
    void'(evidence.expect_true(
        "CHK-AXI-BRIDGE-FAULT-WR",
        rres.is_ok() && rres.first_data() == stored,
        $sformatf(
            "%s bus: untouched", code.name())
    ));
  endtask

  // A deferred BREADY and a held RREADY: the responder keeps BVALID and
  // RVALID asserted with a stable payload until the master accepts.
  protected task response_holds(bit [7:0] full_strb);
    bit [63:0] data;
    ocah_axi_item wres, rres;
    data = 64'($urandom()) & DataMask;
    axi_cfg.arm_expected_write(HoldWord, data, full_strb);
    write_skewed_result(.addr(HoldWord), .data(data), .result(wres), .b_ready_delay(stall_cycles));
    void'(evidence.expect_true(
        "CHK-AXI-BRIDGE-HOLD",
        wres.is_ok(),
        $sformatf(
            "BREADY deferred %0d cycles resp=%s", stall_cycles, wres.worst_resp().name())
    ));
    axi_cfg.arm_expected_read(HoldWord);
    read_hold_result(HoldWord, stall_cycles, rres);
    void'(evidence.expect_true(
        "CHK-AXI-BRIDGE-HOLD",
        rres.is_ok() && rres.hold_stable && rres.first_data() == data,
        $sformatf(
            "RREADY held %0d cycles stable=%0d data=0x%0h",
            stall_cycles,
            rres.hold_stable,
            rres.first_data())
    ));
  endtask

  // Bounded READY stalls on the agent's request channels complete every
  // transfer: one round on every request channel, one on the write address
  // channel alone, where the write data waits for its address (the
  // responder accepts W after AW).
  protected task backpressure(bit [7:0] full_strb);
    string all_channels[$] = '{"aw", "w", "ar"};
    string aw_only[$] = '{"aw"};
    stall_round(all_channels, StallBase, full_strb);
    stall_round(aw_only, StallBase + 64'h10, full_strb);
  endtask

  protected task stall_round(string channels[$], bit [63:0] base, bit [7:0] full_strb);
    bit [63:0] addr, data;
    ocah_axi_item wres, rres;
    slave_seq.enable_backpressure(channels, stall_cycles);
    for (int unsigned index = 0; index < 4; index++) begin
      addr = base + 64'(4 * index);
      data = 64'($urandom()) & DataMask;
      axi_cfg.arm_expected_write(addr, data, full_strb);
      write_result(addr, data, wres);
      axi_cfg.arm_expected_read(addr);
      read_result(addr, rres);
      void'(evidence.expect_true(
          "CHK-AXI-BRIDGE-BACKPRESSURE",
          wres.is_ok() && rres.is_ok() && rres.first_data() == data,
          $sformatf(
              "stall=%0d channels=%p op=%0d addr=0x%0h", stall_cycles, channels, index, addr)
      ));
    end
    slave_seq.disable_backpressure();
  endtask

endclass : ocah_axi_struct_bridge_test_seq
