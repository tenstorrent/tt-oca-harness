// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC lock-CSR reference model: the lock_csr predictor of smc_scoreboard. It
// subscribes to the SEP_IN monitor stream and keeps, per smc_lock_pairs entry,
// a shadow of the write-once lock register and a shadow of the register that
// lock guards, both rebuilt from the writes it observes and both cleared on
// cold reset (smc_tb_if cold_rst_assert_count). For every OKAY single-beat
// read of either register it publishes one expected ocah_axi_item carrying
// the predicted value on the register's byte lanes.
//
// The two RDL/RTL rules being modelled -- and therefore independently
// asserted, rather than restated by the sequence that drove them:
//
//   lock register   `onwrite = woset`: a written 1 sets a bit and a written 0
//                   does nothing, so the shadow only ever ORs in what it sees.
//                   Software cannot release a lock it has taken.
//   guarded register the lock filters the write bit-enables before they reach
//                   the storage flop (smc_subsystem_resets.sv:81 / :100), so
//                   the shadow applies a write only to the bits that are both
//                   strobed and unlocked and keeps the rest.
//
// Because the prediction is rebuilt from observed traffic, it stays correct
// across the 16 scenario passes of one simulation even though `woset` makes
// each pass leave one more bit permanently locked.
//
// cfg.lock_scoreboard_negative (+SMC_LOCK_SCOREBOARD_NEGATIVE) is the
// documented negative-validation hook: the prediction is corrupted so the
// scoreboard must fail on the first lock-pair read. No comparison and no
// verdict live here. The cocotb twin is the value-checked half of
// seq_lib/smc_reset_unit_lock_test_seq.py.

class smc_lock_csr_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_lock_csr_ref_model)

  smc_env_cfg cfg;
  // Handed by smc_env: the cold-reset counter the shadows re-baseline on.
  virtual smc_tb_if tb_vif;

  // Per-pair shadows; index matches smc_lock_pairs order. Both registers of
  // a pair reset to zero (reset_unit.rdl reset 0; the guarded flops clear to
  // '0 on rst_primary_ni).
  protected bit [31:0] m_lock[$];
  protected bit [31:0] m_target[$];
  protected bit [63:0] m_rst_epoch_seen;

  function new(string name = "smc_lock_csr_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    smc_lock_pair_t pairs[$];
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual smc_tb_if `tb_vif` not set by the env")
    smc_lock_pairs(pairs);
    foreach (pairs[i]) begin
      m_lock.push_back(32'h0);
      m_target.push_back(32'h0);
    end
    if (cfg.lock_scoreboard_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: lock-pair prediction corrupted (bit 0 inverted)", UVM_LOW)
  endfunction

  // One observed SEP_IN transaction on a lock pair.
  function void write(ocah_axi_item t);
    int unsigned pair_idx;
    bit          is_lock;
    bit [63:0]   word_addr;
    bit [31:0]   value;
    sync_cold_reset();
    if (!smc_is_lock_csr_access(t, pair_idx, is_lock)) return;
    word_addr = smc_csr_word_addr(t.address);
    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      apply_write(pair_idx, is_lock, word_addr, t);
      return;
    end
    value = is_lock ? m_lock[pair_idx] : m_target[pair_idx];
    expected_ap.write(expected_read(t, word_addr, value));
  endfunction

  // woset on the lock; lock-filtered bit-enables on the guarded register.
  protected function void apply_write(int unsigned pair_idx, bit is_lock, bit [63:0] word_addr,
                                      ocah_axi_item t);
    bit [31:0] wdata = smc_csr_from_bus(word_addr, t.data_words[0]);
    bit [31:0] biten = strobe_bits(word_addr, t);
    bit [31:0] filtered;
    if (is_lock) begin
      // A written 1 sets; a written 0 is inert. Only strobed bytes count.
      m_lock[pair_idx] = m_lock[pair_idx] | (wdata & biten);
      return;
    end
    filtered = biten & ~m_lock[pair_idx];
    m_target[pair_idx] = (wdata & filtered) | (m_target[pair_idx] & ~filtered);
  endfunction

  // The 32 write bit-enables of one CSR write, from the beat's byte strobes.
  protected function bit [31:0] strobe_bits(bit [63:0] word_addr, ocah_axi_item t);
    bit [7:0]    strb = (t.strobes.size() != 0) ? t.strobes[0] : 8'hFF;
    int unsigned lane = smc_csr_lane(word_addr);
    bit [31:0]   biten = 32'h0;
    for (int unsigned b = 0; b < SmcCsrBytes; b++) begin
      if (strb[lane+b]) biten[8*b+:8] = 8'hFF;
    end
    return biten;
  endfunction

  protected function ocah_axi_item expected_read(ocah_axi_item t, bit [63:0] word_addr,
                                                 bit [31:0] value);
    ocah_axi_item e = ocah_axi_item::type_id::create("expected");
    if (cfg.lock_scoreboard_negative) value ^= 32'h1;
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

  // Both guarded flops and the lock registers sit under
  // rst_primary_smc_clk_n, which a cold reset AND a de-glitched cool reset
  // drop, so the shadows follow the tb_if reset epoch rather than the cold
  // counter alone.
  protected function void sync_cold_reset();
    bit [63:0] epoch = smc_csr_reset_epoch(
        tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count
    );
    if (epoch !== m_rst_epoch_seen) begin
      m_rst_epoch_seen = epoch;
      foreach (m_lock[i]) m_lock[i] = 32'h0;
      foreach (m_target[i]) m_target[i] = 32'h0;
    end
  endfunction

endclass : smc_lock_csr_ref_model
