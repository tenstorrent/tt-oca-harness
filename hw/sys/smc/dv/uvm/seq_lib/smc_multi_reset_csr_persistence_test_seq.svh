// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC CSR behaviour across the public cool-reset control
// (smc_multi_reset_csr_persistence_test), carrying the cocotb
// smc_multi_reset_csr_persistence_test_seq semantics on the SEP_IN AXI4
// ingress. Unlike the cocotb twin this needs no reset agent: smc_tb_if
// already carries the rst_cool_n pin and the reset-unit observables, so the
// scenario drives and polls them directly.
//
// WHAT THIS PROVES
//   1. A pulse on the public rst_cool_ni pin survives smc_reset_ctrl's
//      de-glitch (RESET_DEGLITCH_WIDTH samples on clk_ref_i) and really
//      reaches the reset domain: rst_primary_smc_clk_n AND
//      rst_warm_smc_clk_n both drop, then both release. Polled, not waited
//      out with a fixed delay -- a fixed hold could be shorter than the
//      de-glitch window and would prove nothing about whether anything
//      downstream reset at all.
//   2. Both scratch windows lose their contents to it. This is the reset
//      TOPOLOGY the specification states, not a reading of the register
//      names: clk_rst.adoc lists the cool reset as a Primary Reset activation
//      source ("Primary Reset with isolation"; Primary Reset Activation
//      Sources), Primary Reset covers the "SMC control and configuration
//      registers" (Primary Reset), and the warm reset is "cascaded from" the
//      primary reset (Warm Reset Activation Sources). Both scratch windows are
//      such registers (misc_wrap.rdl:20-21), so a cool reset clears BOTH --
//      the "COLD" in SCRATCH_COLD names a reset it is reset BY, not a reset
//      it survives.
//   3. The CSR path recovers with real content, not merely with OKAY
//      responses: a static register whose generated default is NON-ZERO
//      (CHIP_CONFIG.VERSION_LO = 0x000100A0) reads that default again, and a
//      fresh write/readback lands.
//
// WHAT THIS DOES NOT PROVE, AND WHY. It does not show either scratch window
// surviving a reset the other one takes, because no stimulus here drops
// rst_warm_ni WITHOUT dropping rst_primary_ni -- the cool-reset pin drops
// both. Separating the two domains needs a warm-only source (the
// SS_WARM_RESET_N control or the SEP WDT pin) and is deliberately left out
// rather than asserted from the register naming.
//
// The patterns written before the reset are drawn per pass and REQUIRED TO BE
// NON-ZERO: "the register reads 0 after the reset" says nothing if it held 0
// going in.
//
// The always-on smc_scoreboard's scratch_csr feature independently predicts
// every scratch read, and its reference model re-baselines on the same cool
// reset through smc_csr_reset_epoch, so a model that ignored the cool reset
// would fail here. +SMC_CSR_SCOREBOARD_NEGATIVE corrupts that prediction so
// the run must FAIL.

class smc_multi_reset_csr_persistence_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_multi_reset_csr_persistence_test_seq)

  localparam string ChkPreReset = "CHK-CSR-PRE-COOL-READBACK";
  localparam string ChkCoolAsserted = "CHK-COOL-RESET-ASSERTED";
  localparam string ChkCoolReleased = "CHK-COOL-RESET-RELEASED";
  localparam string ChkCoolClears = "CHK-COOL-CLEARS-SCRATCH";
  localparam string ChkPathRecovered = "CHK-CSR-PATH-RECOVERED";
  localparam string ChkRwRecovered = "CHK-CSR-RW-RECOVERED";
  localparam string ChkNonvac = "CHK-NONVAC";

  // Bound on each cool-reset transition poll, in smc clocks. The de-glitch is
  // RESET_DEGLITCH_WIDTH samples of clk_ref_i (~32), which at the randomized
  // ref/smc periods is under a hundred smc clocks; this leaves ample margin
  // and still fails loudly instead of hanging.
  localparam int unsigned CoolResetPollCycles = 5_000;
  // Accesses this body issues per pass: four writes and seven reads.
  localparam int unsigned ExpectedAccesses = 11;
  // Six of those eleven are scratch reads -- two before the pulse, two after
  // it, and two around the post-reset write/restore -- and each one is
  // predicted by the scratch_csr reference model.
  localparam int unsigned PredictedScratchReadsPerPass = 6;

  function new(string name = "smc_multi_reset_csr_persistence_test_seq");
    super.new(name);
  endfunction

  task body();
    bit [63:0] cold_addr = smc_scratch_cold_addr(1);
    bit [63:0] warm_addr = smc_scratch_cold_warm_addr(1);
    bit [63:0] version_addr =
        64'(smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR);
    bit [31:0] pattern_cold, pattern_warm, pattern_rw;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkPreReset, ChkCoolAsserted, ChkCoolReleased,
                    ChkCoolClears, ChkPathRecovered, ChkRwRecovered, ChkNonvac, ChkSbMinAct});

    check_min_activity(SmcFeatureScratchCsr, PredictedScratchReadsPerPass);
    pattern_cold = 32'(random_pattern(32)) | 32'h1;
    pattern_warm = 32'(random_pattern(32)) | 32'h2;
    pattern_rw   = 32'(random_pattern(32)) | 32'h4;
    // "Cleared to its reset value" is only a claim if the register did not
    // already hold that value before the reset.
    if (pattern_cold == 32'h0 || pattern_warm == 32'h0)
      `uvm_fatal(get_type_name(), "pre-reset patterns must be non-zero to discriminate a clear")

    `uvm_info(
        get_type_name(),
        $sformatf(
            {"SMC SV-UVM cool-reset CSR behaviour (smc_multi_reset_csr_persistence_test): ",
             "SCRATCH_COLD[1]=0x%08h SCRATCH_COLD_WARM[1]=0x%08h then one rst_cool_ni pulse; ",
             "scenario_seed=%0d"}, pattern_cold, pattern_warm, scenario_seed), UVM_LOW)

    wait_fuse_sense_done();

    // --- before the reset: both windows hold a non-zero pattern -----------
    csr_write(cold_addr, pattern_cold, "SCRATCH_COLD_1.pre_cool");
    csr_read_check(ChkPreReset, cold_addr, pattern_cold, "SCRATCH_COLD_1.pre_cool");
    csr_write(warm_addr, pattern_warm, "SCRATCH_COLD_WARM_1.pre_cool");
    csr_read_check(ChkPreReset, warm_addr, pattern_warm, "SCRATCH_COLD_WARM_1.pre_cool");

    // --- the cool-reset pulse ---------------------------------------------
    pulse_cool_reset();

    // The warm domain comes back through the fuse-sense ladder again.
    wait_fuse_sense_done();

    // --- after the reset --------------------------------------------------
    csr_read_check(ChkCoolClears, cold_addr, 32'(SCRATCH_SCRATCH_REG_DEFAULT),
                   "SCRATCH_COLD_1.post_cool");
    csr_read_check(ChkCoolClears, warm_addr, 32'(SCRATCH_SCRATCH_REG_DEFAULT),
                   "SCRATCH_COLD_WARM_1.post_cool");
    // Real content, not just an OKAY: this default is non-zero, so a read
    // path that came back dead or stuck at zero fails here.
    csr_read_check(ChkPathRecovered, version_addr, 32'(CHIP_CONFIG_VERSION_LO_REG_DEFAULT),
                   "CHIP_CONFIG_VERSION_LO.post_cool");
    // And the write path works again, then restore.
    csr_write(cold_addr, pattern_rw, "SCRATCH_COLD_1.post_cool_write");
    csr_read_check(ChkRwRecovered, cold_addr, pattern_rw, "SCRATCH_COLD_1.post_cool_write");
    csr_write(cold_addr, 32'(SCRATCH_SCRATCH_REG_DEFAULT), "SCRATCH_COLD_1.restore");
    csr_read_check(ChkRwRecovered, cold_addr, 32'(SCRATCH_SCRATCH_REG_DEFAULT),
                   "SCRATCH_COLD_1.restore");

    check_evidence(ChkNonvac, "sep_in_csr_accesses", 64'(csr_accesses), 64'(ExpectedAccesses));
    finalize_evidence();
  endtask

  // Drive one pulse on the public cool-reset pin, holding it low until the
  // reset is observed downstream rather than for a fixed time, and releasing
  // it only after both observables have dropped.
  protected task pulse_cool_reset();
    bit primary_down, warm_down, primary_up, warm_up;

    tb_vif.rst_cool_n <= 1'b0;
    wait_observable("rst_primary_smc_clk_n", 1'b0, primary_down);
    wait_observable("rst_warm_smc_clk_n", 1'b0, warm_down);
    void'(m_check.expect_true(
        ChkCoolAsserted,
        primary_down && warm_down,
        $sformatf(
            {
              "rst_cool_ni=0 de-glitched into the domain: ",
              "rst_primary_smc_clk_n=%0b rst_warm_smc_clk_n=%0b"
            },
            tb_vif.rst_primary_smc_clk_n,
            tb_vif.rst_warm_smc_clk_n)
    ));

    tb_vif.rst_cool_n <= 1'b1;
    wait_observable("rst_primary_smc_clk_n", 1'b1, primary_up);
    wait_observable("rst_warm_smc_clk_n", 1'b1, warm_up);
    void'(m_check.expect_true(
        ChkCoolReleased,
        primary_up && warm_up,
        $sformatf(
            {
              "rst_cool_ni=1 released the domain: ",
              "rst_primary_smc_clk_n=%0b rst_warm_smc_clk_n=%0b"
            },
            tb_vif.rst_primary_smc_clk_n,
            tb_vif.rst_warm_smc_clk_n)
    ));
  endtask

  // Bounded poll of one reset observable to a level; expiry errors and
  // reports 0 rather than hanging the run. The level itself is compared with
  // !==, so an X or Z matches NEITHER direction and the poll expires instead
  // of passing. A predicate of the "is it 1?" shape would make X the passing
  // case on the asserted leg, where the loop exits as soon as that predicate
  // reads false.
  protected task wait_observable(string which, bit want, output bit reached);
    int unsigned cycles = 0;
    while (reset_observable(
        which
    ) !== want) begin
      if (cycles >= CoolResetPollCycles) begin
        `uvm_error(get_type_name(), $sformatf("%s never reached %0b within %0d smc clocks", which,
                                              want, cycles))
        reached = 1'b0;
        return;
      end
      wait_smc_cycles(1);
      cycles++;
    end
    `uvm_info(get_type_name(), $sformatf("%s reached %0b after %0d smc clocks", which, want,
                                         cycles), UVM_MEDIUM)
    reached = 1'b1;
  endtask

  protected function logic reset_observable(string which);
    case (which)
      "rst_primary_smc_clk_n": return tb_vif.rst_primary_smc_clk_n;
      "rst_warm_smc_clk_n":    return tb_vif.rst_warm_smc_clk_n;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown reset observable %s", which))
        return 1'bx;
      end
    endcase
  endfunction

endclass : smc_multi_reset_csr_persistence_test_seq
