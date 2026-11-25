// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_smc_wdt_sanity_test scenario sequence (CORE0 watchdog magic unlock and
// CMP programming over the SMC-fabric JTAG2AXI bridge), carrying the cocotb
// cocotb_wrapper/seq_lib/smu_smc_wdt_sanity_test_seq.py semantics:
// S1 TAP reset to Run-Test/Idle, IDCODE and the bridge's lifecycle gate
// (CHK-WDT-SANITY-GATE-OPEN); S2 the CMP reset value (CHK-WDT-CMP-DEFAULT);
// S3 a CTRL write while locked that leaves WDOGSCALE unchanged
// (CHK-WDT-CTRL-LOCKED); S4 the KEY unlock and its readback
// (CHK-WDT-KEY-UNLOCKED); S5 a CTRL write after the unlock
// (CHK-WDT-CTRL-UNLOCKED); S6 the unlock and CMP programming
// (CHK-WDT-UNLOCK); S7 the restore of CMP and CTRL to their reset values, so
// the next pass starts from the reset state (CHK-WDT-RESTORE); TIMEOUT the
// bounded-wait inventory (CHK-TIMEOUT-PATHS). Every access is a SINGLE_OP
// whose bridge status is graded SUCCESS under the check of its step.
// Independently, the embedded DTP's jtag2axi_req and jtag2axi_status features
// pair every bridge transaction. Each check has its own negative switch of
// smu_test_cfg that corrupts the expected value of that check only, so the
// run must FAIL on it.

class smu_smc_wdt_sanity_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_smc_wdt_sanity_test_seq)

  localparam string ChkGateOpen = "CHK-WDT-SANITY-GATE-OPEN";
  localparam string ChkCmpDefault = "CHK-WDT-CMP-DEFAULT";
  localparam string ChkCtrlLocked = "CHK-WDT-CTRL-LOCKED";
  localparam string ChkKeyUnlocked = "CHK-WDT-KEY-UNLOCKED";
  localparam string ChkCtrlUnlocked = "CHK-WDT-CTRL-UNLOCKED";
  localparam string ChkUnlock = "CHK-WDT-UNLOCK";
  localparam string ChkRestore = "CHK-WDT-RESTORE";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";

  localparam bit [63:0] CtrlAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR);
  localparam bit [63:0] FeedAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_FEED_BASE_ADDR);
  localparam bit [63:0] KeyAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR);
  localparam bit [63:0] CmpAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_CMP_BASE_ADDR);

  // The KEY magic of the watchdog register specification; the generated
  // headers carry no define for it.
  localparam bit [31:0] KeyMagic = 32'h0051_F15E;
  // KEY's 32-bit lane within its 8-byte beat, from the register address.
  localparam int unsigned KeyShift = 32 * int'(KeyAddr[2]);
  localparam bit [7:0] KeyStrobe = 8'h0F << (4 * int'(KeyAddr[2]));
  localparam bit [31:0] ScaleMask = 32'(smu_fcov_smc_csr_pkg::WDT_CTRL_WDOGSCALE_MASK);
  localparam bit [31:0] CmpMask = 32'(smu_fcov_smc_csr_pkg::WDT_CMP_WDOGCMP0_MASK);
  localparam bit [31:0] CmpReset = 32'(smu_fcov_smc_csr_pkg::WDT_CMP_REG_DEFAULT);
  localparam bit [31:0] CtrlReset = 32'(smu_fcov_smc_csr_pkg::WDT_CTRL_REG_DEFAULT);
  // The directed programming of the cocotb scenario.
  localparam bit [31:0] ScaleProgrammed = 32'h1;
  localparam bit [31:0] CmpProgrammed = 32'h2345;

  localparam int unsigned IdcodeWidth = 32;
  // AxSIZE encodings of the 32-bit register access and the 64-bit KEY lane.
  localparam int unsigned Size4B = 2;
  localparam int unsigned Size8B = 3;
  // Idle TCK cycles after the baseline reset (cocotb: eight TMS=0 steps).
  localparam int unsigned IdleAfterReset = 8;
  // Bridge transactions of a pass: sixteen SINGLE_OP accesses.
  localparam int unsigned BridgeOpsPerPass = 16;
  // Bounded-wait sites: s1_rti and one status poll per access.
  localparam int unsigned ExpectedTimeoutPaths = 17;

  protected dtp_env_pkg::dtp_j2a_target_t m_target;

  function new(string name = "smu_smc_wdt_sanity_test_seq");
    super.new(name);
  endfunction

  task body();
    m_target = j2a_target_smc_axi();

    seed_scenario_rng();
    attach_evidence('{ChkGateOpen, ChkCmpDefault, ChkCtrlLocked, ChkKeyUnlocked, ChkCtrlUnlocked,
                    ChkUnlock, ChkRestore, ChkTimeoutPaths, ChkSbMinAct});
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiReq, BridgeOpsPerPass);
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiStatus, BridgeOpsPerPass);
    `uvm_info(get_type_name(),
              $sformatf({"SMU SV-UVM SMC WDT sanity (smu_smc_wdt_sanity_test): ctrl=0x%0h ",
                         "key=0x%0h cmp=0x%0h; scenario_seed=%0d"}, CtrlAddr, KeyAddr, CmpAddr,
                          scenario_seed), UVM_LOW)

    run_setup();
    run_cmp_default();
    run_ctrl_locked();
    run_key_unlocked();
    run_ctrl_unlocked();
    run_unlock_cmp();
    run_restore();
    run_timeout_inventory(ChkTimeoutPaths, ExpectedTimeoutPaths);

    finalize_evidence();
    mark_step("END", "scenario complete");
  endtask

  // KEY write that unlocks the next register write, graded under `check_id`.
  protected task unlock(string check_id, string label);
    write_j2a_checked(m_target, check_id, "KEY unlock", KeyAddr, 64'(KeyMagic) << KeyShift,
                      KeyStrobe, Size4B, label);
  endtask

  // S1: TAP reset, IDCODE and the bridge's lifecycle gate.
  protected task run_setup();
    bit [15:0] last;
    bit [63:0] observed;
    mark_step("S1",
              "SETUP: TAP reset then Run-Test/Idle; IDCODE; SMC JTAG2AXI lifecycle gate open");
    tap_reset();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    confirm_state_tck(OCAH_JTAG_RUN_TEST_IDLE, "s1_rti", 1'b0, last);
    idle_tck(IdleAfterReset);
    load_ir(dtp_env_pkg::IDCODE_INSTR);
    dr_scan(64'h0, IdcodeWidth, observed);
    check_evidence(ChkGateOpen, "IDCODE", observed[31:0], smu_ptap_expected_idcode(
                   test_cfg.wdt_sanity_gate_open_negative));
    check_pin(ChkGateOpen, "smc_jtag2axi_security_disable", "smc_jtag2axi_security_disable",
              test_cfg.wdt_sanity_gate_open_negative);
  endtask

  // S2: CMP holds its reset value.
  protected task run_cmp_default();
    bit [63:0] rdata;
    mark_step("S2", "ACTION/RESPONSE: read CMP, expecting its reset value");
    read_j2a_checked(m_target, ChkCmpDefault, "CMP", CmpAddr, Size4B, "s2_cmp_rd_poll", rdata);
    check_evidence(ChkCmpDefault, "CMP reset value", rdata[31:0] & CmpMask,
                   CmpReset ^ 32'(test_cfg.wdt_cmp_default_negative), $sformatf(
                   "addr=0x%0h", CmpAddr));
  endtask

  // S3: a CTRL write while the watchdog is locked returns OKAY and changes
  // nothing.
  protected task run_ctrl_locked();
    bit [63:0] rdata;
    mark_step("S3", "ACTION/RESPONSE: CTRL write while locked, WDOGSCALE stays at its reset value");
    write_j2a_checked(m_target, ChkCtrlLocked, "CTRL locked", CtrlAddr, 64'(ScaleProgrammed), 8'h0F,
                      Size4B, "s3_ctrl_locked_wr_poll");
    read_j2a_checked(m_target, ChkCtrlLocked, "CTRL locked", CtrlAddr, Size4B,
                     "s3_ctrl_locked_rd_poll", rdata);
    check_evidence(ChkCtrlLocked, "WDOGSCALE after locked write", rdata[31:0] & ScaleMask,
                   (CtrlReset & ScaleMask) ^ 32'(test_cfg.wdt_ctrl_locked_negative), $sformatf(
                   "addr=0x%0h", CtrlAddr));
  endtask

  // S4: the magic KEY write unlocks, and a KEY read through the 8-byte
  // FEED/KEY lane returns 1 in its upper word.
  protected task run_key_unlocked();
    bit [63:0] rdata;
    mark_step("S4", "ACTION/RESPONSE: write the KEY magic, read KEY back through the 8-byte lane");
    unlock(ChkKeyUnlocked, "s4_key_wr_poll");
    read_j2a_checked(m_target, ChkKeyUnlocked, "KEY", FeedAddr, Size8B, "s4_key_rd_poll", rdata);
    check_evidence(ChkKeyUnlocked, "KEY readback", rdata[KeyShift+:32],
                   32'(!test_cfg.wdt_key_unlocked_negative), $sformatf("addr=0x%0h", FeedAddr));
  endtask

  // S5: a CTRL write after the unlock takes effect.
  protected task run_ctrl_unlocked();
    bit [63:0] rdata;
    mark_step("S5", "ACTION/RESPONSE: CTRL write after the unlock, WDOGSCALE takes the value");
    write_j2a_checked(m_target, ChkCtrlUnlocked, "CTRL unlocked", CtrlAddr, 64'(ScaleProgrammed),
                      8'h0F, Size4B, "s5_ctrl_unlocked_wr_poll");
    read_j2a_checked(m_target, ChkCtrlUnlocked, "CTRL unlocked", CtrlAddr, Size4B,
                     "s5_ctrl_unlocked_rd_poll", rdata);
    check_evidence(ChkCtrlUnlocked, "WDOGSCALE after unlocked write", rdata[31:0] & ScaleMask,
                   ScaleProgrammed ^ 32'(test_cfg.wdt_ctrl_unlocked_negative), $sformatf(
                   "addr=0x%0h", CtrlAddr));
  endtask

  // S6: unlock, then program CMP.
  protected task run_unlock_cmp();
    bit [63:0] rdata;
    mark_step("S6", "ACTION/RESPONSE: unlock, write CMP, read it back");
    unlock(ChkUnlock, "s6_key_wr_poll");
    write_j2a_checked(m_target, ChkUnlock, "CMP", CmpAddr, 64'(CmpProgrammed), 8'h0F, Size4B,
                      "s6_cmp_wr_poll");
    read_j2a_checked(m_target, ChkUnlock, "CMP", CmpAddr, Size4B, "s6_cmp_rd_poll", rdata);
    check_evidence(ChkUnlock, "CMP programmed", rdata[31:0] & CmpMask,
                   CmpProgrammed ^ 32'(test_cfg.wdt_unlock_negative), $sformatf(
                   "addr=0x%0h", CmpAddr));
  endtask

  // S7: CMP and CTRL back to their reset values, each behind its own unlock.
  protected task run_restore();
    bit [63:0] rdata;
    mark_step("S7", "RESTORE: CMP and CTRL back to their reset values, both read back");
    unlock(ChkRestore, "s7_cmp_key_wr_poll");
    write_j2a_checked(m_target, ChkRestore, "CMP restore", CmpAddr, 64'(CmpReset), 8'h0F, Size4B,
                      "s7_cmp_wr_poll");
    unlock(ChkRestore, "s7_ctrl_key_wr_poll");
    write_j2a_checked(m_target, ChkRestore, "CTRL restore", CtrlAddr, 64'(CtrlReset), 8'h0F, Size4B,
                      "s7_ctrl_wr_poll");
    read_j2a_checked(m_target, ChkRestore, "CTRL restore", CtrlAddr, Size4B, "s7_ctrl_rd_poll",
                     rdata);
    check_evidence(ChkRestore, "CTRL after restore", rdata[31:0], CtrlReset, $sformatf(
                   "addr=0x%0h", CtrlAddr));
    read_j2a_checked(m_target, ChkRestore, "CMP restore", CmpAddr, Size4B, "s7_cmp_rd_poll", rdata);
    check_evidence(ChkRestore, "CMP after restore", rdata[31:0] & CmpMask,
                   CmpReset ^ 32'(test_cfg.wdt_restore_negative), $sformatf("addr=0x%0h", CmpAddr));
  endtask

endclass : smu_smc_wdt_sanity_test_seq
