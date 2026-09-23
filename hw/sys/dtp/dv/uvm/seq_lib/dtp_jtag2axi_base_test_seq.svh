// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI family layer of the DTP scenario sequences — the SV analogue of
// the cocotb dtp_jtag2axi_base_test_seq and dtp_jtag2axi_cmd_lib_seq. Every
// bridge request is a reusable operation on the primary TAP sequencer
// (dtp_jtag2axi_single_op_seq / _single_status_seq / _series_ctrl_seq /
// _series_data_seq, all built on the dtp_types codec); this layer adds the
// bridge geometry lookups, the status polling bound, the evidence arming,
// the responder backdoor through the virtual sequencer's responder
// sequences, the lifecycle debug-disable gating, and the request-activity
// evidence from the dtp_tb_if pulse counters.
//
// The responders are shared ocah_axi_vip UVM slave agents reached through
// the virtual sequencer by target name; the test plumbs the
// target-under-test evidence bundle (axi_cfg / axi_evidence / axi_ref_model)
// before start(). Error arming discipline: arm_target_error() programs the
// responder injection AND cfg.arm_expected_resp() in one place, so the
// injected non-OKAY is EXPECTED for the shared AXI scoreboard;
// clear_target_error() reverses both. test_cfg.axi_scoreboard_negative
// (+DTP_AXI_SCOREBOARD_NEGATIVE) is the negative-validation hook: it arms
// the WRONG expected response so the run must FAIL, proving the checker
// rejects a bad expectation end to end.
//
// Gated attempts must never arm credits: issue_single() skips intent arming
// whenever the target's lifecycle disable is asserted (an armed credit that
// is never consumed correctly fails at check_phase). The lifecycle debug
// disables reset to the fail-closed '1 tie-off, so the target's disable
// must be cleared before any JTAG2AXI op.

class dtp_jtag2axi_base_test_seq extends dtp_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_base_test_seq)

  // Plumbed by the test for the target under test: the shared AXI VIP
  // passive cfg (expected-response/intent arming), its scoreboard evidence
  // recorder, and the passive reference model (backdoor-preload mirror).
  ocah_axi_config    axi_cfg;
  ocah_axi_checker   axi_evidence;
  ocah_axi_ref_model axi_ref_model;
  // The port's observed-read history (CHK-J2A-ERR-RDATA).
  dtp_axi_read_history axi_reads;

  // Settle after programming or clearing responder error injection
  // (system-domain cycles).
  localparam int unsigned InjectSettleCycles = 2;

  // Completed responder bursts per bridge when the pass began: the
  // anti-vacuity record of a scenario requires the bridge it ran on to have
  // moved at least one burst across the DUT's AXI port since then.
  protected int unsigned m_burst_baseline[string];

  function new(string name = "dtp_jtag2axi_base_test_seq");
    super.new(name);
  endfunction

  // Every pass opens with the burst baseline and the geometry gate: the
  // three *_JTAG2AXI_CAPS TDRs are read and their bus type, address size,
  // and data size compared with the dtp_types table (CHK-J2A-GEOMETRY), so
  // no bridge request is packed with field widths the DUT does not publish.
  virtual task pre_body();
    super.pre_body();
    snapshot_burst_baseline();
    verify_bridge_geometry();
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
    geometry.name_tag     = "dtp_jtag2axi_geometry";
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
    end
    geometry.finalize();
  endtask

  // --- bridge geometry and codec (dtp_types; kept under their short names
  //     for the scenario bodies) ------------------------------------------
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

  // A nonzero seeded word: a preload the errored beat's RDATA cannot equal.
  function bit [63:0] rand_nonzero_data(dtp_j2a_target_t t);
    bit [63:0] data;
    do data = mask_target_data(t, {$urandom(), $urandom()}); while (data == '0);
    return data;
  endfunction

  // Beat-aligned random address inside the responder memory window; wider
  // alignment when the transfer size exceeds the beat.
  function bit [63:0] random_target_aligned_addr(dtp_j2a_target_t t, int unsigned size);
    int unsigned align = (size_bytes(size) > t.beat_bytes) ? size_bytes(size)
                                                               : t.beat_bytes;
    int unsigned max_slot = (DtpJ2aTargetMemBytes - align) / align;
    return 64'($urandom_range(max_slot) * align);
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
    if (axi_ref_model != null) axi_ref_model.backdoor_write(addr, payload);
  endfunction

  function bit [63:0] read_target_mem_int(dtp_j2a_target_t t, bit [63:0] addr, int unsigned size);
    return responder(t).read_int(addr, size_bytes(size)) & data_mask(size);
  endfunction

  // --- end-state byte image of a random write stream ----------------------
  // Record the bytes of the word at `addr` that the image lacks.
  function void snapshot_target_word(dtp_j2a_target_t t, ref bit [7:0] image[bit [63:0]],
                                     input bit [63:0] addr, input int unsigned size);
    bit [63:0] word = read_target_mem_int(t, addr, size);
    for (int unsigned b = 0; b < size_bytes(size); b++)
      if (!image.exists(addr + b)) image[addr+b] = word[8*b+:8];
  endfunction

  // Apply one write's enabled lanes to the byte image.
  function void image_write(ref bit [7:0] image[bit [63:0]], input bit [63:0] addr,
                            input bit [63:0] data, input bit [7:0] wstrb, input int unsigned size);
    for (int unsigned b = 0; b < size_bytes(size); b++)
      if (wstrb[b]) image[addr+b] = data[8*b+:8];
  endfunction

  // CHK-J2A-MEM-IMAGE: every byte of the image matches the responder memory.
  // The image holds every lane a stream wrote at its last value and every
  // untouched lane of a touched word at its prior value, so a write that
  // landed on the wrong lane or disturbed a neighbour fails here.
  function void check_memory_image(dtp_j2a_target_t t, ref bit [7:0] image[bit [63:0]],
                                   input string context_s);
    int unsigned mismatches = 0;
    foreach (image[addr]) begin
      bit [7:0] observed = 8'(read_target_mem_int(t, addr, 0));
      if (observed !== image[addr]) begin
        mismatches++;
        `uvm_error("jtag2axi_image_chk", $sformatf(
                   "%s: %s byte 0x%0h holds 0x%02h, image 0x%02h",
                   context_s,
                   t.name,
                   addr,
                   observed,
                   image[addr]
                   ))
      end
    end
    if (axi_evidence != null)
      void'(axi_evidence.expect_equal(
          DtpJ2aMemImageCheckId,
          64'(mismatches),
          64'd0,
          $sformatf(
              "%s target=%s bytes=%0d", context_s, t.name, image.num())
      ));
  endfunction

  // CHK-AXI-WMEM: responder RAM bytes versus the stimulus intent.
  function void check_target_memory(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] expected,
                                    int unsigned size, string context_s);
    bit [63:0] observed = read_target_mem_int(t, addr, size);
    if (axi_evidence != null)
      void'(axi_evidence.expect_equal(
          "CHK-AXI-WMEM",
          observed,
          expected & data_mask(
              size
          ),
          $sformatf(
              "%s target=%s addr=0x%0h bytes=%0d source=stimulus-intent",
              context_s,
              t.name,
              addr,
              size_bytes(
                  size
              ))
      ));
    else if (observed !== (expected & data_mask(size)))
      `uvm_error("jtag2axi_mem_chk", $sformatf(
                 "%s: memory at 0x%0h is 0x%0h, expected 0x%0h",
                 context_s,
                 addr,
                 observed,
                 expected & data_mask(
                     size
                 )
                 ))
  endfunction

  // --- single-op TDR flow ------------------------------------------------
  task issue_single(dtp_j2a_target_t t, dtp_j2a_op_e op, bit [63:0] addr, bit [63:0] data = '0,
                    bit [7:0] wstrb = '0, int unsigned size = 0, bit use_default_size = 1'b1);
    int unsigned eff_size = use_default_size ? t.default_size : size;
    `uvm_info(get_type_name(), $sformatf(
                                   "%s SINGLE_OP %s addr=0x%0h data=0x%0h wstrb=0x%0h size=%0d",
                                   t.name, op.name(), addr, data, wstrb, eff_size), UVM_MEDIUM)
    // Stimulus-intent records: the address/data/wstrb programmed into the
    // TDR is the truth the observed bus transaction must match
    // (CHK-AXI-WADDR / CHK-AXI-WDATA / CHK-AXI-STRB / CHK-AXI-RADDR).
    // Gated ops never reach the bus: do not arm intents while the
    // target's disable is asserted (the no-activity evidence owns that
    // case; a dangling intent would false-fail at check_phase).
    if (op == DTP_J2A_OP_WRITE && axi_cfg != null && target_enabled(t))
      axi_cfg.arm_expected_write(addr & bit_mask(t.addr_width), data & bit_mask(t.data_width),
                                 wstrb);
    if (op == DTP_J2A_OP_READ && axi_cfg != null && target_enabled(t))
      axi_cfg.arm_expected_read(addr & bit_mask(t.addr_width));
    begin
      dtp_jtag2axi_single_op_seq req = dtp_jtag2axi_single_op_seq::type_id::create("single_op");
      req.target = t;
      req.op     = op;
      req.addr   = addr;
      req.data   = data;
      req.wstrb  = wstrb;
      req.size   = eff_size;
      run_jtag_op(req);
    end
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after SINGLE_OP request");
    note_tdr_access(single_op_len(t), $sformatf("%s single_op request", t.name));
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
    status = st.status;
    rdata  = st.rdata;
  endtask

  // Poll SINGLE_OP until the bridge leaves BUSY_OR_FULL, then land
  // CHK-AXI-COMPLETION: a bridge stuck BUSY within the poll bound fails
  // (every call site expects a final, settled status). The log counts the
  // captures that read BUSY_OR_FULL first, usually none at the bench's TCK
  // ratio, since a scan outlasts the bus access.
  task poll_single(dtp_j2a_target_t t, output dtp_j2a_status_e status, output bit [63:0] rdata,
                   input string context_s = "single_op");
    int unsigned busy_polls = 0;
    status = DTP_J2A_BUSY_OR_FULL;
    rdata  = '0;
    for (int unsigned poll = 0; poll < DtpJ2aMaxStatusPolls; poll++) begin
      single_status_once(t, status, rdata);
      if (status != DTP_J2A_BUSY_OR_FULL) break;
      busy_polls++;
    end
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP status=%s rdata=0x%0h busy_polls=%0d",
                                         t.name, status.name(), rdata, busy_polls), UVM_MEDIUM)
    if (axi_evidence != null)
      void'(axi_evidence.expect_true(
          "CHK-AXI-COMPLETION",
          status != DTP_J2A_BUSY_OR_FULL,
          $sformatf(
              "%s target=%s polls=%0d", context_s, t.name, DtpJ2aMaxStatusPolls)
      ));
  endtask

  task single_write(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, bit [7:0] wstrb,
                    output dtp_j2a_status_e status, input int unsigned size = 0,
                    input bit use_default_size = 1'b1, input string context_s = "single_write");
    bit [63:0] unused_rdata;
    issue_single(t, DTP_J2A_OP_WRITE, addr, data, wstrb, size, use_default_size);
    poll_single(t, status, unused_rdata, context_s);
  endtask

  task single_read(dtp_j2a_target_t t, bit [63:0] addr, output dtp_j2a_status_e status,
                   output bit [63:0] rdata, input int unsigned size = 0,
                   input bit use_default_size = 1'b1, input string context_s = "single_read");
    issue_single(t, DTP_J2A_OP_READ, addr, '0, '0, size, use_default_size);
    poll_single(t, status, rdata, context_s);
  endtask

  function void check_status(string context_s, dtp_j2a_status_e observed,
                             dtp_j2a_status_e expected);
    if (observed !== expected)
      `uvm_error("jtag2axi_status_chk", $sformatf(
                 "%s: JTAG2AXI status %s, expected %s", context_s, observed.name(), expected.name()
                 ))
    else
      `uvm_info("jtag2axi_status_chk", $sformatf(
                "%s: JTAG2AXI status %s as expected", context_s, observed.name()), UVM_MEDIUM)
  endfunction

  // --- checked single operations (cocotb *_and_check parity) --------------
  // Write, poll to completion, and verify enabled byte lanes landed in the
  // responder memory.
  task write_target_single_and_check(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                                     output dtp_j2a_status_e status, input int unsigned size,
                                     input bit [7:0] wstrb = 8'hFF,
                                     input string context_s = "single_write");
    bit [63:0] observed;
    bit [63:0] masked = data & data_mask(size);
    single_write(t, addr, masked, wstrb, status, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, DTP_J2A_SUCCESS);
    observed = read_target_mem_int(t, addr, size);
    for (int unsigned lane = 0; lane < size_bytes(size); lane++) begin
      if (wstrb[lane]) begin
        if (observed[8*lane+:8] !== masked[8*lane+:8])
          `uvm_error("jtag2axi_data_chk", $sformatf(
                     "%s.byte%0d: memory 0x%02h != written 0x%02h (addr=0x%0h wstrb=0x%02h)",
                     context_s,
                     lane,
                     observed[8*lane+:8],
                     masked[8*lane+:8],
                     addr + lane,
                     wstrb
                     ))
      end
    end
  endtask

  // Read, poll to completion, and verify the returned data.
  task read_target_single_and_check(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] expected,
                                    output dtp_j2a_status_e status, input int unsigned size,
                                    input string context_s = "single_read");
    bit [63:0] rdata;
    single_read(t, addr, status, rdata, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, DTP_J2A_SUCCESS);
    if ((rdata & data_mask(size)) !== (expected & data_mask(size)))
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "%s: rdata 0x%0h != expected 0x%0h (addr=0x%0h size=%0d)",
                 context_s,
                 rdata & data_mask(
                     size
                 ),
                 expected & data_mask(
                     size
                 ),
                 addr,
                 size
                 ))
  endtask

  // Error-path variants: complete and verify the requested status.
  task write_target_single_expect_status(
      dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, dtp_j2a_status_e expected_status,
      output dtp_j2a_status_e status, input int unsigned size, input bit [7:0] wstrb = 8'hFF,
      input string context_s = "single_write_error");
    single_write(t, addr, data & data_mask(size), wstrb, status, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, expected_status);
  endtask

  task read_target_single_expect_status(
      dtp_j2a_target_t t, bit [63:0] addr, dtp_j2a_status_e expected_status,
      output dtp_j2a_status_e status, output bit [63:0] rdata, input int unsigned size,
      input string context_s = "single_read_error");
    single_read(t, addr, status, rdata, size, 1'b0, context_s);
    check_status({context_s, ".status"}, status, expected_status);
  endtask

  // CHK-J2A-ERR-RDATA: the SINGLE_OP rdata is the RDATA of the errored beat.
  // The bridge latches the errored R beat's data together with its status,
  // so the capture returns the word the responder drove on that beat: it
  // equals the beat the port's monitor observed at `addr` with `resp` and
  // differs from the word preloaded in the slot.
  function void check_error_rdata(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] rdata,
                                  ocah_axi_resp_e resp, bit [63:0] preload, int unsigned size,
                                  string context_s);
    ocah_axi_item item;
    bit [63:0] mask = data_mask(size);
    bit [63:0] observed = rdata & mask;
    bit [63:0] beat_addr, beat_word;
    string detail;
    if (axi_reads == null)
      `uvm_fatal(get_type_name(), "dtp_axi_read_history `axi_reads` not plumbed by the test")
    if (!axi_reads.last_read(item)) begin
      `uvm_error("jtag2axi_data_chk", $sformatf("%s: no read observed on %s for the errored beat",
                                                context_s, t.name))
      return;
    end
    beat_addr = item.address - (item.address % t.beat_bytes);
    beat_word = item.first_data() & mask;
    detail = $sformatf("%s target=%s addr=0x%0h preload=0x%0h", context_s, t.name, addr,
                       preload & mask);
    if (axi_evidence != null) begin
      void'(axi_evidence.expect_equal(
          DtpJ2aErrRdataCheckId,
          beat_addr,
          addr - (addr % t.beat_bytes),
          {
            detail, " field=beat_addr"
          }
      ));
      void'(axi_evidence.expect_equal(
          DtpJ2aErrRdataCheckId, 64'(item.worst_resp()), 64'(resp), {detail, " field=beat_resp"}
      ));
      void'(axi_evidence.expect_equal(
          DtpJ2aErrRdataCheckId, observed, beat_word, {detail, " field=rdata"}
      ));
      void'(axi_evidence.expect_true(
          DtpJ2aErrRdataCheckId, observed != (preload & mask), {detail, " field=rdata_not_preload"}
      ));
    end
    if (observed !== beat_word)
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "%s.err_rdata: rdata 0x%0h != errored beat 0x%0h (addr=0x%0h beat_addr=0x%0h)",
                 context_s,
                 observed,
                 beat_word,
                 addr,
                 beat_addr
                 ))
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
      // CHK-AXI-WMEM against the STIMULUS intent (non-circular).
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
    if (axi_evidence != null)
      void'(axi_evidence.expect_true(
          "CHK-AXI-COMPLETION",
          status != DTP_J2A_BUSY_OR_FULL,
          $sformatf(
              "series_ctrl target=%s", t.name)
      ));
  endtask

  // CHK-J2A-SERIES-ADDR: the SERIES_CTRL capture holds `expected_addr`;
  // returns the captured status.
  task check_series_addr(dtp_j2a_target_t t, bit [63:0] expected_addr, int unsigned size,
                         string context_s, output dtp_j2a_status_e status);
    bit sr_reset;
    bit [63:0] addr_after;
    int unsigned sr_pl, sr_size;
    bit [63:0] expected = expected_addr & bit_mask(t.addr_width);
    read_series_ctrl(t, size, sr_reset, addr_after, sr_pl, sr_size, status);
    if (axi_evidence != null)
      void'(axi_evidence.expect_equal(
          DtpJ2aSeriesAddrCheckId,
          addr_after,
          expected,
          $sformatf(
              "%s target=%s", context_s, t.name)
      ));
    if (addr_after !== expected)
      `uvm_error("jtag2axi_series_chk", $sformatf(
                 "%s.addr_after: 0x%0h != expected 0x%0h", context_s, addr_after, expected))
  endtask

  // One series-data shift (dtp_jtag2axi_series_data_seq): payload-sized
  // TDR, optional MSB increment bit (with-status mode), idle TCK cycles
  // for the op to launch.
  protected task series_data_shift(dtp_j2a_target_t t, dtp_jtag_instr_e instr, bit [63:0] data,
                                   int unsigned size,
                                   input int increment,  // <0: no increment/status bit in the TDR
                                   output bit [63:0] result);
    int unsigned payload_bits = 8 * size_bytes(size);
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
    int unsigned payload_bits = 8 * size_bytes(size);
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
    rdata      = shift.captured & data_mask(size);
    status_bit = shift.captured_status;
  endtask

  // --- lifecycle debug disables (must be cleared before JTAG2AXI ops) ----
  // Assert exactly the disable that gates this target (all others clear).
  task gate_target(dtp_j2a_target_t t);
    set_dbg_disable(t.dbg_disable_mask);
  endtask

  function bit target_enabled(dtp_j2a_target_t t);
    return (tb_vif.dbg_disable & t.dbg_disable_mask) == '0;
  endfunction

  // --- error arming (responder injection + shared checker, one place) ----
  task arm_target_error(dtp_j2a_target_t t, bit [63:0] addr, ocah_axi_resp_e resp, bit for_read,
                        bit for_write, bit arm_expected = 1'b1);
    ocah_axi_resp_e armed_resp = resp;
    responder(t).inject_error(addr, resp, for_read, for_write);
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
    `uvm_info(get_type_name(), $sformatf("%s armed error resp=%s addr=0x%0h read=%0d write=%0d",
                                         t.name, resp.name(), addr, for_read, for_write),
              UVM_MEDIUM)
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

  // --- request-activity evidence (security gating) -----------------------
  function void sample_activity(dtp_j2a_target_t t, output int unsigned aw, output int unsigned w,
                                output int unsigned ar);
    if (t.name == "smc_otp") begin
      aw = tb_vif.smc_otp_axil_awvalid_count;
      w  = tb_vif.smc_otp_axil_wvalid_count;
      ar = tb_vif.smc_otp_axil_arvalid_count;
    end else if (t.name == "sep_otp") begin
      aw = tb_vif.sep_otp_axil_awvalid_count;
      w  = tb_vif.sep_otp_axil_wvalid_count;
      ar = tb_vif.sep_otp_axil_arvalid_count;
    end else begin
      aw = tb_vif.smc_axi_awvalid_count;
      w  = tb_vif.smc_axi_wvalid_count;
      ar = tb_vif.smc_axi_arvalid_count;
    end
  endfunction

  // Compare an activity snapshot pair through the shared evidence recorder.
  function void expect_no_activity_evidence(
      dtp_j2a_target_t t, int unsigned before_aw, int unsigned before_w, int unsigned before_ar,
      int unsigned after_aw, int unsigned after_w, int unsigned after_ar, string context_s);
    if (axi_evidence == null) return;
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-AW",
        after_aw,
        before_aw,
        $sformatf(
            "%s target=%s source=tb_pulse_counters", context_s, t.name)
    ));
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-W",
        after_w,
        before_w,
        $sformatf(
            "%s target=%s source=tb_pulse_counters", context_s, t.name)
    ));
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-AR",
        after_ar,
        before_ar,
        $sformatf(
            "%s target=%s source=tb_pulse_counters", context_s, t.name)
    ));
  endfunction

  // Wait until an operation reaches the target's request channel (series
  // ops launch in the system domain after the TDR shift completes).
  task wait_for_target_activity(dtp_j2a_target_t t, int unsigned before_aw, int unsigned before_w,
                                int unsigned before_ar, bit is_read, string context_s,
                                int unsigned timeout_cycles = 200);
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
    `uvm_error("jtag2axi_activity_chk",
               $sformatf("%s: expected %s %s activity within %0d cycles (aw=%0d->%0d ar=%0d->%0d)",
                         context_s, t.name, is_read ? "AR" : "AW", timeout_cycles, before_aw, aw,
                         before_ar, ar))
  endtask

  // CHK-AXI-NONVAC: the scenario's own minimum-activity condition, gated on
  // the responder behind `t` having completed a burst this pass, so a
  // tied-off, idle, or gated bridge cannot satisfy the record whatever the
  // sequence counted (the SV analogue of the cocotb stream-minimum +
  // nonvacuous evidence).
  function void emit_nonvacuity_evidence(dtp_j2a_target_t t, bit condition, string context_s);
    int unsigned bursts = bursts_since_baseline(t);
    if (axi_evidence != null)
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
                                 int unsigned timeout_cycles = 200);
    for (int unsigned cycle = 0; cycle < timeout_cycles; cycle++) begin
      if (write_bursts_now(t) > before_count) return;
      wait_sys_cycles(1);
    end
    `uvm_error("jtag2axi_activity_chk",
               $sformatf("%s: %s write burst did not complete within %0d cycles", context_s,
                         t.name, timeout_cycles))
  endtask

  // --- bridge state-machine observation (dtp_tb_if) -------------------------
  // tb_top decodes each bridge's AXI state machine by state name into the
  // idle, write-path, and read-path flags.
  function bit bridge_fsm_idle(dtp_j2a_target_t t);
    if (t.name == "smc_otp") return tb_vif.smc_otp_fsm_idle;
    if (t.name == "sep_otp") return tb_vif.sep_otp_fsm_idle;
    return tb_vif.smc_axi_fsm_idle;
  endfunction

  function bit bridge_fsm_on_path(dtp_j2a_target_t t, bit is_read);
    if (t.name == "smc_otp")
      return is_read ? tb_vif.smc_otp_fsm_read_path : tb_vif.smc_otp_fsm_write_path;
    if (t.name == "sep_otp")
      return is_read ? tb_vif.sep_otp_fsm_read_path : tb_vif.sep_otp_fsm_write_path;
    return is_read ? tb_vif.smc_axi_fsm_read_path : tb_vif.smc_axi_fsm_write_path;
  endfunction

  function bit bridge_op_pending(dtp_j2a_target_t t);
    if (t.name == "smc_otp") return tb_vif.smc_otp_op_pending;
    if (t.name == "sep_otp") return tb_vif.sep_otp_op_pending;
    return tb_vif.smc_axi_op_pending;
  endfunction

  // 1 once the bridge's CDC has run its TCK-side isolate-and-clear since
  // clear_cdc_clear_seen().
  function bit cdc_clear_seen(dtp_j2a_target_t t);
    if (t.name == "smc_otp") return tb_vif.smc_otp_cdc_clear_seen;
    if (t.name == "sep_otp") return tb_vif.sep_otp_cdc_clear_seen;
    return tb_vif.smc_axi_cdc_clear_seen;
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
  // the last beat) fits the target window.
  function dtp_j2a_series_status_plan_t plan_series_status(dtp_j2a_target_t t);
    dtp_j2a_series_status_plan_t p;
    bit [63:0] span;
    p.size      = t.default_size;
    p.stride    = t.beat_bytes;
    p.fault_idx = -1;
    p.expected  = DTP_J2A_SUCCESS;
    p.base      = '0;
    span        = dtp_j2a_series_status_span(p);
    p.base      = random_target_aligned_addr(t, p.size);
    if (p.base > 64'(DtpJ2aTargetMemBytes) - span) p.base = 64'(DtpJ2aTargetMemBytes) - span;
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
    if (axi_evidence != null)
      void'(axi_evidence.expect_equal(
          DtpJ2aStatusBitCheckId,
          64'(observed),
          64'(expected),
          $sformatf(
              "%s target=%s %s", name, t.name, detail)
      ));
    if (observed !== expected)
      `uvm_error("jtag2axi_status_chk", $sformatf(
                 "%s: status bit %0d, expected %0d (%s)", name, observed, expected, detail))
    else
      `uvm_info("jtag2axi_status_chk", $sformatf(
                "%s: status bit %0d as expected (%s)", name, observed, detail), UVM_MEDIUM)
  endfunction

  // One shift of a WITH_ERROR_STATUS stream: the shift past the last beat
  // holds the address; a write shift also waits for its burst to commit
  // before the caller inspects memory.
  task series_status_shift(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p, int unsigned shift,
                           bit [63:0] data, bit is_read, string context_s, output bit [63:0] rdata);
    bit inc = (shift < DtpJ2aSeriesStatusBeats) ? DtpJ2aSeriesStatusIncrements[shift] : 1'b0;
    bit status_bit;
    int unsigned aw0, w0, ar0, wb0;
    sample_activity(t, aw0, w0, ar0);
    wb0 = is_read ? 0 : write_bursts_now(t);
    series_data_with_status(t, data, p.size, inc, rdata, status_bit);
    wait_for_target_activity(t, aw0, w0, ar0, is_read, $sformatf("%s.axi#%0d", context_s, shift));
    if (!is_read) wait_for_write_completion(t, wb0, $sformatf("%s.commit#%0d", context_s, shift));
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
    bit [63:0] unused, addr_after, observed;
    bit sr_reset;
    int unsigned sr_pl, sr_size;
    dtp_j2a_status_e sr_status;
    if (p.fault_idx >= 0)
      fault_before = read_target_mem_int(t, dtp_j2a_series_status_addr(p, p.fault_idx), p.size);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, p.base, p.size);
    foreach (words[idx]) begin
      bit [63:0] addr = dtp_j2a_series_status_addr(p, idx);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: with-status write addr=0x%08h inc=%0d data=0x%0h resp=%s",
                idx + 1,
                DtpJ2aSeriesStatusBeats,
                addr,
                DtpJ2aSeriesStatusIncrements[idx],
                words[idx],
                dtp_j2a_series_status_is_fault(
                    p, idx
                ) ? p.expected.name() : "OKAY"
                ), UVM_LOW)
      series_status_shift(t, p, idx, words[idx], 1'b0, context_s, unused);
      observed = read_target_mem_int(t, addr, p.size);
      if (dtp_j2a_series_status_is_fault(p, idx)) begin
        if (observed !== fault_before)
          `uvm_error("jtag2axi_data_chk", $sformatf(
                     "%s.mem_dropped#%0d: memory 0x%0h != prior 0x%0h (addr=0x%0h)",
                     context_s,
                     idx,
                     observed,
                     fault_before,
                     addr
                     ))
      end else if (observed !== words[idx])
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "%s.mem#%0d: memory 0x%0h != data 0x%0h (addr=0x%0h)",
                   context_s,
                   idx,
                   observed,
                   words[idx],
                   addr
                   ))
    end
    series_status_shift(t, p, DtpJ2aSeriesStatusBeats, '0, 1'b0, context_s, unused);
    read_series_ctrl(t, p.size, sr_reset, addr_after, sr_pl, sr_size, sr_status);
    check_series_status_addr(t, p, addr_after, context_s);
  endtask

  // Drive one WITH_ERROR_STATUS read stream from a single SERIES_CTRL
  // preload: every shift launches a read and returns the previous read's
  // word and status bit, so shift k judges read k-1 and a trailing shift
  // judges the last beat. The fault beat's word is not judged: the
  // responder returns no valid data with an error response.
  task run_series_status_read(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p,
                              bit [63:0] expected[], string context_s);
    bit [63:0] rdata, addr_after;
    bit sr_reset;
    int unsigned sr_pl, sr_size;
    dtp_j2a_status_e sr_status;
    series_ctrl_op(t, DTP_J2A_OP_READ, p.base, p.size);
    for (int unsigned shift = 0; shift <= DtpJ2aSeriesStatusBeats; shift++) begin
      if (shift < DtpJ2aSeriesStatusBeats)
        `uvm_info(get_type_name(), $sformatf(
                  "Iteration %0d/%0d: with-status read addr=0x%08h inc=%0d resp=%s",
                  shift + 1,
                  DtpJ2aSeriesStatusBeats,
                  dtp_j2a_series_status_addr(
                      p, shift
                  ),
                  DtpJ2aSeriesStatusIncrements[shift],
                  dtp_j2a_series_status_is_fault(
                      p, shift
                  ) ? p.expected.name() : "OKAY"
                  ), UVM_LOW)
      series_status_shift(t, p, shift, '0, 1'b1, context_s, rdata);
      if (shift >= 1 && !dtp_j2a_series_status_is_fault(
              p, shift - 1
          ) && rdata !== expected[shift-1])
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "%s.rdata#%0d: read 0x%0h != expected 0x%0h (addr=0x%0h)",
                   context_s,
                   shift - 1,
                   rdata,
                   expected[shift-1],
                   dtp_j2a_series_status_addr(
                       p, shift - 1
                   )
                   ))
    end
    read_series_ctrl(t, p.size, sr_reset, addr_after, sr_pl, sr_size, sr_status);
    check_series_status_addr(t, p, addr_after, context_s);
  endtask

  function void check_series_status_addr(dtp_j2a_target_t t, dtp_j2a_series_status_plan_t p,
                                         bit [63:0] addr_after, string context_s);
    bit [63:0] expected = dtp_j2a_series_status_final_addr(p) & bit_mask(t.addr_width);
    if (addr_after !== expected)
      `uvm_error("jtag2axi_series_chk", $sformatf(
                 "%s.addr_after: 0x%0h != expected 0x%0h", context_s, addr_after, expected))
  endfunction

  function int unsigned pending_expected_credits();
    if (axi_cfg == null) return 0;
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
                             "scenario=%s target=%s operations=%0d fault_beat=%0d resp=%s credits_unconsumed=%0d",
                             label,
                             t.name,
                             operations,
                             p.fault_idx,
                             p.expected.name(),
                             unconsumed
                             ));
  endfunction

endclass : dtp_jtag2axi_base_test_seq
