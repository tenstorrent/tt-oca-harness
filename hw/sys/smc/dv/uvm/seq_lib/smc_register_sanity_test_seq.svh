// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC register-sanity scenario sequence (smc_register_sanity_test), carrying the
// cocotb smc_register_sanity_test_seq semantics on the SEP_IN AXI4 ingress:
//   * wait for the warm-reset domain release (fuse sense -> delayed fuse
//     reset -> rst_warm), since SCRATCH_COLD_WARM sits behind it;
//   * read the idle value of SCRATCH_COLD[0], SCRATCH_COLD[1], and
//     SCRATCH_COLD_WARM[0] (zero after cold reset, zero again after the
//     restore of the previous pass);
//   * write the three directed patterns of the cocotb scenario and read
//     each back; then random_count seeded random patterns per register IN
//     ADDITION (+SMC_RANDOM_COUNT, default 5; each pass exercises different
//     data), each read back;
//   * restore zero and read back, so every pass leaves the registers at
//     their reset value;
//   * named evidence through the base-sequence ocah_checker: idle values,
//     directed and random readbacks, restores, every OKAY response, and the
//     non-vacuity count of real SEP_IN CSR accesses: per register one idle
//     read, a directed write and readback, random_count random writes and
//     readbacks, and a restore write and readback.
// The always-on smc_scoreboard independently predicts every scratch read
// from the writes the passive monitor observed; +SMC_CSR_SCOREBOARD_NEGATIVE
// corrupts that prediction so the run must FAIL (see smc_scoreboard).

class smc_register_sanity_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_register_sanity_test_seq)

  localparam string ChkCsrIdle = "CHK-CSR-IDLE-VALUE";
  localparam string ChkCsrReadback = "CHK-CSR-READBACK";
  localparam string ChkCsrRandom = "CHK-CSR-RANDOM-READBACK";
  localparam string ChkCsrRestore = "CHK-CSR-RESTORE";
  localparam string ChkNonvac = "CHK-NONVAC";

  typedef struct {
    string     name;
    bit [63:0] addr;
    bit [31:0] pattern;
  } scratch_case_t;

  // Accesses per register and pass beyond the random patterns: one idle
  // read, a directed write and readback, a restore write and readback; each
  // random pattern adds a write and a readback.
  localparam int unsigned FixedAccessesPerRegister = 5;
  localparam int unsigned AccessesPerRandomPattern = 2;

  function new(string name = "smc_register_sanity_test_seq");
    super.new(name);
  endfunction

  // The cocotb scenario's registers and directed patterns.
  function void scratch_cases(ref scratch_case_t cases[$]);
    cases.delete();
    cases.push_back('{"SCRATCH_COLD_0", smc_scratch_cold_addr(0), 32'hA5A5_0001});
    cases.push_back('{"SCRATCH_COLD_1", smc_scratch_cold_addr(1), 32'h5A5A_0002});
    cases.push_back('{"SCRATCH_COLD_WARM_0", smc_scratch_cold_warm_addr(0), 32'hC0DE_0003});
  endfunction

  task body();
    scratch_case_t cases[$];
    bit [31:0]     rand_pattern;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkCsrIdle, ChkCsrReadback, ChkCsrRandom,
                    ChkCsrRestore, ChkNonvac});
    scratch_cases(cases);
    `uvm_info(
        get_type_name(),
        $sformatf(
            {"SMC SV-UVM register sanity (smc_register_sanity_test): SEP_IN scratch CSR idle/write/",
             "readback/restore on %0d registers; scenario_seed=%0d random_count=%0d"},
              cases.size(), scenario_seed, random_count), UVM_LOW)

    wait_fuse_sense_done();

    foreach (cases[i]) csr_read_check(ChkCsrIdle, cases[i].addr, 32'h0, {cases[i].name, ".idle"});

    foreach (cases[i]) begin
      csr_write(cases[i].addr, cases[i].pattern, {cases[i].name, ".directed"});
      csr_read_check(ChkCsrReadback, cases[i].addr, cases[i].pattern, {cases[i].name, ".directed"});
    end

    foreach (cases[i]) begin
      for (int unsigned r = 0; r < random_count; r++) begin
        string label = $sformatf("%s.random%0d", cases[i].name, r);
        rand_pattern = 32'(random_pattern(32));
        csr_write(cases[i].addr, rand_pattern, label);
        csr_read_check(ChkCsrRandom, cases[i].addr, rand_pattern, label);
      end
    end

    foreach (cases[i]) begin
      csr_write(cases[i].addr, 32'h0, {cases[i].name, ".restore"});
      csr_read_check(ChkCsrRestore, cases[i].addr, 32'h0, {cases[i].name, ".restore"});
    end

    check_evidence(
        ChkNonvac, "sep_in_csr_accesses", 64'(csr_accesses),
        64'(cases.size() * (FixedAccessesPerRegister + AccessesPerRandomPattern * random_count)));
    finalize_evidence();
  endtask

endclass : smc_register_sanity_test_seq
