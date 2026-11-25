// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI System Bus Access sizes, byte lanes and autoincrement on every
// bridge, each bridge in a seeded order. An access of each size up to the
// data width, at each offset aligned to it, strobes exactly its bytes,
// carries write data on the byte lanes the address selects and takes read
// data from them. With sbautoincrement the address advances by the access
// size after each access, from sbaddress0 into sbaddress1 on a bridge wider
// than 32 bits. The cocotb twin is
// seq_lib/dtp_jtag2axi_sba_sizes_test_seq.py.

class dtp_jtag2axi_sba_sizes_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_sba_sizes_test_seq)

  // Whole beats one autoincrement stream writes, so every byte a read of the
  // stream returns is one the stream wrote.
  localparam int unsigned StreamBeatsMin = 2;
  localparam int unsigned StreamBeatsMax = 3;

  typedef struct {
    int unsigned size;
    int unsigned offset;
  } access_t;

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_sba_sizes_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    string names[$] = '{"smc_otp", "sep_otp", "smc_axi"};
    seed_scenario_rng();
    `uvm_info(get_type_name(),
              "=== System Bus Access sizes, byte lanes and autoincrement on every bridge ===",
              UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      m_ledger = t.name;
      open_bus_ledger();
      lanes_case(t);
      autoincrement_case(t);
      check_responder_activity(t, 1, {t.name, ".sba_sizes"});
      close_bus_ledger();
      m_ledger = "";
      `uvm_info(get_type_name(), $sformatf("Summary: %s System Bus Access sizes complete", t.name),
                UVM_LOW)
    end
  endtask

  // Every (size, offset in the beat) pair `t` supports, the offset aligned
  // to the size.
  function void aligned_accesses(input dtp_j2a_target_t t, output access_t accesses[$]);
    accesses = {};
    for (int unsigned size = 0; size <= t.default_size; size++)
    for (int unsigned offset = 0; offset < t.beat_bytes; offset += dtp_j2a_size_bytes(size))
    accesses.push_back('{size: size, offset: offset});
  endfunction

  // Each read takes its bytes from the lanes its address selects, and each
  // write changes only the bytes it strobes.
  task lanes_case(dtp_j2a_target_t t);
    ocah_axi_checker              ev = evidence(t);
    string                        ctx = {t.name, ".lanes"};
    bit              [63:0]       base = random_target_addr(t);
    // Distinct bytes, so a read from any other lane returns other data.
    bit              [63:0]       beat = distinct_bytes(t.beat_bytes);
    access_t                      accesses[$];
    sba_write(t, base, beat, t.default_size, {ctx, ".fill"});
    check_target_word(t, base, beat, t.default_size, {ctx, ".fill.mem"});
    aligned_accesses(t, accesses);
    accesses.shuffle();
    foreach (accesses[i]) begin
      int unsigned        size = accesses[i].size;
      int unsigned        offset = accesses[i].offset;
      string              access = $sformatf("%s.read.size%0d.offset%0d", ctx, size, offset);
      bit          [63:0] mask = dtp_j2a_data_mask(size);
      bit          [63:0] rdata;
      sba_read(t, base + offset, size, access, rdata);
      void'(ev.expect_equal(
          "CHK-AXI-RDATA",
          rdata & mask,
          (beat >> (8 * offset)) & mask,
          $sformatf(
              "%s target=%s source=bridge_capture", access, t.name)
      ));
    end
    accesses.shuffle();
    foreach (accesses[i]) begin
      int unsigned        size = accesses[i].size;
      int unsigned        offset = accesses[i].offset;
      string              access = $sformatf("%s.write.size%0d.offset%0d", ctx, size, offset);
      bit          [63:0] mask = dtp_j2a_data_mask(size) << (8 * offset);
      bit          [63:0] lanes;
      do lanes = ({$urandom(), $urandom()} << (8 * offset)) & mask; while (lanes == (beat & mask));
      sba_write(t, base + offset, lanes >> (8 * offset), size, access);
      beat = (beat & ~mask) | lanes;
      check_target_word(t, base, beat, t.default_size, {access, ".mem"});
    end
  endtask

  // An autoincrement stream at every size `t` supports, in a seeded order.
  task autoincrement_case(dtp_j2a_target_t t);
    int unsigned sizes[$];
    for (int unsigned size = 0; size <= t.default_size; size++) sizes.push_back(size);
    sizes.shuffle();
    foreach (sizes[i]) autoincrement_stream(t, sizes[i]);
  endtask

  // With sbautoincrement each sbdata0 write starts a `size` write at the next
  // address, and a read started by an sbaddress0 write advances the address
  // too; on a bridge wider than 32 bits the stream crosses address bit 32.
  task autoincrement_stream(dtp_j2a_target_t t, int unsigned size);
    ocah_axi_checker        ev = evidence(t);
    string                  ctx = $sformatf("%s.autoinc.size%0d", t.name, size);
    int unsigned            stride = dtp_j2a_size_bytes(size);
    int unsigned            per_beat = t.beat_bytes / stride;
    int unsigned            beats = $urandom_range(StreamBeatsMax, StreamBeatsMin);
    int unsigned            count = beats * per_beat;
    bit              [63:0] mask = dtp_j2a_data_mask(size);
    int unsigned            below;
    int unsigned            index;
    bit              [63:0] start;
    bit              [63:0] last;
    bit              [63:0] addr;
    bit              [63:0] rdata;
    bit              [63:0] words[$];
    if (t.addr_width > 32) begin
      below = $urandom_range(beats - 1, 1);
      start = ((64'($urandom_range(32'(bit_mask(t.addr_width - 32)) - 1)) + 1) << 32) -
          below * t.beat_bytes;
      // The read is of the last element below the boundary.
      index = below * per_beat - 1;
    end else begin
      index = $urandom_range(count - 1);
      start = random_target_addr(t);
      last  = bit_mask(t.addr_width) + 1 - (beats + 1) * t.beat_bytes;
      if (start > last) start = last;
    end
    distinct_words(8 * stride, count, words);
    sba_setup(t, start, size, 1'b0, {ctx, ".stream"}, 1'b1);
    foreach (words[i])
      sba_write_data(t, start + i * stride, words[i], size, $sformatf("%s.write%0d", ctx, i));
    check_sba_address(t, start + count * stride, {ctx, ".stream"});
    foreach (words[i])
      check_target_word(t, start + i * stride, words[i], size, $sformatf("%s.mem%0d", ctx, i));
    addr = start + index * stride;
    sba_read(t, addr, size, {ctx, ".read"}, rdata, 1'b1);
    void'(ev.expect_equal(
        "CHK-AXI-RDATA",
        rdata & mask,
        words[index],
        $sformatf(
            "%s.read target=%s source=bridge_capture", ctx, t.name)
    ));
    check_sba_address(t, addr + stride, {ctx, ".read"});
  endtask

  // CHK-J2A-AUTOINC: sbaddress reads `expected`.
  // +DTP_J2A_AUTOINC_NEGATIVE flips the expected bit 0, so the run must fail.
  task check_sba_address(dtp_j2a_target_t t, bit [63:0] expected, string context_s);
    ocah_axi_checker        ev = evidence(t);
    bit              [63:0] observed;
    read_sbaddress(t, context_s, observed);
    expected &= bit_mask(t.addr_width);
    if (test_cfg != null && test_cfg.j2a_autoinc_negative) expected ^= 64'h1;
    void'(ev.expect_equal(
        DtpJ2aAutoincCheckId,
        observed,
        expected,
        $sformatf(
            "%s target=%s observed=0x%0h expected=0x%0h", context_s, t.name, observed, expected)
    ));
  endtask

  // A word of `count` seeded bytes, no two equal.
  function bit [63:0] distinct_bytes(int unsigned count);
    byte unsigned        values[$];
    bit           [63:0] word = '0;
    for (int unsigned value = 0; value < 256; value++) values.push_back(8'(value));
    values.shuffle();
    for (int unsigned i = 0; i < count; i++) word[8*i+:8] = values[i];
    return word;
  endfunction

  // `count` seeded nonzero `bits`-bit words, no two equal.
  function void distinct_words(input int unsigned bits, input int unsigned count,
                               output bit [63:0] words[$]);
    words = {};
    while (words.size() < count) begin
      bit [63:0] word = {$urandom(), $urandom()} & bit_mask(bits);
      int        found[$] = words.find_first_index(w) with (w == word);
      if (word != '0 && found.size() == 0) words.push_back(word);
    end
  endfunction

endclass : dtp_jtag2axi_sba_sizes_test_seq
