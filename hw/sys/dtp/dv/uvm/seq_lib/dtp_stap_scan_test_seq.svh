// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// STAP/3DCR scan scenarios — the SV analogue of the cocotb
// dtp_stap_scan_test_seq. One parameterized sequence, dispatched on
// `scenario`:
//
//   stap_sel_{ds,smc,sep,extra}  configure and select one STAP through
//       composed TAP_3DCR chain scans: forwarding proved by a temporal
//       window (tdo_oen pulses, tms follows live TMS), then the port's
//       direct disable stops forwarding and a gated 3DCR update is
//       ignored (chain readback), selection resumes from stored state
//       without reset, an unrelated STAP stays usable under the disable,
//       and a fresh configuration recovers fully;
//   ext_stap_scan  the extended STAP host scan interface follows the PTAP
//       3DCR select, its controls stay quiet under the stap_host disable
//       (seeded gated attempt), and recover without reset;
//   config_hold    PTAP 3DCR CONFIG_HOLD preserve/TLR-clear/TRST-clear
//       sub-cases in a seeded order (PTAP select=1 routes TDO to the STAP
//       path, so PTAP readbacks use select=0);
//   tms_hold       per-STAP (seeded order) TRST + SIB-open flow: the
//       unselected port must never drive tdo_oen; the parked TMS polarity
//       is logged only (full polarity checking needs a real STAP host
//       behind the OSS loopback).

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

    protected function sep_lifecycle_ctrl_pkg::dbg_disable_t stap_gate_mask(
        int unsigned stap
    );
        sep_lifecycle_ctrl_pkg::dbg_disable_t d = '0;
        case (stap)
            int'(ST_IO):  d.stap_io    = 1'b1;
            int'(ST_SMC): d.stap_smc   = 1'b1;
            int'(ST_SEP): d.stap_sep   = 1'b1;
            default:      d.stap_extra = 1'b1;
        endcase
        return d;
    endfunction

    // Open the STAP's SIB and write its selected 3DCR payload through two
    // composed chain scans.
    protected task configure_stap(
        int unsigned                          stap,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        string                                context_s
    );
        int unsigned sib_en[int];
        dtp_stap_3dcr_state_t payloads[int];
        int unsigned no_sib[int];
        dtp_stap_3dcr_state_t no_pl[int];
        bit [63:0] unused;
        sib_en[stap] = 1;
        stap_chain_write(d, 1, 1, sib_en, no_pl,
                         {context_s, ".open_sib"}, unused);
        payloads[stap] = selected_payload();
        stap_chain_write(d, -1, -1, no_sib, payloads,
                         {context_s, ".write_3dcr"}, unused);
    endtask

    protected task run_stap_select(int unsigned stap);
        sep_lifecycle_ctrl_pkg::dbg_disable_t gate = stap_gate_mask(stap);
        string prefix = stap_prefix(stap);
        string watch[$];
        string quiet[$], active[$];
        int unsigned neighbor = (stap + 1) % DtpStapCount;
        int unsigned edges;
        int unsigned counts[string];
        int unsigned no_sib[int];
        int unsigned iso_sib[int];
        dtp_stap_3dcr_state_t no_pl[int];
        dtp_stap_3dcr_state_t iso_pl[int];
        bit [63:0] captured, unused;
        dtp_stap_3dcr_state_t attempt;
        watch.push_back({prefix, "_tdo_oen"});
        watch.push_back({prefix, "_tms"});
        `uvm_info(get_type_name(), $sformatf(
            "STAP selection: %s", stap_name(stap)), UVM_LOW)

        // Step 1: configure and select via composed TAP_3DCR scans.
        stap_chain_flush({stap_name(stap), ".flush"});
        configure_stap(stap, '0, {stap_name(stap), ".select"});
        start_scan_window(watch);
        stap_chain_maintain('0, {stap_name(stap), ".observe"}, captured);
        stop_scan_window(edges, counts);
        family_check("CHK-SCAN-WIN", "window edges nonvacuous",
                     64'(edges > 0), 64'd1, {stap_name(stap), ".selected"});
        check_stap_forwarding(edges, counts, stap, 1'b1,
                              {stap_name(stap), ".selected"});
        check_stap_chain_readback(captured, '0,
                                  {stap_name(stap), ".selected_readback"});

        // Step 2: assert exactly the port's disable — forwarding stops and
        // a randomized deselecting 3DCR update attempt is ignored.
        set_dbg_disable_full(gate);
        attempt = '{bit'($urandom_range(1)), 1'b0, 1'b0};
        `uvm_info(get_type_name(), $sformatf(
            "%s gated 3DCR update attempt config_hold=%0d",
            stap_name(stap), attempt.config_hold), UVM_LOW)
        start_scan_window(watch);
        iso_pl.delete();
        iso_pl[stap] = attempt;
        stap_chain_write(gate, -1, -1, no_sib, iso_pl,
                         {stap_name(stap), ".gated_update_attempt"}, captured);
        stop_scan_window(edges, counts);
        family_check("CHK-SCAN-WIN", "window edges nonvacuous",
                     64'(edges > 0), 64'd1, {stap_name(stap), ".gated"});
        check_stap_forwarding(edges, counts, stap, 1'b0,
                              {stap_name(stap), ".gated"});
        check_stap_chain_readback(captured, gate,
                                  {stap_name(stap), ".gated_readback"});

        // Step 3: clear the disable without reset — selection resumes from
        // stored state.
        enable_all_debug();
        start_scan_window(watch);
        stap_chain_maintain('0, {stap_name(stap), ".resume"}, captured);
        stop_scan_window(edges, counts);
        family_check("CHK-SCAN-WIN", "window edges nonvacuous",
                     64'(edges > 0), 64'd1, {stap_name(stap), ".resume"});
        check_stap_forwarding(edges, counts, stap, 1'b1,
                              {stap_name(stap), ".resume"});
        check_stap_chain_readback(captured, '0,
                                  {stap_name(stap), ".resume_readback"});

        // Step 4: with the disable re-asserted, an unrelated STAP stays
        // usable.
        set_dbg_disable_full(gate);
        iso_sib.delete();
        iso_sib[stap]     = 1;
        iso_sib[neighbor] = 1;
        stap_chain_write(gate, -1, -1, iso_sib, no_pl,
                         {stap_name(stap), ".isolation_open"}, unused);
        iso_pl.delete();
        iso_pl[neighbor] = selected_payload();
        stap_chain_write(gate, -1, -1, no_sib, iso_pl,
                         {stap_name(stap), ".isolation_3dcr"}, unused);
        quiet.delete();
        active.delete();
        quiet.push_back({prefix, "_tdo_oen"});
        active.push_back({stap_prefix(neighbor), "_tdo_oen"});
        start_scan_window({quiet, active});
        stap_chain_maintain(gate, {stap_name(stap), ".isolation_observe"},
                            unused);
        check_scan_window(quiet, active,
                          {stap_name(stap), ".isolation_window"});

        // Step 5: full recovery with a fresh configuration.
        enable_all_debug();
        stap_chain_flush({stap_name(stap), ".recover_flush"});
        configure_stap(stap, '0, {stap_name(stap), ".recover"});
        start_scan_window(watch);
        stap_chain_maintain('0, {stap_name(stap), ".recover_observe"},
                            captured);
        stop_scan_window(edges, counts);
        family_check("CHK-SCAN-WIN", "window edges nonvacuous",
                     64'(edges > 0), 64'd1, {stap_name(stap), ".recover"});
        check_stap_forwarding(edges, counts, stap, 1'b1,
                              {stap_name(stap), ".recover"});
        check_stap_chain_readback(captured, '0,
                                  {stap_name(stap), ".recover_readback"});

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

        write_ptap_3dcr(1'b0, 1'b0, "ext.disable");
        shift_dr(64'h0, Ptap3dcrWidth, unused);
        // The RTL keeps scan control active during PTAP scan activity and
        // uses the PTAP_3DCR select for data routing: log-only here.

        write_ptap_3dcr(1'b1, 1'b1, "ext.gate_enable");
        gate.stap_host = 1'b1;
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

    protected task run_config_hold();
        int unsigned order[3] = '{0, 1, 2};
        bit [63:0] observed;
        `uvm_info(get_type_name(), "PTAP CONFIG_HOLD behavior", UVM_LOW)
        // Seeded per-pass order: each self-contained sub-case starts with
        // its own 3DCR write and reset.
        for (int unsigned i = 2; i > 0; i--) begin
            int unsigned j = $urandom_range(i);
            int unsigned tmp = order[i];
            order[i] = order[j];
            order[j] = tmp;
        end
        foreach (order[i]) begin
            case (order[i])
                0: begin  // config_hold=1 preserves across a TMS TLR
                    write_ptap_3dcr(1'b1, 1'b0, "config_hold.preserve_write");
                    apply_tlr();
                    read_ptap_3dcr(observed, 64'h1);
                    family_check("CHK-SCAN-OBS",
                                 "config_hold.ptap_config_preserved",
                                 observed & 64'h1, 64'h1);
                end
                1: begin  // config_hold=0 lets a TMS TLR clear the 3DCR
                    write_ptap_3dcr(1'b0, 1'b1, "config_hold.clear_write");
                    apply_tlr();
                    read_ptap_3dcr(observed, 64'h0);
                    family_check("CHK-SCAN-OBS", "config_hold.ptap_cleared",
                                 observed & 64'h3, 64'h0);
                end
                default: begin  // TRST always clears, config_hold or not
                    write_ptap_3dcr(1'b1, 1'b0, "config_hold.trst_write");
                    apply_trst();
                    read_ptap_3dcr(observed, 64'h0);
                    family_check("CHK-SCAN-OBS",
                                 "config_hold.ptap_trst_cleared",
                                 observed & 64'h3, 64'h0);
                end
            endcase
        end
    endtask

    protected task run_tms_hold();
        int unsigned order[DtpStapCount] = '{0, 1, 2, 3};
        `uvm_info(get_type_name(), "STAP TMS_HOLD behavior", UVM_LOW)
        // Seeded per-pass STAP order: each loop walks the ports differently.
        for (int unsigned i = DtpStapCount - 1; i > 0; i--) begin
            int unsigned j = $urandom_range(i);
            int unsigned tmp = order[i];
            order[i] = order[j];
            order[j] = tmp;
        end
        foreach (order[i]) begin
            int unsigned stap = order[i];
            string prefix = stap_prefix(stap);
            string quiet[$], none[$];
            bit [63:0] unused;
            int unsigned edges;
            int unsigned counts[string];
            apply_trst();
            write_ptap_3dcr(1'b1, 1'b1, $sformatf("tms_hold.%s.ptap",
                                                  stap_name(stap)));
            // Open only this STAP's SIB (MSB-first pattern in the 4-bit
            // scan; the model is not synchronized here — no readback).
            load_ir(6'(TAP_3DCR_INSTR));
            shift_dr(64'h1 << (DtpStapCount - 1 - stap), DtpStapCount, unused);
            // The port's 3DCR is untouched (stap_sel=0), so it must never
            // drive tdo_oen; the parked TMS polarity is state-dependent in
            // the OSS loopback and is sampled for the log only.
            quiet.push_back({prefix, "_tdo_oen"});
            start_scan_window({quiet, {prefix, "_tms"}});
            shift_dr('0, DtpStapCount, unused);
            stop_scan_window(edges, counts);
            check_window_counts(edges, counts, quiet, none,
                                $sformatf("tms_hold.%s.window",
                                          stap_name(stap)));
            `uvm_info(get_type_name(), $sformatf(
                {"tms_hold.%s sampled TMS high %0d/%0d cycles (OSS loopback: ",
                 "polarity is state-dependent; log only)"},
                stap_name(stap), counts[{prefix, "_tms"}], edges), UVM_LOW)
        end
    endtask

    task body();
        string required[$];
        seed_scenario_rng();
        case (scenario)
            "stap_sel_ds", "stap_sel_smc", "stap_sel_sep", "stap_sel_extra":
                required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN",
                             "CHK-SCAN-CHAIN"};
            "ext_stap_scan":
                required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN"};
            "config_hold":
                required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-OBS"};
            "tms_hold":
                required = '{"CHK-TAP-RESET-TLR", "CHK-SCAN-WIN"};
            default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown STAP scenario %s", scenario))
        endcase
        // Scenario-owned Shift-x exits: skip the scan-count cross-check.
        attach_family_checker(required, 1'b0);
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
