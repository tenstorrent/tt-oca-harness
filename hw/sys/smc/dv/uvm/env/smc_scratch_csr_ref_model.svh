// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC scratch CSR reference model: the scratch_csr predictor of
// smc_scoreboard. It subscribes to the SEP_IN monitor stream and keeps a
// shadow of the SCRATCH_COLD and SCRATCH_COLD_WARM registers rebuilt from the
// strobed writes it observes, cleared on every cold reset (the warm domain
// sits inside the cold one; smc_tb_if cold_rst_assert_count). For every OKAY
// single-beat read of a scratch register it publishes one expected
// ocah_axi_item on expected_ap carrying the predicted CSR value on the
// register's byte lanes; the scoreboard pairs it with the observed read.
// Writes and accesses outside the scratch windows produce no expected item.
// cfg.csr_scoreboard_negative (+SMC_CSR_SCOREBOARD_NEGATIVE) is the
// documented negative-validation hook: the prediction is corrupted so the
// scoreboard must fail on the first scratch read. No comparison and no
// verdict live here. The cocotb twin is the SysAxi expected-value check of
// env/smc_scoreboard.py.

class smc_scratch_csr_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_scratch_csr_ref_model)

  smc_env_cfg cfg;
  // Handed by smc_env: the cold-reset counter the shadow re-baselines on.
  virtual smc_tb_if tb_vif;

  // CSR shadow keyed by 4-byte word address.
  protected bit [31:0] m_scratch_shadow[bit [63:0]];
  protected bit [31:0] m_cold_rst_seen;

  function new(string name = "smc_scratch_csr_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual smc_tb_if `tb_vif` not set by the env")
    if (cfg.csr_scoreboard_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: scratch readback prediction corrupted (bit 0 inverted)",
                UVM_LOW)
  endfunction

  // One observed SEP_IN transaction: writes update the shadow, reads of a
  // scratch register publish their expected item.
  function void write(ocah_axi_item t);
    bit        warm;
    bit [63:0] word_addr;
    bit [31:0] shadow;
    sync_cold_reset();
    if (!smc_is_scratch_csr_access(t, warm)) return;
    word_addr = smc_csr_word_addr(t.address);
    shadow    = m_scratch_shadow.exists(word_addr) ? m_scratch_shadow[word_addr] : '0;
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      m_scratch_shadow[word_addr] = apply_write(word_addr, shadow, t);
      return;
    end
    expected_ap.write(expected_read(t, word_addr, shadow));
  endfunction

  // The expected item of one scratch read: the shadow value on the CSR
  // lanes of a single OKAY beat at the register's word address.
  protected function ocah_axi_item expected_read(ocah_axi_item t, bit [63:0] word_addr,
                                                 bit [31:0] value);
    ocah_axi_item e = ocah_axi_item::type_id::create("expected");
    if (cfg.csr_scoreboard_negative) value ^= 32'h1;
    e.protocol       = t.protocol;
    e.direction      = OCAH_AXI_DIR_READ;
    e.address        = word_addr;
    e.size           = SmcCsrSize;
    e.expected_beats = 1;
    e.source         = get_full_name();
    e.data_words.push_back(smc_csr_to_bus(word_addr, value));
    e.resp_list.push_back(OCAH_AXI_RESP_OKAY);
    return e;
  endfunction

  // Merge one strobed write beat into the CSR shadow, lane by lane.
  protected function bit [31:0] apply_write(bit [63:0] word_addr, bit [31:0] shadow,
                                            ocah_axi_item t);
    bit [7:0]    strb = (t.strobes.size() != 0) ? t.strobes[0] : 8'hFF;
    int unsigned lane = smc_csr_lane(word_addr);
    bit [31:0]   next = shadow;
    for (int unsigned b = 0; b < SmcCsrBytes; b++) begin
      if (strb[lane+b]) next[8*b+:8] = t.data_words[0][8*(lane+b)+:8];
    end
    return next;
  endfunction

  // A cold reset clears every scratch register, so the shadow follows the
  // tb_if counter.
  protected function void sync_cold_reset();
    if (tb_vif.cold_rst_assert_count !== m_cold_rst_seen) begin
      m_cold_rst_seen = tb_vif.cold_rst_assert_count;
      m_scratch_shadow.delete();
    end
  endfunction

endclass : smc_scratch_csr_ref_model
