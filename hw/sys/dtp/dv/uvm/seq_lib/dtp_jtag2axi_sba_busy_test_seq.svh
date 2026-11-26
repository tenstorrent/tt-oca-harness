// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI System Bus Access while a bus access is outstanding, on every
// bridge. On each bridge, every access kind the Debug Module refuses while a
// bus access is outstanding runs once per pass, in a seeded order: an sbcs
// write, sbaddress0 and sbaddress1 writes, and sbdata0 and sbdata1 writes and
// reads. A kind runs under a held write in one pass and a held read in the
// next. Each case starts a seeded access with its response held and polls sbcs
// past the SbaPolls bound, every poll reading sbbusy 1, then reads sbaddress,
// which the Debug Module never refuses. The case's own kind is then refused
// with the busy status, which a DTMCS dmireset clears, and one more kind is
// refused under the sbbusyerror the first set, which a DMI op-3 scan clears.
// Neither refusal changes sbcs or sbaddress or raises a request at the port,
// and an sbcs write that sets sbbusyerror does not clear it. Released, the
// access completes with its data, sbcs keeps sbbusyerror until a write of 1
// clears it, and the next access reaches the port. The cocotb twin is
// seq_lib/dtp_jtag2axi_sba_busy_test_seq.py.

class dtp_jtag2axi_sba_busy_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_sba_busy_test_seq)

  // Every access the Debug Module refuses while a bus access is outstanding.
  typedef enum int unsigned {
    KIND_SBCS_WRITE,
    KIND_SBADDRESS0_WRITE,
    KIND_SBADDRESS1_WRITE,
    KIND_SBDATA0_WRITE,
    KIND_SBDATA1_WRITE,
    KIND_SBDATA0_READ,
    KIND_SBDATA1_READ
  } busy_kind_e;

  localparam int unsigned NumKinds = 7;

  // The sbcs and sbaddress a held access keeps through its refusals.
  typedef struct {
    bit [31:0] sbcs;
    bit [63:0] sbaddress;
  } held_state_t;

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_sba_busy_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    names_t names = bridge_names();
    seed_scenario_rng();
    `uvm_info(get_type_name(),
              "=== System Bus Access while a bus access is outstanding on every bridge ===",
              UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      m_ledger = t.name;
      open_bus_ledger();
      busy_cases(t);
      check_responder_activity(t, 1, {t.name, ".sba_busy"});
      close_bus_ledger();
      m_ledger = "";
      `uvm_info(get_type_name(), $sformatf("Summary: %s busy accesses complete", t.name), UVM_LOW)
    end
  endtask

  // Every kind once, in a seeded order, then a seeded access. A kind's held
  // access is a read when its busy_kind_e value and the pass index differ in
  // parity, so every two passes hold each kind under both. A seeded cycle
  // through the kinds names the kind each case refuses second, so every kind
  // is also refused once under sbbusyerror.
  task busy_cases(dtp_j2a_target_t t);
    busy_kind_e kinds[$];
    for (int unsigned k = 0; k < NumKinds; k++) kinds.push_back(busy_kind_e'(k));
    kinds.shuffle();
    foreach (kinds[k]) begin
      bit is_read = 1'((int'(kinds[k]) + loop_index) % 2);
      held_case(t, is_read, kinds[k], kinds[(k+1)%NumKinds]);
    end
    port_access(t, 1'($urandom()), DtpJ2aSbaBusyCheckId, {t.name, ".next"});
  endtask

  // A seeded read or write whose response is held while sbcs is polled and
  // `first` and then `second` are refused; released, it completes with its
  // data.
  task held_case(dtp_j2a_target_t t, bit is_read, busy_kind_e first, busy_kind_e second);
    string              ctx = $sformatf("%s.%s.%s", t.name, pick(is_read, "read", "write"),
                                        kind_name(first));
    string              released_ctx = {ctx, ".released"};
    ocah_axi_checker    ev = evidence(t);
    bit          [63:0] addr;
    bit          [63:0] masked;
    bit          [63:0] data;
    bit          [63:0] beat;
    bit          [63:0] lanes;
    bit          [63:0] sbaddress;
    bit          [63:0] rdata;
    bit          [7:0]  wstrb;
    int unsigned        size;
    int unsigned        offset;
    int unsigned        since;
    int unsigned        held;
    bit                 reached;
    held_state_t        state;
    dtp_sbcs_t          released;
    dtp_sbcs_t          cleared;
    dtp_sbcs_t          sbcs = '0;
    seeded_access(t, addr, size, offset);
    masked = addr & bit_mask(t.addr_width);
    data   = sized_word(size, memory_word(t, addr, size));
    wstrb  = 8'(dtp_j2a_full_wstrb(size) << offset);
    lanes  = (data << (8 * offset)) & bit_mask(t.data_width);
    if (is_read) begin
      beat = {$urandom(), $urandom()} & bit_mask(t.data_width);
      beat &= ~(dtp_j2a_data_mask(size) << (8 * offset));
      beat |= data << (8 * offset);
      sba_write(t, addr - offset, beat, t.default_size, {ctx, ".fill"});
      target_cfgs[t.name].arm_expected_read(masked);
    end else begin
      target_cfgs[t.name].arm_expected_write(masked, lanes, wstrb);
    end
    since = open_request_count(t);
    held  = held_count(t, is_read);
    hold_responses(t, !is_read, is_read);
    sba_setup(t, addr, size, is_read, ctx);
    if (!is_read) begin
      if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {ctx, ".sbdata1"});
      dmi_write(t, DTP_DM_SBDATA0, data[31:0], {ctx, ".sbdata0"});
    end
    wait_response_held(t, is_read, held, reached);
    poll_while_held(t, $urandom_range(BusyPollsMax, BusyPollsMin), {ctx, ".held"}, state.sbcs);
    state.sbaddress = masked;
    read_sbaddress(t, {ctx, ".held"}, sbaddress);
    record_field(t, DtpJ2aSbaBusyCheckId, "held", 64'(reached), 64'd1, {ctx, ".held"});
    record_field(t, DtpJ2aSbaBusyCheckId, "sbaddress", sbaddress, state.sbaddress, {ctx, ".held"});
    refuse(t, first, state, 1'b1, {ctx, ".first"});
    refuse(t, second, state, 1'b0, {ctx, ".", kind_name(second)});
    hold_responses(t, 1'b0, 1'b0);
    expect_bus_request(t, is_read, addr, size, is_read ? '0 : lanes, is_read ? '0 : wstrb, ctx);
    poll_sba_idle(t, {ctx, ".released"}, released, 1'b1);
    sbcs.sbbusyerror = 1'b1;
    sbcs.sbaccess    = 3'(size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbbusyerror_w1"});
    poll_sba_idle(t, {ctx, ".cleared"}, cleared);
    record_field(t, DtpJ2aSbaBusyCheckId, "sbbusyerror_released", 64'(released.sbbusyerror), 64'd1,
                 released_ctx);
    record_field(t, DtpJ2aSbaBusyCheckId, "sbbusyerror_cleared", 64'(cleared.sbbusyerror), 64'd0,
                 released_ctx);
    if (is_read) begin
      read_sbdata(t, size, ctx, rdata);
      rdata &= dtp_j2a_data_mask(size);
      void'(ev.expect_equal(
          "CHK-AXI-RDATA", rdata, data, $sformatf("%s target=%s source=bridge_capture", ctx, t.name)
      ));
    end else begin
      check_target_word(t, addr, data, size, {ctx, ".mem"});
    end
    check_one_transfer(t, since, ctx);
  endtask

  // A `kind` access the Debug Module refuses while the access is outstanding.
  // The next DMI capture returns status 3 with the refused access's address
  // and, for a write, its data, for a read DmiDataBusy. With `dmireset` a NOP
  // scan takes that capture and a DTMCS dmireset, whose capture reads dmistat
  // 3, clears the status; otherwise a DMI op-3 scan takes it and clears the
  // status. sbcs then reads sbbusyerror 1 with every other field and sbaddress
  // as `state` holds them, and the port raised no request.
  task refuse(dtp_j2a_target_t t, busy_kind_e kind, held_state_t state, bit dmireset, string ctx);
    dtp_dm_reg_e        address = kind_register(kind);
    int unsigned        since = open_request_count(t);
    bit          [31:0] value;
    bit          [31:0] captured;
    bit          [31:0] sbcs;
    bit          [63:0] sbaddress;
    dtp_sbcs_t          expected = dtp_sbcs_t'(state.sbcs);
    dtp_dmi_op_e        clear_op = dmireset ? DTP_DMI_OP_NOP : DTP_DMI_OP_CLEAR;
    string              capture_ctx = {ctx, ".capture"};
    string              kind_ctx = $sformatf("%s kind=%s", ctx, kind_name(kind));
    if (kind_reads(kind)) begin
      dmi_scan(t, address, '0, DTP_DMI_OP_READ, {ctx, ".refused"}, captured);
      value = DmiDataBusy;
    end else begin
      value = refused_value(t, kind, state);
      dmi_write(t, address, value, {ctx, ".refused"});
    end
    select_dmi(t);
    dmi_raw(t, '0, '0, clear_op, DTP_DMI_BUSY, capture_ctx, 1'b0, 1'b1, address, value);
    if (dmireset) dtmcs_scan(t, 32'h1 << DtpDtmcsDmiresetBit, DTP_DMI_BUSY, {ctx, ".dmireset"});
    dmi_read(t, DTP_DM_SBCS, {ctx, ".sbcs"}, sbcs);
    read_sbaddress(t, ctx, sbaddress);
    expected.sbbusyerror = 1'b1;
    record_field(t, DtpJ2aSbaBusyCheckId, "sbcs", 64'(sbcs), 64'(expected), kind_ctx);
    record_field(t, DtpJ2aSbaBusyCheckId, "sbaddress", sbaddress, state.sbaddress, kind_ctx);
    check_one_transfer(t, since, {ctx, ".refused"});
  endtask

  // A seeded value for a refused `kind` write: for sbcs one that changes every
  // writable field and sets both write-1-to-clear fields, for sbaddress one
  // that changes the register.
  function bit [31:0] refused_value(dtp_j2a_target_t t, busy_kind_e kind, held_state_t state);
    dtp_sbcs_t       held = dtp_sbcs_t'(state.sbcs);
    dtp_sbcs_t       sbcs = '0;
    bit       [31:0] current;
    bit       [31:0] value;
    case (kind)
      KIND_SBCS_WRITE: begin
        sbcs.sbbusyerror     = 1'b1;
        sbcs.sbreadonaddr    = !held.sbreadonaddr;
        sbcs.sbaccess        = held.sbaccess;
        while (sbcs.sbaccess == held.sbaccess) sbcs.sbaccess = 3'($urandom_range(t.default_size));
        sbcs.sbautoincrement = 1'b1;
        sbcs.sbreadondata    = 1'b1;
        sbcs.sberror         = 3'h7;
        return 32'(sbcs);
      end
      KIND_SBADDRESS0_WRITE: current = state.sbaddress[31:0];
      KIND_SBADDRESS1_WRITE: current = state.sbaddress[63:32];
      default: current = '0;
    endcase
    do value = $urandom(); while (value == '0 || value == current);
    return value;
  endfunction

  function dtp_dm_reg_e kind_register(busy_kind_e kind);
    case (kind)
      KIND_SBCS_WRITE: return DTP_DM_SBCS;
      KIND_SBADDRESS0_WRITE: return DTP_DM_SBADDRESS0;
      KIND_SBADDRESS1_WRITE: return DTP_DM_SBADDRESS1;
      KIND_SBDATA0_WRITE, KIND_SBDATA0_READ: return DTP_DM_SBDATA0;
      default: return DTP_DM_SBDATA1;
    endcase
  endfunction

  function bit kind_reads(busy_kind_e kind);
    return kind inside {KIND_SBDATA0_READ, KIND_SBDATA1_READ};
  endfunction

  // The kind's name as the cocotb twin spells it.
  function string kind_name(busy_kind_e kind);
    string name = kind.name();
    return name.substr(5, name.len() - 1).tolower();
  endfunction

endclass : dtp_jtag2axi_sba_busy_test_seq
