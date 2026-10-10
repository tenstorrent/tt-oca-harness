// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Predicts watchdog configuration and lock state from sequential SEP_IN traffic.
// COUNT and IP timing remain outside this model. No other watchdog writer or
// software uncore reset is supported; reset with outstanding traffic is excluded.

class smc_wdt_csr_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_wdt_csr_ref_model)
  localparam bit [31:0] CtrlByte1Fields = WDT_CTRL_WDOGRSTEN_MASK |
      WDT_CTRL_WDOGZEROCMP_MASK | WDT_CTRL_WDOGENALWAYS_MASK | WDT_CTRL_WDOGCOREAWAKE_MASK;
  smc_env_cfg cfg;
  virtual smc_tb_if tb_vif;
  protected bit unlocked[SmcWdtCores];
  protected bit [31:0] control[SmcWdtCores];
  protected bit [31:0] compare_value[SmcWdtCores];
  protected int unsigned reset_epoch;
  protected int unsigned seen_epoch;

  function new(string name = "smc_wdt_csr_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg not found")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "smc_tb_if not set")
    reset_shadow();
    if (cfg.wdt_csr_scoreboard_negative)
      `uvm_info(
          get_type_name(),
          "NEGATIVE VALIDATION: watchdog read predictions corrupted and writes predict SLVERR",
          UVM_LOW)
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      @(negedge tb_vif.rst_warm_smc_clk_n);
      reset_epoch++;
    end
  endtask

  protected function void reset_shadow();
    foreach (control[i]) begin
      unlocked[i] = 1'b0;
      control[i] = 32'(WDT_CTRL_REG_DEFAULT);
      compare_value[i] = 32'(WDT_CMP_REG_DEFAULT) & WDT_CMP_WDOGCMP0_MASK;
    end
  endfunction

  function void write(ocah_axi_item t);
    int unsigned core, offset;
    bit enabled = 1'b0;
    bit [31:0] value = '0;
    ocah_axi_item expected;
    foreach (cfg.required_features[i]) begin
      if (cfg.required_features[i] == SmcFeatureWdtCsr) enabled = 1'b1;
    end
    if (!enabled || !smc_is_wdt_csr_access(t, core, offset)) return;
    if (seen_epoch != reset_epoch) begin
      seen_epoch = reset_epoch;
      reset_shadow();
    end
    if (t.direction == OCAH_AXI_DIR_READ) begin
      case (offset)
        SmcWdtCtrlOffset: value = control[core];
        SmcWdtKeyOffset: value = 32'(unlocked[core]);
        SmcWdtCmpOffset: value = compare_value[core];
        default: value = '0;
      endcase
      if (cfg.wdt_csr_scoreboard_negative && smc_wdt_csr_mask(offset) != 0) value ^= 32'h1;
    end
    expected = ocah_axi_item::type_id::create("expected");
    expected.protocol = t.protocol;
    expected.direction = t.direction;
    expected.address = smc_csr_word_addr(t.address);
    expected.size = t.size;
    expected.expected_beats = 1;
    expected.source = get_full_name();
    expected.data_words.push_back(
        t.direction == OCAH_AXI_DIR_WRITE ? t.data_words[0] : smc_csr_to_bus(expected.address, value
        ));
    expected.resp_list.push_back(
        cfg.wdt_csr_scoreboard_negative && t.direction == OCAH_AXI_DIR_WRITE ?
        OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_OKAY);
    expected_ap.write(expected);
    if (t.direction == OCAH_AXI_DIR_WRITE && t.is_ok()) apply_write(core, offset, t);
  endfunction

  protected function void apply_write(int unsigned core, int unsigned offset, ocah_axi_item t);
    bit [7:0] lanes = t.strobes.size() != 0 ? t.strobes[0] : 8'hFF;
    bit [63:0] data = t.data_words[0];
    int unsigned beat_offset = offset & ~(SmcMemBytes - 1);
    bit key_write = beat_offset == (SmcWdtKeyOffset & ~(SmcMemBytes - 1)) &&
                     lanes[SmcWdtKeyOffset % SmcMemBytes +: SmcCsrBytes] == 4'hF;
    bit write_any = 1'b0;
    case (beat_offset)
      SmcWdtCtrlOffset: begin
        write_any = |lanes[3:0];
        if (unlocked[core]) begin
          if (lanes[0])
            control[core] = (control[core] & ~WDT_CTRL_WDOGSCALE_MASK) |
                            (data[31:0] & WDT_CTRL_WDOGSCALE_MASK);
          if (lanes[1])
            control[core] = (control[core] & ~CtrlByte1Fields) | (data[31:0] & CtrlByte1Fields);
        end
      end
      SmcWdtCountOffset: write_any = lanes[3:0] == 4'hF || lanes[7:4] == 4'hF;
      SmcWdtScaledCountOffset: write_any = lanes[1:0] == 2'b11;
      SmcWdtFeedOffset: write_any = lanes[3:0] == 4'hF;
      SmcWdtCmpOffset: begin
        write_any = lanes[1:0] == 2'b11;
        if (unlocked[core] && write_any)
          compare_value[core] = data[31:0] & WDT_CMP_WDOGCMP0_MASK;
      end
      default: write_any = 1'b0;
    endcase
    if (key_write || write_any)
      unlocked[core] = key_write &&
                        data[8 * (SmcWdtKeyOffset % SmcMemBytes) +: 8 * SmcCsrBytes] ==
                        SmcWdtMagicKey && !write_any;
  endfunction
endclass : smc_wdt_csr_ref_model
