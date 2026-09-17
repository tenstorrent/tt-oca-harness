// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG TAP checker with named evidence -- the SV analogue of the cocotb
// ocah_jtag_vip.OcahJtagChecker. The named-evidence mechanics
// (CHK-*/CHECKER_SUMMARY grammar, severity routing, finalization) are
// inherited from ocah_checker_uvm_pkg::ocah_checker; this class owns the
// IEEE 1149.1 TAP reference-model checks for the core TAP contracts:
// reset-to-TLR, per-step state transitions, the five-TMS-high reset walk,
// BYPASS one-TCK latency, and reconstructed scan lengths. Observed TAP states
// are taken in the common one-hot exported-observable form (bit index == the
// VIP enum's IEEE state number).
//
// Rule provenance: all TAP contracts are implemented from the public IEEE
// Std 1149.1 clause descriptions. No third-party protocol-checker source
// was consulted or copied.

class ocah_jtag_checker extends ocah_checker;
  `uvm_object_utils(ocah_jtag_checker)

  // TAP reference model (shared instance may be injected after construction).
  ocah_jtag_ref_model m_ref;

  function new(string name = "ocah_jtag_checker");
    super.new(name);
    name_tag = "ocah_jtag";
    m_ref = ocah_jtag_ref_model::type_id::create({name, ".ref_model"});
  endfunction

  virtual function void clear();
    super.clear();
    m_ref.reset_model();
  endfunction

  // ------------------------------------------------------------------
  // TAP reference model (owned ocah_jtag_ref_model); the checker's public
  // API forwards to it.
  // ------------------------------------------------------------------

  function ocah_jtag_tap_state_e model_state();
    return m_ref.state();
  endfunction

  function void reset_model();
    m_ref.reset_model();
  endfunction

  function void sync_state(ocah_jtag_tap_state_e state);
    m_ref.sync_state(state);
  endfunction

  static function bit [63:0] predict_bypass_tdo(bit [63:0] pattern, int unsigned width,
                                                bit capture_bit = 1'b0);
    return ocah_jtag_ref_model::predict_bypass_tdo(pattern, width, capture_bit);
  endfunction

  // ------------------------------------------------------------------
  // Named TAP-contract checks. Observed states arrive in the exported
  // one-hot form; the model's helpers label invalid encodings instead of
  // aborting.
  // ------------------------------------------------------------------

  protected function string onehot_label(bit [15:0] onehot);
    return ocah_jtag_ref_model::onehot_label(onehot);
  endfunction

  protected function bit onehot_to_state(bit [15:0] onehot, output ocah_jtag_tap_state_e state);
    return ocah_jtag_ref_model::onehot_to_state(onehot, state);
  endfunction

  // Named check: a TAP reset must leave the controller in TLR.
  function bit check_reset_to_tlr(bit [15:0] observed_onehot, string context_s = "",
                                  string check_id = "CHK-TAP-RESET-TLR");
    reset_model();
    return record(
        check_id,
        observed_onehot === 16'h0001,
        onehot_label(
            16'h0001
        ),
        onehot_label(
            observed_onehot
        ),
        context_s
    );
  endfunction

  // Named check: one TMS step must land in the reference-model state.
  function bit check_state_step(bit tms, bit [15:0] observed_onehot, string context_s = "",
                                string check_id = "CHK-TAP-STATE");
    ocah_jtag_tap_state_e previous = m_ref.state();
    ocah_jtag_tap_state_e predicted;
    ocah_jtag_tap_state_e observed;
    bit [15:0] expected_onehot;
    bit passed;
    predicted = m_ref.step(tms);
    expected_onehot = 16'h1 << int'(predicted);
    passed = record(check_id, observed_onehot === expected_onehot,
                        $sformatf("%s(0x%04h)", predicted.name(), expected_onehot),
                        onehot_label(observed_onehot),
                        $sformatf("prev=%s tms=%0b %s", previous.name(), tms, context_s));
    // Keep later predictions meaningful by re-aligning to what the DUT
    // actually did (matters when the run aggregates evidence failures).
    if (!passed && onehot_to_state(observed_onehot, observed)) m_ref.sync_state(observed);
    return passed;
  endfunction

  // Named check: >= five TMS-high TCK cycles must force TLR from any state.
  function bit check_tms_ones_to_tlr(int unsigned ones_count, bit [15:0] observed_onehot,
                                     string context_s = "", string check_id = "CHK-TAP-TLR-TMS5");
    if (ones_count < 5)
      `uvm_fatal(get_type_name(), $sformatf(
                 "IEEE 1149.1 guarantees TLR only after 5+ TMS-high cycles, got %0d", ones_count))
    reset_model();
    return record(
        check_id,
        observed_onehot === 16'h0001,
        onehot_label(
            16'h0001
        ),
        onehot_label(
            observed_onehot
        ),
        $sformatf(
            "tms_ones=%0d %s", ones_count, context_s)
    );
  endfunction

  // Named check: BYPASS TDO equals TDI delayed by exactly one TCK.
  function bit check_bypass_latency(bit [63:0] observed_tdo, bit [63:0] pattern, int unsigned width,
                                    bit capture_bit = 1'b0, string context_s = "",
                                    string check_id = "CHK-BYPASS-LATENCY");
    bit [63:0] expected = predict_bypass_tdo(pattern, width, capture_bit);
    bit [63:0] mask = (width == 0) ? '0 :
                          (width < 64) ? ((64'h1 << width) - 1) : '1;
    return record(
        check_id,
        (observed_tdo & mask) === expected,
        $sformatf(
            "0x%0h", expected
        ),
        $sformatf(
            "0x%0h", observed_tdo & mask
        ),
        $sformatf(
            "width=%0d pattern=0x%0h %s", width, pattern, context_s)
    );
  endfunction

  // Named check: reconstructed scan bit count equals the driven width.
  function bit check_scan_length(ocah_jtag_scan_item item, int unsigned expected_width,
                                 string context_s = "");
    return record(
        item.is_ir ? "CHK-SCAN-IR-LEN" : "CHK-SCAN-DR-LEN",
        item.bit_count == expected_width,
        $sformatf(
            "%0d", expected_width
        ),
        $sformatf(
            "%0d", item.bit_count
        ),
        $sformatf(
            "kind=%s %s", item.is_ir ? "IR" : "DR", context_s)
    );
  endfunction

endclass : ocah_jtag_checker
