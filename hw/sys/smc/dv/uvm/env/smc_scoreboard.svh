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
//   regblock_wide every catalogued single-beat read or write is paired with
//                its predicted response, including accesses that return errors.
//                Reads also compare the complete predicted 64-bit value;
//                only OKAY writes update the reference model's shadow.
//
//   wdt_csr      sequential single-beat writes and aligned 32-bit reads of
//                watchdog words compare responses without filtering errors.
//                CTRL (IP masked), KEY and CMP also compare predicted data.
//                Only OKAY writes update the model; other writers and reset
//                with outstanding watchdog accesses are outside its contract.
//
//   fabric_reg   required-feature-only full-width accesses to five register
//                words compare OKAY responses, including error observations.
//                Reads compare defined RDL fields. The SEP_IN read helper
//                checks X/Z; the passive monitor does not retain data X/Z masks.
//                Only OKAY writes update the model; filter configuration is fixed.
//
//   mailbox_fifo required-only sequential full-width mailbox accesses compare
//                request-derived responses and defined read fields. IRQS data
//                and data of reads answered SLVERR are excluded; successful
//                ERROR reads are predicted. Error accesses still update error
//                flags; cold/cool epochs clear shadow. No other accessor or
//                reset with outstanding traffic is supported. Active SEP_IN
//                helpers check X/Z; the passive monitor discards data X/Z masks.
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

`uvm_analysis_imp_decl(_smc_wdt_csr_observed)
`uvm_analysis_imp_decl(_smc_wdt_csr_expected)

`uvm_analysis_imp_decl(_smc_fabric_reg_observed)
`uvm_analysis_imp_decl(_smc_fabric_reg_expected)
`uvm_analysis_imp_decl(_smc_mailbox_fifo_observed)
`uvm_analysis_imp_decl(_smc_mailbox_fifo_expected)

class smc_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(smc_scoreboard)

  smc_env_cfg cfg;

  uvm_analysis_imp_smc_fabric_reg_observed #(ocah_axi_item, smc_scoreboard)
      fabric_reg_observed_export;
  uvm_analysis_imp_smc_fabric_reg_expected #(ocah_axi_item, smc_scoreboard)
      fabric_reg_expected_export;

  uvm_analysis_imp_smc_mailbox_fifo_observed #(ocah_axi_item, smc_scoreboard)
      mailbox_fifo_observed_export;
  uvm_analysis_imp_smc_mailbox_fifo_expected #(ocah_axi_item, smc_scoreboard)
      mailbox_fifo_expected_export;

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
  uvm_analysis_imp_smc_wdt_csr_observed #(ocah_axi_item, smc_scoreboard) wdt_csr_observed_export;
  uvm_analysis_imp_smc_wdt_csr_expected #(ocah_axi_item, smc_scoreboard) wdt_csr_expected_export;

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
    wdt_csr_observed_export = new("wdt_csr_observed_export", this);
    wdt_csr_expected_export = new("wdt_csr_expected_export", this);
    add_feature(SmcFeatureScratchCsr);
    add_feature(SmcFeatureDefaultReg);
    add_feature(SmcFeatureLockCsr);
    add_feature(SmcFeatureMutexSema);
    add_feature(SmcFeatureSpmMem);
    add_feature(SmcFeatureRegblockWide);
    fabric_reg_observed_export = new("fabric_reg_observed_export", this);
    fabric_reg_expected_export = new("fabric_reg_expected_export", this);
    add_feature(SmcFeatureFabricReg);
    add_feature(SmcFeatureWdtCsr);
    mailbox_fifo_observed_export = new("mailbox_fifo_observed_export", this);
    mailbox_fifo_expected_export = new("mailbox_fifo_expected_export", this);
    add_feature(SmcFeatureMailboxFifo);
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
  // registers are in this catalogue as well as in the scratch windows, so a
  // read of one is judged by both features.
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
    if (!enabled || !smc_is_regblock_wide_access(t, entry, index)) return;
    push_observed(SmcFeatureRegblockWide, t);
  endfunction

  function void write_smc_regblock_wide_expected(ocah_axi_item t);
    push_expected(SmcFeatureRegblockWide, t);
  endfunction

  function void write_smc_wdt_csr_observed(ocah_axi_item t);
    int unsigned core, offset;
    bit enabled = 1'b0;
    foreach (cfg.required_features[i]) begin
      if (cfg.required_features[i] == SmcFeatureWdtCsr) enabled = 1'b1;
    end
    if (enabled && smc_is_wdt_csr_access(t, core, offset)) push_observed(SmcFeatureWdtCsr, t);
  endfunction

  function void write_smc_wdt_csr_expected(ocah_axi_item t);
    push_expected(SmcFeatureWdtCsr, t);
  endfunction

  protected function void compare_wdt_csr_pair(ocah_axi_item obs, ocah_axi_item exp);
    int unsigned core, offset;
    string direction_label = obs.direction == OCAH_AXI_DIR_READ ? "read" : "write";
    bit passed = obs.direction == exp.direction &&
                 smc_csr_word_addr(obs.address) === exp.address &&
                 obs.resp_list.size() == 1 && exp.resp_list.size() == 1 &&
                 !obs.timed_out && !obs.any_resp_xz();
    bit [31:0] mask;
    void'(smc_is_wdt_csr_access(obs, core, offset));
    mask = smc_wdt_csr_mask(offset);
    if (passed) passed = obs.resp_list[0] == exp.resp_list[0];
    if (passed && obs.direction == OCAH_AXI_DIR_READ && mask != 0)
      passed = (smc_csr_from_bus(
          obs.address, obs.first_xz_mask()
      ) & mask) == 0 && (smc_csr_from_bus(
          obs.address, obs.first_data()
      ) & mask) === (smc_csr_from_bus(
          exp.address, exp.first_data()
      ) & mask);
    record_compare(
        SmcFeatureWdtCsr, passed, $sformatf(
        "addr=0x%0h data=0x%0h resp=%s", exp.address, exp.first_data(), exp.worst_resp().name()),
        $sformatf(
        "addr=0x%0h data=0x%0h resp=%s", obs.address, obs.first_data(), obs.worst_resp().name()),
        $sformatf("WDT%0d offset=0x%0h %s", core, offset, direction_label));
  endfunction

  function void write_smc_fabric_reg_observed(ocah_axi_item t);
    int unsigned index;
    bit enabled = 0;
    foreach (cfg.required_features[i]) begin
      if (cfg.required_features[i] == SmcFeatureFabricReg) enabled = 1;
    end
    if (enabled && smc_is_fabric_reg_access(t, index)) push_observed(SmcFeatureFabricReg, t);
  endfunction

  function void write_smc_fabric_reg_expected(ocah_axi_item t);
    push_expected(SmcFeatureFabricReg, t);
  endfunction

  protected function void compare_fabric_reg_pair(ocah_axi_item obs, ocah_axi_item exp);
    smc_fabric_reg_entry_t entries[$];
    int unsigned index;
    bit passed = smc_is_fabric_reg_access(obs, index);
    bit [63:0] mask;
    string direction_label = obs.direction == OCAH_AXI_DIR_READ ? "read" : "write";
    smc_fabric_reg_catalog(entries);
    if (!passed) begin
      record_compare(SmcFeatureFabricReg, 0, "catalogued single beat", "unsupported shape");
      return;
    end
    mask = entries[index].read_mask;
    passed = obs.direction == exp.direction && obs.address === exp.address &&
             obs.size == exp.size && obs.resp_list.size() == 1 &&
             exp.resp_list.size() == 1 && !obs.timed_out && !obs.any_resp_xz();
    if (passed) passed = obs.resp_list[0] == exp.resp_list[0];
    if (passed && obs.direction == OCAH_AXI_DIR_READ)
      passed = (obs.first_data() & mask) === (exp.first_data() & mask);
    record_compare(
        SmcFeatureFabricReg, passed, $sformatf(
        "data=0x%016h resp=%s", exp.first_data(), exp.worst_resp().name()), $sformatf(
        "data=0x%016h resp=%s", obs.first_data(), obs.worst_resp().name()), $sformatf(
        "%s %s addr=0x%0h mask=0x%016h", entries[index].name, direction_label, obs.address, mask));
  endfunction

  function void write_smc_mailbox_fifo_observed(ocah_axi_item t);
    bit enabled = 0;
    int unsigned mailbox, offset;
    bit inbound;
    foreach (cfg.required_features[i])
    if (cfg.required_features[i] == SmcFeatureMailboxFifo) enabled = 1;
    if (!enabled || !smc_mailbox_decode(t.address, mailbox, inbound, offset)) return;
    if (!smc_is_mailbox_fifo_access(t))
      `uvm_fatal(get_type_name(), "mailbox_fifo observed unsupported access")
    push_observed(SmcFeatureMailboxFifo, t);
  endfunction

  function void write_smc_mailbox_fifo_expected(ocah_axi_item t);
    push_expected(SmcFeatureMailboxFifo, t);
  endfunction

  protected function void compare_mailbox_fifo_pair(ocah_axi_item obs, ocah_axi_item exp);
    int unsigned mailbox, offset;
    bit inbound;
    bit [63:0] mask;
    bit passed = smc_mailbox_decode(obs.address, mailbox, inbound, offset);
    string direction_label = obs.direction == OCAH_AXI_DIR_READ ? "read" : "write";
    mask = smc_mailbox_mask(offset);
    passed &= obs.address === exp.address && obs.direction == exp.direction &&
        obs.size == exp.size && obs.expected_beats == 1 && exp.expected_beats == 1 &&
        obs.resp_list.size() == 1 && exp.resp_list.size() == 1 &&
        !obs.timed_out && !obs.any_resp_xz();
    if (passed) passed = obs.resp_list[0] == exp.resp_list[0];
    if (passed && obs.direction == OCAH_AXI_DIR_READ && exp.data_words.size() == 1)
      passed = obs.data_words.size() == 1 &&
          (obs.first_data() & mask) === (exp.first_data() & mask);
    record_compare(
        SmcFeatureMailboxFifo, passed, $sformatf(
        "data=0x%016h resp=%s", exp.first_data(), exp.worst_resp().name()), $sformatf(
        "data=0x%016h resp=%s", obs.first_data(), obs.worst_resp().name()), $sformatf(
        "mailbox=%0d inbound=%0b offset=0x%0h %s", mailbox, inbound, offset, direction_label));
  endfunction

  // The CSR features compare 32-bit register lanes within each 64-bit beat.
  // SPM and wide register-block features compare complete 64-bit beats.
  virtual function void compare_pair(string feature, uvm_object observed, uvm_object expected);
    ocah_axi_item obs, exp;
    bit [63:0] word_addr;
    if (feature != SmcFeatureScratchCsr && feature != SmcFeatureDefaultReg &&
        feature != SmcFeatureLockCsr && feature != SmcFeatureMutexSema &&
        feature != SmcFeatureSpmMem && feature != SmcFeatureRegblockWide &&
        feature != SmcFeatureWdtCsr && feature != SmcFeatureFabricReg &&
        feature != SmcFeatureMailboxFifo)
      `uvm_fatal(get_type_name(), $sformatf("no compare for feature `%s`", feature))
    if (!$cast(obs, observed) || !$cast(exp, expected))
      `uvm_fatal(get_type_name(), {feature, " pair is not a pair of ocah_axi_item"})
    if (feature == SmcFeatureMailboxFifo) begin
      compare_mailbox_fifo_pair(obs, exp);
      return;
    end
    if (feature == SmcFeatureFabricReg) begin
      compare_fabric_reg_pair(obs, exp);
      return;
    end
    if (feature == SmcFeatureWdtCsr) begin
      compare_wdt_csr_pair(obs, exp);
      return;
    end
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
    string access_kind = obs.direction == OCAH_AXI_DIR_READ ? "read" : "write";
    bit passed = obs.direction == exp.direction && obs.address === exp.address &&
                 obs.size == exp.size && obs.expected_beats == 1 && exp.expected_beats == 1 &&
                 obs.data_words.size() == 1 && exp.data_words.size() == 1 &&
                 obs.resp_list.size() == 1 && exp.resp_list.size() == 1 &&
                 !obs.timed_out && !obs.any_resp_xz();
    if (passed && obs.resp_list[0] != exp.resp_list[0]) passed = 1'b0;
    if (passed && obs.direction == OCAH_AXI_DIR_READ && obs.data_words[0] !== exp.data_words[0])
      passed = 1'b0;
    record_compare(
        SmcFeatureRegblockWide, passed, $sformatf(
        "addr=0x%0h data=0x%016h resp=%s", exp.address, exp.first_data(), exp.worst_resp().name()),
        $sformatf(
        "addr=0x%0h data=0x%016h resp=%s", obs.address, obs.first_data(), obs.worst_resp().name()),
        {"wide register-block ", access_kind});
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
