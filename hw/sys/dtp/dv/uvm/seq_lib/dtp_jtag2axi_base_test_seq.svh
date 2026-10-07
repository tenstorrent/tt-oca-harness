// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI family layer of the DTP scenario sequences — the SV analogue of
// the cocotb dtp_jtag2axi_base_test_seq. Every bridge request is a reusable
// operation on the primary TAP sequencer (dtp_jtag2axi_single_op_seq /
// _single_status_seq / _series_ctrl_seq / _series_data_seq, all built on
// the dtp_types codec); this layer adds the bridge geometry lookups, the
// status polling bound, the evidence arming, the responder backdoor through
// the virtual sequencer's responder sequences, the lifecycle debug-disable
// gating, and the request-activity evidence from the dtp_tb_if pulse
// counters.
//
// The responders are shared ocah_axi_vip UVM slave agents reached through
// the virtual sequencer by target name; the test plumbs every bridge's
// evidence bundle (target_cfgs / target_evidence / target_ref_models, keyed
// by bridge name) and port history (axi_ports) before start(), and
// use_target() points axi_cfg / axi_evidence / axi_ref_model at the bridge
// a scenario judges. Error arming discipline: arm_target_error() programs
// the responder injection, with the errored-beat word for a read, AND
// cfg.arm_expected_resp() in one place, so the injected non-OKAY is
// EXPECTED for the shared AXI scoreboard; clear_target_error() clears the
// injection. test_cfg.axi_scoreboard_negative (+DTP_AXI_SCOREBOARD_NEGATIVE)
// is the negative-validation hook: it arms the WRONG expected response so
// the run must FAIL, proving the checker rejects a bad expectation end to
// end.
//
// Every judgement of the bridge under test lands as a CHK-* record on
// axi_evidence: CHK-J2A-FAULT-STATUS for the status a SINGLE_OP or
// SERIES_CTRL capture returns, CHK-AXI-RDATA (source=bridge_capture) for
// the read data it returns, CHK-AXI-WMEM for responder words,
// CHK-J2A-SERIES-ADDR for the SERIES_CTRL address, and CHK-AXI-COMPLETION
// for a bounded wait on the port that expired. A scenario calls
// use_target() before its first operation on a bridge.
//
// Gated attempts must never arm credits: issue_single() skips intent arming
// whenever the target's lifecycle disable is asserted, and an operation the
// scenario aborts passes arm_intent = 0 (an armed credit that is never
// consumed correctly fails at check_phase). The lifecycle debug disables
// reset to the fail-closed '1 tie-off, so the target's disable must be
// cleared before any JTAG2AXI op.

class dtp_jtag2axi_base_test_seq extends dtp_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_base_test_seq)

  // Every bridge's shared AXI VIP passive cfg (expected-response/intent
  // arming), scoreboard evidence recorder, and passive reference model
  // (backdoor-preload mirror), keyed by bridge name and plumbed by the test.
  ocah_axi_config      target_cfgs[string];
  ocah_axi_checker     target_evidence[string];
  ocah_axi_ref_model   target_ref_models[string];
  // The bundle of the bridge use_target() selected.
  ocah_axi_config      axi_cfg;
  ocah_axi_checker     axi_evidence;
  ocah_axi_ref_model   axi_ref_model;
  // Completed-transaction histories of the three bridge ports, keyed by
  // target name.
  dtp_axi_port_history axi_ports[string];

  // The three bridges in the cocotb ROBUST_TARGETS order, for the scenarios
  // that iterate all of them.
  localparam int unsigned NumTargets = 3;
  dtp_j2a_target_t targets[NumTargets];

  // The pass's bus-request ledger (CHK-J2A-BUS-REQ): the bridge it accounts,
  // "" while closed, and per bridge port the counts that the pass's judged
  // operations add up to.
  protected string       m_ledger_target;
  protected int unsigned m_ledger_writes[string];
  protected int unsigned m_ledger_reads[string];

  // Settle after programming or clearing responder error injection
  // (system-domain cycles).
  localparam int unsigned InjectSettleCycles = 2;
  // TCK cycles for a bridge's state machine to return to idle after a
  // response, and for a released bridge to put a queued request on the bus.
  localparam int unsigned QueueDropTck = 32;
  // System cycles a wait on a bridge port's request or completion lasts
  // before it records a CHK-AXI-COMPLETION timeout.
  localparam int unsigned PortWaitCycles = 200;

  // Completed responder bursts per bridge when the pass began: the
  // anti-vacuity record of a scenario requires the bridge it ran on to have
  // moved at least one burst across the DUT's AXI port since then.
  protected int unsigned m_burst_baseline[string];

  // The image the last SINGLE_OP request or status capture shifted out.
  protected bit m_single_capture[];

  // Settled status of the scenario's last checked operation, and the
  // operations the pass ran.
  dtp_j2a_status_e status = DTP_J2A_SUCCESS;
  int unsigned operation_count = 0;

  function new(string name = "dtp_jtag2axi_base_test_seq");
    super.new(name);
    targets[0] = target_smc_axi();
    targets[1] = target_smc_otp();
    targets[2] = target_sep_otp();
  endfunction

  // Point axi_cfg / axi_evidence / axi_ref_model at the bundle of `t`: every
  // judgement of that bridge records through axi_evidence.
  function void use_target(dtp_j2a_target_t t);
    if (!target_cfgs.exists(
            t.name
        ) || !target_evidence.exists(
            t.name
        ) || !target_ref_models.exists(
            t.name
        ))
      `uvm_fatal(get_type_name(), $sformatf("%s evidence bundle not plumbed by the test", t.name))
    axi_cfg       = target_cfgs[t.name];
    axi_evidence  = target_evidence[t.name];
    axi_ref_model = target_ref_models[t.name];
    if (axi_cfg == null || axi_evidence == null || axi_ref_model == null)
      `uvm_fatal(get_type_name(), $sformatf("%s evidence bundle has a null handle", t.name))
  endfunction

  // use_target() on targets[idx], returning its geometry.
  function dtp_j2a_target_t select_target(int unsigned idx);
    use_target(targets[idx]);
    return targets[idx];
  endfunction

  // Open a pass over every bridge: every bridge's bundle must be plumbed,
  // and the pass starts on targets[0] with every debug path enabled and the
  // TAP in Run-Test/Idle.
  task begin_all_bridges_pass();
    for (int unsigned i = 0; i < NumTargets; i++) void'(select_target(i));
    void'(select_target(0));
    enable_all_debug();
    reset_to_rti();
  endtask

  // Every pass opens with the burst baseline and the geometry gate: the
  // three *_JTAG2AXI_CAPS TDRs are read and their bus type, address size,
  // data size, and write and read pipeline depths compared with the
  // dtp_types table (CHK-J2A-GEOMETRY), so no bridge request is packed with
  // field widths the DUT does not publish.
  virtual task pre_body();
    super.pre_body();
    snapshot_burst_baseline();
    verify_bridge_geometry();
    open_bus_ledger();
  endtask

  virtual task post_body();
    super.post_body();
    close_bus_ledger();
  endtask

  function void snapshot_burst_baseline();
    string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    foreach (names[i]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[i]);
      m_burst_baseline[t.name] = write_bursts_now(t) + read_bursts_now(t);
    end
  endfunction

  // Bursts the responder behind `t` completed since the pass began: the
  // bus-side witness that the bridge drove its AXI port.
  function int unsigned bursts_since_baseline(dtp_j2a_target_t t);
    int unsigned now = write_bursts_now(t) + read_bursts_now(t);
    return m_burst_baseline.exists(t.name) ? now - m_burst_baseline[t.name] : now;
  endfunction

  // +DTP_J2A_GEOMETRY_NEGATIVE corrupts the expected address size so the
  // run must FAIL, proving the gate rejects a wrong table end to end.
  task verify_bridge_geometry();
    string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    bit negative = (test_cfg != null) && test_cfg.j2a_geometry_negative;
    ocah_jtag_checker geometry = ocah_jtag_checker::type_id::create({get_name(), ".geometry"});
    geometry.name_tag     = $sformatf("dtp_jtag2axi_geometry.pass%0d", loop_index);
    geometry.required_ids = {DtpJ2aGeometryCheckId};
    if (negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: geometry gate expectations will be corrupted", UVM_LOW)
    tap_reset();
    step(1'b0);  // TLR -> RTI: TDR reads start their IR scan from Run-Test/Idle
    foreach (names[i]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[i]);
      bit [63:0] value;
      bit [63:0] exp_addr = 64'(t.addr_width) ^ 64'(negative);
      read_tdr(IrWidth'(t.caps_instr), DtpJtag2AxiCapsLen, value);
      `uvm_info(get_type_name(), $sformatf(
                "GEOMETRY %s raw=0x%04h bus_type=%0d addr_size=%0d data_size=%0d",
                t.caps_instr.name(),
                value,
                value[0],
                value[6:1],
                value[9:7]
                ), UVM_LOW)
      void'(geometry.expect_equal(
          DtpJ2aGeometryCheckId, 64'(value[0]), 64'(t.bus_type), {t.name, " bus_type"}
      ));
      void'(geometry.expect_equal(
          DtpJ2aGeometryCheckId, 64'(value[6:1]), exp_addr, {t.name, " addr_size"}
      ));
      void'(geometry.expect_equal(
          DtpJ2aGeometryCheckId, 64'(value[9:7]), 64'(dtp_j2a_data_size(t)), {t.name, " data_size"}
      ));
      void'(geometry.expect_equal(
          DtpJ2aGeometryCheckId, 64'(value[11:10]), 64'(t.wr_pl_depth), {t.name, " wr_pl_depth"}
      ));
      void'(geometry.expect_equal(
          DtpJ2aGeometryCheckId, 64'(value[13:12]), 64'(t.rd_pl_depth), {t.name, " rd_pl_depth"}
      ));
    end
    geometry.finalize();
  endtask

  // --- bridge geometry and codec: short-name wrappers over dtp_types ------
  static function dtp_j2a_target_t target_smc_otp();
    return dtp_j2a_target_smc_otp();
  endfunction

  static function dtp_j2a_target_t target_sep_otp();
    return dtp_j2a_target_sep_otp();
  endfunction

  static function dtp_j2a_target_t target_smc_axi();
    return dtp_j2a_target_smc_axi();
  endfunction

  static function int unsigned single_op_len(dtp_j2a_target_t t);
    return dtp_j2a_single_op_len(t);
  endfunction

  static function int unsigned series_ctrl_len(dtp_j2a_target_t t);
    return dtp_j2a_series_ctrl_len(t);
  endfunction

  static function dtp_j2a_status_e axi_resp_to_status(ocah_axi_resp_e resp);
    return dtp_j2a_axi_resp_to_status(resp);
  endfunction

  static function int unsigned size_bytes(int unsigned size);
    return dtp_j2a_size_bytes(size);
  endfunction

  static function bit [63:0] data_mask(int unsigned size);
    return dtp_j2a_data_mask(size);
  endfunction

  static function bit [7:0] full_wstrb(int unsigned size);
    return dtp_j2a_full_wstrb(size);
  endfunction

  function bit [63:0] mask_target_data(dtp_j2a_target_t t, bit [63:0] value);
    return value & bit_mask(t.data_width);
  endfunction

  // A nonzero seeded word of the target's data width.
  function bit [63:0] rand_nonzero_data(dtp_j2a_target_t t);
    bit [63:0] data;
    do data = mask_target_data(t, {$urandom(), $urandom()}); while (data == '0);
    return data;
  endfunction

  // A seeded word, nonzero and different from every `avoid` word: a capture
  // that repeats an `avoid` word, or a data field a status poll cleared,
  // cannot pass for it.
  function bit [63:0] random_distinct_word(dtp_j2a_target_t t, bit [63:0] avoid[$]);
    bit [63:0] excluded[$];
    bit [63:0] word;
    foreach (avoid[i]) excluded.push_back(mask_target_data(t, avoid[i]));
    do word = rand_nonzero_data(t); while (word inside {excluded});
    return word;
  endfunction

  // Beat-aligned random address inside the responder memory window; wider
  // alignment when the transfer size exceeds the beat.
  function bit [63:0] random_target_aligned_addr(dtp_j2a_target_t t, int unsigned size);
    int unsigned align = (size_bytes(size) > t.beat_bytes) ? size_bytes(size)
                                                               : t.beat_bytes;
    int unsigned max_slot = (DtpJ2aTargetMemBytes - align) / align;
    return 64'($urandom_range(max_slot) * align);
  endfunction

  // Seeded address bits above the responder window, up to the bridge
  // address width: the responder memory never sees them, and
  // CHK-J2A-BUS-REQ judges them on the bus.
  function bit [63:0] random_upper_addr(dtp_j2a_target_t t);
    return ({$urandom(), $urandom()} << $clog2(DtpJ2aTargetMemBytes)) & bit_mask(t.addr_width);
  endfunction

  // A seeded beat-aligned stream base with seeded address bits above the
  // responder window. The stream's `span` bytes stay inside one window. With
  // `straddle`, a seeded half of the streams longer than a beat cross a
  // window top instead, at least one beat past it: the series address
  // carries out of the window bits through a seeded run of ones above them
  // and stops below the bridge address width.
  function bit [63:0] random_series_base(dtp_j2a_target_t t, bit [63:0] span, bit straddle = 1'b0);
    int unsigned window_bits = $clog2(DtpJ2aTargetMemBytes);
    bit [63:0] low = random_target_aligned_addr(t, t.default_size);
    bit [63:0] upper;
    int unsigned run, below;
    if (low > 64'(DtpJ2aTargetMemBytes) - span) low = 64'(DtpJ2aTargetMemBytes) - span;
    upper = random_upper_addr(t);
    if (straddle && span > t.beat_bytes && $urandom_range(1)) begin
      run   = $urandom_range(t.addr_width - window_bits - 1);
      below = $urandom_range(int'(span / t.beat_bytes) - 1, 1);
      upper = (upper | (((64'd1 << run) - 1) << window_bits)) & ~(64'd1 << (window_bits + run));
      low   = 64'(DtpJ2aTargetMemBytes) - 64'(below * t.beat_bytes);
    end
    return upper | low;
  endfunction

  // --- responder backdoor memory (shared slave agents) --------------------
  // The target's responder sequence from the virtual sequencer.
  protected function ocah_axi_slave_sequence responder(dtp_j2a_target_t t);
    ocah_axi_slave_sequence seq = p_sequencer.axi_slave_seq(t.name);
    if (seq == null)
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s responder sequence not wired on the virtual sequencer", t.name))
    return seq;
  endfunction

  // Backdoor-preload the responder RAM; mirrored into the passive reference
  // model's shadow so front-door reads of preloaded data compare clean.
  function void write_target_mem_int(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] value,
                                     int unsigned size);
    bit [7:0] payload[];
    bit [63:0] masked = value & data_mask(size);
    responder(t).write_int(addr, masked, size_bytes(size));
    payload = new[size_bytes(size)];
    foreach (payload[i]) payload[i] = masked[8*i+:8];
    axi_ref_model.backdoor_write(addr, payload);
  endfunction

  function bit [63:0] read_target_mem_int(dtp_j2a_target_t t, bit [63:0] addr, int unsigned size);
    return responder(t).read_int(addr, size_bytes(size)) & data_mask(size);
  endfunction

  // --- end-state byte image of a random write stream ----------------------
  // Images are keyed by responder slot, so two writes whose addresses share
  // a slot land in one image byte, as they do in the responder.

  // Record the bytes of the word at `addr` that the image lacks.
  function void snapshot_target_word(dtp_j2a_target_t t, ref bit [7:0] image[bit [63:0]],
                                     input bit [63:0] addr, input int unsigned size);
    bit [63:0] word = read_target_mem_int(t, addr, size);
    bit [63:0] slot = addr % DtpJ2aTargetMemBytes;
    for (int unsigned b = 0; b < size_bytes(size); b++) begin
      if (!image.exists(slot + b)) image[slot+b] = word[8*b+:8];
    end
  endfunction

  // Apply one write's enabled lanes to the byte image.
  function void image_write(ref bit [7:0] image[bit [63:0]], input bit [63:0] addr,
                            input bit [63:0] data, input bit [7:0] wstrb, input int unsigned size);
    bit [63:0] slot = addr % DtpJ2aTargetMemBytes;
    for (int unsigned b = 0; b < size_bytes(size); b++) begin
      if (wstrb[b]) image[slot+b] = data[8*b+:8];
    end
  endfunction

  // CHK-J2A-MEM-IMAGE: every byte of the image matches the responder memory.
  // The image holds every lane a stream wrote at its last value and every
  // untouched lane of a touched word at its prior value, so a write that
  // landed on the wrong lane or disturbed a neighbour fails here.
  // Each mismatching byte records its own FAIL with its address; one
  // record closes the image.
  function void check_memory_image(dtp_j2a_target_t t, ref bit [7:0] image[bit [63:0]],
                                   input string context_s);
    int unsigned mismatches = 0;
    foreach (image[addr]) begin
      bit [7:0] observed = 8'(read_target_mem_int(t, addr, 0));
      if (observed !== image[addr]) begin
        mismatches++;
        void'(axi_evidence.expect_equal(
            DtpJ2aMemImageCheckId,
            64'(observed),
            64'(image[addr]),
            $sformatf(
                "%s target=%s byte_addr=0x%0h", context_s, t.name, addr)
        ));
      end
    end
    void'(axi_evidence.expect_equal(
        DtpJ2aMemImageCheckId,
        64'(mismatches),
        64'd0,
        $sformatf(
            "%s target=%s bytes=%0d field=mismatches", context_s, t.name, image.num())
    ));
  endfunction

  // CHK-AXI-WMEM: responder RAM bytes versus the stimulus intent.
  function void check_target_memory(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] expected,
                                    int unsigned size, string context_s);
    bit [63:0] observed = read_target_mem_int(t, addr, size);
    void'(axi_evidence.expect_equal(
        "CHK-AXI-WMEM",
        observed,
        expected & data_mask(
            size
        ),
        $sformatf(
            "%s target=%s addr=0x%0h len=%0d source=intent",
            context_s,
            t.name,
            addr,
            size_bytes(
                size
            ))
    ));
  endfunction

  // CHK-AXI-RDATA: the read data a SINGLE_OP or series capture returned
  // equals `expected`, the word the responder holds at the read address.
  function void check_returned_rdata(dtp_j2a_target_t t, bit [63:0] observed, bit [63:0] expected,
                                     string context_s);
    void'(axi_evidence.expect_equal(
        "CHK-AXI-RDATA",
        observed,
        expected,
        $sformatf(
            "%s target=%s source=bridge_capture", context_s, t.name)
    ));
  endfunction

  // CHK-AXI-COMPLETION FAIL for a bounded wait on the port of `t` that
  // expired; the bound rides in the context.
  function void record_wait_timeout(dtp_j2a_target_t t, int unsigned timeout_cycles,
                                    string context_s);
    void'(axi_evidence.expect_not_timed_out(
        "CHK-AXI-COMPLETION",
        1'b1,
        64'(timeout_cycles) * tb_vif.clk_period_ns,
        $sformatf(
            "%s target=%s cycles=%0d", context_s, t.name, timeout_cycles)
    ));
  endfunction

  // --- per-operation bus-request ledger (CHK-J2A-BUS-REQ) -----------------
  // The bridge whose port this scenario's ledger accounts; "" keeps it
  // closed.
  virtual function string bus_ledger_target();
    return "";
  endfunction

  function dtp_axi_port_history port_history(string name);
    if (!axi_ports.exists(name) || axi_ports[name] == null)
      `uvm_fatal(get_type_name(), $sformatf("%s port history not plumbed by the test", name))
    return axi_ports[name];
  endfunction

  // Account the bridge ports for this pass when the test requires
  // CHK-J2A-BUS-REQ on the ledger target. From the second pass on, every
  // port's counts must equal those the previous pass closed with.
  function void open_bus_ledger();
    string name = bus_ledger_target();
    dtp_axi_port_history port;
    m_ledger_target = "";
    if (name == "" || test_cfg == null || !test_cfg.requires_axi_id(name, DtpJ2aBusReqCheckId))
      return;
    use_target(dtp_j2a_target_by_name(name));
    m_ledger_target = name;
    void'(port_history(name));
    foreach (axi_ports[p]) begin
      port = port_history(p);
      if (port.marked)
        void'(check_bus_counts(p, port.mark_writes, port.mark_reads, "between_passes"));
      m_ledger_writes[p] = port.count(1'b0);
      m_ledger_reads[p]  = port.count(1'b1);
    end
    if (test_cfg.j2a_bus_req_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: bus-request address expectations will be corrupted", UVM_LOW)
  endfunction

  // No transaction reached the port after the pass's last judged operation,
  // and every other bridge port holds the counts it opened the pass with.
  function void close_bus_ledger();
    dtp_axi_port_history port;
    if (m_ledger_target == "") return;
    foreach (m_ledger_writes[p]) begin
      port = port_history(p);
      void'(check_bus_counts(p, m_ledger_writes[p], m_ledger_reads[p], "after_last_op"));
      port.marked      = 1'b1;
      port.mark_writes = m_ledger_writes[p];
      port.mark_reads  = m_ledger_reads[p];
    end
    m_ledger_target = "";
  endfunction

  // Record the port's write and read counts against the expected ones.
  function bit check_bus_counts(string name, int unsigned exp_writes, int unsigned exp_reads,
                                string context_s);
    dtp_axi_port_history port = port_history(name);
    bit ok = record_bus_field(name, "writes", 64'(port.count(1'b0)), 64'(exp_writes), context_s);
    ok &= record_bus_field(name, "reads", 64'(port.count(1'b1)), 64'(exp_reads), context_s);
    return ok;
  endfunction

  // The test requires CHK-J2A-BUS-REQ on the ledger bridge's checker, so
  // the records of every port land there.
  function bit record_bus_field(string name, string field, bit [63:0] observed, bit [63:0] expected,
                                string context_s);
    string detail = $sformatf("%s target=%s field=%s", context_s, name, field);
    return target_evidence[m_ledger_target].expect_equal(
        DtpJ2aBusReqCheckId, observed, expected, detail
    );
  endfunction

  // Wait until the port behind `t` has completed more than `completed`
  // transactions of one direction (bounded); `done` reports whether it has.
  // The monitor publishes a write at its B and a read at its last R, so the
  // transaction's effect on the subordinate is final, and the passive
  // reference model and scoreboard receive the item in the same broadcast:
  // a one-shot fault or expected response armed after the wait cannot land
  // on it.
  task wait_port_count(dtp_j2a_target_t t, bit is_read, int unsigned completed, output bit done,
                       input int unsigned timeout_cycles = PortWaitCycles);
    dtp_axi_port_history port = port_history(t.name);
    for (int unsigned cycle = 0; cycle < timeout_cycles; cycle++) begin
      done = port.count(is_read) > completed;
      if (done) return;
      wait_sys_cycles(1);
    end
    done = port.count(is_read) > completed;
  endtask

  // CHK-J2A-BUS-REQ: the operation just issued completed exactly one
  // transaction, the one it requested. Against the stimulus: the port's
  // exact write and read counts, the address over the full bridge width, a
  // single beat, the AXI4 size, and for a write the strobes and the strobed
  // data, `data` and `wstrb` being the bus lanes the request drives. A no-op
  // unless this pass's ledger accounts `t`. +DTP_J2A_BUS_REQ_NEGATIVE
  // corrupts the expected address, so the run must fail.
  task expect_bus_request(dtp_j2a_target_t t, bit is_read, bit [63:0] addr, int unsigned size,
                          bit [63:0] data, bit [7:0] wstrb, string context_s);
    dtp_axi_port_history port;
    ocah_axi_item item;
    bit [63:0] exp_addr, lanes;
    bit done;
    if (m_ledger_target == "" || m_ledger_target != t.name) return;
    port = port_history(t.name);
    wait_port_count(t, is_read, is_read ? m_ledger_reads[t.name] : m_ledger_writes[t.name], done);
    if (is_read) m_ledger_reads[t.name]++;
    else m_ledger_writes[t.name]++;
    if (!check_bus_counts(t.name, m_ledger_writes[t.name], m_ledger_reads[t.name], context_s))
      return;
    void'(port.last(is_read, item));
    exp_addr = addr & bit_mask(t.addr_width);
    if (test_cfg.j2a_bus_req_negative) exp_addr ^= 64'h4;
    void'(record_bus_field(t.name, "address", item.address, exp_addr, context_s));
    void'(record_bus_field(t.name, "beats", 64'(item.beat_count()), 64'd1, context_s));
    if (t.protocol == OCAH_AXI_PROTO_AXI4)
      void'(record_bus_field(t.name, "size", 64'(item.size), 64'(size), context_s));
    if (!is_read) begin
      lanes = dtp_j2a_strobe_lanes(wstrb);
      void'(record_bus_field(
          t.name,
          "strobes",
          (item.strobes.size() > 0) ? 64'(item.strobes[0]) : '1,
          64'(wstrb),
          context_s
      ));
      void'(record_bus_field(t.name, "data", item.first_data() & lanes, data & lanes, context_s));
    end
  endtask

  // --- single-op TDR flow ------------------------------------------------
  task issue_single(dtp_j2a_target_t t, dtp_j2a_op_e op, bit [63:0] addr, bit [63:0] data = '0,
                    bit [7:0] wstrb = '0, int unsigned size = 0, bit use_default_size = 1'b1,
                    bit arm_intent = 1'b1);
    int unsigned eff_size = use_default_size ? t.default_size : size;
    ocah_axi_config cfg = target_cfgs[t.name];
    `uvm_info(get_type_name(), $sformatf(
                                   "%s SINGLE_OP %s addr=0x%0h data=0x%0h wstrb=0x%0h size=%0d",
                                   t.name, op.name(), addr, data, wstrb, eff_size), UVM_MEDIUM)
    // Stimulus-intent records: the address/data/wstrb programmed into the
    // TDR is the truth the observed bus transaction must match
    // (CHK-AXI-WADDR / CHK-AXI-WDATA / CHK-AXI-STRB / CHK-AXI-RADDR).
    // Gated ops never reach the bus: do not arm intents while the
    // target's disable is asserted (the no-activity evidence owns that
    // case; a dangling intent would false-fail at check_phase).
    if (op == DTP_J2A_OP_WRITE && target_enabled(t) && arm_intent)
      cfg.arm_expected_write(addr & bit_mask(t.addr_width), data & bit_mask(t.data_width), wstrb);
    if (op == DTP_J2A_OP_READ && target_enabled(t) && arm_intent)
      cfg.arm_expected_read(addr & bit_mask(t.addr_width));
    begin
      dtp_jtag2axi_single_op_seq req = dtp_jtag2axi_single_op_seq::type_id::create("single_op");
      req.target = t;
      req.op     = op;
      req.addr   = addr;
      req.data   = data;
      req.wstrb  = wstrb;
      req.size   = eff_size;
      run_jtag_op(req);
      m_single_capture = req.captured;
    end
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after SINGLE_OP request");
    note_tdr_access(single_op_len(t), $sformatf("%s single_op request", t.name));
  endtask

  // Load the target's SINGLE_OP instruction and shift `op` in as one raw TMS
  // walk that stops with the TAP in Update-DR and TCK idle. The bridge
  // latches the operation on the TCK edge that leaves Update-DR, so the
  // caller's next step is the edge that launches it. No intent is armed: the
  // caller discards the operation before it reaches the bus.
  task scan_single_to_update_dr(dtp_j2a_target_t t, dtp_j2a_op_e op, bit [63:0] addr,
                                bit [63:0] data, bit [7:0] wstrb, int unsigned size);
    bit dr[];
    bit tms[];
    bit tdi[];
    int unsigned len;
    dtp_j2a_pack_single_op(t, op, addr, data, wstrb, size, dr);
    len = dr.size();
    `uvm_info(get_type_name(),
              $sformatf(
                  "%s SINGLE_OP %s addr=0x%0h data=0x%0h wstrb=0x%0h size=%0d held in Update-DR",
                  t.name, op.name(), addr, data, wstrb, size), UVM_MEDIUM)
    load_ir(IrWidth'(t.single_op_instr));
    // Select-DR, Capture-DR, Shift-DR, the image LSB first with its last bit
    // moving to Exit1-DR, then Update-DR.
    tms = new[len + 4];
    tdi = new[len + 4];
    tms[0] = 1'b1;
    foreach (dr[i]) begin
      tms[3+i] = (i == len - 1);
      tdi[3+i] = dr[i];
    end
    tms[len+3] = 1'b1;
    raw_walk(tms, tdi);
    check_state(UPDATE_DR, "jtag2axi_scan_chk", "SINGLE_OP held in Update-DR");
    check_last_scan_length(1'b0, len, $sformatf("%s single_op held in Update-DR", t.name));
    note_scan(1'b0, len);
  endtask

  // One SINGLE_OP status capture (shifting zeros): the bridge's status and
  // data field as this poll saw them.
  task single_status_once(dtp_j2a_target_t t, output dtp_j2a_status_e status,
                          output bit [63:0] rdata);
    dtp_jtag2axi_single_status_seq st = dtp_jtag2axi_single_status_seq::type_id::create(
        "single_status"
    );
    st.target = t;
    run_jtag_op(st);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after SINGLE_OP status capture");
    check_last_scan_length(1'b0, single_op_len(t), $sformatf("%s status poll", t.name));
    note_scan(1'b0, single_op_len(t));
    status           = st.status;
    rdata            = st.rdata;
    m_single_capture = st.captured;
  endtask

  // The image the last issue_single() or single_status_once() captured.
  function void last_single_capture(output bit bits[]);
    bits = m_single_capture;
  endfunction

  // Poll SINGLE_OP until the bridge leaves BUSY_OR_FULL, within `max_polls`
  // captures, then land CHK-AXI-COMPLETION: a bridge stuck BUSY within the
  // poll bound fails (every call site expects a final, settled status). The
  // log counts the captures that read BUSY_OR_FULL first, usually none at
  // the bench's TCK ratio, since a scan outlasts the bus access.
  task poll_single(dtp_j2a_target_t t, output dtp_j2a_status_e status, output bit [63:0] rdata,
                   input string context_s = "single_op",
                   input int unsigned max_polls = DtpJ2aMaxStatusPolls);
    int unsigned busy_polls = 0;
    status = DTP_J2A_BUSY_OR_FULL;
    rdata  = '0;
    for (int unsigned poll = 0; poll < max_polls; poll++) begin
      single_status_once(t, status, rdata);
      if (status != DTP_J2A_BUSY_OR_FULL) break;
      busy_polls++;
    end
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP status=%s rdata=0x%0h busy_polls=%0d",
                                         t.name, status.name(), rdata, busy_polls), UVM_MEDIUM)
    void'(axi_evidence.expect_true(
        "CHK-AXI-COMPLETION",
        status != DTP_J2A_BUSY_OR_FULL,
        $sformatf(
            "%s target=%s polls=%0d", context_s, t.name, max_polls)
    ));
  endtask

  // `data` and `wstrb` are the bus lanes of the beat holding `addr`.
  task single_write(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, bit [7:0] wstrb,
                    output dtp_j2a_status_e status, input int unsigned size = 0,
                    input bit use_default_size = 1'b1, input string context_s = "single_write");
    bit [63:0] unused_rdata;
    issue_single(t, DTP_J2A_OP_WRITE, addr, data, wstrb, size, use_default_size);
    poll_single(t, status, unused_rdata, context_s);
    expect_bus_request(t, 1'b0, addr, use_default_size ? t.default_size : size, data, wstrb,
                       context_s);
  endtask

  task single_read(dtp_j2a_target_t t, bit [63:0] addr, output dtp_j2a_status_e status,
                   output bit [63:0] rdata, input int unsigned size = 0,
                   input bit use_default_size = 1'b1, input string context_s = "single_read");
    issue_single(t, DTP_J2A_OP_READ, addr, '0, '0, size, use_default_size);
    poll_single(t, status, rdata, context_s);
    expect_bus_request(t, 1'b1, addr, use_default_size ? t.default_size : size, '0, '0, context_s);
  endtask

  // CHK-J2A-FAULT-STATUS: the status a SINGLE_OP or SERIES_CTRL capture of
  // `t` returned; `detail` extends the context.
  function void check_status(dtp_j2a_target_t t, string context_s, dtp_j2a_status_e observed,
                             dtp_j2a_status_e expected, string detail = "");
    void'(axi_evidence.expect_equal(
        DtpJ2aFaultStatusCheckId,
        64'(observed),
        64'(expected),
        $sformatf(
            "%s target=%s%s%s", context_s, t.name, detail.len() ? " " : "", detail)
    ));
  endfunction

  // --- checked single operations (cocotb *_and_check parity) --------------
  // Write, poll to completion, and verify enabled byte lanes landed in the
  // responder memory. `data` and `wstrb` start at `addr`; the request
  // carries them on the bus lanes `addr` selects in the beat.
  task write_target_single_and_check(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                     output dtp_j2a_status_e status, input int unsigned size,
                                     input bit [7:0] wstrb = 8'hFF,
                                     input string context_s = "single_write");
    bit [63:0] observed;
    bit [63:0] masked = data & data_mask(size);
    bit [63:0] lanes = dtp_j2a_strobe_lanes(wstrb) & data_mask(size);
    int unsigned lane = int'(addr % t.beat_bytes);
    single_write(t, addr, masked << (8 * lane), 8'(wstrb << lane), status, size,
                 .use_default_size(1'b0), .context_s(context_s));
    check_status(t, {context_s, ".status"}, status, DTP_J2A_SUCCESS);
    observed = read_target_mem_int(t, addr, size);
    void'(axi_evidence.expect_equal(
        "CHK-AXI-WMEM",
        observed & lanes,
        masked & lanes,
        $sformatf(
            "%s target=%s addr=0x%0h wstrb=0x%02h source=intent", context_s, t.name, addr, wstrb)
    ));
  endtask

  // Read, poll to completion, and verify the returned data. The data field
  // returns the whole beat; the `size` bytes at `addr` sit on the lanes
  // `addr` selects.
  task read_target_single_and_check(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] expected,
                                    output dtp_j2a_status_e status, input int unsigned size,
                                    input string context_s = "single_read");
    bit [63:0] rdata;
    bit [63:0] observed;
    single_read(t, addr, status, rdata, size, .use_default_size(1'b0), .context_s(context_s));
    check_status(t, {context_s, ".status"}, status, DTP_J2A_SUCCESS);
    observed = (rdata >> (8 * (addr % t.beat_bytes))) & data_mask(size);
    check_returned_rdata(t, observed, expected & data_mask(size), $sformatf(
                         "%s.rdata addr=0x%0h size=%0d", context_s, addr, size));
  endtask

  // Write a seeded word at `addr` and another at the next beat, then read
  // `addr` back: the neighbouring write leaves its word in the SINGLE_OP
  // data field, which the read must replace with the word the bus returns.
  task write_neighbour_then_read(dtp_j2a_target_t t, bit [63:0] addr, string context_s,
                                 output dtp_j2a_status_e status);
    int unsigned size = t.default_size;
    bit [7:0] wstrb = full_wstrb(size);
    bit [63:0] data = rand_nonzero_data(t);
    bit [63:0] other = random_distinct_word(t, {data});
    `uvm_info(get_type_name(), $sformatf("%s %s: addr=0x%0h data=0x%0h neighbour=0x%0h", t.name,
                                         context_s, addr, data, other), UVM_LOW)
    write_target_single_and_check(t, addr, data, status, size, wstrb, {context_s, ".write"});
    check_target_memory(t, addr, data, size, {context_s, ".write.mem"});
    write_target_single_and_check(t, addr + t.beat_bytes, other, status, size, wstrb, {
                                  context_s, ".neighbour"});
    check_target_memory(t, addr + t.beat_bytes, other, size, {context_s, ".neighbour.mem"});
    read_target_single_and_check(t, addr, data, status, size, {context_s, ".read"});
  endtask

  // Error-path variants: complete and verify the requested status.
  task write_target_single_expect_status(
      dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, dtp_j2a_status_e expected_status,
      output dtp_j2a_status_e status, input int unsigned size, input bit [7:0] wstrb = 8'hFF,
      input string context_s = "single_write_error");
    single_write(t, addr, data & data_mask(size), wstrb, status, size, .use_default_size(1'b0),
                 .context_s(context_s));
    check_status(t, {context_s, ".status"}, status, expected_status);
  endtask

  task read_target_single_expect_status(
      dtp_j2a_target_t t, bit [63:0] addr, dtp_j2a_status_e expected_status,
      output dtp_j2a_status_e status, output bit [63:0] rdata, input int unsigned size,
      input string context_s = "single_read_error");
    single_read(t, addr, status, rdata, size, .use_default_size(1'b0), .context_s(context_s));
    check_status(t, {context_s, ".status"}, status, expected_status);
  endtask

  // CHK-J2A-ERR-RDATA: the SINGLE_OP rdata is the RDATA of the errored beat.
  // The responder answers the errored R beat with the seeded `errored` word,
  // and the bridge latches the beat's data together with its status, so the
  // capture returns that word: it equals `errored` and the beat the port's
  // monitor observed at `addr` with `resp`, and differs from the word
  // preloaded in the slot.
  function void check_error_rdata(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] rdata,
                                  ocah_axi_resp_e resp, bit [63:0] preload, bit [63:0] errored,
                                  int unsigned size, string context_s);
    ocah_axi_item item;
    bit [63:0] mask = data_mask(size);
    bit [63:0] observed = rdata & mask;
    bit [63:0] intent = errored & mask;
    bit [63:0] beat_addr, beat_word;
    string detail = $sformatf(
        "%s target=%s addr=0x%0h preload=0x%0h errored=0x%0h",
        context_s,
        t.name,
        addr,
        preload & mask,
        intent
    );
    if (!axi_evidence.expect_true(
            DtpJ2aErrRdataCheckId,
            port_history(
                t.name
            ).last(
                1'b1, item
            ),
            {
              detail, " field=beat_seen"
            }
        ))
      return;
    beat_addr = item.address - (item.address % t.beat_bytes);
    beat_word = item.first_data() & mask;
    void'(axi_evidence.expect_equal(
        DtpJ2aErrRdataCheckId, beat_addr, addr - (addr % t.beat_bytes), {detail, " field=beat_addr"}
    ));
    void'(axi_evidence.expect_equal(
        DtpJ2aErrRdataCheckId, 64'(item.worst_resp()), 64'(resp), {detail, " field=beat_resp"}
    ));
    void'(axi_evidence.expect_equal(
        DtpJ2aErrRdataCheckId, observed, beat_word, {detail, " field=rdata"}
    ));
    void'(axi_evidence.expect_equal(
        DtpJ2aErrRdataCheckId, beat_word, intent, {detail, " field=beat_intent"}
    ));
    void'(axi_evidence.expect_equal(
        DtpJ2aErrRdataCheckId, observed, intent, {detail, " field=rdata_intent"}
    ));
    void'(axi_evidence.expect_true(
        DtpJ2aErrRdataCheckId, observed != (preload & mask), {detail, " field=rdata_not_preload"}
    ));
  endfunction

  // Verify an OKAY access after an error/reset path to catch stuck state.
  task verify_target_recovery(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, bit is_read,
                              string context_s);
    dtp_j2a_status_e status;
    recover_target(t, addr, data, is_read, context_s, status);
  endtask

  // The recovery access with its settled status returned to the caller.
  task recover_target(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, bit is_read,
                      string context_s, output dtp_j2a_status_e status);
    int unsigned size = t.default_size;
    if (is_read) begin
      write_target_mem_int(t, addr, data, size);
      read_target_single_and_check(t, addr, data, status, size, {context_s, ".recover_read"});
    end else begin
      write_target_single_and_check(t, addr, data, status, size, full_wstrb(size), {
                                    context_s, ".recover_write"});
      // CHK-AXI-WMEM: the responder memory against the stimulus intent.
      check_target_memory(t, addr, data, size, {context_s, ".recover_write"});
    end
  endtask

  // --- series TDR flow -----------------------------------------------------
  // Program SERIES_CTRL (WRITE/READ arms a stream; NOP+reset clears it).
  task series_ctrl_op(dtp_j2a_target_t t, dtp_j2a_op_e op, bit [63:0] addr, int unsigned size,
                      int unsigned pipeline_depth = 0, bit series_reset = 1'b0);
    dtp_jtag2axi_series_ctrl_seq ctrl = dtp_jtag2axi_series_ctrl_seq::type_id::create(
        "series_ctrl"
    );
    `uvm_info(get_type_name(),
              $sformatf("%s SERIES_CTRL %s addr=0x%0h size=%0d pl_depth=%0d reset=%0d", t.name,
                        op.name(), addr, size, pipeline_depth, series_reset), UVM_MEDIUM)
    ctrl.target         = t;
    ctrl.op             = op;
    ctrl.addr           = addr;
    ctrl.size           = size;
    ctrl.pipeline_depth = pipeline_depth;
    ctrl.series_reset   = series_reset;
    run_jtag_op(ctrl);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after SERIES_CTRL scan");
    note_tdr_access(series_ctrl_len(t), $sformatf("%s series_ctrl", t.name));
  endtask

  // Capture and decode SERIES_CTRL (shifting a NOP image), landing
  // CHK-AXI-COMPLETION on the settled status.
  task read_series_ctrl(dtp_j2a_target_t t, input int unsigned size, output bit series_reset,
                        output bit [63:0] addr_after, output int unsigned pipeline_depth,
                        output int unsigned size_rd, output dtp_j2a_status_e status);
    dtp_jtag2axi_series_ctrl_seq ctrl = dtp_jtag2axi_series_ctrl_seq::type_id::create(
        "series_ctrl_read"
    );
    ctrl.target = t;
    ctrl.op     = DTP_J2A_OP_NOP;
    ctrl.addr   = '0;
    ctrl.size   = size;
    run_jtag_op(ctrl);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after SERIES_CTRL capture");
    note_tdr_access(series_ctrl_len(t), $sformatf("%s series_ctrl capture", t.name));
    dtp_j2a_unpack_series_ctrl(t, ctrl.captured, series_reset, addr_after, pipeline_depth, size_rd,
                               status);
    `uvm_info(get_type_name(),
              $sformatf("%s SERIES_CTRL reset=%0d addr=0x%0h pl_depth=%0d size=%0d status=%s",
                        t.name, series_reset, addr_after, pipeline_depth, size_rd, status.name()),
              UVM_MEDIUM)
    // Every series stream ends with this status capture; a bridge stuck
    // BUSY fails here (call sites expect a settled status, never BUSY).
    void'(axi_evidence.expect_true(
        "CHK-AXI-COMPLETION",
        status != DTP_J2A_BUSY_OR_FULL,
        $sformatf(
            "series_ctrl target=%s", t.name)
    ));
  endtask

  // CHK-J2A-SERIES-ADDR (`<context>.addr_after`): the SERIES_CTRL capture
  // holds `expected_addr`; returns the captured status.
  task check_series_addr(dtp_j2a_target_t t, bit [63:0] expected_addr, int unsigned size,
                         string context_s, output dtp_j2a_status_e status);
    bit sr_reset;
    bit [63:0] addr_after;
    int unsigned sr_pl, sr_size;
    bit [63:0] expected = expected_addr & bit_mask(t.addr_width);
    read_series_ctrl(t, size, sr_reset, addr_after, sr_pl, sr_size, status);
    void'(axi_evidence.expect_equal(
        DtpJ2aSeriesAddrCheckId,
        addr_after,
        expected,
        $sformatf(
            "%s.addr_after target=%s", context_s, t.name)
    ));
  endtask

  // One series-data shift (dtp_jtag2axi_series_data_seq): payload-sized
  // TDR, optional MSB increment bit (with-status mode), idle TCK cycles
  // for the op to launch.
  protected task series_data_shift(dtp_j2a_target_t t, dtp_jtag_instr_e instr, bit [63:0] data,
                                   int unsigned size,
                                   input int increment,  // <0: no increment/status bit in the TDR
                                   output bit [63:0] result);
    int unsigned payload_bits = 8 * size_bytes(dtp_j2a_axsize(t, size));
    int unsigned width = payload_bits + ((increment >= 0) ? 1 : 0);
    dtp_jtag2axi_series_data_seq shift =
            dtp_jtag2axi_series_data_seq::type_id::create("series_data");
    shift.target    = t;
    shift.instr     = instr;
    shift.data      = data;
    shift.size      = size;
    shift.increment = increment;
    run_jtag_op(shift);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after SERIES_DATA shift");
    note_tdr_access(width, $sformatf("%s series_data", t.name));
    result = shift.captured;
  endtask

  task series_data_incr(dtp_j2a_target_t t, bit [63:0] data, int unsigned size);
    bit [63:0] unused;
    series_data_shift(t, t.series_data_incr_instr, data, size, -1, unused);
  endtask

  task series_data_no_incr(dtp_j2a_target_t t, bit [63:0] data, int unsigned size);
    bit [63:0] unused;
    series_data_shift(t, t.series_data_no_incr_instr, data, size, -1, unused);
  endtask

  // With-status shift: the payload and the status bit above it, which sits
  // past bit 63 for a 64-bit bridge and so comes from the operation's own
  // capture rather than the 64-bit result word.
  task series_data_with_status(dtp_j2a_target_t t, bit [63:0] data, int unsigned size,
                               bit increment, output bit [63:0] rdata, output bit status_bit);
    int unsigned payload_bits = 8 * size_bytes(dtp_j2a_axsize(t, size));
    dtp_jtag2axi_series_data_seq shift =
            dtp_jtag2axi_series_data_seq::type_id::create("series_data_status");
    shift.target    = t;
    shift.instr     = t.series_data_with_status_instr;
    shift.data      = data;
    shift.size      = size;
    shift.increment = int'(increment);
    run_jtag_op(shift);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after SERIES_DATA shift");
    note_tdr_access(payload_bits + 1, $sformatf("%s series_data", t.name));
    rdata      = shift.captured & data_mask(dtp_j2a_axsize(t, size));
    status_bit = shift.captured_status;
  endtask

  // --- plain series beats ----------------------------------------------------
  // One SERIES_DATA write beat to `addr`, judged once the port completes it:
  // the beat lands on the lanes `addr` and `size` select, the ledger judges
  // the request (CHK-J2A-BUS-REQ), and the subordinate must hold `data` at
  // `addr` (CHK-AXI-WMEM).
  task series_write_beat(dtp_j2a_target_t t, bit [63:0] data, bit [63:0] addr, int unsigned size,
                         bit increment, string context_s);
    int unsigned eff = dtp_j2a_axsize(t, size);
    bit [63:0] payload = data & data_mask(eff);
    int unsigned completed = port_history(t.name).count(1'b0);
    int unsigned aw0, w0, ar0;
    bit done;
    sample_activity(t, aw0, w0, ar0);
    if (increment) series_data_incr(t, payload, size);
    else series_data_no_incr(t, payload, size);
    wait_for_target_activity(t, aw0, w0, ar0, 1'b0, {context_s, ".axi"});
    wait_port_count(t, 1'b0, completed, done);
    if (!done) record_wait_timeout(t, PortWaitCycles, {context_s, ".write_completion"});
    expect_bus_request(t, 1'b0, addr, eff, dtp_j2a_series_wdata(t, payload, addr, eff),
                       dtp_j2a_series_wstrb(t, addr, eff), context_s);
    check_target_memory(t, addr, payload, eff, {context_s, ".mem"});
  endtask

  // Read `addr` through SERIES_CTRL(READ) and two SERIES_DATA shifts,
  // returning the captured payload: the first shift launches the read, and
  // at pipeline depth 0 the bridge launches no second one; once the port
  // completes the read (CHK-J2A-BUS-REQ), the second shift captures its data.
  task series_read_beat(dtp_j2a_target_t t, bit [63:0] addr, int unsigned size, bit increment,
                        string context_s, output bit [63:0] observed);
    dtp_jtag_instr_e instr = increment ? t.series_data_incr_instr : t.series_data_no_incr_instr;
    int unsigned completed;
    int unsigned aw0, w0, ar0;
    bit [63:0] raw;
    bit done;
    series_ctrl_op(t, DTP_J2A_OP_READ, addr, size);
    completed = port_history(t.name).count(1'b1);
    sample_activity(t, aw0, w0, ar0);
    series_data_shift(t, instr, '0, size, -1, raw);
    wait_for_target_activity(t, aw0, w0, ar0, 1'b1, {context_s, ".axi"});
    wait_port_count(t, 1'b1, completed, done);
    if (!done) record_wait_timeout(t, PortWaitCycles, {context_s, ".read_completion"});
    expect_bus_request(t, 1'b1, addr, dtp_j2a_axsize(t, size), '0, '0, context_s);
    series_data_shift(t, instr, '0, size, -1, raw);
    observed = raw & data_mask(dtp_j2a_axsize(t, size));
  endtask

  // Read the fixed series address `addr` `beats` times, `status` returning
  // the SERIES_CTRL status after them: the first read returns `last_word`,
  // the last word the stream wrote, and before every later read the slot
  // takes a fresh word, so each capture is its own. The series address
  // stays at `addr`.
  task series_reread_fixed(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] last_word,
                           int unsigned beats, string context_s, output dtp_j2a_status_e status);
    int unsigned size = t.default_size;
    bit [63:0] expected = last_word;
    bit [63:0] obs, addr_after;
    bit series_reset;
    int unsigned pl_depth, size_rd;
    for (int unsigned idx = 1; idx <= beats; idx++) begin
      if (idx > 1) begin
        expected = random_distinct_word(t, {expected});
        write_target_mem_int(t, addr, expected, size);
      end
      series_read_beat(t, addr, size, 1'b0, $sformatf("%s.read#%0d", context_s, idx), obs);
      log_iteration(idx, beats, $sformatf("series no-incr read addr=0x%0h obs=0x%0h", addr, obs));
      check_returned_rdata(t, obs, expected, $sformatf("%s.rdata#%0d", context_s, idx));
    end
    read_series_ctrl(t, size, series_reset, addr_after, pl_depth, size_rd, status);
    void'(axi_evidence.expect_equal(
        DtpJ2aSeriesAddrCheckId,
        addr_after,
        addr & bit_mask(
            t.addr_width
        ),
        $sformatf(
            "%s.addr_after target=%s", context_s, t.name)
    ));
  endtask

  // --- shared scenario flows --------------------------------------------
  // TAP reset into Run-Test/Idle (scans start from RTI).
  task reset_to_rti();
    tap_reset();
    step(1'b0);
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after TLR->RTI step");
  endtask

  // Series beats per pass: at least 2, at most 6, tracking +DTP_RANDOM_COUNT.
  function int unsigned series_beats();
    if (random_count < 2) return 2;
    if (random_count > 6) return 6;
    return random_count;
  endfunction

  // A seeded word of the target's data width.
  function bit [63:0] rand_data(dtp_j2a_target_t t);
    return mask_target_data(t, {$urandom(), $urandom()});
  endfunction

  // SERIES_CTRL + SERIES_DATA_INCR writes from a seeded base, then the
  // capture after them: OKAY at the address past the last beat.
  task run_series_write_incr(dtp_j2a_target_t t);
    int unsigned size   = t.default_size;
    int unsigned stride = t.beat_bytes;
    int unsigned beats  = series_beats();
    bit [63:0]   base   = random_series_base(t, beats * stride, 1'b1);
    `uvm_info(get_type_name(), $sformatf("%s SERIES_DATA_INCR Write Sweep: base=0x%0h beats=%0d",
                                         t.name, base, beats), UVM_LOW)
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] addr = base + (idx * stride);
      bit [63:0] data = rand_data(t) & data_mask(size);
      log_iteration(idx + 1, beats, $sformatf("series incr write addr=0x%0h data=0x%0h", addr, data
                    ));
      series_write_beat(t, data, addr, size, 1'b1, $sformatf("series_incr#%0d", idx));
      operation_count++;
    end
    check_series_addr(t, base + beats * stride, size, "series_incr", status);
    check_status(t, "series_incr.status", status, DTP_J2A_SUCCESS);
  endtask

  // A fixed-address SERIES_DATA_NO_INCR write stream; the series address
  // stays put.
  task run_series_write_no_incr(dtp_j2a_target_t t);
    int unsigned size  = t.default_size;
    int unsigned beats = series_beats();
    bit [63:0]   addr  = random_series_base(t, t.beat_bytes);
    `uvm_info(get_type_name(), $sformatf("%s SERIES_DATA_NO_INCR Write Sweep: addr=0x%0h beats=%0d",
                                         t.name, addr, beats), UVM_LOW)
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] data = rand_data(t) & data_mask(size);
      log_iteration(idx + 1, beats, $sformatf(
                    "series no-incr write addr=0x%0h data=0x%0h", addr, data));
      series_write_beat(t, data, addr, size, 1'b0, $sformatf("series_no_incr#%0d", idx));
      operation_count++;
    end
    check_series_addr(t, addr, size, "series_no_incr", status);
    check_status(t, "series_no_incr.status", status, DTP_J2A_SUCCESS);
  endtask

  // WITH_ERROR_STATUS write stream with one armed fault beat, then a
  // recovery write outside it.
  task run_series_write_incr_with_error(dtp_j2a_target_t t);
    dtp_j2a_series_status_plan_t plan = plan_series_status(t);
    bit [63:0] words[] = new[DtpJ2aSeriesStatusBeats];
    arm_series_status_fault(t, plan, 1'b0);
    foreach (words[i]) words[i] = rand_data(t) & data_mask(plan.size);
    log_step("1", $sformatf(
             "%s WITH_ERROR_STATUS write stream: base=0x%0h fault_beat=%0d resp=%s",
             t.name,
             plan.base,
             plan.fault_idx,
             plan.expected.name()
             ));
    run_series_status_write(t, plan, words, "series_status");
    log_step("2", "Recover with a legal single write outside the stream");
    recover_target(t, series_status_recovery_addr(plan), rand_data(t), 1'b0, "series_status",
                   status);
    operation_count += DtpJ2aSeriesStatusBeats + 1;
    emit_series_status_nonvacuity("series_write_incr_with_error", t, plan, operation_count);
  endtask

  // An incrementing series write leg, then a per-beat read-back through
  // SERIES_CTRL(READ): each read returns the word its beat wrote, and the
  // last primed read leaves the series address one stride past it. A
  // `size` above the bus width moves full bus-width beats.
  task run_series_write_read_incr(dtp_j2a_target_t t, int unsigned size, string label);
    int unsigned eff    = dtp_j2a_axsize(t, size);
    int unsigned stride = t.beat_bytes;
    int unsigned beats  = series_beats();
    bit [63:0]   base   = random_series_base(t, beats * stride, 1'b1);
    bit [63:0]   expected_q[$];
    bit [63:0] obs, addr;
    log_step(
        "1", $sformatf(
        "Write %s incrementing series: base=0x%0h beats=%0d size=%0d", t.name, base, beats, size));
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] data = rand_data(t) & data_mask(eff);
      expected_q.push_back(data);
      log_iteration(idx + 1, beats, $sformatf(
                    "series incr write addr=0x%0h data=0x%0h", base + idx * stride, data));
      series_write_beat(t, data, base + idx * stride, size, 1'b1, $sformatf(
                        "%s.write#%0d", label, idx));
    end
    log_step("2", "Read the incrementing series back");
    foreach (expected_q[idx]) begin
      addr = base + idx * stride;
      series_read_beat(t, addr, size, 1'b1, $sformatf("%s.read#%0d", label, idx), obs);
      log_iteration(idx + 1, beats, $sformatf("series incr read addr=0x%0h obs=0x%0h", addr, obs));
      check_returned_rdata(t, obs, expected_q[idx], $sformatf(
                           "%s.rdata#%0d addr=0x%0h", label, idx, addr));
      operation_count++;
    end
    check_series_addr(t, addr + stride, size, {label, ".final"}, status);
    check_status(t, {label, ".final"}, status, DTP_J2A_SUCCESS);
  endtask

  // A fixed-address series write leg, then re-reads of the address: the
  // first returns the last word written.
  task run_series_write_read_no_incr(dtp_j2a_target_t t);
    int unsigned size  = t.default_size;
    int unsigned beats = series_beats();
    bit [63:0]   addr  = random_series_base(t, t.beat_bytes);
    bit [63:0]   values_q[$];
    for (int unsigned idx = 0; idx < beats; idx++)
      values_q.push_back(rand_data(t) & data_mask(size));
    log_step("1", $sformatf(
             "Write %s fixed-address series: addr=0x%0h beats=%0d", t.name, addr, beats));
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    foreach (values_q[idx]) begin
      log_iteration(idx + 1, beats, $sformatf(
                    "series no-incr write addr=0x%0h data=0x%0h", addr, values_q[idx]));
      series_write_beat(t, values_q[idx], addr, size, 1'b0, $sformatf(
                        "series_wr_rd_no_incr.write#%0d", idx + 1));
    end
    log_step("2", "Re-read the fixed address");
    series_reread_fixed(t, addr, values_q[$], beats, "series_wr_rd_no_incr", status);
    operation_count += beats;
    check_status(t, "series_wr_rd_no_incr.final", status, DTP_J2A_SUCCESS);
  endtask

  // WITH_ERROR_STATUS on both legs: a clean write stream, then a read
  // stream with one armed fault beat, then a recovery read outside them.
  task run_series_write_read_incr_with_error(dtp_j2a_target_t t);
    dtp_j2a_series_status_plan_t plan = plan_series_status(t);
    bit [63:0] words[] = new[DtpJ2aSeriesStatusBeats];
    bit [63:0] expected[];
    foreach (words[i]) words[i] = rand_data(t) & data_mask(plan.size);
    log_step("1", $sformatf(
             "Write the %s with-status series without a fault: base=0x%0h", t.name, plan.base));
    run_series_status_write(t, plan, words, "series_wr_rd_status.write");
    dtp_j2a_series_status_final_words(plan, words, expected);
    arm_series_status_fault(t, plan, 1'b1);
    log_step("2", $sformatf(
             "Read the with-status series with a fault on beat %0d (resp=%s)",
             plan.fault_idx,
             plan.expected.name()
             ));
    run_series_status_read(t, plan, expected, "series_wr_rd_status.read");
    log_step("3", "Recover with a legal single read outside the stream");
    recover_target(t, series_status_recovery_addr(plan), rand_data(t), 1'b1, "series_wr_rd_status",
                   status);
    operation_count += 2 * DtpJ2aSeriesStatusBeats + 1;
    emit_series_status_nonvacuity("series_write_read_incr_with_error", t, plan, operation_count);
  endtask

  // CHK-AXI-NONVAC: the operation just issued moved the AW (write) or AR
  // (read) request counter of the port behind `t` past `before_count`.
  function void expect_request_activity(dtp_j2a_target_t t, bit is_read, int unsigned before_count,
                                        string context_s);
    int unsigned aw, w, ar;
    sample_activity(t, aw, w, ar);
    void'(axi_evidence.expect_true(
        "CHK-AXI-NONVAC",
        (is_read ? ar : aw) > before_count,
        $sformatf(
            "%s target=%s %s_before=%0d %s_after=%0d",
            context_s,
            t.name,
            is_read ? "ar" : "aw",
            before_count,
            is_read ? "ar" : "aw",
            is_read ? ar : aw)
    ));
  endfunction

  // CHK-AXI-GATE-EXACT across a gate pass: from before the gated attempt to
  // after the sanctioned restore, the responder completed exactly the
  // restore (+1 in the restore's direction, none in the other).
  function void expect_gate_exact(dtp_j2a_target_t t, bit is_read, int unsigned wr_bursts_gate,
                                  int unsigned rd_bursts_gate, string context_s);
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-EXACT",
        write_bursts_now(
            t
        ),
        wr_bursts_gate + (is_read ? 0 : 1),
        $sformatf(
            "%s target=%s source=responder_burst_counts writes sanctioned=%s",
            context_s,
            t.name,
            is_read ? "none" : "restore_write(+1)")
    ));
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-EXACT",
        read_bursts_now(
            t
        ),
        rd_bursts_gate + (is_read ? 1 : 0),
        $sformatf(
            "%s target=%s source=responder_burst_counts reads sanctioned=%s",
            context_s,
            t.name,
            is_read ? "restore_read(+1)" : "none")
    ));
  endfunction

  // The bridge's lifecycle disable gates writes. A baseline write, then two
  // gate passes: the gated SINGLE_OP write raises no request, leaves a
  // seeded sentinel at its address while gated and after the release,
  // latches nothing (CHK-J2A-GATE-TDR), and only the sanctioned restore
  // write completes across the pass. Then a gated series with beats queued
  // behind one on the bus, and a recovery write.
  task run_write_security_gating(dtp_j2a_target_t t, bit [63:0] addr);
    int unsigned size = t.default_size;
    bit [7:0] wstrb = full_wstrb(size);
    bit [63:0] data = rand_data(t) & data_mask(size);
    int unsigned aw0, w0, ar0;
    int unsigned gate_aw, gate_w, gate_ar;
    int unsigned now_aw, now_w, now_ar;
    int unsigned wr_bursts_start = write_bursts_now(t);
    `uvm_info(get_type_name(), $sformatf("%s Write Security Gating", t.name), UVM_LOW)
    log_step("1", "Establish baseline write and AXI activity");
    sample_activity(t, aw0, w0, ar0);
    write_target_single_and_check(t, addr, data, status, size, wstrb, "gate.baseline");
    expect_request_activity(t, 1'b0, aw0, "gate.baseline");
    // Two assert/release passes of the one direct disable prove the gate
    // is repeatable, not a one-shot POR effect.
    for (int unsigned idx = 1; idx <= 2; idx++) begin
      bit [63:0] gate_addr = addr + idx * t.beat_bytes;
      bit [63:0] gate_data = (data ^ 64'(idx)) & data_mask(size);
      bit [63:0] sentinel = random_distinct_word(t, {gate_data}) & data_mask(size);
      int unsigned wr_bursts_gate, rd_bursts_gate;
      bit reference[], gated[], post[];
      string ctx = $sformatf("gate.pass%0d", idx);
      log_step($sformatf("%0d", idx + 1), $sformatf(
               "Gate %s write with its lifecycle disable (pass %0d)", t.name, idx));
      gate_image_reference(t, gate_addr, reference);
      gate_target(t);
      write_target_mem_int(t, gate_addr, sentinel, size);
      // Snapshot before the gated attempt: pulse counters for the
      // no-activity windows, responder burst counts for the exact-delta
      // proof across the whole gate/restore span.
      sample_activity(t, gate_aw, gate_w, gate_ar);
      wr_bursts_gate = write_bursts_now(t);
      rd_bursts_gate = read_bursts_now(t);
      // issue_single arms no intent while the target's disable is asserted.
      issue_single(t, DTP_J2A_OP_WRITE, gate_addr, gate_data, wstrb, size, .use_default_size(1'b0));
      last_single_capture(gated);
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, {
                                  ctx, ".no_axi"});
      check_target_memory(t, gate_addr, sentinel, size, {ctx, ".sentinel"});
      capture_single(t, post);
      check_gated_tdr(t, reference, gate_addr, wstrb, size, gated, post, ctx);
      // The counters stay flat after the release until sanctioned traffic,
      // and the sentinel survives it: a delayed replay would overwrite it.
      enable_all_debug();
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, {
                                  ctx, ".post_release"});
      check_target_memory(t, gate_addr, sentinel, size, {ctx, ".sentinel_post_release"});
      sample_activity(t, aw0, w0, ar0);
      write_target_single_and_check(t, addr + idx * 64'h40, (data ^ (64'(idx) << 8)) & data_mask(
                                    size), status, size, wstrb, {ctx, ".restore"});
      expect_request_activity(t, 1'b0, aw0, {ctx, ".restore"});
      expect_gate_exact(t, 1'b0, wr_bursts_gate, rd_bursts_gate, ctx);
      operation_count++;
    end
    log_step("4", $sformatf("Gate %s write with series beats queued behind one on the bus", t.name
             ));
    run_queued_write_drop(t, addr + 64'h100, "gate.queued_drop");
    recover_target(t, addr + 64'h140, (data ^ 64'hA5A5) & data_mask(size), 1'b0, "gate.queued_drop",
                   status);
    emit_nonvacuity_evidence(t, (write_bursts_now(t) - wr_bursts_start) >= 3, $sformatf(
                             "gate.writes source=responder_burst_counts write_bursts=%0d sanctioned>=3 (baseline+2 restores)",
                             write_bursts_now(
                                 t
                             ) - wr_bursts_start
                             ));
  endtask

  // The bridge's lifecycle disable gates reads. A baseline read, then two
  // gate passes: the gated SINGLE_OP read raises no request while gated or
  // after the release, latches nothing (CHK-J2A-GATE-TDR), and only the
  // sanctioned restore read completes across the pass.
  task run_read_security_gating(dtp_j2a_target_t t, bit [63:0] addr);
    int unsigned size = t.default_size;
    bit [63:0] data = rand_data(t) & data_mask(size);
    int unsigned aw0, w0, ar0;
    int unsigned gate_aw, gate_w, gate_ar;
    int unsigned now_aw, now_w, now_ar;
    int unsigned rd_bursts_start = read_bursts_now(t);
    write_target_mem_int(t, addr, data, size);
    log_step("1", "Establish baseline read and AXI activity");
    sample_activity(t, aw0, w0, ar0);
    read_target_single_and_check(t, addr, data, status, size, "read_gate.baseline");
    expect_request_activity(t, 1'b1, ar0, "read_gate.baseline");
    // Two assert/release passes of the one direct disable prove the gate
    // is repeatable, not a one-shot POR effect.
    for (int unsigned idx = 1; idx <= 2; idx++) begin
      bit [63:0] gate_addr = addr + idx * t.beat_bytes;
      int unsigned wr_bursts_gate, rd_bursts_gate;
      bit reference[], gated[], post[];
      string ctx = $sformatf("read_gate.pass%0d", idx);
      log_step($sformatf("%0d", idx + 1), $sformatf(
               "Gate %s read with its lifecycle disable (pass %0d)", t.name, idx));
      gate_image_reference(t, gate_addr, reference);
      gate_target(t);
      // Snapshot before the gated attempt so a request leaked at shift
      // time is caught.
      sample_activity(t, gate_aw, gate_w, gate_ar);
      rd_bursts_gate = read_bursts_now(t);
      wr_bursts_gate = write_bursts_now(t);
      issue_single(t, DTP_J2A_OP_READ, gate_addr);
      last_single_capture(gated);
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, {
                                  ctx, " window=gated_attempt+8cyc"});
      capture_single(t, post);
      check_gated_tdr(t, reference, gate_addr, 8'h00, size, gated, post, ctx);
      // A bridge that queued the gated request and replays it after the
      // release is the leak this window catches.
      enable_all_debug();
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, {
                                  ctx, ".post_reenable"});
      read_target_single_and_check(t, addr, data, status, size, {ctx, ".restore"});
      expect_request_activity(t, 1'b1, gate_ar, {ctx, ".restore"});
      expect_gate_exact(t, 1'b1, wr_bursts_gate, rd_bursts_gate, ctx);
      operation_count++;
    end
    emit_nonvacuity_evidence(t, (read_bursts_now(t) - rd_bursts_start) >= 3, $sformatf(
                             "read_gate.reads source=responder_burst_counts read_bursts=%0d sanctioned>=3 (baseline+2 restores)",
                             read_bursts_now(
                                 t
                             ) - rd_bursts_start
                             ));
  endtask

  // --- lifecycle debug disables (must be cleared before JTAG2AXI ops) ----
  // Assert exactly the disable that gates this target (all others clear).
  task gate_target(dtp_j2a_target_t t);
    set_dbg_disable(dtp_dbg_disable_only(t.dbg_path));
  endtask

  function bit target_enabled(dtp_j2a_target_t t);
    return !dtp_dbg_path_disabled(tb_vif.dbg_disable, t.dbg_path);
  endfunction

  // --- gated SINGLE_OP evidence ----------------------------------------------
  // The SINGLE_OP image a NOP capture returns while the bridge is enabled.
  // Every bridge shifts each DR scan of the TAP and latches it at Update-DR
  // unless disabled, whichever register the scan selects. The first NOP scan
  // of the image loads it into the update latch, and the second one's
  // capture is the image the gated captures repeat. A flow that takes
  // several bridges' references in turn keeps the zero image, since each
  // reference scan also loads the other bridges' latches.
  // The capture's size, wstrb and address fields must hold the shifted
  // image (CHK-J2A-GATE-TDR field=reference_vs_image) before the gated
  // captures are judged against it.
  task gate_reference(dtp_j2a_target_t t, output bit reference[], input bit [63:0] img_addr = '0,
                      input bit [63:0] img_data = '0, input bit [7:0] img_wstrb = '0,
                      input int unsigned img_size = 0);
    bit ref_q[$];
    bit image[];
    string detail;
    repeat (2)
      issue_single(t, DTP_J2A_OP_NOP, img_addr, img_data, img_wstrb, img_size,
                   .use_default_size(1'b0));
    last_single_capture(reference);
    ref_q = reference;
    dtp_j2a_pack_single_op(t, DTP_J2A_OP_NOP, img_addr, img_data, img_wstrb, img_size, image);
    detail = $sformatf(
        "gate_reference image=0x%s reference=0x%s target=%s",
        dtp_bits_hex(
            image
        ),
        dtp_bits_hex(
            reference
        ),
        t.name
    );
    `uvm_info(get_type_name(), detail, UVM_MEDIUM)
    void'(axi_evidence.expect_equal(
        DtpJ2aGateTdrCheckId,
        dtp_bits_field(
            ref_q, 2, t.size_bits
        ),
        64'(img_size) & bit_mask(
            t.size_bits
        ),
        {
          detail, " field=reference_vs_image.size"
        }
    ));
    void'(axi_evidence.expect_equal(
        DtpJ2aGateTdrCheckId,
        dtp_bits_field(
            ref_q, 2 + t.size_bits, t.wstrb_bits
        ),
        64'(img_wstrb) & bit_mask(
            t.wstrb_bits
        ),
        {
          detail, " field=reference_vs_image.wstrb"
        }
    ));
    void'(axi_evidence.expect_equal(
        DtpJ2aGateTdrCheckId,
        dtp_bits_field(
            ref_q, 2 + t.size_bits + t.wstrb_bits + t.data_width, t.addr_width
        ),
        img_addr & bit_mask(
            t.addr_width
        ),
        {
          detail, " field=reference_vs_image.addr"
        }
    ));
  endtask

  // gate_reference() over a seeded NOP image, for a flow that gates one
  // bridge: size and data are nonzero, the strobe is neither zero nor the
  // full mask, and the address differs from the gated request's `req_addr`
  // within the address field.
  task gate_image_reference(dtp_j2a_target_t t, bit [63:0] req_addr, output bit reference[]);
    bit [63:0] data = rand_nonzero_data(t);
    bit [7:0] wstrb = 8'($urandom_range((1 << t.wstrb_bits) - 2, 1));
    int unsigned size = $urandom_range((1 << t.size_bits) - 1, 1);
    bit [63:0] flip;
    do flip = {$urandom(), $urandom()} & bit_mask(t.addr_width); while (flip == '0);
    gate_reference(t, reference, req_addr ^ flip, data, wstrb, size);
  endtask

  // One SINGLE_OP status capture, returning the whole image.
  task capture_single(dtp_j2a_target_t t, output bit bits[]);
    dtp_j2a_status_e status;
    bit [63:0] rdata;
    single_status_once(t, status, rdata);
    bits = m_single_capture;
  endtask

  // CHK-J2A-GATE-TDR: a gated SINGLE_OP register stays selected and latches
  // nothing. The gated request's own capture and a NOP capture after its
  // Update-DR equal `reference` in every field. A register that left the
  // scan path returns the shifted TDI instead, and one that latched the
  // request returns its fields afterwards; the request must differ from the
  // reference in a field the capture reads from the update latch (size,
  // wstrb, address), so a latching bridge cannot pass.
  function void check_gated_tdr(dtp_j2a_target_t t, bit reference[], bit [63:0] req_addr,
                                bit [7:0] req_wstrb, int unsigned req_size, bit request_capture[],
                                bit post_capture[], string context_s);
    string names[5] = '{"op", "size", "wstrb", "data", "addr"};
    int unsigned offsets[5];
    int unsigned widths[5];
    bit [63:0] expected[5];
    bit ref_q[$];
    bit distinct;
    string detail;
    offsets = '{
        0,
        2,
        2 + t.size_bits,
        2 + t.size_bits + t.wstrb_bits,
        2 + t.size_bits + t.wstrb_bits + t.data_width
    };
    widths = '{2, t.size_bits, t.wstrb_bits, t.data_width, t.addr_width};
    ref_q = reference;
    foreach (names[i]) expected[i] = dtp_bits_field(ref_q, offsets[i], widths[i]);
    distinct = ((64'(req_size) & bit_mask(t.size_bits)) != expected[1])
        || ((64'(req_wstrb) & bit_mask(t.wstrb_bits)) != expected[2])
        || ((req_addr & bit_mask(t.addr_width)) != expected[4]);
    detail = $sformatf("%s target=%s", context_s, t.name);
    void'(axi_evidence.expect_true(
        DtpJ2aGateTdrCheckId, distinct, {detail, " field=request_differs"}
    ));
    for (int unsigned c = 0; c < 2; c++) begin
      string label = (c == 0) ? "request_capture" : "post_update_capture";
      bit cap_q[$];
      if (c == 0) cap_q = request_capture;
      else cap_q = post_capture;
      foreach (names[i]) begin
        bit [63:0] observed = dtp_bits_field(cap_q, offsets[i], widths[i]);
        void'(axi_evidence.expect_equal(
            DtpJ2aGateTdrCheckId, observed, expected[i], {detail, " ", label, " field=", names[i]}
        ));
      end
    end
  endfunction

  // The disable drops the bridge's buffered requests. A fixed-address series
  // write with pl_depth at the bridge's write depth puts its first beat on
  // the bus, where the responder holds AW (it accepts W only after AW), and
  // queues the next beats in the bridge. The disable lands while they wait.
  // The beat on the bus completes, since an AXI master cannot withdraw a
  // valid request, and no queued beat reaches the bus, while gated or after
  // the release: exactly one write completes and the slot keeps the first
  // beat's word.
  task run_queued_write_drop(dtp_j2a_target_t t, bit [63:0] addr, string context_s);
    int unsigned size = t.default_size;
    int unsigned queued = $urandom_range(t.wr_pl_depth + 1, 1);
    int unsigned scan_tck = single_op_len(t) + 32;
    int unsigned wr_bursts0 = write_bursts_now(t);
    int unsigned rd_bursts0 = read_bursts_now(t);
    int unsigned stall;
    int unsigned aw0, w0, ar0, aw1, w1, ar1, aw2, w2, ar2;
    bit [63:0] words[$];
    bit [63:0] excluded[$];
    bit [63:0] observed;
    bit idle;
    bit sr_reset;
    bit [63:0] sr_addr;
    int unsigned sr_pl, sr_size;
    dtp_j2a_status_e sr_status;
    excluded.push_back(read_target_mem_int(t, addr, size));
    while (words.size() < queued + 1) begin
      bit [63:0] word = rand_nonzero_data(t) & data_mask(size);
      if (!(word inside {excluded})) begin
        excluded.push_back(word);
        words.push_back(word);
      end
    end
    // READY stall, in system cycles, outlasting the SERIES_CTRL programming
    // and capture, the beats' shifts and the disable settle.
    stall = (2 * scan_tck + (queued + 1) * scan_tck + 16) * tck_sys_ratio() +
        $urandom_range(64, 16);
    `uvm_info(get_type_name(),
              $sformatf("%s %s: %0d beat(s) queued behind the first, stall=%0d words=%p",
                        context_s, t.name, queued, stall, words), UVM_LOW)
    configure_target_backpressure(t, '{"aw"}, stall);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size, t.wr_pl_depth);
    sample_activity(t, aw0, w0, ar0);
    series_data_no_incr(t, words[0], size);
    wait_for_target_activity(t, aw0, w0, ar0, 1'b0, {context_s, ".first_beat_on_bus"});
    for (int unsigned i = 1; i < words.size(); i++) series_data_no_incr(t, words[i], size);
    // A beat the bridge refused would leave the series status BUSY_OR_FULL.
    read_series_ctrl(t, size, sr_reset, sr_addr, sr_pl, sr_size, sr_status);
    check_status(t, {context_s, ".queued_status"}, sr_status, DTP_J2A_SUCCESS);
    gate_target(t);
    wait_for_write_completion(t, wr_bursts0, {context_s, ".first_beat"}, 2 * stall + 200);
    // The state machine runs on TCK: it leaves the write path, and drops the
    // queue, only while TCK toggles.
    wait_bridge_fsm(t, 1'b1, QueueDropTck, idle);
    clear_target_backpressure(t);
    sample_activity(t, aw1, w1, ar1);
    enable_all_debug();
    repeat (QueueDropTck) step(1'b0);
    wait_sys_cycles(8);
    sample_activity(t, aw2, w2, ar2);
    expect_no_activity_evidence(t, aw1, w1, ar1, aw2, w2, ar2, {
                                context_s, " window=first_beat_completion+release"});
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-EXACT",
        write_bursts_now(
            t
        ),
        wr_bursts0 + 1,
        $sformatf(
            "%s target=%s source=responder_burst_counts sanctioned=first_beat(+1) queued=%0d",
            context_s,
            t.name,
            queued)
    ));
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-EXACT",
        read_bursts_now(
            t
        ),
        rd_bursts0,
        $sformatf(
            "%s target=%s source=responder_burst_counts reads", context_s, t.name)
    ));
    check_target_memory(t, addr, words[0], size, {context_s, ".slot"});
  endtask

  // --- error arming (responder injection + shared checker, one place) ----
  // The errored read beat answers `err_rdata` as its RDATA word.
  task arm_target_error(dtp_j2a_target_t t, bit [63:0] addr, ocah_axi_resp_e resp, bit for_read,
                        bit for_write, bit arm_expected = 1'b1, bit [63:0] err_rdata = '0);
    ocah_axi_resp_e armed_resp = resp;
    responder(t).inject_error(addr, resp, for_read, for_write, err_rdata);
    // arm_expected=0 injects WITHOUT arming the scoreboard expectation —
    // for gated attempts whose op must never reach the bus.
    if (arm_expected && axi_cfg != null) begin
      if (test_cfg != null && test_cfg.axi_scoreboard_negative) begin
        armed_resp = (resp == OCAH_AXI_RESP_DECERR) ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_DECERR;
        `uvm_info(get_type_name(),
                  $sformatf("NEGATIVE VALIDATION: arming resp=%s instead of injected resp=%s",
                            armed_resp.name(), resp.name()), UVM_LOW)
      end
      axi_cfg.arm_expected_resp(addr, armed_resp, for_read, for_write);
    end
    wait_sys_cycles(InjectSettleCycles);
    `uvm_info(get_type_name(),
              $sformatf("%s armed error resp=%s addr=0x%0h read=%0d write=%0d err_rdata=0x%0h",
                        t.name, resp.name(), addr, for_read, for_write, err_rdata), UVM_MEDIUM)
  endtask

  task clear_target_error(dtp_j2a_target_t t);
    responder(t).clear_errors();
    wait_sys_cycles(InjectSettleCycles);
  endtask

  // Bounded responder READY backpressure on the target under test (cocotb
  // configure_target_backpressure parity; channel names are "aw"/"w"/"ar").
  function void configure_target_backpressure(dtp_j2a_target_t t, string channels[$],
                                              int unsigned stall_cycles);
    `uvm_info(
        get_type_name(), $sformatf(
        "%s configure backpressure channels=%p stall_cycles=%0d", t.name, channels, stall_cycles),
        UVM_MEDIUM)
    responder(t).enable_backpressure(channels, stall_cycles);
  endfunction

  function void clear_target_backpressure(dtp_j2a_target_t t);
    responder(t).disable_backpressure();
  endfunction

  // Arms the target's responder so the W beat of the next write is accepted
  // while its AW waits against a stalled AWREADY; later writes take AW
  // first. Call it with the write channels idle.
  function void arm_target_w_before_aw(dtp_j2a_target_t t);
    responder(t).arm_w_before_aw();
  endfunction

  // --- per-bridge dtp_tb_if observables -------------------------------------
  // One sample of the observables tb_top keeps for the port behind `t`: the
  // VALID-high request counters, the READY-stall counters, and the decoded
  // bridge state machine.
  typedef struct {
    int unsigned aw, w, ar;
    int unsigned aw_stall, w_stall, ar_stall;
    bit fsm_idle, fsm_read_path, fsm_write_path;
    bit op_pending;
    bit cdc_clear_seen;
  } port_obs_t;

  function port_obs_t port_observables(dtp_j2a_target_t t);
    port_obs_t o;
    case (t.name)
      "smc_otp": begin
        o = '{
            tb_vif.smc_otp_axil_awvalid_count,
            tb_vif.smc_otp_axil_wvalid_count,
            tb_vif.smc_otp_axil_arvalid_count,
            tb_vif.smc_otp_axil_aw_stall_count,
            tb_vif.smc_otp_axil_w_stall_count,
            tb_vif.smc_otp_axil_ar_stall_count,
            tb_vif.smc_otp_fsm_idle,
            tb_vif.smc_otp_fsm_read_path,
            tb_vif.smc_otp_fsm_write_path,
            tb_vif.smc_otp_op_pending,
            tb_vif.smc_otp_cdc_clear_seen
        };
      end
      "sep_otp": begin
        o = '{
            tb_vif.sep_otp_axil_awvalid_count,
            tb_vif.sep_otp_axil_wvalid_count,
            tb_vif.sep_otp_axil_arvalid_count,
            tb_vif.sep_otp_axil_aw_stall_count,
            tb_vif.sep_otp_axil_w_stall_count,
            tb_vif.sep_otp_axil_ar_stall_count,
            tb_vif.sep_otp_fsm_idle,
            tb_vif.sep_otp_fsm_read_path,
            tb_vif.sep_otp_fsm_write_path,
            tb_vif.sep_otp_op_pending,
            tb_vif.sep_otp_cdc_clear_seen
        };
      end
      "smc_axi": begin
        o = '{
            tb_vif.smc_axi_awvalid_count,
            tb_vif.smc_axi_wvalid_count,
            tb_vif.smc_axi_arvalid_count,
            tb_vif.smc_axi_aw_stall_count,
            tb_vif.smc_axi_w_stall_count,
            tb_vif.smc_axi_ar_stall_count,
            tb_vif.smc_axi_fsm_idle,
            tb_vif.smc_axi_fsm_read_path,
            tb_vif.smc_axi_fsm_write_path,
            tb_vif.smc_axi_op_pending,
            tb_vif.smc_axi_cdc_clear_seen
        };
      end
      default: `uvm_fatal(get_type_name(), {"unknown JTAG2AXI bridge ", t.name})
    endcase
    return o;
  endfunction

  // --- request-activity evidence (security gating) -----------------------
  function void sample_activity(dtp_j2a_target_t t, output int unsigned aw, output int unsigned w,
                                output int unsigned ar);
    port_obs_t o = port_observables(t);
    aw = o.aw;
    w  = o.w;
    ar = o.ar;
  endfunction

  // READY-stall counters of the target's port (cocotb target_stall_counts).
  function void sample_stall(dtp_j2a_target_t t, output int unsigned aw, output int unsigned w,
                             output int unsigned ar);
    port_obs_t o = port_observables(t);
    aw = o.aw_stall;
    w  = o.w_stall;
    ar = o.ar_stall;
  endfunction

  // CHK-AXI-NOACT: the AW, W and AR request counters of the port behind
  // `t` did not move across the window.
  function void expect_no_activity_evidence(
      dtp_j2a_target_t t, int unsigned before_aw, int unsigned before_w, int unsigned before_ar,
      int unsigned after_aw, int unsigned after_w, int unsigned after_ar, string context_s);
    void'(axi_evidence.expect_equal_words(
        "CHK-AXI-NOACT",
        {
          64'(after_aw), 64'(after_w), 64'(after_ar)
        },
        {
          64'(before_aw), 64'(before_w), 64'(before_ar)
        },
        $sformatf(
            "%s target=%s source=tb_pulse_counters", context_s, t.name)
    ));
  endfunction

  // Wait until an operation reaches the target's request channel (series
  // ops launch in the system domain after the TDR shift completes).
  task wait_for_target_activity(dtp_j2a_target_t t, int unsigned before_aw, int unsigned before_w,
                                int unsigned before_ar, bit is_read, string context_s,
                                int unsigned timeout_cycles = PortWaitCycles);
    int unsigned aw, w, ar;
    for (int unsigned cycle = 0; cycle < timeout_cycles; cycle++) begin
      sample_activity(t, aw, w, ar);
      if (is_read ? (ar > before_ar) : (aw > before_aw)) begin
        `uvm_info(get_type_name(), $sformatf("%s: %s %s activity after %0d cycles", context_s,
                                             t.name, is_read ? "AR" : "AW", cycle), UVM_MEDIUM)
        return;
      end
      wait_sys_cycles(1);
    end
    record_wait_timeout(t, timeout_cycles, $sformatf(
                        "%s.%s_activity aw=%0d->%0d ar=%0d->%0d",
                        context_s,
                        is_read ? "ar" : "aw",
                        before_aw,
                        aw,
                        before_ar,
                        ar
                        ));
  endtask

  // CHK-AXI-NONVAC: the scenario's own minimum-activity condition, gated on
  // the responder behind `t` having completed a burst this pass, so a
  // tied-off, idle, or gated bridge cannot satisfy the record whatever the
  // sequence counted (the SV analogue of the cocotb stream-minimum +
  // nonvacuous evidence).
  function void emit_nonvacuity_evidence(dtp_j2a_target_t t, bit condition, string context_s);
    int unsigned bursts = bursts_since_baseline(t);
    void'(axi_evidence.expect_true(
        "CHK-AXI-NONVAC",
        condition && (bursts > 0),
        $sformatf(
            "%s target=%s responder_bursts=%0d", context_s, t.name, bursts)
    ));
  endfunction

  // Completed-burst counters from the responder (exact per-transaction
  // counts; the tb pulse counters count VALID-high cycles, which are
  // timing-dependent per transaction on the reactive slave driver).
  function int unsigned write_bursts_now(dtp_j2a_target_t t);
    return responder(t).write_burst_count();
  endfunction

  function int unsigned read_bursts_now(dtp_j2a_target_t t);
    return responder(t).read_burst_count();
  endfunction

  // Wait until the responder completes a write burst beyond before_count
  // (bounded), so a backdoor memory check cannot race the W-beat commit —
  // the request-pulse wait above returns on AW, cycles before the data
  // beat lands in memory.
  task wait_for_write_completion(dtp_j2a_target_t t, int unsigned before_count, string context_s,
                                 int unsigned timeout_cycles = PortWaitCycles);
    for (int unsigned cycle = 0; cycle < timeout_cycles; cycle++) begin
      if (write_bursts_now(t) > before_count) return;
      wait_sys_cycles(1);
    end
    record_wait_timeout(t, timeout_cycles, {context_s, ".write_burst"});
  endtask

  // --- bridge state-machine observation (dtp_tb_if) -------------------------
  // tb_top decodes each bridge's AXI state machine by state name into the
  // idle, write-path, and read-path flags.
  function bit bridge_fsm_idle(dtp_j2a_target_t t);
    return port_observables(t).fsm_idle;
  endfunction

  function bit bridge_fsm_on_path(dtp_j2a_target_t t, bit is_read);
    port_obs_t o = port_observables(t);
    return is_read ? o.fsm_read_path : o.fsm_write_path;
  endfunction

  function bit bridge_op_pending(dtp_j2a_target_t t);
    return port_observables(t).op_pending;
  endfunction

  // 1 once the bridge's CDC has run its TCK-side isolate-and-clear since
  // clear_cdc_clear_seen().
  function bit cdc_clear_seen(dtp_j2a_target_t t);
    return port_observables(t).cdc_clear_seen;
  endfunction

  task clear_cdc_clear_seen();
    tb_vif.cdc_clear_seen_clear <= 1'b1;
    wait_sys_cycles(1);
    tb_vif.cdc_clear_seen_clear <= 1'b0;
    wait_sys_cycles(1);
  endtask

  // Step TCK in Run-Test/Idle until the bridge's state machine leaves
  // (want_idle = 0) or reaches (want_idle = 1) idle, within `tck_cycles`: the
  // state machine and the CDC's TCK side advance only while TCK runs.
  task wait_bridge_fsm(dtp_j2a_target_t t, bit want_idle, int unsigned tck_cycles, output bit idle);
    idle = bridge_fsm_idle(t);
    for (int unsigned i = 0; i < tck_cycles; i++) begin
      if (idle == want_idle) return;
      step(1'b0);
      idle = bridge_fsm_idle(t);
    end
  endtask

  // --- WITH_ERROR_STATUS streams -------------------------------------------
  // A clean stream whose footprint (the trailing shift touches one slot past
  // the last beat) fits one responder window.
  function dtp_j2a_series_status_plan_t plan_series_status(dtp_j2a_target_t t);
    dtp_j2a_series_status_plan_t p;
    p.size      = t.default_size;
    p.stride    = t.beat_bytes;
    p.fault_idx = -1;
    p.expected  = DTP_J2A_SUCCESS;
    p.base      = '0;
    p.base      = random_series_base(t, dtp_j2a_series_status_span(p));
    return p;
  endfunction

  // Arm a random SLVERR or DECERR on a random first-visit beat of the
  // stream. +DTP_J2A_STATUS_BIT_NEGATIVE keeps the expectation but leaves
  // the responder unarmed, so the fault beat's checks must fail.
  task arm_series_status_fault(dtp_j2a_target_t t, ref dtp_j2a_series_status_plan_t p,
                               input bit for_read);
    int unsigned beats[$];
    ocah_axi_resp_e resp = $urandom_range(1) ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_DECERR;
    dtp_j2a_series_status_first_visits(p, beats);
    p.fault_idx = int'(beats[$urandom_range(beats.size() - 1)]);
    p.expected  = dtp_j2a_axi_resp_to_status(resp);
    if (test_cfg != null && test_cfg.j2a_status_bit_negative)
      `uvm_info(get_type_name(), $sformatf(
                "NEGATIVE VALIDATION: fault beat %0d at 0x%0h left unarmed; the fault beat's checks must fail",
                p.fault_idx,
                dtp_j2a_series_status_addr(
                    p, p.fault_idx
                )
                ), UVM_LOW)
    else arm_target_error(t, dtp_j2a_series_status_addr(p, p.fault_idx), resp, for_read, !for_read);
  endtask

  // An aligned slot outside the stream's footprint for the recovery access.
  function bit [63:0] series_status_recovery_addr(dtp_j2a_series_status_plan_t p);
    return (p.base >= p.stride) ? p.base - p.stride : p.base + dtp_j2a_series_status_span(p);
  endfunction

  // Judge the WITH_ERROR_STATUS bit shift k returns (1 = beat k-1 failed).
  function void check_series_status_bit(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p,
                                        int unsigned shift, bit observed, string context_s);
    bit expected = dtp_j2a_series_status_expected_bit(p, shift);
    string name = $sformatf("%s.status_bit#%0d", context_s, shift);
    string detail = $sformatf("addr=0x%0h", dtp_j2a_series_status_addr(p, shift));
    void'(axi_evidence.expect_equal(
        DtpJ2aStatusBitCheckId,
        64'(observed),
        64'(expected),
        $sformatf(
            "%s target=%s %s", name, t.name, detail)
    ));
  endfunction

  // One shift of a WITH_ERROR_STATUS stream: the shift past the last beat
  // holds the address. Returns once the port completes the shift's
  // transaction.
  task series_status_shift(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p, int unsigned shift,
                           bit [63:0] data, bit is_read, string context_s, output bit [63:0] rdata);
    bit inc = (shift < DtpJ2aSeriesStatusBeats) ? DtpJ2aSeriesStatusIncrements[shift] : 1'b0;
    bit [63:0] addr = dtp_j2a_series_status_addr(p, shift);
    bit [63:0] payload = data & data_mask(p.size);
    int unsigned completed = port_history(t.name).count(is_read);
    bit status_bit;
    bit done;
    int unsigned aw0, w0, ar0;
    sample_activity(t, aw0, w0, ar0);
    series_data_with_status(t, payload, p.size, inc, rdata, status_bit);
    wait_for_target_activity(t, aw0, w0, ar0, is_read, $sformatf("%s.axi#%0d", context_s, shift));
    wait_port_count(t, is_read, completed, done);
    if (!done) record_wait_timeout(t, PortWaitCycles, $sformatf("%s.commit#%0d", context_s, shift));
    expect_bus_request(t, is_read, addr, p.size, dtp_j2a_series_wdata(t, payload, addr, p.size),
                       dtp_j2a_series_wstrb(t, addr, p.size), $sformatf("%s#%0d", context_s, shift
                       ));
    check_series_status_bit(t, p, shift, status_bit, context_s);
  endtask

  // Drive one WITH_ERROR_STATUS write stream and judge every shift: the
  // returned bit belongs to the previous beat and a trailing shift returns
  // the last beat's; the responder drops the fault beat, so that slot keeps
  // its prior word; the SERIES_CTRL capture must show the pattern's final
  // address.
  task run_series_status_write(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p,
                               bit [63:0] words[], string context_s);
    bit [63:0] fault_before = '0;
    bit [63:0] unused, addr_after;
    bit sr_reset;
    int unsigned sr_pl, sr_size;
    dtp_j2a_status_e sr_status;
    if (p.fault_idx >= 0)
      fault_before = read_target_mem_int(t, dtp_j2a_series_status_addr(p, p.fault_idx), p.size);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, p.base, p.size);
    foreach (words[idx]) begin
      bit [63:0] addr = dtp_j2a_series_status_addr(p, idx);
      log_iteration(idx + 1, DtpJ2aSeriesStatusBeats, $sformatf(
                    "with-status write addr=0x%08h inc=%0d data=0x%0h resp=%s",
                    addr,
                    DtpJ2aSeriesStatusIncrements[idx],
                    words[idx],
                    dtp_j2a_series_status_is_fault(
                        p, idx
                    ) ? p.expected.name() : "OKAY"
                    ));
      series_status_shift(t, p, idx, words[idx], 1'b0, context_s, unused);
      if (dtp_j2a_series_status_is_fault(p, idx))
        check_target_memory(t, addr, fault_before, p.size, $sformatf(
                            "%s.mem_dropped#%0d", context_s, idx));
      else
        check_target_memory(t, addr, words[idx], p.size, $sformatf("%s.mem#%0d", context_s, idx));
    end
    series_status_shift(t, p, DtpJ2aSeriesStatusBeats, '0, 1'b0, context_s, unused);
    read_series_ctrl(t, p.size, sr_reset, addr_after, sr_pl, sr_size, sr_status);
    check_series_status_addr(t, p, addr_after, context_s);
  endtask

  // Drive one WITH_ERROR_STATUS read stream from a single SERIES_CTRL
  // preload: every shift launches a read and returns the previous read's
  // word and status bit, so shift k judges read k-1 and a trailing shift
  // judges the last beat. `expected` holds each beat's word when the stream
  // starts; once a read completes, a beat that re-reads its address gets a
  // fresh seeded word written there, so that read's capture cannot repeat
  // the earlier one. The fault beat returns the port's errored-beat word,
  // which this stream sets to zero, and is not judged.
  task run_series_status_read(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p,
                              bit [63:0] expected[], string context_s);
    bit [63:0] rdata, addr_after;
    bit [63:0] want[] = expected;
    bit sr_reset;
    int unsigned sr_pl, sr_size;
    dtp_j2a_status_e sr_status;
    series_ctrl_op(t, DTP_J2A_OP_READ, p.base, p.size);
    for (int unsigned shift = 0; shift <= DtpJ2aSeriesStatusBeats; shift++) begin
      if (shift < DtpJ2aSeriesStatusBeats)
        log_iteration(shift + 1, DtpJ2aSeriesStatusBeats, $sformatf(
                      "with-status read addr=0x%08h inc=%0d resp=%s",
                      dtp_j2a_series_status_addr(
                          p, shift
                      ),
                      DtpJ2aSeriesStatusIncrements[shift],
                      dtp_j2a_series_status_is_fault(
                          p, shift
                      ) ? p.expected.name() : "OKAY"
                      ));
      series_status_shift(t, p, shift, '0, 1'b1, context_s, rdata);
      if (shift >= 1 && !dtp_j2a_series_status_is_fault(p, shift - 1))
        check_returned_rdata(t, rdata, want[shift-1], $sformatf(
                             "%s.rdata#%0d addr=0x%0h",
                             context_s,
                             shift - 1,
                             dtp_j2a_series_status_addr(
                                 p, shift - 1
                             )
                             ));
      if (shift + 1 < DtpJ2aSeriesStatusBeats && dtp_j2a_series_status_addr(
              p, shift + 1
          ) == dtp_j2a_series_status_addr(
              p, shift
          )) begin
        bit [63:0] fresh = random_distinct_word(t, {want[shift]});
        `uvm_info(get_type_name(), $sformatf("%s: held address 0x%0h takes 0x%0h for read %0d",
                                             context_s, dtp_j2a_series_status_addr(p, shift),
                                             fresh, shift + 1), UVM_MEDIUM)
        write_target_mem_int(t, dtp_j2a_series_status_addr(p, shift), fresh, p.size);
        want[shift+1] = fresh;
      end
    end
    read_series_ctrl(t, p.size, sr_reset, addr_after, sr_pl, sr_size, sr_status);
    check_series_status_addr(t, p, addr_after, context_s);
  endtask

  function void check_series_status_addr(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p,
                                         bit [63:0] addr_after, string context_s);
    bit [63:0] expected = dtp_j2a_series_status_final_addr(p) & bit_mask(t.addr_width);
    void'(axi_evidence.expect_equal(
        DtpJ2aSeriesAddrCheckId,
        addr_after,
        expected,
        $sformatf(
            "%s.addr_after target=%s", context_s, t.name)
    ));
  endfunction

  function int unsigned pending_expected_credits();
    return axi_cfg.pending_expected_resp() + axi_cfg.pending_expected_writes()
        + axi_cfg.pending_expected_reads();
  endfunction

  // CHK-AXI-NONVAC: the stream ran and a real bus response consumed its
  // fault credit.
  function void emit_series_status_nonvacuity(
      string label, dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p, int unsigned operations);
    int unsigned unconsumed = pending_expected_credits();
    bit ran = (operations >= DtpJ2aSeriesStatusBeats) && (p.fault_idx >= 0) && (unconsumed == 0);
    emit_nonvacuity_evidence(t, ran, $sformatf(
                             "scenario=%s operations=%0d fault_beat=%0d resp=%s credits_unconsumed=%0d",
                             label,
                             operations,
                             p.fault_idx,
                             p.expected.name(),
                             unconsumed
                             ));
  endfunction

  // CHK-AXI-NONVAC on every bridge: its responder completed a burst this
  // pass and no armed expectation is left unconsumed.
  function void emit_all_bridges_nonvacuity(string label);
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      int unsigned unconsumed = pending_expected_credits();
      emit_nonvacuity_evidence(
          t, unconsumed == 0, $sformatf(
          "scenario=%s operations=%0d credits_unconsumed=%0d", label, operation_count, unconsumed));
    end
  endfunction

endclass : dtp_jtag2axi_base_test_seq
