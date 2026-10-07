// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scoreboard base: the feature registry and the two-stream pairing behind
// the mandatory, always-on bench scoreboard. A bench <dut>_scoreboard
// registers one feature per reference model (add_feature) and declares two
// analysis imps per feature: the observed VIP monitor stream and the
// expected_ap of that feature's <dut>_<feature>_ref_model. Its write_*
// handlers call push_observed()/push_expected(), optionally naming a lane
// when one feature is judged on several independent in-order streams (one
// per monitored port); the base pairs the two queues of a lane in
// observation order and hands each pair to compare_pair(), which
// the bench implements with compare_equal() or record_compare(): a mismatch
// is a uvm_error at once, carrying feature, expected, observed, and
// context. Analysis subscriber order is unordered, so either stream may
// arrive first. A reset that cancels predicted transactions withdraws them
// with flush_expected(), on every lane or on one. check_phase errors on items
// left unpaired, turns each feature, its unpaired items included, into one
// CHK-SB-<FEATURE> record through the shared evidence recorder, and
// finalizes it once; a required feature (require_feature, from the env cfg)
// that ends with zero comparisons fails the run, so a scenario cannot pass
// without exercising what it claims to check. The scoreboard holds no
// expected-value state: prediction is the reference model's job. The cocotb
// twin is ocah_lib.OcahScoreboard.

class ocah_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(ocah_scoreboard)

  typedef struct {
    string       name;
    bit          required;
    int unsigned compares;
    int unsigned mismatches;
    int unsigned unpaired;
  } feature_t;

  // The flush_expected() lane that selects every lane of a feature.
  localparam string AllLanes = "*";

  // Evidence identity for the CHK-SB-* records and the mismatch report id.
  string name_tag = "ocah_scoreboard";
  ocah_checker m_evidence;

  protected feature_t m_features[string];
  protected string    m_feature_order[$];

  // Two-stream pairing per feature and lane (pair_key), in observation
  // order on both sides; m_key_feature maps a key back to its feature.
  protected uvm_object m_observed_q[string][$];
  protected uvm_object m_expected_q[string][$];
  protected string     m_key_feature[string];

  function new(string name = "ocah_scoreboard", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    m_evidence = ocah_checker::type_id::create({get_name(), ".evidence"});
    m_evidence.name_tag = name_tag;
  endfunction

  function void check_phase(uvm_phase phase);
    bit any_required = 1'b0;
    super.check_phase(phase);
    foreach (m_feature_order[i]) begin
      feature_t f = m_features[m_feature_order[i]];
      any_required |= f.required;
      f.unpaired = report_unpaired(f.name, m_observed_q,
                                   "observed item(s) never paired with an expectation") +
          report_unpaired(f.name, m_expected_q,
                          "expected item(s) never paired with an observation");
      if (!f.required && f.compares == 0 && f.unpaired == 0) continue;
      void'(m_evidence.expect_true(
          feature_check_id(
              f.name
          ),
          (f.compares > 0) && (f.mismatches == 0) && (f.unpaired == 0),
          $sformatf(
              "feature=%s compares=%0d mismatches=%0d unpaired=%0d required=%0d",
              f.name,
              f.compares,
              f.mismatches,
              f.unpaired,
              f.required)
      ));
    end
    m_evidence.finalize(any_required);
  endfunction

  // ------------------------------------------------------------------
  // Feature registry (build_phase of the bench scoreboard).
  // ------------------------------------------------------------------

  function void add_feature(string feature, bit required = 1'b0);
    feature_t f;
    if (m_features.exists(feature))
      `uvm_fatal(get_type_name(), $sformatf("feature `%s` registered twice", feature))
    f.name       = feature;
    f.required   = required;
    f.compares   = 0;
    f.mismatches = 0;
    f.unpaired   = 0;
    m_features[feature] = f;
    m_feature_order.push_back(feature);
  endfunction

  // Mark a registered feature as required (from the env cfg).
  function void require_feature(string feature);
    if (!m_features.exists(feature))
      `uvm_fatal(get_type_name(), $sformatf(
                 "required feature `%s` is not registered; known: %p", feature, m_feature_order))
    m_features[feature].required = 1'b1;
  endfunction

  function bit has_feature(string feature);
    return m_features.exists(feature);
  endfunction

  function int unsigned compare_count(string feature);
    return m_features.exists(feature) ? m_features[feature].compares : 0;
  endfunction

  function int unsigned mismatch_count(string feature);
    return m_features.exists(feature) ? m_features[feature].mismatches : 0;
  endfunction

  // ------------------------------------------------------------------
  // Recording (write_* handlers of the bench scoreboard).
  // ------------------------------------------------------------------

  // Record one comparison verdict against a feature; a mismatch is an
  // error at once with expected, observed, and context.
  function void record_compare(string feature, bit passed, string expected_s, string observed_s,
                               string context_s = "");
    if (!m_features.exists(feature))
      `uvm_fatal(get_type_name(), $sformatf("compare on unregistered feature `%s`", feature))
    m_features[feature].compares++;
    if (passed) begin
      `uvm_info({name_tag, "_", feature, "_chk"},
                  $sformatf("%s: expected=%s observed=%s context=%s", feature, expected_s,
                            observed_s, context_s), UVM_MEDIUM)
      return;
    end
    m_features[feature].mismatches++;
    `uvm_error({name_tag, "_", feature, "_chk"}, $sformatf(
               "%s mismatch: expected=%s observed=%s context=%s",
               feature,
               expected_s,
               observed_s,
               context_s
               ))
  endfunction

  // Integer comparison with four-state safety (=== on the observed value).
  function bit compare_equal(string feature, bit [63:0] observed, bit [63:0] expected,
                             string context_s = "");
    bit passed = (observed === expected);
    record_compare(feature, passed, $sformatf("0x%0h", expected), $sformatf("0x%0h", observed),
                   context_s);
    return passed;
  endfunction

  // ------------------------------------------------------------------
  // Two-stream pairing (write_* handlers of the bench scoreboard).
  // ------------------------------------------------------------------

  // Enqueue one observed item of a feature and pair whatever is pairable.
  // A lane separates independent in-order streams of one feature.
  function void push_observed(string feature, uvm_object item, string lane = "");
    string key = pair_key(feature, lane);
    check_registered(feature, "push_observed");
    m_observed_q[key].push_back(item);
    try_pair(key);
  endfunction

  // Enqueue one expected item of a feature (from its reference model).
  function void push_expected(string feature, uvm_object item, string lane = "");
    string key = pair_key(feature, lane);
    check_registered(feature, "push_expected");
    m_expected_q[key].push_back(item);
    try_pair(key);
  endfunction

  // Drop every expected item of a feature still waiting for its
  // observation, on every lane or on `lane` alone: a reset cancels the
  // transactions they predicted. Returns how many were dropped.
  function int unsigned flush_expected(string feature, string lane = AllLanes);
    string only = (lane == AllLanes) ? "" : pair_key(feature, lane);
    int unsigned dropped = 0;
    foreach (m_expected_q[key]) begin
      if (m_key_feature[key] != feature || (only != "" && key != only)) continue;
      dropped += m_expected_q[key].size();
      m_expected_q[key].delete();
    end
    return dropped;
  endfunction

  // Bench hook: compare one observed/expected pair of a feature through
  // compare_equal() or record_compare(). Reached only through try_pair().
  virtual function void compare_pair(string feature, uvm_object observed, uvm_object expected);
    `uvm_fatal(get_type_name(), $sformatf("compare_pair() not implemented for feature `%s`", feature
               ))
  endfunction

  protected function void try_pair(string key);
    if (!m_observed_q.exists(key) || !m_expected_q.exists(key)) return;
    while (m_observed_q[key].size() > 0 && m_expected_q[key].size() > 0) begin
      uvm_object observed = m_observed_q[key].pop_front();
      uvm_object expected = m_expected_q[key].pop_front();
      compare_pair(m_key_feature[key], observed, expected);
    end
  endfunction

  // Queue key of a feature's lane; the bare feature name when unlaned.
  protected function string pair_key(string feature, string lane);
    string key = (lane == "") ? feature : {feature, "/", lane};
    m_key_feature[key] = feature;
    return key;
  endfunction

  // One error per lane of a feature that holds items at check_phase;
  // returns how many items they hold.
  protected function int unsigned report_unpaired(string feature, ref uvm_object q[string][$],
                                                  input string what);
    int unsigned total = 0;
    foreach (q[key]) begin
      if (m_key_feature[key] != feature || q[key].size() == 0) continue;
      total += q[key].size();
      `uvm_error({name_tag, "_", feature, "_chk"}, $sformatf(
                 "%0d %s (feature %s, lane %s)", q[key].size(), what, feature, key))
    end
    return total;
  endfunction

  protected function void check_registered(string feature, string what);
    if (!m_features.exists(feature))
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s on unregistered feature `%s`; known: %p", what, feature, m_feature_order))
  endfunction

  // CHK-SB-<FEATURE>: upper case, underscores as dashes.
  protected function string feature_check_id(string feature);
    string id = feature.toupper();
    foreach (id[i]) if (id[i] == "_") id[i] = "-";
    return {"CHK-SB-", id};
  endfunction

endclass : ocah_scoreboard
