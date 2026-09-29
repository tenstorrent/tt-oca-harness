// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Exercises single-byte, non-contiguous, and null write strobes on selected
// side-effect-free words of the SMC 64-bit register-block interfaces.

class smc_regblock_sparse_strobe_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_regblock_sparse_strobe_test_seq)

  localparam string ChkBaseline = "CHK-REGBLOCK-WIDE-BASELINE";
  localparam string ChkFullRw = "CHK-REGBLOCK-WIDE-FULL-RW";
  localparam string ChkSingleByte = "CHK-REGBLOCK-WIDE-SINGLE-BYTE";
  localparam string ChkSparse = "CHK-REGBLOCK-WIDE-SPARSE";
  localparam string ChkNull = "CHK-REGBLOCK-WIDE-NULL-STROBE";
  localparam string ChkRestore = "CHK-REGBLOCK-WIDE-RESTORE";
  localparam string ChkRestoreNonvac = "CHK-REGBLOCK-WIDE-RESTORE-NONVAC";
  localparam string ChkNoZeroerStart = "CHK-REGBLOCK-WIDE-NO-ZEROER-START";
  localparam string ChkLaneCoverage = "CHK-REGBLOCK-WIDE-LANE-COVERAGE";
  localparam string ChkScoreboard = "CHK-REGBLOCK-WIDE-SCOREBOARD";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned ComparisonTimeoutCycles = 4096;
  // Five safe-state reads precede the catalogued register operations.
  localparam int unsigned SafeStateReads = 5;
  // The final Zeroer status read corroborates the SYS_OUT activity check.
  localparam int unsigned FinalStateReads = 1;
  // Baseline, full, single-byte, seeded sparse, null-strobe and restore each
  // end in a predicted read; fixed sparse strobes add one read apiece.
  localparam int unsigned BaseReadsPerRegister = 6;
  // Those six reads pair with five writes; fixed sparse strobes add one pair.
  localparam int unsigned BaseAccessesPerRegister = 11;
  // The scenario and its lane-coverage claim require all seven selected words.
  localparam int unsigned CatalogEntries = 7;

  function new(string name = "smc_regblock_sparse_strobe_test_seq");
    super.new(name);
  endfunction

  protected function bit strb_contiguous(bit [7:0] strb);
    bit seen_one;
    bit seen_gap;
    for (int unsigned lane = 0; lane < SmcMemBytes; lane++) begin
      if (strb[lane]) begin
        if (seen_gap) return 1'b0;
        seen_one = 1'b1;
      end else if (seen_one) begin
        seen_gap = 1'b1;
      end
    end
    return seen_one;
  endfunction

  protected function bit valid_sparse_strobe(bit [7:0] strb, bit [7:0] rw_lane_mask);
    return (strb & ~rw_lane_mask) == 0 && strb != 8'h00 && strb != 8'hFF &&
        !strb_contiguous(strb) && $countones(strb) >= 2 && strb != rw_lane_mask;
  endfunction

  protected function void valid_sparse_strobes(bit [7:0] rw_lane_mask, ref bit [7:0] values[$]);
    values.delete();
    for (int unsigned raw = 0; raw < (1 << SmcMemBytes); raw++) begin
      bit [7:0] strb = 8'(raw);
      if (valid_sparse_strobe(strb, rw_lane_mask)) values.push_back(strb);
    end
  endfunction

  protected function void fixed_sparse_strobes(bit [7:0] rw_lane_mask, ref bit [7:0] values[$]);
    bit [7:0] candidates[$] = '{8'h55, 8'hAA, 8'h81, 8'h5A, 8'h05};
    values.delete();
    foreach (candidates[i]) begin
      if (valid_sparse_strobe(candidates[i], rw_lane_mask)) values.push_back(candidates[i]);
    end
  endfunction

  protected function int unsigned rw_lane_at(bit [7:0] rw_lane_mask, int unsigned ordinal);
    int unsigned count;
    for (int unsigned lane = 0; lane < SmcMemBytes; lane++) begin
      if (!rw_lane_mask[lane]) continue;
      if (count == ordinal) return lane;
      count++;
    end
    `uvm_fatal(get_type_name(), $sformatf("RW lane ordinal %0d is out of range", ordinal))
    return 0;
  endfunction

  protected task write_strobe(bit [63:0] addr, bit [63:0] data, bit [7:0] strb, string label);
    smc_axi_mem_write_seq op = smc_axi_mem_write_seq::type_id::create("write_strobe");
    op.addr = addr;
    op.data = data;
    op.strb = strb;
    op.start(p_sequencer.m_sep_in_seqr);
    mem_accesses++;
    check_response(ChkMemResp, op.result, label, $sformatf(
                   "write addr=0x%0h data=0x%016h strb=0x%02h", addr, data, strb));
    `uvm_info(get_type_name(),
              $sformatf("SEP_IN MEM WRITE %-24s addr=0x%014h data=0x%016h strb=0x%02h resp=%s",
                        label, addr, data, strb, op.result.worst_resp().name()), UVM_MEDIUM)
  endtask

  protected task safe_read(bit [63:0] addr, bit [63:0] expected, string name);
    bit [63:0] observed;
    mem_read(addr, observed, name);
    if (observed !== expected)
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s is not in its required safe state: expected=0x%016h observed=0x%016h",
                 name,
                 expected,
                 observed
                 ))
  endtask

  protected task wait_for_comparisons(int unsigned target);
    for (int unsigned cycle = 0; cycle < ComparisonTimeoutCycles; cycle++) begin
      if (scoreboard.compare_count(SmcFeatureRegblockWide) >= target) return;
      wait_smc_cycles(1);
    end
    `uvm_error("OCAH_SMC_REGBLOCK_WIDE_TIMEOUT",
               $sformatf("regblock_wide comparisons=%0d target=%0d", scoreboard.compare_count(
                         SmcFeatureRegblockWide), target))
  endtask

  protected function bit [63:0] pass_pattern();
    case (loop_index)
      0: return 64'hFFFF_FFFF_FFFF_FFFF;
      1: return 64'h0000_0000_0000_0000;
      2: return 64'h5555_5555_5555_5555;
      3: return 64'hAAAA_AAAA_AAAA_AAAA;
      default: return {32'(random_pattern(32)), 32'(random_pattern(32))};
    endcase
  endfunction

  task body();
    smc_regblock_wide_entry_t entries[$];
    bit [7:0] fixed[$];
    bit [7:0] valid[$];
    bit [7:0] lane_coverage;
    bit [63:0] pattern;
    bit [63:0] status_word;
    int unsigned predicted_reads;
    int unsigned predicted_accesses = SafeStateReads + FinalStateReads;
    int unsigned compare_target;
    int unsigned mismatch_before;
    int unsigned accesses_before;
    int unsigned writes_before;
    int unsigned writes_after;
    int unsigned restore_changes;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkMemResp, ChkBaseline, ChkFullRw, ChkSingleByte, ChkSparse,
                    ChkNull, ChkRestore, ChkRestoreNonvac, ChkNoZeroerStart, ChkLaneCoverage,
                    ChkScoreboard, ChkNonvac, ChkSbMinAct});
    smc_regblock_wide_catalog(entries);
    if (entries.size() != CatalogEntries)
      `uvm_fatal(get_type_name(), $sformatf("regblock-wide catalog has %0d entries", entries.size()
                 ))
    foreach (entries[i]) begin
      fixed_sparse_strobes(entries[i].rw_lane_mask, fixed);
      valid_sparse_strobes(entries[i].rw_lane_mask, valid);
      if (valid.size() == 0)
        `uvm_fatal(get_type_name(), {entries[i].name, " has no valid sparse strobe"})
      predicted_reads += BaseReadsPerRegister + fixed.size();
      predicted_accesses += BaseAccessesPerRegister + 2 * fixed.size();
    end
    check_min_activity(SmcFeatureRegblockWide, predicted_reads);
    wait_fuse_sense_done();
    mismatch_before = scoreboard.mismatch_count(SmcFeatureRegblockWide);
    compare_target = scoreboard.compare_count(SmcFeatureRegblockWide) + predicted_reads;
    accesses_before = mem_accesses;
    writes_before = p_sequencer.m_sys_out_slave_seq.write_burst_count();

    // The catalogued words are side-effect-free only while the Zeroer is idle and
    // the hang detectors and alias region are disabled; stop before the first
    // write if any control word is not at its reset value.
    safe_read(SmcZeroerCtrlStatusAddr, ZEROER_CTRL_CTRL_STATUS_REG_DEFAULT,
              "ZEROER_CTRL.CTRL_STATUS");
    safe_read(SmcHangSysCtrlAddr, SMC_BASE_CONFIG_HANG_DET_CTRL_REG_DEFAULT,
              "HANG_DET_SYS_AXI_CTRL");
    safe_read(SmcHangSepCtrlAddr, SMC_BASE_CONFIG_HANG_DET_CTRL_REG_DEFAULT,
              "HANG_DET_SEP_AXI_CTRL");
    safe_read(SmcHangDataAccelCtrlAddr, SMC_BASE_CONFIG_HANG_DET_CTRL_REG_DEFAULT,
              "HANG_DET_DATA_ACCEL_CTRL");
    safe_read(SmcAliasRegionAttrsAddr, REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
              "SMC_ALIAS_REMAP_0.REGION_ATTRS");

    pattern = pass_pattern();
    foreach (entries[i]) begin
      bit [63:0] shadow = entries[i].reset_value;
      bit [63:0] data;
      bit [7:0] strb;
      int unsigned rw_lane_count = $countones(entries[i].rw_lane_mask);
      int unsigned lane = rw_lane_at(entries[i].rw_lane_mask, loop_index % rw_lane_count);

      mem_read_check(ChkBaseline, entries[i].addr, shadow, {entries[i].name, " baseline"});

      shadow = smc_regblock_merge_write(shadow, pattern, 8'hFF, entries[i].rw_mask);
      mem_write(entries[i].addr, pattern, {entries[i].name, " full write"});
      mem_read_check(ChkFullRw, entries[i].addr, shadow, {entries[i].name, " full readback"});

      data = ~shadow;
      strb = 8'(1 << lane);
      shadow = smc_regblock_merge_write(shadow, data, strb, entries[i].rw_mask);
      write_strobe(entries[i].addr, data, strb, {entries[i].name, " single-byte write"});
      mem_read_check(ChkSingleByte, entries[i].addr, shadow, {
                     entries[i].name, " single-byte readback"});
      lane_coverage |= strb & entries[i].rw_lane_mask;

      fixed_sparse_strobes(entries[i].rw_lane_mask, fixed);
      foreach (fixed[j]) begin
        data = ~shadow;
        shadow = smc_regblock_merge_write(shadow, data, fixed[j], entries[i].rw_mask);
        write_strobe(entries[i].addr, data, fixed[j], $sformatf(
                     "%s sparse 0x%02h write", entries[i].name, fixed[j]));
        mem_read_check(ChkSparse, entries[i].addr, shadow, $sformatf(
                       "%s sparse 0x%02h readback", entries[i].name, fixed[j]));
        lane_coverage |= fixed[j] & entries[i].rw_lane_mask;
      end

      valid_sparse_strobes(entries[i].rw_lane_mask, valid);
      strb = valid[int'(random_pattern(8) % valid.size())];
      data = ~shadow;
      shadow = smc_regblock_merge_write(shadow, data, strb, entries[i].rw_mask);
      write_strobe(entries[i].addr, data, strb, $sformatf(
                   "%s seeded sparse 0x%02h write", entries[i].name, strb));
      mem_read_check(ChkSparse, entries[i].addr, shadow, $sformatf(
                     "%s seeded sparse 0x%02h readback", entries[i].name, strb));
      lane_coverage |= strb & entries[i].rw_lane_mask;

      data = ~shadow;
      write_strobe(entries[i].addr, data, 8'h00, {entries[i].name, " null-strobe write"});
      mem_read_check(ChkNull, entries[i].addr, shadow, {entries[i].name, " null-strobe readback"});

      if (shadow != entries[i].reset_value) restore_changes++;
      mem_write(entries[i].addr, entries[i].reset_value, {entries[i].name, " restore"});
      mem_read_check(ChkRestore, entries[i].addr, entries[i].reset_value, {
                     entries[i].name, " restore readback"});
    end

    writes_after = p_sequencer.m_sys_out_slave_seq.write_burst_count();
    mem_read(SmcZeroerCtrlStatusAddr, status_word, "ZEROER_CTRL.CTRL_STATUS final");
    check_evidence(ChkNoZeroerStart, "Zeroer busy",
                   64'(status_word[ZEROER_CTRL_CTRL_STATUS_STATUS_SHIFT]), 64'h0,
                   "DEST_ADDR and SIZE writes left the Zeroer idle");
    check_evidence(ChkNoZeroerStart, "SYS_OUT write bursts", 64'(writes_after), 64'(writes_before),
                   "no Zeroer write reached SYS_OUT");
    check_evidence(ChkLaneCoverage, "strobed RW lanes", 64'(lane_coverage), 64'hFF,
                   "all SEP_IN byte lanes");
    check_evidence(ChkRestoreNonvac, "restores that changed an RW value", 64'(restore_changes > 0),
                   64'h1, $sformatf("non-vacuous restores=%0d", restore_changes));

    wait_for_comparisons(compare_target);
    void'(m_check.expect_true(
        ChkScoreboard,
        scoreboard.compare_count(
            SmcFeatureRegblockWide
        ) >= compare_target && scoreboard.mismatch_count(
            SmcFeatureRegblockWide
        ) == mismatch_before,
        $sformatf(
            "comparisons=%0d target=%0d mismatches_before=%0d mismatches_after=%0d",
            scoreboard.compare_count(
                SmcFeatureRegblockWide
            ),
            compare_target,
            mismatch_before,
            scoreboard.mismatch_count(
                SmcFeatureRegblockWide
            ))
    ));
    check_evidence(ChkNonvac, "wide register-block accesses", 64'(mem_accesses - accesses_before),
                   64'(predicted_accesses), "safe-state reads and complete register catalog");
    finalize_evidence();
  endtask

endclass : smc_regblock_sparse_strobe_test_seq
