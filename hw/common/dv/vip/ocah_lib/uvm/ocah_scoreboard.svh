// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Scoreboard base: the feature registry behind the mandatory, always-on
// bench scoreboard. A bench <dut>_scoreboard registers one feature per
// predictor (add_feature), subscribes to VIP monitor streams, and records
// every comparison through compare_equal() or record_compare(): a mismatch
// is a uvm_error at once, carrying feature, expected, observed, and
// context. check_phase turns each feature into one CHK-SB-<FEATURE> record
// through the shared evidence recorder and finalizes it once; a required
// feature (require_feature, from the env cfg) that ends with zero
// comparisons fails the run, so a scenario cannot pass without exercising
// what it claims to check. Observed values come from a monitor stream;
// expected values come from configuration through a predictor, never from
// the observation. The cocotb twin is ocah_lib.OcahScoreboard.

class ocah_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(ocah_scoreboard)

    typedef struct {
        string       name;
        bit          required;
        int unsigned compares;
        int unsigned mismatches;
    } feature_t;

    // Evidence identity for the CHK-SB-* records and the mismatch report id.
    string name_tag = "ocah_scoreboard";
    ocah_checker m_evidence;

    protected feature_t m_features[string];
    protected string    m_feature_order[$];

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
            if (!f.required && f.compares == 0)
                continue;
            void'(m_evidence.expect_true(feature_check_id(f.name),
                (f.compares > 0) && (f.mismatches == 0),
                $sformatf("feature=%s compares=%0d mismatches=%0d required=%0d",
                          f.name, f.compares, f.mismatches, f.required)));
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
    function void record_compare(string feature, bit passed, string expected_s,
                                 string observed_s, string context_s = "");
        if (!m_features.exists(feature))
            `uvm_fatal(get_type_name(), $sformatf("compare on unregistered feature `%s`", feature))
        m_features[feature].compares++;
        if (passed) begin
            `uvm_info({name_tag, "_", feature, "_chk"}, $sformatf(
                "%s: expected=%s observed=%s context=%s", feature, expected_s, observed_s,
                context_s), UVM_MEDIUM)
            return;
        end
        m_features[feature].mismatches++;
        `uvm_error({name_tag, "_", feature, "_chk"}, $sformatf(
            "%s mismatch: expected=%s observed=%s context=%s", feature, expected_s, observed_s,
            context_s))
    endfunction

    // Integer comparison with four-state safety (=== on the observed value).
    function bit compare_equal(string feature, bit [63:0] observed, bit [63:0] expected,
                               string context_s = "");
        bit passed = (observed === expected);
        record_compare(feature, passed, $sformatf("0x%0h", expected),
                       $sformatf("0x%0h", observed), context_s);
        return passed;
    endfunction

    // CHK-SB-<FEATURE>: upper case, underscores as dashes.
    protected function string feature_check_id(string feature);
        string id = feature.toupper();
        foreach (id[i])
            if (id[i] == "_")
                id[i] = "-";
        return {"CHK-SB-", id};
    endfunction

endclass : ocah_scoreboard
