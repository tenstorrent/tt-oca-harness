// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC mutex/semaphore reference model: the mutex_sema predictor of
// smc_scoreboard. It subscribes to the SEP_IN monitor stream and models the
// CPU_CTRL hardware mutexes and semaphores, whose READ is not a passive
// observation:
//
//   MUTEX[i]  a read attempts to acquire. The expected read value is the
//             "available" encoding when the lock was free and 0 when it was
//             already held -- and EITHER WAY the lock is held afterwards, so
//             the state advances on a read. A write of any value releases it.
//   SEMA[i]   a write adds its value to the accumulator as a 16-bit two's
//             complement signed number; a read returns the accumulator.
//
// Because a read mutates the model, the expected value is computed BEFORE the
// state advances -- the reverse order would predict what the *next* read
// should see and would let a DUT that never acquires anything pass.
//
// Only the RDL field bits are predicted: both registers are declared
// regwidth 64 with their live field inside the low 32 bits, so the bits above
// the field have no field to hold and the scoreboard compares under
// SmcMutexMask / SmcSemaMask rather than being handed an invented expectation
// for them.
//
// Every mutex and semaphore instance is modelled, not just the ones a given
// scenario drives, so a test that touches MUTEX[2] gets the same checking as
// one that touches MUTEX[0]. State clears on cold reset (smc_tb_if
// cold_rst_assert_count).
//
// cfg.mutex_scoreboard_negative (+SMC_MUTEX_SCOREBOARD_NEGATIVE) is the
// documented negative-validation hook: the prediction is corrupted so the
// scoreboard must fail on the first mutex or semaphore read. No comparison
// and no verdict live here. The cocotb twin is the value-checked half of
// seq_lib/smc_mutex_semaphore_test_seq.py.

class smc_mutex_sema_ref_model extends ocah_ref_model #(ocah_axi_item, ocah_axi_item);
  `uvm_component_utils(smc_mutex_sema_ref_model)

  smc_env_cfg cfg;
  // Handed by smc_env: the cold-reset counter the state re-baselines on.
  virtual smc_tb_if tb_vif;

  // One holder flag per mutex, one accumulator per semaphore.
  protected bit        m_mutex_taken[SmcMutexCount];
  protected bit [15:0] m_sema[SmcSemaCount];
  protected bit [63:0] m_rst_epoch_seen;

  function new(string name = "smc_mutex_sema_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual smc_tb_if `tb_vif` not set by the env")
    if (cfg.mutex_scoreboard_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: mutex/semaphore prediction corrupted (field bit 0 inverted)",
                UVM_LOW)
  endfunction

  // One observed SEP_IN transaction on a mutex or a semaphore.
  function void write(ocah_axi_item t);
    int unsigned idx;
    bit          is_sema;
    bit [63:0]   word_addr;
    bit [31:0]   wdata;
    bit [31:0]   value;
    sync_cold_reset();
    if (!smc_is_mutex_sema_access(t, idx, is_sema)) return;
    word_addr = smc_csr_word_addr(t.address);

    if (t.direction == OCAH_AXI_DIR_WRITE) begin
      wdata = smc_csr_from_bus(word_addr, t.data_words[0]);
      // MUTEX: a write of any value releases. SEMA: the written value is a
      // signed 16-bit increment, so plain truncated addition applies it.
      if (is_sema) m_sema[idx] = m_sema[idx] + wdata[15:0];
      else m_mutex_taken[idx] = 1'b0;
      return;
    end

    if (is_sema) begin
      value = 32'(m_sema[idx]) & SmcSemaMask;
    end else begin
      // Expected FIRST, then the acquire the read itself performs.
      value = m_mutex_taken[idx] ? SmcMutexTaken : SmcMutexFree;
      m_mutex_taken[idx] = 1'b1;
    end
    expected_ap.write(expected_read(t, word_addr, value, is_sema ? SmcSemaMask : SmcMutexMask));
  endfunction

  protected function ocah_axi_item expected_read(ocah_axi_item t, bit [63:0] word_addr,
                                                 bit [31:0] value, bit [31:0] field_mask);
    ocah_axi_item e = ocah_axi_item::type_id::create("expected");
    if (cfg.mutex_scoreboard_negative) value ^= (field_mask & ~(field_mask << 1));
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

  // CPU_CTRL sits under rst_primary_smc_clk_n, which a cold reset AND a
  // de-glitched cool reset drop, so the state follows the tb_if reset epoch.
  protected function void sync_cold_reset();
    bit [63:0] epoch = smc_csr_reset_epoch(
        tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count
    );
    if (epoch !== m_rst_epoch_seen) begin
      m_rst_epoch_seen = epoch;
      foreach (m_mutex_taken[i]) m_mutex_taken[i] = 1'b0;
      foreach (m_sema[i]) m_sema[i] = 16'h0;
    end
  endfunction

endclass : smc_mutex_sema_ref_model
