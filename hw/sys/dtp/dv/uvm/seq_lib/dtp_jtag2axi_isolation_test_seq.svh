// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI instruction decode and the isolation between the bridges. Each
// pass first gives a seeded proper subset of the bridges the busy status and
// loads distinct DMI cells into the others, then scans each of the six bridge
// registers, in a seeded order, past its length: the capture is the selected
// bridge's own register, and TDO from the register length on is TDI. Then
// each bridge in turn is the victim. Its Debug Module and DMI cells are
// recorded, with a bus access held outstanding in odd passes, and its last
// DMI update leads straight into a seeded mix of scans of other instructions
// and of the other two bridges, with a complete access on each other bridge,
// one of them held in odd passes. The victim's DMI capture, dmistat, Debug
// Module registers and port counts are then unchanged, and each held access
// completes on its own port with its data once released. The cocotb twin is
// seq_lib/dtp_jtag2axi_isolation_test_seq.py.

class dtp_jtag2axi_isolation_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_isolation_test_seq)

  // Fewest and most bits a decode scan shifts past the register.
  localparam int unsigned ExtraBitsMin = 1;
  localparam int unsigned ExtraBitsMax = 32;
  // Fewest and most scans between the victim's last DMI update and its next
  // capture.
  localparam int unsigned DisturbScansMin = 4;
  localparam int unsigned DisturbScansMax = 8;
  // Fewest and most bits of a scan of a non-bridge instruction.
  localparam int unsigned OtherScanBitsMin = 8;
  localparam int unsigned OtherScanBitsMax = 32;
  localparam bit [31:0] DtmcsDmireset = 32'(1) << DtpDtmcsDmiresetBit;
  // The undefined opcodes, each of which selects BYPASS.
  localparam int unsigned UndefinedFirst = int'(UNDEFINED_BYPASS_21_INSTR);
  localparam int unsigned UndefinedLast = int'(UNDEFINED_BYPASS_3C_INSTR);

  // Scans of the other bridges and of non-bridge instructions that change no
  // DUT output, and an access on another bridge.
  typedef enum int unsigned {
    DISTURB_IDCODE,
    DISTURB_BYPASS,
    DISTURB_UNDEFINED,
    DISTURB_DTMCS,
    DISTURB_DMI_LOAD,
    DISTURB_DM_READ,
    DISTURB_ACCESS
  } disturb_kind_e;

  localparam int unsigned NumScanKinds = 6;

  typedef struct {
    disturb_kind_e kind;
    string         target;
  } disturb_item_t;

  // A bridge's DMI cells and sticky status.
  typedef struct {
    bit [6:0]        address;
    bit [31:0]       data;
    dtp_dmi_status_e status;
  } dmi_cell_t;

  // A bus access whose response a bridge's hold keeps from it.
  typedef struct {
    dtp_j2a_target_t t;
    bit              is_read;
    bit [63:0]       addr;
    int unsigned     size;
    int unsigned     offset;
    bit [63:0]       data;
  } held_access_t;

  // sbcs and sbaddress, and sbdata0 without a held access.
  typedef struct {
    bit [31:0] sbcs;
    bit [63:0] sbaddress;
    bit [31:0] sbdata0;
  } dm_state_t;

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_isolation_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  // Account `name`'s port from here on; on opening, every port holds the
  // counts the last ledger closed with.
  function void switch_ledger(string name);
    close_bus_ledger();
    m_ledger = name;
    open_bus_ledger();
  endfunction

  task body();
    names_t victims = bridge_names();
    bit     held = loop_index % 2 == 1;
    seed_scenario_rng();
    `uvm_info(get_type_name(), "=== JTAG2AXI instruction decode and isolation between bridges ===",
              UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    decode_step();
    victims.shuffle();
    foreach (victims[v]) isolation_case(dtp_j2a_target_by_name(victims[v]), held);
    switch_ledger("");
    foreach (victims[v])
      check_responder_activity(dtp_j2a_target_by_name(victims[v]), 1, {victims[v], ".isolation"});
    `uvm_info(get_type_name(), $sformatf("Summary: decode and isolation complete, held=%0b", held),
              UVM_LOW)
  endtask

  // --- decode ----------------------------------------------------------------

  // A seeded proper subset of the bridges takes the busy status and the
  // others load distinct DMI cells; each of the six registers is then scanned
  // past its length in a seeded order, and dmireset clears the busy statuses.
  task decode_step();
    names_t    names = bridge_names();
    names_t    order;
    bit        busy[string];
    dmi_cell_t cells[string];
    bit        is_dtmcs[$];
    int unsigned busy_count = $urandom_range(names.size() - 1, 1);
    order = names;
    order.shuffle();
    foreach (names[n]) busy[names[n]] = 1'b0;
    for (int unsigned i = 0; i < busy_count; i++) busy[order[i]] = 1'b1;
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      bit       [31:0] data;
      bit              taken;
      do begin
        data  = cell_data(t, busy[t.name]);
        taken = 1'b0;
        foreach (cells[c]) taken |= cells[c].data == data;
      end while (taken);
      if (busy[t.name]) begin
        take_busy_status(t, data, cells[t.name]);
      end else begin
        bit [31:0] unused;
        cells[t.name].address = 7'($urandom());
        cells[t.name].data    = data;
        cells[t.name].status  = DTP_DMI_SUCCESS;
        dmi_scan(t, cells[t.name].address, data, DTP_DMI_OP_NOP, {t.name, ".load"}, unused);
      end
    end
    order = {};
    foreach (names[n]) begin
      order.push_back(names[n]);
      order.push_back(names[n]);
      is_dtmcs.push_back(1'b0);
      is_dtmcs.push_back(1'b1);
    end
    for (int unsigned i = order.size() - 1; i > 0; i--) begin
      int unsigned j = $urandom_range(i);
      string       name = order[i];
      bit          dtmcs = is_dtmcs[i];
      order[i]    = order[j];
      is_dtmcs[i] = is_dtmcs[j];
      order[j]    = name;
      is_dtmcs[j] = dtmcs;
    end
    foreach (order[i]) decode_scan(dtp_j2a_target_by_name(order[i]), is_dtmcs[i], cells[order[i]]);
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      if (busy[t.name]) dtmcs_scan(t, DtmcsDmireset, DTP_DMI_BUSY, {t.name, ".clear"});
    end
  endtask

  // Seeded DMI cell data: for a bridge that takes the busy status, an
  // sbaddress0 value within its address width.
  function bit [31:0] cell_data(dtp_j2a_target_t t, bit busy);
    bit [31:0] data = $urandom();
    return busy ? 32'(64'(data) & bit_mask(t.addr_width)) : data;
  endfunction

  // A capture during an sbaddress0 read sets the busy status; the cells then
  // hold the read's address and the `sbaddress0` written first.
  task take_busy_status(input dtp_j2a_target_t t, input bit [31:0] sbaddress0,
                        output dmi_cell_t loaded);
    string     ctx = {t.name, ".busy"};
    dtp_sbcs_t sbcs = '0;
    sbcs.sbaccess = 3'd2;
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbcs"});
    dmi_write(t, DTP_DM_SBADDRESS0, sbaddress0, {ctx, ".setup"});
    select_dmi(t);
    dmi_raw(t, DTP_DM_SBADDRESS0, '0, DTP_DMI_OP_READ, DTP_DMI_SUCCESS, ctx, 1'b1);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_BUSY, ctx, 1'b0, 1'b1, DTP_DM_SBADDRESS0, '0);
    run_test_idle(DmiIdleTck);
    loaded.address = DTP_DM_SBADDRESS0;
    loaded.data    = sbaddress0;
    loaded.status  = DTP_DMI_BUSY;
  endtask

  // CHK-J2A-DECODE on one scan of a bridge register a seeded 1 to 32 bits
  // past its length: the low bits are the bridge's own capture, and TDO from
  // the register length on is the TDI shifted in first. The last
  // register-length bits shifted in leave the register unchanged.
  // +DTP_J2A_DECODE_NEGATIVE expects a register one bit longer, so the run
  // must fail.
  task decode_scan(dtp_j2a_target_t t, bit dtmcs, dmi_cell_t loaded);
    int unsigned        length = dtmcs ? DtpDtmcsLen : DtpDmiLen;
    int unsigned        extra = $urandom_range(ExtraBitsMax, ExtraBitsMin);
    int unsigned        delay = int'(test_cfg.j2a_decode_negative);
    bit          [31:0] tail;
    bit          [63:0] payload;
    bit          [63:0] capture;
    bit          [63:0] observed_capture = '0;
    bit          [31:0] observed_tail = '0;
    bit          [31:0] expected_tail;
    bit                 pattern [];
    bit                 observed[];
    string              ctx = $sformatf("%s.%s length=%0d extra=%0d", t.name,
                                        pick(dtmcs, "dtmcs", "dmi"), length, extra);
    do tail = 32'($urandom()) & 32'(bit_mask(extra)); while (tail == '0);
    if (dtmcs) begin
      payload = '0;
      capture = 64'(DtpExpectedDtmcs) | (64'(loaded.status) << DtpDtmcsDmistatLsb);
    end else begin
      payload = dtp_j2a_pack_dmi(loaded.address, loaded.data, DTP_DMI_OP_NOP);
      capture = dtp_j2a_pack_dmi(loaded.address, loaded.data, loaded.status);
    end
    pattern = new[length + extra];
    for (int unsigned i = 0; i < extra; i++) pattern[i] = tail[i];
    for (int unsigned i = 0; i < length; i++) pattern[extra+i] = payload[i];
    load_ir(IrWidth'(dtmcs ? t.dtmcs_instr : t.dmi_instr));
    shift_dr_wide(pattern, observed);
    for (int unsigned i = 0; i < length; i++) observed_capture[i] = observed[i];
    for (int unsigned i = 0; i < extra; i++) observed_tail[i] = observed[length+i];
    expected_tail = (tail << delay) & 32'(bit_mask(extra));
    record_field(t, DtpJ2aDecodeCheckId, "capture", observed_capture, capture, ctx);
    record_field(t, DtpJ2aDecodeCheckId, "passthrough", 64'(observed_tail), 64'(expected_tail),
                 ctx);
  endtask

  // --- isolation -------------------------------------------------------------

  // CHK-J2A-ISOLATION on `victim` across a seeded mix of scans and accesses
  // on everything else, with a bus access held on it, and on one other
  // bridge, when `held`.
  task isolation_case(dtp_j2a_target_t victim, bit held);
    string              ctx = $sformatf("%s.isolation.%s", victim.name, pick(held, "held", "idle"));
    held_access_t       holds[$];
    held_access_t       access;
    dm_state_t          dm_before;
    bit          [6:0]  address;
    bit          [31:0] data;
    int unsigned        writes;
    int unsigned        reads;
    `uvm_info(get_type_name(), $sformatf("Step 2: %s unchanged by other scans and accesses", ctx),
              UVM_LOW)
    switch_ledger(victim.name);
    if (held) begin
      start_held(victim, {ctx, ".start"}, access);
      holds.push_back(access);
    end else begin
      port_access(victim, 1'($urandom()), DtpJ2aIsolationCheckId, ctx);
    end
    dm_state(victim, held, {ctx, ".before"}, dm_before);
    writes = port_history(victim.name).count(1'b0);
    reads  = port_history(victim.name).count(1'b1);
    last_update(victim, dm_before, ctx, address, data);
    disturb(victim, held, ctx, holds);
    switch_ledger(victim.name);
    run_test_idle(DmiIdleTck);
    check_victim(victim, address, data, dm_before, writes, reads, held, {ctx, ".after"});
    holds.shuffle();
    foreach (holds[h]) begin
      switch_ledger(holds[h].t.name);
      release_held(holds[h], {ctx, ".release"});
    end
    switch_ledger("");
  endtask

  task dm_state(input dtp_j2a_target_t t, input bit held, input string ctx,
                output dm_state_t state);
    state = '{default: '0};
    dmi_read(t, DTP_DM_SBCS, {ctx, ".sbcs"}, state.sbcs);
    read_sbaddress(t, ctx, state.sbaddress);
    if (!held) dmi_read(t, DTP_DM_SBDATA0, {ctx, ".sbdata0"}, state.sbdata0);
  endtask

  // The victim's last DMI update before the disturbance, ending in
  // Run-Test/Idle with no idle cycles: a seeded op-0 load, or an sbaddress0
  // read. `address` and `data` are what its next capture shows.
  task last_update(input dtp_j2a_target_t victim, input dm_state_t dm_before, input string ctx,
                   output bit [6:0] address, output bit [31:0] data);
    string read_ctx = {ctx, ".read"};
    select_dmi(victim);
    if (1'($urandom())) begin
      address = 7'($urandom());
      data    = $urandom();
      dmi_raw(victim, address, data, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".load"});
    end else begin
      address = DTP_DM_SBADDRESS0;
      data    = dm_before.sbaddress[31:0];
      dmi_raw(victim, DTP_DM_SBADDRESS0, $urandom(), DTP_DMI_OP_READ, DTP_DMI_SUCCESS, read_ctx);
    end
  endtask

  // One access on each other bridge and seeded scans of the other bridges
  // and of non-bridge instructions, 4 to 8 in all, in a seeded order. With
  // `held` one seeded other bridge's access is held.
  task disturb(input dtp_j2a_target_t victim, input bit held, input string ctx,
               ref held_access_t holds[$]);
    names_t        others;
    disturb_item_t items[$];
    string         held_other = "";
    int unsigned   total = $urandom_range(DisturbScansMax, DisturbScansMin);
    names_t        names = bridge_names();
    foreach (names[n]) if (names[n] != victim.name) others.push_back(names[n]);
    if (held) held_other = others[$urandom_range(others.size()-1)];
    foreach (others[o]) items.push_back('{DISTURB_ACCESS, others[o]});
    while (items.size() < total) begin
      disturb_item_t item;
      item.kind   = disturb_kind_e'($urandom_range(NumScanKinds - 1));
      item.target = others[$urandom_range(others.size() - 1)];
      items.push_back(item);
    end
    items.shuffle();
    foreach (items[i]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(items[i].target);
      string           step_ctx = $sformatf("%s.%0d.%s", ctx, i, items[i].kind.name());
      if (items[i].kind == DISTURB_ACCESS) begin
        switch_ledger(t.name);
        if (t.name == held_other) begin
          held_access_t access;
          start_held(t, step_ctx, access);
          holds.push_back(access);
        end else begin
          port_access(t, 1'($urandom()), DtpJ2aIsolationCheckId, step_ctx);
        end
        switch_ledger(victim.name);
      end else begin
        disturb_scan(items[i].kind, t, step_ctx);
      end
    end
  endtask

  // One scan that leaves every DUT output as it is.
  task disturb_scan(disturb_kind_e kind, dtp_j2a_target_t t, string ctx);
    bit          [63:0] observed;
    bit          [31:0] unused;
    int unsigned        width = $urandom_range(OtherScanBitsMax, OtherScanBitsMin);
    case (kind)
      DISTURB_IDCODE, DISTURB_BYPASS, DISTURB_UNDEFINED: begin
        bit [IrWidth-1:0] instr;
        if (kind == DISTURB_IDCODE) instr = IrWidth'(IDCODE_INSTR);
        else if (kind == DISTURB_BYPASS)
          instr = 1'($urandom()) ? IrWidth'(BYPASS_INSTR) : IrWidth'(BYPASS_ALT_INSTR);
        else instr = IrWidth'($urandom_range(UndefinedLast, UndefinedFirst));
        load_ir(instr);
        shift_dr({$urandom(), $urandom()} & bit_mask(width), width, observed);
      end
      DISTURB_DTMCS: dtmcs_scan(t, 1'($urandom()) ? DtmcsDmireset : '0, DTP_DMI_SUCCESS, ctx);
      DISTURB_DMI_LOAD: dmi_scan(t, 7'($urandom()), $urandom(), DTP_DMI_OP_NOP, ctx, unused);
      default: dmi_read(t, 1'($urandom()) ? DTP_DM_SBCS : DTP_DM_DMCONTROL, ctx, unused);
    endcase
  endtask

  // A seeded read or write whose response t's hold keeps from the bridge.
  task start_held(input dtp_j2a_target_t t, input string ctx, output held_access_t access);
    bit          [63:0] masked;
    bit          [63:0] beat;
    bit          [63:0] lanes;
    bit          [7:0]  wstrb;
    int unsigned        held;
    bit                 reached;
    access.t       = t;
    access.is_read = 1'($urandom());
    seeded_access(t, access.addr, access.size, access.offset);
    access.data = sized_word(access.size, memory_word(t, access.addr, access.size));
    masked      = access.addr & bit_mask(t.addr_width);
    wstrb       = 8'(dtp_j2a_full_wstrb(access.size) << access.offset);
    lanes       = (access.data << (8 * access.offset)) & bit_mask(t.data_width);
    if (access.is_read) begin
      beat = {$urandom(), $urandom()} & bit_mask(t.data_width);
      beat &= ~(dtp_j2a_data_mask(access.size) << (8 * access.offset));
      beat |= access.data << (8 * access.offset);
      sba_write(t, access.addr - access.offset, beat, t.default_size, {ctx, ".fill"});
      target_cfgs[t.name].arm_expected_read(masked);
    end else begin
      target_cfgs[t.name].arm_expected_write(masked, lanes, wstrb);
    end
    held = held_count(t, access.is_read);
    hold_responses(t, !access.is_read, access.is_read);
    sba_setup(t, access.addr, access.size, access.is_read, ctx);
    if (!access.is_read) begin
      if (access.size == 3) dmi_write(t, DTP_DM_SBDATA1, access.data[63:32], {ctx, ".sbdata1"});
      dmi_write(t, DTP_DM_SBDATA0, access.data[31:0], {ctx, ".sbdata0"});
    end
    wait_response_held(t, access.is_read, held, reached);
    record_field(t, DtpJ2aIsolationCheckId, "held", 64'(reached), 64'd1, ctx);
  endtask

  // Release a held access; it completes on its own port with its data.
  task release_held(held_access_t access, string ctx);
    dtp_j2a_target_t        t = access.t;
    ocah_axi_checker        ev = evidence(t);
    bit              [63:0] lanes = (access.data << (8 * access.offset)) & bit_mask(t.data_width);
    bit              [7:0]  wstrb = 8'(dtp_j2a_full_wstrb(access.size) << access.offset);
    bit              [63:0] rdata;
    ctx = {ctx, ".", t.name};
    hold_responses(t, 1'b0, 1'b0);
    expect_bus_request(t, access.is_read, access.addr, access.size, access.is_read ? '0 : lanes,
                       access.is_read ? '0 : wstrb, ctx);
    wait_sba_idle(t, ctx);
    if (access.is_read) begin
      read_sbdata(t, access.size, ctx, rdata);
      rdata &= dtp_j2a_data_mask(access.size);
      void'(ev.expect_equal(
          "CHK-AXI-RDATA",
          rdata,
          access.data,
          $sformatf(
              "%s target=%s source=bridge_capture", ctx, t.name)
      ));
    end else begin
      check_target_word(t, access.addr, access.data, access.size, {ctx, ".mem"});
    end
  endtask

  // CHK-J2A-ISOLATION: the victim's DMI capture returns its last update's
  // address and data with status 0, dmistat reads 0, its port completed
  // nothing more, and its Debug Module registers read as before. The scan
  // that takes the capture loads the same address and data.
  // +DTP_J2A_ISOLATION_NEGATIVE expects the captured data inverted, so the
  // run must fail.
  task check_victim(dtp_j2a_target_t victim, bit [6:0] address, bit [31:0] data,
                    dm_state_t dm_before, int unsigned writes, int unsigned reads, bit held,
                    string ctx);
    bit        [63:0] observed;
    bit        [63:0] dtmcs;
    bit        [31:0] expected_data = data;
    dtp_dmi_t         captured;
    dm_state_t        dm_after;
    int unsigned      writes_after;
    int unsigned      reads_after;
    if (test_cfg.j2a_isolation_negative) expected_data = ~data;
    select_dmi(victim);
    shift_dr(dtp_j2a_pack_dmi(address, data, DTP_DMI_OP_NOP), DtpDmiLen, observed);
    captured = dtp_j2a_unpack_dmi(observed);
    read_tdr(IrWidth'(victim.dtmcs_instr), DtpDtmcsLen, dtmcs);
    writes_after = port_history(victim.name).count(1'b0);
    reads_after  = port_history(victim.name).count(1'b1);
    record_field(victim, DtpJ2aIsolationCheckId, "writes", 64'(writes_after), 64'(writes), ctx);
    record_field(victim, DtpJ2aIsolationCheckId, "reads", 64'(reads_after), 64'(reads), ctx);
    dm_state(victim, held, ctx, dm_after);
    record_field(victim, DtpJ2aIsolationCheckId, "dmi_address", 64'(captured.address), 64'(address),
                 ctx);
    record_field(victim, DtpJ2aIsolationCheckId, "dmi_data", 64'(captured.data), 64'(expected_data),
                 ctx);
    record_field(victim, DtpJ2aIsolationCheckId, "dmi_status", 64'(captured.op),
                 64'(DTP_DMI_SUCCESS), ctx);
    record_field(victim, DtpJ2aIsolationCheckId, "dmistat", 64'(dtmcs[DtpDtmcsDmistatLsb+:2]),
                 64'(DTP_DMI_SUCCESS), ctx);
    record_field(victim, DtpJ2aIsolationCheckId, "sbcs", 64'(dm_after.sbcs), 64'(dm_before.sbcs),
                 ctx);
    record_field(victim, DtpJ2aIsolationCheckId, "sbaddress", dm_after.sbaddress,
                 dm_before.sbaddress, ctx);
    if (!held)
      record_field(victim, DtpJ2aIsolationCheckId, "sbdata0", 64'(dm_after.sbdata0),
                   64'(dm_before.sbdata0), ctx);
  endtask

endclass : dtp_jtag2axi_isolation_test_seq
