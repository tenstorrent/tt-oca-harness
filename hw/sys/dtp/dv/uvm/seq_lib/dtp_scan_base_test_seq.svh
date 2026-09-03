// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Shared iJTAG/STAP scan helper base sequence — the SV analogue of the
// cocotb dtp_scan_base_test_seq, layered on the JTAG command library with
// the dtp_scan_ref_model classes:
//
//   * temporal scan-control windows: a forked sampler counts high samples
//     of named dtp_tb_if observables once per TCK cycle, so a gated
//     operation proves ZERO pulses over a whole scan and an enabled one
//     proves the expected pulses occurred (post-scan snapshots cannot).
//     Samples land on the falling TCK edge, where every control has
//     settled — the same one-sample-per-cycle semantics as the cocotb
//     post-edge ReadOnly monitor;
//   * iJTAG SIB programming (SELECT_IJTAG) with requested/gated/effective
//     prediction from the SIB model and window-proved outcomes;
//   * STAP/3DCR access: PTAP 3DCR read/write, composed TAP_3DCR chain
//     scans through the 3DCR model (compose/apply/expected-capture), the
//     forwarding checks (tdo_oen pulses + tms follows live TMS vs parked),
//     and TLR/TRST model synchronization;
//   * downstream STAP TAPs: the shared ocah_jtag_vip slave devices the
//     bench splices behind the STAP host ports (test-attached), reached only
//     through composed chain scans (network-wide IR scans included) and
//     judged through each device's ocah_jtag_slave_sequence.
//
// Scenario checks land named family evidence (CHK-SCAN-WIN for the
// temporal windows, CHK-SCAN-OBS for sampled observables, CHK-SCAN-CHAIN
// for chain readbacks, CHK-DS-* for downstream readbacks), honoring
// +DTP_JTAG_FAMILY_CHECKER_NEGATIVE. The scan scenarios navigate Shift-x
// with sequence-owned exits, so tests attach the family checker with
// use_scan_crosscheck=0.

class dtp_scan_base_test_seq extends dtp_jtag_cmd_lib_seq;
    `uvm_object_utils(dtp_scan_base_test_seq)

    localparam int unsigned Ptap3dcrWidth      = 2;
    // Over-length composed scans: 64 bits holds the worst case (PTAP 3DCR +
    // a 32-bit downstream IDCODE + the I/O STAP splice + four open SIBs with
    // their 3DCRs).
    localparam int unsigned StapChainScanWidth = 64;
    localparam string       StapDsTdrName      = "DS_TDR";

    // The UVM harness system clock is fixed at 100 MHz (tb_top).
    localparam time SysClkPeriod = 10ns;

    dtp_stap_3dcr_model stap_model;

    // Downstream STAP TAPs (plumbed by the test per pass, dtp_stap_e order):
    // the slave sequence bound to each device, the device configuration the
    // scan model is seeded from, and whether the port is attached (its host
    // TDI takes the device's TDO instead of the wire loopback).
    ocah_jtag_slave_sequence stap_ds_seq[DtpStapCount];
    ocah_jtag_slave_config   stap_ds_cfg[DtpStapCount];
    bit                      stap_ds_attached[DtpStapCount];

    // Window-monitor state (one window at a time, mirroring cocotb usage).
    protected string       m_win_signals[$];
    protected int unsigned m_win_counts[string];
    protected int unsigned m_win_edges;
    protected process      m_win_proc;

    function new(string name = "dtp_scan_base_test_seq");
        super.new(name);
        stap_model = new();
    endfunction

    // --- system helpers -------------------------------------------------------
    task wait_sys_cycles(int unsigned cycles = 4);
        #(cycles * SysClkPeriod);
    endtask

    // Drive the full lifecycle disable vector, then settle through the
    // DUT's 2-stage TCK-domain synchronizers.
    task set_dbg_disable_full(sep_lifecycle_ctrl_pkg::dbg_disable_t d);
        tb_vif.dbg_disable <= d;
        for (int unsigned i = 0; i < 4; i++)
            step(1'b0);
        wait_sys_cycles(4);
        `uvm_info(get_type_name(), $sformatf("dbg_disable=0x%03h", d), UVM_MEDIUM)
    endtask

    task enable_all_debug();
        set_dbg_disable_full('0);
    endtask

    // --- generic TDR access ----------------------------------------------------
    task read_tdr64(
        input  bit [IrWidth-1:0] instr,
        input  int unsigned      width,
        output bit [63:0]        observed,
        input  bit [63:0]        shift_value = '0
    );
        load_ir(instr);
        shift_dr(shift_value & bit_mask(width), width, observed);
        observed &= bit_mask(width);
    endtask

    task write_tdr64(
        input bit [IrWidth-1:0] instr,
        input int unsigned      width,
        input bit [63:0]        value
    );
        bit [63:0] unused;
        load_ir(instr);
        shift_dr(value & bit_mask(width), width, unused);
    endtask

    // --- observable sampling and temporal windows ------------------------------
    function bit sample_scan_signal(string name);
        case (name)
            "jtag_dft_secure_select":     return tb_vif.jtag_dft_secure_select;
            "jtag_dft_secure_shift_en":   return tb_vif.jtag_dft_secure_shift_en;
            "jtag_dft_secure_capture_en": return tb_vif.jtag_dft_secure_capture_en;
            "jtag_dft_secure_update_en":  return tb_vif.jtag_dft_secure_update_en;
            "jtag_dft_select":            return tb_vif.jtag_dft_select;
            "jtag_dft_shift_en":          return tb_vif.jtag_dft_shift_en;
            "jtag_dft_capture_en":        return tb_vif.jtag_dft_capture_en;
            "jtag_dft_update_en":         return tb_vif.jtag_dft_update_en;
            "jtag_dfd_select":            return tb_vif.jtag_dfd_select;
            "jtag_dfd_shift_en":          return tb_vif.jtag_dfd_shift_en;
            "jtag_dfd_capture_en":        return tb_vif.jtag_dfd_capture_en;
            "jtag_dfd_update_en":         return tb_vif.jtag_dfd_update_en;
            "jtag_stap_io_tms":           return tb_vif.jtag_stap_io_tms;
            "jtag_stap_io_tdo_oen":       return tb_vif.jtag_stap_io_tdo_oen;
            "jtag_stap_smc_tms":          return tb_vif.jtag_stap_smc_tms;
            "jtag_stap_smc_tdo_oen":      return tb_vif.jtag_stap_smc_tdo_oen;
            "jtag_stap_sep_tms":          return tb_vif.jtag_stap_sep_tms;
            "jtag_stap_sep_tdo_oen":      return tb_vif.jtag_stap_sep_tdo_oen;
            "jtag_stap_extra0_tms":       return tb_vif.jtag_stap_extra0_tms;
            "jtag_stap_extra0_tdo_oen":   return tb_vif.jtag_stap_extra0_tdo_oen;
            "jtag_stap_host_select":      return tb_vif.jtag_stap_host_select;
            "jtag_stap_host_shift_en":    return tb_vif.jtag_stap_host_shift_en;
            "jtag_stap_host_capture_en":  return tb_vif.jtag_stap_host_capture_en;
            "jtag_stap_host_update_en":   return tb_vif.jtag_stap_host_update_en;
            default: begin
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown scan observable '%s'", name))
                return 1'b0;
            end
        endcase
    endfunction

    // Begin counting high samples of the named observables once per TCK
    // cycle (falling edge, all controls settled).
    task start_scan_window(string signals[$]);
        if (m_win_proc != null)
            `uvm_fatal(get_type_name(), "scan window monitor is already running")
        m_win_signals = signals;
        m_win_counts.delete();
        foreach (signals[i])
            m_win_counts[signals[i]] = 0;
        m_win_edges = 0;
        fork
            begin
                m_win_proc = process::self();
                forever begin
                    @(negedge jtag_vif.tck);
                    m_win_edges++;
                    foreach (m_win_signals[i])
                        if (sample_scan_signal(m_win_signals[i]))
                            m_win_counts[m_win_signals[i]]++;
                end
            end
        join_none
    endtask

    // End the window; return the TCK-cycle count and per-signal high counts.
    function void stop_scan_window(output int unsigned edges,
                                   output int unsigned counts[string]);
        if (m_win_proc == null)
            `uvm_fatal(get_type_name(), "scan window monitor was never started")
        m_win_proc.kill();
        m_win_proc = null;
        edges  = m_win_edges;
        counts = m_win_counts;
        foreach (counts[name])
            `uvm_info(get_type_name(), $sformatf(
                "scan window %s=%0d/%0d", name, counts[name], edges), UVM_MEDIUM)
    endfunction

    // Quiet signals must never pulse inside the window; active ones must.
    function void check_window_counts(
        int unsigned edges,
        int unsigned counts[string],
        string       quiet[$],
        string       active[$],
        string       context_s
    );
        family_check("CHK-SCAN-WIN", "window edges nonvacuous",
                     64'(edges > 0), 64'd1, context_s);
        foreach (quiet[i])
            family_check("CHK-SCAN-WIN", {quiet[i], " quiet"},
                         64'(counts[quiet[i]]), 64'd0,
                         $sformatf("%s edges=%0d", context_s, edges));
        foreach (active[i])
            family_check("CHK-SCAN-WIN", {active[i], " active"},
                         64'(counts[active[i]] > 0), 64'd1,
                         $sformatf("%s count=%0d/%0d", context_s,
                                   counts[active[i]], edges));
    endfunction

    // Stop the running window and apply the quiet/active checks in one step.
    function void check_scan_window(string quiet[$], string active[$],
                                    string context_s);
        int unsigned edges;
        int unsigned counts[string];
        stop_scan_window(edges, counts);
        check_window_counts(edges, counts, quiet, active, context_s);
    endfunction

    // --- iJTAG ------------------------------------------------------------------
    static function string ijtag_prefix(int unsigned sib);
        case (sib)
            int'(IJ_DFT_SECURE): return "jtag_dft_secure";
            int'(IJ_DFT):        return "jtag_dft";
            default:             return "jtag_dfd";
        endcase
    endfunction

    static function string ijtag_name(int unsigned sib);
        case (sib)
            int'(IJ_DFT_SECURE): return "dft_secure";
            int'(IJ_DFT):        return "dft";
            default:             return "dfd";
        endcase
    endfunction

    // Update the three iJTAG SIB bits in LSB-first RTL order.
    task program_ijtag_sibs(bit [DtpIjtagSibCount-1:0] pattern, string context_s);
        bit [63:0] unused;
        `uvm_info(get_type_name(), $sformatf(
            "%s SIB pattern=0b%03b", context_s, pattern), UVM_MEDIUM)
        load_ir(6'(SELECT_IJTAG_INSTR));
        shift_dr(64'(pattern), DtpIjtagSibCount, unused);
    endtask

    // Program a SIB pattern under a disable mask and prove the outcome with
    // a temporal window across a second observation scan: a requested-but-
    // gated SIB's scan controls must never pulse, an effective SIB's select
    // must be seen high, and any closed SIB's select stays quiet.
    task check_ijtag_pattern(
        bit [DtpIjtagSibCount-1:0]            pattern,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        string                                context_s
    );
        bit requested[DtpIjtagSibCount];
        bit gated[DtpIjtagSibCount];
        bit effective[DtpIjtagSibCount];
        int unsigned chain_len;
        string quiet[$], active[$];
        bit [63:0] unused;
        dtp_ijtag_sib_model::state(pattern, d, requested, gated, effective,
                                   chain_len);
        `uvm_info(get_type_name(), $sformatf(
            "%s SIB pattern=0b%03b requested=%p gated=%p effective=%p",
            context_s, pattern, requested, gated, effective), UVM_LOW)
        set_dbg_disable_full(d);
        program_ijtag_sibs(pattern, {context_s, ".program"});

        for (int unsigned sib = 0; sib < DtpIjtagSibCount; sib++) begin
            if (effective[sib])
                active.push_back({ijtag_prefix(sib), "_select"});
            else if (requested[sib] && gated[sib]) begin
                quiet.push_back({ijtag_prefix(sib), "_select"});
                quiet.push_back({ijtag_prefix(sib), "_shift_en"});
                quiet.push_back({ijtag_prefix(sib), "_capture_en"});
                quiet.push_back({ijtag_prefix(sib), "_update_en"});
            end else
                quiet.push_back({ijtag_prefix(sib), "_select"});
        end
        start_scan_window({quiet, active});
        load_ir(6'(SELECT_IJTAG_INSTR));
        shift_dr(64'(pattern), DtpIjtagSibCount, unused);
        check_scan_window(quiet, active, {context_s, ".window"});
        family_check("CHK-SCAN-OBS", {context_s, ".chain_len"},
                     64'(chain_len), 64'd3);
    endtask

    // --- STAP / 3DCR -------------------------------------------------------------
    static function string stap_prefix(int unsigned stap);
        case (stap)
            int'(ST_IO):  return "jtag_stap_io";
            int'(ST_SMC): return "jtag_stap_smc";
            int'(ST_SEP): return "jtag_stap_sep";
            default:      return "jtag_stap_extra0";
        endcase
    endfunction

    static function string stap_name(int unsigned stap);
        case (stap)
            int'(ST_IO):  return "io";
            int'(ST_SMC): return "smc";
            int'(ST_SEP): return "sep";
            default:      return "extra0";
        endcase
    endfunction

    task write_ptap_3dcr(bit config_hold, bit stap_sel, string context_s);
        bit [63:0] value = dtp_stap_3dcr_model::ptap_3dcr_value(config_hold,
                                                                stap_sel);
        `uvm_info(get_type_name(), $sformatf(
            "%s PTAP_3DCR config_hold=%0d select=%0d raw=0x%0h",
            context_s, config_hold, stap_sel, value), UVM_MEDIUM)
        stap_model.update_ptap(value);
        write_tdr64(6'(TAP_3DCR_INSTR), Ptap3dcrWidth, value);
        step(1'b0);
        step(1'b0);
    endtask

    task read_ptap_3dcr(output bit [63:0] observed,
                        input bit [63:0] shift_value = '0);
        read_tdr64(6'(TAP_3DCR_INSTR), Ptap3dcrWidth, observed, shift_value);
    endtask

    // --- downstream STAP TAPs --------------------------------------------------
    // Seed the chain model with every attached downstream TAP and route
    // their slave-sequence evidence into this pass's family checker. Call
    // once per pass after attach_family_checker(); a pass on a bench with no
    // attached ports is unaffected.
    function void attach_downstream_taps();
        for (int unsigned s = 0; s < DtpStapCount; s++) begin
            if (!stap_ds_attached[s])
                continue;
            if (stap_ds_cfg[s] == null || stap_ds_seq[s] == null)
                `uvm_fatal(get_type_name(), $sformatf(
                    "STAP %s attached but its downstream handles were not plumbed",
                    stap_name(s)))
            stap_model.attach(s, stap_ds_cfg[s]);
            if (m_family != null)
                stap_ds_seq[s].evidence = m_family;
            `uvm_info(get_type_name(), $sformatf(
                "downstream TAP behind STAP %s: idcode=0x%08h ir_width=%0d",
                stap_name(s), stap_ds_cfg[s].idcode, stap_ds_cfg[s].ir_width), UVM_LOW)
        end
    endfunction

    function bit ds_attached(int unsigned stap);
        return stap_model.attached(stap);
    endfunction

    // Re-establish lockstep after a STAP's disable clears. While gated, the
    // port parks its host TMS at the stored tms_hold, so a downstream TAP
    // behind it sits in Test-Logic-Reset. The disable clears through the
    // DUT's 2-stage TCK synchronizer and the downstream then needs one live
    // TMS=0 cycle to re-enter Run-Test/Idle alongside the PTAP;
    // set_dbg_disable_full() leaves a one-cycle margin, so add two idle TCK
    // cycles before the next composed scan.
    task settle_stap_release();
        repeat (2)
            step(1'b0);
    endtask

    // Load TAP_3DCR and zero the whole PTAP+STAP configuration chain. With a
    // selected STAP splicing an attached downstream TAP, a plain 6-bit IR
    // load would shift garbage through the network at Update-IR (into the
    // SIB/3DCR flops and the downstream IR) and leave the downstream
    // instruction untracked, so the load is a composed IR scan that parks
    // every spliced downstream TAP on BYPASS first.
    task stap_chain_flush(string context_s, sep_lifecycle_ctrl_pkg::dbg_disable_t d = '0);
        bit [63:0] unused;
        int unsigned spliced_list[$];
        stap_model.spliced_downstream(d, spliced_list);
        if (spliced_list.size() > 0) begin
            bit [63:0] ds_ir[int];
            int no_sib[int];
            dtp_stap_3dcr_state_t no_pl[int];
            foreach (spliced_list[i])
                ds_ir[int'(spliced_list[i])] = stap_model.ds[spliced_list[i]].bypass_opcode();
            `uvm_info(get_type_name(), $sformatf(
                "%s flush TAP_3DCR chain (composed IR load, %0d downstream TAP(s))",
                context_s, spliced_list.size()), UVM_MEDIUM)
            stap_chain_ir_write(d, 6'(TAP_3DCR_INSTR), ds_ir, no_sib, no_pl,
                                {context_s, ".ir"}, unused);
        end else begin
            `uvm_info(get_type_name(), $sformatf(
                "%s flush TAP_3DCR configuration chain", context_s), UVM_MEDIUM)
            load_ir(6'(TAP_3DCR_INSTR));
        end
        shift_dr('0, StapChainScanWidth, unused);
        stap_model.flush_scan(d);
    endtask

    // One composed TAP_3DCR scan driving the full chain state. TAP_3DCR
    // must already be loaded (stap_chain_flush). Negative ptap args and
    // absent associative entries keep stored values, so a bare call is a
    // maintain scan whose captured bits read back the pre-scan chain state;
    // new_ds_values writes a spliced downstream TAP's selected (writable)
    // register.
    task stap_chain_write_ds(
        input  sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        input  int                   new_ptap_select,
        input  int                   new_ptap_config_hold,
        input  int                   new_sib_en[int],
        input  dtp_stap_3dcr_state_t new_payloads[int],
        input  bit [63:0]            new_ds_values[int],
        input  string                context_s,
        output bit [63:0]            captured
    );
        bit [63:0] value = stap_model.compose_scan_ds(StapChainScanWidth, d,
                                                      new_ptap_select,
                                                      new_ptap_config_hold,
                                                      new_sib_en, new_payloads,
                                                      new_ds_values);
        `uvm_info(get_type_name(), $sformatf(
            "%s TAP_3DCR chain scan value=0x%016h", context_s, value), UVM_MEDIUM)
        shift_dr(value, StapChainScanWidth, captured);
        stap_model.apply_scan_ds(d, new_ptap_select, new_ptap_config_hold,
                                 new_sib_en, new_payloads, new_ds_values);
    endtask

    task stap_chain_write(
        input  sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        input  int                   new_ptap_select,
        input  int                   new_ptap_config_hold,
        input  int                   new_sib_en[int],
        input  dtp_stap_3dcr_state_t new_payloads[int],
        input  string                context_s,
        output bit [63:0]            captured
    );
        bit [63:0] no_ds[int];
        stap_chain_write_ds(d, new_ptap_select, new_ptap_config_hold, new_sib_en,
                            new_payloads, no_ds, context_s, captured);
    endtask

    // One composed instruction scan over the full network. With the PTAP
    // 3DCR select set the IR shift-out feeds the STAP chain, so the scan
    // carries the PTAP instruction, every SIB/3DCR field (maintained unless
    // given), and each spliced downstream TAP's IR (new_ds_ir names new
    // instructions; others keep the active one).
    task stap_chain_ir_write(
        input  sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        input  bit [63:0]            ptap_instr,
        input  bit [63:0]            new_ds_ir[int],
        input  int                   new_sib_en[int],
        input  dtp_stap_3dcr_state_t new_payloads[int],
        input  string                context_s,
        output bit [63:0]            captured
    );
        bit [63:0] value = stap_model.compose_ir_scan(StapChainScanWidth, d, ptap_instr,
                                                      new_ds_ir, new_sib_en, new_payloads);
        `uvm_info(get_type_name(), $sformatf(
            "%s composed IR scan value=0x%016h ptap_instr=0x%02h",
            context_s, value, ptap_instr), UVM_MEDIUM)
        ir_scan_raw(value, StapChainScanWidth, captured);
        stap_model.apply_ir_scan(d, new_ds_ir, new_sib_en, new_payloads);
    endtask

    // State-preserving chain scan; the capture reads back stored state.
    task stap_chain_maintain(
        input  sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        input  string     context_s,
        output bit [63:0] captured
    );
        int no_sib[int];
        dtp_stap_3dcr_state_t no_pl[int];
        stap_chain_write(d, -1, -1, no_sib, no_pl, context_s, captured);
    endtask

    // Compare a maintain scan's captured bits against the model state.
    // Valid only while the PTAP 3DCR select was already 1 before the scan
    // (otherwise TDO carries the PTAP TDR path, not the chain return).
    function void check_stap_chain_readback(
        bit [63:0]                            captured,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        string                                context_s,
        dtp_scan_kind_e                       kind = DTP_SCAN_DR
    );
        bit [63:0] expected, care;
        int unsigned chain_len;
        stap_model.expected_capture(d, expected, care, chain_len, kind);
        family_check("CHK-SCAN-CHAIN", "stap_chain_readback",
                     captured & care, expected & care,
                     $sformatf("%s len=%0d care=0x%0h", context_s, chain_len,
                               care));
    endfunction

    // --- downstream TAP access through the selected STAP -----------------------
    // Select `reg_name` in the downstream TAP behind a selected STAP
    // (composed IR scan; the PTAP keeps TAP_3DCR).
    task stap_ds_load_ir(
        int unsigned                          stap,
        string                                reg_name,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        string                                context_s
    );
        bit [63:0] opcode, unused;
        bit [63:0] ds_ir[int];
        int no_sib[int];
        dtp_stap_3dcr_state_t no_pl[int];
        if (!stap_model.ds[stap].opcode_of(reg_name, opcode))
            `uvm_fatal(get_type_name(), $sformatf(
                "%s: downstream register %s unknown", stap_name(stap), reg_name))
        ds_ir[int'(stap)] = opcode;
        `uvm_info(get_type_name(), $sformatf(
            "%s downstream %s: load IR %s (0x%02h)", context_s, stap_name(stap),
            reg_name, opcode), UVM_MEDIUM)
        stap_chain_ir_write(d, 6'(TAP_3DCR_INSTR), ds_ir, no_sib, no_pl, context_s, unused);
    endtask

    // Write the downstream TAP's selected register through the chain.
    task stap_ds_write_tdr(
        int unsigned                          stap,
        bit [63:0]                            value,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        string                                context_s
    );
        dtp_stap_ds_reg_t r;
        bit [63:0] unused;
        bit [63:0] ds_values[int];
        int no_sib[int];
        dtp_stap_3dcr_state_t no_pl[int];
        if (!stap_model.ds[stap].selected(r) || !r.writable)
            `uvm_fatal(get_type_name(), $sformatf(
                "%s: selected downstream register is not writable", stap_name(stap)))
        value &= stap_model.ds[stap].width_mask(r.width);
        ds_values[int'(stap)] = value;
        `uvm_info(get_type_name(), $sformatf(
            "%s downstream %s: write %s=0x%0h", context_s, stap_name(stap), r.name, value),
            UVM_MEDIUM)
        stap_chain_write_ds(d, -1, -1, no_sib, no_pl, ds_values, context_s, unused);
    endtask

    // Maintain scan; extract the downstream segment and record it as
    // `check_id` evidence against the model's predicted capture (the full
    // chain readback is checked as well).
    task stap_ds_readback(
        input  int unsigned                          stap,
        input  string                                check_id,
        input  sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        input  string                                context_s,
        output bit [63:0]                            observed
    );
        dtp_stap_ds_reg_t r;
        string name = stap_model.ds[stap].selected(r) ? r.name : "BYPASS";
        int unsigned lsb, width;
        bit [63:0] expected, captured;
        // Layout and prediction as they exist during the scan (pre-update).
        stap_model.ds_capture_slice(stap, d, DTP_SCAN_DR, lsb, width);
        expected = stap_model.ds[stap].capture(DTP_SCAN_DR);
        stap_chain_maintain(d, context_s, captured);
        observed = (captured >> lsb) & stap_model.ds[stap].width_mask(width);
        family_check(check_id, $sformatf("%s downstream %s readback", stap_name(stap), name),
                     observed, expected,
                     $sformatf("%s width=%0d lsb=%0d", context_s, width, lsb));
        check_stap_chain_readback(captured, d, context_s);
    endtask

    // Read back the downstream TAP's selected data register.
    task stap_ds_read_tdr(
        int unsigned                          stap,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        string                                context_s,
        string                                check_id = "CHK-DS-TDR-READBACK"
    );
        bit [63:0] unused;
        stap_ds_readback(stap, check_id, d, context_s, unused);
    endtask

    // Read the downstream TAP's IDCODE through the selected STAP (the device
    // must have IDCODE selected: after reset, or parked in Test-Logic-Reset
    // while its port was deselected or gated).
    task check_ds_idcode(
        int unsigned                          stap,
        sep_lifecycle_ctrl_pkg::dbg_disable_t d,
        string                                context_s
    );
        bit [63:0] unused;
        if (stap_model.ds[stap].active_ir != stap_model.ds[stap].idcode_opcode)
            `uvm_fatal(get_type_name(), $sformatf(
                "%s: downstream IR is 0x%02h, not IDCODE", stap_name(stap),
                stap_model.ds[stap].active_ir))
        stap_ds_readback(stap, "CHK-DS-IDCODE", d, context_s, unused);
    endtask

    // A selected STAP forwards: tdo_oen pulses during shifts and tms follows
    // the live TMS (mixed samples). A deselected or gated STAP with
    // tms_hold=1 stored parks its tms high and never drives tdo_oen.
    function void check_stap_forwarding(
        int unsigned edges,
        int unsigned counts[string],
        int unsigned stap,
        bit          forwarding,
        string       context_s
    );
        string prefix = stap_prefix(stap);
        int unsigned tdo_oen = counts[{prefix, "_tdo_oen"}];
        int unsigned tms     = counts[{prefix, "_tms"}];
        if (forwarding) begin
            family_check("CHK-SCAN-WIN", {prefix, "_tdo_oen forwarding"},
                         64'(tdo_oen > 0), 64'd1,
                         $sformatf("%s count=%0d/%0d", context_s, tdo_oen, edges));
            family_check("CHK-SCAN-WIN", {prefix, "_tms follows live TMS"},
                         64'((tms > 0) && (tms < edges)), 64'd1,
                         $sformatf("%s count=%0d/%0d", context_s, tms, edges));
        end else begin
            family_check("CHK-SCAN-WIN", {prefix, "_tdo_oen quiet"},
                         64'(tdo_oen), 64'd0, context_s);
            family_check("CHK-SCAN-WIN", {prefix, "_tms parked at tms_hold=1"},
                         64'(tms), 64'(edges), context_s);
        end
    endfunction

    // --- reset helpers with model synchronization --------------------------------
    task apply_tlr();
        goto_tlr_via_tms();
        step(1'b0);
        check_state(RUN_TEST_IDLE, "scan_seq_chk", "after TMS TLR->RTI");
        stap_model.tlr();
    endtask

    task apply_trst();
        set_trst(1'b0, 5);  // assert (active-low pin)
        set_trst(1'b1, 2);  // release
        step(1'b0);
        check_state(RUN_TEST_IDLE, "scan_seq_chk", "after TRST release");
        stap_model.trst();
    endtask

endclass : dtp_scan_base_test_seq
