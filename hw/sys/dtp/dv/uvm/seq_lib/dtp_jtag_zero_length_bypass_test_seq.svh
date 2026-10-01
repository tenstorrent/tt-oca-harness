// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// dtp_jtag_zero_length_bypass_test scenario sequence (cocotb twin:
// seq_lib/dtp_jtag_zero_length_bypass_test_seq.py). The single-TAP leg
// checks ZERO_LENGTH_BYPASS direct TDI-to-TDO pass-through
// (CHK-ZLB-PASSTHROUGH) across directed + seeded random patterns against
// one plain BYPASS delay reference point (CHK-BYPASS-DELAY). The chain leg
// selects a seeded STAP with a downstream TAP behind it and scans the same
// chain under ZERO_LENGTH_BYPASS and then under BYPASS. With the PTAP 3DCR
// select set, ZERO_LENGTH_BYPASS is BYPASS: under both, the bit after the
// STAP chain is the bypass register's captured 0 and the marker follows it
// (CHK-ZLB-CHAIN-ALIGN), and the captured chain matches the reference model
// (CHK-SCAN-CHAIN).

class dtp_jtag_zero_length_bypass_test_seq extends dtp_scan_base_test_seq;
  `uvm_object_utils(dtp_jtag_zero_length_bypass_test_seq)

  function new(string name = "dtp_jtag_zero_length_bypass_test_seq");
    super.new(name);
  endfunction

  task body();
    seed_scenario_rng();
    attach_family_checker({
                          "CHK-TAP-RESET-TLR",
                          "CHK-ZLB-PASSTHROUGH",
                          "CHK-BYPASS-DELAY",
                          "CHK-ZLB-CHAIN-ALIGN",
                          "CHK-SCAN-CHAIN",
                          "CHK-SCAN-COUNT",
                          "CHK-SCAN-IR-LEN",
                          "CHK-SCAN-DR-LEN",
                          "CHK-NONVAC"
                          });
    attach_downstream_taps();
    reset_to_tlr();
    check_zero_length_bypass_patterns(64);
    check_bypass_delay(BYPASS_INSTR, 64'hA5A5_5A5A_C3C3_3C3C);
    check_zero_length_bypass_chain();
    finalize_family_checker();
  endtask

  // Scan one STAP chain under ZERO_LENGTH_BYPASS and under BYPASS. With the
  // PTAP 3DCR select set, a seeded STAP selected, and its downstream TAP on
  // DS_TDR, a ZERO_LENGTH_BYPASS scan writes a seeded DS_TDR value and a
  // maintain scan reads the chain back (CHK-SCAN-CHAIN); under BYPASS the
  // same chain reads back the same way. Every scan carries a marker whose
  // position proves the PTAP adds its one bypass bit under both
  // (CHK-ZLB-CHAIN-ALIGN).
  protected task check_zero_length_bypass_chain();
    int unsigned stap = $urandom_range(int'(ST_EXTRA0), int'(ST_IO));
    string ctx = {"zlb_chain.", stap_name(stap)};
    int sib_en[int];
    int no_sib[int];
    dtp_stap_3dcr_state_t payloads[int];
    dtp_stap_3dcr_state_t no_pl[int];
    bit [63:0] ds_ir[int];
    bit [63:0] ds_values[int];
    bit [63:0] no_ir[int];
    bit [63:0] opcode, value, marker, captured, unused;
    if (!ds_attached(stap))
      `uvm_fatal(get_type_name(), {"no downstream TAP behind STAP ", stap_name(stap)})
    if (!stap_model.ds[stap].opcode_of(StapDsTdrName, opcode))
      `uvm_fatal(get_type_name(), {"downstream device has no ", StapDsTdrName})
    value          = random_pattern(stap_model.ds[stap].regs[opcode].width);
    marker         = random_pattern(DtpScanMarkerWidth) | (64'h1 << (DtpScanMarkerWidth - 1));
    // config_hold, stap_sel, tms_hold
    payloads[stap] = '{bit'($urandom_range(1)), 1'b1, bit'($urandom_range(1))};
    `uvm_info(get_type_name(),
              $sformatf(
                  "ZERO_LENGTH_BYPASS in the STAP chain: %s %s=0x%0h marker=0x%04h 3DCR payload=%p",
                  stap_name(stap), StapDsTdrName, value, marker, payloads[stap]), UVM_LOW)

    log_step("1", $sformatf("Select STAP %s with composed TAP_3DCR scans", stap_name(stap)));
    stap_chain_flush({ctx, ".flush"});
    sib_en[stap] = 1;
    stap_chain_write('0, 1, 1, sib_en, no_pl, {ctx, ".open_sib"}, unused);
    stap_chain_write('0, -1, -1, no_sib, payloads, {ctx, ".select"}, unused);

    log_step("2", "One network-wide IR scan: ZERO_LENGTH_BYPASS and downstream DS_TDR");
    ds_ir[stap] = opcode;
    stap_chain_ir_write('0, 6'(ZERO_LENGTH_BYPASS_INSTR), ds_ir, no_sib, no_pl, {ctx, ".load_zlb"},
                        unused);

    log_step("3", "ZERO_LENGTH_BYPASS: write DS_TDR through the chain, then read it back");
    ds_values[stap] = value;
    stap_chain_write_ds('0, -1, -1, no_sib, no_pl, ds_values, {ctx, ".zlb_write"}, captured, marker,
                        -1, DTP_SCAN_ZLB);
    check_zlb_chain_align(captured, marker, DTP_SCAN_ZLB, {ctx, ".zlb_write"});
    stap_chain_maintain('0, {ctx, ".zlb_read"}, captured, marker, DTP_SCAN_ZLB);
    check_stap_chain_readback(captured, '0, {ctx, ".zlb_read"}, DTP_SCAN_ZLB);
    check_zlb_chain_align(captured, marker, DTP_SCAN_ZLB, {ctx, ".zlb_read"});

    log_step("4", "BYPASS: the same chain reads back behind the same bypass register");
    stap_chain_ir_write('0, 6'(BYPASS_INSTR), no_ir, no_sib, no_pl, {ctx, ".load_bypass"}, unused);
    stap_chain_maintain('0, {ctx, ".bypass_read"}, captured, marker, DTP_SCAN_BYPASS);
    check_stap_chain_readback(captured, '0, {ctx, ".bypass_read"}, DTP_SCAN_BYPASS);
    check_zlb_chain_align(captured, marker, DTP_SCAN_BYPASS, {ctx, ".bypass_read"});

    stap_chain_flush({ctx, ".cleanup"});
  endtask

  // CHK-ZLB-CHAIN-ALIGN: with the PTAP 3DCR select set, the bit after the
  // STAP chain is the bypass register's captured 0 and the marker follows
  // it, under ZERO_LENGTH_BYPASS and BYPASS alike. The STAP chain length
  // comes from the TAP_3DCR layout less the PTAP 3DCR, which holds no PTAP
  // bypass bit. Valid after a scan that leaves the chain layout as it found
  // it, such as a maintain scan or a downstream register write.
  protected function void check_zlb_chain_align(bit [63:0] captured, bit [63:0] marker,
                                                dtp_scan_kind_e kind, string context_s);
    dtp_stap_3dcr_model::layout_entry_t layout[$];
    string name = (kind == DTP_SCAN_ZLB) ? "ZERO_LENGTH_BYPASS: captured 0, then the marker"
                                         : "BYPASS: captured 0, then the marker";
    int latency = msb_index(captured) + 1 - int'(DtpScanMarkerWidth);
    int unsigned chain_len;
    bit [63:0] observed;
    if (kind != DTP_SCAN_ZLB && kind != DTP_SCAN_BYPASS)
      `uvm_fatal(get_type_name(), $sformatf("no alignment rule for a %s scan", kind.name()))
    stap_model.chain_layout('0, layout, DTP_SCAN_DR);
    chain_len = layout.size() - Ptap3dcrWidth;
    observed  = (captured >> chain_len) & bit_mask(DtpScanMarkerWidth + 1);
    family_check(
        "CHK-ZLB-CHAIN-ALIGN", name, observed, marker << 1, $sformatf(
        "%s chain_len=%0d latency=%0d captured=0x%0h", context_s, chain_len, latency, captured));
  endfunction

endclass : dtp_jtag_zero_length_bypass_test_seq
