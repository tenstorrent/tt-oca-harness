// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Interrupts held SEP_IN responses and checks same-ID SPM recovery.
class smc_ingress_reset_inflight_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_ingress_reset_inflight_test_seq)
  localparam string ChkPhase = "CHK-RIF-PHASE";
  localparam string ChkBaseline = "CHK-RIF-BASELINE";
  localparam string ChkAsserted = "CHK-RIF-ASSERTED";
  localparam string ChkReleased = "CHK-RIF-RELEASED";
  localparam string ChkEpoch = "CHK-RIF-EPOCH";
  localparam string ChkSva = "CHK-RIF-SVA";
  localparam string ChkStale = "CHK-RIF-NO-STALE";
  localparam string ChkRecovery = "CHK-RIF-RECOVERY";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned Ops = 2;
  localparam int unsigned PhaseBound = 10000;
  localparam int unsigned ResetBound = 5000;
  localparam int unsigned ReturnSlack = 16;
  // The cool pin is de-glitched over 32 reference-clock cycles.
  localparam int unsigned HoldRefCycles = 128;
  smc_sep_in_reset_monitor reset_monitor;
  bit negative;
  ocah_axi_master_config master_cfg;
  bit write_cell;
  bit [15:0] id;
  bit [63:0] base, baseline_data[Ops], fresh[Ops];
  int unsigned hold_cycles, item_bound, old_timeouts, compare_before;

  function new(string name = "smc_ingress_reset_inflight_test_seq");
    super.new(name);
  endfunction

  protected function void require_value(string id, bit condition, string label,
                                        string context_s = "");
    string detail = context_s == "" ? label : {label, " ", context_s};
    if (!m_check.expect_true(id, condition, detail))
      `uvm_fatal(get_type_name(), {"ingress reset prerequisite: ", detail})
  endfunction

  protected task wait_reset_level(bit level, string id);
    bit reached;
    for (int unsigned cycle = 0; cycle < ResetBound; cycle++) begin
      reached = tb_vif.rst_primary_smc_clk_n === level && tb_vif.rst_warm_smc_clk_n === level;
      if (reached) break;
      wait_smc_cycles(1);
    end
    require_value(id, reached, "primary and warm reset level", $sformatf(
                  "expected=%b primary=%b warm=%b bound=%0d",
                  level,
                  tb_vif.rst_primary_smc_clk_n,
                  tb_vif.rst_warm_smc_clk_n,
                  ResetBound
                  ));
  endtask

  protected task grade(string id, string label, bit condition, string context_s = "");
    check_evidence(id, label, 64'(condition), 64'(!negative), context_s);
  endtask

  protected function bit clean_epoch();
    return (reset_monitor.stale_b == 0 && reset_monitor.stale_r == 0) &&
        (reset_monitor.orphan_b == 0 && reset_monitor.orphan_r == 0) &&
        reset_monitor.shape_errors == 0;
  endfunction

  protected task prepare_cell();
    seed_scenario_rng();
    attach_evidence('{ChkPhase, ChkBaseline, ChkAsserted, ChkReleased, ChkEpoch, ChkSva, ChkStale,
                    ChkRecovery, ChkNonvac, ChkMemResp, ChkFuseSense, ChkSbMinAct});
    wait_fuse_sense_done();
    negative = env_cfg.ingress_reset_sequence_negative;
    if (negative)
      `uvm_info(get_type_name(), "NEGATIVE VALIDATION: ingress reset expectations reversed",
                UVM_LOW)
    require_value(ChkSva, tb_vif.axi_sva_en === 1'b1, "SEP_IN assertions enabled");
    if (!uvm_config_db#(ocah_axi_master_config)::get(
            p_sequencer.m_sep_in_seqr, "", "cfg", master_cfg
        ))
      `uvm_fatal(get_type_name(), "SEP_IN master config missing")
    hold_cycles =
        int'($ceil(HoldRefCycles * env_cfg.ref_clk_period_ns / env_cfg.smc_clk_period_ns));
    require_value(ChkPhase, master_cfg.timeout_cycles > hold_cycles && hold_cycles > 0,
                  "finite timeout exceeds response hold", $sformatf(
                  "timeout=%0d hold=%0d", master_cfg.timeout_cycles, hold_cycles));
    item_bound = hold_cycles + master_cfg.timeout_cycles + ReturnSlack;
    write_cell = loop_index % 2 == 0;
    id = master_cfg.mask_id(16'(random_pattern(16)));
    base = SmcSpmBase + 64'h1000 + 64'(loop_index) * 64'h100;
    require_value(ChkBaseline,
                  base >= SmcSpmBase && base + Ops * SmcMemBytes <= SmcSpmBase + SmcSpmSize,
                  "SPM probe geometry");
    compare_before = scoreboard.compare_count(SmcFeatureSpmMem);
    check_min_activity(SmcFeatureSpmMem, 2 * Ops);
    if (reset_monitor == null) begin
      `uvm_fatal(get_type_name(), "Env reset monitor is not connected")
    end
    begin
      int unsigned sample_before = reset_monitor.sample_count;
      reset_monitor.arm(write_cell);
      for (int unsigned c = 0; c < PhaseBound; c++) begin
        if (reset_monitor.sample_count != sample_before) break;
        wait_smc_cycles(1);
      end
      require_value(ChkBaseline, reset_monitor.armed && reset_monitor.sample_count != sample_before,
                    "env reset monitor samples after arm");
    end
  endtask

  protected task baseline_cell();
    bit [63:0] data;
    foreach (baseline_data[i]) begin
      baseline_data[i] = random_pattern(64);
      fresh[i] = ~baseline_data[i] ^ 64'h55AA_55AA_55AA_55AA;
      mem_write(base + 64'(i) * SmcMemBytes, baseline_data[i], "baseline seed");
    end
    foreach (baseline_data[i]) begin
      mem_read(base + 64'(i) * SmcMemBytes, data, "baseline readback");
      require_value(ChkBaseline, data == baseline_data[i], "baseline data", $sformatf(
                    "seed=%0d addr=%h expected=%h observed=%h",
                    scenario_seed,
                    base + 64'(i) * SmcMemBytes,
                    baseline_data[i],
                    data
                    ));
    end
    uvm_wait_for_nba_region();
    require_value(ChkBaseline,
                  reset_monitor.aw == Ops && reset_monitor.w == Ops && reset_monitor.b == Ops &&
                  reset_monitor.ar == Ops && reset_monitor.r == Ops && clean_epoch(),
                  "five-channel monitor positive control", reset_monitor.counters_context());
  endtask

  protected task interrupt_cell();
    smc_ingress_reset_pipeline_seq pipe;
    bit reached;
    int unsigned cold_before, cool_before;
    reset_monitor.clear_counts();
    pipe = smc_ingress_reset_pipeline_seq::type_id::create("pipe");
    pipe.cfg = master_cfg;
    pipe.hold_cycles = hold_cycles;
    foreach (baseline_data[i]) begin
      pipe.add_access(write_cell, base + 64'(i) * SmcMemBytes, ~baseline_data[i], id);
    end
    fork
      pipe.start(p_sequencer.m_sep_in_seqr);
    join_none
    for (int unsigned c = 0; c < PhaseBound; c++) begin
      if (write_cell) reached = reset_monitor.aw == Ops && reset_monitor.w == Ops;
      else reached = reset_monitor.ar == Ops;
      reached &= reset_monitor.request_idle && reset_monitor.held_response;
      if (reached) break;
      wait_smc_cycles(1);
    end
    require_value(ChkPhase, reached && !pipe.done, "held-response phase reached", $sformatf(
                  "request_idle=%b held_response=%b pipe_done=%b %s",
                  reset_monitor.request_idle,
                  reset_monitor.held_response,
                  pipe.done,
                  reset_monitor.counters_context()
                  ));
    cold_before = tb_vif.cold_rst_assert_count;
    cool_before = tb_vif.cool_rst_assert_count;
    tb_vif.rst_cool_n <= 1'b0;
    wait_reset_level(1'b0, ChkAsserted);
    require_value(ChkPhase,
                  reset_monitor.reset_seen && reset_monitor.phase_valid &&
                  reset_monitor.abandoned == Ops && reset_monitor.held_valid > 0 && !pipe.done,
                  "requests accepted and response held at effective reset", $sformatf(
                  "%s reset_seen=%b phase_valid=%b abandoned=%0d pipe_done=%b",
                  reset_monitor.phase_context,
                  reset_monitor.reset_seen,
                  reset_monitor.phase_valid,
                  reset_monitor.abandoned,
                  pipe.done
                  ));
    tb_vif.rst_cool_n <= 1'b1;
    wait_reset_level(1'b1, ChkReleased);
    wait_fuse_sense_done();
    require_value(ChkEpoch,
                  reset_monitor.extra_resets == 0 &&
                  tb_vif.cold_rst_assert_count == cold_before &&
                  tb_vif.cool_rst_assert_count == cool_before + 1,
                  "one cool and no cold reset", $sformatf(
                  {
                    "cold_before=%0d cold_after=%0d cool_before=%0d cool_after=%0d ",
                    "extra_resets=%0d"
                  },
                  cold_before,
                  tb_vif.cold_rst_assert_count,
                  cool_before,
                  tb_vif.cool_rst_assert_count,
                  reset_monitor.extra_resets
                  ));
    for (int unsigned c = 0; c < item_bound && !pipe.done; c++) begin
      wait_smc_cycles(1);
    end
    require_value(ChkPhase, pipe.done, "interrupted pipeline terminates within bound", $sformatf(
                  "done=%b bound=%0d %s", pipe.done, item_bound, reset_monitor.counters_context()));
    foreach (pipe.ops[i]) begin
      if (pipe.ops[i].timed_out) old_timeouts++;
      require_value(
          ChkPhase, pipe.ops[i].timed_out && pipe.ops[i].resp_list.size() == 0,
          "old operation timed out without response", $sformatf(
          "index=%0d timed_out=%b responses=%p", i, pipe.ops[i].timed_out, pipe.ops[i].resp_list));
      `uvm_info(get_type_name(), $sformatf(
                "OBS-RIF-ABANDONED seed=%0d write=%0b id=%h timed_out=%0b responses=%0d",
                scenario_seed,
                write_cell,
                id,
                pipe.ops[i].timed_out,
                pipe.ops[i].resp_list.size()
                ), UVM_LOW)
    end
    begin
      int unsigned waited;
      for (waited = 0; waited < PhaseBound; waited++) begin
        if (reset_monitor.request_idle && reset_monitor.master_ready_low) break;
        wait_smc_cycles(1);
      end
      require_value(ChkPhase, reset_monitor.request_idle && reset_monitor.master_ready_low,
                    "master idle before recovery", $sformatf(
                    "request_idle=%b BREADY=%b RREADY=%b waited=%0d bound=%0d",
                    reset_monitor.request_idle,
                    reset_monitor.sampled_bready,
                    reset_monitor.sampled_rready,
                    waited,
                    PhaseBound
                    ));
    end
  endtask

  protected task recover_cell();
    smc_ingress_reset_pipeline_seq pipe;
    grade(ChkStale, "no old response before recovery",
          clean_epoch() && reset_monitor.b == 0 && reset_monitor.r == 0,
          reset_monitor.counters_context());
    for (int unsigned direction = 0; direction < 2; direction++) begin
      pipe = smc_ingress_reset_pipeline_seq::type_id::create("pipe");
      pipe.cfg = master_cfg;
      foreach (fresh[i]) begin
        pipe.add_access(direction == 0, base + 64'(i) * SmcMemBytes, fresh[i], id);
      end
      pipe.start(p_sequencer.m_sep_in_seqr);
      foreach (pipe.ops[i]) begin
        bit valid = pipe.ops[i].is_ok() && !pipe.ops[i].any_resp_xz() &&
            pipe.ops[i].resp_list.size() == 1 && pipe.ops[i].observed_id_valid &&
            pipe.ops[i].observed_id == id;
        if (direction != 0) begin
          valid &= pipe.ops[i].data_words.size() == 1 && pipe.ops[i].data_xz_masks.size() == 1;
          if (pipe.ops[i].data_words.size() == 1 && pipe.ops[i].data_xz_masks.size() == 1) begin
            valid &= pipe.ops[i].data_words[0] == fresh[i] && pipe.ops[i].data_xz_masks[0] == 0;
          end
        end
        grade(ChkRecovery, direction == 0 ? "fresh write response" : "fresh read response/data",
              valid, $sformatf(
              {
                "seed=%0d id=%h index=%0d timed_out=%b responses=%p resp_xz=%b ",
                "observed_id_valid=%b observed_id=%h data_words=%p data_xz_masks=%p ",
                "expected_data=%h"
              },
              scenario_seed,
              id,
              i,
              pipe.ops[i].timed_out,
              pipe.ops[i].resp_list,
              pipe.ops[i].any_resp_xz(),
              pipe.ops[i].observed_id_valid,
              pipe.ops[i].observed_id,
              pipe.ops[i].data_words,
              pipe.ops[i].data_xz_masks,
              fresh[i]
              ));
      end
    end
    uvm_wait_for_nba_region();
    grade(ChkRecovery, "fresh response accounting",
          clean_epoch() && (reset_monitor.b == Ops && reset_monitor.r == Ops) &&
          (reset_monitor.aw == Ops && reset_monitor.w == Ops && reset_monitor.ar == Ops) &&
          reset_monitor.pending_write() == 0 && reset_monitor.pending_read == 0 &&
          reset_monitor.b_valid_with_pending > 0 && reset_monitor.r_valid_with_pending > 0,
          reset_monitor.counters_context());
    for (int unsigned c = 0; c < ReturnSlack; c++) begin
      if (scoreboard.compare_count(SmcFeatureSpmMem) >= compare_before + 2 * Ops) break;
      wait_smc_cycles(1);
    end
    check_evidence(ChkNonvac, "helper accesses", mem_accesses, 2 * Ops);
    check_evidence(ChkNonvac, "old operation timeouts", old_timeouts, Ops);
    check_evidence(ChkNonvac, "abandoned operations", reset_monitor.abandoned, Ops);
    check_evidence(ChkNonvac, "SPM comparisons", scoreboard.compare_count(SmcFeatureSpmMem
                   ) - compare_before, 2 * Ops);
    require_value(ChkSva, !reset_monitor.sva_disabled, "assertions remained enabled");
    reset_monitor.disarm();
    finalize_evidence();
  endtask

  task body();
    prepare_cell();
    baseline_cell();
    interrupt_cell();
    recover_cell();
  endtask
endclass : smc_ingress_reset_inflight_test_seq
