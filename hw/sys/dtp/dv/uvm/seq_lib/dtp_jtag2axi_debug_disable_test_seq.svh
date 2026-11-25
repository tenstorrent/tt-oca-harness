// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI debug disables and the security demultiplexer on every bridge.
// While a bridge's disable is 1 its demultiplexer sends each access to the
// error slave: the access ends with sberror 2, a read returns 0xBADCAB1E in
// each 32 bits, sbaddress keeps the failing address under sbautoincrement,
// and no request reaches the port. The bridge's DTMCS, DMI and Debug Module
// registers stay live, and alignment and size errors report 3 and 4 as when
// enabled. A pass runs these cases in a seeded order:
//
// - matrix: the eight combinations of the three disables, each bridge making
//   one access per combination, judged on its own port and on the other two;
// - live: the registers of a disabled bridge;
// - held: a disable set while the port holds an access, first with READY low
//   and then with the response held; the access completes on the port and
//   the next one on the error slave;
// - race: a disable changed some clk_i cycles after the Update-DR that starts
//   an access, in both directions, the delays closing in on the cycle the
//   access takes its path in; the access completes on exactly one path,
//   consistently on the port, in sberror and in the data;
// - reset: a system reset under a seeded mix of disables and one under its
//   complement; each bridge's first access takes the path its disable
//   selects.
//
// The cocotb twin is seq_lib/dtp_jtag2axi_debug_disable_test_seq.py.

class dtp_jtag2axi_debug_disable_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_debug_disable_test_seq)

  localparam bit [2:0] SberrorBus = 3'd2;
  localparam bit [2:0] SberrorAlign = 3'd3;
  localparam bit [2:0] SberrorSize = 3'd4;
  // READY low for longer than any held case lasts; the case releases it.
  localparam int unsigned ReadyHoldCycles = 1 << 20;
  // Races per bridge and direction, and the clk_i cycles past two TCK periods
  // after Update-DR that bound the first race window, and past the window
  // that a race drawn while the access is open lands in.
  localparam int unsigned Races = 6;
  localparam int unsigned RaceSpread = 16;

  typedef string names_t[$];

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_debug_disable_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    string cases[$] = '{"matrix", "live", "held", "race", "reset"};
    string names[$] = bridge_names();
    string order = "";
    seed_scenario_rng();
    `uvm_info(get_type_name(),
              "=== Debug disables and the security demultiplexer on every bridge ===", UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    cases.shuffle();
    foreach (cases[c]) begin
      case (cases[c])
        "matrix": matrix_case();
        "live":   live_case();
        "held":   held_case();
        "race":   race_case();
        default:  reset_case();
      endcase
      enable_all_debug();
      order = {order, " ", cases[c]};
    end
    foreach (names[n]) begin
      check_responder_activity(dtp_j2a_target_by_name(names[n]), 1, {names[n], ".debug_disable"});
    end
    `uvm_info(get_type_name(), $sformatf("Summary: Debug disables complete order=%s", order),
              UVM_LOW)
  endtask

  // --- cases -------------------------------------------------------------------

  // Each combination of the three disables in a seeded order, with one
  // seeded access per bridge. Each bridge reads and writes twice on each path
  // over the combinations.
  task matrix_case();
    int unsigned combos[$] = '{0, 1, 2, 3, 4, 5, 6, 7};
    bit          reads[3][8];
    combos.shuffle();
    for (int unsigned b = 0; b < 3; b++) begin
      for (int unsigned disabled = 0; disabled < 2; disabled++) begin
        bit ops[$] = '{1'b0, 1'b1, 1'b0, 1'b1};
        int unsigned k = 0;
        ops.shuffle();
        foreach (combos[c]) begin
          if (combos[c][b] == disabled[0]) reads[b][combos[c]] = ops[k++];
        end
      end
    end
    foreach (combos[c]) begin
      bit [2:0] disables = 3'(combos[c]);
      string    order[$] = bridge_names();
      set_bridge_disables(disables);
      order.shuffle();
      foreach (order[o]) begin
        dtp_j2a_target_t t = dtp_j2a_target_by_name(order[o]);
        string           ctx = $sformatf("%s.matrix%03b", t.name, disables);
        ledgered_access(t, reads[t.reset_arm_bit][combos[c]], disables[t.reset_arm_bit], ctx);
      end
    end
  endtask

  // With one bridge disabled at a time, its DTMCS, dmcontrol, sbcs, sbaddress
  // and sbdata1 stay readable and writable, and an alignment and a size error
  // report 3 and 4 with no request.
  task live_case();
    string names[$] = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      set_bridge_disables(3'b001 << t.reset_arm_bit);
      m_ledger = t.name;
      open_bus_ledger();
      live_registers(t, {t.name, ".live"});
      close_bus_ledger();
      m_ledger = "";
    end
  endtask

  // On each bridge the disable is set while the port holds an access, once
  // with READY low and once with the response held, a seeded one of them a
  // read.
  task held_case();
    string names[$] = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      bit              stall_read = 1'($urandom());
      for (int unsigned s = 0; s < 2; s++) begin
        set_bridge_disables('0);
        m_ledger = t.name;
        open_bus_ledger();
        held_switch(t, s == 0, (s == 0) ? stall_read : !stall_read);
        close_bus_ledger();
        m_ledger = "";
      end
    end
  endtask

  // On each bridge, Races accesses in each direction whose disable changes a
  // number of clk_i cycles after the Update-DR that starts them. The delays
  // close in on the cycle in which the access takes its path: two races in
  // three bisect the window between the latest delay that took the new path
  // and the earliest that took the old one, and the third draws a seeded
  // delay just past that window, while the access is open.
  task race_case();
    string       names[$] = bridge_names();
    int unsigned tck = tck_sys_ratio();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      bit              directions[$] = '{1'b0, 1'b1};
      int unsigned     early = 0;
      int unsigned     late = 2 * tck + RaceSpread;
      directions.shuffle();
      foreach (directions[d]) begin
        bit    reads[$];
        string direction = pick(directions[d], "disable", "enable");
        for (int unsigned r = 0; r < Races / 2; r++) begin
          reads.push_back(1'b0);
          reads.push_back(1'b1);
        end
        reads.shuffle();
        foreach (reads[i]) begin
          int unsigned delay;
          bit          on_port;
          string       ctx = $sformatf("%s.race.%s%0d", t.name, direction, i);
          if (i % 3 == 2) delay = $urandom_range(late + RaceSpread, late);
          else delay = (early + late + 1) / 2;
          m_ledger = t.name;
          open_bus_ledger();
          race_access(t, reads[i], directions[d], delay, ctx, on_port);
          close_bus_ledger();
          m_ledger = "";
          if (on_port != directions[d]) begin
            if (delay > early) early = delay;
            if (late <= early) late = early + 1;
          end else begin
            if (delay < late) late = delay;
            if (early >= late) early = late - 1;
          end
        end
      end
    end
  endtask

  // A system reset under a seeded mix of disables, at least one 0 and one 1,
  // then one under its complement: after each, each bridge's first access
  // takes the path its disable selects, and with every disable cleared each
  // reaches its port.
  task reset_case();
    string    names[$] = bridge_names();
    bit [2:0] mix;
    do mix = 3'($urandom()); while (mix == '0 || mix == '1);
    for (int unsigned r = 0; r < 2; r++) begin
      bit [2:0] disables = (r == 0) ? mix : ~mix;
      string    label = pick(r == 0, "mix", "complement");
      set_bridge_disables(disables);
      pulse_system_reset();
      foreach (names[n]) activate_dm(dtp_j2a_target_by_name(names[n]));
      for (int unsigned phase = 0; phase < 2; phase++) begin
        bit [2:0] setting = (phase == 0) ? disables : 3'b000;
        string    stage = pick(phase == 0, "held", "cleared");
        string    order[$] = bridge_names();
        set_bridge_disables(setting);
        order.shuffle();
        foreach (order[o]) begin
          dtp_j2a_target_t t = dtp_j2a_target_by_name(order[o]);
          string           ctx = $sformatf("%s.reset.%s.%s", t.name, label, stage);
          ledgered_access(t, 1'($urandom()), setting[t.reset_arm_bit], ctx);
        end
      end
    end
  endtask

  // --- building blocks ---------------------------------------------------------

  function string pick(bit condition, string if_set, string if_clear);
    return condition ? if_set : if_clear;
  endfunction

  function names_t bridge_names();
    return '{"smc_axi", "smc_otp", "sep_otp"};
  endfunction

  // Drive the three bridge disables, bit t.reset_arm_bit for bridge t, and
  // wait for the synchronizers.
  task set_bridge_disables(bit [2:0] disables);
    sep_lifecycle_ctrl_pkg::dbg_disable_t d = tb_vif.dbg_disable;
    string names[$] = bridge_names();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      dtp_dbg_path_set(d, t.dbg_path, disables[t.reset_arm_bit]);
    end
    set_dbg_disable(d);
  endtask

  // One seeded access under a ledger of t's port; the other ports keep their
  // counts.
  task ledgered_access(dtp_j2a_target_t t, bit is_read, bit disabled, string context_s);
    m_ledger = t.name;
    open_bus_ledger();
    if (disabled) disabled_access(t, is_read, context_s);
    else enabled_access(t, is_read, context_s);
    close_bus_ledger();
    m_ledger = "";
  endtask

  // A seeded legal access: its size, and its offset in the beat.
  function void seeded_access(input dtp_j2a_target_t t, output bit [63:0] addr,
                              output int unsigned size, output int unsigned offset);
    size   = $urandom_range(t.default_size);
    offset = $urandom_range(t.beat_bytes / dtp_j2a_size_bytes(size) - 1) * dtp_j2a_size_bytes(size);
    addr   = random_target_addr(t) + offset;
  endfunction

  // The responder's `size` word at `addr`.
  function bit [63:0] memory_word(dtp_j2a_target_t t, bit [63:0] addr, int unsigned size);
    return responder(t.name).read_int(addr, dtp_j2a_size_bytes(size)) & dtp_j2a_data_mask(size);
  endfunction

  // A seeded nonzero `size` word other than `avoid`.
  function bit [63:0] sized_word(int unsigned size, bit [63:0] avoid = '0);
    bit [63:0] word;
    do begin
      word = {$urandom(), $urandom()} & dtp_j2a_data_mask(size);
    end while (word == '0 || word == avoid);
    return word;
  endfunction

  // The error slave's read beat: 0xBADCAB1E in each 32 bits.
  function bit [63:0] err_slave_beat(dtp_j2a_target_t t);
    return {DtpJ2aErrSlaveWord, DtpJ2aErrSlaveWord} & bit_mask(t.data_width);
  endfunction

  // The sbdata bits read_sbdata returns: the Debug Module shifts the beat to
  // the access offset and keeps the bits above the access size.
  function bit [63:0] sbdata_mask(int unsigned size);
    return (size == 3) ? '1 : 64'hFFFF_FFFF;
  endfunction

  function void record_field(dtp_j2a_target_t t, string check_id, string field, bit [63:0] observed,
                             bit [63:0] expected, string context_s);
    void'(evidence(t).expect_equal(check_id, observed, expected,
                                   $sformatf("%s target=%s field=%s", context_s, t.name, field)));
  endfunction

  // A seeded access that reaches the port, judged on the bus and on its
  // data, with CHK-J2A-DBG-DISABLE recording that the port took it. A read
  // returns the bytes a full-beat write put there first; the passive AXI
  // checks compare every byte of the beat a read returns.
  task enabled_access(dtp_j2a_target_t t, bit is_read, string context_s);
    bit          [63:0] addr;
    bit          [63:0] data;
    bit          [63:0] beat;
    bit          [63:0] rdata;
    int unsigned        size;
    int unsigned        offset;
    int unsigned        port_start;
    int unsigned        moved;
    ocah_axi_checker    ev = evidence(t);
    string              ctx = {context_s, " enabled"};
    seeded_access(t, addr, size, offset);
    data = sized_word(size, memory_word(t, addr, size));
    if (is_read) begin
      beat = {$urandom(), $urandom()} & bit_mask(t.data_width);
      beat &= ~(dtp_j2a_data_mask(size) << (8 * offset));
      beat |= data << (8 * offset);
      sba_write(t, addr - offset, beat, t.default_size, {context_s, ".fill"});
    end
    port_start = port_history(t.name).count(is_read);
    if (is_read) begin
      sba_read(t, addr, size, {context_s, ".read"}, rdata);
      rdata &= dtp_j2a_data_mask(size);
      void'(ev.expect_equal(
          "CHK-AXI-RDATA",
          rdata,
          data,
          $sformatf(
              "%s.read target=%s source=bridge_capture", context_s, t.name)
      ));
    end else begin
      sba_write(t, addr, data, size, {context_s, ".write"});
      check_target_word(t, addr, data, size, {context_s, ".mem"});
    end
    moved = port_history(t.name).count(is_read) - port_start;
    record_field(t, DtpJ2aDbgDisableCheckId, "port_transactions", 64'(moved), 64'd1, ctx);
  endtask

  // A seeded access, under a seeded sbautoincrement, that ends on the error
  // slave: sberror 2, the error slave's data on a read, the responder word
  // unchanged on a write, sbaddress at the failing address, and no request
  // on the port.
  task disabled_access(dtp_j2a_target_t t, bit is_read, string context_s);
    bit          [63:0] addr;
    bit          [63:0] word;
    bit          [63:0] data;
    bit          [63:0] observed;
    int unsigned        size;
    int unsigned        offset;
    int unsigned        port_start;
    int unsigned        moved;
    string              ctx = {context_s, " disabled"};
    seeded_access(t, addr, size, offset);
    port_start = port_history(t.name).count(1'b0) + port_history(t.name).count(1'b1);
    word   = memory_word(t, addr, size);
    sba_setup(t, addr, size, is_read, context_s, 1'($urandom()));
    if (!is_read) begin
      data = sized_word(size, word);
      if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {context_s, ".sbdata1"});
      dmi_write(t, DTP_DM_SBDATA0, data[31:0], {context_s, ".sbdata0"});
    end
    wait_sba_idle(t, context_s, 1'b0, SberrorBus);
    expect_no_bus_request(t, context_s);
    moved = port_history(t.name).count(1'b0) + port_history(t.name).count(1'b1) - port_start;
    record_field(t, DtpJ2aDbgDisableCheckId, "port_transactions", 64'(moved), 64'd0, ctx);
    read_sbaddress(t, context_s, observed);
    record_field(t, DtpJ2aDbgDisableCheckId, "sbaddress", observed, addr & bit_mask(t.addr_width),
                 ctx);
    if (is_read) begin
      bit [63:0] expected = (err_slave_beat(t) >> (8 * offset)) & sbdata_mask(size);
      if (test_cfg != null && test_cfg.j2a_dbg_disable_negative) expected ^= 64'h1;
      read_sbdata(t, size, context_s, observed);
      record_field(t, DtpJ2aDbgDisableCheckId, "rdata", observed, expected, ctx);
    end else begin
      record_field(t, DtpJ2aDbgDisableCheckId, "memory", memory_word(t, addr, size), word, ctx);
    end
    clear_sberror(t, size, context_s);
  endtask

  // The registers of a disabled bridge.
  task live_registers(dtp_j2a_target_t t, string context_s);
    bit          [31:0] value;
    bit          [63:0] addr;
    bit          [63:0] observed;
    dtp_sbcs_t          sbcs = '0;
    int unsigned        size = $urandom_range(t.default_size);
    bit                 autoincrement = 1'($urandom());
    string              ctx = {context_s, " registers"};
    dtmcs_scan(t, '0, DTP_DMI_SUCCESS, {context_s, ".dtmcs"});
    dmi_write(t, DTP_DM_DMCONTROL, 32'h1, {context_s, ".dmcontrol"});
    dmi_read(t, DTP_DM_DMCONTROL, {context_s, ".dmcontrol"}, value);
    record_field(t, DtpJ2aDbgDisableCheckId, "dmcontrol", 64'(value[1:0]), 64'h1, ctx);
    sbcs.sbaccess        = 3'(size);
    sbcs.sbautoincrement = autoincrement;
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {context_s, ".sbcs"});
    dmi_read(t, DTP_DM_SBCS, {context_s, ".sbcs"}, value);
    check_sbcs_geometry(t, value, {context_s, ".sbcs"});
    sbcs = dtp_sbcs_t'(value);
    record_field(t, DtpJ2aDbgDisableCheckId, "sbaccess", 64'(sbcs.sbaccess), 64'(size), ctx);
    record_field(t, DtpJ2aDbgDisableCheckId, "sbautoincrement", 64'(sbcs.sbautoincrement),
                 64'(autoincrement), ctx);
    addr = {$urandom(), $urandom()} & bit_mask(t.addr_width);
    if (t.addr_width > 32) dmi_write(t, DTP_DM_SBADDRESS1, addr[63:32], {context_s, ".sbaddress1"});
    dmi_write(t, DTP_DM_SBADDRESS0, addr[31:0], {context_s, ".sbaddress0"});
    read_sbaddress(t, context_s, observed);
    record_field(t, DtpJ2aDbgDisableCheckId, "sbaddress", observed, addr, ctx);
    if (t.data_width > 32) begin
      bit [31:0] sbdata1 = $urandom();
      dmi_write(t, DTP_DM_SBDATA1, sbdata1, {context_s, ".sbdata1"});
      dmi_read(t, DTP_DM_SBDATA1, {context_s, ".sbdata1"}, value);
      record_field(t, DtpJ2aDbgDisableCheckId, "sbdata1", 64'(value), 64'(sbdata1), ctx);
    end
    refused_access(t, SberrorAlign, $urandom_range(t.default_size, 1), context_s);
    refused_access(t, SberrorSize, t.default_size + 1, context_s);
  endtask

  // An access the Debug Module refuses with `sberror` before any transfer:
  // misaligned for SberrorAlign, aligned to the access size otherwise, since
  // the alignment error takes precedence.
  task refused_access(dtp_j2a_target_t t, bit [2:0] sberror, int unsigned size, string context_s);
    string     ctx = $sformatf("%s.sberror%0d", context_s, sberror);
    bit [63:0] addr = random_target_addr(t) & ~((64'h1 << size) - 1);
    if (sberror == SberrorAlign) addr |= 64'h1;
    sba_setup(t, addr, size, 1'b0, ctx);
    dmi_write(t, DTP_DM_SBDATA0, $urandom(), {ctx, ".sbdata0"});
    wait_sba_idle(t, ctx, 1'b0, sberror);
    expect_no_bus_request(t, ctx);
    clear_sberror(t, size, ctx);
  endtask

  // Set the disable while the port holds an access: with `stall` READY stays
  // low, otherwise the response is held. The access completes on the port, a
  // read returning the word a write put there first, and the next access
  // ends on the error slave.
  task held_switch(dtp_j2a_target_t t, bit stall, bit is_read);
    string                                ctx = $sformatf("%s.held.%s.%s", t.name,
                                                          pick(stall, "ready", "response"),
                                                          pick(is_read, "read", "write"));
    string                                sw = {ctx, " switch"};
    int unsigned                          size = t.default_size;
    bit [63:0]                            addr = random_target_addr(t);
    bit [63:0]                            data = random_distinct_word(t, memory_word(t, addr, size));
    bit [63:0]                            observed;
    bit [7:0]                             wstrb = dtp_j2a_full_wstrb(size);
    bit [31:0]                            value;
    dtp_sbcs_t                            sbcs;
    int unsigned                          port_start;
    int unsigned                          moved;
    int unsigned                          valid_before;
    bit                                   open_at_switch;
    int unsigned                          expected_port;
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    if (is_read) sba_write(t, addr, data, size, {ctx, ".fill"});
    valid_before = valid_count(t, is_read);
    port_start = port_history(t.name).count(is_read);
    if (stall) begin
      ocah_axi_delays hold = new(0, 0, 0, 100, ReadyHoldCycles, ReadyHoldCycles);
      ocah_axi_delays none = new(0);
      apply_responder_timing(t, hold, hold, hold, none, none);
    end else begin
      hold_responses(t, !is_read, is_read);
    end
    if (is_read) begin
      target_cfgs[t.name].arm_expected_read(addr & bit_mask(t.addr_width));
      sba_setup(t, addr, size, 1'b1, ctx);
    end else begin
      target_cfgs[t.name].arm_expected_write(addr & bit_mask(t.addr_width), data, wstrb);
      sba_setup(t, addr, size, 1'b0, ctx);
      if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {ctx, ".sbdata1"});
      dmi_write(t, DTP_DM_SBDATA0, data[31:0], {ctx, ".sbdata0"});
    end
    open_at_switch = port_history(t.name).count(is_read) == port_start
        && valid_count(t, is_read) > valid_before;
    d = tb_vif.dbg_disable;
    dtp_dbg_path_set(d, t.dbg_path);
    set_dbg_disable(d);
    open_at_switch &= port_history(t.name).count(is_read) == port_start;
    dmi_read(t, DTP_DM_SBCS, {ctx, ".held_sbcs"}, value);
    sbcs = dtp_sbcs_t'(value);
    if (stall) clear_responder_timing(t);
    else hold_responses(t, 1'b0, 1'b0);
    expect_bus_request(t, is_read, addr, size, is_read ? '0 : data, is_read ? '0 : wstrb, ctx);
    wait_sba_idle(t, {ctx, ".released"});
    expected_port = (test_cfg != null && test_cfg.j2a_dbg_switch_negative) ? 0 : 1;
    record_field(t, DtpJ2aDbgSwitchCheckId, "open_at_switch", 64'(open_at_switch), 64'd1, sw);
    record_field(t, DtpJ2aDbgSwitchCheckId, "sbbusy_while_held", 64'(sbcs.sbbusy), 64'd1, sw);
    moved = port_history(t.name).count(is_read) - port_start;
    record_field(t, DtpJ2aDbgSwitchCheckId, "port_transactions", 64'(moved), 64'(expected_port),
                 sw);
    if (is_read) begin
      read_sbdata(t, size, ctx, observed);
      record_field(t, DtpJ2aDbgSwitchCheckId, "rdata", observed, data, sw);
    end else begin
      record_field(t, DtpJ2aDbgSwitchCheckId, "memory", memory_word(t, addr, size), data, sw);
    end
    disabled_access(t, !is_read, {ctx, ".next"});
  endtask

  // An access whose disable flips to `to_disabled` `delay` clk_i cycles after
  // the PTAP leaves the Update-DR that starts it. It completes on exactly one
  // path: on the port with sberror 0 and the responder's data, or on the
  // error slave with sberror 2 and its data. A read's slot holds a word
  // written first. `on_port` returns whether the port took it.
  task race_access(input dtp_j2a_target_t t, input bit is_read, input bit to_disabled,
                   input int unsigned delay, input string context_s, output bit on_port);
    string              sw = {context_s, " race"};
    int unsigned        size = t.default_size;
    bit [63:0]          addr = random_target_addr(t);
    bit [63:0]          word = memory_word(t, addr, size);
    bit [63:0]          data;
    bit [63:0]          observed;
    bit [7:0]           wstrb = dtp_j2a_full_wstrb(size);
    dtp_sbcs_t          sbcs = '0;
    int unsigned        port_start;
    int unsigned        moved;
    bit                 flipped;
    string              path;
    if (is_read) begin
      set_bridge_disables('0);
      word = random_distinct_word(t, word);
      sba_write(t, addr, word, size, {context_s, ".fill"});
    end
    data = random_distinct_word(t, word);
    set_bridge_disables(3'(!to_disabled) << t.reset_arm_bit);
    port_start = port_history(t.name).count(is_read);
    sbcs.sbreadonaddr = is_read;
    sbcs.sbaccess = 3'(size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {context_s, ".sbcs"});
    if (t.addr_width > 32) dmi_write(t, DTP_DM_SBADDRESS1, addr[63:32], {context_s, ".sbaddress1"});
    if (!is_read) begin
      dmi_write(t, DTP_DM_SBADDRESS0, addr[31:0], {context_s, ".sbaddress0"});
      if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {context_s, ".sbdata1"});
    end
    tb_vif.j2a_dis_race[t.reset_arm_bit] = 1'b1;
    fork
      begin
        flip_after_update(t, delay);
        flipped = 1'b1;
      end
    join_none
    if (is_read) dmi_write(t, DTP_DM_SBADDRESS0, addr[31:0], {context_s, ".sbaddress0"});
    else dmi_write(t, DTP_DM_SBDATA0, data[31:0], {context_s, ".sbdata0"});
    wait (flipped);
    tb_vif.j2a_dis_race[t.reset_arm_bit] = 1'b0;
    moved   = port_history(t.name).count(is_read) - port_start;
    on_port = moved == 1;
    path    = pick(on_port, "port", "error_slave");
    `uvm_info(get_type_name(), $sformatf("%s delay=%0d cycles path=%s", context_s, delay, path),
              UVM_LOW)
    wait_sba_idle(t, context_s, 1'b0, on_port ? 3'd0 : SberrorBus);
    if (on_port)
      expect_bus_request(t, is_read, addr, size, is_read ? '0 : data, is_read ? '0 : wstrb,
                         context_s);
    else expect_no_bus_request(t, context_s);
    record_field(t, DtpJ2aDbgSwitchCheckId, "port_transactions", 64'(moved <= 1), 64'd1, sw);
    if (is_read) begin
      read_sbdata(t, size, context_s, observed);
      record_field(t, DtpJ2aDbgSwitchCheckId, "rdata", observed, on_port ? word : err_slave_beat(t),
                   sw);
    end else begin
      record_field(t, DtpJ2aDbgSwitchCheckId, "memory", memory_word(t, addr, size),
                   on_port ? data : word, sw);
    end
    if (!on_port) clear_sberror(t, size, context_s);
  endtask

  // Toggle t's disable `delay` clk_i cycles after the PTAP next leaves
  // Update-DR.
  task flip_after_update(dtp_j2a_target_t t, int unsigned delay);
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    wait (tb_vif.tap_state == UPDATE_DR);
    wait (tb_vif.tap_state != UPDATE_DR);
    repeat (delay) @(posedge tb_vif.clk);
    d = tb_vif.dbg_disable;
    dtp_dbg_path_set(d, t.dbg_path, !dtp_dbg_path_disabled(d, t.dbg_path));
    tb_vif.drive_dbg_disable(d);
  endtask

  // Cycles t's port has raised ARVALID (`is_read`) or AWVALID.
  function int unsigned valid_count(dtp_j2a_target_t t, bit is_read);
    case (t.reset_arm_bit)
      0: return is_read ? tb_vif.smc_axi_arvalid_count : tb_vif.smc_axi_awvalid_count;
      1: return is_read ? tb_vif.smc_otp_axil_arvalid_count : tb_vif.smc_otp_axil_awvalid_count;
      default:
      return is_read ? tb_vif.sep_otp_axil_arvalid_count : tb_vif.sep_otp_axil_awvalid_count;
    endcase
  endfunction

  // sbdata0, and sbdata1 for an 8-byte access.
  task read_sbdata(input dtp_j2a_target_t t, input int unsigned size, input string context_s,
                   output bit [63:0] value);
    bit [31:0] word;
    dmi_read(t, DTP_DM_SBDATA0, {context_s, ".sbdata0"}, word);
    value = 64'(word);
    if (size == 3) begin
      dmi_read(t, DTP_DM_SBDATA1, {context_s, ".sbdata1"}, word);
      value[63:32] = word;
    end
  endtask

  // Clear sberror, keeping sbaccess `size`, and require sbcs idle with no
  // error.
  task clear_sberror(dtp_j2a_target_t t, int unsigned size, string context_s);
    dtp_sbcs_t sbcs = '0;
    sbcs.sberror  = 3'h7;
    sbcs.sbaccess = 3'(size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {context_s, ".clear"});
    wait_sba_idle(t, {context_s, ".cleared"});
  endtask

endclass : dtp_jtag2axi_debug_disable_test_seq
