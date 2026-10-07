// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC default-register reference model: the default_reg predictor of
// smc_scoreboard. It subscribes to the SEP_IN monitor stream and keeps a
// shadow of every register in the smc_default_reg_catalog, seeded from that
// register's generated *_REG_DEFAULT and cleared back to the defaults on
// every cold reset (smc_tb_if cold_rst_assert_count). For every OKAY
// single-beat read of a catalogued register that carries a default contract
// it publishes one expected ocah_axi_item on expected_ap with the predicted
// value on the register's byte lanes; the scoreboard pairs it with the
// observed read.
//
// Two catalogue properties are modelled here:
//
//   * a `SMC_REG_KIND_RW_RESTORE` entry is software storage, so an observed
//     strobed write updates its shadow and later reads follow the write
//     across every scenario pass of one simulation;
//   * a `SMC_REG_KIND_RO_STATIC` entry is `sw=r` in the RDL, so a write never
//     changes what it reads back and the shadow ignores writes to it; a write
//     that lands on such a register is reported through the next read.
//
// A decode-only entry (`has_default == 0`) produces no expected item at all:
// its OKAY response and access count are the only evidence the bench claims,
// and the sequence records those.
//
// cfg.default_reg_scoreboard_negative (+SMC_DEFAULT_REG_SCOREBOARD_NEGATIVE)
// is the documented negative-validation hook: the prediction is corrupted so
// the scoreboard must fail on the first catalogued read. No comparison and no
// verdict live here. The cocotb twin is the catalogue half of
// seq_lib/smc_default_reg_rd_test_seq.py plus seq_lib/smc_csr_field_catalog.py.

class smc_default_reg_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_default_reg_ref_model)

  smc_env_cfg cfg;
  // Handed by smc_env: the cold-reset counter the shadow re-baselines on.
  virtual smc_tb_if tb_vif;

  // Register shadow keyed by 4-byte word address; an absent key means
  // "still at the catalogued default".
  protected bit [31:0] m_shadow[bit [63:0]];
  protected bit [63:0] m_rst_epoch_seen;

  function new(string name = "smc_default_reg_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual smc_tb_if `tb_vif` not set by the env")
    if (cfg.default_reg_scoreboard_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: default-register prediction corrupted (bit 0 inverted)",
                UVM_LOW)
  endfunction

  // One observed SEP_IN transaction: writes update the shadow of software
  // -owned registers, reads of a register with a default contract publish
  // their expected item.
  function void write(ocah_axi_item t);
    smc_default_reg_entry_t entry;
    bit [63:0]              word_addr;
    bit [31:0]              shadow;
    sync_cold_reset();
    if (!smc_is_default_reg_access(t, entry)) return;
    if (!entry.has_default) return;  // decode-only: no value contract
    word_addr = smc_csr_word_addr(t.address);
    shadow    = m_shadow.exists(word_addr) ? m_shadow[word_addr] : entry.default_value;
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      // `sw=r` registers cannot take a write; only software storage moves.
      if (entry.kind == SMC_REG_KIND_RW_RESTORE)
        m_shadow[word_addr] = apply_write(word_addr, shadow, t);
      return;
    end
    expected_ap.write(expected_read(t, word_addr, shadow));
  endfunction

  // The expected item of one catalogued read: the shadow value on the CSR
  // lanes of a single OKAY beat at the register's word address.
  protected function ocah_axi_item expected_read(ocah_axi_item t, bit [63:0] word_addr,
                                                 bit [31:0] value);
    ocah_axi_item e = ocah_axi_item::type_id::create("expected");
    if (cfg.default_reg_scoreboard_negative) value ^= 32'h1;
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

  // Merge one strobed write beat into the register shadow, lane by lane.
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

  // A cold reset -- or a de-glitched cool reset, which drops the same
  // rst_primary_smc_clk_n -- returns every catalogued register to its
  // default, so the shadow follows the tb_if reset epoch.
  protected function void sync_cold_reset();
    bit [63:0] epoch = smc_csr_reset_epoch(
        tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count
    );
    if (epoch !== m_rst_epoch_seen) begin
      m_rst_epoch_seen = epoch;
      m_shadow.delete();
    end
  endfunction

endclass : smc_default_reg_ref_model
