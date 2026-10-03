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
// After the pipelines, a list whose write times out behind AW and W stalls
// while its read completes, and a list the driver rejects for an
// out-of-range access before driving anything.

class ocah_axi_pipeline_test_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(ocah_axi_pipeline_test_seq)

  localparam int unsigned ShortTimeout = 50;
  localparam int unsigned DrainCycles = 64;
  localparam int unsigned QuietCycles = 20;

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

  // pipeline_result under the per-cycle recorder, which keeps sampling for
  // `tail` cycles after the operation returns.
  protected task recorded_pipeline(input ocah_axi_item ops[$], output ocah_axi_item result,
                                   input int unsigned b_hold = 0, input int unsigned r_hold = 0,
                                   input bit allow_timeout = 1'b0, input int unsigned tail = 0);
    m_stop = 1'b0;
    fork
      record();
      begin
        pipeline_result(ops, result, b_hold, r_hold, 1'b1, allow_timeout);
        repeat (tail) @(cfg.vif.mon_cb);
        m_stop = 1'b1;
      end
    join
  endtask

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
    recorded_pipeline(ops, result, b_hold, r_hold);

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

  // A write to word A held off by AW and W stalls far beyond a shortened
  // handshake bound, behind which a read of word B completes.
  protected task run_partial_timeout();
    ocah_axi_item ops[$];
    ocah_axi_item result, wres, rres;
    int unsigned saved_timeout = cfg.timeout_cycles;
    bit [63:0] word_a = m_words[6];
    bit [63:0] word_b = m_words[7];
    bit [63:0] word_c = m_words[8];
    bit [63:0] data_c = 64'($urandom());

    `uvm_info(get_type_name(), $sformatf("partial timeout: bound=%0d stall=%0d", ShortTimeout,
                                         4 * ShortTimeout), UVM_LOW)
    cfg.timeout_cycles = ShortTimeout;
    slave_cfg.disable_backpressure();
    slave_cfg.enable_backpressure('{"aw", "w"}, 4 * ShortTimeout);
    // The responder takes up a stall setting at its next sampled edge; the
    // write must not meet an AWREADY raised before it.
    repeat (2) @(cfg.vif.mon_cb);
    ops.push_back(pipeline_write(word_a, 64'($urandom())));
    ops.push_back(pipeline_read(word_b));
    recorded_pipeline(ops, result, 0, 0, 1'b1);
    cfg.timeout_cycles = saved_timeout;

    void'(evidence.expect_true("CHK-AXI-PIPE-TIMEOUT", result.timed_out, "operation timed out"));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-TIMEOUT", ops[1].is_ok() && !ops[1].timed_out, "read completed OKAY"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-TIMEOUT", ops[1].first_data(), m_memory[word_b], "read data"
    ));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-TIMEOUT", ops[0].timed_out && !ops[0].is_ok(), "write timed out"
    ));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-TIMEOUT",
        result.aw_stall_cycles > 0,
        $sformatf(
            "AW stalled %0d cycles", result.aw_stall_cycles)
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-TIMEOUT", 64'(result.aw_stall_cycles), 64'(stalls(0)), "AW stall cycles"
    ));

    // Word A has no expected value: the cocotb twin's backend completes the
    // abandoned write later, this driver withdraws it.
    slave_cfg.disable_backpressure();
    repeat (DrainCycles) @(cfg.vif.mon_cb);
    write_result(word_c, data_c, wres);
    read_result(word_c, rres);
    m_memory[word_c] = data_c;
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-TIMEOUT", rres.first_data(), data_c, "readback after the timeout"
    ));
  endtask

  // A valid write to word D ahead of a read beyond the 32-bit address
  // space: the call fails with the bus idle and word D unchanged.
  protected task run_atomic_validation();
    ocah_axi_pipeline_reject_catcher catcher;
    ocah_axi_item ops[$];
    ocah_axi_item result;
    int unsigned busy = 0;
    bit [63:0] word_d = m_words[9];

    catcher = ocah_axi_pipeline_reject_catcher::type_id::create("catcher");
    `uvm_info(get_type_name(), "atomic validation: valid write, out-of-range read", UVM_LOW)
    ops.push_back(pipeline_write(word_d, m_memory[word_d] ^ 64'hFFFF_FFFF));
    ops.push_back(pipeline_read(64'h1_0000_0000));
    uvm_report_cb::add(null, catcher);
    recorded_pipeline(ops, result, 0, 0, 1'b0, QuietCycles);
    uvm_report_cb::delete(null, catcher);

    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-ATOMIC", 64'(catcher.caught), 64'd1, "rejections reported"
    ));
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-ATOMIC",
        ops[0].resp_list.size() == 0 && !ops[0].timed_out &&
                ops[1].resp_list.size() == 0 && !ops[1].timed_out,
        "no access ran"
    ));
    foreach (m_samples[c]) begin
      sample_t s = m_samples[c];
      if (s.awvalid || s.wvalid || s.arvalid || (s.bvalid && s.bready) || (s.rvalid && s.rready))
        busy++;
    end
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-ATOMIC",
        64'(busy),
        64'd0,
        $sformatf(
            "request VALID or handshake samples of %0d", m_samples.size())
    ));

    ops.delete();
    ops.push_back(pipeline_read(word_d));
    pipeline_result(ops, result);
    void'(evidence.expect_true(
        "CHK-AXI-PIPE-ATOMIC", ops[0].is_ok() && !result.timed_out, "next pipeline completes"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-ATOMIC", ops[0].first_data(), m_memory[word_d], "word D over the bus"
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-PIPE-ATOMIC", 64'(slave_seq.read32(word_d)), m_memory[word_d], "word D backdoor"
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
    run_partial_timeout();
    run_atomic_validation();

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
