// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI Debug Module activation and sbcs geometry on every bridge, each
// bridge in a seeded order. While dmcontrol.dmactive is 0 it is the one Debug
// Module bit a write changes: the System Bus Access registers hold their
// reset values and start no access. A write of 0 to dmactive returns them to
// those values, and the read-only geometry fields of sbcs keep the bridge's
// widths through every write. The cocotb twin is
// seq_lib/dtp_jtag2axi_dm_regs_test_seq.py.

class dtp_jtag2axi_dm_regs_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_dm_regs_test_seq)

  // The one dmcontrol bit besides dmactive that an active Debug Module stores.
  localparam bit [31:0] DmcontrolNdmreset = 32'h2;
  // sbcs while dmactive is 0.
  localparam bit [31:0] SbcsReset = 32'h0004_0000;
  localparam bit [2:0] SberrorSize = 3'd4;

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_dm_regs_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    string names[$] = '{"smc_otp", "sep_otp", "smc_axi"};
    seed_scenario_rng();
    `uvm_info(get_type_name(), "=== Debug Module activation and sbcs geometry on every bridge ===",
              UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      m_ledger = t.name;
      open_bus_ledger();
      deactivate_case(t);
      inactive_writes_case(t);
      reactivate_case(t);
      check_responder_activity(t, 1, {t.name, ".dm_regs"});
      close_bus_ledger();
      m_ledger = "";
      `uvm_info(get_type_name(), $sformatf("Summary: %s Debug Module registers complete", t.name),
                UVM_LOW)
    end
  endtask

  // CHK-J2A-DM-ACTIVE on one Debug Module register read.
  // +DTP_J2A_DM_ACTIVE_NEGATIVE flips the expected bit 0, so the run must
  // fail.
  function void check_dm_register(dtp_j2a_target_t t, dtp_dm_reg_e dm_reg, bit [31:0] observed,
                                  bit [31:0] expected, string context_s);
    ocah_axi_checker ev = evidence(t);
    string           label = reg_label(dm_reg);
    if (test_cfg != null && test_cfg.j2a_dm_active_negative) expected ^= 32'h1;
    void'(ev.expect_equal(
        DtpJ2aDmActiveCheckId,
        64'(observed),
        64'(expected),
        $sformatf(
            "%s target=%s register=%s observed=0x%08h expected=0x%08h",
            context_s,
            t.name,
            label,
            observed,
            expected)
    ));
  endfunction

  // Read each of `regs` in order and judge it against `values`.
  task expect_registers(dtp_j2a_target_t t, dtp_dm_reg_e regs[$], bit [31:0] values[$],
                        string context_s);
    bit [31:0] observed;
    foreach (regs[i]) begin
      dmi_read(t, regs[i], {context_s, ".", reg_label(regs[i])}, observed);
      check_dm_register(t, regs[i], observed, values[i], context_s);
    end
  endtask

  // A Debug Module register's name without its enum prefix, in lower case.
  function string reg_label(dtp_dm_reg_e dm_reg);
    string name = dm_reg.name();
    name = name.substr(7, name.len() - 1);
    return name.tolower();
  endfunction

  // sbcs of an active, idle Debug Module after a write of `written`.
  function bit [31:0] active_sbcs(dtp_j2a_target_t t, bit [31:0] written, bit [2:0] sberror = '0);
    dtp_sbcs_t w = dtp_sbcs_t'(written);
    dtp_sbcs_t sbcs = '0;
    sbcs.sbversion       = 3'd1;
    sbcs.sbasize         = 7'(t.addr_width);
    sbcs.sbaccess64      = (t.data_width >= 64);
    sbcs.sbaccess32      = 1'b1;
    sbcs.sbaccess16      = 1'b1;
    sbcs.sbaccess8       = 1'b1;
    sbcs.sberror         = sberror;
    sbcs.sbreadonaddr    = w.sbreadonaddr;
    sbcs.sbaccess        = w.sbaccess;
    sbcs.sbautoincrement = w.sbautoincrement;
    sbcs.sbreadondata    = w.sbreadondata;
    return 32'(sbcs);
  endfunction

  // The sbaddress and the sbdata registers `t`'s widths use, the one whose
  // write starts an access last.
  function void sba_registers(input dtp_j2a_target_t t, output dtp_dm_reg_e addresses[$],
                              output dtp_dm_reg_e data[$]);
    addresses = {};
    data = {};
    if (t.addr_width > 32) addresses.push_back(DTP_DM_SBADDRESS1);
    addresses.push_back(DTP_DM_SBADDRESS0);
    if (t.data_width > 32) data.push_back(DTP_DM_SBDATA1);
    data.push_back(DTP_DM_SBDATA0);
  endfunction

  // A seeded nonzero word for each of `regs` that `t` holds whole, sbaddress0
  // aligned to a 1 << `align` byte access.
  function void sba_words(input dtp_j2a_target_t t, input dtp_dm_reg_e regs[$],
                          input int unsigned align, output bit [31:0] words[$]);
    words = {};
    foreach (regs[i])
    case (regs[i])
      DTP_DM_SBADDRESS0: words.push_back(random_word((t.addr_width < 32) ? t.addr_width : 32, align));
      DTP_DM_SBADDRESS1: words.push_back(random_word(t.addr_width - 32));
      default: words.push_back(random_word(32));
    endcase
  endfunction

  // A seeded nonzero `bits`-bit word whose low `align` bits are 0.
  function bit [31:0] random_word(int unsigned bits, int unsigned align = 0);
    bit [31:0] word;
    do word = $urandom() & 32'(bit_mask(bits)) & ~32'(bit_mask(align)); while (word == '0);
    return word;
  endfunction

  // A write of 0 to dmactive returns dmcontrol and the SBA registers to their
  // reset values, sberror among them.
  task deactivate_case(dtp_j2a_target_t t);
    string                  ctx = {t.name, ".deactivate"};
    int unsigned            oversize = t.default_size + 1;
    dtp_sbcs_t              sbcs = '0;
    dtp_dm_reg_e            addresses[$];
    dtp_dm_reg_e            data[$];
    dtp_dm_reg_e            regs[$];
    dtp_dm_reg_e            reads[$];
    bit              [31:0] words[$];
    bit              [31:0] values[$];
    sbcs.sbaccess        = 3'(oversize);
    sbcs.sbautoincrement = 1'b1;
    sbcs.sbreadondata    = 1'b1;
    sba_registers(t, addresses, data);
    regs = addresses;
    foreach (data[i]) regs.push_back(data[i]);
    sba_words(t, regs, oversize, words);
    dmi_write(t, DTP_DM_DMCONTROL, DmcontrolNdmreset | 32'h1, {ctx, ".dmcontrol"});
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbcs"});
    // The sbdata0 write starts an access that sbaccess refuses with sberror 4.
    foreach (regs[i]) dmi_write(t, regs[i], words[i], {ctx, ".", reg_label(regs[i])});
    reads  = '{DTP_DM_DMCONTROL, DTP_DM_SBCS};
    values = '{DmcontrolNdmreset | 32'h1, active_sbcs(t, 32'(sbcs), SberrorSize)};
    foreach (regs[i]) begin
      reads.push_back(regs[i]);
      values.push_back(words[i]);
    end
    expect_registers(t, reads, values, {ctx, ".set"});
    dmi_write(t, DTP_DM_DMCONTROL, '0, {ctx, ".dmcontrol"});
    reads  = '{DTP_DM_DMCONTROL, DTP_DM_SBCS};
    values = '{32'h0, SbcsReset};
    foreach (regs[i]) begin
      reads.push_back(regs[i]);
      values.push_back('0);
    end
    expect_registers(t, reads, values, {ctx, ".reset"});
    expect_no_bus_request(t, ctx);
  endtask

  // While dmactive is 0 a write changes no Debug Module register and starts
  // no access; each write would start a read or a write if it took effect.
  task inactive_writes_case(dtp_j2a_target_t t);
    string                  ctx = {t.name, ".inactive"};
    int unsigned            size = $urandom_range(t.default_size);
    dtp_sbcs_t              sbcs = '0;
    dtp_dm_reg_e            addresses[$];
    dtp_dm_reg_e            data[$];
    dtp_dm_reg_e            reads[$];
    bit              [31:0] words[$];
    bit              [31:0] sbdata[$];
    bit              [31:0] values[$];
    sba_registers(t, addresses, data);
    sba_words(t, addresses, size, words);
    sba_words(t, data, 0, sbdata);
    dmi_write(t, DTP_DM_DMCONTROL, (random_word(30) << 2) | DmcontrolNdmreset, {ctx, ".dmcontrol"});
    sbcs.sbreadonaddr    = 1'b1;
    sbcs.sbaccess        = 3'(size);
    sbcs.sbautoincrement = 1'b1;
    sbcs.sbreadondata    = 1'b1;
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbcs"});
    // With sbreadonaddr, the sbaddress0 write starts a read; with
    // sbreadondata, so does the sbdata0 read.
    foreach (addresses[i])
      dmi_write(t, addresses[i], words[i], {ctx, ".", reg_label(addresses[i])});
    reads  = '{DTP_DM_DMCONTROL, DTP_DM_SBCS};
    values = '{32'h0, SbcsReset};
    foreach (addresses[i]) begin
      reads.push_back(addresses[i]);
      values.push_back('0);
    end
    reads.push_back(DTP_DM_SBDATA0);
    values.push_back('0);
    expect_registers(t, reads, values, {ctx, ".read"});
    expect_no_bus_request(t, {ctx, ".read"});
    // The sbdata0 write starts a write.
    foreach (data[i]) dmi_write(t, data[i], sbdata[i], {ctx, ".", reg_label(data[i])});
    reads  = '{DTP_DM_SBCS};
    values = '{SbcsReset};
    foreach (data[i]) begin
      reads.push_back(data[i]);
      values.push_back('0);
    end
    expect_registers(t, reads, values, {ctx, ".write"});
    expect_no_bus_request(t, {ctx, ".write"});
  endtask

  // A write of 1 to dmactive releases the SBA registers at their reset
  // values, with sbcs giving the geometry. A write of sbcs sets its writable
  // fields and leaves the geometry, and the bridge reaches the bus again.
  task reactivate_case(dtp_j2a_target_t t);
    string                  ctx = {t.name, ".reactivate"};
    dtp_dm_reg_e            addresses[$];
    dtp_dm_reg_e            data[$];
    dtp_dm_reg_e            reads[$];
    bit              [31:0] values[$];
    bit              [31:0] written;
    bit              [31:0] sbcs;
    bit              [63:0] rdata;
    bit              [63:0] wdata;
    sba_registers(t, addresses, data);
    activate_dm(t);
    reads  = '{DTP_DM_DMCONTROL, DTP_DM_SBCS};
    values = '{32'h1, active_sbcs(t, SbcsReset)};
    foreach (addresses[i]) begin
      reads.push_back(addresses[i]);
      values.push_back('0);
    end
    foreach (data[i]) begin
      reads.push_back(data[i]);
      values.push_back('0);
    end
    expect_registers(t, reads, values, {ctx, ".released"});
    written = sbcs_over_geometry(t);
    dmi_write(t, DTP_DM_SBCS, written, {ctx, ".sbcs"});
    dmi_read(t, DTP_DM_SBCS, {ctx, ".sbcs"}, sbcs);
    check_sbcs_geometry(t, sbcs, {ctx, ".sbcs"});
    check_dm_register(t, DTP_DM_SBCS, sbcs, active_sbcs(t, written), {ctx, ".sbcs"});
    write_neighbour_then_read(t, random_target_addr(t), {ctx, ".access"}, rdata, wdata);
  endtask

  // An sbcs write with every read-only field the inverse of `t`'s geometry
  // and sbbusy 1, and seeded writable fields other than their reset values.
  function bit [31:0] sbcs_over_geometry(dtp_j2a_target_t t);
    dtp_sbcs_t sbcs = '0;
    dtp_sbcs_t reset = dtp_sbcs_t'(SbcsReset);
    sbcs.sbversion   = ~3'd1;
    sbcs.sbbusy      = 1'b1;
    sbcs.sbasize     = ~7'(t.addr_width);
    sbcs.sbaccess128 = (t.data_width < 128);
    sbcs.sbaccess64  = (t.data_width < 64);
    sbcs.sbaccess32  = (t.data_width < 32);
    sbcs.sbaccess16  = (t.data_width < 16);
    sbcs.sbaccess8   = (t.data_width < 8);
    do begin
      sbcs.sbreadonaddr    = 1'($urandom());
      sbcs.sbaccess        = 3'($urandom());
      sbcs.sbautoincrement = 1'($urandom());
      sbcs.sbreadondata    = 1'($urandom());
    end while ({sbcs.sbreadonaddr, sbcs.sbaccess, sbcs.sbautoincrement, sbcs.sbreadondata} ==
               {reset.sbreadonaddr, reset.sbaccess, reset.sbautoincrement, reset.sbreadondata});
    return 32'(sbcs);
  endfunction

endclass : dtp_jtag2axi_dm_regs_test_seq
