// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Debug-disable matrix over the eight scan-side gate fields — the SV
// analogue of the cocotb dtp_dbg_disable_scan_matrix_test_seq. One compact
// matrix instead of eight duplicate wrappers: deterministic one-hot rows,
// the all-clear and all-disabled boundary masks, and seeded multi-hot
// masks. Every row drives the full disable vector, then proves each
// resource's allowed/blocked outcome with temporal windows and chain
// readbacks: all three iJTAG SIBs requested open follow their gates; the
// four STAPs are configured ungated in one composed pass, then the row
// mask is asserted — gated ports stop forwarding (tms parked at the
// stored tms_hold) and ignore a clearing update while ungated ports
// accept it, and the extended host scan interface follows stap_host.
// After the all_disabled row, releasing
// every gate without reset must not replay any gated open attempt, and a
// sanctioned all-clear row recovers.
//
// The default 6 seeded multi-hot rows make 16 rows per pass (1 all_clear +
// 8 one-hot + 6 multi-hot + 1 all_disabled), so one matrix pass meets the
// 16-iteration floor with seeded rows; +DTP_DBG_DISABLE_MULTI_HOT_ROWS
// overrides. The cocotb flow's Python DtpDbgDisableFcov ledger is
// cocotb-only.

class dtp_dbg_disable_scan_matrix_test_seq extends dtp_scan_base_test_seq;
  `uvm_object_utils(dtp_dbg_disable_scan_matrix_test_seq)

  localparam int unsigned ScanFieldCount = 8;

  int unsigned multi_hot_rows = 6;

  function new(string name = "dtp_dbg_disable_scan_matrix_test_seq");
    super.new(name);
  endfunction

  protected static function string scan_field_name(int unsigned idx);
    case (idx)
      0: return "stap_io";
      1: return "stap_smc";
      2: return "stap_sep";
      3: return "stap_extra";
      4: return "stap_host";
      5: return "dft_secure";
      6: return "dft_nonsecure";
      default: return "dfd";
    endcase
  endfunction

  protected static function sep_lifecycle_ctrl_pkg::dbg_disable_t scan_mask_from_bits(
      bit [ScanFieldCount-1:0] bits);
    sep_lifecycle_ctrl_pkg::dbg_disable_t d = '0;
    d.stap_io       = bits[0];
    d.stap_smc      = bits[1];
    d.stap_sep      = bits[2];
    d.stap_extra    = bits[3];
    d.stap_host     = bits[4];
    d.dft_secure    = bits[5];
    d.dft_nonsecure = bits[6];
    d.dfd           = bits[7];
    return d;
  endfunction

  // Request all three SIBs open; each SIB's outcome follows its disable.
  protected task check_ijtag_row(sep_lifecycle_ctrl_pkg::dbg_disable_t d, string context_s);
    check_ijtag_pattern(3'b111, d, {context_s, ".ijtag"});
  endtask

  // Configure all four STAPs UNGATED in one composed pass, then assert
  // the row mask (the pattern the standalone stap_sel scenarios prove):
  // each port's outcome under the mask (forwarding vs quiet with tms
  // parked at the stored tms_hold=1) follows its disable, a gated
  // clearing update is ignored while ungated ports accept it (chain
  // readback against the model's gated-update semantics), and the
  // extended host scan interface follows stap_host. Configuring under
  // the gate instead couples stored 3DCR state across rows through the
  // chain's IR-scan-time client updates, so the row mask is asserted
  // only after the configuration is established.
  protected task check_stap_row(sep_lifecycle_ctrl_pkg::dbg_disable_t d, string context_s);
    int all_sib[int];
    dtp_stap_3dcr_state_t all_payloads[int];
    dtp_stap_3dcr_state_t clear_payloads[int];
    int no_sib[int];
    dtp_stap_3dcr_state_t no_pl[int];
    string watch[$];
    bit gates[DtpStapCount];
    bit [63:0] captured, unused;
    int unsigned edges;
    int unsigned counts[string];
    dtp_stap_3dcr_model::gates(d, gates);
    for (int unsigned s = 0; s < DtpStapCount; s++) begin
      all_sib[s] = 1;
      all_payloads[s]   = '{1'b1, 1'b1, 1'b1};
      clear_payloads[s] = '{1'b0, 1'b0, 1'b0};
      watch.push_back({stap_prefix(s), "_tdo_oen"});
      watch.push_back({stap_prefix(s), "_tms"});
    end
    watch.push_back("jtag_stap_host_select");
    watch.push_back("jtag_stap_host_shift_en");
    watch.push_back("jtag_stap_host_capture_en");
    watch.push_back("jtag_stap_host_update_en");

    // Establish the configuration with every gate clear.
    enable_all_debug();
    stap_chain_flush({context_s, ".flush"});
    stap_chain_write('0, 1, 1, all_sib, no_pl, {context_s, ".open_sibs"}, unused);
    stap_chain_write('0, -1, -1, no_sib, all_payloads, {context_s, ".write_3dcrs"}, unused);

    // Assert the row mask and observe under it.
    set_dbg_disable_full(d);
    start_scan_window(watch);
    stap_chain_maintain(d, {context_s, ".observe"}, captured);
    stop_scan_window(edges, counts);
    family_check("CHK-SCAN-WIN", "window edges nonvacuous", 64'(edges > 0), 64'd1, {
                 context_s, ".window"});

    // Gated ports stop forwarding with tms parked at the stored
    // tms_hold=1; ungated ports keep forwarding.
    for (int unsigned s = 0; s < DtpStapCount; s++)
      check_stap_forwarding(edges, counts, s, ~gates[s], context_s);

    if (d.stap_host) begin
      family_check("CHK-SCAN-WIN", "stap_host select gated quiet",
                   64'(counts["jtag_stap_host_select"]), 64'd0, context_s);
      family_check("CHK-SCAN-WIN", "stap_host shift_en gated quiet",
                   64'(counts["jtag_stap_host_shift_en"]), 64'd0, context_s);
      family_check("CHK-SCAN-WIN", "stap_host capture_en gated quiet",
                   64'(counts["jtag_stap_host_capture_en"]), 64'd0, context_s);
      family_check("CHK-SCAN-WIN", "stap_host update_en gated quiet",
                   64'(counts["jtag_stap_host_update_en"]), 64'd0, context_s);
    end else begin
      family_check("CHK-SCAN-WIN", "stap_host select active",
                   64'(counts["jtag_stap_host_select"] > 0), 64'd1, context_s);
      family_check("CHK-SCAN-WIN", "stap_host shift_en active",
                   64'(counts["jtag_stap_host_shift_en"] > 0), 64'd1, context_s);
    end
    check_stap_chain_readback(captured, d, {context_s, ".readback"});

    // Gated clearing update: ignored on gated ports, accepted on
    // ungated ones — the readback proves per-port gating exactly.
    stap_chain_write(d, -1, -1, no_sib, clear_payloads, {context_s, ".gated_clear_attempt"},
                     unused);
    stap_chain_maintain(d, {context_s, ".gated_clear_readback"}, captured);
    check_stap_chain_readback(captured, d, {context_s, ".gated_clear_readback"});

    // Cleanup with every gate clear so no stored 3DCR state couples
    // into the next row, then restore the row mask for the caller.
    enable_all_debug();
    stap_chain_flush({context_s, ".cleanup"});
    set_dbg_disable_full(d);
  endtask

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN",
                              "CHK-SCAN-LEN", "CHK-SCAN-CHAIN"};
    bit [ScanFieldCount-1:0] row_bits[$];
    string row_labels[$];
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    seed_scenario_rng();
    // Scenario-owned Shift-x exits: skip the scan-count cross-check.
    attach_family_checker(required, 1'b0);
    enable_all_debug();
    reset_to_tlr();

    row_bits.push_back('0);
    row_labels.push_back("all_clear");
    for (int unsigned f = 0; f < ScanFieldCount; f++) begin
      row_bits.push_back(ScanFieldCount'(1) << f);
      row_labels.push_back({"one_hot_", scan_field_name(f)});
    end
    for (int unsigned idx = 0; idx < multi_hot_rows; idx++) begin
      bit [ScanFieldCount-1:0] bits;
      do
      bits = ScanFieldCount'($urandom);
      while ($countones(
          bits
      ) < 2 || $countones(
          bits
      ) >= ScanFieldCount);
      row_bits.push_back(bits);
      row_labels.push_back($sformatf("multi_hot_%0d", idx));
    end
    row_bits.push_back('1);
    row_labels.push_back("all_disabled");

    foreach (row_bits[r]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: row=%s mask=0b%08b",
                r + 1,
                row_bits.size(),
                row_labels[r],
                row_bits[r]
                ), UVM_LOW)
      d = scan_mask_from_bits(row_bits[r]);
      check_ijtag_row(d, row_labels[r]);
      check_stap_row(d, row_labels[r]);
    end

    // Delayed-replay proof (the check_stored_sib_across_gate pattern):
    // close every SIB with a sanctioned write first — the SIB scan
    // registers RETAIN sanctioned configuration under a gate, so a SIB
    // left open by an earlier row re-arms on release and
    // is not a replay — then attempt a fully-gated open of all three,
    // release without reset, and prove no select pulses (a gated open
    // attempt that stuck would assert here).
    enable_all_debug();
    program_ijtag_sibs(3'b000, '0, "release.close");
    set_dbg_disable_full(scan_mask_from_bits('1));
    program_ijtag_sibs(3'b111, scan_mask_from_bits('1), "release.gated_open_attempt");
    enable_all_debug();
    check_ijtag_all_closed('0, "release.observe");

    check_ijtag_row('0, "recovery");
    check_stap_row('0, "recovery");

    finalize_family_checker();
  endtask

endclass : dtp_dbg_disable_scan_matrix_test_seq
