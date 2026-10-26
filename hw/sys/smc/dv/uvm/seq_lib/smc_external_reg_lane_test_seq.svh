// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Checks byte-enable merges, neighbor protection and isolation effects.
class smc_external_reg_lane_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_external_reg_lane_test_seq)
  localparam string ChkLane = "CHK-EXTREG-LANE";
  localparam string ChkNull = "CHK-EXTREG-NULL";
  localparam string ChkNeighbor = "CHK-EXTREG-NEIGHBOR";
  localparam string ChkVis = "CHK-EXTREG-VIS";
  localparam string ChkEffect = "CHK-EXTREG-EFFECT";
  localparam string ChkIdle = "CHK-EXTREG-IDLE";
  localparam string ChkStimulus = "CHK-EXTREG-STIMULUS";
  localparam string ChkSetup = "CHK-EXTREG-SETUP";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned Words = 6;
  localparam int unsigned WritesPerWord = 8;
  localparam int unsigned PinBound = 32;
  localparam int unsigned SourceBound = 32;
  localparam int unsigned StableSamples = 8;
  // GPIO integrator table, doc/integrator/meta/ocah_gpio_table.csv: Isolate Request.
  localparam int unsigned IsolatePad = 53;
  // Five wide baselines, forty wide writes and forty wide readbacks.
  localparam int unsigned MemAccessesPerPass = 85;
  // Setup/final 6; narrow baseline/write/read 17; target restores 12;
  // two RW-neighbor restores/readbacks 4. VIS polling is counted separately.
  localparam int unsigned FixedCsrAccesses = 39;
  localparam bit [63:0] FlrAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR;
  localparam bit [63:0] LockAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR;
  localparam bit [63:0] VisAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_VIS_BASE_ADDR;
  localparam bit [63:0] FlrResetCounterAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR;
  localparam bit [31:0] VisIdle = RESET_UNIT_ISOLATE_REQ_VIS_COOL_RESET_N_I_MASK |
      RESET_UNIT_ISOLATE_REQ_VIS_COOL_RESET_N_O_MASK;
  localparam bit [31:0] VisMask = VisIdle | RESET_UNIT_ISOLATE_REQ_VIS_ISOLATE_REQ_PIN_MASK;
  typedef struct {
    string name;
    bit [63:0] addr;
    bit [31:0] reset_value;
  } entry_t;
  virtual ocah_axi_if vif;
  bit negative, watch_ready, watch_stop, watch_done, idle_en, idle_bad;
  logic [31:0] idle_first_bad;
  int unsigned aw_count, w_count, b_count, pin_polls;
  logic [63:0] aw_addr, w_data;
  logic [15:0] aw_id, b_id;
  logic [7:0] w_strb, aw_len;
  logic [2:0] aw_size;
  logic w_last;
  logic [1:0] b_resp;

  function new(string name = "smc_external_reg_lane_test_seq");
    super.new(name);
  endfunction

  protected function void require_value(string id, bit condition, string context_s);
    if (!m_check.expect_true(id, condition, context_s))
      `uvm_fatal(get_type_name(), {"external register prerequisite: ", context_s})
  endfunction

  protected function void catalog(ref entry_t entries[$]);
    entries = '{
        '{
            "ISOLATE_REQ_REG",
            smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR,
            32'(RESET_UNIT_ISOLATE_REQ_REG_REG_DEFAULT)
        },
        '{
            "ISOLATE_REQ_PINEN_REG",
            smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_PINEN_REG_BASE_ADDR,
            32'(RESET_UNIT_ISOLATE_REQ_PINEN_REG_REG_DEFAULT)
        },
        '{
            "SS_CONFIG",
            smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR,
            32'(RESET_UNIT_SS_CONFIG_REG_DEFAULT)
        },
        '{
            "ISOLATE_REQ_SMCEN_REG",
            smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR,
            32'(RESET_UNIT_ISOLATE_REQ_SMCEN_REG_REG_DEFAULT)
        },
        '{
            "ISOLATE_REQ_FLR_COUNTER_VALUE",
            smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR,
            32'(RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_REG_DEFAULT)
        },
        '{
            "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE",
            FlrResetCounterAddr,
            32'(RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_REG_DEFAULT)
        }
    };
  endfunction

  protected function bit [31:0] lane_mask(bit [3:0] strb);
    bit [31:0] mask;
    for (int unsigned lane = 0; lane < SmcCsrBytes; lane++) begin
      mask[8*lane+:8] = {8{strb[lane]}};
    end
    return mask;
  endfunction

  protected task sample_bus();
    forever begin
      @(vif.mon_cb);
      if (vif.mon_cb.awvalid === 1'b1 && vif.mon_cb.awready === 1'b1) begin
        aw_count++;
        aw_addr = vif.mon_cb.awaddr;
        aw_size = vif.mon_cb.awsize;
        aw_len = vif.mon_cb.awlen;
        aw_id = vif.mon_cb.awid;
      end
      if (vif.mon_cb.wvalid === 1'b1 && vif.mon_cb.wready === 1'b1) begin
        w_count++;
        w_data = vif.mon_cb.wdata;
        w_strb = vif.mon_cb.wstrb;
        w_last = vif.mon_cb.wlast;
      end
      if (vif.mon_cb.bvalid === 1'b1 && vif.mon_cb.bready === 1'b1) begin
        b_count++;
        b_id = vif.mon_cb.bid;
        b_resp = vif.mon_cb.bresp;
      end
    end
  endtask

  protected task watch();
    watch_ready = 1;
    fork
      sample_bus();
      forever begin
        if (idle_en && tb_vif.isolate_req !== 32'b0 && !idle_bad) begin
          idle_bad = 1;
          idle_first_bad = tb_vif.isolate_req;
        end
        @(tb_vif.isolate_req or idle_en or watch_stop);
      end
      wait (watch_stop);
    join_any
    disable fork;
    watch_done = 1;
  endtask

  protected task set_pin(bit level);
    bit [31:0] vis;
    bit reached;
    tb_vif.gpio_ext_drive_value[IsolatePad] <= level;
    tb_vif.gpio_ext_drive_en[IsolatePad] <= 1'b1;
    for (int unsigned poll = 0; poll < PinBound; poll++) begin
      csr_read(VisAddr, vis, "isolation pin synchronization");
      pin_polls++;
      reached = ((vis & RESET_UNIT_ISOLATE_REQ_VIS_ISOLATE_REQ_PIN_MASK) != 0) == level;
      if (reached) break;
      wait_smc_cycles(1);
    end
    require_value(ChkSetup, reached, $sformatf("pin=%b VIS=%h polls=%0d", level, vis, pin_polls));
  endtask

  protected task read_entry(entry_t entry, bit narrow, output bit [31:0] value,
                            output bit [31:0] neighbor);
    bit [63:0] beat;
    ocah_axi_item result;
    neighbor = 0;
    if (narrow) begin
      smc_axi_csr_read_seq op = smc_axi_csr_read_seq::type_id::create("entry_read");
      op.addr = entry.addr;
      op.start(p_sequencer.m_sep_in_seqr);
      csr_accesses++;
      result = op.result;
      value = op.data;
      check_response(ChkCsrResp, result, entry.name);
    end else begin
      smc_axi_mem_read_seq op = smc_axi_mem_read_seq::type_id::create("entry_read");
      op.addr = smc_mem_word_addr(entry.addr);
      op.start(p_sequencer.m_sep_in_seqr);
      mem_accesses++;
      result = op.result;
      beat = op.data;
      check_response(ChkMemResp, result, entry.name);
      value = smc_csr_from_bus(entry.addr, beat);
      neighbor = 32'(beat >> (entry.addr[2] ? 0 : 32));
    end
    require_value(ChkSetup,
                  result.data_words.size() == 1 && result.data_xz_masks.size() == 1 &&
                  (narrow ? smc_csr_from_bus(
                  entry.addr, result.first_xz_mask()) == 0 : result.first_xz_mask() == 0),
                  $sformatf("%s known readback xz_mask=%016h", entry.name, result.first_xz_mask()));
  endtask

  protected task issue_write(entry_t entry, bit narrow, bit [31:0] data, bit [31:0] neighbor,
                             bit [3:0] strb);
    ocah_axi_item result;
    int unsigned aw_before = aw_count, w_before = w_count, b_before = b_count;
    bit [63:0] addr = narrow ? smc_csr_word_addr(entry.addr) : smc_mem_word_addr(entry.addr);
    bit [63:0] expected_data = smc_csr_to_bus(entry.addr, data);
    bit [31:0] neighbor_data = ~neighbor;
    bit [7:0] expected_strb = 8'(strb) << smc_csr_lane(entry.addr);
    if (!narrow) expected_data |= 64'(neighbor_data) << (entry.addr[2] ? 0 : 32);
    if (narrow) begin
      smc_extreg_csr_strobe_write_seq op = smc_extreg_csr_strobe_write_seq::type_id::create("op");
      op.addr = entry.addr;
      op.data = data;
      op.strb = strb;
      op.start(p_sequencer.m_sep_in_seqr);
      result = op.result;
      csr_accesses++;
    end else begin
      smc_axi_mem_write_seq op = smc_axi_mem_write_seq::type_id::create("op");
      op.addr = addr;
      op.data = expected_data;
      op.strb = expected_strb;
      op.check_response = 0;
      op.allow_timeout = 1;
      op.start(p_sequencer.m_sep_in_seqr);
      result = op.result;
      mem_accesses++;
    end
    uvm_wait_for_nba_region();
    require_value(ChkStimulus,
                  aw_count == aw_before + 1 && w_count == w_before + 1 &&
                  b_count == b_before + 1 && aw_addr === addr &&
                  aw_size === 3'(narrow ? SmcCsrSize : SmcMemSize) && aw_len === 0 &&
                  w_last === 1'b1 && w_data === expected_data && w_strb === expected_strb &&
                  !$isunknown(
                  {aw_id, b_id, b_resp}
                  ) && b_id == aw_id && result.observed_id_valid && result.observed_id == aw_id &&
                      !result.timed_out && result.resp_list.size() == 1 && !result.any_resp_xz(),
                  $sformatf(
                  {
                    "%s AW=%h size=%0d len=%0d W=%h strb=%h last=%b BID=%h AWID=%h ",
                    "BRESP=%b timeout=%b counts=%0d/%0d/%0d expected_W=%h expected_strb=%h"
                  },
                  entry.name,
                  aw_addr,
                  aw_size,
                  aw_len,
                  w_data,
                  w_strb,
                  w_last,
                  b_id,
                  aw_id,
                  b_resp,
                  result.timed_out,
                  aw_count - aw_before,
                  w_count - w_before,
                  b_count - b_before,
                  expected_data,
                  expected_strb
                  ));
    if (strb != 0) begin
      check_response(narrow ? ChkCsrResp : ChkMemResp, result, entry.name);
    end else begin
      `uvm_info(get_type_name(), $sformatf(
                "OBS-EXTREG-NULL-RESP seed=%0d addr=%h BRESP=%s",
                scenario_seed,
                entry.addr,
                result.worst_resp().name()
                ), UVM_LOW)
    end
  endtask

  protected task effect(bit [31:0] expected, bit inject, string label);
    bit reached, stable = 1;
    for (int unsigned cycle = 0; cycle < SourceBound; cycle++) begin
      reached = tb_vif.isolate_req === expected;
      if (reached) break;
      wait_smc_cycles(1);
    end
    repeat (StableSamples) begin
      @(negedge tb_vif.clk_smc);
      stable &= tb_vif.isolate_req === expected;
    end
    check_evidence(ChkEffect, label, 64'(reached && stable), 64'(!inject), $sformatf(
                   "expected=%h observed=%h reached=%b stable=%b",
                   expected,
                   tb_vif.isolate_req,
                   reached,
                   stable
                   ));
  endtask

  task body();
    entry_t entries[$];
    bit [3:0] partials[8] = '{4'h3, 4'h6, 4'hC, 4'h7, 4'hB, 4'hD, 4'hE, 4'h9};
    bit [3:0] lane_seen[Words];
    int unsigned cool_before;
    bit [31:0] value, neighbor, shadow, expected, baseline_neighbor, vis;
    logic [smc_pkg::NumGpioWraps-1:0] saved_drive_en, saved_drive_value;
    seed_scenario_rng();
    attach_evidence('{ChkLane, ChkNull, ChkNeighbor, ChkVis, ChkEffect, ChkIdle, ChkStimulus,
                    ChkSetup, ChkNonvac, ChkMemResp, ChkCsrResp, ChkFuseSense});
    negative = env_cfg.extreg_lane_sequence_negative;
    if (negative)
      `uvm_info(get_type_name(), "NEGATIVE VALIDATION: external register lane expectations",
                UVM_LOW)
    wait_fuse_sense_done();
    if (!uvm_config_db#(virtual ocah_axi_if)::get(null, "", "sep_in_axi_vif", vif))
      `uvm_fatal(get_type_name(), "SEP_IN passive interface missing")
    catalog(entries);
    require_value(ChkSetup, entries.size() == Words && IsolatePad < smc_pkg::NumGpioWraps,
                  "catalog and GPIO geometry");
    saved_drive_en = tb_vif.gpio_ext_drive_en;
    saved_drive_value = tb_vif.gpio_ext_drive_value;
    require_value(ChkSetup, saved_drive_en[IsolatePad] === 1'b0, "isolation pad unowned");
    cool_before = tb_vif.cool_rst_assert_count;
    csr_read(FlrAddr, value, "FLR idle baseline");
    require_value(ChkSetup, value == 0, "FLR latch idle");
    csr_read(LockAddr, value, "SS_CONFIG lock baseline");
    require_value(ChkSetup, value == RESET_UNIT_SS_CONFIG_LOCK_REG_DEFAULT, "SS_CONFIG unlocked");
    set_pin(0);
    // PINEN clears during cold reset only when the synchronized pin is low.
    csr_write(entries[1].addr, entries[1].reset_value, "PINEN explicit initialization");
    csr_read_check(ChkSetup, entries[1].addr, entries[1].reset_value, "PINEN initialized baseline");
    require_value(ChkSetup, tb_vif.isolate_req === 32'b0, "isolation initially idle");
    fork
      watch();
    join_none
    for (int unsigned cycle = 0; cycle < SourceBound && !watch_ready; cycle++) begin
      wait_smc_cycles(1);
    end
    require_value(ChkSetup, watch_ready, "sampler ready");
    foreach (entries[i]) begin
      bit [3:0] strobes[WritesPerWord] = '{4'h1, 4'h2, 4'h4, 4'h8, 4'h5, 4'hA, 0, 0};
      strobes[6] = partials[random_pattern(3)];
      read_entry(entries[i], i == Words - 1, shadow, baseline_neighbor);
      require_value(ChkSetup, shadow == entries[i].reset_value, {entries[i].name, " baseline"});
      if (i < 4) require_value(ChkSetup, baseline_neighbor == 0, "neighbor baseline");
      if (i == 4) require_value(ChkSetup, (baseline_neighbor & VisMask) == VisIdle, "VIS baseline");
      if (i == 1) set_pin(1);
      if (i >= 2) begin
        idle_bad = tb_vif.isolate_req !== 32'b0;
        idle_first_bad = tb_vif.isolate_req;
        idle_en = 1;
      end
      foreach (strobes[k]) begin
        bit [31:0] data = ~shadow;
        shadow = (shadow & ~lane_mask(strobes[k])) | (data & lane_mask(strobes[k]));
        issue_write(entries[i], i == Words - 1, data, baseline_neighbor, strobes[k]);
        read_entry(entries[i], i == Words - 1, value, neighbor);
        expected = shadow;
        if (negative && i == 0 && (k == 0 || k == WritesPerWord - 1)) expected ^= 32'h1;
        check_evidence(strobes[k] == 0 ? ChkNull : ChkLane, entries[i].name, value, expected,
                       $sformatf("strb=%h data=%h", strobes[k], data));
        if (i < 3) begin
          check_evidence(
              ChkNeighbor, entries[i].name, neighbor,
              negative && i == 1 && k == 0 ? baseline_neighbor ^ 32'h1 : baseline_neighbor);
        end
        if (i == 4) begin
          bit [31:0] expected_vis = VisIdle;
          if (negative && k == 0) expected_vis ^= RESET_UNIT_ISOLATE_REQ_VIS_ISOLATE_REQ_PIN_MASK;
          check_evidence(ChkVis, "VIS stays idle", neighbor & VisMask, expected_vis);
        end
        if (value == shadow) lane_seen[i] |= strobes[k];
        if (i < 2) effect(shadow, negative && i == 0 && k == 0, entries[i].name);
      end
      csr_write(entries[i].addr, entries[i].reset_value, "external register restore");
      csr_read(entries[i].addr, value, "external register restore readback");
      require_value(ChkSetup, value == entries[i].reset_value, "restored target");
      if (i < 2) begin
        int unsigned other = 1 - i;
        csr_write(entries[other].addr, entries[other].reset_value, "RW neighbor restore");
        csr_read(entries[other].addr, value, "RW neighbor restore readback");
        require_value(ChkSetup, value == entries[other].reset_value, "restored neighbor");
      end
      if (i == 1) set_pin(0);
      require_value(ChkSetup, tb_vif.isolate_req === 32'b0, "restored isolation output");
      if (i >= 2) begin
        if (tb_vif.isolate_req !== 32'b0) idle_bad = 1;
        idle_en = 0;
        check_evidence(ChkIdle, entries[i].name, 64'(!idle_bad), 64'(!(negative && i == 3)),
                       $sformatf("first_bad=%h final=%h", idle_first_bad, tb_vif.isolate_req));
      end
    end
    csr_read(FlrAddr, value, "FLR idle final");
    require_value(ChkSetup, value == 0, "FLR latch stays idle");
    csr_read(VisAddr, vis, "cool reset released final");
    require_value(ChkSetup,
                  (vis & VisMask) == VisIdle && tb_vif.cool_rst_assert_count == cool_before,
                  "no cool reset during lane test");
    tb_vif.gpio_ext_drive_en <= saved_drive_en;
    tb_vif.gpio_ext_drive_value <= saved_drive_value;
    watch_stop = 1;
    for (int unsigned cycle = 0; cycle < SourceBound && !watch_done; cycle++) begin
      wait_smc_cycles(1);
    end
    require_value(ChkSetup, watch_done, "sampler stopped");
    require_value(ChkSetup,
                  tb_vif.gpio_ext_drive_en === saved_drive_en &&
                  tb_vif.gpio_ext_drive_value === saved_drive_value,
                  "GPIO drive restored");
    check_evidence(ChkNonvac, "memory helper accesses", mem_accesses, MemAccessesPerPass);
    check_evidence(ChkNonvac, "CSR helper accesses", csr_accesses, FixedCsrAccesses + pin_polls);
    foreach (lane_seen[i]) begin
      check_evidence(ChkNonvac, entries[i].name, lane_seen[i], 4'hF);
    end
    finalize_evidence();
  endtask
endclass : smc_external_reg_lane_test_seq
