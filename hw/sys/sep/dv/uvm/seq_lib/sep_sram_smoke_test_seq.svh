// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP no-CPU SRAM smoke scenario sequence, carrying the cocotb
// sep_sram_smoke_seq semantics on the CPU-LSU AXI4 splice: the SEP local
// fabric routes to the SRAM and the SRAM stores.
//   * wait for fuse sense done, since the local fabric answers only after
//     it;
//   * read one SRAM word before any write and require zero (decode and
//     liveness anchor; the zero is the zero fill of the SRAM macro in
//     tb/tb_top.sv, not a reset property of the SRAM);
//   * write the cocotb 64-bit pattern and read it back;
//   * write the cocotb 32-bit pattern as a genuine 4-byte beat (AxSIZE=2)
//     to the upper half and read the full word back: only the upper lanes
//     change, the lower lanes keep the 64-bit pattern;
//   * then random_count seeded random rounds IN ADDITION (+SEP_RANDOM_COUNT,
//     default 5): a 64-bit write and readback, then a 4-byte beat to a
//     seeded half and a full-word readback;
//   * every access must return OKAY, and every read must return one beat.
// Each pass uses its own SRAM word (loop_index selects it), so the
// before-write read of every pass reads a word no earlier pass wrote. Every
// expected value is the written stimulus or the zero fill; the scoreboard
// does not predict SRAM. The cocotb twin is seq_lib/sep_sram_smoke_seq.py.

class sep_sram_smoke_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_sram_smoke_test_seq)

  localparam string ChkResetRead = "CHK-RESET-READ";
  localparam string ChkStore = "CHK-STORE";
  localparam string ChkLane = "CHK-LANE";
  localparam string ChkRandomStore = "CHK-RANDOM-STORE";
  localparam string ChkRandomLane = "CHK-RANDOM-LANE";
  localparam string ChkResp = "CHK-RESP";

  // Word of pass 0 (the cocotb target), then one 64-bit word per pass.
  localparam bit [63:0] TargetOffset = 64'h100;
  localparam int unsigned WordBytes = 8;
  localparam int unsigned WordSize = 3;
  localparam int unsigned HalfBytes = 4;

  // The cocotb directed patterns.
  localparam bit [63:0] StorePattern = 64'h0123_4567_89AB_CDEF;
  localparam bit [31:0] LanePattern = 32'hFEED_FACE;

  function new(string name = "sep_sram_smoke_test_seq");
    super.new(name);
  endfunction

  // Record the response of one access, and for a read the beat count, so a
  // read that returns no data word cannot pass as zero.
  function void check_resp(ocah_axi_item result, bit is_read, string label);
    check_evidence(ChkResp, {label, ".resp"}, 64'(result.worst_resp()), 64'(OCAH_AXI_RESP_OKAY),
                   $sformatf("addr=0x%0h resp=%s", result.address, result.worst_resp().name()));
    if (is_read)
      check_evidence(ChkResp, {label, ".beats"}, 64'(result.data_words.size()), 64'd1, $sformatf(
                     "addr=0x%0h", result.address));
  endfunction

  // One full 64-bit word write.
  task word_write(bit [63:0] addr, bit [63:0] data, string label);
    ocah_axi_item result;
    bus_write(addr, data, 8'hFF, WordSize, result, label);
    check_resp(result, 1'b0, label);
  endtask

  // One genuine 4-byte beat (AxSIZE=2) at a 4-byte-aligned address; the
  // value sits on its byte lanes of the bus word with the matching strobes.
  task half_write(bit [63:0] addr, bit [31:0] data, string label);
    ocah_axi_item result;
    bus_write(addr, sep_csr_to_bus(addr, data), sep_csr_strb(addr), SepCsrSize, result, label);
    check_resp(result, 1'b0, label);
  endtask

  // One full 64-bit word read, compared under check_id.
  task word_read_check(string check_id, bit [63:0] addr, bit [63:0] expected, string label);
    ocah_axi_item result;
    bus_read(addr, WordSize, result, label);
    check_resp(result, 1'b1, label);
    check_evidence(check_id, label, result.first_data(), expected, $sformatf("addr=0x%0h", addr));
  endtask

  task body();
    bit [63:0] word_addr;
    bit [63:0] rand_word;
    bit [31:0] rand_half;
    bit        upper;
    bit [63:0] expected;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkResp, ChkResetRead, ChkStore, ChkLane, ChkRandomStore,
                    ChkRandomLane});
    word_addr = 64'(SEP_SRAM_MEM_BASE_ADDR) + TargetOffset + 64'(loop_index) * WordBytes;
    if (word_addr + WordBytes > 64'(SEP_SRAM_MEM_BASE_ADDR) + 64'(SEP_SRAM_MEM_SIZE))
      `uvm_fatal(get_type_name(), $sformatf(
                 "pass %0d word 0x%0h is outside the SRAM", loop_index, word_addr))
    `uvm_info(get_type_name(),
              $sformatf({"SEP SV-UVM SRAM smoke: CPU-LSU word 0x%08h, directed 64-bit and 32-bit ",
                         "write/readback; scenario_seed=%0d random_count=%0d"}, word_addr,
                          scenario_seed, random_count), UVM_LOW)

    wait_fuse_sense_done();

    log_step("1", "read before any write");
    word_read_check(ChkResetRead, word_addr, 64'h0, "sram.before_write");

    log_step("2", "directed 64-bit write/readback");
    word_write(word_addr, StorePattern, "sram.store");
    word_read_check(ChkStore, word_addr, StorePattern, "sram.store");

    log_step("3", "directed 4-byte beat to the upper half");
    half_write(word_addr + HalfBytes, LanePattern, "sram.lane");
    word_read_check(ChkLane, word_addr, {LanePattern, StorePattern[31:0]}, "sram.lane");

    log_step("4", "seeded random write/readback");
    for (int unsigned r = 0; r < random_count; r++) begin
      string label = $sformatf("sram.random%0d", r);
      rand_word = random_pattern(64);
      word_write(word_addr, rand_word, {label, ".store"});
      word_read_check(ChkRandomStore, word_addr, rand_word, {label, ".store"});
      rand_half = 32'(random_pattern(32));
      upper     = 1'(random_pattern(1));
      half_write(word_addr + (upper ? HalfBytes : 0), rand_half, {label, ".lane"});
      expected = upper ? {rand_half, rand_word[31:0]} : {rand_word[63:32], rand_half};
      word_read_check(ChkRandomLane, word_addr, expected, $sformatf(
                      "%s.lane.%s", label, upper ? "upper" : "lower"));
    end

    finalize_evidence();
  endtask

endclass : sep_sram_smoke_test_seq
