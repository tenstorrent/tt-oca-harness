// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC SPM memory reference model: the spm_mem predictor of smc_scoreboard. It
// subscribes to the SEP_IN monitor stream and keeps a shadow of the SPM
// window, keyed by 64-bit word address and rebuilt byte by byte from the
// strobed writes it observes; for every OKAY single-beat read inside the
// window it publishes one expected ocah_axi_item with the predicted word.
//
// A SHADOW PER WORD ADDRESS IS THE WHOLE POINT. The scenario writes several
// window edges before reading any of them back, so if two "distinct" edge
// addresses decoded onto one physical location the second write would
// overwrite the first and this model -- which keeps them apart -- would
// disagree with the read. A model that predicted per access instead of per
// address could not see that.
//
// An address read before anything wrote it predicts zero. That is NOT a claim
// about SRAM power-on content: nothing in this bench establishes it, and the
// scenarios write before they read, so the branch is unreachable there. It is
// deliberately a fail-loud default rather than "adopt whatever was observed",
// which would make the first read of every location a compare that cannot
// fail.
//
// The shadow is cleared on cold reset only to keep it from carrying state
// across a reset the bench sequenced; SPM contents themselves are not claimed
// to survive or clear.
//
// cfg.spm_mem_scoreboard_negative (+SMC_SPM_MEM_SCOREBOARD_NEGATIVE) is the
// documented negative-validation hook: the prediction is corrupted so the
// scoreboard must fail on the first SPM read. No comparison and no verdict
// live here. The cocotb twin is the expected-value half of
// seq_lib/smc_spm_mem_boundary_test_seq.py.

class smc_spm_mem_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_spm_mem_ref_model)

  smc_env_cfg cfg;
  // Handed by smc_env: the cold-reset counter the shadow re-baselines on.
  virtual smc_tb_if tb_vif;

  // Word shadow keyed by 8-byte-aligned address.
  protected bit [63:0] m_shadow[bit [63:0]];
  protected bit [31:0] m_cold_rst_seen;

  function new(string name = "smc_spm_mem_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual smc_tb_if `tb_vif` not set by the env")
    if (cfg.spm_mem_scoreboard_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: SPM word prediction corrupted (bit 0 inverted)", UVM_LOW)
  endfunction

  function void write(ocah_axi_item t);
    bit [63:0] word_addr;
    bit [63:0] shadow;
    sync_cold_reset();
    if (!smc_is_spm_mem_access(t)) return;
    word_addr = smc_mem_word_addr(t.address);
    shadow    = m_shadow.exists(word_addr) ? m_shadow[word_addr] : 64'h0;
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      m_shadow[word_addr] = apply_write(shadow, t);
      return;
    end
    expected_ap.write(expected_read(t, word_addr, shadow));
  endfunction

  protected function ocah_axi_item expected_read(ocah_axi_item t, bit [63:0] word_addr,
                                                 bit [63:0] value);
    ocah_axi_item e = ocah_axi_item::type_id::create("expected");
    if (cfg.spm_mem_scoreboard_negative) value ^= 64'h1;
    e.protocol       = t.protocol;
    e.direction      = OCAH_AXI_DIR_READ;
    e.address        = word_addr;
    e.size           = SmcMemSize;
    e.expected_beats = 1;
    e.source         = get_full_name();
    e.data_words.push_back(value);
    e.resp_list.push_back(OCAH_AXI_RESP_OKAY);
    return e;
  endfunction

  // Merge one strobed 64-bit beat into the word shadow, byte by byte.
  protected function bit [63:0] apply_write(bit [63:0] shadow, ocah_axi_item t);
    bit [7:0]  strb = (t.strobes.size() != 0) ? t.strobes[0] : 8'hFF;
    bit [63:0] next = shadow;
    for (int unsigned b = 0; b < SmcMemBytes; b++) begin
      if (strb[b]) next[8*b+:8] = t.data_words[0][8*b+:8];
    end
    return next;
  endfunction

  // Deliberately the cold counter alone, NOT smc_csr_reset_epoch: SPM is an
  // SRAM, and nothing in this bench establishes that a cool reset (or a cold
  // one) clears its contents. The clear here only keeps the shadow from
  // carrying state across a reset the bench sequenced.
  protected function void sync_cold_reset();
    if (tb_vif.cold_rst_assert_count !== m_cold_rst_seen) begin
      m_cold_rst_seen = tb_vif.cold_rst_assert_count;
      m_shadow.delete();
    end
  endfunction

endclass : smc_spm_mem_ref_model
