// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC default-register read scenario sequence (smc_default_reg_rd_test),
// carrying the cocotb smc_default_reg_rd_test_seq semantics on the SEP_IN
// AXI4 ingress: read the post-reset content of every register in
// smc_default_reg_catalog and hold each one to its generated
// *_REG_DEFAULT, across four register blocks (scratch, chip_config,
// ndm_reset, reset_unit).
//
// This scenario WRITES NOTHING. That is what lets it claim "the register
// still holds its reset value" for a `sw=rw` entry: nothing in this
// simulation moved it. (The always-on smc_default_reg_ref_model does not
// depend on that -- it follows any write it observes -- but the scenario's
// own claim does.)
//
// Two properties stop this passing for the wrong reason:
//
//   * TWO OF THE EXPECTATIONS ARE NON-ZERO -- CHIP_CONFIG.VERSION_LO is
//     0x000100A0 and RESET_UNIT.SS_WARM_RESET_N is 0xFFFFFFFF. A read path
//     stuck at zero, an unmapped decode that returns zero, or a predictor
//     that lost its expected value cannot satisfy the catalogue.
//   * DECODE-ONLY ENTRIES CARRY NO CHECKER OF THEIR OWN. A catalogue entry
//     whose read value this bench cannot establish (CHIP_CONFIG.LC_STATE is
//     driven by the harness; NDM_RESET.NDMRESET_CLUSTER_COUNT by a
//     design-side count) has its OKAY response covered by CHK-CSR-RESP, and
//     its observed word logged as an OBSERVED-ONLY line. Comparing them
//     against the RDL default would be an invented claim; giving them a
//     CHK- token whose condition is a literal true would add a check that
//     cannot fail to the CHECKER_SUMMARY census.
//
// Every value compare is also made independently by the always-on
// smc_scoreboard's default_reg feature, whose reference model reaches the
// same expectation from the generated defaults plus the writes it observed;
// +SMC_DEFAULT_REG_SCOREBOARD_NEGATIVE corrupts that prediction so the run
// must FAIL. The cocotb twin is seq_lib/smc_default_reg_rd_test_seq.py.

class smc_default_reg_rd_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_default_reg_rd_test_seq)

  localparam string ChkRegDefault = "CHK-REG-DEFAULT";
  localparam string ChkNonvac = "CHK-NONVAC";

  function new(string name = "smc_default_reg_rd_test_seq");
    super.new(name);
  endfunction

  task body();
    smc_default_reg_entry_t entries[$];
    int unsigned            compared = 0;
    int unsigned            predicted = 0;
    int unsigned            decode_only = 0;
    bit [31:0]              observed;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkRegDefault, ChkNonvac, ChkSbMinAct});
    smc_default_reg_catalog(entries);
    if (entries.size() == 0)
      `uvm_fatal(get_type_name(), "smc_default_reg_catalog is empty: nothing to prove")
    // Every entry that carries a default is one read the default_reg feature
    // predicts, so the catalogue itself is the per-pass activity floor.
    foreach (entries[i]) if (entries[i].has_default) predicted++;
    check_min_activity(SmcFeatureDefaultReg, predicted);
    `uvm_info(get_type_name(),
              $sformatf(
                  {"SMC SV-UVM default register read (smc_default_reg_rd_test): SEP_IN post-reset ",
                   "content of %0d catalogued registers; scenario_seed=%0d"}, entries.size(),
                    scenario_seed), UVM_LOW)

    // The reset_unit and the warm-domain scratch registers answer only after
    // the warm reset domain is released.
    wait_fuse_sense_done();

    foreach (entries[i]) begin
      if (entries[i].has_default) begin
        csr_read_check(ChkRegDefault, entries[i].addr, entries[i].default_value, entries[i].name);
        compared++;
      end else begin
        // Decode-only. The OKAY claim on this access is carried by
        // CHK-CSR-RESP, which csr_read records and which can fail; the
        // observed word is REPORTED and never compared, because no authority
        // in this bench fixes its value. It is logged as an observation
        // rather than under a CHK- id: a token whose condition is a literal
        // true cannot fail, and putting one in the CHECKER_SUMMARY census
        // would inflate the count of checks that carry a claim.
        csr_read(entries[i].addr, observed, entries[i].name);
        `uvm_info(get_type_name(), $sformatf(
                  "OBSERVED-ONLY %s addr=0x%0h read 0x%08h (%s)",
                  entries[i].name,
                  entries[i].addr,
                  observed,
                  entries[i].why
                  ), UVM_LOW)
        decode_only++;
      end
    end

    `uvm_info(
        get_type_name(),
        $sformatf(
            "default register read: %0d compared against a generated default, %0d decode-only",
            compared, decode_only), UVM_LOW)

    // Reconcile the accesses the bench actually issued against the catalogue
    // this body walked: one read per entry, no writes. A body that stopped
    // early leaves this short and fails.
    check_evidence(ChkNonvac, "sep_in_csr_accesses", 64'(csr_accesses), 64'(entries.size()));
    finalize_evidence();
  endtask

endclass : smc_default_reg_rd_test_seq
