// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_idcode_test scenario sequence: one IDCODE read through the
// reset-loaded instruction (a DR scan with no IR load after TAP reset), one
// through the instruction a power-on reset loads (a seeded instruction other
// than IDCODE loaded, then power-on reset with TRST_N high and TCK idle, then
// a DR scan with no IR load: CHK-IDCODE-RECOVERY), then looped IDCODE reads
// under seeded random TAP preconditioning. Every read
// must return the exact default device-identification value
// (CHK-IDCODE-RAW) regardless of the TAP context established before it —
// TAP reset, TLR walk plus random TMS stress, a safe IR load, or a BYPASS
// scan — and the reads must be stable
// (CHK-IDCODE-STABLE) with the IEEE 1149.1 fields decoding to the expected
// marker/version/part/manufacturer values. Read count per pass comes from
// test_cfg.idcode_reads_per_loop (+DTP_IDCODE_READS_PER_LOOP, default 4,
// minimum 1).

class dtp_jtag_idcode_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_jtag_idcode_test_seq)

  // IDCODE reads per pass, taken from the test cfg at the top of body().
  protected int unsigned read_loops = 4;

  function new(string name = "dtp_jtag_idcode_test_seq");
    super.new(name);
  endfunction

  // Randomize the TAP context before reloading and reading IDCODE. Loop 0
  // always walks through TLR so the required TAP reset/state evidence
  // executes on every seed; later loops stay randomized.
  protected task random_precondition(int unsigned loop_idx);
    int unsigned action = (loop_idx == 0) ? 1 : $urandom_range(3);
    case (action)
      0: begin
        `uvm_info(get_type_name(), $sformatf("IDCODE loop %0d precondition: tap_reset", loop_idx),
                  UVM_LOW)
        reset_to_tlr();
      end
      1: begin
        int unsigned walk_cycles = $urandom_range(10, 1);
        `uvm_info(get_type_name(), $sformatf(
                  "IDCODE loop %0d precondition: tlr_walk cycles=%0d", loop_idx, walk_cycles),
                  UVM_LOW)
        reset_to_tlr();
        random_tms_walk(walk_cycles);
        goto_state(OCAH_JTAG_RUN_TEST_IDLE);
      end
      2: begin
        bit [IrWidth-1:0] safe_irs[3] =
                    '{BYPASS_ALT_INSTR, BYPASS_INSTR, SAMPLE_PRELOAD_INSTR};
        bit [IrWidth-1:0] instr = safe_irs[$urandom_range(2)];
        `uvm_info(get_type_name(), $sformatf(
                  "IDCODE loop %0d precondition: safe_ir 0x%02h", loop_idx, instr), UVM_LOW)
        load_ir(instr);
      end
      default: begin
        bit [63:0] pattern = random_pattern(32);
        `uvm_info(get_type_name(), $sformatf(
                  "IDCODE loop %0d precondition: bypass_scan pattern=0x%08h", loop_idx, pattern),
                  UVM_LOW)
        check_bypass_delay(BYPASS_INSTR, pattern, 32);
      end
    endcase
    // CHK-TAP-STATE: the DUT one-hot observable matches the sequence's
    // tracked reference state after every precondition.
    family_check("CHK-TAP-STATE", "TAP state after precondition", 64'(tb_vif.tap_state),
                 64'(16'h1 << int'(current_state())), $sformatf(
                 "loop=%0d action=%0d", loop_idx, action));
  endtask

  task body();
    localparam bit [31:0] ExpectedIdcode = DtpDefaultIdcode;
    bit [IrWidth-1:0] por_preload;
    int unsigned por_cycles;
    bit [15:0] state_under_por;
    bit trst_n_under_por;
    bit [63:0] observed;
    bit [31:0] reads[$];
    bit        seen_values[bit [31:0]];
    string     values_s = "";
    string     por_ctx;

    seed_scenario_rng();
    read_loops = test_cfg.idcode_reads_per_loop;
    // No scan-count cross-check: the random-TMS-walk preconditions cross
    // Shift-x, publishing scan-builder items the sequence cannot count
    // (cocotb use_monitor=False parity).
    attach_family_checker({
                          "CHK-IDCODE-RAW",
                          "CHK-IDCODE-STABLE",
                          "CHK-IDCODE-MARKER",
                          "CHK-IDCODE-VERSION",
                          "CHK-IDCODE-PART-NUMBER",
                          "CHK-IDCODE-MANUFACTURER",
                          "CHK-IDCODE-RECOVERY",
                          "CHK-TAP-RESET-TLR",
                          "CHK-TAP-STATE",
                          "CHK-NONVAC"
                          }, 1'b0);

    // Test-Logic-Reset loads IDCODE into the instruction register, so a DR
    // scan with no IR load reads the device identification through the
    // reset-selected path.
    reset_to_tlr();
    shift_dr(64'h0, 32, observed);
    reads.push_back(observed[31:0]);
    seen_values[observed[31:0]] = 1'b1;
    values_s = $sformatf("0x%08h", observed[31:0]);
    family_check("CHK-IDCODE-RAW", "IDCODE read without IR load", observed[31:0], ExpectedIdcode,
                 "precondition=tap_reset no_ir_load");

    // Power-on reset alone reloads IDCODE over the instruction loaded
    // before it: TRST_N stays high and TCK idles across the pulse.
    por_preload = random_non_idcode_preload();
    por_cycles  = $urandom_range(8, 2);
    por_ctx     = $sformatf("preload=0x%02h por_cycles=%0d", por_preload, por_cycles);
    load_ir(por_preload);
    pulse_por(por_cycles, state_under_por, trst_n_under_por);
    check_tap_state("CHK-TAP-POR-TLR", state_under_por, TEST_LOGIC_RESET, {"during POR ", por_ctx});
    family_check("CHK-TAP-POR-TLR", "TRST_N deasserted during POR", 64'(trst_n_under_por), 64'd1,
                 por_ctx);
    tms_expect(1'b0, RUN_TEST_IDLE);
    shift_dr(64'h0, 32, observed);
    reads.push_back(observed[31:0]);
    seen_values[observed[31:0]] = 1'b1;
    values_s = {values_s, $sformatf(",0x%08h", observed[31:0])};
    family_check("CHK-IDCODE-RECOVERY", "IDCODE DR scan after POR, no IR load, TRST high",
                 observed[31:0], ExpectedIdcode, por_ctx);

    for (int unsigned loop_idx = 0; loop_idx < read_loops; loop_idx++) begin
      random_precondition(loop_idx);
      read_idcode(observed);
      reads.push_back(observed[31:0]);
      seen_values[observed[31:0]] = 1'b1;
      values_s = {values_s, $sformatf(",0x%08h", observed[31:0])};
      family_check("CHK-IDCODE-RAW", "IDCODE read", observed[31:0], ExpectedIdcode, $sformatf(
                   "loop=%0d precondition=randomized", loop_idx));
    end

    family_check("CHK-IDCODE-STABLE", "distinct IDCODE reads", 64'(seen_values.num()), 64'h1,
                 $sformatf("reads=%0d values=%s", reads.size(), values_s));

    // IEEE 1149.1 field decode of the first read: marker (bit 0),
    // manufacturer [11:1], part number [27:12], version [31:28].
    family_check("CHK-IDCODE-MARKER", "IDCODE marker bit", 64'(reads[0][0]), 64'd1, $sformatf(
                 "raw=0x%08h bit=0", reads[0]));
    family_check("CHK-IDCODE-MANUFACTURER", "IDCODE manufacturer field", 64'(reads[0][11:1]),
                 64'(ExpectedIdcode[11:1]), $sformatf("raw=0x%08h", reads[0]));
    family_check("CHK-IDCODE-PART-NUMBER", "IDCODE part-number field", 64'(reads[0][27:12]),
                 64'(ExpectedIdcode[27:12]), $sformatf("raw=0x%08h", reads[0]));
    family_check("CHK-IDCODE-VERSION", "IDCODE version field", 64'(reads[0][31:28]),
                 64'(ExpectedIdcode[31:28]), $sformatf("raw=0x%08h", reads[0]));

    void'(m_family.expect_true(
        "CHK-NONVAC",
        (reads.size() >= 2) && (reads[0] != 32'h0) && (reads[0] != 32'hFFFF_FFFF),
        $sformatf(
            "reads=%0d exact_expected=0x%08h observed=0x%08h",
            reads.size(),
            ExpectedIdcode,
            reads[0])
    ));
    finalize_family_checker();
  endtask

endclass : dtp_jtag_idcode_test_seq
