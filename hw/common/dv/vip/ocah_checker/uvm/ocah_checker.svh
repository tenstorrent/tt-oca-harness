// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Protocol-neutral SV-UVM checker-evidence base -- the SV analogue of the
// shared cocotb OcahChecker (cocotb/checker.py), emitting the exact grammar
// from hw/common/dv/docs/vip-checker-model.adoc:
//
//   CHK-<ID> PASS expected=<v> observed=<v> context=<details>
//   CHK-<ID> FAIL expected=<v> observed=<v> context=<details>
//   CHECKER_SUMMARY name=<n> checks=N passed=N failed=N missing=N
//
// PASS evidence goes through `uvm_info (UVM_LOW); FAIL evidence goes through
// `uvm_error so the uvm-log parser (parsers.toml [policy.uvm-log]) fails the
// run. finalize() emits the summary once and errors on zero checks (when the
// owning cfg requires checks) and on missing required IDs.
//
// This class owns evidence mechanics only. Protocol legality belongs in the
// checker shipped by each ocah_<protocol>_vip package, which extends this
// base -- the same split the cocotb flow draws between ocah_checker and the
// per-protocol checkers.

class ocah_checker extends uvm_object;
  `uvm_object_utils(ocah_checker)

  string       name_tag = "ocah";
  int unsigned check_count;
  int unsigned pass_count;
  int unsigned fail_count;
  string       required_ids[$];
  protected bit m_seen_ids[string];
  protected bit m_finalized;

  function new(string name = "ocah_checker");
    super.new(name);
  endfunction

  // Enforce CHK-[A-Z0-9][A-Z0-9_-]* (invalid IDs are configuration defects).
  function bit validate_id(string check_id);
    if (check_id.len() < 5 || check_id.substr(0, 3) != "CHK-") return 1'b0;
    for (int i = 4; i < check_id.len(); i++) begin
      byte c = check_id.getc(i);
      if (!((c >= "A" && c <= "Z") || (c >= "0" && c <= "9") || c == "_" || (c == "-" && i > 4)))
        return 1'b0;
    end
    return 1'b1;
  endfunction

  protected virtual function bit record(string check_id, bit passed, string expected_s,
                                        string observed_s, string context_s);
    string message;
    if (!validate_id(check_id))
      `uvm_fatal(get_type_name(), $sformatf(
                 "invalid checker ID %s; expected CHK-[A-Z0-9][A-Z0-9_-]*", check_id))
    check_count++;
    m_seen_ids[check_id] = 1'b1;
    message = $sformatf("%s %s expected=%s observed=%s context=%s",
                            check_id, passed ? "PASS" : "FAIL",
                            expected_s, observed_s,
                            context_s.len() ? context_s : "-");
    if (passed) begin
      pass_count++;
      `uvm_info(name_tag, message, UVM_LOW)
    end else begin
      fail_count++;
      `uvm_error(name_tag, message)
    end
    return passed;
  endfunction

  virtual function bit expect_equal(string check_id, bit [63:0] observed, bit [63:0] expected,
                                    string context_s = "");
    return record(
        check_id,
        observed === expected,
        $sformatf(
            "0x%0h", expected
        ),
        $sformatf(
            "0x%0h", observed
        ),
        context_s
    );
  endfunction

  virtual function bit expect_true(string check_id, bit condition, string context_s = "");
    return record(check_id, condition === 1'b1, "true", condition === 1'b1 ? "true" : "false",
                  context_s);
  endfunction

  virtual function bit expect_equal_words(string check_id, bit [63:0] observed[$],
                                          bit [63:0] expected[$], string context_s = "");
    bit passed = (observed.size() == expected.size());
    if (passed) begin
      foreach (observed[i]) begin
        if (observed[i] !== expected[i]) passed = 1'b0;
      end
    end
    return record(
        check_id, passed, words_to_string(expected), words_to_string(observed), context_s
    );
  endfunction

  protected function string words_to_string(bit [63:0] words[$]);
    string s = "(";
    foreach (words[i]) s = {s, i ? "," : "", $sformatf("0x%0h", words[i])};
    return {s, ")"};
  endfunction

  // Emit the summary exactly once; error on defects.
  virtual function void finalize(bit require_checks);
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
        missing_names = {missing_names, missing_names.len() ? ", " : "", required_ids[i]};
      end
    end
    `uvm_info(name_tag, $sformatf(
              "CHECKER_SUMMARY name=%s checks=%0d passed=%0d failed=%0d missing=%0d",
              name_tag,
              check_count,
              pass_count,
              fail_count,
              missing
              ), UVM_LOW)
    if (require_checks && check_count == 0)
      `uvm_error(name_tag, "CHECKER_SUMMARY zero checks executed")
    if (missing > 0) `uvm_error(name_tag, {"CHECKER_SUMMARY missing required IDs: ", missing_names})
    // Failed checks already produced UVM_ERROR inline.
  endfunction

  virtual function void clear();
    check_count = 0;
    pass_count  = 0;
    fail_count  = 0;
    m_seen_ids.delete();
    m_finalized = 1'b0;
  endfunction

endclass : ocah_checker
