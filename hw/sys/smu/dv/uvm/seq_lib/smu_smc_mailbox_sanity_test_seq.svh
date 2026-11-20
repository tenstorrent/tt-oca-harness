// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_smc_mailbox_sanity_test scenario sequence (SMC outbound mailbox 0
// over the SMC-fabric JTAG2AXI bridge), carrying the cocotb
// cocotb_wrapper/seq_lib/smu_smc_mailbox_sanity_test_seq.py semantics:
// S1 TAP reset to Run-Test/Idle, IDCODE and the bridge's lifecycle gate
// (CHK-MBX-JTAG-READY); S2 the idle STATUS and ERROR_FLAGS reads
// (CHK-MBX-STATUS, CHK-MBX-ERR-FLAGS); S3 an IRQEN write of every enable and
// its readback (CHK-MBX-IRQEN); S4 the IRQEN clear, its readback and a second
// STATUS read (CHK-MBX-IRQEN-CLR, CHK-MBX-STATUS); TIMEOUT the bounded-wait
// inventory (CHK-TIMEOUT-PATHS). Every access is a 4-byte SINGLE_OP whose
// bridge status is graded SUCCESS under the check of its step, and the pass
// ends with IRQEN back at its reset value. Independently, the embedded DTP's
// jtag2axi_req and jtag2axi_status features pair every bridge transaction.
// Each check has its own negative switch of smu_test_cfg that corrupts the
// expected value of that check only, so the run must FAIL on it.

class smu_smc_mailbox_sanity_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_smc_mailbox_sanity_test_seq)

  localparam string ChkJtagReady = "CHK-MBX-JTAG-READY";
  localparam string ChkStatus = "CHK-MBX-STATUS";
  localparam string ChkErrFlags = "CHK-MBX-ERR-FLAGS";
  localparam string ChkIrqen = "CHK-MBX-IRQEN";
  localparam string ChkIrqenClr = "CHK-MBX-IRQEN-CLR";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";

  localparam bit [63:0] StatusAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR);
  localparam bit [63:0] ErrFlagsAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_ERROR_FLAGS_BASE_ADDR);
  localparam bit [63:0] IrqenAddr =
      64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR);

  // Idle STATUS: the register's reset value (EMPTY set, FULL and both
  // thresholds clear).
  localparam bit [31:0] IdleStatus = 32'(smu_fcov_smc_csr_pkg::AXIL_MAILBOX_STATUS_REG_DEFAULT);
  localparam bit [31:0] StatusMask = 32'(
      smu_fcov_smc_csr_pkg::AXIL_MAILBOX_STATUS_EMPTY_MASK |
      smu_fcov_smc_csr_pkg::AXIL_MAILBOX_STATUS_FULL_MASK |
      smu_fcov_smc_csr_pkg::AXIL_MAILBOX_STATUS_WRITE_LEVEL_ABOVE_THRESH_MASK |
      smu_fcov_smc_csr_pkg::AXIL_MAILBOX_STATUS_READ_LEVEL_ABOVE_THRESH_MASK);
  localparam bit [31:0] IdleErrFlags = 32'(smu_fcov_smc_csr_pkg::AXIL_MAILBOX_ERROR_REG_DEFAULT);
  localparam bit [31:0] IrqenAll = 32'(
      smu_fcov_smc_csr_pkg::AXIL_MAILBOX_IRQEN_WTIRQ_MASK |
      smu_fcov_smc_csr_pkg::AXIL_MAILBOX_IRQEN_RTIRQ_MASK |
      smu_fcov_smc_csr_pkg::AXIL_MAILBOX_IRQEN_EIRQ_MASK);
  localparam bit [31:0] IrqenReset = 32'(smu_fcov_smc_csr_pkg::AXIL_MAILBOX_IRQEN_REG_DEFAULT);

  localparam int unsigned IdcodeWidth = 32;
  localparam int unsigned Size4B = 2;
  // Idle TCK cycles after the baseline reset (cocotb: eight TMS=0 steps).
  localparam int unsigned IdleAfterReset = 8;
  // Bridge transactions of a pass: seven SINGLE_OP accesses.
  localparam int unsigned BridgeOpsPerPass = 7;
  // Bounded-wait sites: s1_rti and one status poll per access.
  localparam int unsigned ExpectedTimeoutPaths = 8;

  protected dtp_env_pkg::dtp_j2a_target_t m_target;

  function new(string name = "smu_smc_mailbox_sanity_test_seq");
    super.new(name);
  endfunction

  task body();
    m_target = j2a_target_smc_axi();

    seed_scenario_rng();
    attach_evidence('{ChkJtagReady, ChkStatus, ChkErrFlags, ChkIrqen, ChkIrqenClr, ChkTimeoutPaths,
                    ChkSbMinAct});
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiReq, BridgeOpsPerPass);
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiStatus, BridgeOpsPerPass);
    `uvm_info(get_type_name(),
              $sformatf({"SMU SV-UVM SMC mailbox sanity (smu_smc_mailbox_sanity_test): ",
                         "status=0x%0h err_flags=0x%0h irqen=0x%0h; scenario_seed=%0d"},
                          StatusAddr, ErrFlagsAddr, IrqenAddr, scenario_seed), UVM_LOW)

    run_setup();
    run_idle_registers();
    run_irqen_readback();
    run_irqen_clear();
    run_timeout_inventory(ChkTimeoutPaths, ExpectedTimeoutPaths);

    finalize_evidence();
    mark_step("END", "scenario complete");
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
    check_evidence(ChkJtagReady, "IDCODE", observed[31:0], smu_ptap_expected_idcode(
                   test_cfg.mbx_jtag_ready_negative));
    check_pin(ChkJtagReady, "smc_jtag2axi_security_disable", "smc_jtag2axi_security_disable",
              test_cfg.mbx_jtag_ready_negative);
  endtask

  // S2: the idle STATUS and ERROR_FLAGS of outbound mailbox 0.
  protected task run_idle_registers();
    bit [63:0] rdata;
    mark_step("S2", "ACTION/RESPONSE: read STATUS and ERROR_FLAGS of outbound mailbox 0");
    read_j2a_checked(m_target, ChkStatus, "STATUS", StatusAddr, Size4B, "s2_status_rd_poll", rdata);
    check_evidence(ChkStatus, "idle STATUS", rdata[31:0],
                   IdleStatus ^ 32'(test_cfg.mbx_status_negative), $sformatf(
                   "addr=0x%0h", StatusAddr));
    read_j2a_checked(m_target, ChkErrFlags, "ERROR_FLAGS", ErrFlagsAddr, Size4B,
                     "s2_err_flags_rd_poll", rdata);
    check_evidence(ChkErrFlags, "ERROR_FLAGS", rdata[31:0],
                   IdleErrFlags ^ 32'(test_cfg.mbx_err_flags_negative), $sformatf(
                   "addr=0x%0h", ErrFlagsAddr));
  endtask

  // S3: IRQEN write of every enable and readback.
  protected task run_irqen_readback();
    bit [63:0] rdata;
    mark_step("S3", "ACTION/RESPONSE: write IRQEN with WTIRQ|RTIRQ|EIRQ then read it back");
    write_j2a_checked(m_target, ChkIrqen, "IRQEN", IrqenAddr, 64'(IrqenAll), 8'h0F, Size4B,
                      "s3_irqen_wr_poll");
    read_j2a_checked(m_target, ChkIrqen, "IRQEN", IrqenAddr, Size4B, "s3_irqen_rd_poll", rdata);
    check_evidence(ChkIrqen, "IRQEN readback", rdata[31:0],
                   IrqenAll ^ 32'(test_cfg.mbx_irqen_negative), $sformatf("addr=0x%0h", IrqenAddr));
  endtask

  // S4: IRQEN back to its reset value, and STATUS once more.
  protected task run_irqen_clear();
    bit [63:0] rdata;
    mark_step("S4", "ACTION/RESPONSE: clear IRQEN, read it back, read STATUS again");
    write_j2a_checked(m_target, ChkIrqenClr, "IRQEN clear", IrqenAddr, 64'(IrqenReset), 8'h0F,
                      Size4B, "s4_irqen_clr_wr_poll");
    read_j2a_checked(m_target, ChkIrqenClr, "IRQEN clear", IrqenAddr, Size4B,
                     "s4_irqen_clr_rd_poll", rdata);
    check_evidence(ChkIrqenClr, "IRQEN after clear", rdata[31:0],
                   IrqenReset ^ 32'(test_cfg.mbx_irqen_clr_negative), $sformatf(
                   "addr=0x%0h", IrqenAddr));
    read_j2a_checked(m_target, ChkStatus, "STATUS after IRQEN clear", StatusAddr, Size4B,
                     "s4_status_rd_poll", rdata);
    check_evidence(ChkStatus, "STATUS after IRQEN clear", rdata[31:0] & StatusMask,
                   IdleStatus ^ 32'(test_cfg.mbx_status_negative), $sformatf(
                   "addr=0x%0h", StatusAddr));
  endtask

endclass : smu_smc_mailbox_sanity_test_seq
