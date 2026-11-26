// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI TAP resets and the bridge reset on every bridge. A TAP reset, by
// TRST, by five TMS-high cycles or by power-on reset, resets the bridges'
// DTMCS and DMI TDR cells but not the bridges: the DMI capture after it
// returns the last update's address and data with the sticky status, and the
// Debug Module keeps dmactive and its System Bus Access registers. The bridge
// reset, rst_n_i outside test mode and scan_rst_ni in it, returns every
// bridge to its reset state and drops the access in flight; outside test
// mode its release reaches clk_i and TCK each on the synchronizer's depth of
// that clock's rising edges, and in test mode it follows scan_rst_ni. A pass
// runs these cases in a seeded order:
//
// - tap_idle: on each bridge, a TAP reset from each source after an access;
// - tap_open: on each bridge, a TAP reset from each source while the port
//   holds an access, by READY or by a held response; the access completes on
//   the port;
// - tap_sticky: on each bridge, a TAP reset from each source with the sticky
//   busy status set, which survives it until a dmireset clears it;
// - bridge_access: on each bridge, the bridge reset in each phase of a read
//   and of a write: started and not at the port, the request or the write
//   data held by READY, a read's address just accepted with the response
//   owed, once released on the pulse's own clk_i edge and once held for
//   scans, the response held, and completed on the port before a scan
//   fetches the result;
// - scan_in_reset: on each bridge, DMI and DTMCS scans while the bridge reset
//   is asserted, and the TCK side's release once TCK runs again;
// - unreleased_hold: on each bridge, a read and a write whose response stays
//   held, sbbusy reading 1 past the poll bound until the bridge reset drops
//   the access;
// - test_mode: test_en set, in which every bridge reaches its port, keeps its
//   state through an rst_n_i pulse and resets on a scan_rst_ni pulse.
//
// Every reset is asserted and released at a seeded time between two clk_i
// edges, and released while TCK is stopped, except the read-armed reset: it
// asserts on the clk_i edge that completes the read's address handshake and,
// unless the sequence holds it, releases on a clk_i edge with TCK running.
// The cocotb twin is seq_lib/dtp_jtag2axi_reset_test_seq.py.

class dtp_jtag2axi_reset_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_reset_test_seq)

  // READY low for longer than any held access lasts; the case releases it.
  localparam int unsigned ReadyHoldCycles = 1 << 20;
  // Most clk_i cycles a reset stays asserted, and that the bridge reset lands
  // past the cycle its phase begins in.
  localparam int unsigned ResetHoldMax = 8;
  localparam int unsigned PhaseDelayMax = 4;
  // Most clk_i cycles TCK stays stopped, past twice the synchronizer depth,
  // after a release.
  localparam int unsigned TckStoppedMax = 16;
  localparam bit [2:0] AllBridges = 3'b111;
  localparam bit [31:0] Dmireset = 32'h1 << DtpDtmcsDmiresetBit;

  // A bridge's state or a capture, by field name.
  typedef bit [63:0] fields_t[string];

  protected string       m_ledger;
  protected int unsigned m_release_errors;

  function new(string name = "dtp_jtag2axi_reset_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    string cases[$] = '{
        "tap_idle",
        "tap_open",
        "tap_sticky",
        "bridge_access",
        "scan_in_reset",
        "unreleased_hold",
        "test_mode"
    };
    string names[$] = bridge_names();
    string order = "";
    seed_scenario_rng();
    `uvm_info(get_type_name(), "=== TAP resets and the bridge reset on every bridge ===", UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    m_release_errors = tb_vif.j2a_release_err_count;
    cases.shuffle();
    foreach (cases[c]) begin
      case (cases[c])
        "tap_idle":      tap_idle_case();
        "tap_open":      tap_open_case();
        "tap_sticky":    tap_sticky_case();
        "bridge_access": bridge_access_case();
        "scan_in_reset": scan_in_reset_case();
        "unreleased_hold": unreleased_hold_case();
        default:         test_mode_case();
      endcase
      order = {order, " ", cases[c]};
    end
    foreach (names[n]) begin
      check_responder_activity(dtp_j2a_target_by_name(names[n]), 1, {names[n], ".reset"});
    end
    `uvm_info(get_type_name(),
              $sformatf("Summary: TAP and bridge resets complete order=%s", order), UVM_LOW)
  endtask

  // --- cases -------------------------------------------------------------------

  // On each bridge, a TAP reset from each source in a seeded order after a
  // seeded access and a NOP scan of a seeded address and data. The DMI
  // capture then returns that address and data with status 0, dmistat reads
  // 0, dmactive and the System Bus Access registers keep their values, and
  // the next access reaches the port without a dmactive write.
  task tap_idle_case();
    names_t names = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      names_t          sources = tap_sources();
      sources.shuffle();
      foreach (sources[s]) begin
        string            ctx = $sformatf("%s.tap_idle.%s", t.name, sources[s]);
        bit        [6:0] peek_address = 7'($urandom());
        bit        [31:0] peek_data = $urandom();
        bit        [31:0] unused;
        fields_t          prior;
        fields_t          after;
        fields_t          capture;
        open_ledger(t);
        activate_dm(t);
        port_access(t, 1'($urandom()), DtpJ2aTapResetCheckId, {ctx, ".access"});
        bridge_state(t, {ctx, ".before"}, prior);
        dmi_scan(t, peek_address, peek_data, DTP_DMI_OP_NOP, {ctx, ".peek"}, unused);
        tap_reset_from(sources[s]);
        bridge_state(t, {ctx, ".after"}, after, peek_address, peek_data);
        capture = tap_capture(peek_address, peek_data, DTP_DMI_SUCCESS);
        foreach (capture[k]) prior[k] = capture[k];
        check_bridge_state(t, DtpJ2aTapResetCheckId, after, prior, ctx);
        port_access(t, 1'($urandom()), DtpJ2aTapResetCheckId, {ctx, ".next"});
        close_ledger();
      end
    end
  endtask

  // On each bridge, a TAP reset from each source in a seeded order while the
  // port holds a seeded read or write, by READY low or by a held response;
  // power-on reset holds by READY, since it clears the response holds. The
  // access completes on the port with its data, and the DMI capture after
  // the reset returns the update that started it.
  task tap_open_case();
    names_t names = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      names_t          sources = tap_sources();
      sources.shuffle();
      foreach (sources[s]) begin
        bit    is_read = 1'($urandom());
        bit    stall = sources[s] == "por" || 1'($urandom());
        string ctx = $sformatf("%s.tap_open.%s.%s.%s", t.name, sources[s],
                               pick(stall, "ready", "response"), pick(is_read, "read", "write"));
        open_ledger(t);
        activate_dm(t);
        open_access_reset(t, is_read, stall, sources[s], ctx);
        close_ledger();
      end
    end
  endtask

  // On each bridge, a TAP reset from each source in a seeded order with the
  // sticky busy status set. The DMI capture keeps its address, data and
  // status 3 through the reset, dmistat reads 3, a dmireset clears the
  // status, and the next access reaches the port.
  task tap_sticky_case();
    names_t names = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      names_t          sources = tap_sources();
      sources.shuffle();
      foreach (sources[s]) begin
        string          ctx = $sformatf("%s.tap_sticky.%s", t.name, sources[s]);
        dtp_dmi_t       held;
        dtp_dmi_t       after;
        dtp_dmi_t       cleared;
        bit       [1:0] dmistat;
        fields_t        expected;
        open_ledger(t);
        activate_dm(t);
        raise_sticky_busy(t, ctx);
        dmi_capture(t, '0, '0, held);
        tap_reset_from(sources[s]);
        dmi_capture(t, '0, '0, after);
        read_dmistat(t, Dmireset, ctx, dmistat);
        dmi_capture(t, held.address, held.data, cleared);
        expected = tap_capture(held.address, held.data, DTP_DMI_BUSY);
        check_bridge_state(t, DtpJ2aTapResetCheckId, capture_fields(after), expected, ctx);
        record_field(t, DtpJ2aTapResetCheckId, "dmistat", 64'(dmistat), 64'(DTP_DMI_BUSY), ctx);
        record_field(t, DtpJ2aTapResetCheckId, "cleared_status", 64'(cleared.op),
                     64'(DTP_DMI_SUCCESS), ctx);
        port_access(t, 1'($urandom()), DtpJ2aTapResetCheckId, {ctx, ".next"});
        close_ledger();
      end
    end
  endtask

  // On each bridge, the bridge reset in each phase of a read and of a write,
  // in a seeded order.
  task bridge_access_case();
    string  phases[11] = '{
        "launched",
        "request",
        "armed",
        "armed_held",
        "response",
        "done",
        "launched",
        "request",
        "w",
        "response",
        "done"
    };
    names_t names = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      int unsigned     order[$];
      for (int unsigned i = 0; i < 11; i++) order.push_back(i);
      order.shuffle();
      foreach (order[i]) begin
        bit    is_read = order[i] < 6;
        string phase = phases[order[i]];
        string ctx = $sformatf("%s.bridge_access.%s.%s", t.name, pick(is_read, "read", "write"),
                               phase);
        open_ledger(t);
        reset_access(t, is_read, phase, ctx);
        close_ledger();
      end
    end
  endtask

  // On each bridge, scans while the bridge reset is asserted: DTMCS with
  // dmireset reads dmistat 0, and DMI writes of dmactive and of a seeded
  // sbaddress0 capture 0. None of them takes effect: after the release the
  // bridge reads its reset state. TCK stays stopped for a seeded number of
  // clk_i cycles after the release, in which the clk_i side leaves reset and
  // the TCK side does not.
  task scan_in_reset_case();
    names_t names = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t        t = dtp_j2a_target_by_name(names[n]);
      string                  ctx = {t.name, ".scan_in_reset"};
      logic            [31:0] j2a_before;
      bit              [63:0] value;
      open_ledger(t);
      activate_dm(t);
      write_sbaddress0(t, ctx, value);
      j2a_before = tb_vif.j2a_rst_assert_count;
      drive_reset(1'b0, 1'b0);
      scan_in_reset(t, ctx);
      release_and_check(t, j2a_before, ctx);
      recover(t, ctx);
      close_ledger();
    end
  endtask

  // On each bridge, a full-beat read and write in a seeded order, each with
  // its response held: sbcs reads sbbusy 1 past the poll bound, the bridge
  // reset lands while the response is held, and the hold is cleared while
  // the reset is asserted. After the release the bridge reads its reset
  // state, the held response never reached it, and the next access reaches
  // the port.
  task unreleased_hold_case();
    names_t names = bridge_names();
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      bit              first_read = 1'($urandom());
      for (int unsigned i = 0; i < 2; i++) begin
        bit    is_read = first_read ^ 1'(i);
        string ctx = $sformatf("%s.unreleased_hold.%s", t.name, pick(is_read, "read", "write"));
        open_ledger(t);
        unreleased_hold(t, is_read, ctx);
        close_ledger();
      end
    end
  endtask

  // With test_en 1: every bridge reaches its port; an rst_n_i pulse with the
  // bridges idle leaves the synchronized resets high and each bridge's
  // dmactive, sbaddress0 and sticky status in place; a scan_rst_ni pulse
  // resets every bridge, its synchronized resets following it with no clock
  // edge. With test_en back at 0 and dmactive set again, every bridge reaches
  // its port.
  task test_mode_case();
    names_t           names = bridge_names();
    bit       [63:0]  sbaddress[string];
    dtp_dmi_t         kept[string];
    dtp_j2a_target_t  first;
    names.shuffle();
    first = dtp_j2a_target_by_name(names[0]);
    set_test_mode(1'b1);
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      string           ctx = {t.name, ".test_mode"};
      open_ledger(t);
      activate_dm(t);
      port_access(t, 1'($urandom()), DtpJ2aBridgeResetCheckId, {ctx, ".access"});
      write_sbaddress0(t, ctx, sbaddress[t.name]);
      raise_sticky_busy(t, ctx);
      dmi_capture(t, '0, '0, kept[t.name]);
      close_ledger();
    end
    pulse_in_test_mode(1'b0, first);
    foreach (names[n]) begin
      dtp_j2a_target_t        t = dtp_j2a_target_by_name(names[n]);
      string                  ctx = {t.name, ".test_mode.rst_n"};
      dtp_dmi_t               after;
      bit              [1:0] dmistat;
      bit              [31:0] dmcontrol;
      bit              [31:0] observed;
      bit                     dmactive = kept_dmactive(1'b1);
      open_ledger(t);
      dmi_capture(t, '0, '0, after);
      read_dmistat(t, Dmireset, ctx, dmistat);
      dmi_read(t, DTP_DM_DMCONTROL, {ctx, ".dmcontrol"}, dmcontrol);
      dmi_read(t, DTP_DM_SBADDRESS0, {ctx, ".sbaddress0"}, observed);
      record_field(t, DtpJ2aBridgeResetCheckId, "capture", 64'(after), 64'(kept[t.name]), ctx);
      record_field(t, DtpJ2aBridgeResetCheckId, "dmistat", 64'(dmistat), 64'(DTP_DMI_BUSY), ctx);
      record_field(t, DtpJ2aBridgeResetCheckId, "dmactive", 64'(dmcontrol[0]), 64'(dmactive), ctx);
      record_field(t, DtpJ2aBridgeResetCheckId, "sbaddress0", 64'(observed), sbaddress[t.name],
                   ctx);
      port_access(t, 1'($urandom()), DtpJ2aBridgeResetCheckId, {ctx, ".access"});
      close_ledger();
    end
    pulse_in_test_mode(1'b1, first);
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      string           ctx = {t.name, ".test_mode.scan_rst"};
      fields_t         state;
      open_ledger(t);
      bridge_state(t, ctx, state);
      check_bridge_state(t, DtpJ2aBridgeResetCheckId, state, reset_state(), ctx);
      close_ledger();
    end
    set_test_mode(1'b0);
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      open_ledger(t);
      recover(t, {t.name, ".test_mode.exit"});
      close_ledger();
    end
  endtask

  // --- TAP resets --------------------------------------------------------------

  function names_t tap_sources();
    return '{"tlr", "trst", "por"};
  endfunction

  // Reset the TAP from `source`: five TMS-high cycles to Test-Logic-Reset,
  // TRST changed with TCK stopped and held over a seeded number of TCK
  // cycles, or power-on reset followed by the settle of the debug-disable
  // synchronizers it set; then step to Run-Test/Idle.
  task tap_reset_from(string source);
    bit [15:0] state_under_por;
    bit        trst_n_under_por;
    case (source)
      "tlr": goto_tlr_via_tms();
      "trst": begin
        set_trst(1'b0, $urandom_range(4, 1));
        set_trst(1'b1);
      end
      default: begin
        pulse_por($urandom_range(4, 1), state_under_por, trst_n_under_por);
        enable_all_debug();
      end
    endcase
    step(1'b0);
  endtask

  // The DMI capture a TAP reset leaves: `address` and `data` with `status`.
  // +DTP_J2A_TAP_RESET_NEGATIVE expects the capture the bridge reset leaves,
  // 0, so the run must fail.
  function fields_t tap_capture(bit [6:0] address, bit [31:0] data, dtp_dmi_status_e status);
    fields_t f;
    bit      negative = test_cfg.j2a_tap_reset_negative;
    f["capture_address"] = negative ? '0 : 64'(address);
    f["capture_data"]    = negative ? '0 : 64'(data);
    f["capture_status"]  = negative ? '0 : 64'(status);
    return f;
  endfunction

  // A full-beat read or write held at the port across a TAP reset from
  // `source`. A read's slot holds a word written first.
  task open_access_reset(dtp_j2a_target_t t, bit is_read, bit stall, string source, string ctx);
    int unsigned        size = t.default_size;
    bit          [63:0] addr = random_target_addr(t);
    bit          [63:0] data = random_distinct_word(t, memory_word(t, addr, size));
    bit          [63:0] masked = addr & bit_mask(t.addr_width);
    bit          [7:0] wstrb = dtp_j2a_full_wstrb(size);
    bit          [6:0] update_address;
    bit          [31:0] update_data;
    bit          [63:0] observed;
    int unsigned        valid_before;
    int unsigned        port_start;
    int unsigned        moved;
    bit                 open_at_reset;
    dtp_dmi_t           captured;
    fields_t            expected;
    if (is_read) sba_write(t, addr, data, size, {ctx, ".fill"});
    valid_before = valid_count(t, is_read);
    port_start   = port_history(t.name).count(is_read);
    hold_port(t, is_read, stall);
    if (is_read) begin
      target_cfgs[t.name].arm_expected_read(masked);
      sba_setup(t, addr, size, 1'b1, ctx);
      update_address = DTP_DM_SBADDRESS0;
      update_data    = masked[31:0];
    end else begin
      target_cfgs[t.name].arm_expected_write(masked, data, wstrb);
      sba_setup(t, addr, size, 1'b0, ctx);
      if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {ctx, ".sbdata1"});
      dmi_write(t, DTP_DM_SBDATA0, data[31:0], {ctx, ".sbdata0"});
      update_address = DTP_DM_SBDATA0;
      update_data    = data[31:0];
    end
    open_at_reset = port_history(t.name).count(is_read) == port_start &&
        valid_count(t, is_read) > valid_before;
    tap_reset_from(source);
    dmi_capture(t, update_address, update_data, captured);
    open_at_reset &= port_history(t.name).count(is_read) == port_start;
    release_port(t);
    expect_bus_request(t, is_read, addr, size, is_read ? '0 : data, is_read ? '0 : wstrb, ctx);
    wait_sba_idle(t, {ctx, ".released"});
    moved = port_history(t.name).count(is_read) - port_start;
    expected = tap_capture(update_address, update_data, DTP_DMI_SUCCESS);
    check_bridge_state(t, DtpJ2aTapResetCheckId, capture_fields(captured), expected, ctx);
    record_field(t, DtpJ2aTapResetCheckId, "open_at_reset", 64'(open_at_reset), 64'd1, ctx);
    record_field(t, DtpJ2aTapResetCheckId, "port_transactions", 64'(moved), 64'd1, ctx);
    if (is_read) begin
      read_sbdata(t, size, ctx, observed);
      record_field(t, DtpJ2aTapResetCheckId, "rdata", observed, data, ctx);
    end else begin
      record_field(t, DtpJ2aTapResetCheckId, "memory", memory_word(t, addr, size), data, ctx);
    end
  endtask

  // Set the sticky busy status: a dmcontrol write of dmactive 1 whose scan
  // chains into a scan that captures while the write is in progress.
  task raise_sticky_busy(dtp_j2a_target_t t, string ctx);
    select_dmi(t);
    dmi_raw(t, DTP_DM_DMCONTROL, 32'h1, DTP_DMI_OP_WRITE, DTP_DMI_SUCCESS, {ctx, ".sticky"}, 1'b1);
    dmi_zero_shift();
    run_test_idle(DmiIdleTck);
  endtask

  // --- the bridge reset ----------------------------------------------------------

  // A full-beat read or write with the bridge reset asserted in `phase` and
  // released with TCK stopped. Before dmactive is written again the bridge
  // reads its reset state, and the port completes the access only when the
  // reset found it completed. A read's slot holds a word written first.
  task reset_access(dtp_j2a_target_t t, bit is_read, string phase, string ctx);
    int unsigned            size = t.default_size;
    bit          [63:0]     addr = random_target_addr(t);
    bit          [63:0]     data = random_distinct_word(t, memory_word(t, addr, size));
    bit          [63:0]     masked = addr & bit_mask(t.addr_width);
    bit          [7:0]     wstrb = dtp_j2a_full_wstrb(size);
    bit                     completed = phase == "done";
    string                  port_ctx = {ctx, " port"};
    dtp_dm_reg_e            start_reg;
    bit          [31:0]     start_value;
    dtp_sbcs_t              sbcs = '0;
    int unsigned            port_start;
    int unsigned            moved;
    logic        [31:0]     j2a_before;
    logic        [31:0]     sys_before;
    bit                     began;
    bit          [63:0]     valid_cycles;
    activate_dm(t);
    if (is_read) begin
      sba_write(t, addr, data, size, {ctx, ".fill"});
      start_reg   = DTP_DM_SBADDRESS0;
      start_value = masked[31:0];
    end else begin
      start_reg   = DTP_DM_SBDATA0;
      start_value = data[31:0];
    end
    if (phase == "request" || phase == "w") hold_port(t, is_read, 1'b1, phase == "w");
    else if (phase == "response") hold_port(t, is_read, 1'b0);
    sbcs.sbreadonaddr = is_read;
    sbcs.sbaccess     = 3'(size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbcs"});
    if (t.addr_width > 32) dmi_write(t, DTP_DM_SBADDRESS1, masked[63:32], {ctx, ".sbaddress1"});
    if (!is_read) begin
      dmi_write(t, DTP_DM_SBADDRESS0, masked[31:0], {ctx, ".sbaddress0"});
      if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {ctx, ".sbdata1"});
    end
    if (completed && is_read) target_cfgs[t.name].arm_expected_read(masked);
    if (completed && !is_read) target_cfgs[t.name].arm_expected_write(masked, data, wstrb);
    port_start = port_history(t.name).count(is_read);
    j2a_before = tb_vif.j2a_rst_assert_count;
    sys_before = tb_vif.sys_rst_assert_count;
    if (completed) begin
      dmi_write(t, start_reg, start_value, {ctx, ".start"});
      wait_port_count(t, is_read, port_start);
      began = port_history(t.name).count(is_read) > port_start;
      repeat ($urandom_range(PhaseDelayMax)) @(posedge tb_vif.clk);
      drive_reset(1'b0, 1'b0);
    end else if (phase == "armed" || phase == "armed_held") begin
      armed_start(t, start_reg, start_value, sys_before, phase == "armed_held", ctx, began);
    end else begin
      bit asserted = 1'b0;
      fork
        begin
          reset_in_phase(t, is_read, phase, began);
          asserted = 1'b1;
        end
      join_none
      dmi_write(t, start_reg, start_value, {ctx, ".start"});
      wait (asserted);
    end
    release_port(t);
    moved = port_history(t.name).count(is_read) - port_start;
    if (phase == "armed") check_released(t, j2a_before, 1'b0, ctx);
    else release_and_check(t, j2a_before, ctx);
    if (completed)
      expect_bus_request(t, is_read, addr, size, is_read ? '0 : data, is_read ? '0 : wstrb, ctx);
    else expect_no_bus_request(t, ctx);
    record_field(t, DtpJ2aBridgeResetCheckId, "phase_reached", 64'(began), 64'd1, port_ctx);
    record_field(t, DtpJ2aBridgeResetCheckId, "port_transactions", 64'(moved), 64'(completed),
                 port_ctx);
    valid_cycles = 64'(response_valid_cycles(t, is_read));
    record_field(t, DtpJ2aBridgeResetCheckId, "response_valid_cycles", valid_cycles, 64'd0,
                 port_ctx);
    recover(t, ctx);
  endtask

  // Start a read with rst_n_i armed to assert for a seeded number of clk_i
  // cycles from the edge that completes its AR handshake, so the reset lands
  // while the responder owes the R; `began` returns whether it asserted since
  // the rst_n_i assertion counter read `sys_before`. With `held` the sequence
  // holds the reset from a seeded time before the pulse's first clk_i edge
  // and scans the bridge in it.
  task armed_start(input dtp_j2a_target_t t, input dtp_dm_reg_e start_reg,
                   input bit [31:0] start_value, input logic [31:0] sys_before, input bit held,
                   input string ctx, output bit began);
    int unsigned period_ps = tb_vif.clk_period_ns * 1000;
    int unsigned delay_ps = $urandom_range(period_ps - 1, 1);
    bit          holding = 1'b0;
    process      hold;
    arm_reset_on_read(t, $urandom_range(ResetHoldMax, 1));
    if (held) begin
      fork
        begin
          hold = process::self();
          @(negedge tb_vif.rst_n);
          #(delay_ps * 1ps);
          tb_vif.sys_rst_n = 1'b0;
          holding = 1'b1;
        end
      join_none
    end
    dmi_write(t, start_reg, start_value, {ctx, ".start"});
    for (int unsigned c = 0; c < PortWaitCycles; c++) begin
      if (tb_vif.sys_rst_assert_count != sys_before && (held || tb_vif.rst_n === 1'b1)) break;
      @(posedge tb_vif.clk);
    end
    disarm_reset_on_read();
    began = tb_vif.sys_rst_assert_count != sys_before;
    if (!held) return;
    if (!began) begin
      hold.kill();
      return;
    end
    wait (holding);
    scan_in_reset(t, ctx);
  endtask

  // Scans while the bridge reset is asserted: DTMCS with dmireset reads
  // dmistat 0, and DMI writes of dmactive and of a seeded sbaddress0 capture
  // 0.
  task scan_in_reset(dtp_j2a_target_t t, string ctx);
    string           in_reset = {ctx, " in_reset"};
    bit       [1:0] dmistat;
    bit       [63:0] value;
    bit       [63:0] sbaddress;
    read_dmistat(t, Dmireset, in_reset, dmistat);
    record_field(t, DtpJ2aBridgeResetCheckId, "dmistat", 64'(dmistat), 64'd0, in_reset);
    dmi_tdr(t, DTP_DM_DMCONTROL, 32'h1, DTP_DMI_OP_WRITE, value);
    record_field(t, DtpJ2aBridgeResetCheckId, "dmcontrol_capture", value, 64'd0, in_reset);
    sbaddress = random_target_addr(t);
    dmi_tdr(t, DTP_DM_SBADDRESS0, sbaddress[31:0], DTP_DMI_OP_WRITE, value);
    record_field(t, DtpJ2aBridgeResetCheckId, "sbaddress0_capture", value, 64'd0, in_reset);
  endtask

  // A full-beat read or write whose response stays held through
  // BusyPollsMin to BusyPollsMax sbcs polls and the bridge reset. A read's
  // slot holds a word written first.
  task unreleased_hold(dtp_j2a_target_t t, bit is_read, string ctx);
    int unsigned        size = t.default_size;
    bit          [63:0] addr = random_target_addr(t);
    bit          [63:0] data = random_distinct_word(t, memory_word(t, addr, size));
    string              port_ctx = {ctx, " port"};
    int unsigned        held;
    int unsigned        port_start;
    int unsigned        moved;
    logic        [31:0] j2a_before;
    bit                 reached;
    bit          [31:0] sbcs;
    bit          [63:0] valid_cycles;
    activate_dm(t);
    if (is_read) sba_write(t, addr, data, size, {ctx, ".fill"});
    held       = held_count(t, is_read);
    port_start = port_history(t.name).count(is_read);
    hold_port(t, is_read, 1'b0);
    sba_setup(t, addr, size, is_read, ctx);
    if (!is_read) begin
      if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {ctx, ".sbdata1"});
      dmi_write(t, DTP_DM_SBDATA0, data[31:0], {ctx, ".sbdata0"});
    end
    wait_response_held(t, is_read, held, reached);
    poll_while_held(t, $urandom_range(BusyPollsMax, BusyPollsMin), {ctx, ".held"}, sbcs);
    j2a_before = tb_vif.j2a_rst_assert_count;
    drive_reset(1'b0, 1'b0);
    release_port(t);
    moved = port_history(t.name).count(is_read) - port_start;
    release_and_check(t, j2a_before, ctx);
    expect_no_bus_request(t, ctx);
    record_field(t, DtpJ2aBridgeResetCheckId, "held", 64'(reached), 64'd1, port_ctx);
    record_field(t, DtpJ2aBridgeResetCheckId, "port_transactions", 64'(moved), 64'd0, port_ctx);
    valid_cycles = 64'(response_valid_cycles(t, is_read));
    record_field(t, DtpJ2aBridgeResetCheckId, "response_valid_cycles", valid_cycles, 64'd0,
                 port_ctx);
    recover(t, ctx);
  endtask

  // Assert the bridge reset in `phase` of the access the next Update-DR
  // starts; `began` returns whether the access was in that phase. A launched
  // access has raised no request at the port; the other phases begin on a
  // rise of phase_marker(), which the reset follows by a seeded number of
  // clk_i cycles.
  task reset_in_phase(input dtp_j2a_target_t t, input bit is_read, input string phase,
                      output bit began);
    int unsigned start = phase_marker(t, is_read, phase);
    wait_update_dr_exit();
    if (phase == "launched") begin
      drive_reset(1'b0, 1'b0);
      began = phase_marker(t, is_read, phase) == start;
      return;
    end
    for (int unsigned c = 0; c < PortWaitCycles; c++) begin
      if (phase_marker(t, is_read, phase) != start) break;
      @(posedge tb_vif.clk);
    end
    began = phase_marker(t, is_read, phase) != start;
    repeat ($urandom_range(PhaseDelayMax)) @(posedge tb_vif.clk);
    drive_reset(1'b0, 1'b0);
  endtask

  // A counter of t's port that rises when `phase` begins: the request VALID
  // cycles, the write-data stall cycles or the held responses.
  function int unsigned phase_marker(dtp_j2a_target_t t, bit is_read, string phase);
    case (phase)
      "w": begin
        case (t.reset_arm_bit)
          0: return tb_vif.smc_axi_w_stall_count;
          1: return tb_vif.smc_otp_axil_w_stall_count;
          default: return tb_vif.sep_otp_axil_w_stall_count;
        endcase
      end
      "response": return held_count(t, is_read);
      default: return valid_count(t, is_read);
    endcase
  endfunction

  // Release the bridge reset asserted since its counter read `j2a_before`,
  // after a seeded hold, and judge both releases and the state the bridge
  // then reads.
  task release_and_check(dtp_j2a_target_t t, logic [31:0] j2a_before, string ctx);
    wait_sys_cycles($urandom_range(ResetHoldMax, 1));
    drive_reset(1'b0, 1'b1);
    check_released(t, j2a_before, 1'b1, ctx);
  endtask

  // Judge the release of the bridge reset asserted since its counter read
  // `j2a_before` after a seeded number of clk_i cycles: with `tck_stopped`
  // since the release, the clk_i side has left reset and the TCK side has
  // not; once scans run TCK both have, and the bridge reads its reset state.
  task check_released(dtp_j2a_target_t t, logic [31:0] j2a_before, bit tck_stopped, string ctx);
    int unsigned stopped = $urandom_range(
        2 * DtpJ2aResetSyncTck + TckStoppedMax, 2 * DtpJ2aResetSyncTck + 1
    );
    fields_t     state;
    string       reset_ctx = {ctx, " bridge_reset"};
    wait_sys_cycles(stopped);
    check_reset_counted("j2a_rst_assert_count", j2a_before, tb_vif.j2a_rst_assert_count, reset_ctx);
    if (tck_stopped) check_release(t, 1'b0, 1'b0, $sformatf("%s tck_stopped=%0d", ctx, stopped));
    bridge_state(t, {ctx, ".reset_state"}, state);
    check_release(t, 1'b1, 1'b0, {ctx, " tck_running"});
    check_bridge_state(t, DtpJ2aBridgeResetCheckId, state, reset_state(), ctx);
  endtask

  // Pulse rst_n_i (`scan` 0) or scan_rst_ni (`scan` 1) in test mode with the
  // bridges idle. An rst_n_i pulse leaves the synchronized resets high and
  // counts no bridge reset; a scan_rst_ni pulse holds them low while it lasts
  // and releases them after no clock edge.
  task pulse_in_test_mode(bit scan, dtp_j2a_target_t t);
    string           ctx = pick(scan, "test_mode.scan_rst_n", "test_mode.sys_rst_n");
    logic     [31:0] sys_before = tb_vif.sys_rst_assert_count;
    logic     [31:0] j2a_before = tb_vif.j2a_rst_assert_count;
    bit       [2:0] expected = scan ? 3'b000 : AllBridges;
    bit       [2:0] held_clk;
    bit       [2:0] held_tck;
    drive_reset(scan, 1'b0);
    wait_sys_cycles($urandom_range(ResetHoldMax, 1));
    held_clk = tb_vif.j2a_arst_clk_n;
    held_tck = tb_vif.j2a_arst_tck_n;
    drive_reset(scan, 1'b1);
    wait_sys_cycles(2);
    if (scan)
      check_reset_counted("j2a_rst_assert_count", j2a_before, tb_vif.j2a_rst_assert_count, ctx);
    else check_reset_counted("sys_rst_assert_count", sys_before, tb_vif.sys_rst_assert_count, ctx);
    record_field(t, DtpJ2aResetReleaseCheckId, "arst_clk_n_held", 64'(held_clk), 64'(expected),
                 ctx);
    record_field(t, DtpJ2aResetReleaseCheckId, "arst_tck_n_held", 64'(held_tck), 64'(expected),
                 ctx);
    if (scan) begin
      check_release(t, 1'b1, 1'b1, ctx);
    end else begin
      record_field(t, DtpJ2aResetReleaseCheckId, "bridge_resets",
                   64'(32'(tb_vif.j2a_rst_assert_count - j2a_before)), 64'd0, ctx);
      record_field(t, DtpJ2aResetReleaseCheckId, "errors",
                   64'(32'(tb_vif.j2a_release_err_count - m_release_errors)), 64'd0, ctx);
    end
  endtask

  // Every bridge's synchronized resets released on clk_i, and on TCK with
  // `tck_released`, each after the synchronizer's depth of its clock's rising
  // edges outside test mode and after none in it, with no change that breaks
  // a reset rule. +DTP_J2A_RESET_RELEASE_NEGATIVE expects one edge fewer
  // outside test mode, so the run must fail.
  function void check_release(dtp_j2a_target_t t, bit tck_released, bit test_mode, string ctx);
    int unsigned edges = test_mode ? 0 : DtpJ2aResetSyncTck;
    names_t      names = bridge_names();
    if (edges != 0 && test_cfg.j2a_reset_release_negative) edges--;
    record_field(t, DtpJ2aResetReleaseCheckId, "arst_clk_n", 64'(tb_vif.j2a_arst_clk_n),
                 64'(AllBridges), ctx);
    record_field(t, DtpJ2aResetReleaseCheckId, "arst_tck_n", 64'(tb_vif.j2a_arst_tck_n),
                 tck_released ? 64'(AllBridges) : 64'd0, ctx);
    record_field(t, DtpJ2aResetReleaseCheckId, "errors",
                 64'(32'(tb_vif.j2a_release_err_count - m_release_errors)), 64'd0, ctx);
    foreach (names[n]) begin
      dtp_j2a_target_t b = dtp_j2a_target_by_name(names[n]);
      record_field(t, DtpJ2aResetReleaseCheckId, {b.name, ".clk_edges"},
                   64'(tb_vif.j2a_clk_release_edges[b.reset_arm_bit]), 64'(edges), ctx);
      if (tck_released)
        record_field(t, DtpJ2aResetReleaseCheckId, {b.name, ".tck_edges"},
                     64'(tb_vif.j2a_tck_release_edges[b.reset_arm_bit]), 64'(edges), ctx);
    end
  endfunction

  // The state every bridge reads after the bridge reset.
  // +DTP_J2A_BRIDGE_RESET_NEGATIVE expects dmactive to survive it, so the run
  // must fail.
  function fields_t reset_state();
    fields_t   f;
    dtp_sbcs_t sbcs = '0;
    sbcs.sbaccess        = 3'd2;
    f["capture_address"] = '0;
    f["capture_data"]    = '0;
    f["capture_status"]  = '0;
    f["dmistat"]         = '0;
    f["dmactive"]        = 64'(kept_dmactive(1'b0));
    f["sbcs"]            = 64'(sbcs);
    f["sbaddress"]       = '0;
    f["sbdata"]          = '0;
    return f;
  endfunction

  // Cycles t's bridge has seen RVALID (`is_read`) or BVALID since rst_n_i
  // last released.
  function int unsigned response_valid_cycles(dtp_j2a_target_t t, bit is_read);
    case (t.reset_arm_bit)
      0: return is_read ? tb_vif.smc_axi_rvalid_count : tb_vif.smc_axi_bvalid_count;
      1: return is_read ? tb_vif.smc_otp_axil_rvalid_count : tb_vif.smc_otp_axil_bvalid_count;
      default:
      return is_read ? tb_vif.sep_otp_axil_rvalid_count : tb_vif.sep_otp_axil_bvalid_count;
    endcase
  endfunction

  // `expected` dmactive, inverted by +DTP_J2A_BRIDGE_RESET_NEGATIVE.
  function bit kept_dmactive(bit expected);
    return expected ^ test_cfg.j2a_bridge_reset_negative;
  endfunction

  // Set dmactive again; a read of a word a full-beat write put there first
  // then reaches the port.
  task recover(dtp_j2a_target_t t, string ctx);
    activate_dm(t);
    port_access(t, 1'b1, DtpJ2aBridgeResetCheckId, {ctx, ".recover"});
  endtask

  // Drive test_en, with scan_rst_n and rst_n both 1.
  task set_test_mode(bit value);
    tb_vif.test_en = value;
    wait_sys_cycles(2);
  endtask

  // --- building blocks -----------------------------------------------------------

  // Account t's port for the operations up to close_ledger(); the other ports
  // keep their counts.
  function void open_ledger(dtp_j2a_target_t t);
    m_ledger = t.name;
    open_bus_ledger();
  endfunction

  function void close_ledger();
    close_bus_ledger();
    m_ledger = "";
  endfunction

  // Write a seeded sbaddress0 after an sbcs write that clears sbreadonaddr,
  // so no read starts; `sbaddress` returns the value written.
  task write_sbaddress0(input dtp_j2a_target_t t, input string ctx, output bit [63:0] sbaddress);
    dtp_sbcs_t sbcs = '0;
    sbaddress     = random_target_addr(t) & 64'hFFFF_FFFF;
    sbcs.sbaccess = 3'(t.default_size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbcs"});
    dmi_write(t, DTP_DM_SBADDRESS0, sbaddress[31:0], {ctx, ".sbaddress0"});
  endtask

  // Drive rst_n_i (`scan` 0) or scan_rst_ni (`scan` 1) to `value` at a seeded
  // time between two clk_i edges.
  task drive_reset(bit scan, bit value);
    int unsigned period_ps = tb_vif.clk_period_ns * 1000;
    @(posedge tb_vif.clk);
    #($urandom_range(period_ps - 1, 1) * 1ps);
    if (scan) tb_vif.scan_rst_n = value;
    else tb_vif.sys_rst_n = value;
  endtask

  // Hold t's next access at the port: with `request` by READY low on every
  // request channel, or on W alone with `w_only`; otherwise by holding its
  // response.
  function void hold_port(dtp_j2a_target_t t, bit is_read, bit request, bit w_only = 1'b0);
    if (request) begin
      ocah_axi_delays hold = new(0, 0, 0, 100, ReadyHoldCycles, ReadyHoldCycles);
      ocah_axi_delays none = new(0);
      apply_responder_timing(t, w_only ? none : hold, hold, hold, none, none);
    end else begin
      hold_responses(t, !is_read, is_read);
    end
  endfunction

  // Return t's responder to READY high and release its response holds.
  function void release_port(dtp_j2a_target_t t);
    clear_responder_timing(t);
    hold_responses(t, 1'b0, 1'b0);
  endfunction

  // One DMI scan of {address, data, op}; `value` returns the whole capture.
  task dmi_tdr(input dtp_j2a_target_t t, input bit [6:0] address, input bit [31:0] data,
               input dtp_dmi_op_e op, output bit [63:0] value);
    read_tdr(IrWidth'(t.dmi_instr), DtpDmiLen, value, dtp_j2a_pack_dmi(address, data, op));
    run_test_idle(DmiIdleTck);
  endtask

  // The capture of a DMI NOP scan carrying `address` and `data`; the scan
  // loads what it captures when that is `address` and `data` or the status
  // is not 0.
  task dmi_capture(input dtp_j2a_target_t t, input bit [6:0] address, input bit [31:0] data,
                   output dtp_dmi_t capture);
    bit [63:0] value;
    dmi_tdr(t, address, data, DTP_DMI_OP_NOP, value);
    capture = dtp_j2a_unpack_dmi(value);
  endtask

  // DTMCS dmistat, from a scan that shifts `shift_value`; CHK-J2A-DTM-CAPTURE
  // judges the other fields, which no reset changes.
  task read_dmistat(input dtp_j2a_target_t t, input bit [31:0] shift_value, input string ctx,
                    output bit [1:0] dmistat);
    bit [63:0] value;
    read_tdr(IrWidth'(t.dtmcs_instr), DtpDtmcsLen, value, 64'(shift_value));
    run_test_idle(DmiIdleTck);
    check_dtmcs_fields(t, value, ctx);
    dmistat = value[DtpDtmcsDmistatLsb+:2];
  endtask

  function fields_t capture_fields(dtp_dmi_t capture);
    fields_t f;
    f["capture_address"] = 64'(capture.address);
    f["capture_data"]    = 64'(capture.data);
    f["capture_status"]  = 64'(capture.op);
    return f;
  endfunction

  // The bridge as JTAG reads it: the DMI capture of a NOP scan carrying
  // `peek_address` and `peek_data`, then DTMCS dmistat, and with the captured
  // status 0 dmactive, sbcs, sbaddress and sbdata. An sbcs read with dmactive
  // 1 also takes CHK-J2A-GEOMETRY.
  task bridge_state(input dtp_j2a_target_t t, input string ctx, output fields_t state,
                    input bit [6:0] peek_address = '0, input bit [31:0] peek_data = '0);
    dtp_dmi_t        capture;
    bit       [1:0] dmistat;
    bit       [31:0] word;
    bit       [63:0] wide;
    dmi_capture(t, peek_address, peek_data, capture);
    read_dmistat(t, '0, ctx, dmistat);
    state = capture_fields(capture);
    state["dmistat"] = 64'(dmistat);
    if (capture.op == DTP_DMI_SUCCESS) begin
      dmi_read(t, DTP_DM_DMCONTROL, {ctx, ".dmcontrol"}, word);
      state["dmactive"] = 64'(word[0]);
      dmi_read(t, DTP_DM_SBCS, {ctx, ".sbcs"}, word);
      state["sbcs"] = 64'(word);
      if (state["dmactive"] == 1) check_sbcs_geometry(t, word, {ctx, ".sbcs"});
      read_sbaddress(t, ctx, wide);
      state["sbaddress"] = wide;
      read_sbdata(t, t.default_size, ctx, wide);
      state["sbdata"] = wide;
    end
  endtask

  // `check_id` on every field of `expected`; a field `observed` lacks reads
  // all ones.
  function void check_bridge_state(dtp_j2a_target_t t, string check_id, fields_t observed,
                                   fields_t expected, string ctx);
    foreach (expected[k]) begin
      record_field(t, check_id, k, observed.exists(k) ? observed[k] : '1, expected[k], ctx);
    end
  endfunction

endclass : dtp_jtag2axi_reset_test_seq
