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
//     arm_w_before_aw(), and after its AW handshake without it
//     (CHK-AXI-SLAVE-W-FIRST).
//   * BUSER and RUSER are zero until randomize_resp_user(); then they take
//     more than one value across the beats, repeat for the same seed and the
//     same accesses, and change with the seed (CHK-AXI-SLAVE-USER).
// The passive env scores every access, with each injected error armed on
// it as an expected response.

class ocah_axi_responder_ops_test_seq extends ocah_axi_pipeline_base_test_seq;
  `uvm_object_utils(ocah_axi_responder_ops_test_seq)

  // Bound by the test before start(): the passive env cfg that classifies
  // the injected errors.
  ocah_axi_config axi_cfg;

  localparam int unsigned AwDelay = 4;
  localparam int unsigned UserOps = 8;
  localparam bit [63:0] ErrWord = 64'h100;
  localparam bit [63:0] OrderBase = 64'h200;
  localparam bit [63:0] UserBase = 64'h1000;
  localparam bit [63:0] DataMask = 64'hFFFF_FFFF;

  typedef bit [15:0] user_q_t[$];

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
    resp_user();
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

  // One write whose AWVALID rises AwDelay cycles after its WVALID.
  protected task w_before_aw(bit armed, bit [63:0] addr);
    ocah_axi_item ops[$], result;
    int unsigned aw_hs[$], w_hs[$];
    bit [63:0] data = 64'($urandom()) & DataMask;
    string ctx = $sformatf("armed=%0d addr=0x%0h", armed, addr);
    if (armed) slave_seq.arm_w_before_aw();
    ops.push_back(pipeline_write(addr, data, AwDelay));
    recorded_pipeline(ops, result);
    handshakes(0, aw_hs);
    handshakes(1, w_hs);
    if (!evidence.expect_true(
            "CHK-AXI-SLAVE-W-FIRST",
            aw_hs.size() == 1 && w_hs.size() == 1,
            $sformatf(
                "%s AW handshakes=%0d W handshakes=%0d", ctx, aw_hs.size(), w_hs.size())
        ))
      return;
    void'(evidence.expect_true(
        "CHK-AXI-SLAVE-W-FIRST",
        armed ? (w_hs[0] < aw_hs[0]) : (w_hs[0] > aw_hs[0]),
        $sformatf(
            "%s W handshake at sample %0d, AW handshake at sample %0d", ctx, w_hs[0], aw_hs[0])
    ));
    void'(evidence.expect_equal(
        "CHK-AXI-SLAVE-W-FIRST", 64'(slave_seq.read32(addr)), data, {ctx, " stored word"}
    ));
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
      record();
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

endclass : ocah_axi_responder_ops_test_seq
