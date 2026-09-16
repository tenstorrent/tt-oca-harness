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
// Accesses outside the scratch windows carry no data contract here and are
// skipped on the observed side. The cocotb twin is env/smc_scoreboard.py
// (its SysAxi expected-value checks).

`uvm_analysis_imp_decl(_smc_scratch_observed)
`uvm_analysis_imp_decl(_smc_scratch_expected)

class smc_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(smc_scoreboard)

  smc_env_cfg cfg;

  uvm_analysis_imp_smc_scratch_observed #(ocah_axi_item, smc_scoreboard) scratch_observed_export;
  uvm_analysis_imp_smc_scratch_expected #(ocah_axi_item, smc_scoreboard) scratch_expected_export;

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
    add_feature(SmcFeatureScratchCsr);
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

  // One pair: same register, then the CSR lanes of both beats.
  virtual function void compare_pair(string feature, uvm_object observed, uvm_object expected);
    ocah_axi_item obs, exp;
    bit           warm;
    bit [63:0]    word_addr;
    string        context_s;
    if (feature != SmcFeatureScratchCsr)
      `uvm_fatal(get_type_name(), $sformatf("no compare for feature `%s`", feature))
    if (!$cast(obs, observed) || !$cast(exp, expected))
      `uvm_fatal(get_type_name(), "scratch_csr pair is not a pair of ocah_axi_item")
    word_addr = smc_csr_word_addr(obs.address);
    void'(smc_is_scratch_csr(word_addr, warm));
    context_s = $sformatf("%s addr=0x%0h", warm ? "SCRATCH_COLD_WARM" : "SCRATCH_COLD", word_addr);
    if (exp.address !== word_addr) begin
      record_compare(feature, 1'b0, $sformatf("addr=0x%0h", exp.address), $sformatf(
                     "addr=0x%0h", word_addr), {context_s, " pairing"});
      return;
    end
    void'(compare_equal(
        feature,
        64'(smc_csr_from_bus(
            word_addr, obs.first_data()
        )),
        64'(smc_csr_from_bus(
            word_addr, exp.first_data()
        )),
        context_s
    ));
  endfunction

endclass : smc_scoreboard
