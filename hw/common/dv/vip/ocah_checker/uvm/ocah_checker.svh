// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Protocol-neutral SV-UVM checker-evidence base -- the SV twin of the shared
// cocotb OcahChecker (cocotb/checker.py), emitting the exact grammar from
// hw/common/dv/docs/vip-checker-model.adoc:
//
//   CHK-<ID> PASS expected=<v> observed=<v> context=<details>
//   CHK-<ID> FAIL expected=<v> observed=<v> context=<details>
//   CHECKER_SUMMARY name=<n> checks=N passed=N failed=N missing=N
//
// PASS evidence goes through `uvm_info (UVM_LOW); FAIL evidence goes through
// `uvm_error so the uvm-log parser (parsers.toml [policy.uvm-log]) fails the
// run. finalize() emits the summary once and errors on zero checks (unless
// the caller declares the stream idle with require_checks = 0), on missing
// required IDs, and on a second call.
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
      bit alnum = (c >= "A" && c <= "Z") || (c >= "0" && c <= "9");
      if (i == 4 && !alnum) return 1'b0;
      if (!(alnum || c == "_" || c == "-")) return 1'b0;
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

  // ------------------------------------------------------------------
  // Comparisons
  // ------------------------------------------------------------------

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

  // ------------------------------------------------------------------
  // Timeout evidence: the declared bound rides in the context.
  // ------------------------------------------------------------------

  virtual function bit expect_not_timed_out(string check_id, bit timed_out,
                                            longint unsigned timeout_ns, string context_s = "");
    return record(
        check_id,
        timed_out === 1'b0,
        "false",
        timed_out === 1'b1 ? "true" : "false",
        with_fields(
            context_s, $sformatf("timeout_ns=%0d", timeout_ns))
    );
  endfunction

  virtual function bit expect_timeout(string check_id, bit timed_out, longint unsigned timeout_ns,
                                      string context_s = "");
    return record(
        check_id,
        timed_out === 1'b1,
        "true",
        timed_out === 1'b1 ? "true" : "false",
        with_fields(
            context_s, $sformatf("timeout_ns=%0d", timeout_ns))
    );
  endfunction

  // ------------------------------------------------------------------
  // Reset, interrupt, and status evidence
  // ------------------------------------------------------------------

  // Write-one-to-clear status: the mask bits were set before the clearing
  // write and are clear after it; bits outside the mask are not judged.
  virtual function bit expect_rw1c(string check_id, bit [63:0] read_before, bit [63:0] read_after,
                                   bit [63:0] mask, string context_s = "");
    bit set_before = ((read_before & mask) === mask);
    return record(
        check_id,
        set_before && ((read_after & mask) === 64'h0),
        "0x0",
        $sformatf(
            "0x%0h", read_after & mask
        ),
        with_fields(
            context_s,
            $sformatf(
                "before=0x%0h after=0x%0h mask=0x%0h set_before=%s",
                read_before,
                read_after,
                mask,
                set_before ? "true" : "false"))
    );
  endfunction

  // Sticky status: the mask bits read set twice with no clearing write between.
  virtual function bit expect_sticky(string check_id, bit [63:0] read_first, bit [63:0] read_second,
                                     bit [63:0] mask, string context_s = "");
    bit set_first = ((read_first & mask) === mask);
    return record(
        check_id,
        set_first && ((read_second & mask) === mask),
        $sformatf(
            "0x%0h", mask
        ),
        $sformatf(
            "0x%0h", read_second & mask
        ),
        with_fields(
            context_s,
            $sformatf(
                "first=0x%0h second=0x%0h mask=0x%0h set_first=%s",
                read_first,
                read_second,
                mask,
                set_first ? "true" : "false"))
    );
  endfunction

  // Pulse-only event: asserted for the event (bit 1) and deasserted after
  // completion (bit 0), so the expected encoding is 0x3.
  virtual function bit expect_pulse(string check_id, bit asserted, bit deasserted,
                                    string context_s = "");
    bit [1:0] observed = {asserted === 1'b1, deasserted === 1'b1};
    return record(
        check_id,
        observed === 2'b11,
        "0x3",
        $sformatf(
            "0x%0h", observed
        ),
        with_fields(
            context_s,
            $sformatf(
                "asserted=%s deasserted=%s",
                asserted === 1'b1 ? "true" : "false",
                deasserted === 1'b1 ? "true" : "false"))
    );
  endfunction

  protected function string with_fields(string context_s, string fields);
    return context_s.len() ? {context_s, " ", fields} : fields;
  endfunction

  // ------------------------------------------------------------------
  // Finalization: one summary per checker.
  // ------------------------------------------------------------------

  // require_checks = 0 declares the stream idle for this scenario, so zero
  // checks pass; a retained failure or a missing required ID still errors.
  virtual function void finalize(bit require_checks = 1'b1);
    int unsigned missing = 0;
    string missing_names = "";
    if (m_finalized) begin
      `uvm_error(name_tag, $sformatf("CHECKER name=%s finalize() called more than once", name_tag))
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
