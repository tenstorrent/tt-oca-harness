// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Sequential SEP_IN full-width accesses only; no other writer or in-flight reset.
// Read OKAY/error -> predict OKAY and shadow data. Write OKAY/error -> predict
// OKAY, updating shadow only for OKAY. Unsupported shapes/config writes stop
// a required feature rather than silently losing prediction state.
class smc_fabric_reg_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_fabric_reg_ref_model)
  smc_env_cfg cfg;
  virtual smc_tb_if tb_vif;
  protected smc_fabric_reg_entry_t entries[$];
  protected bit [63:0] shadow[SmcFabricRegWords];
  protected bit [63:0] end_shadow[2];
  protected bit [63:0] reset_epoch;
  protected bit ob_written, negative_used;

  function new(string name = "smc_fabric_reg_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || tb_vif == null)
      `uvm_fatal(get_type_name(), "env_cfg/tb_vif not set")
    smc_fabric_reg_catalog(entries);
    reset_shadow();
    if (cfg.fabric_reg_scoreboard_negative)
      `uvm_info(get_type_name(), "NEGATIVE VALIDATION: one fabric-register read corrupted per pass",
                UVM_LOW)
  endfunction

  function void start_pass();
    ob_written = 0;
    negative_used = 0;
  endfunction

  protected function void reset_shadow();
    foreach (shadow[i]) shadow[i] = entries[i].reset_value;
    foreach (end_shadow[i]) end_shadow[i] = FILTER_CTRL_END_ADDR_REG_DEFAULT;
    start_pass();
  endfunction

  function void write(ocah_axi_item t);
    int unsigned index;
    bit enabled = 0;
    bit [63:0] epoch;
    bit [63:0] word_addr = smc_mem_word_addr(t.address);
    ocah_axi_item expected;
    foreach (cfg.required_features[i]) begin
      if (cfg.required_features[i] == SmcFeatureFabricReg) enabled = 1;
    end
    if (!enabled) return;
    epoch = smc_csr_reset_epoch(tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count);
    if (epoch !== reset_epoch) begin
      reset_epoch = epoch;
      reset_shadow();
    end
    for (int unsigned i = 0; i < 2; i++) begin
      bit config_write = word_addr == smc_cg_filter_config(
          i == 1
      ) || word_addr == smc_cg_filter_end(
          i == 1
      );
      if (t.direction == OCAH_AXI_DIR_WRITE && config_write)
        `uvm_fatal(get_type_name(), "fabric_reg excludes filter CONFIG/END writes")
    end
    if (!smc_fabric_reg_lookup(word_addr, index)) return;
    if (!smc_is_fabric_reg_access(t, index))
      `uvm_fatal(get_type_name(), "fabric_reg requires aligned full-width single-beat accesses")
    expected = ocah_axi_item::type_id::create("expected");
    expected.protocol = t.protocol;
    expected.direction = t.direction;
    expected.address = t.address;
    expected.size = SmcMemSize;
    expected.expected_beats = 1;
    expected.source = get_full_name();
    expected.resp_list.push_back(OCAH_AXI_RESP_OKAY);
    if (t.direction == OCAH_AXI_DIR_READ) begin
      bit [63:0] value = shadow[index];
      if (cfg.fabric_reg_scoreboard_negative && index == 0 && ob_written && !negative_used) begin
        value ^= 64'h1;
        negative_used = 1;
      end
      expected.data_words.push_back(value);
    end else begin
      expected.data_words.push_back(t.first_data());
    end
    expected_ap.write(expected);
    if (t.direction != OCAH_AXI_DIR_WRITE || !t.is_ok()) return;
    shadow[index] = t.first_data() & entries[index].write_mask;
    if (index < 2) begin
      // The scenario holds allow_burst=0 and data_bus_width=3 (filter_ctrl.rdl).
      bit [63:0] granule = SmcMemBytes;
      if (shadow[index] / granule == end_shadow[index] / granule) begin
        shadow[index] &= ~(granule - 1);
        end_shadow[index] |= granule - 1;
      end
    end
    if (index == 0) ob_written = 1;
  endfunction
endclass : smc_fabric_reg_ref_model
