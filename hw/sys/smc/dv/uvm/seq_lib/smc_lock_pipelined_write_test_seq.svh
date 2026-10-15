// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Checks keyed WDT write ordering and SS_CONFIG bit locks with overlapping
// SEP_IN writes. AW/W/B handshakes establish overlap of each decisive pair.

class smc_lock_pipelined_write_test_seq extends smc_wdt_base_test_seq;
  `uvm_object_utils(smc_lock_pipelined_write_test_seq)

  localparam string ChkSeed = "CHK-PLOCK-SEED";
  localparam string ChkResp = "CHK-PLOCK-RESP";
  localparam string ChkRestore = "CHK-PLOCK-WDT-RESTORE";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam string ChkOne = "CHK-PLOCK-WDT-ONE";
  localparam string ChkIneffective = "CHK-PLOCK-WDT-INEFFECTIVE";
  localparam string ChkPrekey = "CHK-PLOCK-WDT-PREKEY";
  localparam string ChkFeedkey = "CHK-PLOCK-WDT-FEEDKEY";
  localparam string ChkState = "CHK-PLOCK-WDT-STATE";
  localparam string ChkConfig = "CHK-PLOCK-SSCFG";
  localparam string ChkFinal = "CHK-PLOCK-SSCFG-FINAL";
  localparam string ChkScoreboard = "CHK-PLOCK-SCOREBOARD";
  typedef enum int unsigned {
    P1,
    P2A,
    P2B,
    P3,
    P4,
    P5
  } leg_e;
  localparam int unsigned WdtLegs = 6;
  localparam int unsigned CpuCores = SmcWdtCores;
  localparam int unsigned HoldCycles = 16;
  localparam int unsigned CountSamples = 64;
  localparam bit [31:0] CompareBits = WDT_CMP_WDOGCMP0_MASK;
  localparam int unsigned LockReads = 6;
  localparam int unsigned LockComparisonBound = 32;
  // Lock bits span two bytes; the queued inverse write must move a free bit.
  localparam bit [31:0] ForcedLockBits = 32'h0000_0101;
  localparam bit [31:0] FreeConfigBit = 32'h8000_0000;
  localparam bit [3:0] PartialStrb = 4'h3;
  localparam bit [63:0] ConfigAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR;
  localparam bit [63:0] LockAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR;
  bit final_pass;

  function new(string name = "smc_lock_pipelined_write_test_seq");
    super.new(name);
  endfunction

  protected function bit [31:0] count_value(bit [31:0] cmp_value);
    bit [31:0] value = 32'(random_pattern(32)) & WDT_COUNT_WDOGCOUNT_MASK;
    value = (value & ~CompareBits) | (32'(random_pattern(32)) % cmp_value);
    return value;
  endfunction

  task body();
    int unsigned completed_legs;
    int unsigned overlapped_legs;
    bit negative = ocah_knobs::is_set("SMC_LOCK_PIPELINED_SEQUENCE_NEGATIVE");
    string names[WdtLegs] = '{"P1", "P2A", "P2B", "P3", "P4", "P5"};
    string required[$] = '{
        ChkSeed,
        ChkResp,
        ChkRestore,
        ChkNonvac,
        ChkFuseSense,
        ChkCsrResp,
        ChkOne,
        ChkIneffective,
        ChkPrekey,
        ChkFeedkey,
        ChkState
    };
    if (final_pass) begin
      required.push_back(ChkConfig);
      required.push_back(ChkFinal);
      required.push_back(ChkScoreboard);
    end
    seed_scenario_rng();
    attach_evidence(required);
    wait_fuse_sense_done();
    for (core = 0; core < CpuCores; core++) begin
      bit [31:0] cmp_value, initial_count, a, b, observed;
      csr_read(smc_wdt_addr(core, WDT_CTRL), observed, "WDT CTRL prerequisite");
      check_evidence(ChkSeed, "WDT CTRL prerequisite", 64'(observed), 64'(WDT_CTRL_REG_DEFAULT));
      if (observed != 32'(WDT_CTRL_REG_DEFAULT))
        `uvm_fatal(get_type_name(), "WDT CTRL is not in its reset state")
      csr_read(smc_wdt_addr(core, WDT_CMP), cmp_value, "WDT CMP prerequisite");
      check_evidence(ChkSeed, "WDT CMP prerequisite", 64'(cmp_value), 64'(WDT_CMP_REG_DEFAULT));
      if (cmp_value != 32'(WDT_CMP_REG_DEFAULT) || cmp_value < 2 ||
          cmp_value > WDT_CMP_WDOGCMP0_MASK)
        `uvm_fatal(get_type_name(), "invalid WDT compare prerequisite")
      do initial_count = count_value(cmp_value); while (initial_count == 0);
      do a = count_value(cmp_value); while (a == 0 || a == initial_count);
      do begin
        b = count_value(cmp_value);
      end while (b == a || b == initial_count ||
                 (b & CompareBits) == (initial_count & CompareBits));
      foreach (names[k]) begin
        smc_lock_pipeline_write_seq op = smc_lock_pipeline_write_seq::type_id::create("op");
        bit [31:0] partial_count = (initial_count & ~CompareBits) |
                                  (b & CompareBits);
        if (!uvm_config_db#(ocah_axi_master_config)::get(
                p_sequencer.m_sep_in_seqr, "", "cfg", op.cfg
            ))
          `uvm_fatal(get_type_name(), "SEP_IN master configuration is unavailable")
        wdt_write(WDT_COUNT, initial_count);
        csr_read_check(ChkSeed, smc_wdt_addr(core, WDT_COUNT), initial_count, "WDT baseline");
        csr_read_check(ChkSeed, smc_wdt_addr(core, WDT_KEY), 0, "WDT locked baseline");
        if (k == P1) begin
          wait_smc_cycles(CountSamples);
          csr_read_check(ChkSeed, smc_wdt_addr(core, WDT_COUNT), initial_count,
                         "WDT count holds while disabled");
        end
        op.label = $sformatf("core=%0d %s", core, names[k]);
        op.previous_op = (k inside {P1, P2B, P4, P5}) ? 1 : 0;
        op.next_op = op.previous_op + 1;
        if (k == P3) begin
          op.add_write(smc_wdt_addr(core, WDT_COUNT), a);
          op.add_write(smc_wdt_addr(core, WDT_KEY), SmcWdtMagicKey);
        end else begin
          op.add_write(smc_wdt_addr(core, WDT_KEY), SmcWdtMagicKey);
          if (k == P4) begin
            ocah_axi_item feed_key = op.pipeline_write(
                smc_wdt_addr(
                    core, WDT_FEED
                ),
                (64'(SmcWdtMagicKey) << (8 * (SmcWdtKeyOffset % SmcMemBytes))) |
                    64'(SmcWdtFeedMagic)
            );
            op.ops.push_back(feed_key);
            op.add_write(smc_wdt_addr(core, WDT_COUNT), a);
          end else if (k inside {P2A, P2B}) begin
            op.add_write(smc_wdt_addr(core, WDT_COUNT), b, PartialStrb);
            if (k == P2B) op.add_write(smc_wdt_addr(core, WDT_COUNT), a);
          end else begin
            op.add_write(smc_wdt_addr(core, WDT_COUNT), a);
            op.add_write(smc_wdt_addr(core, WDT_COUNT), b);
          end
        end
        if (k == P5) op.hold_cycles = HoldCycles;
        op.start(p_sequencer.m_sep_in_seqr);
        check_evidence(ChkResp, op.label, 64'(op.complete), 1);
        if (op.complete) completed_legs++;
        check_evidence(ChkNonvac, {op.label, " decisive pair overlap"}, 64'(op.overlap), 1);
        if (op.complete && op.overlap) overlapped_legs++;
        csr_read(smc_wdt_addr(core, WDT_COUNT), observed, "WDT count after pipeline");
        `uvm_info(
            "PLOCK-PIPELINE", $sformatf(
            "%s count=0x%08h C0=0x%08h A=0x%08h B=0x%08h", op.label, observed, initial_count, a, b),
            UVM_LOW)
        case (k)
          P1, P5:
          check_evidence(ChkOne, op.label, 64'(observed),
                         64'(negative && core == 0 && k == P1 ? b : a));
          P2A:
          check_evidence(ChkIneffective, op.label, 64'(observed),
                         64'(negative && core == 0 ? partial_count : initial_count));
          P2B: check_evidence(ChkIneffective, op.label, 64'(observed), 64'(a));
          P3:
          check_evidence(ChkPrekey, op.label, 64'(observed),
                         64'(negative && core == 0 ? a : initial_count));
          P4:
          check_evidence(ChkFeedkey, op.label, 64'(observed),
                         64'(negative && core == 0 ? a : 0));
          default: `uvm_fatal(get_type_name(), "invalid WDT pipeline leg")
        endcase
        csr_read(smc_wdt_addr(core, WDT_KEY), observed, "WDT key after pipeline");
        `uvm_info("PLOCK-PIPELINE", $sformatf("%s key=0x%08h", op.label, observed), UVM_LOW)
        check_evidence(ChkState, op.label, 64'(observed), 64'(k inside {P2A, P3} ? 1 : 0));
        if (k == P2A) begin
          check_evidence(ChkIneffective, {op.label, " unlock retained"}, 64'(observed), 1);
          csr_write(smc_wdt_addr(core, WDT_COUNT), a, "WDT write after partial");
          csr_read_check(ChkIneffective, smc_wdt_addr(core, WDT_COUNT), a,
                         "WDT full write uses retained unlock");
          csr_read_check(ChkState, smc_wdt_addr(core, WDT_KEY), 0, "WDT relocked after full write");
        end
        if (k == P3) begin
          csr_write(smc_wdt_addr(core, WDT_SCALED_COUNT), 0, "WDT relock");
          csr_read_check(ChkState, smc_wdt_addr(core, WDT_KEY), 0, "WDT scaled write relocks");
        end
      end
      wdt_write(WDT_COUNT, 32'(WDT_COUNT_REG_DEFAULT));
      csr_read_check(ChkRestore, smc_wdt_addr(core, WDT_COUNT), 32'(WDT_COUNT_REG_DEFAULT),
                     "WDT restored count");
      csr_read_check(ChkRestore, smc_wdt_addr(core, WDT_KEY), 0, "WDT restored key");
      csr_read_check(ChkRestore, smc_wdt_addr(core, WDT_CTRL), 32'(WDT_CTRL_REG_DEFAULT),
                     "WDT restored CTRL");
    end
    if (final_pass) begin
      smc_lock_pipeline_write_seq op = smc_lock_pipeline_write_seq::type_id::create("op");
      bit [31:0] initial_config = 32'(random_pattern(32));
      bit [31:0] lock_mask = (32'(random_pattern(32)) | ForcedLockBits) & ~FreeConfigBit;
      bit [31:0] lock_value;
      bit [31:0] expected, config_value;
      int unsigned compares_before = scoreboard.compare_count(SmcFeatureLockCsr);
      int unsigned mismatches_before = scoreboard.mismatch_count(SmcFeatureLockCsr);
      if (!uvm_config_db#(ocah_axi_master_config)::get(
              p_sequencer.m_sep_in_seqr, "", "cfg", op.cfg
          ))
        `uvm_fatal(get_type_name(), "SEP_IN master configuration is unavailable")
      csr_read(LockAddr, lock_value, "SS_CONFIG unlocked prerequisite");
      check_evidence(ChkSeed, "SS_CONFIG unlocked prerequisite", 64'(lock_value), 0);
      if (lock_value != 0) `uvm_fatal(get_type_name(), "SS_CONFIG lock is already set")
      csr_write(ConfigAddr, initial_config, "SS_CONFIG baseline");
      csr_read_check(ChkSeed, ConfigAddr, initial_config, "SS_CONFIG baseline readback");
      op.label = "L1";
      op.previous_op = 0;
      op.next_op = 1;
      op.add_write(LockAddr, lock_mask, .size(SmcCsrSize));
      op.add_write(ConfigAddr, ~initial_config, .size(SmcCsrSize));
      op.start(p_sequencer.m_sep_in_seqr);
      check_evidence(ChkResp, op.label, 64'(op.complete), 1);
      if (op.complete) completed_legs++;
      check_evidence(ChkNonvac, "L1 decisive pair overlap", 64'(op.overlap), 1);
      if (op.complete && op.overlap) overlapped_legs++;
      expected = (initial_config & lock_mask) | (~initial_config & ~lock_mask);
      csr_read(ConfigAddr, config_value, "SS_CONFIG after pipeline");
      check_evidence(ChkConfig, "SS_CONFIG lock filters queued write", 64'(config_value),
                     64'(negative ? ~initial_config : expected));
      csr_read_check(ChkConfig, LockAddr, lock_mask, "SS_CONFIG pipeline lock readback");
      csr_write(ConfigAddr, 32'(RESET_UNIT_SS_CONFIG_REG_DEFAULT), "SS_CONFIG final restore");
      csr_read_check(
          ChkFinal, ConfigAddr,
          (initial_config & lock_mask) | (32'(RESET_UNIT_SS_CONFIG_REG_DEFAULT) & ~lock_mask),
          "SS_CONFIG final state");
      csr_write(LockAddr, 0, "SS_CONFIG zero lock write");
      csr_read_check(ChkFinal, LockAddr, lock_mask, "SS_CONFIG final lock");
      for (int unsigned cycle = 0; cycle < LockComparisonBound; cycle++) begin
        if (scoreboard.compare_count(SmcFeatureLockCsr) >= compares_before + LockReads) break;
        wait_smc_cycles(1);
      end
      void'(m_check.expect_true(
          ChkScoreboard,
          scoreboard.compare_count(
              SmcFeatureLockCsr
          ) == compares_before + LockReads && scoreboard.mismatch_count(
              SmcFeatureLockCsr
          ) == mismatches_before,
          $sformatf(
              "L1 comparisons=%0d required=%0d mismatches=%0d",
              scoreboard.compare_count(
                  SmcFeatureLockCsr
              ) - compares_before,
              LockReads,
              scoreboard.mismatch_count(
                  SmcFeatureLockCsr
              ) - mismatches_before)
      ));
    end
    check_evidence(ChkNonvac, "completed pipeline legs", 64'(completed_legs),
                   64'(CpuCores * WdtLegs + int'(final_pass)));
    check_evidence(ChkNonvac, "overlapped pipeline legs", 64'(overlapped_legs),
                   64'(CpuCores * WdtLegs + int'(final_pass)));
    finalize_evidence();
  endtask
endclass : smc_lock_pipelined_write_test_seq
