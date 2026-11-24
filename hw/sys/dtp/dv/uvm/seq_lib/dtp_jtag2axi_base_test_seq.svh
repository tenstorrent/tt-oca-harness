// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI family layer of the DTP scenario sequences. Each bridge is reached
// through its DTMCS and DMI TDRs: a DMI scan performs one Debug Module
// register operation and captures the result of the one before it, and the
// Debug Module's System Bus Access registers issue one bus beat per access.
//
// The test plumbs every bridge's passive AXI config (intent arming), its
// evidence recorder and the port histories, keyed by bridge name, before
// start(). Every judgement of a bridge lands as a CHK-* record on that
// bridge's recorder: CHK-J2A-FAULT-STATUS for the DMI status of every capture
// and the sberror and sbbusyerror of every access, CHK-AXI-RDATA
// (source=bridge_capture) for the data a read fetches, CHK-AXI-WMEM for
// responder words, CHK-AXI-COMPLETION for the sbbusy poll bound, and
// CHK-AXI-NONVAC for the responder bursts of the pass. The lifecycle debug
// disables reset to the fail-closed '1 tie-off, so the bridge's disable must
// be cleared before any bus access. The cocotb twin is
// seq_lib/dtp_jtag2axi_base_test_seq.py.

class dtp_jtag2axi_base_test_seq extends dtp_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_base_test_seq)

  // Every bridge's shared AXI VIP passive cfg (intent arming) and evidence
  // recorder, keyed by bridge name and plumbed by the test.
  ocah_axi_config      target_cfgs[string];
  ocah_axi_checker     target_evidence[string];
  // Completed-transaction histories of the three bridge ports, keyed by
  // bridge name.
  dtp_axi_port_history axi_ports[string];

  // System cycles a port transaction has to complete in once its access
  // started.
  localparam int unsigned PortWaitCycles = 200;
  // sbcs reads a bus access has to clear sbbusy in.
  localparam int unsigned SbaPolls = 8;
  // Run-Test/Idle TCK cycles after every DTMCS or DMI scan, in which a DMI
  // operation crosses to the Debug Module and back (DtpDmiSettleTck).
  localparam int unsigned DmiIdleTck = 64;
  // The data a read refused by the Debug Module returns.
  localparam bit [31:0] DmiDataBusy = 32'hB051_B051;

  // The pass's bus-request ledger (CHK-J2A-BUS-REQ): the bridge it accounts,
  // "" while closed, and per bridge port the counts that the pass's judged
  // accesses add up to.
  protected string       m_ledger_target;
  protected int unsigned m_ledger_writes[string];
  protected int unsigned m_ledger_reads[string];
  // Completed responder bursts per bridge when the pass began.
  protected int unsigned m_burst_baseline[string];
  // The TAP waits in Select-DR-Scan after a chained raw DMI scan.
  protected bit          m_dr_chained;

  function new(string name = "dtp_jtag2axi_base_test_seq");
    super.new(name);
  endfunction

  // Every pass opens with the burst baseline and the geometry gate, so no
  // bus access is packed with widths the DUT does not publish.
  virtual task pre_body();
    super.pre_body();
    foreach (axi_ports[name]) m_burst_baseline[name] = responder_bursts(name);
    verify_bridge_geometry();
    open_bus_ledger();
  endtask

  virtual task post_body();
    super.post_body();
    close_bus_ledger();
  endtask

  // CHK-J2A-GEOMETRY: each bridge's DTMCS (DMI version, address width, idle
  // hint) and, with the Debug Module active, its sbcs (SBA version, address
  // width, access sizes) equal the dtp_types table, one record per bridge.
  // +DTP_J2A_GEOMETRY_NEGATIVE corrupts the expected address width so the
  // run must FAIL.
  task verify_bridge_geometry();
    string            names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    ocah_jtag_checker geometry = ocah_jtag_checker::type_id::create({get_name(), ".geometry"});
    geometry.name_tag     = $sformatf("dtp_jtag2axi_geometry.pass%0d", loop_index);
    geometry.required_ids = {DtpJ2aGeometryCheckId};
    if (test_cfg != null && test_cfg.j2a_geometry_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: geometry gate expectations will be corrupted", UVM_LOW)
    tap_reset();
    step(1'b0);  // TLR -> RTI: TDR reads start their IR scan from Run-Test/Idle
    foreach (names[i]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[i]);
      bit       [63:0] dtmcs;
      bit       [31:0] sbcs;
      bit       [63:0] observed;
      bit       [63:0] expected;
      read_tdr(IrWidth'(t.dtmcs_instr), DtpDtmcsLen, dtmcs);
      run_test_idle(DmiIdleTck);
      activate_dm(t);
      dmi_read(t, DTP_DM_SBCS, "geometry", sbcs);
      `uvm_info(get_type_name(), $sformatf(
                "GEOMETRY %s dtmcs=0x%08h sbcs=0x%08h", t.name, dtmcs, sbcs), UVM_LOW)
      observed = {dtmcs[31:0], sbcs_geometry(sbcs)};
      expected = {DtpExpectedDtmcs, expected_geometry(t)};
      void'(geometry.expect_equal(
          DtpJ2aGeometryCheckId, observed, expected, $sformatf("%s DTMCS and sbcs geometry", t.name)
      ));
    end
    geometry.finalize();
  endtask

  // The geometry fields of an sbcs value (SBA version, address width, access
  // sizes), every other field 0.
  function bit [31:0] sbcs_geometry(bit [31:0] value);
    dtp_sbcs_t field_mask = '0;
    field_mask.sbversion   = '1;
    field_mask.sbasize     = '1;
    field_mask.sbaccess128 = 1'b1;
    field_mask.sbaccess64  = 1'b1;
    field_mask.sbaccess32  = 1'b1;
    field_mask.sbaccess16  = 1'b1;
    field_mask.sbaccess8   = 1'b1;
    return value & 32'(field_mask);
  endfunction

  // The sbcs geometry of `t` in the dtp_types table.
  // +DTP_J2A_GEOMETRY_NEGATIVE corrupts the expected address width so the
  // run must FAIL.
  function bit [31:0] expected_geometry(dtp_j2a_target_t t);
    bit        negative = (test_cfg != null) && test_cfg.j2a_geometry_negative;
    dtp_sbcs_t sbcs = '0;
    sbcs.sbversion  = 3'd1;
    sbcs.sbasize    = 7'(t.addr_width ^ int'(negative));
    sbcs.sbaccess64 = (t.data_width >= 64);
    sbcs.sbaccess32 = (t.data_width >= 32);
    sbcs.sbaccess16 = (t.data_width >= 16);
    sbcs.sbaccess8  = 1'b1;
    return 32'(sbcs);
  endfunction

  // CHK-J2A-GEOMETRY on one sbcs read of an active Debug Module.
  function void check_sbcs_geometry(dtp_j2a_target_t t, bit [31:0] sbcs, string context_s);
    ocah_axi_checker ev = evidence(t);
    bit       [31:0] observed = sbcs_geometry(sbcs);
    bit       [31:0] expected = expected_geometry(t);
    void'(ev.expect_equal(
        DtpJ2aGeometryCheckId,
        64'(observed),
        64'(expected),
        $sformatf(
            "%s target=%s sbcs=0x%08h", context_s, t.name, sbcs)
    ));
  endfunction

  // --- DMI access ------------------------------------------------------------

  // Idle in Run-Test/Idle for `tck_cycles` TCK cycles.
  task run_test_idle(int unsigned tck_cycles);
    bit tms[] = new[tck_cycles];
    bit tdi[] = new[tck_cycles];
    raw_walk(tms, tdi);
  endtask

  // One DMI scan of {address, data, op}; `captured` is the captured data.
  // The capture carries the sticky status, which CHK-J2A-FAULT-STATUS
  // compares with `status`.
  task dmi_scan(input dtp_j2a_target_t t, input bit [6:0] address, input bit [31:0] data,
                input dtp_dmi_op_e op, input string context_s, output bit [31:0] captured,
                input dtp_dmi_status_e status = DTP_DMI_SUCCESS);
    bit       [63:0] value;
    dtp_dmi_t        dmi;
    read_tdr(IrWidth'(t.dmi_instr), DtpDmiLen, value, dtp_j2a_pack_dmi(address, data, op));
    run_test_idle(DmiIdleTck);
    dmi = dtp_j2a_unpack_dmi(value);
    check_dmi_status(t, dmi.op, status, $sformatf("%s dmi_capture=0x%0h", context_s, value));
    captured = dmi.data;
  endtask

  // CHK-J2A-FAULT-STATUS on a captured DMI status or DTMCS dmistat.
  // +DTP_J2A_FAULT_STATUS_NEGATIVE swaps the expected status between success
  // and busy, so the run must fail.
  function void check_dmi_status(dtp_j2a_target_t t, bit [1:0] observed, dtp_dmi_status_e expected,
                                 string context_s);
    ocah_axi_checker       ev = evidence(t);
    bit              [1:0] exp = expected;
    if (test_cfg != null && test_cfg.j2a_fault_status_negative) exp ^= DTP_DMI_BUSY;
    void'(ev.expect_equal(
        DtpJ2aFaultStatusCheckId,
        64'(observed),
        64'(exp),
        $sformatf(
            "%s target=%s status", context_s, t.name)
    ));
  endfunction

  // CHK-J2A-DTM-CAPTURE on a capture without its status: a DMI capture's
  // address and data, or a DTMCS capture's other fields.
  // +DTP_J2A_DTM_CAPTURE_NEGATIVE flips the expected bit 0, so the run must
  // fail.
  function void check_dtm_capture(dtp_j2a_target_t t, bit [63:0] observed, bit [63:0] expected,
                                  string context_s);
    ocah_axi_checker ev = evidence(t);
    if (test_cfg != null && test_cfg.j2a_dtm_capture_negative) expected ^= 64'h1;
    void'(ev.expect_equal(
        DtpJ2aDtmCaptureCheckId,
        observed,
        expected,
        $sformatf(
            "%s target=%s observed=0x%0h expected=0x%0h", context_s, t.name, observed, expected)
    ));
  endfunction

  // One DTMCS scan shifting `shift_value`; judges the captured fields and
  // dmistat.
  task dtmcs_scan(dtp_j2a_target_t t, bit [31:0] shift_value, dtp_dmi_status_e status,
                  string context_s);
    bit [63:0] value;
    read_tdr(IrWidth'(t.dtmcs_instr), DtpDtmcsLen, value, 64'(shift_value));
    run_test_idle(DmiIdleTck);
    check_dmi_status(t, value[DtpDtmcsDmistatLsb+:2], status, {context_s, ".dmistat"});
    value[DtpDtmcsDmistatLsb+:2] = '0;
    check_dtm_capture(t, value, 64'(DtpExpectedDtmcs), {context_s, ".dtmcs"});
  endtask

  // --- raw DMI scans -----------------------------------------------------------

  // Load `t`'s DMI instruction and stop in Run-Test/Idle.
  task select_dmi(dtp_j2a_target_t t);
    load_ir(IrWidth'(t.dmi_instr));
    m_dr_chained = 1'b0;
  endtask

  // One DMI scan of {address, data, op} under the loaded DMI instruction,
  // from Run-Test/Idle or from Select-DR-Scan after a chained scan; ends in
  // Select-DR-Scan with `chain` and in Run-Test/Idle otherwise, with no idle
  // cycles. Judges the captured status against `status` and, with
  // `check_capture`, the captured address and data against `exp_address`
  // and `exp_data`.
  task dmi_raw(dtp_j2a_target_t t, bit [6:0] address, bit [31:0] data, dtp_dmi_op_e op,
               dtp_dmi_status_e status, string context_s, bit chain = 1'b0,
               bit check_capture = 1'b0, bit [6:0] exp_address = '0, bit [31:0] exp_data = '0);
    bit       [63:0] value = dtp_j2a_pack_dmi(address, data, op);
    int unsigned     lead = m_dr_chained ? 2 : 3;
    bit              tms         [] = new[lead + DtpDmiLen + 2];
    bit              tdi         [] = new[lead + DtpDmiLen + 2];
    bit              tdo         [];
    bit       [63:0] captured = '0;
    bit       [63:0] fields;
    dtp_dmi_t        dmi;
    // Select-DR-Scan, Capture-DR, Shift-DR; Exit1-DR on the last bit; Update-DR.
    if (!m_dr_chained) tms[0] = 1'b1;
    for (int unsigned i = 0; i < DtpDmiLen; i++) begin
      tms[lead+i] = (i == DtpDmiLen - 1);
      tdi[lead+i] = value[i];
    end
    tms[lead+DtpDmiLen]   = 1'b1;
    tms[lead+DtpDmiLen+1] = chain;
    raw_walk_tdo(tms, tdi, tdo);
    m_dr_chained = chain;
    for (int unsigned i = 0; i < DtpDmiLen; i++) captured[i] = tdo[lead+i];
    dmi       = dtp_j2a_unpack_dmi(captured);
    context_s = $sformatf("%s op=%s dmi_capture=0x%0h", context_s, op.name(), captured);
    check_dmi_status(t, dmi.op, status, context_s);
    fields = dtp_j2a_pack_dmi(dmi.address, dmi.data, '0) >> 2;
    if (check_capture)
      check_dtm_capture(t, fields, dtp_j2a_pack_dmi(exp_address, exp_data, '0) >> 2, context_s);
  endtask

  // A DMI scan from Select-DR-Scan that shifts no bit, so its update loads
  // its capture. Ends in Select-DR-Scan with `chain` and in Run-Test/Idle
  // otherwise.
  task dmi_zero_shift(bit chain = 1'b0);
    bit tms[] = '{1'b0, 1'b1, 1'b1, chain};
    bit tdi[] = new[4];
    if (!m_dr_chained)
      `uvm_fatal(get_type_name(), "dmi_zero_shift starts in Select-DR-Scan after a chained scan")
    raw_walk(tms, tdi);
    m_dr_chained = chain;
  endtask

  // Set `t`'s write (`b`) and read (`r`) response holds; the other bridges
  // keep theirs. Set a hold only while its channel shows the bridge no
  // response.
  function void hold_responses(dtp_j2a_target_t t, bit b, bit r);
    tb_vif.j2a_b_hold[t.reset_arm_bit] = b;
    tb_vif.j2a_r_hold[t.reset_arm_bit] = r;
  endfunction

  task dmi_write(dtp_j2a_target_t t, dtp_dm_reg_e address, bit [31:0] data, string context_s);
    bit [31:0] unused;
    dmi_scan(t, address, data, DTP_DMI_OP_WRITE, context_s, unused);
  endtask

  // Read one Debug Module register: the read, then a NOP scan that captures
  // its data.
  task dmi_read(input dtp_j2a_target_t t, input dtp_dm_reg_e address, input string context_s,
                output bit [31:0] data);
    dmi_scan(t, address, '0, DTP_DMI_OP_READ, context_s, data);
    dmi_scan(t, '0, '0, DTP_DMI_OP_NOP, {context_s, ".fetch"}, data);
  endtask

  // Set dmactive, which releases the System Bus Access registers from reset.
  task activate_dm(dtp_j2a_target_t t);
    dmi_write(t, DTP_DM_DMCONTROL, 32'h1, "activate_dm");
  endtask

  // --- System Bus Access -------------------------------------------------------

  // Program sbcs for `size` accesses, then sbaddress; with `is_read` the
  // sbaddress0 write starts the read.
  task sba_setup(dtp_j2a_target_t t, bit [63:0] addr, int unsigned size, bit is_read,
                 string context_s, bit autoincrement = 1'b0);
    dtp_sbcs_t       sbcs = '0;
    bit       [63:0] masked = addr & bit_mask(t.addr_width);
    sbcs.sbreadonaddr    = is_read;
    sbcs.sbaccess        = 3'(size);
    sbcs.sbautoincrement = autoincrement;
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {context_s, ".sbcs"});
    if (t.addr_width > 32)
      dmi_write(t, DTP_DM_SBADDRESS1, masked[63:32], {context_s, ".sbaddress1"});
    dmi_write(t, DTP_DM_SBADDRESS0, masked[31:0], {context_s, ".sbaddress0"});
  endtask

  // Poll sbcs until sbbusy clears, then require sberror 0 and sbbusyerror
  // `exp_sbbusyerror`. CHK-AXI-COMPLETION judges the SbaPolls bound and
  // CHK-J2A-FAULT-STATUS the two error fields.
  task wait_sba_idle(dtp_j2a_target_t t, string context_s, bit exp_sbbusyerror = 1'b0);
    ocah_axi_checker        ev = evidence(t);
    realtime                start = $realtime;
    bit              [31:0] value;
    dtp_sbcs_t              sbcs;
    bit              [63:0] errors;
    for (int unsigned poll = 0; poll < SbaPolls; poll++) begin
      dmi_read(t, DTP_DM_SBCS, context_s, value);
      sbcs = dtp_sbcs_t'(value);
      if (!sbcs.sbbusy) break;
    end
    void'(ev.expect_not_timed_out(
        "CHK-AXI-COMPLETION",
        sbcs.sbbusy,
        longint'(($realtime - start) / 1ns),
        $sformatf(
            "%s sbcs polls=%0d target=%s", context_s, SbaPolls, t.name)
    ));
    errors = 64'({sbcs.sberror, sbcs.sbbusyerror});
    void'(ev.expect_equal(
        DtpJ2aFaultStatusCheckId,
        errors,
        64'(exp_sbbusyerror),
        $sformatf(
            "%s target=%s (sberror, sbbusyerror)", context_s, t.name)
    ));
  endtask

  // Write the `size` word `data` at `addr` through System Bus Access and
  // judge the bus request.
  task sba_write(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, int unsigned size,
                 string context_s);
    sba_setup(t, addr, size, 1'b0, context_s);
    sba_write_data(t, addr, data, size, context_s);
  endtask

  // Write `data` to sbdata, which starts the `size` write at `addr`, the
  // address sbaddress holds, and judge the bus request.
  task sba_write_data(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data, int unsigned size,
                      string context_s);
    int unsigned offset = int'(addr % t.beat_bytes);
    bit [7:0] wstrb = 8'(dtp_j2a_full_wstrb(size) << offset);

    bit [63:0] masked = data & dtp_j2a_data_mask(size);
    bit [63:0] lanes = (masked << (8 * offset)) & bit_mask(t.data_width);
    if (target_enabled(t))
      target_cfgs[t.name].arm_expected_write(addr & bit_mask(t.addr_width), lanes, wstrb);
    if (size == 3) dmi_write(t, DTP_DM_SBDATA1, masked[63:32], {context_s, ".sbdata1"});
    dmi_write(t, DTP_DM_SBDATA0, masked[31:0], {context_s, ".sbdata0"});
    wait_sba_idle(t, context_s);
    expect_bus_request(t, 1'b0, addr, size, lanes, wstrb, context_s);
  endtask

  // Read the `size` word at `addr` through System Bus Access and judge the
  // bus request.
  task sba_read(input dtp_j2a_target_t t, input bit [63:0] addr, input int unsigned size,
                input string context_s, output bit [63:0] data, input bit autoincrement = 1'b0);
    bit [31:0] word;
    if (target_enabled(t)) target_cfgs[t.name].arm_expected_read(addr & bit_mask(t.addr_width));
    sba_setup(t, addr, size, 1'b1, context_s, autoincrement);
    wait_sba_idle(t, context_s);
    expect_bus_request(t, 1'b1, addr, size, '0, '0, context_s);
    dmi_read(t, DTP_DM_SBDATA0, {context_s, ".sbdata0"}, word);
    data = 64'(word);
    if (size == 3) begin
      dmi_read(t, DTP_DM_SBDATA1, {context_s, ".sbdata1"}, word);
      data[63:32] = word;
    end
  endtask

  // Write a seeded word at `addr` and another at the next beat, then read
  // `addr` back. The words differ, so a read that returns the first one read
  // `addr`. Every write is judged in the responder memory and the read on
  // the data the debugger fetches.
  task write_neighbour_then_read(input dtp_j2a_target_t t, input bit [63:0] addr,
                                 input string context_s, output bit [63:0] rdata,
                                 output bit [63:0] data);
    ocah_axi_checker        ev = evidence(t);
    int unsigned            size = t.default_size;
    bit              [63:0] other;
    data  = random_distinct_word(t);
    other = random_distinct_word(t, data);
    sba_write(t, addr, data, size, {context_s, ".write"});
    check_target_word(t, addr, data, size, {context_s, ".write.mem"});
    sba_write(t, addr + t.beat_bytes, other, size, {context_s, ".neighbour"});
    check_target_word(t, addr + t.beat_bytes, other, size, {context_s, ".neighbour.mem"});
    sba_read(t, addr, size, {context_s, ".read"}, rdata);
    void'(ev.expect_equal(
        "CHK-AXI-RDATA",
        rdata,
        data,
        $sformatf(
            "%s.read target=%s source=bridge_capture", context_s, t.name)
    ));
  endtask

  // --- data, address and responder helpers -------------------------------------

  function ocah_axi_checker evidence(dtp_j2a_target_t t);
    if (!target_evidence.exists(t.name) || target_evidence[t.name] == null)
      `uvm_fatal(get_type_name(), $sformatf("%s evidence recorder not plumbed by the test", t.name))
    return target_evidence[t.name];
  endfunction

  function bit target_enabled(dtp_j2a_target_t t);
    return !dtp_dbg_path_disabled(tb_vif.dbg_disable, t.dbg_path);
  endfunction

  // A seeded beat-aligned address: a responder slot under seeded address bits
  // above the responder window. The responder never sees the upper bits;
  // CHK-J2A-BUS-REQ judges them on the bus.
  function bit [63:0] random_target_addr(dtp_j2a_target_t t);
    bit [63:0] upper = ({$urandom(), $urandom()} << $clog2(
        DtpJ2aTargetMemBytes
    )) & bit_mask(
        t.addr_width
    );
    return upper | 64'($urandom_range(DtpJ2aTargetMemBytes / t.beat_bytes - 1) * t.beat_bytes);
  endfunction

  // A seeded data-width word, nonzero and different from `avoid`.
  function bit [63:0] random_distinct_word(dtp_j2a_target_t t, bit [63:0] avoid = '0);
    bit [63:0] word;
    do
    word = {$urandom(), $urandom()} & bit_mask(t.data_width);
    while (word == '0 || word == (avoid & bit_mask(
        t.data_width
    )));
    return word;
  endfunction

  // The bridge's responder sequence from the virtual sequencer.
  protected function ocah_axi_slave_sequence responder(string name);
    ocah_axi_slave_sequence seq = p_sequencer.axi_slave_seq(name);
    if (seq == null)
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s responder sequence not wired on the virtual sequencer", name))
    return seq;
  endfunction

  protected function int unsigned responder_bursts(string name);
    return responder(name).write_burst_count() + responder(name).read_burst_count();
  endfunction

  // CHK-AXI-WMEM: the responder word at `addr` equals `expected`, taken from
  // the stimulus.
  function void check_target_word(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] expected,
                                  int unsigned size, string context_s);
    ocah_axi_checker               ev = evidence(t);
    ocah_axi_slave_sequence        mem = responder(t.name);
    int unsigned                   len = dtp_j2a_size_bytes(size);
    bit                     [63:0] mask = dtp_j2a_data_mask(size);
    bit                     [63:0] observed = mem.read_int(addr, len) & mask;
    void'(ev.expect_equal(
        "CHK-AXI-WMEM",
        observed,
        expected & mask,
        $sformatf(
            "%s target=%s addr=0x%0h len=%0d source=intent", context_s, t.name, addr, len)
    ));
  endfunction

  // CHK-AXI-NONVAC: the responder behind `t` completed at least
  // `min_bursts` bursts this pass, so a tied-off, idle, or gated bridge
  // cannot satisfy the scenario whatever the sequence counted.
  function void check_responder_activity(dtp_j2a_target_t t, int unsigned min_bursts,
                                         string context_s);
    ocah_axi_checker ev = evidence(t);
    int unsigned     bursts = responder_bursts(t.name) - m_burst_baseline[t.name];
    void'(ev.expect_true(
        "CHK-AXI-NONVAC",
        bursts >= min_bursts,
        $sformatf(
            "%s target=%s responder_bursts=%0d min=%0d", context_s, t.name, bursts, min_bursts)
    ));
  endfunction

  // --- per-access bus-request ledger (CHK-J2A-BUS-REQ) -------------------------

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
    string               name = bus_ledger_target();
    dtp_axi_port_history port;
    m_ledger_target = "";
    if (name == "" || test_cfg == null || !test_cfg.requires_axi_id(name, DtpJ2aBusReqCheckId))
      return;
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

  // No transaction reached the port after the pass's last judged access, and
  // every other bridge port holds the counts it opened the pass with.
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

  // CHK-J2A-BUS-REQ: the port holds the counts of the pass's last judged
  // access. A no-op unless this pass's ledger accounts `t`.
  function void expect_no_bus_request(dtp_j2a_target_t t, string context_s);
    if (m_ledger_target == "" || m_ledger_target != t.name) return;
    void'(check_bus_counts(t.name, m_ledger_writes[t.name], m_ledger_reads[t.name], context_s));
  endfunction

  // Record the port's write and read counts against the expected ones.
  function bit check_bus_counts(string name, int unsigned exp_writes, int unsigned exp_reads,
                                string context_s);
    dtp_axi_port_history port = port_history(name);
    bit ok = record_bus_field(name, "writes", 64'(port.count(1'b0)), 64'(exp_writes), context_s);
    ok &= record_bus_field(name, "reads", 64'(port.count(1'b1)), 64'(exp_reads), context_s);
    return ok;
  endfunction

  // The test requires CHK-J2A-BUS-REQ on the ledger bridge's recorder, so
  // the records of every port land there.
  function bit record_bus_field(string name, string field, bit [63:0] observed, bit [63:0] expected,
                                string context_s);
    string detail = $sformatf("%s target=%s field=%s", context_s, name, field);
    return target_evidence[m_ledger_target].expect_equal(
        DtpJ2aBusReqCheckId, observed, expected, detail
    );
  endfunction

  // Wait until the port behind `t` has completed more than `completed`
  // transactions of one direction (bounded). The monitor publishes a write
  // at its B and a read at its last R, so the transaction's effect on the
  // subordinate is final.
  task wait_port_count(dtp_j2a_target_t t, bit is_read, int unsigned completed);
    dtp_axi_port_history port = port_history(t.name);
    for (int unsigned cycle = 0; cycle < PortWaitCycles; cycle++) begin
      if (port.count(is_read) > completed) return;
      wait_sys_cycles(1);
    end
  endtask

  // CHK-J2A-BUS-REQ: the access just issued completed exactly one
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
    if (m_ledger_target == "" || m_ledger_target != t.name) return;
    port = port_history(t.name);
    wait_port_count(t, is_read, is_read ? m_ledger_reads[t.name] : m_ledger_writes[t.name]);
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

endclass : dtp_jtag2axi_base_test_seq
