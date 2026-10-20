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
  smc_ingress_reset_observer observer;
  bit negative;

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
    return observer.stale_b == 0 && observer.stale_r == 0 && observer.orphan_b == 0 &&
        observer.orphan_r == 0 && observer.shape_errors == 0;
  endfunction

  task body();
    ocah_axi_master_config master_cfg;
    smc_ingress_reset_pipeline_seq pipe;
    bit write_cell, reached;
    bit [15:0] id;
    bit [63:0] base, baseline_data[Ops], fresh[Ops], data;
    int unsigned hold_cycles, item_bound, old_timeouts, compare_before;
    int unsigned cold_before, cool_before;
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
    observer = smc_ingress_reset_observer::type_id::create("observer");
    observer.vif = master_cfg.vif;
    observer.tb_vif = tb_vif;
    observer.write_cell = write_cell;
    fork
      observer.watch();
    join_none
    for (int unsigned c = 0; c < PhaseBound && !observer.ready; c++) begin
      wait_smc_cycles(1);
    end
    require_value(ChkBaseline, observer.ready, "observer ready");
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
                  observer.aw == Ops && observer.w == Ops && observer.b == Ops &&
                  observer.ar == Ops && observer.r == Ops && clean_epoch(),
                  "five-channel observer positive control", observer.counters_context());
    observer.clear_counts();
    observer.held_valid = 0;
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
      reached = observer.request_idle && observer.held_response &&
          (write_cell ? observer.aw == Ops && observer.w == Ops : observer.ar == Ops);
      if (reached) break;
      wait_smc_cycles(1);
    end
    require_value(ChkPhase, reached && !pipe.done, "held-response phase reached", $sformatf(
                  "request_idle=%b held_response=%b pipe_done=%b %s",
                  observer.request_idle,
                  observer.held_response,
                  pipe.done,
                  observer.counters_context()
                  ));
    cold_before = tb_vif.cold_rst_assert_count;
    cool_before = tb_vif.cool_rst_assert_count;
    tb_vif.rst_cool_n <= 1'b0;
    wait_reset_level(1'b0, ChkAsserted);
    require_value(ChkPhase,
                  observer.reset_seen && observer.phase_valid &&
                  observer.abandoned == Ops && observer.held_valid > 0 && !pipe.done,
                  "requests accepted and response held at effective reset", $sformatf(
                  "%s reset_seen=%b phase_valid=%b abandoned=%0d pipe_done=%b",
                  observer.phase_context,
                  observer.reset_seen,
                  observer.phase_valid,
                  observer.abandoned,
                  pipe.done
                  ));
    tb_vif.rst_cool_n <= 1'b1;
    wait_reset_level(1'b1, ChkReleased);
    wait_fuse_sense_done();
    require_value(ChkEpoch,
                  tb_vif.cold_rst_assert_count == cold_before &&
                  tb_vif.cool_rst_assert_count == cool_before + 1,
                  "one cool and no cold reset", $sformatf(
                  "cold_before=%0d cold_after=%0d cool_before=%0d cool_after=%0d",
                  cold_before,
                  tb_vif.cold_rst_assert_count,
                  cool_before,
                  tb_vif.cool_rst_assert_count
                  ));
    for (int unsigned c = 0; c < item_bound && !pipe.done; c++) begin
      wait_smc_cycles(1);
    end
    require_value(ChkPhase, pipe.done, "interrupted pipeline terminates within bound", $sformatf(
                  "done=%b bound=%0d %s", pipe.done, item_bound, observer.counters_context()));
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
    require_value(ChkPhase,
                  observer.request_idle && master_cfg.vif.bready === 1'b0 &&
                  master_cfg.vif.rready === 1'b0,
                  "master idle before recovery", $sformatf(
                  "request_idle=%b BREADY=%b RREADY=%b",
                  observer.request_idle,
                  master_cfg.vif.bready,
                  master_cfg.vif.rready
                  ));
    grade(ChkStale, "no old response before recovery",
          clean_epoch() && observer.b == 0 && observer.r == 0, observer.counters_context());
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
    observer.stop = 1;
    for (int unsigned c = 0; c < PhaseBound && !observer.stopped; c++) begin
      wait_smc_cycles(1);
    end
    require_value(ChkPhase, observer.stopped, "observer stopped");
    grade(ChkRecovery, "fresh response accounting",
          clean_epoch() && observer.b == Ops &&
          observer.r == Ops && observer.aw == Ops && observer.w == Ops && observer.ar == Ops &&
          observer.pending_write() == 0 && observer.pending_read == 0 &&
          observer.b_valid_with_pending > 0 && observer.r_valid_with_pending > 0,
          observer.counters_context());
    for (int unsigned c = 0; c < ReturnSlack; c++) begin
      if (scoreboard.compare_count(SmcFeatureSpmMem) >= compare_before + 2 * Ops) break;
      wait_smc_cycles(1);
    end
    check_evidence(ChkNonvac, "helper accesses", mem_accesses, 2 * Ops);
    check_evidence(ChkNonvac, "old operation timeouts", old_timeouts, Ops);
    check_evidence(ChkNonvac, "abandoned operations", observer.abandoned, Ops);
    check_evidence(ChkNonvac, "SPM comparisons", scoreboard.compare_count(SmcFeatureSpmMem
                   ) - compare_before, 2 * Ops);
    require_value(ChkSva, !observer.sva_disabled, "assertions remained enabled");
    finalize_evidence();
  endtask
endclass : smc_ingress_reset_inflight_test_seq
