// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// smu_jtag_reset_override_test scenario sequence (IC_RESET TDR override of
// the external and SMC cold-reset slices), carrying the cocotb
// cocotb_wrapper/tests/smu_jtag_reset_override_test.py semantics on the
// 155-bit TDR of this wrapper (68 SMC + 8 SEP + 1 EXT ports, two bits each,
// plus reset_hold): S1 TAP reset to Run-Test/Idle; S2 the default readback is
// all ones over the whole register and both override exports idle
// (CHK-IC-DEFAULT); S3 the external port overridden with reset_control 0
// asserts the external override flag and drives its control low while the
// SMC cold override stays idle, and the written image reads back
// (CHK-IC-EXT-OVERRIDE, CHK-IC-DOMAIN, CHK-IC-READBACK); S4 the SMC cold port
// overridden likewise asserts the SMC cold override and drives it low, the
// external override is back to idle, and the whole SMC slice the SMC reset
// controller receives equals the slice the image encodes (CHK-IC-SMC-COLD-
// OVERRIDE, CHK-IC-DOMAIN); S5 the default image restores both exports and
// the SMC comes back out of the reset the override held it in (CHK-IC-
// CLEAR); TIMEOUT the bounded-wait inventory (CHK-TIMEOUT-PATHS) and the
// ordered step fence with a DUT change inside every step S1..S5
// (CHK-NONVAC). The external port sits nearest TDO, so a
// geometry short of the TDR lands its fields in the SEP slice and S3 fails:
// this is the scenario that catches a wrong slice width. Independently, the
// always-on scoreboard's ic_reset_tdr feature predicts the capture of every
// IC_RESET scan from the register shadow; +SMU_IC_RESET_SCOREBOARD_NEGATIVE
// corrupts that prediction so the run must FAIL.

class smu_jtag_reset_override_test_seq extends smu_base_test_seq;
  `uvm_object_utils(smu_jtag_reset_override_test_seq)

  localparam string ChkIcDefault = "CHK-IC-DEFAULT";
  localparam string ChkIcReadback = "CHK-IC-READBACK";
  localparam string ChkIcExt = "CHK-IC-EXT-OVERRIDE";
  localparam string ChkIcSmcCold = "CHK-IC-SMC-COLD-OVERRIDE";
  localparam string ChkIcDomain = "CHK-IC-DOMAIN";
  localparam string ChkIcClear = "CHK-IC-CLEAR";
  localparam string ChkTimeoutPaths = "CHK-TIMEOUT-PATHS";
  localparam string ChkNonvac = "CHK-NONVAC";

  // SMU clocks an export may take to follow a TDR update.
  localparam int unsigned ExportBound = 64;
  // IC_RESET scans a pass issues: default readback, EXT write, EXT readback,
  // SMC write, clear -- each one capture the ic_reset_tdr predictor compares.
  localparam int unsigned IcResetScansPerPass = 5;
  // Bounded-wait sites: s1_rti, s3_ext_ovrd, s4_smc_ovrd, s4_primary_held,
  // s5_ext_clear, s5_smc_clear, s5_primary_released.
  localparam int unsigned ExpectedTimeoutPaths = 7;
  // Step marks S1..S5, TIMEOUT, PASS: six ordered, non-decreasing deltas.
  localparam int unsigned ExpectedStepDeltas = 6;

  function new(string name = "smu_jtag_reset_override_test_seq");
    super.new(name);
  endfunction

  task body();
    seed_scenario_rng();
    attach_evidence('{ChkIcDefault, ChkIcReadback, ChkIcExt, ChkIcSmcCold, ChkIcDomain, ChkIcClear,
                    ChkTimeoutPaths, ChkNonvac, ChkSbMinAct});
    start_step_anchor();
    check_min_activity(SmuFeatureIcResetTdr, IcResetScansPerPass);
    `uvm_info(get_type_name(), $sformatf(
              {"SMU SV-UVM IC_RESET override (smu_jtag_reset_override_test): TDR %0d bits, ",
               "%0d SMC + %0d SEP + %0d EXT ports; scenario_seed=%0d"},
              SmuIcResetLen, SmuIcResetNumSmcPorts, SmuIcResetNumSepPorts, SmuIcResetNumExtPorts,
              scenario_seed), UVM_LOW)

    run_setup();
    run_default();
    run_ext_override();
    run_smc_cold_override();
    run_clear();
    run_timeout_inventory(ChkTimeoutPaths, ExpectedTimeoutPaths);

    mark_step("PASS", "scenario complete (PASS term recorded for the NONVAC fence)");
    stop_step_anchor();
    check_evidence(ChkNonvac, "ordered step-delta count", 64'(ordered_step_deltas()),
                   64'(ExpectedStepDeltas), $sformatf("steps=%0d", m_step_order.size()));
    check_step_anchors(ChkNonvac);
    finalize_evidence();
  endtask

  protected task run_setup();
    bit [15:0] last;
    mark_step("S1", "SETUP: baseline TAP reset then Run-Test/Idle; SMC settled");
    tap_reset();
    goto_state(OCAH_JTAG_RUN_TEST_IDLE);
    confirm_state_tck(OCAH_JTAG_RUN_TEST_IDLE, "s1_rti", 1'b0, last);
    wait_smu_cycles(8);
  endtask

  // S2: the reset image reads back whole, and no override is active.
  protected task run_default();
    smu_ic_reset_image_t captured;
    mark_step("S2", "DEFAULT: IC_RESET readback is all ones; EXT and SMC overrides idle");
    ic_reset_scan(SmuIcResetDefault, captured);
    check_evidence_wide(ChkIcDefault, "IC_RESET default readback", 256'(captured),
                        256'(SmuIcResetDefault), $sformatf("len=%0d", SmuIcResetLen));
    check_pin(ChkIcDefault, "ext ovrd idle", "jtag_ic_reset_ext_ovrd", 1'b0);
    check_pin(ChkIcDefault, "smc cold ovrd idle", "jtag_ic_reset_smc_ovrd", 1'b0);
  endtask

  // S3: override the external port, control 0.
  protected task run_ext_override();
    smu_ic_reset_image_t image = smu_ic_reset_override_image(SmuIcResetExtPort, 1'b0);
    smu_ic_reset_image_t readback;
    int cycles;
    mark_step("S3", "EXT: reset_enable=0/reset_control=0 on port 0 asserts the external override");
    ic_reset_write(image);
    wait_pin_level("jtag_ic_reset_ext_ovrd", 1'b1, ExportBound, "s3_ext_ovrd", cycles);
    check_pin(ChkIcExt, "ext ovrd asserted", "jtag_ic_reset_ext_ovrd", 1'b1,
              $sformatf("after %0d smu clocks", cycles));
    check_pin(ChkIcExt, "ext ctrl_n driven low", "jtag_ic_reset_ext_ctrl_n", 1'b0);
    check_pin(ChkIcDomain, "smc cold ovrd idle while ext asserted", "jtag_ic_reset_smc_ovrd", 1'b0);
    ic_reset_scan(image, readback);
    check_evidence_wide(ChkIcReadback, "IC_RESET EXT pattern readback", 256'(readback),
                        256'(image));
  endtask

  // S4: override the SMC cold-reset port, control 0: the SMC is held in
  // cold reset by JTAG.
  protected task run_smc_cold_override();
    smu_ic_reset_image_t image =
        smu_ic_reset_override_image(smu_ic_reset_smc_port(SmuIcResetSmcCold), 1'b0);
    int cycles;
    mark_step("S4", "SMC: reset_enable=0/reset_control=0 on the SMC cold port; EXT released");
    ic_reset_write(image);
    wait_pin_level("jtag_ic_reset_smc_ovrd", 1'b1, ExportBound, "s4_smc_ovrd", cycles);
    check_pin(ChkIcSmcCold, "smc cold ovrd asserted", "jtag_ic_reset_smc_ovrd", 1'b1,
              $sformatf("after %0d smu clocks", cycles));
    check_pin(ChkIcSmcCold, "smc cold ctrl_n driven low", "jtag_ic_reset_smc_ctrl_n", 1'b0);
    check_pin(ChkIcDomain, "ext ovrd released while smc asserted", "jtag_ic_reset_ext_ovrd", 1'b0);
    check_evidence_wide(ChkIcSmcCold, "SMC slice ovrd vector", 256'(tb_vif.smc_reset_ctrl_ovrd),
                        256'(smu_ic_reset_smc_ovrd_of(image)));
    check_evidence_wide(ChkIcSmcCold, "SMC slice val vector", 256'(tb_vif.smc_reset_ctrl_val),
                        256'(smu_ic_reset_smc_val_of(image)));
    wait_pin_level("rst_primary_smc_clk_n", 1'b0, ExportBound, "s4_primary_held", cycles);
    check_pin(ChkIcSmcCold, "SMC primary reset held by the cold override", "rst_primary_smc_clk_n",
              1'b0, $sformatf("after %0d smu clocks", cycles));
  endtask

  // S5: the reset image releases both overrides; the SMC comes back out of
  // the cold reset the override held.
  protected task run_clear();
    int ext_cycles, smc_cycles, primary_cycles;
    mark_step("S5", "CLEAR: default image restores ovrd=0 on both slices; SMC resets release");
    ic_reset_write(SmuIcResetDefault);
    wait_pin_level("jtag_ic_reset_ext_ovrd", 1'b0, ExportBound, "s5_ext_clear", ext_cycles);
    wait_pin_level("jtag_ic_reset_smc_ovrd", 1'b0, ExportBound, "s5_smc_clear", smc_cycles);
    check_pin(ChkIcClear, "ext ovrd cleared", "jtag_ic_reset_ext_ovrd", 1'b0);
    check_pin(ChkIcClear, "smc cold ovrd cleared", "jtag_ic_reset_smc_ovrd", 1'b0);
    wait_pin_level("rst_primary_smc_clk_n", 1'b1, test_cfg.reset_release_timeout_cycles,
                   "s5_primary_released", primary_cycles);
    check_pin(ChkIcClear, "SMC primary reset released after the override", "rst_primary_smc_clk_n",
              1'b1, $sformatf("after %0d smu clocks", primary_cycles));
  endtask

endclass : smu_jtag_reset_override_test_seq
