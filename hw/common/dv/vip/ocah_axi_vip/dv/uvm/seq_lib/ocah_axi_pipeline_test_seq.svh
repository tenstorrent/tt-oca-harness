// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_axi_pipeline_test (the SV-UVM twin of the cocotb
// ocah_axi_lite_pipeline_test): a directed list and randomized lists of
// single-beat reads and writes issued through pipeline_result, with and
// without responder READY stalls. Every claim of the operation is judged
// against a per-cycle recording of the master's own interface: each beat
// launches on the later of its channel delay and the cycle after the beat
// ahead of it was accepted, VALID holds until the handshake, BREADY and
// RREADY stay low for the hold after the first BVALID and RVALID, each
// response returns to its own access, and the reported stall cycles match
// the wires. Read data is cross-checked against the responder's backdoor.

class ocah_axi_pipeline_test_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(ocah_axi_pipeline_test_seq)

  typedef struct {
    bit        awvalid, awready, wvalid, wready, bvalid, bready;
    bit        arvalid, arready, rvalid, rready;
    bit [63:0] awaddr, wdata, araddr;
  } sample_t;

  // Bound by the test before start().
  ocah_axi_checker        evidence;
  ocah_axi_slave_config   slave_cfg;
  ocah_axi_slave_sequence slave_seq;

  int unsigned n_ops = 12;

  protected sample_t     m_samples[$];
  protected bit          m_stop;
  protected bit   [63:0] m_memory   [bit [63:0]];
  protected bit   [63:0] m_words    [$];

  function new(string name = "ocah_axi_pipeline_test_seq");
    super.new(name);
  endfunction

  protected task record();
    m_samples.delete();
    while (!m_stop) begin
      sample_t row;
      @(cfg.vif.mon_cb);
      row.awvalid = cfg.vif.mon_cb.awvalid === 1'b1;
      row.awready = cfg.vif.mon_cb.awready === 1'b1;
      row.wvalid  = cfg.vif.mon_cb.wvalid === 1'b1;
      row.wready  = cfg.vif.mon_cb.wready === 1'b1;
      row.bvalid  = cfg.vif.mon_cb.bvalid === 1'b1;
      row.bready  = cfg.vif.mon_cb.bready === 1'b1;
      row.arvalid = cfg.vif.mon_cb.arvalid === 1'b1;
      row.arready = cfg.vif.mon_cb.arready === 1'b1;
      row.rvalid  = cfg.vif.mon_cb.rvalid === 1'b1;
      row.rready  = cfg.vif.mon_cb.rready === 1'b1;
      row.awaddr  = 64'(cfg.vif.mon_cb.awaddr);
      row.wdata   = 64'(cfg.vif.mon_cb.wdata);
      row.araddr  = 64'(cfg.vif.mon_cb.araddr);
      m_samples.push_back(row);
    end
  endtask

  // chan: 0 AW, 1 W, 2 B, 3 AR, 4 R.
  protected function bit valid_at(int unsigned chan, int unsigned c);
    case (chan)
      0: return m_samples[c].awvalid;
      1: return m_samples[c].wvalid;
      2: return m_samples[c].bvalid;
      3: return m_samples[c].arvalid;
      default: return m_samples[c].rvalid;
    endcase
  endfunction

  protected function bit ready_at(int unsigned chan, int unsigned c);
    case (chan)
      0: return m_samples[c].awready;
      1: return m_samples[c].wready;
      2: return m_samples[c].bready;
      3: return m_samples[c].arready;
      default: return m_samples[c].rready;
    endcase
  endfunction

  protected function bit [63:0] payload_at(int unsigned chan, int unsigned c);
    case (chan)
      0: return m_samples[c].awaddr;
      1: return m_samples[c].wdata;
      default: return m_samples[c].araddr;
    endcase
  endfunction

  protected function void handshakes(int unsigned chan, ref int unsigned hs[$]);
    hs.delete();
    foreach (m_samples[c]) if (valid_at(chan, c) && ready_at(chan, c)) hs.push_back(c);
  endfunction

  protected function int unsigned stalls(int unsigned chan);
    int unsigned n = 0;
    foreach (m_samples[c]) if (valid_at(chan, c) && !ready_at(chan, c)) n++;
    return n;
  endfunction

  // Order and launch cycles of one request channel. A beat with delay d
  // shows in sample d at the earliest and no earlier than the sample after
  // the beat ahead of it was accepted.
  protected function void check_lane(int unsigned chan, ocah_axi_item beats[$], string ctx,
                                     ref int unsigned hs[$]);
    string name = (chan == 0) ? "AW" : (chan == 1) ? "W" : "AR";
    handshakes(chan, hs);
    if (!evidence.expect_equal(
            "CHK-AXI-PIPE-ORDER",
            64'(hs.size()),
            64'(beats.size()),
            $sformatf(
                "%s %s handshakes", ctx, name)
        ))
      return;
    foreach (beats[i]) begin
      int unsigned delay = (chan == 0) ? beats[i].aw_valid_delay :
                           (chan == 1) ? beats[i].w_valid_delay : beats[i].ar_valid_delay;
      bit [63:0] expected = (chan == 1) ? beats[i].data_words[0] : beats[i].address;
      int unsigned floor = (i == 0) ? 0 : hs[i-1] + 1;
      int unsigned launch = floor;
      bit held = 1'b1;
      void'(evidence.expect_equal(
          "CHK-AXI-PIPE-ORDER",
          payload_at(
              chan, hs[i]
          ),
          expected,
          $sformatf(
              "%s %s beat %0d", ctx, name, i)
      ));
      while (launch < m_samples.size() && !valid_at(chan, launch)) launch++;
      void'(evidence.expect_equal(
          "CHK-AXI-PIPE-LAUNCH",
          64'(launch),
          64'((delay > floor) ? delay : floor),
          $sformatf(
              "%s %s beat %0d delay %0d floor %0d", ctx, name, i, delay, floor)
      ));
      for (int unsigned c = launch; c <= hs[i]; c++) held &= valid_at(chan, c);
      void'(evidence.expect_true(
          "CHK-AXI-PIPE-LAUNCH", held, $sformatf("%s %s beat %0d held VALID", ctx, name, i)
      ));
    end
  endfunction

  // READY low for `hold` samples from the first VALID.
  protected function void check_hold(int unsigned chan, int unsigned hold, string ctx);
    int unsigned hs[$];
    int unsigned first = 0;
    bit low = 1'b1;
    handshakes(chan, hs);
    if (hold == 0 || hs.size() == 0) return;
    while (!valid_at(chan, first)) first++;
    for (int unsigned c = first; c < first + hold; c++) low &= !ready_at(chan, c);
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-HOLD",
        (hs[0] >= first + hold) && low,
        $sformatf(
            "%s %s first=%0d handshake=%0d hold=%0d",
            ctx,
            (chan == 2) ? "B" : "R",
            first,
            hs[0],
            hold)
    ));
  endfunction

  protected task run_pipeline(int unsigned index, ocah_axi_item ops[$], int unsigned b_hold,
                              int unsigned r_hold, int unsigned stall, output int unsigned b_hs[$],
                              output int unsigned ar_hs[$]);
    ocah_axi_item result, writes[$], reads[$];
    int unsigned hs[$];
    string ctx = $sformatf("op=%0d", index);
    `uvm_info(get_type_name(), $sformatf("%s: %0d accesses b_hold=%0d r_hold=%0d stall=%0d", ctx,
                                         ops.size(), b_hold, r_hold, stall), UVM_LOW)
    if (stall > 0) slave_cfg.enable_backpressure('{"aw", "w", "ar"}, stall);
    else slave_cfg.disable_backpressure();
    m_stop = 1'b0;
    fork
      record();
      begin
        pipeline_result(ops, result, b_hold, r_hold);
        m_stop = 1'b1;
      end
    join

    foreach (ops[i]) begin
      if (ops[i].direction == OCAH_AXI_DIR_WRITE) begin
        writes.push_back(ops[i]);
        m_memory[ops[i].address] = ops[i].data_words[0];
      end else begin
        reads.push_back(ops[i]);
        void'(evidence.expect_equal(
            "CHK-AXI-PIPE-DATA",
            ops[i].first_data(),
            m_memory[ops[i].address],
            $sformatf(
                "%s read 0x%0h", ctx, ops[i].address)
        ));
      end
      void'(evidence.expect_true(
          "CHK-AXI-PIPE-DATA",
          ops[i].is_ok() && !ops[i].timed_out,
          $sformatf(
              "%s access %0d resp", ctx, i)
      ));
    end
    foreach (m_memory[addr])
      void'(evidence.expect_equal(
          "CHK-AXI-PIPE-DATA",
          64'(slave_seq.read32(
              addr
          )),
          m_memory[addr],
          $sformatf(
              "%s backdoor 0x%0h", ctx, addr)
      ));

    check_lane(0, writes, ctx, hs);
    check_lane(1, writes, ctx, hs);
    check_lane(3, reads, ctx, ar_hs);
    handshakes(2, b_hs);
    handshakes(4, hs);
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-ORDER",
        b_hs.size() == writes.size() && hs.size() == reads.size(),
        $sformatf(
            "%s %0d B and %0d R handshakes", ctx, b_hs.size(), hs.size())
    ));
    check_hold(2, b_hold, ctx);
    check_hold(4, r_hold, ctx);
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-STALL", 64'(result.aw_stall_cycles), 64'(stalls(0)), {ctx, " AW"}
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-STALL", 64'(result.w_stall_cycles), 64'(stalls(1)), {ctx, " W"}
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-STALL", 64'(result.ar_stall_cycles), 64'(stalls(3)), {ctx, " AR"}
    ));
  endtask

  task body();
    ocah_axi_item ops[$];
    ocah_axi_item wres, rres;
    int unsigned b_hs[$], ar_hs[$];
    bit [63:0] word_dir[bit [63:0]];

    if (evidence == null || slave_cfg == null || slave_seq == null)
      `uvm_fatal(get_type_name(), "evidence/slave_cfg/slave_seq handles not bound")
    void'(resolve_cfg());

    // Preload through the bus, so the passive reference model's shadow
    // memory holds every word the lists read.
    while (m_words.size() < 64) begin
      bit [63:0] addr = 64'($urandom_range(16383)) & ~64'h3;
      if (!m_memory.exists(addr)) begin
        m_memory[addr] = 64'($urandom());
        write_result(addr, m_memory[addr], wres);
        m_words.push_back(addr);
      end
    end

    // Directed: reads interleaved with three writes whose responses wait
    // behind a BREADY hold, and an AW-first and a W-first write.
    ops.push_back(pipeline_write(m_words[0], 64'($urandom())));
    ops.push_back(pipeline_read(m_words[1]));
    ops.push_back(pipeline_write(m_words[2], 64'($urandom()), 0, 3));
    ops.push_back(pipeline_read(m_words[3], 1));
    ops.push_back(pipeline_write(m_words[4], 64'($urandom()), 5, 1));
    ops.push_back(pipeline_read(m_words[5]));
    run_pipeline(0, ops, 10, 4, 0, b_hs, ar_hs);
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-OVERLAP",
        ar_hs[0] < b_hs[0],
        $sformatf(
            "first AR at %0d, first B at %0d", ar_hs[0], b_hs[0])
    ));

    for (int unsigned index = 1; index <= n_ops; index++) begin
      int unsigned count = $urandom_range(8, 3);
      ops.delete();
      word_dir.delete();
      repeat (count) begin
        bit [63:0] addr = m_words[$urandom_range(m_words.size() - 1)];
        bit is_write = $urandom_range(1);
        // A read and a write to one word in one list race at the responder,
        // so each word takes one direction per list.
        if (word_dir.exists(addr) && word_dir[addr] != 64'(is_write)) continue;
        word_dir[addr] = 64'(is_write);
        if (is_write)
          ops.push_back(pipeline_write(addr, 64'($urandom()), $urandom_range(6), $urandom_range(6)
                        ));
        else ops.push_back(pipeline_read(addr, $urandom_range(6)));
      end
      run_pipeline(index, ops, $urandom_range(8), $urandom_range(8), $urandom_range(3), b_hs,
                   ar_hs);
    end

    // A plain access afterwards proves the pipeline leaves the master idle.
    slave_cfg.disable_backpressure();
    write_result(m_words[$], 64'h5A5A_A5A5, wres);
    read_result(m_words[$], rres);
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-DATA", rres.first_data(), 64'h5A5A_A5A5, "post-pipeline readback"
    ));
    `uvm_info(get_type_name(), $sformatf("done: %0d pipelines, writes=%0d reads=%0d", n_ops + 1,
                                         write_transactions, read_transactions), UVM_LOW)
  endtask

endclass : ocah_axi_pipeline_test_seq
