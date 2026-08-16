// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG TAP checker with named evidence — the SV analogue of the cocotb
// ocah_jtag_vip.OcahJtagChecker (issue tt-oca-hw#3296). Carries the same
// named-evidence mechanics as ocah_axi_checker (the SV port of
// ocah_checker/cocotb/checker.py), emitting the exact grammar from
// hw/common/dv/docs/vip-checker-model.adoc:
//
//   CHK-<ID> PASS expected=<v> observed=<v> context=<details>
//   CHK-<ID> FAIL expected=<v> observed=<v> context=<details>
//   CHECKER_SUMMARY name=<n> checks=N passed=N failed=N missing=N
//
// plus IEEE 1149.1 TAP reference-model checks for the core TAP contracts:
// reset-to-TLR, per-step state transitions, the five-TMS-high reset walk,
// BYPASS one-TCK latency, and reconstructed scan lengths. Observed TAP
// states are taken in the common one-hot exported-observable form (bit
// index == the VIP enum's IEEE state number).
//
// Rule provenance: all TAP contracts are implemented from the public IEEE
// Std 1149.1 clause descriptions. No third-party protocol-checker source
// was consulted or copied.

class ocah_jtag_checker extends uvm_object;
    `uvm_object_utils(ocah_jtag_checker)

    string       name_tag = "ocah_jtag";
    int unsigned check_count;
    int unsigned pass_count;
    int unsigned fail_count;
    string       required_ids[$];
    protected bit m_seen_ids[string];
    protected bit m_finalized;

    protected ocah_jtag_tap_state_e m_model = OCAH_JTAG_TEST_LOGIC_RESET;

    function new(string name = "ocah_jtag_checker");
        super.new(name);
    endfunction

    // ------------------------------------------------------------------
    // Named-evidence mechanics (same grammar and policy as ocah_axi_checker).
    // ------------------------------------------------------------------

    // Enforce CHK-[A-Z0-9][A-Z0-9_-]* (invalid IDs are configuration defects).
    function bit validate_id(string check_id);
        if (check_id.len() < 5 || check_id.substr(0, 3) != "CHK-")
            return 1'b0;
        for (int i = 4; i < check_id.len(); i++) begin
            byte c = check_id.getc(i);
            if (!((c >= "A" && c <= "Z") || (c >= "0" && c <= "9") ||
                  c == "_" || (c == "-" && i > 4)))
                return 1'b0;
        end
        return 1'b1;
    endfunction

    protected function bit record(
        string check_id,
        bit    passed,
        string expected_s,
        string observed_s,
        string context_s
    );
        string message;
        if (!validate_id(check_id))
            `uvm_fatal(get_type_name(), $sformatf(
                "invalid checker ID %s; expected CHK-[A-Z0-9][A-Z0-9_-]*", check_id))
        check_count++;
        m_seen_ids[check_id] = 1'b1;
        message = $sformatf("%s %s expected=%s observed=%s context=%s",
                            check_id, passed ? "PASS" : "FAIL",
                            expected_s, observed_s,
                            (context_s.len() != 0) ? context_s : "-");
        if (passed) begin
            pass_count++;
            `uvm_info(name_tag, message, UVM_LOW)
        end else begin
            fail_count++;
            `uvm_error(name_tag, message)
        end
        return passed;
    endfunction

    function bit expect_equal(
        string     check_id,
        bit [63:0] observed,
        bit [63:0] expected,
        string     context_s = ""
    );
        return record(check_id, observed === expected,
                      $sformatf("0x%0h", expected), $sformatf("0x%0h", observed),
                      context_s);
    endfunction

    function bit expect_true(string check_id, bit condition, string context_s = "");
        return record(check_id, condition === 1'b1,
                      "true", condition === 1'b1 ? "true" : "false", context_s);
    endfunction

    // Emit the summary exactly once; error on defects.
    function void finalize(bit require_checks);
        int unsigned missing = 0;
        string missing_names = "";
        if (m_finalized) begin
            `uvm_error(name_tag, "CHECKER finalize() called more than once")
            return;
        end
        m_finalized = 1'b1;
        foreach (required_ids[i]) begin
            if (!m_seen_ids.exists(required_ids[i])) begin
                missing++;
                missing_names = {missing_names, (missing_names.len() != 0) ? ", " : "",
                                 required_ids[i]};
            end
        end
        `uvm_info(name_tag, $sformatf(
            "CHECKER_SUMMARY name=%s checks=%0d passed=%0d failed=%0d missing=%0d",
            name_tag, check_count, pass_count, fail_count, missing), UVM_LOW)
        if (require_checks && check_count == 0)
            `uvm_error(name_tag, "CHECKER_SUMMARY zero checks executed")
        if (missing > 0)
            `uvm_error(name_tag, {"CHECKER_SUMMARY missing required IDs: ", missing_names})
        // Failed checks already produced UVM_ERROR inline.
    endfunction

    function void clear();
        check_count = 0;
        pass_count  = 0;
        fail_count  = 0;
        m_seen_ids.delete();
        m_finalized = 1'b0;
        m_model     = OCAH_JTAG_TEST_LOGIC_RESET;
    endfunction

    // ------------------------------------------------------------------
    // TAP reference model.
    // ------------------------------------------------------------------

    function ocah_jtag_tap_state_e model_state();
        return m_model;
    endfunction

    // Model a TAP reset (TRST assertion or a TMS-high walk) to TLR.
    function void reset_model();
        m_model = OCAH_JTAG_TEST_LOGIC_RESET;
    endfunction

    // Re-align the model after driver-internal navigation (e.g. the scan
    // legs that return to Run-Test/Idle without per-step visibility).
    function void sync_state(ocah_jtag_tap_state_e state);
        m_model = state;
    endfunction

    // Expected LSB-first TDO for a scan through the one-bit BYPASS register:
    // bit 0 is the captured bit, bits [width-1:1] the first width-1 pattern
    // bits (exactly one TCK of TDI-to-TDO delay).
    static function bit [63:0] predict_bypass_tdo(
        bit [63:0]   pattern,
        int unsigned width,
        bit          capture_bit = 1'b0
    );
        bit [63:0] mask;
        if (width == 0) return '0;
        mask = (width < 64) ? ((64'h1 << width) - 1) : '1;
        return (({pattern[62:0], capture_bit}) & mask);
    endfunction

    // ------------------------------------------------------------------
    // Named TAP-contract checks. Observed states arrive in the exported
    // one-hot form; helpers label invalid encodings instead of aborting.
    // ------------------------------------------------------------------

    protected function string onehot_label(bit [15:0] onehot);
        ocah_jtag_tap_state_e state;
        if (onehot_to_state(onehot, state))
            return $sformatf("%s(0x%04h)", state.name(), onehot);
        return $sformatf("INVALID(0x%04h)", onehot);
    endfunction

    protected function bit onehot_to_state(
        bit [15:0] onehot,
        output ocah_jtag_tap_state_e state
    );
        if ($countones(onehot) != 1) return 1'b0;
        for (int i = 0; i < 16; i++) begin
            if (onehot[i]) begin
                state = ocah_jtag_tap_state_e'(i);
                return 1'b1;
            end
        end
        return 1'b0;
    endfunction

    // Named check: a TAP reset must leave the controller in TLR.
    function bit check_reset_to_tlr(
        bit [15:0] observed_onehot,
        string     context_s = "",
        string     check_id = "CHK-TAP-RESET-TLR"
    );
        reset_model();
        return record(check_id, observed_onehot === 16'h0001,
                      onehot_label(16'h0001), onehot_label(observed_onehot),
                      context_s);
    endfunction

    // Named check: one TMS step must land in the reference-model state.
    function bit check_state_step(
        bit        tms,
        bit [15:0] observed_onehot,
        string     context_s = "",
        string     check_id = "CHK-TAP-STATE"
    );
        ocah_jtag_tap_state_e previous = m_model;
        ocah_jtag_tap_state_e observed;
        bit [15:0] expected_onehot;
        bit passed;
        m_model = ocah_jtag_next_state(previous, tms);
        expected_onehot = 16'h1 << int'(m_model);
        passed = record(check_id, observed_onehot === expected_onehot,
                        $sformatf("%s(0x%04h)", m_model.name(), expected_onehot),
                        onehot_label(observed_onehot),
                        $sformatf("prev=%s tms=%0b %s", previous.name(), tms, context_s));
        // Keep later predictions meaningful by re-aligning to what the DUT
        // actually did (matters when the run aggregates evidence failures).
        if (!passed && onehot_to_state(observed_onehot, observed))
            m_model = observed;
        return passed;
    endfunction

    // Named check: >= five TMS-high TCK cycles must force TLR from any state.
    function bit check_tms_ones_to_tlr(
        int unsigned ones_count,
        bit [15:0]   observed_onehot,
        string       context_s = "",
        string       check_id = "CHK-TAP-TLR-TMS5"
    );
        if (ones_count < 5)
            `uvm_fatal(get_type_name(), $sformatf(
                "IEEE 1149.1 guarantees TLR only after 5+ TMS-high cycles, got %0d",
                ones_count))
        reset_model();
        return record(check_id, observed_onehot === 16'h0001,
                      onehot_label(16'h0001), onehot_label(observed_onehot),
                      $sformatf("tms_ones=%0d %s", ones_count, context_s));
    endfunction

    // Named check: BYPASS TDO equals TDI delayed by exactly one TCK.
    function bit check_bypass_latency(
        bit [63:0]   observed_tdo,
        bit [63:0]   pattern,
        int unsigned width,
        bit          capture_bit = 1'b0,
        string       context_s = "",
        string       check_id = "CHK-BYPASS-LATENCY"
    );
        bit [63:0] expected = predict_bypass_tdo(pattern, width, capture_bit);
        bit [63:0] mask = (width == 0) ? '0 :
                          (width < 64) ? ((64'h1 << width) - 1) : '1;
        return record(check_id, (observed_tdo & mask) === expected,
                      $sformatf("0x%0h", expected),
                      $sformatf("0x%0h", observed_tdo & mask),
                      $sformatf("width=%0d pattern=0x%0h %s", width, pattern, context_s));
    endfunction

    // Named check: reconstructed scan bit count equals the driven width.
    function bit check_scan_length(
        ocah_jtag_scan_item item,
        int unsigned        expected_width,
        string              context_s = ""
    );
        return record(item.is_ir ? "CHK-SCAN-IR-LEN" : "CHK-SCAN-DR-LEN",
                      item.bit_count == expected_width,
                      $sformatf("%0d", expected_width),
                      $sformatf("%0d", item.bit_count),
                      $sformatf("kind=%s %s", item.is_ir ? "IR" : "DR", context_s));
    endfunction

endclass : ocah_jtag_checker
