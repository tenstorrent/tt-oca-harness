// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_smc_wdt_timeout_irq_test scenario sequence (CORE0 watchdog first
// timeout over the SMC-fabric JTAG2AXI bridge), carrying the cocotb
// cocotb_wrapper/seq_lib/smu_smc_wdt_timeout_irq_test_seq.py semantics:
// S1 TAP reset to Run-Test/Idle, IDCODE and the bridge's lifecycle gate
// (CHK-WDT-TO-GATE-OPEN); S2 CMP programmed to a small value
// (CHK-WDT-TO-CMP) with WDOGIP0 still clear (CHK-WDT-TO-IP0-PRE); S3 the
// counter enabled (CHK-WDT-TO-EN); S4 WDOGIP0 polled until set, then sampled
// four more times 512 SMU clocks apart with no software clear in between
// (CHK-WDT-IP0); S5 the restore of CMP, CTRL and COUNT, so the next pass
// starts with WDOGIP0 clear and the counter at zero (CHK-WDT-TO-RESTORE);
// TIMEOUT the bounded-wait inventory (CHK-TIMEOUT-PATHS), one site per access
// plus the TAP-state confirmation and the WDOGIP0 poll loop. The scenario
// observes the interrupt as the CTRL.WDOGIP0 register bit; interrupt delivery
// is not claimed. Independently, the embedded DTP's jtag2axi_req and
// jtag2axi_status features pair every bridge transaction. Each check has its
// own negative switch of smu_test_cfg that corrupts the expected value of
// that check only, so the run must FAIL on it.

class smu_smc_wdt_timeout_irq_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_smc_wdt_timeout_irq_test_seq)

  localparam string ChkGateOpen = "CHK-WDT-TO-GATE-OPEN";
  localparam string ChkCmp = "CHK-WDT-TO-CMP";
  localparam string ChkIp0Pre = "CHK-WDT-TO-IP0-PRE";
  localparam string ChkEnable = "CHK-WDT-TO-EN";
  localparam string ChkIp0 = "CHK-WDT-IP0";
  localparam string ChkRestore = "CHK-WDT-TO-RESTORE";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";

  localparam bit [63:0] CtrlAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_CTRL_BASE_ADDR);
  localparam bit [63:0] CountAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_COUNT_BASE_ADDR);
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
  localparam bit [31:0] CmpMask = 32'(smu_fcov_smc_csr_pkg::WDT_CMP_WDOGCMP0_MASK);
  localparam bit [31:0] CountMask = 32'(smu_fcov_smc_csr_pkg::WDT_COUNT_WDOGCOUNT_MASK);
  localparam bit [31:0] Ip0Mask = 32'(smu_fcov_smc_csr_pkg::WDT_CTRL_WDOGIP0_MASK);
  localparam bit [31:0] ZeroCmpMask = 32'(smu_fcov_smc_csr_pkg::WDT_CTRL_WDOGZEROCMP_MASK);
  localparam bit [31:0] EnAlwaysMask = 32'(smu_fcov_smc_csr_pkg::WDT_CTRL_WDOGENALWAYS_MASK);
  localparam bit [31:0] CmpReset = 32'(smu_fcov_smc_csr_pkg::WDT_CMP_REG_DEFAULT);
  localparam bit [31:0] CtrlReset = 32'(smu_fcov_smc_csr_pkg::WDT_CTRL_REG_DEFAULT);
  localparam bit [31:0] CountReset = 32'(smu_fcov_smc_csr_pkg::WDT_COUNT_REG_DEFAULT);
  // The cocotb scenario's compare value, and the CTRL bits that count and
  // reset the counter at the compare value.
  localparam bit [31:0] CmpSmall = 32'h10;
  // A COUNT pattern inside WDOGCOUNT, above CmpSmall, written while the counter
  // is frozen so the restore's zero write is read back against a non-zero value.
  localparam bit [31:0] CountPattern = 32'h0000_0A5A;
  localparam bit [31:0] CtrlEnable = EnAlwaysMask | ZeroCmpMask;

  localparam int unsigned IdcodeWidth = 32;
  localparam int unsigned Size4B = 2;
  // Idle TCK cycles after the baseline reset (cocotb: eight TMS=0 steps).
  localparam int unsigned IdleAfterReset = 8;
  // SMU clocks from the enable to the first WDOGIP0 poll, and between polls
  // and hold samples (cocotb: max(CMP * 64, 2048) and 512).
  localparam int unsigned EnableWaitCycles = 2048;
  localparam int unsigned SampleGapCycles = 512;
  localparam int unsigned MaxIp0Polls = 32;
  localparam int unsigned HoldSamples = 4;
  // Bridge transactions of a pass whose first poll already reads WDOGIP0
  // set: twenty-five SINGLE_OP accesses. Every further poll adds one.
  localparam int unsigned BridgeOpsPerPass = 25;
  // Accesses of a pass outside the poll loop, and the bounded-wait sites
  // beside them: s1_rti and the poll loop.
  localparam int unsigned FixedAccesses = 24;
  localparam int unsigned ExtraTimeoutSites = 2;

  protected dtp_env_pkg::dtp_j2a_target_t m_target;

  function new(string name = "smu_smc_wdt_timeout_irq_test_seq");
    super.new(name);
  endfunction

  task body();
    int unsigned polls;
    m_target = j2a_target_smc_axi();

    seed_scenario_rng();
    attach_evidence('{ChkGateOpen, ChkCmp, ChkIp0Pre, ChkEnable, ChkIp0, ChkRestore,
                    ChkTimeoutPaths, ChkSbMinAct});
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiReq, BridgeOpsPerPass);
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiStatus, BridgeOpsPerPass);
    `uvm_info(get_type_name(),
              $sformatf({"SMU SV-UVM SMC WDT timeout (smu_smc_wdt_timeout_irq_test): ctrl=0x%0h ",
                         "cmp=0x%0h; scenario_seed=%0d"}, CtrlAddr, CmpAddr, scenario_seed),
              UVM_LOW)

    run_setup();
    run_program_cmp();
    run_enable();
    run_ip0_set(polls);
    run_ip0_hold();
    run_restore();
    run_timeout_inventory(ChkTimeoutPaths, ExtraTimeoutSites + FixedAccesses + polls);

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
                   test_cfg.wdt_to_gate_open_negative));
    check_pin(ChkGateOpen, "smc_jtag2axi_security_disable", "smc_jtag2axi_security_disable",
              test_cfg.wdt_to_gate_open_negative);
  endtask

  // S2: CMP set to the small compare value, WDOGIP0 clear before the enable.
  protected task run_program_cmp();
    bit [63:0] rdata;
    mark_step("S2",
              "ACTION/RESPONSE: unlock, write CMP, read it back; WDOGIP0 clear before enable");
    unlock(ChkCmp, "s2_cmp_key_wr_poll");
    write_j2a_checked(m_target, ChkCmp, "CMP", CmpAddr, 64'(CmpSmall), 8'h0F, Size4B,
                      "s2_cmp_wr_poll");
    read_j2a_checked(m_target, ChkCmp, "CMP", CmpAddr, Size4B, "s2_cmp_rd_poll", rdata);
    check_evidence(ChkCmp, "CMP programmed", rdata[31:0] & CmpMask,
                   CmpSmall ^ 32'(test_cfg.wdt_to_cmp_negative), $sformatf("addr=0x%0h", CmpAddr));
    read_j2a_checked(m_target, ChkIp0Pre, "CTRL", CtrlAddr, Size4B, "s2_ip0_pre_rd_poll", rdata);
    check_evidence(ChkIp0Pre, "WDOGIP0 before enable", rdata[31:0] & Ip0Mask,
                   test_cfg.wdt_to_ip0_pre_negative ? Ip0Mask : 32'h0, $sformatf(
                   "addr=0x%0h", CtrlAddr));
  endtask

  // S3: the counter enabled, counting and resetting at the compare value.
  protected task run_enable();
    bit [63:0] rdata;
    mark_step("S3", "ACTION/RESPONSE: unlock, write CTRL with WDOGENALWAYS|WDOGZEROCMP, read back");
    unlock(ChkEnable, "s3_ctrl_key_wr_poll");
    write_j2a_checked(m_target, ChkEnable, "CTRL enable", CtrlAddr, 64'(CtrlEnable), 8'h0F, Size4B,
                      "s3_ctrl_wr_poll");
    read_j2a_checked(m_target, ChkEnable, "CTRL enable", CtrlAddr, Size4B, "s3_ctrl_rd_poll",
                     rdata);
    check_evidence(ChkEnable, "WDOGENALWAYS|WDOGZEROCMP", rdata[31:0] & CtrlEnable,
                   CtrlEnable ^ (test_cfg.wdt_to_en_negative ? ZeroCmpMask : 32'h0), $sformatf(
                   "addr=0x%0h", CtrlAddr));
  endtask

  // S4a: the wait for the first timeout, then CTRL polled until WDOGIP0 is
  // set; `polls` counts the reads.
  protected task run_ip0_set(output int unsigned polls);
    bit [63:0] rdata;
    bit ip0_set = 1'b0;
    mark_step("S4", "ACTION/RESPONSE: wait for the first timeout, poll CTRL until WDOGIP0 is set");
    wait_smu_cycles(EnableWaitCycles);
    polls = 0;
    while (!ip0_set && polls < MaxIp0Polls) begin
      read_j2a_checked(m_target, ChkIp0, "CTRL", CtrlAddr, Size4B, $sformatf(
                       "s4_ip0_poll_%0d", polls), rdata);
      polls++;
      ip0_set = |(rdata[31:0] & Ip0Mask);
      if (!ip0_set && polls < MaxIp0Polls) wait_smu_cycles(SampleGapCycles);
    end
    record_timeout_path("s4_ip0_poll_loop", MaxIp0Polls, ip0_set, 16'(rdata[31:16]));
    check_evidence(ChkIp0, "WDOGIP0 set after enable", rdata[31:0] & Ip0Mask, Ip0Mask, $sformatf(
                   "polls=%0d", polls));
  endtask

  // S4b: WDOGIP0 stays set at every sample of the hold window, and the
  // counter is readable.
  protected task run_ip0_hold();
    bit [63:0] rdata;
    for (int unsigned sample = 0; sample < HoldSamples; sample ++) begin
      wait_smu_cycles(SampleGapCycles);
      read_j2a_checked(m_target, ChkIp0, "CTRL hold", CtrlAddr, Size4B, $sformatf(
                       "s4_ip0_hold_%0d", sample), rdata);
      check_evidence(ChkIp0, "WDOGIP0 held", rdata[31:0] & Ip0Mask,
                     test_cfg.wdt_ip0_negative ? 32'h0 : Ip0Mask, $sformatf("sample=%0d", sample));
    end
    read_j2a_checked(m_target, ChkIp0, "COUNT", CountAddr, Size4B, "s4_count_rd_poll", rdata);
    check_evidence(ChkIp0, "COUNT at most CMP", 64'((rdata[31:0] & CountMask) <= CmpSmall),
                   test_cfg.wdt_ip0_negative ? 64'h0 : 64'h1, $sformatf(
                   "count=0x%0h cmp=0x%0h WDOGSCALE=0 WDOGZEROCMP=1 wdogcount",
                   rdata[31:0] & CountMask,
                   CmpSmall
                   ));
  endtask

  // S5: CMP, CTRL and COUNT back to their reset values, each behind its own
  // unlock. CMP returns first, so the WDOGIP0 clear never lands on the cycle
  // the count meets the compare value. With CTRL back at 0 the counter is
  // frozen, so a non-zero COUNT pattern written and read back before the zero
  // write shows that the COUNT write lands.
  protected task run_restore();
    bit [63:0] rdata;
    mark_step("S5", "RESTORE: CMP, CTRL and COUNT back to reset values, each read back");
    unlock(ChkRestore, "s5_cmp_key_wr_poll");
    write_j2a_checked(m_target, ChkRestore, "CMP restore", CmpAddr, 64'(CmpReset), 8'h0F, Size4B,
                      "s5_cmp_wr_poll");
    unlock(ChkRestore, "s5_ctrl_key_wr_poll");
    write_j2a_checked(m_target, ChkRestore, "CTRL restore", CtrlAddr, 64'(CtrlReset), 8'h0F, Size4B,
                      "s5_ctrl_wr_poll");
    unlock(ChkRestore, "s5_pattern_key_wr_poll");
    write_j2a_checked(m_target, ChkRestore, "COUNT pattern write", CountAddr, 64'(CountPattern),
                      8'h0F, Size4B, "s5_pattern_wr_poll");
    read_j2a_checked(m_target, ChkRestore, "COUNT pattern write", CountAddr, Size4B,
                     "s5_pattern_rd_poll", rdata);
    check_evidence(ChkRestore, "COUNT pattern write", rdata[31:0] & CountMask,
                   CountPattern ^ 32'(test_cfg.wdt_to_restore_negative), $sformatf(
                   "addr=0x%0h", CountAddr));
    unlock(ChkRestore, "s5_count_key_wr_poll");
    write_j2a_checked(m_target, ChkRestore, "COUNT restore", CountAddr, 64'(CountReset), 8'h0F,
                      Size4B, "s5_count_wr_poll");
    read_j2a_checked(m_target, ChkRestore, "CTRL restore", CtrlAddr, Size4B, "s5_ctrl_rd_poll",
                     rdata);
    check_evidence(ChkRestore, "CTRL after restore", rdata[31:0],
                   CtrlReset ^ 32'(test_cfg.wdt_to_restore_negative), $sformatf(
                   "addr=0x%0h", CtrlAddr));
    read_j2a_checked(m_target, ChkRestore, "CMP restore", CmpAddr, Size4B, "s5_cmp_rd_poll", rdata);
    check_evidence(ChkRestore, "CMP after restore", rdata[31:0] & CmpMask, CmpReset, $sformatf(
                   "addr=0x%0h", CmpAddr));
    read_j2a_checked(m_target, ChkRestore, "COUNT restore", CountAddr, Size4B, "s5_count_rd_poll",
                     rdata);
    check_evidence(ChkRestore, "COUNT after restore", rdata[31:0],
                   CountReset ^ 32'(test_cfg.wdt_to_restore_negative), $sformatf(
                   "addr=0x%0h", CountAddr));
  endtask

endclass : smu_smc_wdt_timeout_irq_test_seq
