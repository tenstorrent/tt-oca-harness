// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP no-CPU AXI smoke scenario sequence, carrying the cocotb
// sep_axi_smoke_seq semantics on the CPU-LSU AXI4 splice:
//   * wait for fuse sense done, since the local fabric answers only after
//     it;
//   * read the reset value of sep_cpu_ctrl.SEP_LOCAL_BASE_ADDR (decode
//     sanity: a non-zero reset value proves the block decoded rather than
//     returning zeros from an unmapped address);
//   * write the four directed patterns of the cocotb scenario to
//     SEP_SW_DEBUG, SEP_NMI_VEC, PKA_CTRL, and SEP_REGION_SIZE and read each
//     back through its implemented-field mask; then random_count seeded
//     random patterns per register IN ADDITION (+SEP_RANDOM_COUNT, default
//     5; each pass exercises different data), each read back;
//   * restore every register to its reset value and read back, so each pass
//     leaves the block as reset left it;
//   * named evidence through the base-sequence ocah_checker: fabric
//     release, reset value, directed and random readbacks, restores, every
//     OKAY response, and non-vacuity: the cpu_ctrl_csr scoreboard compares
//     this pass added must equal the predicted reads it issued (one reset
//     read, then per register a directed readback, random_count random
//     readbacks, and a restore readback).
// The always-on sep_scoreboard independently predicts every predicted-CSR
// read from the writes the passive monitor observed;
// +SEP_CSR_SCOREBOARD_NEGATIVE corrupts that prediction so the run must
// FAIL (see sep_scoreboard). The cocotb twin is seq_lib/sep_axi_smoke_seq.py.

class sep_axi_smoke_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_axi_smoke_test_seq)

  localparam string ChkCsrReset = "CHK-CSR-RESET-VALUE";
  localparam string ChkCsrReadback = "CHK-CSR-READBACK";
  localparam string ChkCsrRandom = "CHK-CSR-RANDOM-READBACK";
  localparam string ChkCsrRestore = "CHK-CSR-RESTORE";
  localparam string ChkNonvac = "CHK-NONVAC";

  // The register the reset read decodes.
  localparam string ResetReadRegister = "SEP_LOCAL_BASE_ADDR";

  typedef struct {
    sep_csr_desc_t desc;
    bit [31:0]     pattern;
  } write_case_t;

  // Predicted reads per register and pass beyond the random patterns: a
  // directed readback and a restore readback; each random pattern adds one
  // readback. The reset read is one more.
  localparam int unsigned FixedReadsPerRegister = 2;
  localparam int unsigned ReadsPerRandomPattern = 1;
  localparam int unsigned ResetReads = 1;

  function new(string name = "sep_axi_smoke_test_seq");
    super.new(name);
  endfunction

  // The cocotb scenario's write/readback registers and directed patterns,
  // each with a distinct pattern so a write to one register cannot satisfy
  // the readback of another.
  function void write_cases(ref write_case_t cases[$]);
    string     names[$] = {"SEP_SW_DEBUG", "SEP_NMI_VEC", "PKA_CTRL", "SEP_REGION_SIZE"};
    bit [31:0] patterns[$] = {32'hDEAD_BEEF, 32'h0BAD_C0DE, 32'h0000_0007, 32'h0200_0000};
    cases.delete();
    foreach (names[i]) begin
      write_case_t c;
      if (!sep_cpu_ctrl_csr_by_name(names[i], c.desc))
        `uvm_fatal(get_type_name(), {"register not in the predicted set: ", names[i]})
      c.pattern = patterns[i];
      cases.push_back(c);
    end
  endfunction

  task body();
    write_case_t   cases[$];
    sep_csr_desc_t reset_reg;
    bit [31:0]     rand_pattern;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkCsrReset, ChkCsrReadback, ChkCsrRandom,
                    ChkCsrRestore, ChkNonvac});
    mark_scoreboard_feature(SepFeatureCpuCtrlCsr);
    write_cases(cases);
    if (!sep_cpu_ctrl_csr_by_name(ResetReadRegister, reset_reg))
      `uvm_fatal(get_type_name(), {"register not in the predicted set: ", ResetReadRegister})
    `uvm_info(get_type_name(),
              $sformatf(
                  {"SEP SV-UVM AXI smoke: CPU-LSU reset read of %s then write/readback/restore ",
                   "on %0d registers; scenario_seed=%0d random_count=%0d"}, reset_reg.name,
                    cases.size(), scenario_seed, random_count), UVM_LOW)

    wait_fuse_sense_done();

    log_step("1", "reset-value decode sanity");
    csr_read_check(ChkCsrReset, reset_reg.addr, reset_reg.reset_value, {reset_reg.name, ".reset"});

    log_step("2", "directed write/readback");
    foreach (cases[i]) begin
      csr_write(cases[i].desc.addr, cases[i].pattern, {cases[i].desc.name, ".directed"});
      csr_read_check(ChkCsrReadback, cases[i].desc.addr, cases[i].pattern & cases[i].desc.mask, {
                     cases[i].desc.name, ".directed"});
    end

    log_step("3", "seeded random write/readback");
    foreach (cases[i]) begin
      for (int unsigned r = 0; r < random_count; r++) begin
        string label = $sformatf("%s.random%0d", cases[i].desc.name, r);
        rand_pattern = 32'(random_pattern(32));
        csr_write(cases[i].desc.addr, rand_pattern, label);
        csr_read_check(ChkCsrRandom, cases[i].desc.addr, rand_pattern & cases[i].desc.mask, label);
      end
    end

    log_step("4", "restore reset values");
    foreach (cases[i]) begin
      csr_write(cases[i].desc.addr, cases[i].desc.reset_value, {cases[i].desc.name, ".restore"});
      csr_read_check(ChkCsrRestore, cases[i].desc.addr, cases[i].desc.reset_value, {
                     cases[i].desc.name, ".restore"});
    end

    check_scoreboard_compares(
        ChkNonvac, SepFeatureCpuCtrlCsr,
        ResetReads + cases.size() * (FixedReadsPerRegister + ReadsPerRandomPattern * random_count));
    finalize_evidence();
  endtask

endclass : sep_axi_smoke_test_seq
