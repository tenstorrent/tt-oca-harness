// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// STAP/3DCR scan scenarios — the SV analogue of the cocotb
// dtp_stap_scan_test_seq. One parameterized sequence, dispatched on
// `scenario`:
//
//   stap_sel_{ds,smc,sep,extra}  configure and select one STAP through
//       composed TAP_3DCR chain scans and prove it end to end against the
//       downstream ocah_jtag_vip TAP the bench splices behind every STAP
//       host port: the downstream IDCODE and a written DS_TDR read back
//       through the selected STAP (network-wide IR scans select the
//       register), the port's direct disable freezes the downstream register
//       in Test-Logic-Reset and blocks a gated 3DCR update, selection
//       resumes without reset, an unrelated STAP's downstream stays usable
//       while the target is gated, and a fresh configuration recovers fully.
//       The host-port temporal windows (tdo_oen pulses, tms follows the live
//       TMS or parks) corroborate the downstream evidence; on a bench without
//       attached downstream TAPs the same flow runs against the wire
//       loopbacks with the window and chain-readback evidence only;
//   ext_stap_scan  the extended STAP host scan interface follows the PTAP
//       3DCR select, its controls stay quiet under the stap_host disable
//       (seeded gated attempt), and recover without reset;
//   config_hold    per STAP (seeded order), the PTAP 3DCR and the STAP 3DCR
//       are written with CONFIG_HOLD=1 or 0 through composed chain scans,
//       reset (TLR or TRST), reloaded with a composed IR scan, and read
//       back against the model: hold=1 keeps the PTAP select and the STAP
//       select/tms_hold across TLR, hold=0 lets TLR clear them, TRST clears
//       them all; a PTAP whose select cleared is read over the TDR return
//       path with a marker that proves the path;
//   tms_hold       per STAP and polarity (seeded order): select the STAP
//       with TMS_HOLD=h and prove over a maintain scan that the port
//       forwards (the positive control of the deny that follows), deselect
//       it, and prove over a whole maintain scan that the host TMS parks at
//       h, tdo_oen stays quiet, and the 3DCR reads back through the chain.

class dtp_stap_scan_test_seq extends dtp_scan_base_test_seq;
  `uvm_object_utils(dtp_stap_scan_test_seq)

  // Selected by the test before start(); body() dispatches on it.
  string scenario = "stap_sel_ds";

  function new(string name = "dtp_stap_scan_test_seq");
    super.new(name);
  endfunction

  protected function dtp_stap_3dcr_state_t selected_payload();
    return '{1'b1, 1'b1, 1'b1};  // config_hold, stap_sel, tms_hold
  endfunction

  protected function sep_lifecycle_ctrl_pkg::dbg_disable_t stap_gate_mask(int unsigned stap);
    return dtp_dbg_disable_only(dtp_stap_dbg_path(stap));
  endfunction

  // Open the STAP's SIB and write its selected 3DCR payload through two
  // composed chain scans.
  protected task configure_stap(int unsigned stap, sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                string context_s);
    int sib_en[int];
    dtp_stap_3dcr_state_t payloads[int];
    int no_sib[int];
    dtp_stap_3dcr_state_t no_pl[int];
    bit [63:0] unused;
    sib_en[stap] = 1;
    stap_chain_write(d, 1, 1, sib_en, no_pl, {context_s, ".open_sib"}, unused);
    payloads[stap] = selected_payload();
    stap_chain_write(d, -1, -1, no_sib, payloads, {context_s, ".write_3dcr"}, unused);
  endtask

  // Load DS_TDR in the downstream TAP behind `target`, write `value`, prove
  // the device latched exactly it once, then read it back through the
  // chain (`gate` is the disable mask in force, which shapes the chain).
  protected task ds_write_and_readback(int unsigned target, bit [63:0] value,
                                       sep_lifecycle_ctrl_pkg::dbg_disable_t gate, string context_s,
                                       string check_id = "CHK-DS-TDR-READBACK");
    stap_ds_load_ir(target, StapDsTdrName, gate, {context_s, ".load_ir"});
    m_stap_ds_seq[target].clear_updates();
    stap_ds_write_tdr(target, value, gate, {context_s, ".write"});
    void'(m_stap_ds_seq[target].check_last_update(
        StapDsTdrName, value, $sformatf("%s stap=%s", context_s, stap_name(target))
    ));
    void'(m_stap_ds_seq[target].check_update_count(
        1, StapDsTdrName, $sformatf("%s stap=%s", context_s, stap_name(target))
    ));
    stap_ds_read_tdr(target, gate, {context_s, ".read"}, check_id);
  endtask

  protected task run_stap_select(int unsigned stap);
    sep_lifecycle_ctrl_pkg::dbg_disable_t gate = stap_gate_mask(stap);
    string prefix = stap_prefix(stap);
    string watch[$];
    string quiet[$], active[$];
    int unsigned neighbor = (stap + 1) % DtpStapCount;
    int unsigned edges;
    int unsigned counts[string];
    int no_sib[int];
    int iso_sib[int];
    dtp_stap_3dcr_state_t no_pl[int];
    dtp_stap_3dcr_state_t iso_pl[int];
    bit [63:0] captured, unused;
    dtp_stap_3dcr_state_t attempt;
    bit downstream = ds_attached(stap);
    dtp_stap_ds_reg_t tdr;
    bit [63:0] v_select = '0, v_recover = '0, v_neighbor = '0;
    watch.push_back({prefix, "_tdo_oen"});
    watch.push_back({prefix, "_tms"});
    `uvm_info(get_type_name(), $sformatf("STAP selection: %s (downstream TAP %s)", stap_name(stap),
                                         downstream ? "attached" : "absent"), UVM_LOW)
    if (downstream) begin
      bit [63:0] opcode;
      if (!stap_model.ds[stap].opcode_of(StapDsTdrName, opcode))
        `uvm_fatal(get_type_name(), {"downstream device has no ", StapDsTdrName})
      tdr = stap_model.ds[stap].regs[opcode];
      // Per-pass random downstream values: selected and recovery.
      v_select  = random_pattern(tdr.width);
      v_recover = random_pattern(tdr.width);
    end

    // Step 1: configure and select via composed TAP_3DCR scans.
    stap_chain_flush({stap_name(stap), ".flush"});
    configure_stap(stap, '0, {stap_name(stap), ".select"});
    start_scan_window(watch);
    stap_chain_maintain('0, {stap_name(stap), ".observe"}, captured);
    stop_scan_window(edges, counts);
    check_window_shifted("CHK-SCAN-WIN", {stap_name(stap), ".selected"});
    check_stap_forwarding(edges, counts, stap, 1'b1, {stap_name(stap), ".selected"});
    check_stap_chain_readback(captured, '0, {stap_name(stap), ".selected_readback"});
    if (downstream) begin
      // End-to-end: the downstream IDCODE (selected since TRST) returns
      // through the spliced port, then a written DS_TDR reads back.
      check_ds_idcode(stap, '0, {stap_name(stap), ".selected_idcode"});
      ds_write_and_readback(stap, v_select, '0, {stap_name(stap), ".selected_tdr"});
    end

    // Step 2: assert exactly the port's disable — forwarding stops and
    // a randomized deselecting 3DCR update attempt is ignored.
    set_dbg_disable_full(gate);
    attempt = '{bit'($urandom_range(1)), 1'b0, 1'b0};
    `uvm_info(get_type_name(), $sformatf("%s gated 3DCR update attempt config_hold=%0d", stap_name(
                                         stap), attempt.config_hold), UVM_LOW)
    if (downstream) m_stap_ds_seq[stap].clear_updates();
    start_scan_window(watch);
    iso_pl.delete();
    iso_pl[stap] = attempt;
    stap_chain_write(gate, -1, -1, no_sib, iso_pl, {stap_name(stap), ".gated_update_attempt"},
                     captured);
    stop_scan_window(edges, counts);
    check_window_shifted("CHK-SCAN-WIN", {stap_name(stap), ".gated"});
    check_stap_forwarding(edges, counts, stap, 1'b0, {stap_name(stap), ".gated"});
    check_stap_chain_readback(captured, gate, {stap_name(stap), ".gated_readback"});
    if (downstream) begin
      // The gated port parks its host TMS high: the downstream TAP sits
      // in Test-Logic-Reset (checked after the scan, which supplies the
      // five parked TCKs), latched nothing, and still holds the value.
      void'(m_stap_ds_seq[stap].check_update_count(0, StapDsTdrName, {stap_name(stap), ".gated"}));
      void'(m_stap_ds_seq[stap].check_register(
          StapDsTdrName, v_select, {stap_name(stap), ".gated"}, "CHK-DS-TDR-HOLD"
      ));
      void'(m_stap_ds_seq[stap].check_state(
          OCAH_JTAG_TEST_LOGIC_RESET, {stap_name(stap), ".gated"}, "CHK-DS-PARKED-TLR"
      ));
    end

    // Step 3: clear the disable without reset — selection resumes from
    // stored state.
    enable_all_debug();
    if (downstream) settle_stap_release();
    start_scan_window(watch);
    stap_chain_maintain('0, {stap_name(stap), ".resume"}, captured);
    stop_scan_window(edges, counts);
    check_window_shifted("CHK-SCAN-WIN", {stap_name(stap), ".resume"});
    check_stap_forwarding(edges, counts, stap, 1'b1, {stap_name(stap), ".resume"});
    check_stap_chain_readback(captured, '0, {stap_name(stap), ".resume_readback"});
    if (downstream) begin
      // Live splice and park-reset proven: the downstream answers IDCODE
      // again; reloading DS_TDR reads the pre-gate value.
      check_ds_idcode(stap, '0, {stap_name(stap), ".resume_idcode"});
      stap_ds_load_ir(stap, StapDsTdrName, '0, {stap_name(stap), ".resume_load_ir"});
      stap_ds_read_tdr(stap, '0, {stap_name(stap), ".resume_tdr"}, "CHK-DS-TDR-RESUME");
    end

    // Step 4: with the disable re-asserted, an unrelated STAP stays
    // usable.
    set_dbg_disable_full(gate);
    iso_sib.delete();
    iso_sib[stap]     = 1;
    iso_sib[neighbor] = 1;
    stap_chain_write(gate, -1, -1, iso_sib, no_pl, {stap_name(stap), ".isolation_open"}, unused);
    iso_pl.delete();
    iso_pl[neighbor] = selected_payload();
    stap_chain_write(gate, -1, -1, no_sib, iso_pl, {stap_name(stap), ".isolation_3dcr"}, unused);
    quiet.delete();
    active.delete();
    quiet.push_back({prefix, "_tdo_oen"});
    active.push_back({stap_prefix(neighbor), "_tdo_oen"});
    start_scan_window({quiet, active});
    stap_chain_maintain(gate, {stap_name(stap), ".isolation_observe"}, captured);
    check_scan_window(quiet, active, {stap_name(stap), ".isolation_window"});
    check_stap_chain_readback(captured, gate, {stap_name(stap), ".isolation_readback"});
    if (downstream) m_stap_ds_seq[stap].clear_updates();
    if (ds_attached(neighbor)) begin
      bit [63:0] n_opcode;
      void'(stap_model.ds[neighbor].opcode_of(StapDsTdrName, n_opcode));
      v_neighbor = random_pattern(stap_model.ds[neighbor].regs[n_opcode].width);
      ds_write_and_readback(neighbor, v_neighbor, gate, {stap_name(stap), ".isolation_neighbor"});
    end
    if (downstream)
      void'(m_stap_ds_seq[stap].check_update_count(
          0, StapDsTdrName, {stap_name(stap), ".isolation"}
      ));

    // Step 5: full recovery with a fresh configuration.
    enable_all_debug();
    if (downstream) settle_stap_release();
    stap_chain_flush({stap_name(stap), ".recover_flush"});
    configure_stap(stap, '0, {stap_name(stap), ".recover"});
    start_scan_window(watch);
    stap_chain_maintain('0, {stap_name(stap), ".recover_observe"}, captured);
    stop_scan_window(edges, counts);
    check_window_shifted("CHK-SCAN-WIN", {stap_name(stap), ".recover"});
    check_stap_forwarding(edges, counts, stap, 1'b1, {stap_name(stap), ".recover"});
    check_stap_chain_readback(captured, '0, {stap_name(stap), ".recover_readback"});
    if (downstream) ds_write_and_readback(stap, v_recover, '0, {stap_name(stap), ".recover_tdr"});

    stap_chain_flush({stap_name(stap), ".cleanup"});
  endtask

  protected task run_ext_stap_scan();
    sep_lifecycle_ctrl_pkg::dbg_disable_t gate = '0;
    string host_controls[$];
    string active[$], none[$];
    bit [63:0] unused;
    bit [1:0] gated_attempt;
    host_controls.push_back("jtag_stap_host_select");
    host_controls.push_back("jtag_stap_host_shift_en");
    host_controls.push_back("jtag_stap_host_capture_en");
    host_controls.push_back("jtag_stap_host_update_en");
    active.push_back("jtag_stap_host_select");
    active.push_back("jtag_stap_host_shift_en");
    `uvm_info(get_type_name(), "extended STAP scan interface", UVM_LOW)

    write_ptap_3dcr(1'b1, 1'b1, "ext.enable");
    start_scan_window(host_controls);
    shift_dr(64'h2, Ptap3dcrWidth, unused);
    check_scan_window(none, active, "ext.enabled_window");

    // With the PTAP select clear the host scan strobes still follow every
    // PTAP scan (they are the TAP's; the select routes the scan data), so
    // the deselected scan is judged for pulsing strobes, not for silence.
    write_ptap_3dcr(1'b0, 1'b0, "ext.disable");
    active.delete();
    active.push_back("jtag_stap_host_shift_en");
    start_scan_window(host_controls);
    shift_dr(64'h0, Ptap3dcrWidth, unused);
    check_scan_window(none, active, "ext.deselected_window");
    active.delete();
    active.push_back("jtag_stap_host_select");
    active.push_back("jtag_stap_host_shift_en");

    write_ptap_3dcr(1'b1, 1'b1, "ext.gate_enable");
    dtp_dbg_path_set(gate, DTP_DBG_PATH_STAP_HOST);
    set_dbg_disable_full(gate);
    // Seeded per-pass gated attempt: any value with the select bit set
    // is an equally valid attempt that must be ignored while gated.
    gated_attempt = ($urandom_range(1) == 0) ? 2'b10 : 2'b11;
    start_scan_window(host_controls);
    shift_dr(64'(gated_attempt), Ptap3dcrWidth, unused);
    check_scan_window(host_controls, none, "ext.host_gated_window");

    // Recovery without reset: normal host scan control resumes once the
    // disable clears.
    enable_all_debug();
    start_scan_window(host_controls);
    shift_dr(64'h2, Ptap3dcrWidth, unused);
    check_scan_window(none, active, "ext.recover_window");
  endtask

  // Program the PTAP 3DCR (select=1, config_hold=hold) and one STAP's 3DCR
  // (config_hold=hold, seeded select, tms_hold=1), apply the reset, and
  // read every field back through composed chain scans against the model:
  // with hold=1 a Test-Logic-Reset keeps the PTAP select and the STAP
  // select/tms_hold, with hold=0 it clears them, and TRST clears them all.
  protected task config_hold_case(int unsigned stap, bit hold, bit use_trst);
    string ctx = $sformatf("config_hold.%s.hold%0d.%s", stap_name(stap), hold,
                           use_trst ? "trst" : "tlr");
    int sib_en[int];
    int no_sib[int];
    dtp_stap_3dcr_state_t payloads[int];
    dtp_stap_3dcr_state_t no_pl[int];
    bit [63:0] no_ir[int];
    bit [63:0] captured, unused, marker;
    sib_en[stap]   = 1;
    payloads[stap] = '{hold, bit'($urandom_range(1)), 1'b1};
    marker = random_pattern(DtpScanMarkerWidth) | (64'h1 << (DtpScanMarkerWidth - 1));
    `uvm_info(get_type_name(), $sformatf("%s STAP payload config_hold=%0d stap_sel=%0d tms_hold=1",
                                         ctx, hold, payloads[stap].stap_sel), UVM_LOW)
    stap_chain_flush({ctx, ".flush"});
    stap_chain_write('0, 1, int'(hold), sib_en, no_pl, {ctx, ".open_sib"}, unused);
    stap_chain_write('0, -1, -1, no_sib, payloads, {ctx, ".write_3dcr"}, unused);
    if (use_trst) apply_trst();
    else apply_tlr();
    // The reset leaves IDCODE in the IR. Every IR scan shifts through the
    // STAP chain, so TAP_3DCR is reloaded with a composed IR scan that
    // rewrites the chain image it passes through.
    stap_chain_ir_write('0, 6'(TAP_3DCR_INSTR), no_ir, no_sib, no_pl, {ctx, ".reload_ir"}, unused);
    if (stap_model.ptap_select) begin
      stap_chain_maintain('0, {ctx, ".ptap_readback"}, captured);
      check_stap_chain_readback(captured, '0, {ctx, ".ptap_readback"});
    end else read_ptap_3dcr_deselected(marker, {ctx, ".ptap_readback"});
    // Re-select and reopen the SIB: the STAP's 3DCR fields join the chain
    // and read back as the model predicts after the reset.
    stap_chain_write('0, 1, -1, sib_en, no_pl, {ctx, ".reopen_sib"}, unused);
    stap_chain_maintain('0, {ctx, ".stap_readback"}, captured);
    check_stap_chain_readback(captured, '0, {ctx, ".stap_readback"});
    `uvm_info(get_type_name(), $sformatf("%s after reset: ptap select=%0d config_hold=%0d stap=%p",
                                         ctx, stap_model.ptap_select, stap_model.ptap_config_hold,
                                         stap_model.staps[stap]), UVM_LOW)
  endtask

  protected task run_config_hold();
    int unsigned staps[$] = {0, 1, 2, 3};
    `uvm_info(get_type_name(), "PTAP/STAP CONFIG_HOLD across Test-Logic-Reset and TRST", UVM_LOW)
    shuffle(staps);
    foreach (staps[i]) begin
      // Seeded per-pass order: each self-contained sub-case starts from a
      // flushed chain, so each loop proves a different sequencing of
      // preserve/clear behavior.
      int unsigned cases[$] = {0, 1, 2};
      shuffle(cases);
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: STAP %s cases=%p", i + 1, staps.size(), stap_name(staps[i]), cases),
          UVM_LOW)
      foreach (cases[c]) begin
        case (cases[c])
          0:       config_hold_case(.stap(staps[i]), .hold(1'b1), .use_trst(1'b0));
          1:       config_hold_case(.stap(staps[i]), .hold(1'b0), .use_trst(1'b0));
          default: config_hold_case(.stap(staps[i]), .hold(1'b1), .use_trst(1'b1));
        endcase
      end
    end
  endtask

  // Select the STAP with tms_hold=hold and prove the selected port forwards
  // (tdo_oen pulses, tms follows the live TMS) under the window the parked
  // leg reuses, deselect it, then prove the deselected port drives its host
  // TMS at that polarity for the whole maintain scan while tdo_oen stays
  // quiet, and that the 3DCR reads back as written.
  protected task tms_hold_case(int unsigned stap, bit hold);
    string ctx = $sformatf("tms_hold.%s.hold%0d", stap_name(stap), hold);
    string prefix = stap_prefix(stap);
    string watch[$];
    int sib_en[int];
    int no_sib[int];
    dtp_stap_3dcr_state_t payloads[int];
    dtp_stap_3dcr_state_t no_pl[int];
    bit [63:0] captured, unused;
    int unsigned edges;
    int unsigned counts[string];
    sib_en[stap] = 1;
    watch.push_back({prefix, "_tdo_oen"});
    watch.push_back({prefix, "_tms"});
    stap_chain_flush({ctx, ".flush"});
    stap_chain_write('0, 1, -1, sib_en, no_pl, {ctx, ".open_sib"}, unused);
    payloads[stap] = '{1'b0, 1'b1, hold};
    stap_chain_write('0, -1, -1, no_sib, payloads, {ctx, ".select"}, unused);
    start_scan_window(watch);
    stap_chain_maintain('0, {ctx, ".selected_observe"}, captured);
    stop_scan_window(edges, counts);
    check_window_shifted("CHK-SCAN-WIN", {ctx, ".selected_window"});
    check_stap_forwarding(edges, counts, stap, 1'b1, {ctx, ".selected"});
    check_stap_chain_readback(captured, '0, {ctx, ".selected_readback"});
    payloads[stap] = '{1'b0, 1'b0, hold};
    stap_chain_write('0, -1, -1, no_sib, payloads, {ctx, ".deselect"}, unused);
    start_scan_window(watch);
    stap_chain_maintain('0, {ctx, ".observe"}, captured);
    stop_scan_window(edges, counts);
    check_window_shifted("CHK-SCAN-WIN", {ctx, ".window"});
    check_stap_forwarding(edges, counts, stap, 1'b0, {ctx, ".parked"});
    check_stap_chain_readback(captured, '0, {ctx, ".readback"});
  endtask

  protected task run_tms_hold();
    int unsigned staps[$] = {0, 1, 2, 3};
    `uvm_info(get_type_name(), "STAP TMS_HOLD parked polarity", UVM_LOW)
    // Seeded per-pass STAP and polarity order: each loop walks the ports
    // and the two parked polarities differently.
    shuffle(staps);
    foreach (staps[i]) begin
      int unsigned polarities[$] = {1, 0};
      shuffle(polarities);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: STAP %s tms_hold order=%p",
                i + 1,
                staps.size(),
                stap_name(
                    staps[i]
                ),
                polarities
                ), UVM_LOW)
      foreach (polarities[p]) tms_hold_case(staps[i], bit'(polarities[p]));
    end
  endtask

  // Per-pass evidence every STAP-selection pass must record (cocotb twin:
  // dtp_stap_scan_test_seq.py); the CHK-DS-* and CHK-SLAVE-* IDs need an
  // attached downstream TAP and are required only when the bench has one.
  protected function void stap_sel_required_ids(int unsigned stap, ref string required[$]);
    required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-CHAIN"};
    if (stap_ds_attached[stap]) begin
      required.push_back("CHK-DS-IDCODE");
      required.push_back("CHK-DS-TDR-READBACK");
      required.push_back("CHK-DS-TDR-HOLD");
      required.push_back("CHK-DS-PARKED-TLR");
      required.push_back("CHK-DS-TDR-RESUME");
      required.push_back("CHK-SLAVE-DR-UPDATE");
      required.push_back("CHK-SLAVE-DR-UPDATE-COUNT");
    end
  endfunction

  task body();
    string required[$];
    seed_scenario_rng();
    case (scenario)
      "stap_sel_ds":    stap_sel_required_ids(int'(ST_IO), required);
      "stap_sel_smc":   stap_sel_required_ids(int'(ST_SMC), required);
      "stap_sel_sep":   stap_sel_required_ids(int'(ST_SEP), required);
      "stap_sel_extra": stap_sel_required_ids(int'(ST_EXTRA0), required);
      "ext_stap_scan":
                required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN"};
      "config_hold":
                required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-CHAIN", "CHK-SCAN-OBS"};
      "tms_hold":
                required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN", "CHK-SCAN-CHAIN"};
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown STAP scenario %s", scenario))
    endcase
    // Scenario-owned Shift-x exits: skip the scan-count cross-check.
    attach_family_checker(required, 1'b0);
    attach_downstream_taps();
    enable_all_debug();
    reset_to_tlr();
    case (scenario)
      "stap_sel_ds":    run_stap_select(int'(ST_IO));
      "stap_sel_smc":   run_stap_select(int'(ST_SMC));
      "stap_sel_sep":   run_stap_select(int'(ST_SEP));
      "stap_sel_extra": run_stap_select(int'(ST_EXTRA0));
      "ext_stap_scan":  run_ext_stap_scan();
      "config_hold":    run_config_hold();
      "tms_hold":       run_tms_hold();
      default: ;
    endcase
    enable_all_debug();
    write_ptap_3dcr(1'b0, 1'b0, "cleanup");
    finalize_family_checker();
  endtask

endclass : dtp_stap_scan_test_seq
