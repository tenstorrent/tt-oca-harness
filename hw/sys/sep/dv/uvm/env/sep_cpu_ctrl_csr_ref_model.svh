// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP CPU-control CSR reference model: the cpu_ctrl_csr predictor of
// sep_scoreboard. It subscribes to the CPU-LSU monitor stream and keeps a
// shadow of the predicted sep_cpu_ctrl registers (sep_cpu_ctrl_csr_regs)
// rebuilt from the strobed writes it observes, each register at its
// generated reset value until written and again after every primary reset
// (sep_tb_if rst_assert_count). For every OKAY single-beat read of a
// predicted register it publishes one expected ocah_axi_item on
// expected_ap carrying the predicted CSR value on the register's byte
// lanes; the scoreboard pairs it with the observed read. Writes and
// accesses outside the predicted set produce no expected item.
// cfg.csr_scoreboard_negative (+SEP_CSR_SCOREBOARD_NEGATIVE) is the
// documented negative-validation hook: the prediction is corrupted so the
// scoreboard must fail on the first predicted read. No comparison and no
// verdict live here. The cocotb twin is the expected-value check of
// cocotb/env/sep_scoreboard.py.

class sep_cpu_ctrl_csr_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(sep_cpu_ctrl_csr_ref_model)

  sep_env_cfg cfg;
  // Handed by sep_env: the reset counter the shadow re-baselines on.
  virtual sep_tb_if tb_vif;

  // CSR shadow keyed by word address; an absent key reads the reset value.
  protected bit [31:0] m_csr_shadow[bit [63:0]];
  protected bit [31:0] m_rst_seen;

  function new(string name = "sep_cpu_ctrl_csr_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(sep_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "sep_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual sep_tb_if `tb_vif` not set by the env")
    if (cfg.csr_scoreboard_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: CSR readback prediction corrupted (bit 0 inverted)", UVM_LOW)
  endfunction

  // One observed CPU-LSU transaction: writes update the shadow, reads of a
  // predicted register publish their expected item.
  function void write(ocah_axi_item t);
    sep_csr_desc_t desc;
    bit [31:0]     shadow;
    sync_reset();
    if (!sep_is_cpu_ctrl_csr_access(t, desc)) return;
    shadow = m_csr_shadow.exists(desc.addr) ? m_csr_shadow[desc.addr] : desc.reset_value;
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      m_csr_shadow[desc.addr] = apply_write(desc, shadow, t);
      return;
    end
    expected_ap.write(expected_read(t, desc, shadow));
  endfunction

  // The expected item of one predicted read: the shadow value on the CSR
  // lanes of a single OKAY beat at the register's word address.
  protected function ocah_axi_item expected_read(ocah_axi_item t, sep_csr_desc_t desc,
                                                 bit [31:0] value);
    ocah_axi_item e = ocah_axi_item::type_id::create("expected");
    if (cfg.csr_scoreboard_negative) value ^= 32'h1;
    e.protocol       = t.protocol;
    e.direction      = OCAH_AXI_DIR_READ;
    e.address        = desc.addr;
    e.size           = SepCsrSize;
    e.expected_beats = 1;
    e.source         = get_full_name();
    e.data_words.push_back(sep_csr_to_bus(desc.addr, value));
    e.resp_list.push_back(OCAH_AXI_RESP_OKAY);
    return e;
  endfunction

  // Merge one strobed write beat into the CSR shadow, lane by lane, keeping
  // the implemented field bits: reserved and absent bits read back as zero.
  protected function bit [31:0] apply_write(sep_csr_desc_t desc, bit [31:0] shadow,
                                            ocah_axi_item t);
    bit [7:0]    strb = (t.strobes.size() != 0) ? t.strobes[0] : 8'hFF;
    int unsigned lane = sep_csr_lane(desc.addr);
    bit [31:0]   next = shadow;
    for (int unsigned b = 0; b < SepCsrBytes; b++) begin
      if (strb[lane+b]) next[8*b+:8] = t.data_words[0][8*(lane+b)+:8];
    end
    return next & desc.mask;
  endfunction

  // A primary reset returns every register to its reset value, so the
  // shadow follows the tb_if counter.
  protected function void sync_reset();
    if (tb_vif.rst_assert_count !== m_rst_seen) begin
      m_rst_seen = tb_vif.rst_assert_count;
      m_csr_shadow.delete();
    end
  endfunction

endclass : sep_cpu_ctrl_csr_ref_model
