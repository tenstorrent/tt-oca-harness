// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Predicts selected side-effect-free register-block words from accepted
// SEP_IN writes and publishes an expected item for each subsequent read.

class smc_regblock_wide_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_regblock_wide_ref_model)

  smc_env_cfg cfg;
  virtual smc_tb_if tb_vif;
  protected bit [63:0] m_shadow[$];
  protected bit [63:0] m_rst_epoch_seen;

  function new(string name = "smc_regblock_wide_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual smc_tb_if `tb_vif` not set by env")
    reset_shadow();
  endfunction

  protected function bit enabled();
    foreach (cfg.required_features[i]) begin
      if (cfg.required_features[i] == SmcFeatureRegblockWide) return 1'b1;
    end
    return 1'b0;
  endfunction

  function void write(ocah_axi_item t);
    smc_regblock_wide_entry_t entry;
    int unsigned index;
    sync_reset();
    if (!enabled() || !smc_is_regblock_wide_access(t, entry, index)) return;
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      bit [7:0] strobes = (t.strobes.size() != 0) ? t.strobes[0] : 8'hFF;
      m_shadow[index] =
          smc_regblock_merge_write(m_shadow[index], t.data_words[0], strobes, entry.rw_mask);
      return;
    end
    if (t.direction == OCAH_AXI_DIR_READ) begin
      bit [63:0] expected_value = m_shadow[index];
      if (cfg.regblock_wide_scoreboard_negative) expected_value[0] = ~expected_value[0];
      expected_ap.write(expected_read(t, expected_value));
    end
  endfunction

  protected function ocah_axi_item expected_read(ocah_axi_item observed, bit [63:0] value);
    ocah_axi_item expected = ocah_axi_item::type_id::create("expected_regblock_wide_read");
    expected.protocol = observed.protocol;
    expected.direction = OCAH_AXI_DIR_READ;
    expected.address = observed.address;
    expected.size = SmcMemSize;
    expected.expected_beats = 1;
    expected.source = get_full_name();
    expected.data_words.push_back(value);
    expected.resp_list.push_back(OCAH_AXI_RESP_OKAY);
    return expected;
  endfunction

  protected function void reset_shadow();
    smc_regblock_wide_entry_t entries[$];
    smc_regblock_wide_catalog(entries);
    m_shadow.delete();
    foreach (entries[i]) m_shadow.push_back(entries[i].reset_value);
  endfunction

  protected function void sync_reset();
    bit [63:0] epoch = smc_csr_reset_epoch(
        tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count
    );
    if (epoch !== m_rst_epoch_seen) begin
      m_rst_epoch_seen = epoch;
      reset_shadow();
    end
  endfunction

endclass : smc_regblock_wide_ref_model
