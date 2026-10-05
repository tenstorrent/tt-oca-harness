// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP scoreboard: always on, in every test, pairing per feature the CPU-LSU
// monitor stream (observed) with that feature's reference-model stream
// (expected); one comparison counter per feature. Expected values come from
// the reference models, never from the observation under check, and the
// scoreboard holds no prediction state.
//
//   cpu_ctrl_csr  every OKAY single-beat read of a predicted sep_cpu_ctrl
//                 register observed on the CPU-LSU splice is paired in
//                 order with the expected item sep_cpu_ctrl_csr_ref_model
//                 published for it: the pair must address the same
//                 register and the CSR lanes of both beats must match.
//
// Accesses outside the predicted set carry no data contract here and are
// skipped on the observed side. The cocotb twin is cocotb/env/sep_scoreboard.py
// (its expected-value checks).

`uvm_analysis_imp_decl(_sep_csr_observed)
`uvm_analysis_imp_decl(_sep_csr_expected)

class sep_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(sep_scoreboard)

  sep_env_cfg cfg;

  uvm_analysis_imp_sep_csr_observed #(ocah_axi_item, sep_scoreboard) csr_observed_export;
  uvm_analysis_imp_sep_csr_expected #(ocah_axi_item, sep_scoreboard) csr_expected_export;

  function new(string name = "sep_scoreboard", uvm_component parent = null);
    super.new(name, parent);
    name_tag = "sep_scoreboard";
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(sep_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "sep_env_cfg `env_cfg` not found in uvm_config_db")
    csr_observed_export = new("csr_observed_export", this);
    csr_expected_export = new("csr_expected_export", this);
    add_feature(SepFeatureCpuCtrlCsr);
    foreach (cfg.required_features[i]) require_feature(cfg.required_features[i]);
  endfunction

  // ------------------------------------------------------------------
  // Streams: observed reads the reference model predicts, and its
  // expected items.
  // ------------------------------------------------------------------

  function void write_sep_csr_observed(ocah_axi_item t);
    sep_csr_desc_t desc;
    if (t.direction != OCAH_AXI_DIR_READ || !sep_is_cpu_ctrl_csr_access(t, desc)) return;
    push_observed(SepFeatureCpuCtrlCsr, t);
  endfunction

  function void write_sep_csr_expected(ocah_axi_item t);
    push_expected(SepFeatureCpuCtrlCsr, t);
  endfunction

  // One pair: same register, then the CSR lanes of both beats.
  virtual function void compare_pair(string feature, uvm_object observed, uvm_object expected);
    ocah_axi_item obs, exp;
    sep_csr_desc_t desc;
    bit [63:0]     word_addr;
    string         context_s;
    if (feature != SepFeatureCpuCtrlCsr)
      `uvm_fatal(get_type_name(), $sformatf("no compare for feature `%s`", feature))
    if (!$cast(obs, observed) || !$cast(exp, expected))
      `uvm_fatal(get_type_name(), "cpu_ctrl_csr pair is not a pair of ocah_axi_item")
    word_addr = sep_csr_word_addr(obs.address);
    void'(sep_cpu_ctrl_csr_lookup(word_addr, desc));
    context_s = $sformatf("%s addr=0x%0h", desc.name, word_addr);
    if (exp.address !== word_addr) begin
      record_compare(feature, 1'b0, $sformatf("addr=0x%0h", exp.address), $sformatf(
                     "addr=0x%0h", word_addr), {context_s, " pairing"});
      return;
    end
    void'(compare_equal(
        feature,
        64'(sep_csr_from_bus(
            word_addr, obs.first_data()
        )),
        64'(sep_csr_from_bus(
            word_addr, exp.first_data()
        )),
        context_s
    ));
  endfunction

endclass : sep_scoreboard
