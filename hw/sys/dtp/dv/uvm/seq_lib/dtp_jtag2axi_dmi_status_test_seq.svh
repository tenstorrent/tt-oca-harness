// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI DTMCS and sticky DMI status on every bridge: every DMI operation,
// every cause of the busy status and both ways to clear it, on each bridge in
// a seeded order with the cases in a seeded order. Each case starts and ends
// with the status at 0 and the TAP in Run-Test/Idle. A DMI scan chained from
// Update-DR captures two TCK cycles after the update, one from Run-Test/Idle
// three cycles after it, and a scan that shifts no bit updates four cycles
// after it, all inside the DtpDmiBusyTck window in which the operation is in
// progress. The cocotb twin is seq_lib/dtp_jtag2axi_dmi_status_test_seq.py.

class dtp_jtag2axi_dmi_status_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_dmi_status_test_seq)

  // System cycles TCK stays stopped in Run-Test/Idle after a read's Update-DR.
  localparam int unsigned TckStopMin = 200;
  localparam int unsigned TckStopMax = 1000;

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_dmi_status_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    string names[$] = '{"smc_otp", "sep_otp", "smc_axi"};
    string cases[$];
    seed_scenario_rng();
    `uvm_info(get_type_name(), "=== DMI status on every bridge ===", UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      dtp_sbcs_t       sbcs = '0;
      cases = '{
          "dtmcs_case",
          "ops_case",
          "capture_during_read_case",
          "update_during_write_case",
          "update_during_read_case",
          "dm_busy_case",
          "tck_stop_case"
      };
      cases.shuffle();
      m_ledger = t.name;
      open_bus_ledger();
      activate_dm(t);
      sbcs.sbaccess = 3'(t.default_size);
      dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {t.name, ".sbcs"});
      foreach (cases[i]) begin
        case (cases[i])
          "dtmcs_case": dtmcs_case(t);
          "ops_case": ops_case(t);
          "capture_during_read_case": capture_during_read_case(t);
          "update_during_write_case": update_during_write_case(t);
          "update_during_read_case": update_during_read_case(t);
          "dm_busy_case": dm_busy_case(t);
          "tck_stop_case": tck_stop_case(t);
          default: `uvm_fatal(get_type_name(), {"unknown case ", cases[i]})
        endcase
      end
      check_responder_activity(t, 1, {t.name, ".dmi_status"});
      close_bus_ledger();
      m_ledger = "";
      `uvm_info(get_type_name(), $sformatf("Summary: %s cases=%p", t.name, cases), UVM_LOW)
    end
  endtask

  // DTMCS shows the sticky status in dmistat; dmihardreset leaves it and
  // dmireset clears it, keeping the DMI address and data, and dmireset with
  // status 0 changes nothing.
  task dtmcs_case(dtp_j2a_target_t t);
    string ctx = {t.name, ".dtmcs"};
    dtmcs_scan(t, 32'(1) << DtpDtmcsDmiresetBit, DTP_DMI_SUCCESS, {ctx, ".clear"});
    select_dmi(t);
    dmi_raw(t, DTP_DM_DMCONTROL, 32'h1, DTP_DMI_OP_WRITE, DTP_DMI_SUCCESS, {ctx, ".write"}, 1'b1);
    dmi_zero_shift();
    run_test_idle(DmiIdleTck);
    dtmcs_scan(t, 32'(1) << DtpDtmcsDmihardresetBit, DTP_DMI_BUSY, {ctx, ".hard"});
    dtmcs_scan(t, 32'(1) << DtpDtmcsDmiresetBit, DTP_DMI_BUSY, {ctx, ".dmireset"});
    dtmcs_scan(t, '0, DTP_DMI_SUCCESS, {ctx, ".cleared"});
    select_dmi(t);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".kept"}, 1'b0, 1'b1,
            DTP_DM_DMCONTROL, 32'h1);
  endtask

  // With status 0, NOP and op 3 load the scanned address and data, a write
  // reaches the Debug Module register and a read returns it.
  task ops_case(dtp_j2a_target_t t);
    string     ctx = {t.name, ".ops"};
    bit [6:0]  nop_address = 7'($urandom());
    bit [31:0] nop_data = $urandom();
    bit [6:0]  clear_address = 7'($urandom());
    bit [31:0] clear_data = $urandom();
    bit [31:0] sbaddress0 = random_sbaddress0(t);
    select_dmi(t);
    dmi_raw(t, nop_address, nop_data, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".nop"});
    dmi_raw(t, clear_address, clear_data, DTP_DMI_OP_CLEAR, DTP_DMI_SUCCESS, {ctx, ".clear"}, 1'b0,
            1'b1, nop_address, nop_data);
    dmi_raw(t, DTP_DM_SBADDRESS0, sbaddress0, DTP_DMI_OP_WRITE, DTP_DMI_SUCCESS, {ctx, ".write"},
            1'b0, 1'b1, clear_address, clear_data);
    run_test_idle(DmiIdleTck);
    dmi_raw(t, DTP_DM_SBADDRESS0, $urandom(), DTP_DMI_OP_READ, DTP_DMI_SUCCESS, {ctx, ".read"},
            1'b0, 1'b1, DTP_DM_SBADDRESS0, sbaddress0);
    run_test_idle(DmiIdleTck);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".fetch"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
  endtask

  // A capture during a read is busy and shows the read's own address and
  // data; the update that follows is ignored, and op 3 clears the status
  // over the read data.
  task capture_during_read_case(dtp_j2a_target_t t);
    string     ctx = {t.name, ".capture_during_read"};
    bit [31:0] sbaddress0 = random_sbaddress0(t);
    bit [31:0] ignored = sbaddress0 ^ 32'h1;
    bit [31:0] op_data = $urandom();
    dmi_write(t, DTP_DM_SBADDRESS0, sbaddress0, {ctx, ".setup"});
    select_dmi(t);
    dmi_raw(t, DTP_DM_SBADDRESS0, op_data, DTP_DMI_OP_READ, DTP_DMI_SUCCESS, ctx, 1'b1);
    dmi_raw(t, DTP_DM_SBADDRESS0, ignored, DTP_DMI_OP_WRITE, DTP_DMI_BUSY, {ctx, ".busy"}, 1'b0,
            1'b1, DTP_DM_SBADDRESS0, op_data);
    run_test_idle(DmiIdleTck);
    dmi_raw(t, '0, '0, DTP_DMI_OP_CLEAR, DTP_DMI_BUSY, {ctx, ".after_clear"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".after_nop"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
    dmi_raw(t, DTP_DM_SBADDRESS0, '0, DTP_DMI_OP_READ, DTP_DMI_SUCCESS, ctx);
    run_test_idle(DmiIdleTck);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".unwritten"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
  endtask

  // An update during a write is busy while the write still reaches the Debug
  // Module; a later write is ignored without a bus access, and dmireset
  // clears the status.
  task update_during_write_case(dtp_j2a_target_t t);
    string     ctx = {t.name, ".update_during_write"};
    bit [31:0] sbaddress0 = random_sbaddress0(t);
    select_dmi(t);
    dmi_raw(t, DTP_DM_SBADDRESS0, sbaddress0, DTP_DMI_OP_WRITE, DTP_DMI_SUCCESS, ctx, 1'b1);
    dmi_zero_shift();
    run_test_idle(DmiIdleTck);
    dmi_raw(t, DTP_DM_SBDATA0, $urandom(), DTP_DMI_OP_WRITE, DTP_DMI_BUSY, {ctx, ".ignored"}, 1'b0,
            1'b1, DTP_DM_SBADDRESS0, sbaddress0);
    run_test_idle(DmiIdleTck);
    dtmcs_scan(t, 32'(1) << DtpDtmcsDmiresetBit, DTP_DMI_BUSY, {ctx, ".dmireset"});
    select_dmi(t);
    dmi_raw(t, DTP_DM_SBADDRESS0, '0, DTP_DMI_OP_READ, DTP_DMI_SUCCESS, {ctx, ".read"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
    run_test_idle(DmiIdleTck);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".written"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
  endtask

  // A scan that shifts no bit over a read captures busy and updates op 3,
  // which clears the status; the read completes.
  task update_during_read_case(dtp_j2a_target_t t);
    string     ctx = {t.name, ".update_during_read"};
    bit [31:0] sbaddress0 = random_sbaddress0(t);
    dmi_write(t, DTP_DM_SBADDRESS0, sbaddress0, {ctx, ".setup"});
    select_dmi(t);
    dmi_raw(t, DTP_DM_SBADDRESS0, $urandom(), DTP_DMI_OP_READ, DTP_DMI_SUCCESS, ctx, 1'b1);
    dmi_zero_shift();
    run_test_idle(DmiIdleTck);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".completed"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
  endtask

  // While a held write is outstanding the Debug Module refuses an sbaddress0
  // write and sets sbbusyerror; once the write completes it refuses an
  // sbdata0 read with 0xB051B051 until sbbusyerror is cleared.
  task dm_busy_case(dtp_j2a_target_t t);
    string           ctx = {t.name, ".dm_busy"};
    int unsigned     size = t.default_size;
    bit [63:0]       addr = random_target_addr(t);
    bit [63:0]       data = random_distinct_word(t);
    bit [7:0]        wstrb = dtp_j2a_full_wstrb(size);
    bit [31:0]       refused = $urandom();
    bit [31:0]       value;
    bit [1:0]        held_bits;
    dtp_sbcs_t       sbcs;
    ocah_axi_checker ev = evidence(t);
    if (target_enabled(t))
      target_cfgs[t.name].arm_expected_write(addr & bit_mask(t.addr_width), data, wstrb);
    sba_setup(t, addr, size, 1'b0, ctx);
    hold_responses(t, 1'b1, 1'b0);
    if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {ctx, ".sbdata1"});
    dmi_write(t, DTP_DM_SBDATA0, data[31:0], {ctx, ".sbdata0"});
    dmi_write(t, DTP_DM_SBADDRESS0, refused, {ctx, ".refused"});
    select_dmi(t);
    dmi_raw(t, '0, '0, DTP_DMI_OP_CLEAR, DTP_DMI_BUSY, {ctx, ".clear"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, refused);
    dmi_read(t, DTP_DM_SBCS, {ctx, ".sbcs"}, value);
    sbcs      = dtp_sbcs_t'(value);
    held_bits = {sbcs.sbbusy, sbcs.sbbusyerror};
    void'(ev.expect_equal(
        DtpJ2aFaultStatusCheckId,
        64'(held_bits),
        64'h3,
        $sformatf(
            "%s target=%s held (sbbusy, sbbusyerror)", ctx, t.name)
    ));
    hold_responses(t, 1'b0, 1'b0);
    expect_bus_request(t, 1'b0, addr, size, data, wstrb, ctx);
    wait_sba_idle(t, {ctx, ".released"}, 1'b1);
    check_target_word(t, addr, data, size, {ctx, ".mem"});
    select_dmi(t);
    dmi_raw(t, DTP_DM_SBDATA0, '0, DTP_DMI_OP_READ, DTP_DMI_SUCCESS, {ctx, ".read"});
    run_test_idle(DmiIdleTck);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_BUSY, {ctx, ".refused_read_nop"}, 1'b0, 1'b1,
            DTP_DM_SBDATA0, DmiDataBusy);
    dmi_raw(t, '0, '0, DTP_DMI_OP_CLEAR, DTP_DMI_BUSY, {ctx, ".refused_read_clear"}, 1'b0, 1'b1,
            DTP_DM_SBDATA0, DmiDataBusy);
    sbcs             = '0;
    sbcs.sbbusyerror = 1'b1;
    sbcs.sbaccess    = 3'(size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbbusyerror_w1"});
    wait_sba_idle(t, {ctx, ".cleared"});
  endtask

  // A read stays in progress while TCK is stopped in Run-Test/Idle, so the
  // next capture is busy; with TCK running it completes. The busy scan reads
  // dmstatus, so the captures after it tell an ignored read from one that ran.
  task tck_stop_case(dtp_j2a_target_t t);
    string     ctx = {t.name, ".tck_stop"};
    bit [31:0] sbaddress0 = random_sbaddress0(t);
    bit [31:0] op_data = $urandom();
    dmi_write(t, DTP_DM_SBADDRESS0, sbaddress0, {ctx, ".setup"});
    select_dmi(t);
    dmi_raw(t, DTP_DM_SBADDRESS0, op_data, DTP_DMI_OP_READ, DTP_DMI_SUCCESS, ctx);
    wait_sys_cycles($urandom_range(TckStopMax, TckStopMin));
    dmi_raw(t, DTP_DM_DMSTATUS, '0, DTP_DMI_OP_READ, DTP_DMI_BUSY, {ctx, ".stopped"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, op_data);
    run_test_idle(DmiIdleTck);
    dmi_raw(t, '0, '0, DTP_DMI_OP_CLEAR, DTP_DMI_BUSY, {ctx, ".after_clear"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".after_nop"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, sbaddress0);
  endtask

endclass : dtp_jtag2axi_dmi_status_test_seq
