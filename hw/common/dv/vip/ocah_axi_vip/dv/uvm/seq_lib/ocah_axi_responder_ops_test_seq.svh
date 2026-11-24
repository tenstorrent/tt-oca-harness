// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scenario sequence for ocah_axi_responder_ops_test (the SV-UVM twin of the
// cocotb selftest): the responder operations a DUT bench programs, driven
// through the master sequence API and judged against a per-cycle recording
// of the harness bus.
//   * An errored read beat answers the RDATA word its injection armed,
//     truncated to the bus width, or zero when none was given; the next read
//     of the slot returns memory (CHK-AXI-SLAVE-ERR-RDATA).
//   * A write whose AW is held back completes its W handshake first after
//     arm_w_before_aw(), on every write while set_w_before_aw(1) holds, and
//     after its AW handshake otherwise; while set_w_before_aw(1) holds, a
//     write whose AW and W rise together completes both on one edge, or its
//     AW handshake first while WREADY is stalled (CHK-AXI-SLAVE-W-FIRST).
//   * BUSER and RUSER are zero until randomize_resp_user(); then they take
//     more than one value across the beats, repeat for the same seed and the
//     same accesses, and change with the seed (CHK-AXI-SLAVE-USER).
//   * ocah_axi_delays draws the values its cocotb twin draws for the same
//     seed; under enable_random_backpressure() every AW and AR handshake, and
//     every W handshake counted from its AW handshake, waits at most the
//     largest draw, some wait longer than any short draw, and the same seeds
//     repeat the same waits (CHK-AXI-SLAVE-STALL).
//   * Under set_response_delay() each BVALID and first RVALID comes exactly
//     the drawn number of cycles later than without it
//     (CHK-AXI-SLAVE-RESP-DELAY).
//   * The monitor's items carry the AxCACHE, AxUSER and per-beat WUSER the
//     master drives (CHK-AXI-MON-ATTR).
// The passive env scores every access, with each injected error armed on
// it as an expected response.

class ocah_axi_responder_ops_test_seq extends ocah_axi_pipeline_base_test_seq;
  `uvm_object_utils(ocah_axi_responder_ops_test_seq)

  // Bound by the test before start(): the passive env cfg that classifies
  // the injected errors, and the passive monitor's item stream.
  ocah_axi_config                        axi_cfg;
  uvm_tlm_analysis_fifo #(ocah_axi_item) observed;

  localparam int unsigned AwDelay = 4;
  // WREADY stall of the persistent-order write whose AW lands first.
  localparam int unsigned WStall = 3;
  localparam int unsigned UserOps = 8;
  localparam bit [63:0] ErrWord = 64'h100;
  localparam bit [63:0] OrderBase = 64'h200;
  localparam bit [63:0] UserBase = 64'h1000;
  localparam bit [63:0] DataMask = 64'hFFFF_FFFF;
  localparam bit [63:0] StallBase = 64'h2000;
  localparam bit [63:0] DelayBase = 64'h3000;
  localparam bit [63:0] AttrBase = 64'h4000;
  localparam int unsigned OrderWrites = 4;
  localparam int unsigned TimingOps = 6;
  // Stall and delay draws: 0..ShortMax cycles, or LongMin..LongMax cycles
  // LongPercent percent of the time.
  localparam int unsigned ShortMax = 3;
  localparam int unsigned LongPercent = 30;
  localparam int unsigned LongMin = 12;
  localparam int unsigned LongMax = 20;

  typedef bit [15:0] user_q_t[$];
  typedef int unsigned count_q_t[$];

  function new(string name = "ocah_axi_responder_ops_test_seq");
    super.new(name);
  endfunction

  task body();
    if (evidence == null || slave_seq == null || axi_cfg == null)
      `uvm_fatal(get_type_name(), "evidence/slave_seq/axi_cfg handles not bound")
    void'(resolve_cfg());
    errored_beat_word();
    w_before_aw(1'b1, OrderBase);
    w_before_aw(1'b0, OrderBase + 64'h4);
    w_before_aw_always();
    resp_user();
    delays_vector();
    random_stalls();
    response_delays();
    monitor_attributes();
  endtask

  protected task errored_beat_word();
    bit [63:0] preload, word;
    ocah_axi_item wres, rres;
    preload = 64'($urandom()) & DataMask;
    word    = (preload ^ 64'($urandom_range(32'hFFFF_FFFF, 1))) & DataMask;
    write_result(ErrWord, preload, wres);

    slave_seq.inject_error(ErrWord, OCAH_AXI_RESP_SLVERR, 1'b1, 1'b0, {32'hA5, word[31:0]});
    axi_cfg.arm_expected_resp(ErrWord, OCAH_AXI_RESP_SLVERR, .for_read(1'b1), .for_write(1'b0));
    read_result(.addr(ErrWord), .result(rres), .check_response(1'b0));
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-ERR-RDATA",
        rres.worst_resp() == OCAH_AXI_RESP_SLVERR && rres.first_data() == word,
        $sformatf(
            "armed word: resp=%s rdata=0x%0h word=0x%0h",
            rres.worst_resp().name(),
            rres.first_data(),
            word)
    ));

    slave_seq.inject_error(ErrWord, OCAH_AXI_RESP_DECERR, 1'b1, 1'b0);
    axi_cfg.arm_expected_resp(ErrWord, OCAH_AXI_RESP_DECERR, .for_read(1'b1), .for_write(1'b0));
    read_result(.addr(ErrWord), .result(rres), .check_response(1'b0));
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-ERR-RDATA",
        rres.worst_resp() == OCAH_AXI_RESP_DECERR && rres.first_data() == '0,
        $sformatf(
            "no word: resp=%s rdata=0x%0h", rres.worst_resp().name(), rres.first_data())
    ));

    read_result(ErrWord, rres);
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-ERR-RDATA",
        rres.is_ok() && rres.first_data() == preload,
        $sformatf(
            "unarmed: resp=%s rdata=0x%0h preload=0x%0h",
            rres.worst_resp().name(),
            rres.first_data(),
            preload)
    ));
  endtask

  // One write whose AWVALID rises `aw_delay` cycles after its WVALID, with
  // WREADY stalled `w_stall` cycles from the write's start. When `armed`, its
  // W handshake comes first, on the AW handshake's edge with `aw_delay` 0, or
  // after it while `w_stall` outlasts `aw_delay`; otherwise after the AW
  // handshake. `arm` arms the one-shot order for it; with `arm` 0 the
  // persistent order decides.
  protected task w_before_aw(bit armed, bit [63:0] addr, bit arm = 1'b1,
                             int unsigned aw_delay = AwDelay, int unsigned w_stall = 0);
    ocah_axi_item ops[$], result;
    int unsigned aw_hs[$], w_hs[$];
    bit in_order;
    bit [63:0] data = 64'($urandom()) & DataMask;
    string ctx = $sformatf(
        "armed=%0d one-shot=%0d aw_delay=%0d w_stall=%0d addr=0x%0h",
        armed,
        armed && arm,
        aw_delay,
        w_stall,
        addr
    );
    if (armed && arm) slave_seq.arm_w_before_aw();
    if (w_stall > 0) slave_seq.enable_backpressure('{"w"}, w_stall);
    ops.push_back(pipeline_write(addr, data, aw_delay));
    recorded_pipeline(ops, result);
    if (w_stall > 0) slave_seq.disable_backpressure();
    handshakes(0, aw_hs);
    handshakes(1, w_hs);
    if (!evidence.expect_true(
            "CHK-AXI-SLAVE-W-FIRST",
            aw_hs.size() == 1 && w_hs.size() == 1,
            $sformatf(
                "%s AW handshakes=%0d W handshakes=%0d", ctx, aw_hs.size(), w_hs.size())
        ))
      return;
    if (!armed || w_stall > aw_delay) in_order = w_hs[0] > aw_hs[0];
    else if (aw_delay == 0) in_order = w_hs[0] == aw_hs[0];
    else in_order = w_hs[0] < aw_hs[0];
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-W-FIRST",
        in_order,
        $sformatf(
            "%s W handshake at sample %0d, AW handshake at sample %0d", ctx, w_hs[0], aw_hs[0])
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-SLAVE-W-FIRST", 64'(slave_seq.read32(addr)), data, {ctx, " stored word"}
    ));
  endtask

  // Every write takes its W handshake first while set_w_before_aw(1) holds,
  // both handshakes on one edge when AW and W rise together, and its AW
  // handshake first when WREADY is stalled past AWVALID; then its AW
  // handshake first again after set_w_before_aw(0).
  protected task w_before_aw_always();
    slave_seq.set_w_before_aw(1'b1);
    for (int unsigned i = 0; i < OrderWrites; i++)
      w_before_aw(1'b1, OrderBase + 64'h10 + 64'(4 * i), .arm(1'b0));
    w_before_aw(1'b1, OrderBase + 64'h28, .arm(1'b0), .aw_delay(0), .w_stall(WStall));
    w_before_aw(1'b1, OrderBase + 64'h2C, .arm(1'b0), .aw_delay(0));
    slave_seq.set_w_before_aw(1'b0);
    w_before_aw(1'b0, OrderBase + 64'h30);
  endtask

  protected task resp_user();
    bit [63:0] addrs[UserOps], data[UserOps];
    user_q_t b_zero, r_zero, b_first, r_first, b_again, r_again, b_other, r_other;
    int unsigned seed = $urandom();
    int unsigned other_seed = seed ^ 32'h5A5A_5A5A;
    bit ok;
    foreach (addrs[i]) begin
      addrs[i] = UserBase + 64'(4 * i);
      data[i]  = 64'($urandom()) & DataMask;
    end

    user_pass(addrs, data, b_zero, r_zero);
    ok = full_pass(b_zero, r_zero) && all_zero(b_zero) && all_zero(r_zero);
    check_user(ok, "before randomize_resp_user", b_zero, r_zero);

    slave_seq.randomize_resp_user(seed);
    user_pass(addrs, data, b_first, r_first);
    ok = full_pass(b_first, r_first) && varies(b_first) && varies(r_first);
    check_user(ok, $sformatf("seed=%0d", seed), b_first, r_first);

    slave_seq.randomize_resp_user(seed);
    user_pass(addrs, data, b_again, r_again);
    ok = same(b_again, b_first) && same(r_again, r_first);
    check_user(ok, $sformatf("seed=%0d again", seed), b_again, r_again);

    slave_seq.randomize_resp_user(other_seed);
    user_pass(addrs, data, b_other, r_other);
    ok = full_pass(b_other, r_other) && !same(b_other, b_first) && !same(r_other, r_first);
    check_user(ok, $sformatf("seed=%0d", other_seed), b_other, r_other);
  endtask

  // A write and a read back of every address under the recorder; BUSER of
  // each B handshake and RUSER of each R handshake, in order.
  protected task user_pass(input bit [63:0] addrs[UserOps], input bit [63:0] data[UserOps],
                           output user_q_t b_user, output user_q_t r_user);
    ocah_axi_item wres, rres;
    m_stop = 1'b0;
    fork
      record_samples();
      begin
        foreach (addrs[i]) begin
          write_result(addrs[i], data[i], wres);
          read_result(addrs[i], rres);
        end
        repeat (2) @(cfg.vif.mon_cb);
        m_stop = 1'b1;
      end
    join
    b_user.delete();
    r_user.delete();
    foreach (m_samples[c]) begin
      if (m_samples[c].bvalid && m_samples[c].bready) b_user.push_back(m_samples[c].buser);
      if (m_samples[c].rvalid && m_samples[c].rready) r_user.push_back(m_samples[c].ruser);
    end
  endtask

  protected function void check_user(bit ok, string what, user_q_t b_user, user_q_t r_user);
    void'(evidence.expect_true("CHK-AXI-SLAVE-USER", ok,
                               $sformatf("%s: BUSER=%p RUSER=%p", what, b_user, r_user)));
  endfunction

  protected function bit full_pass(user_q_t b_user, user_q_t r_user);
    return b_user.size() == UserOps && r_user.size() == UserOps;
  endfunction

  protected function bit all_zero(user_q_t values);
    foreach (values[i]) if (values[i] != '0) return 1'b0;
    return 1'b1;
  endfunction

  protected function bit varies(user_q_t values);
    foreach (values[i]) if (values[i] != values[0]) return 1'b1;
    return 1'b0;
  endfunction

  protected function bit same(user_q_t a, user_q_t b);
    if (a.size() != b.size()) return 1'b0;
    foreach (a[i]) if (a[i] != b[i]) return 1'b0;
    return 1'b1;
  endfunction

  // The first draws of ocah_axi_delays seeded 1 with a 0..9 short range and
  // a 40..60 long range 25 percent of the time.
  protected function void delays_vector();
    int unsigned golden[12] = '{7, 2, 1, 5, 8, 3, 6, 4, 48, 6, 1, 41};
    ocah_axi_delays delays = new(1, 0, 9, 25, 40, 60);
    count_q_t drawn;
    bit ok = 1'b1;
    foreach (golden[i]) begin
      drawn.push_back(delays.next());
      ok &= drawn[i] == golden[i];
    end
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-STALL", ok, $sformatf("ocah_axi_delays seed 1 drew %p", drawn)
    ));
  endfunction

  // Two passes of the same accesses under READY stalls on AW, W and AR drawn
  // from the same seeds.
  protected task random_stalls();
    int unsigned seed = $urandom();
    count_q_t aw_first, w_first, ar_first, aw_again, w_again, ar_again;
    bit bounded, waited_long, repeated;
    stall_pass(seed, aw_first, w_first, ar_first);
    stall_pass(seed, aw_again, w_again, ar_again);
    bounded = at_most(aw_first, LongMax) && at_most(w_first, LongMax) &&
        at_most(ar_first, LongMax);
    waited_long = !at_most(aw_first, ShortMax) || !at_most(w_first, ShortMax) ||
        !at_most(ar_first, ShortMax);
    repeated = aw_first.size() == TimingOps && w_first.size() == TimingOps &&
        ar_first.size() == TimingOps && counts_equal(aw_first, aw_again) &&
        counts_equal(w_first, w_again) && counts_equal(ar_first, ar_again);
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-STALL",
        bounded && waited_long && repeated,
        $sformatf(
            "seed=%0d AW waits %p/%p W waits %p/%p AR waits %p/%p",
            seed,
            aw_first,
            aw_again,
            w_first,
            w_again,
            ar_first,
            ar_again)
    ));
  endtask

  // TimingOps writes and reads back under seeded READY stalls; the cycles
  // each AW, W and AR handshake waited with VALID high and READY low, W
  // counted from its AW handshake since the responder opens WREADY only
  // after the address.
  protected task stall_pass(input int unsigned seed, output count_q_t aw_waits,
                            output count_q_t w_waits, output count_q_t ar_waits);
    ocah_axi_delays aw_stalls = new(seed, 0, ShortMax, LongPercent, LongMin, LongMax);
    ocah_axi_delays w_stalls = new(seed + 1, 0, ShortMax, LongPercent, LongMin, LongMax);
    ocah_axi_delays ar_stalls = new(seed + 2, 0, ShortMax, LongPercent, LongMin, LongMax);
    repeat (4) @(cfg.vif.mon_cb);
    slave_seq.enable_random_backpressure('{"aw"}, aw_stalls);
    slave_seq.enable_random_backpressure('{"w"}, w_stalls);
    slave_seq.enable_random_backpressure('{"ar"}, ar_stalls);
    timing_ops(StallBase);
    slave_seq.disable_backpressure();
    aw_waits = handshake_waits(0);
    w_waits  = handshake_waits(1, .after_aw(1'b1));
    ar_waits = handshake_waits(3);
  endtask

  // TimingOps writes, each read back, under the recorder.
  protected task timing_ops(bit [63:0] base);
    ocah_axi_item wres, rres;
    m_stop = 1'b0;
    fork
      record_samples();
      begin
        for (int unsigned i = 0; i < TimingOps; i++) begin
          write_result(base + 64'(4 * i), (64'(i + 1) * 64'h0101_0101) & DataMask, wres);
          read_result(base + 64'(4 * i), rres);
        end
        repeat (2) @(cfg.vif.mon_cb);
        m_stop = 1'b1;
      end
    join
  endtask

  // The VALID-high, READY-low samples before each handshake on `chan`; with
  // `after_aw`, only the samples after the latest AW handshake.
  protected function count_q_t handshake_waits(int unsigned chan, bit after_aw = 1'b0);
    count_q_t waits;
    int unsigned run = 0;
    foreach (m_samples[c]) begin
      if (!valid_at(chan, c)) begin
        run = 0;
      end else if (ready_at(chan, c)) begin
        waits.push_back(run);
        run = 0;
      end else begin
        run++;
      end
      if (after_aw && valid_at(0, c) && ready_at(0, c)) run = 0;
    end
    return waits;
  endfunction

  // The same accesses without and with B and R delays: each BVALID and
  // first RVALID moves by exactly the draw of a same-seed twin source.
  protected task response_delays();
    int unsigned seed = $urandom();
    int unsigned r_seed = seed ^ 32'h5A5A_5A5A;
    ocah_axi_delays b_delays = new(seed, 0, ShortMax, LongPercent, LongMin, LongMax);
    ocah_axi_delays r_delays = new(r_seed, 0, ShortMax, LongPercent, LongMin, LongMax);
    ocah_axi_delays b_twin = new(seed, 0, ShortMax, LongPercent, LongMin, LongMax);
    ocah_axi_delays r_twin = new(r_seed, 0, ShortMax, LongPercent, LongMin, LongMax);
    count_q_t b_base, r_base, b_late, r_late, b_drawn, r_drawn;
    bit ok;
    timing_ops(DelayBase);
    b_base = response_latencies(1'b0);
    r_base = response_latencies(1'b1);
    slave_seq.set_response_delay(b_delays, .read(1'b0), .write(1'b1));
    slave_seq.set_response_delay(r_delays, .read(1'b1), .write(1'b0));
    timing_ops(DelayBase);
    slave_seq.clear_response_delay();
    b_late = response_latencies(1'b0);
    r_late = response_latencies(1'b1);
    ok = b_base.size() == TimingOps && r_base.size() == TimingOps &&
        b_late.size() == TimingOps && r_late.size() == TimingOps;
    for (int unsigned i = 0; ok && i < TimingOps; i++) begin
      b_drawn.push_back(b_twin.next());
      r_drawn.push_back(r_twin.next());
      ok = b_late[i] == b_base[i] + b_drawn[i] && r_late[i] == r_base[i] + r_drawn[i];
    end
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-RESP-DELAY",
        ok,
        $sformatf(
            "B latency %p -> %p for draws %p; R latency %p -> %p for draws %p",
            b_base,
            b_late,
            b_drawn,
            r_base,
            r_late,
            r_drawn)
    ));
  endtask

  // Samples from each write's last W handshake to its first BVALID sample
  // (`read` 0), or from each AR handshake to its first RVALID sample.
  protected function count_q_t response_latencies(bit read);
    count_q_t latencies;
    int unsigned request = 0;
    int unsigned req_chan = read ? 3 : 1;
    int unsigned rsp_chan = read ? 4 : 2;
    foreach (m_samples[c]) begin
      if (valid_at(req_chan, c) && ready_at(req_chan, c)) request = c;
      if (valid_at(rsp_chan, c) && (c == 0 || !valid_at(rsp_chan, c - 1)))
        latencies.push_back(c - request);
    end
    return latencies;
  endfunction

  // A two-beat write and a read with seeded nonzero AxCACHE, AxUSER and
  // WUSER; the monitor's items carry them.
  protected task monitor_attributes();
    ocah_axi_item wr = ocah_axi_item::type_id::create("attr_write");
    ocah_axi_item rd = ocah_axi_item::type_id::create("attr_read");
    ocah_axi_item seen_wr, seen_rd;
    bit wr_match, rd_match;
    observed.flush();
    wr.protocol       = resolve_cfg().protocol;
    wr.direction      = OCAH_AXI_DIR_WRITE;
    wr.address        = AttrBase;
    wr.size           = resolve_size(-1);
    wr.expected_beats = 2;
    wr.cache          = 4'($urandom_range(15, 1));
    wr.user           = 64'($urandom_range(16'hFFFF, 1));
    for (int unsigned beat = 0; beat < 2; beat++) begin
      wr.data_words.push_back(64'($urandom()) & DataMask);
      wr.strobes.push_back(resolve_strb(8'hFF));
      wr.wusers.push_back(64'($urandom_range(16'hFFFF, 1)));
    end
    do_axi(wr);
    rd.protocol       = resolve_cfg().protocol;
    rd.direction      = OCAH_AXI_DIR_READ;
    rd.address        = AttrBase;
    rd.size           = resolve_size(-1);
    rd.expected_beats = 1;
    rd.cache          = 4'($urandom_range(15, 1));
    rd.user           = 64'($urandom_range(16'hFFFF, 1));
    do_axi(rd);
    repeat (2) @(cfg.vif.mon_cb);
    void'(observed.try_get(seen_wr));
    void'(observed.try_get(seen_rd));
    if (!evidence.expect_true(
            "CHK-AXI-MON-ATTR",
            seen_wr != null && seen_rd != null && observed.is_empty() &&
                seen_wr.direction == OCAH_AXI_DIR_WRITE && seen_rd.direction == OCAH_AXI_DIR_READ,
            "the write and then the read each published one item"
        ))
      return;
    wr_match = seen_wr.cache == wr.cache && seen_wr.user == wr.user;
    wr_match &= words_equal(seen_wr.wusers, wr.wusers);
    rd_match = seen_rd.cache == rd.cache && seen_rd.user == rd.user && seen_rd.wusers.size() == 0;
    void'(evidence.expect_true(
        "CHK-AXI-MON-ATTR",
        wr_match,
        $sformatf(
            "write cache=0x%0h/0x%0h user=0x%0h/0x%0h wusers=%p/%p",
            seen_wr.cache,
            wr.cache,
            seen_wr.user,
            wr.user,
            seen_wr.wusers,
            wr.wusers)
    ));
    void'(evidence.expect_true(
        "CHK-AXI-MON-ATTR",
        rd_match,
        $sformatf(
            "read cache=0x%0h/0x%0h user=0x%0h/0x%0h",
            seen_rd.cache,
            rd.cache,
            seen_rd.user,
            rd.user)
    ));
  endtask

  protected function bit at_most(count_q_t values, int unsigned limit);
    foreach (values[i]) if (values[i] > limit) return 1'b0;
    return 1'b1;
  endfunction

  protected function bit counts_equal(count_q_t a, count_q_t b);
    if (a.size() != b.size()) return 1'b0;
    foreach (a[i]) if (a[i] != b[i]) return 1'b0;
    return 1'b1;
  endfunction

  protected function bit words_equal(bit [63:0] a[$], bit [63:0] b[$]);
    if (a.size() != b.size()) return 1'b0;
    foreach (a[i]) if (a[i] != b[i]) return 1'b0;
    return 1'b1;
  endfunction

endclass : ocah_axi_responder_ops_test_seq
