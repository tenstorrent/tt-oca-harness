// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Register-port wake/closure from clk_rst.adoc; word expectations from RDL.
// The taps describe activity/enables, not physical gated-clock edges.
class smc_fabric_reg_clock_gate_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_fabric_reg_clock_gate_test_seq)
  localparam string ChkConfig = "CHK-REG-CG-CONFIG";
  localparam string ChkOff = "CHK-REG-CG-OFF";
  localparam string ChkMap = "CHK-REG-CG-MAP";
  localparam string ChkClose = "CHK-REG-CG-CLOSE";
  localparam string ChkWake = "CHK-REG-CG-WAKE";
  localparam string ChkData = "CHK-REG-CG-DATA";
  localparam string ChkScope = "CHK-REG-CG-SCOPE";
  localparam string ChkScoreboard = "CHK-REG-CG-SCOREBOARD";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned IdleBound = 512;
  localparam int unsigned CloseWindow = 256;
  localparam int unsigned OpenWindow = 16;
  localparam int unsigned HystNominal = 8;
  // filter_ctrl.rdl: the largest supported address granule is 4 KiB.
  localparam bit [63:0] MaxFilterGranule = 4096;
  localparam int unsigned HystSticky =
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_CG_HYSTERESIS_MASK >>
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_CG_HYSTERESIS_SHIFT;
  localparam int unsigned SetGateCalls = 1 + 2 * 6 + 1 + 2 + 2;
  localparam int unsigned FixedCsrAccesses = 1 + 2 * SetGateCalls + 2;
  localparam int unsigned CatalogReads = 3 * SmcFabricRegWords + 2;
  localparam int unsigned CatalogWrites = 2 * SmcFabricRegWords;
  localparam int unsigned ComparisonsPerPass = CatalogReads + CatalogWrites;
  localparam int unsigned FixedMemAccesses = 1 + 2 * 2 +
      int'(smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_NUM) + ComparisonsPerPass;
  localparam bit [31:0] GateMask =
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_AXI_CG_EN_MASK |
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_REG_CG_EN_MASK |
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_IB_AXI_CG_EN_MASK |
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_IB_REG_CG_EN_MASK |
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_ADDR_REMAP_CG_EN_MASK |
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_OUTPUT_FABRIC_CG_EN_MASK;
  localparam bit [31:0] HystMask = SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_CG_HYSTERESIS_MASK;
  localparam int unsigned HystShift = SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_CG_HYSTERESIS_SHIFT;
  localparam bit [63:0] GateAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR;
  localparam bit [SmcFabricGaters-1:0] AllDomains = '1;
  localparam bit [SmcFabricGaters-1:0] RegisterDomains =
      (1 << SMC_CG_OB_FILTER) | (1 << SMC_CG_IB_FILTER) |
      (1 << SMC_CG_ALIAS_REMAP) | (1 << SMC_CG_MMODE_REMAP) | (1 << SMC_CG_XVISOR_REMAP);

  smc_fabric_reg_ref_model ref_model;
  protected smc_fabric_reg_entry_t entries[$];
  protected bit [31:0] baseline;
  protected bit negative;
  protected bit ready, stop_watch, stopped;
  protected int unsigned epoch_request, epoch_ack;
  protected int unsigned selected_domain;
  protected bit transaction_epoch, count_wake, epoch_wake_counted;
  protected longint unsigned cycle, epoch_start;
  protected logic [SmcFabricGaters-1:0] clocks, buses, initial_clocks;
  protected bit [SmcFabricGaters-1:0] busy_seen, active_seen, ref_valid, closed;
  protected bit [SmcFabricGaters-1:0] epoch_low;
  protected bit [SmcFabricGaters-1:0] ever_closed, ever_woke;
  protected longint unsigned idle_at[SmcFabricGaters], closed_at[SmcFabricGaters];
  protected int unsigned unknown_samples, busy_closed, wake_epochs;

  function new(string name = "smc_fabric_reg_clock_gate_test_seq");
    super.new(name);
  endfunction

  protected function void grade(string id, string label, bit condition, bit invert = 0,
                                string context_s = "");
    check_evidence(id, label, 64'(condition), 64'(!(negative && invert)), context_s);
  endfunction

  protected function void prerequisite(bit condition, string label);
    check_evidence(ChkConfig, label, 64'(condition), 1);
    if (!condition) `uvm_fatal(get_type_name(), label)
  endfunction

  protected task watch_gates();
    while (!stop_watch) begin
      @(negedge tb_vif.clk_smc);
      cycle++;
      clocks = tb_vif.cg_clk_active;
      buses  = tb_vif.cg_bus_active;
      if (epoch_ack != epoch_request) begin
        epoch_ack = epoch_request;
        epoch_start = cycle;
        initial_clocks = clocks;
        busy_seen = '0;
        active_seen = '0;
        ref_valid = '0;
        closed = '0;
        epoch_low = '0;
        epoch_wake_counted = 0;
      end
      ready = 1;
      if ($isunknown({clocks, buses})) unknown_samples++;
      for (int unsigned d = 0; d < SmcFabricGaters; d++) begin
        if (clocks[d] === 1'b0) begin
          ever_closed[d] = 1;
          epoch_low[d] = 1;
        end
        if (clocks[d] === 1'b1) active_seen[d] = 1;
        if (buses[d] === 1'b1) begin
          busy_seen[d] = 1;
          ref_valid[d] = 0;
          closed[d] = 0;
          if (clocks[d] === 1'b0) busy_closed++;
        end else if (buses[d] === 1'b0) begin
          if (!ref_valid[d]) begin
            ref_valid[d] = 1;
            idle_at[d]   = cycle;
          end
          if (!closed[d] && clocks[d] === 1'b0 &&
              (!transaction_epoch || d != selected_domain ||
               (busy_seen[d] && active_seen[d]))) begin
            closed[d] = 1;
            closed_at[d] = cycle;
          end
        end
      end
      if (transaction_epoch && initial_clocks[selected_domain] === 1'b0 &&
          busy_seen[selected_domain] && active_seen[selected_domain]) begin
        ever_woke[selected_domain] = 1;
        if (count_wake && !epoch_wake_counted) begin
          wake_epochs++;
          epoch_wake_counted = 1;
        end
      end
    end
    stopped = 1;
  endtask

  protected task begin_epoch(bit traffic = 0, int unsigned domain = 0, bit count_epoch = 0);
    // Requests change on the opposite edge from the passive sampler.
    @(posedge tb_vif.clk_smc);
    selected_domain = domain;
    transaction_epoch = traffic;
    count_wake = count_epoch;
    epoch_request++;
    for (int unsigned c = 0; c < OpenWindow; c++) begin
      @(posedge tb_vif.clk_smc);
      if (epoch_ack == epoch_request) return;
    end
    `uvm_fatal(get_type_name(), "Gate watcher did not acknowledge epoch")
  endtask

  protected task wait_closed(bit [SmcFabricGaters-1:0] mask, string label, bit invert = 0,
                             bit invert_idle = 0);
    bit complete = 0;
    while (cycle <= epoch_start + IdleBound + CloseWindow) begin
      if ((closed & mask) == mask) begin
        complete = 1;
        break;
      end
      @(posedge tb_vif.clk_smc);
    end
    for (int unsigned d = 0; d < SmcFabricGaters; d++) begin
      if (!mask[d]) continue;
      grade(ChkScope, {label, " bounded idle"},
            ref_valid[d] && idle_at[d] <= epoch_start + IdleBound, invert_idle);
      grade(ChkClose, {label, " bounded closure"},
            closed[d] && closed_at[d] <= idle_at[d] + CloseWindow, invert, $sformatf(
            "domain=%0d start=%0d idle=%0d close=%0d", d, epoch_start, idle_at[d], closed_at[d]));
      `uvm_info(get_type_name(), $sformatf(
                {
                  "OBS-REG-CG-CLOSE seed=%0d domain=%0d traffic=%0b ",
                  "t_start=%0d t_ref=%0d close=%0d delta=%0d"
                },
                scenario_seed,
                d,
                transaction_epoch,
                epoch_start,
                idle_at[d],
                closed_at[d],
                closed[d] ? longint'(closed_at[d] - idle_at[d]) : -1
                ), UVM_LOW)
    end
    if (!complete) `uvm_fatal(get_type_name(), "No closed gate available for next leg")
  endtask

  protected task wait_open(bit [SmcFabricGaters-1:0] mask, string label);
    bit opened = 0;
    for (int unsigned c = 0; c < OpenWindow; c++) begin
      @(posedge tb_vif.clk_smc);
      if ((clocks & mask) === mask) begin
        opened = 1;
        break;
      end
    end
    grade(ChkOff, label, opened);
    if (!opened) `uvm_fatal(get_type_name(), "Gate disable did not establish active baseline")
  endtask

  protected task set_gates(bit [31:0] enables, int unsigned hyst, bit invert_config = 0);
    bit [31:0] value = (baseline & ~(GateMask | HystMask)) |
                      enables | ((32'(hyst) << HystShift) & HystMask);
    bit [31:0] observed;
    csr_write(GateAddr, value, "fabric gate control");
    csr_read(GateAddr, observed, "fabric gate readback");
    check_evidence(ChkConfig, "gate configuration", observed,
                   negative && invert_config ? value ^ 32'h1 : value);
    if (observed != value) `uvm_fatal(get_type_name(), "Gate configuration did not apply")
  endtask

  protected function bit [SmcFabricGaters-1:0] domains_for(bit [31:0] enable);
    case (enable)
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_AXI_CG_EN_MASK:
      return 1 << SMC_CG_SYS_OUT_FILTER;
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_REG_CG_EN_MASK: return 1 << SMC_CG_OB_FILTER;
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_IB_AXI_CG_EN_MASK: return 1 << SMC_CG_SYS_IN_FILTER;
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_IB_REG_CG_EN_MASK: return 1 << SMC_CG_IB_FILTER;
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_ADDR_REMAP_CG_EN_MASK:
      return (1 << SMC_CG_ALIAS_REMAP) | (1 << SMC_CG_MMODE_REMAP) | (1 << SMC_CG_XVISOR_REMAP);
      SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_OUTPUT_FABRIC_CG_EN_MASK: return 1 << SMC_CG_FABRIC;
      default: return '0;
    endcase
  endfunction

  protected task cold_access(int unsigned index, bit write_op, bit [63:0] pattern);
    bit [63:0] observed;
    bit [SmcFabricGaters-1:0] mask = 1 << entries[index].domain;
    begin_epoch();
    wait_closed(mask, "before cold access");
    begin_epoch(1, entries[index].domain, 1);
    prerequisite(initial_clocks[entries[index].domain] === 1'b0, "cold request baseline");
    if (write_op) mem_write(entries[index].addr, pattern, entries[index].name);
    else begin
      mem_read(entries[index].addr, observed, entries[index].name);
      check_evidence(ChkData, "cold pattern readback", observed & entries[index].read_mask,
                     negative && index == 0 ? pattern ^ 64'h1 : pattern, entries[index].name);
    end
    wait_closed(mask, "after cold access", .invert_idle(index == 0 && write_op));
    grade(ChkWake, "closed request observed busy and active",
          initial_clocks[entries[index].domain] === 1'b0 &&
          busy_seen[entries[index].domain] && active_seen[entries[index].domain],
          index == 0 && write_op, entries[index].name);
  endtask

  task body();
    bit [63:0] value, config_value, end_value;
    bit [31:0] restored;
    int unsigned compare_before, mismatch_before;
    int unsigned order[$];
    bit [31:0] enables[6] = '{
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_AXI_CG_EN_MASK,
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_REG_CG_EN_MASK,
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_IB_AXI_CG_EN_MASK,
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_IB_REG_CG_EN_MASK,
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_ADDR_REMAP_CG_EN_MASK,
        SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_OUTPUT_FABRIC_CG_EN_MASK
    };
    seed_scenario_rng();
    attach_evidence('{ChkConfig, ChkOff, ChkMap, ChkClose, ChkWake, ChkData, ChkScope,
                    ChkScoreboard, ChkNonvac, ChkFuseSense, ChkCsrResp, ChkMemResp});
    negative = env_cfg.fabric_reg_cg_sequence_negative;
    if (negative)
      `uvm_info(get_type_name(), "NEGATIVE VALIDATION: seven gate-sequence expectations inverted",
                UVM_LOW)
    if (ref_model == null) `uvm_fatal(get_type_name(), "fabric_reg model not plumbed")
    ref_model.start_pass();
    compare_before  = scoreboard.compare_count(SmcFeatureFabricReg);
    mismatch_before = scoreboard.mismatch_count(SmcFeatureFabricReg);
    wait_fuse_sense_done();
    smc_fabric_reg_catalog(entries);
    csr_read(GateAddr, baseline, "gate baseline");
    prerequisite((baseline & GateMask) == 0, "fabric gates initially disabled");
    mem_read(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR, value,
             "output remap presence");
    prerequisite((value & CPU_CTRL_SMC_ATTRIBUTES_NO_OUTPUT_REMAP_MASK) == 0,
                 "output remap present");
    for (int unsigned i = 0; i < 2; i++) begin
      mem_read(smc_cg_filter_config(i == 1), config_value, "filter configuration baseline");
      mem_read(smc_cg_filter_end(i == 1), end_value, "filter END baseline");
      prerequisite(
          (config_value & (FILTER_CTRL_FILTER_CONFIG_LOCKED_MASK |
                   FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_MASK |
                   FILTER_CTRL_FILTER_CONFIG_ALLOW_BURST_MASK)) == 0 &&
                   (config_value & FILTER_CTRL_FILTER_CONFIG_DATA_BUS_WIDTH_MASK) ==
                   (FILTER_CTRL_FILTER_CONFIG_REG_DEFAULT &
                    FILTER_CTRL_FILTER_CONFIG_DATA_BUS_WIDTH_MASK) &&
                   end_value == FILTER_CTRL_END_ADDR_REG_DEFAULT,
          "filter baseline");
    end
    for (int unsigned i = 0; i < smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_NUM; i++) begin
      mem_read(smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR(i), value,
               "alias inactive prerequisite");
      prerequisite((value & REMAP_REGION_REGION_ATTRS_VALID_MASK) == 0, "alias region inactive");
    end
    foreach (entries[i]) begin
      mem_read(entries[i].addr, value, {entries[i].name, " baseline"});
      prerequisite((value & entries[i].read_mask) == entries[i].reset_value, {
                   entries[i].name, " reset baseline"});
      order.push_back(i);
    end
    fork
      watch_gates();
    join_none
    for (int unsigned c = 0; c < OpenWindow && !ready; c++) @(posedge tb_vif.clk_smc);
    prerequisite(ready, "watcher ready");
    begin_epoch();
    begin
      bit low_seen = 0;
      repeat (IdleBound) begin
        @(posedge tb_vif.clk_smc);
        low_seen |= clocks !== AllDomains;
      end
      grade(ChkOff, "disabled domains remain active", !low_seen, 1);
    end
    set_gates(0, HystNominal);
    foreach (enables[i]) begin
      bit [SmcFabricGaters-1:0] expected_domains = domains_for(enables[i]);
      begin_epoch();
      set_gates(enables[i], HystNominal, i == 0);
      wait_closed(expected_domains, "one-hot mapping");
      grade(ChkMap, "one-hot domain map",
            ((~clocks) === expected_domains) && epoch_low == expected_domains, i == 5, $sformatf(
            "enable=0x%0h closed=0x%0h epoch_low=0x%0h expected=0x%0h",
            enables[i],
            ~clocks,
            epoch_low,
            expected_domains
            ));
      set_gates(0, HystNominal);
      wait_open(AllDomains, "one-hot disabled again");
    end
    set_gates(GateMask, HystNominal);
    begin_epoch();
    wait_closed(AllDomains, "all domains");
    for (int unsigned i = order.size(); i > 1; i--) begin
      int unsigned j = int'(random_pattern(32) % i);
      int unsigned temp = order[i-1];
      order[i-1] = order[j];
      order[j]   = temp;
    end
    foreach (order[k]) begin
      int unsigned i = order[k];
      bit [63:0] pattern = random_pattern(64) & entries[i].write_mask;
      if (i >= 3) pattern &= ~OUTPUT_REMAP_REGION_REGION_ATTRS_VALID_MASK;
      if (i < 2) begin
        // Different 4-KiB granules avoid hardware range write-back (filter_ctrl.rdl).
        pattern &= ~(MaxFilterGranule - 1);
        if (pattern == 0) pattern = MaxFilterGranule;
      end
      if (pattern == entries[i].reset_value)
        pattern = entries[i].write_mask & (~entries[i].write_mask + 1);
      cold_access(i, 1, pattern);
      cold_access(i, 0, pattern);
      mem_write(entries[i].addr, entries[i].reset_value, "register restore");
      mem_read(entries[i].addr, value, "register restore readback");
      check_evidence(ChkData, "restored register", value & entries[i].read_mask,
                     entries[i].reset_value, entries[i].name);
      begin_epoch();
      wait_closed(1 << entries[i].domain, "after restore");
    end
    set_gates(GateMask & ~SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_REG_CG_EN_MASK, 0);
    set_gates(GateMask, 0);
    begin_epoch();
    wait_closed(1 << SMC_CG_OB_FILTER, "zero hysteresis before read");
    begin_epoch(1, SMC_CG_OB_FILTER);
    mem_read(entries[0].addr, value, "zero hysteresis read");
    wait_closed(1 << SMC_CG_OB_FILTER, "zero hysteresis after read", 1);
    set_gates(GateMask & ~SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_FILTER_OB_REG_CG_EN_MASK, HystSticky);
    set_gates(GateMask, HystSticky);
    begin_epoch();
    repeat (CloseWindow) @(posedge tb_vif.clk_smc);
    `uvm_info(get_type_name(),
              "OBS-BLOCKED CHK-REG-CG-STICKY reason=hysteresis 63 behavior is not documented",
              UVM_LOW)
    `uvm_info(get_type_name(),
              $sformatf("OBS-REG-CG-STICKY seed=%0d closed=%0b clk_active=%0b bus_active=%0b",
                        scenario_seed, closed[SMC_CG_OB_FILTER], clocks[SMC_CG_OB_FILTER],
                        buses[SMC_CG_OB_FILTER]), UVM_LOW)
    mem_read(entries[0].addr, value, "maximum hysteresis read");
    csr_write(GateAddr, baseline, "restore gate baseline");
    csr_read(GateAddr, restored, "gate restore readback");
    check_evidence(ChkConfig, "gate baseline restored", restored, baseline);
    wait_open(AllDomains, "all domains restored active");
    @(posedge tb_vif.clk_smc);
    stop_watch = 1;
    for (int unsigned c = 0; c < OpenWindow && !stopped; c++) @(posedge tb_vif.clk_smc);
    prerequisite(stopped, "watcher stopped");
    grade(ChkScope, "resolved activity taps", unknown_samples == 0);
    grade(ChkClose, "busy never accompanies disabled clock", busy_closed == 0);
    check_evidence(ChkNonvac, "domains observed closed", ever_closed, AllDomains);
    check_evidence(ChkNonvac, "register domains observed waking", ever_woke, RegisterDomains);
    check_evidence(ChkNonvac, "cold request epochs", wake_epochs, 2 * SmcFabricRegWords);
    check_evidence(ChkNonvac, "SEP_IN CSR accesses", csr_accesses, FixedCsrAccesses);
    check_evidence(ChkNonvac, "SEP_IN memory accesses", mem_accesses, FixedMemAccesses);
    for (int unsigned c = 0; c < IdleBound; c++) begin
      if (scoreboard.compare_count(SmcFeatureFabricReg) >= compare_before + ComparisonsPerPass)
        break;
      wait_smc_cycles(1);
    end
    check_evidence(ChkScoreboard, "catalogued comparisons", scoreboard.compare_count(
                   SmcFeatureFabricReg) - compare_before, ComparisonsPerPass);
    check_evidence(ChkScoreboard, "no new fabric_reg mismatch", scoreboard.mismatch_count(
                   SmcFeatureFabricReg), mismatch_before);
    finalize_evidence();
  endtask
endclass : smc_fabric_reg_clock_gate_test_seq
