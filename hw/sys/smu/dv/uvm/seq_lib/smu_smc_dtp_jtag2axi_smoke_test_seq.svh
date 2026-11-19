// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_smc_dtp_jtag2axi_smoke_test scenario sequence (SMC-fabric JTAG2AXI
// smoke on the SEP=1 wrapper), carrying the cocotb
// cocotb_wrapper/seq_lib/smu_smc_dtp_jtag2axi_smoke_test_seq.py semantics:
// S1 TAP reset to Run-Test/Idle, IDCODE confirmed, the bridge's lifecycle
// gate open and SMC_DTMCS equal to the expected DTMCS value
// (CHK-JTAG2AXI-SMOKE-JTAG-READY, CHK-JTAG2AXI-SMOKE-GATE-OPEN); S2 a 32-bit
// System Bus Access write and readback of CPU_CTRL SCRATCH_15 -- SCRATCH_0 is
// the live boot-ROM mailbox (CHK-JTAG2AXI-SMOKE-SCRATCH); S3 a 64-bit write
// and readback of the SPM base word (CHK-JTAG2AXI-SMOKE-SPM); TIMEOUT the
// bounded-wait inventory (CHK-TIMEOUT-PATHS). The directed patterns of the
// cocotb twin run on pass 0; later passes draw seeded patterns.
// Independently, the embedded DTP's jtag2axi_req feature pairs every bridge
// transaction the passive monitor sees on the SMC debug port with the
// request the scans encoded, and jtag2axi_status pairs every DTMCS and DMI
// capture with the value and status the bridge presents;
// +SMU_J2A_SCOREBOARD_NEGATIVE corrupts the predicted addresses so the run
// must FAIL.

class smu_smc_dtp_jtag2axi_smoke_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_smc_dtp_jtag2axi_smoke_test_seq)

  localparam string ChkJtagReady = "CHK-JTAG2AXI-SMOKE-JTAG-READY";
  localparam string ChkGateOpen = "CHK-JTAG2AXI-SMOKE-GATE-OPEN";
  localparam string ChkScratch = "CHK-JTAG2AXI-SMOKE-SCRATCH";
  localparam string ChkSpm = "CHK-JTAG2AXI-SMOKE-SPM";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";

  // The cocotb scenario's directed patterns.
  localparam bit [31:0] ScratchPattern = 32'hDEAD_BEEF;
  localparam bit [63:0] SpmPattern = 64'h5A17_C0DE_CAFE_1234;
  localparam int unsigned IdcodeWidth = 32;
  // AxSIZE encodings of the 32-bit CSR and the 64-bit memory access.
  localparam int unsigned Size4B = 2;
  localparam int unsigned Size8B = 3;
  // Idle TCK cycles after the baseline reset (cocotb: eight TMS=0 steps).
  localparam int unsigned IdleAfterReset = 8;
  // Bridge transactions a pass launches: two writes and two reads.
  localparam int unsigned BridgeOpsPerPass = 4;
  // Bounded-wait sites: s1_rti, s2_wr_poll, s2_rd_poll, s3_wr_poll,
  // s3_rd_poll.
  localparam int unsigned ExpectedTimeoutPaths = 5;

  function new(string name = "smu_smc_dtp_jtag2axi_smoke_test_seq");
    super.new(name);
  endfunction

  task body();
    dtp_env_pkg::dtp_j2a_target_t target = j2a_target_smc_axi();
    bit [31:0] scratch_pat;
    bit [63:0] spm_pat;

    seed_scenario_rng();
    attach_evidence('{ChkJtagReady, ChkGateOpen, ChkScratch, ChkSpm, ChkTimeoutPaths, ChkSbMinAct});
    // Every launched transaction reaches the jtag2axi_req predictor, and
    // every access takes several DMI captures, so the status predictor
    // compares at least as many captures.
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiReq, BridgeOpsPerPass);
    check_min_activity(dtp_env_pkg::DtpFeatureJtag2axiStatus, BridgeOpsPerPass);
    scratch_pat = (loop_index == 0) ? ScratchPattern : 32'(random_pattern(32));
    spm_pat     = (loop_index == 0) ? SpmPattern : random_pattern(64);
    `uvm_info(get_type_name(),
              $sformatf({"SMU SV-UVM SMC-fabric JTAG2AXI smoke (smu_smc_dtp_jtag2axi_smoke_test): ",
                         "scratch15=0x%0h spm=0x%0h; scenario_seed=%0d patterns=%s"},
                          SmuSmcScratch15Addr, SmuSmcSpmBaseAddr, scenario_seed,
                          (loop_index == 0) ? "directed" : "seeded"), UVM_LOW)

    run_setup(target);
    run_scratch(target, scratch_pat);
    run_spm(target, spm_pat);
    run_timeout_inventory(ChkTimeoutPaths, ExpectedTimeoutPaths);

    mark_step("PASS", "scenario complete");
    finalize_evidence();
  endtask

  // S1: TAP reset, IDCODE, the gate and the bridge's DTMCS.
  protected task run_setup(dtp_env_pkg::dtp_j2a_target_t t);
    bit [15:0] last;
    bit [63:0] observed;
    bit [31:0] dtmcs;
    mark_step("S1", {
              "SETUP: TAP reset then Run-Test/Idle; IDCODE; SMC JTAG2AXI lifecycle gate open; ",
              "SMC_DTMCS"
              });
    tap_reset();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    confirm_state_tck(OCAH_JTAG_RUN_TEST_IDLE, "s1_rti", 1'b0, last);
    idle_tck(IdleAfterReset);
    load_ir(dtp_env_pkg::IDCODE_INSTR);
    dr_scan(64'h0, IdcodeWidth, observed);
    check_evidence(ChkJtagReady, "IDCODE", observed[31:0], smu_ptap_expected_idcode(
                   test_cfg.ptap_idcode_negative));
    check_pin(ChkGateOpen, "smc_jtag2axi_security_disable", "smc_jtag2axi_security_disable", 1'b0);
    read_j2a_dtmcs(t, dtmcs);
    check_evidence(ChkGateOpen, "SMC_DTMCS", 64'(dtmcs), 64'(dtp_env_pkg::DtpExpectedDtmcs),
                   "dmistat=0, no sticky DMI status");
  endtask

  // S2: a 32-bit CSR write and readback through the bridge.
  protected task run_scratch(dtp_env_pkg::dtp_j2a_target_t t, bit [31:0] pattern);
    bit [2:0] wr_err, rd_err;
    bit [63:0] rdata;
    mark_step("S2", "ACTION/RESPONSE: 32-bit write then readback of CPU_CTRL SCRATCH_15");
    write_j2a(t, SmuSmcScratch15Addr, 64'(pattern), Size4B, "s2_wr_poll", wr_err);
    check_evidence(ChkScratch, "SCRATCH_15 write sberror", 64'(wr_err), 64'd0, $sformatf(
                   "addr=0x%0h", SmuSmcScratch15Addr));
    read_j2a(t, SmuSmcScratch15Addr, Size4B, "s2_rd_poll", rd_err, rdata);
    check_evidence(ChkScratch, "SCRATCH_15 read sberror", 64'(rd_err), 64'd0);
    check_evidence(ChkScratch, "SCRATCH_15 readback", rdata[31:0], pattern, $sformatf(
                   "addr=0x%0h", SmuSmcScratch15Addr));
  endtask

  // S3: a 64-bit memory write and readback through the bridge.
  protected task run_spm(dtp_env_pkg::dtp_j2a_target_t t, bit [63:0] pattern);
    bit [2:0] wr_err, rd_err;
    bit [63:0] rdata;
    mark_step("S3", "ACTION/RESPONSE: 64-bit write then readback of the SPM base word");
    write_j2a(t, SmuSmcSpmBaseAddr, pattern, Size8B, "s3_wr_poll", wr_err);
    check_evidence(ChkSpm, "SPM write sberror", 64'(wr_err), 64'd0, $sformatf(
                   "addr=0x%0h", SmuSmcSpmBaseAddr));
    read_j2a(t, SmuSmcSpmBaseAddr, Size8B, "s3_rd_poll", rd_err, rdata);
    check_evidence(ChkSpm, "SPM read sberror", 64'(rd_err), 64'd0);
    check_evidence(ChkSpm, "SPM readback", rdata, pattern, $sformatf("addr=0x%0h", SmuSmcSpmBaseAddr
                   ));
  endtask

endclass : smu_smc_dtp_jtag2axi_smoke_test_seq
