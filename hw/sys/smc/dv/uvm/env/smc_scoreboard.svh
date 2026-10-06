// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC scoreboard: always on, in every test, pairing per feature the SEP_IN
// monitor stream (observed) with that feature's reference-model stream
// (expected); one comparison counter per feature. Expected values come from
// the reference models, never from the observation under check, and the
// scoreboard holds no prediction state.
//
//   scratch_csr  every OKAY single-beat read of a SCRATCH_COLD or
//                SCRATCH_COLD_WARM register observed on SEP_IN is paired in
//                order with the expected item smc_scratch_csr_ref_model
//                published for it: the pair must address the same register
//                and the CSR lanes of both beats must match.
//
//   spm_mem      every OKAY single-beat read inside the SPM window is paired
//                in order with the expected item smc_spm_mem_ref_model
//                published for it, compared as a whole 64-bit word.
//
//   mutex_sema   every OKAY single-beat read of a CPU_CTRL MUTEX or SEMA is
//                paired in order with the expected item
//                smc_mutex_sema_ref_model published for it, compared under the
//                RDL field mask: acquire-on-read for a mutex, the signed
//                accumulator for a semaphore.
//
//   lock_csr     every OKAY single-beat read of a reset-unit write-once lock
//                register or of the register it guards is paired in order with
//                the expected item smc_lock_csr_ref_model published for it:
//                woset accumulation on the lock, lock-filtered write
//                bit-enables on the guarded register.
//
//   default_reg  every OKAY single-beat read of a smc_default_reg_catalog
//                register that carries a default contract is paired in order
//                with the expected item smc_default_reg_ref_model published
//                for it, on the same address-then-value rule. A catalogued
//                register left decode-only publishes no expected item and is
//                skipped on the observed side too, so the pairing cannot
//                slide out of step.
//
// Accesses outside those windows carry no data contract here and are skipped
// on the observed side. The cocotb twin is env/smc_scoreboard.py (its SysAxi
// expected-value checks).

`uvm_analysis_imp_decl(_smc_scratch_observed)
`uvm_analysis_imp_decl(_smc_scratch_expected)
`uvm_analysis_imp_decl(_smc_default_reg_observed)
`uvm_analysis_imp_decl(_smc_default_reg_expected)
`uvm_analysis_imp_decl(_smc_lock_observed)
`uvm_analysis_imp_decl(_smc_lock_expected)
`uvm_analysis_imp_decl(_smc_mutex_observed)
`uvm_analysis_imp_decl(_smc_mutex_expected)
`uvm_analysis_imp_decl(_smc_spm_observed)
`uvm_analysis_imp_decl(_smc_spm_expected)
`uvm_analysis_imp_decl(_smc_regblock_wide_observed)
`uvm_analysis_imp_decl(_smc_regblock_wide_expected)

class smc_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(smc_scoreboard)

  smc_env_cfg cfg;

  uvm_analysis_imp_smc_scratch_observed #(ocah_axi_item, smc_scoreboard) scratch_observed_export;
  uvm_analysis_imp_smc_scratch_expected #(ocah_axi_item, smc_scoreboard) scratch_expected_export;
  uvm_analysis_imp_smc_default_reg_observed #(ocah_axi_item, smc_scoreboard)
      default_reg_observed_export;
  uvm_analysis_imp_smc_default_reg_expected #(ocah_axi_item, smc_scoreboard)
      default_reg_expected_export;
  uvm_analysis_imp_smc_lock_observed #(ocah_axi_item, smc_scoreboard) lock_observed_export;
  uvm_analysis_imp_smc_lock_expected #(ocah_axi_item, smc_scoreboard) lock_expected_export;
  uvm_analysis_imp_smc_mutex_observed #(ocah_axi_item, smc_scoreboard) mutex_observed_export;
  uvm_analysis_imp_smc_mutex_expected #(ocah_axi_item, smc_scoreboard) mutex_expected_export;
  uvm_analysis_imp_smc_spm_observed #(ocah_axi_item, smc_scoreboard) spm_observed_export;
  uvm_analysis_imp_smc_spm_expected #(ocah_axi_item, smc_scoreboard) spm_expected_export;
  uvm_analysis_imp_smc_regblock_wide_observed #(ocah_axi_item, smc_scoreboard)
      regblock_wide_observed_export;
  uvm_analysis_imp_smc_regblock_wide_expected #(ocah_axi_item, smc_scoreboard)
      regblock_wide_expected_export;

  function new(string name = "smc_scoreboard", uvm_component parent = null);
    super.new(name, parent);
    name_tag = "smc_scoreboard";
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(smc_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "smc_env_cfg `env_cfg` not found in uvm_config_db")
    scratch_observed_export = new("scratch_observed_export", this);
    scratch_expected_export = new("scratch_expected_export", this);
    default_reg_observed_export = new("default_reg_observed_export", this);
    default_reg_expected_export = new("default_reg_expected_export", this);
    lock_observed_export = new("lock_observed_export", this);
    lock_expected_export = new("lock_expected_export", this);
    mutex_observed_export = new("mutex_observed_export", this);
    mutex_expected_export = new("mutex_expected_export", this);
    spm_observed_export = new("spm_observed_export", this);
    spm_expected_export = new("spm_expected_export", this);
    regblock_wide_observed_export = new("regblock_wide_observed_export", this);
    regblock_wide_expected_export = new("regblock_wide_expected_export", this);
    add_feature(SmcFeatureScratchCsr);
    add_feature(SmcFeatureDefaultReg);
    add_feature(SmcFeatureLockCsr);
    add_feature(SmcFeatureMutexSema);
    add_feature(SmcFeatureSpmMem);
    add_feature(SmcFeatureRegblockWide);
    foreach (cfg.required_features[i]) require_feature(cfg.required_features[i]);
  endfunction

  // ------------------------------------------------------------------
  // Streams: observed reads the reference model predicts, and its
  // expected items.
  // ------------------------------------------------------------------

  function void write_smc_scratch_observed(ocah_axi_item t);
    bit warm;
    if (t.direction != OCAH_AXI_DIR_READ || !smc_is_scratch_csr_access(t, warm)) return;
    push_observed(SmcFeatureScratchCsr, t);
  endfunction

  function void write_smc_scratch_expected(ocah_axi_item t);
    push_expected(SmcFeatureScratchCsr, t);
  endfunction

  // default_reg: only the catalogued registers that carry a default
  // contract; a decode-only entry is skipped on both sides. The scratch
  // registers appear in this catalogue as well as in the scratch windows, so
  // a read of one is judged independently by both features -- two models
  // reaching the same expectation from different state, not one claim
  // counted twice.
  function void write_smc_default_reg_observed(ocah_axi_item t);
    smc_default_reg_entry_t entry;
    if (t.direction != OCAH_AXI_DIR_READ || !smc_is_default_reg_access(t, entry)) return;
    if (!entry.has_default) return;
    push_observed(SmcFeatureDefaultReg, t);
  endfunction

  function void write_smc_default_reg_expected(ocah_axi_item t);
    push_expected(SmcFeatureDefaultReg, t);
  endfunction

  // lock_csr: reads of either register of a smc_lock_pairs entry.
  function void write_smc_lock_observed(ocah_axi_item t);
    int unsigned pair_idx;
    bit          is_lock;
    if (t.direction != OCAH_AXI_DIR_READ || !smc_is_lock_csr_access(t, pair_idx, is_lock)) return;
    push_observed(SmcFeatureLockCsr, t);
  endfunction

  function void write_smc_lock_expected(ocah_axi_item t);
    push_expected(SmcFeatureLockCsr, t);
  endfunction

  // mutex_sema: reads of any CPU_CTRL mutex or semaphore. A read of a mutex
  // is itself an acquire, so the observed side must not filter differently
  // from the model or the two streams would describe different histories.
  function void write_smc_mutex_observed(ocah_axi_item t);
    int unsigned idx;
    bit          is_sema;
    if (t.direction != OCAH_AXI_DIR_READ || !smc_is_mutex_sema_access(t, idx, is_sema)) return;
    push_observed(SmcFeatureMutexSema, t);
  endfunction

  function void write_smc_mutex_expected(ocah_axi_item t);
    push_expected(SmcFeatureMutexSema, t);
  endfunction

  // spm_mem: reads inside the SPM window, compared as whole 64-bit words.
  function void write_smc_spm_observed(ocah_axi_item t);
    if (t.direction != OCAH_AXI_DIR_READ || !smc_is_spm_mem_access(t)) return;
    push_observed(SmcFeatureSpmMem, t);
  endfunction

  function void write_smc_spm_expected(ocah_axi_item t);
    push_expected(SmcFeatureSpmMem, t);
  endfunction

  function void write_smc_regblock_wide_observed(ocah_axi_item t);
    smc_regblock_wide_entry_t entry;
    int unsigned index;
    bit enabled = 1'b0;
    foreach (cfg.required_features[i]) begin
      if (cfg.required_features[i] == SmcFeatureRegblockWide) enabled = 1'b1;
    end
    if (!enabled || t.direction != OCAH_AXI_DIR_READ || !smc_is_regblock_wide_access(
            t, entry, index
        ))
      return;
    push_observed(SmcFeatureRegblockWide, t);
  endfunction

  function void write_smc_regblock_wide_expected(ocah_axi_item t);
    push_expected(SmcFeatureRegblockWide, t);
  endfunction

  // The CSR features compare 32-bit register lanes within each 64-bit beat.
  // SPM and wide register-block features compare complete 64-bit beats.
  virtual function void compare_pair(string feature, uvm_object observed, uvm_object expected);
    ocah_axi_item obs, exp;
    bit [63:0] word_addr;
    if (feature != SmcFeatureScratchCsr && feature != SmcFeatureDefaultReg &&
        feature != SmcFeatureLockCsr && feature != SmcFeatureMutexSema &&
        feature != SmcFeatureSpmMem && feature != SmcFeatureRegblockWide)
      `uvm_fatal(get_type_name(), $sformatf("no compare for feature `%s`", feature))
    if (!$cast(obs, observed) || !$cast(exp, expected))
      `uvm_fatal(get_type_name(), {feature, " pair is not a pair of ocah_axi_item"})
    if (feature == SmcFeatureSpmMem) begin
      compare_mem_pair(obs, exp);
      return;
    end
    if (feature == SmcFeatureRegblockWide) begin
      compare_regblock_wide_pair(obs, exp);
      return;
    end
    word_addr = smc_csr_word_addr(obs.address);
    compare_csr_pair(feature, obs, exp, word_addr, csr_context(feature, word_addr), field_mask(
                     feature, word_addr));
  endfunction

  // Bits the feature has a contract on. Every CSR feature here owns the whole
  // 32-bit word except mutex_sema, whose registers are declared regwidth 64
  // with a narrower live field, so the bits above the field are excluded
  // rather than given an invented expectation.
  protected function bit [31:0] field_mask(string feature, bit [63:0] word_addr);
    int unsigned idx;
    bit          is_sema;
    if (feature != SmcFeatureMutexSema) return 32'hFFFF_FFFF;
    if (!smc_mutex_sema_lookup(word_addr, idx, is_sema)) return 32'hFFFF_FFFF;
    return is_sema ? SmcSemaMask : SmcMutexMask;
  endfunction

  // ------------------------------------------------------------------
  // Shared comparison of one 32-bit CSR read pair.
  // ------------------------------------------------------------------

  protected function void compare_csr_pair(string feature, ocah_axi_item obs, ocah_axi_item exp,
                                           bit [63:0] word_addr, string context_s,
                                           bit [31:0] mask = 32'hFFFF_FFFF);
    if (exp.address !== word_addr) begin
      record_compare(feature, 1'b0, $sformatf("addr=0x%0h", exp.address), $sformatf(
                     "addr=0x%0h", word_addr), {context_s, " pairing"});
      return;
    end
    void'(compare_equal(
        feature,
        64'(smc_csr_from_bus(
            word_addr, obs.first_data()
        ) & mask),
        64'(smc_csr_from_bus(
            word_addr, exp.first_data()
        ) & mask),
        (mask == 32'hFFFF_FFFF) ? context_s : $sformatf(
            "%s mask=0x%08h", context_s, mask)
    ));
  endfunction

  // One SPM pair: same 64-bit word address, then the whole word. No lane
  // placement and no field mask -- an SPM access strobes every byte.
  protected function void compare_mem_pair(ocah_axi_item obs, ocah_axi_item exp);
    bit [63:0] word_addr = smc_mem_word_addr(obs.address);
    string     context_s = $sformatf("SPM addr=0x%0h", word_addr);
    if (exp.address !== word_addr) begin
      record_compare(SmcFeatureSpmMem, 1'b0, $sformatf("addr=0x%0h", exp.address), $sformatf(
                     "addr=0x%0h", word_addr), {context_s, " pairing"});
      return;
    end
    void'(compare_equal(SmcFeatureSpmMem, obs.first_data(), exp.first_data(), context_s));
  endfunction

  protected function void compare_regblock_wide_pair(ocah_axi_item obs, ocah_axi_item exp);
    bit passed = obs.address === exp.address && obs.size == exp.size &&
                 obs.expected_beats == 1 && exp.expected_beats == 1 &&
                 obs.data_words.size() == 1 && exp.data_words.size() == 1 && obs.is_ok();
    if (passed && obs.data_words[0] !== exp.data_words[0]) passed = 1'b0;
    record_compare(
        SmcFeatureRegblockWide, passed, $sformatf(
        "addr=0x%0h data=0x%016h resp=OKAY", exp.address, exp.first_data()), $sformatf(
        "addr=0x%0h data=0x%016h resp=%s", obs.address, obs.first_data(), obs.worst_resp().name()),
        "wide register-block read");
  endfunction

  // Register identity for the evidence line: the scratch domain, or the
  // catalogue entry name.
  protected function string csr_context(string feature, bit [63:0] word_addr);
    bit                     warm;
    smc_default_reg_entry_t entry;
    int unsigned            pair_idx;
    bit                     is_lock;
    smc_lock_pair_t         pairs[$];
    int unsigned            ms_idx;
    bit                     is_sema;
    if (feature == SmcFeatureScratchCsr) begin
      void'(smc_is_scratch_csr(word_addr, warm));
      return $sformatf("%s addr=0x%0h", warm ? "SCRATCH_COLD_WARM" : "SCRATCH_COLD", word_addr);
    end
    if (feature == SmcFeatureMutexSema) begin
      if (smc_mutex_sema_lookup(word_addr, ms_idx, is_sema))
        return $sformatf(
            "CPU_CTRL_%s_%0d addr=0x%0h", is_sema ? "SEMA" : "MUTEX", ms_idx, word_addr
        );
      return $sformatf("addr=0x%0h", word_addr);
    end
    if (feature == SmcFeatureLockCsr) begin
      smc_lock_pairs(pairs);
      if (smc_lock_lookup(word_addr, pair_idx, is_lock))
        return $sformatf(
            "SS_%s%s addr=0x%0h", pairs[pair_idx].name, is_lock ? "_LOCK" : "", word_addr
        );
      return $sformatf("addr=0x%0h", word_addr);
    end
    if (smc_default_reg_lookup(word_addr, entry))
      return $sformatf("%s addr=0x%0h", entry.name, word_addr);
    return $sformatf("addr=0x%0h", word_addr);
  endfunction

endclass : smc_scoreboard
