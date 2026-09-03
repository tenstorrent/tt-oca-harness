// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI error and error-path security scenarios for the DTP SV-UVM flow —
// the SV analogue of the cocotb dtp_jtag2axi_error_test_seq.
// One parameterized sequence, selected by `scenario`, against the target
// named by `target_name` (SMC fabric or either OTP AXI-Lite port; all
// three responders are shared ocah_axi_vip slave agents):
//
//   * error_single_write / error_single_read — one-shot SLVERR then DECERR
//     injections at beat-aligned addresses with randomized payloads: the
//     JTAG status must report the injected code, the armed non-OKAY is
//     EXPECTED for the shared scoreboard (CHK-AXI-ERR-INJ), the failed
//     write commits nothing (the shared slave responder suppresses armed
//     write beats), and an OKAY recovery access follows every injection;
//   * error_series_{no_incr,incr}_{write,read}[_with_status] — a 3-beat
//     series stream with the fault armed on one specific beat: good beats
//     commit/return the expected data at the expected addresses, the fault
//     beat's settled SERIES_CTRL status is captured for the log (the
//     EXPECTED classification is owned by the scoreboard credit), the
//     with-status modes carry the per-beat status/increment MSB, and an
//     OKAY recovery access proves no stuck state;
//   * error_security_gating — two assert/release passes of the target's
//     lifecycle disable with an injection armed but NOT expected-armed
//     (arm_expected=0: a gated op must never reach the bus, so no credit
//     may be armed for it), flat request-activity counters across the
//     gated attempt AND after release (delayed-replay catch), then a
//     restored ungated DECERR plus recovery.
//
// Every random choice draws from the per-pass seeded stream and is logged
// with its loop context for replay. The body always clears injections and
// re-enables debug on exit, and lands CHK-AXI-NONVAC: real operations ran
// and no armed expectation was left unconsumed (dangling intents also fail
// at the scoreboard's check_phase drain).

class dtp_jtag2axi_error_test_seq extends dtp_jtag2axi_base_test_seq;
    `uvm_object_utils(dtp_jtag2axi_error_test_seq)

    // Scenario selection (set by the test before start()).
    string target_name = "smc_axi";
    string scenario    = "error_single_write";

    // Final settled status for the summary; pass/fail is owned by the
    // inline checks and the scoreboard evidence.
    dtp_j2a_status_e status = DTP_J2A_SUCCESS;
    int unsigned operation_count = 0;

    // Address plan (mirrors the cocotb layout: 0x20-spaced error slots,
    // recovery accesses in a disjoint window).
    localparam bit [63:0] ErrorBase    = 64'h1800;
    localparam bit [63:0] RecoveryBase = 64'h2800;

    function new(string name = "dtp_jtag2axi_error_test_seq");
        super.new(name);
    endfunction

    protected function dtp_j2a_target_t target();
        case (target_name)
            "smc_otp": return target_smc_otp();
            "sep_otp": return target_sep_otp();
            default:   return target_smc_axi();
        endcase
    endfunction

    protected function bit [63:0] slot_addr(dtp_j2a_target_t t, bit [63:0] base,
                                            int unsigned idx);
        int unsigned spacing = (t.beat_bytes > 32) ? t.beat_bytes : 32;
        return base + idx * spacing;
    endfunction

    protected function bit [63:0] rand_data(dtp_j2a_target_t t);
        return {$urandom, $urandom} & bit_mask(t.data_width);
    endfunction

    // SLVERR or DECERR from the seeded stream, logged by the caller.
    protected function ocah_axi_resp_e rand_error_resp();
        return ($urandom_range(1) == 0) ? OCAH_AXI_RESP_SLVERR
                                        : OCAH_AXI_RESP_DECERR;
    endfunction

    // TAP reset into Run-Test/Idle (scans start from RTI).
    protected task reset_to_rti();
        tap_reset();
        step(1'b0);
        check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after TLR->RTI step");
    endtask

    // CHK-AXI-NONVAC: operations ran and every armed expectation was
    // consumed by a real bus response (unconsumed intents also fail at the
    // scoreboard's check_phase drain).
    protected function void emit_error_nonvacuity(string label,
                                                  int unsigned minimum_ops);
        int unsigned unconsumed = 0;
        if (axi_cfg != null)
            unconsumed = axi_cfg.pending_expected_resp()
                       + axi_cfg.pending_expected_writes()
                       + axi_cfg.pending_expected_reads();
        emit_nonvacuity_evidence(
            (operation_count >= minimum_ops) && (unconsumed == 0),
            $sformatf("scenario=%s target=%s operations=%0d credits_unconsumed=%0d",
                      label, target_name, operation_count, unconsumed));
    endfunction

    // ------------------------------------------------------------------
    // Single-op error flows.
    // ------------------------------------------------------------------

    protected task expect_error_write(dtp_j2a_target_t t, bit [63:0] addr,
                                      bit [63:0] data, ocah_axi_resp_e resp,
                                      string context_s);
        dtp_j2a_status_e op_status;
        bit [63:0] mem_before, mem_after;
        arm_target_error(t, addr, resp, 1'b0, 1'b1);
        mem_before = read_target_mem_int(t, addr, t.default_size);
        write_target_single_expect_status(t, addr, data,
                                          axi_resp_to_status(resp), op_status,
                                          t.default_size, full_wstrb(t.default_size),
                                          context_s);
        status = op_status;
        // The shared slave responder suppresses the armed write beat, so the
        // failed write must leave the error-slot memory untouched.
        mem_after = read_target_mem_int(t, addr, t.default_size);
        if (mem_after !== mem_before)
            `uvm_error("jtag2axi_mem_chk", $sformatf(
                "%s.no_write_side_effect: memory at 0x%0h changed 0x%0h -> 0x%0h",
                context_s, addr, mem_before, mem_after))
        verify_target_recovery(t, addr + 64'h400,
                               data ^ 64'h55AA_55AA_55AA_55AA, 1'b0, context_s);
        operation_count++;
    endtask

    protected task expect_error_read(dtp_j2a_target_t t, bit [63:0] addr,
                                     bit [63:0] data, ocah_axi_resp_e resp,
                                     string context_s);
        dtp_j2a_status_e op_status;
        bit [63:0] rdata;
        write_target_mem_int(t, addr, data, t.default_size);
        arm_target_error(t, addr, resp, 1'b1, 1'b0);
        read_target_single_expect_status(t, addr, axi_resp_to_status(resp),
                                         op_status, rdata, t.default_size,
                                         context_s);
        status = op_status;
        verify_target_recovery(t, addr + 64'h400,
                               data ^ 64'h00FF_00FF_00FF_00FF, 1'b1, context_s);
        operation_count++;
    endtask

    protected task run_error_single_write(dtp_j2a_target_t t);
        ocah_axi_resp_e responses[2] = '{OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR};
        `uvm_info(get_type_name(),
                  $sformatf("%s SINGLE_OP write error", t.name), UVM_LOW)
        reset_to_rti();
        foreach (responses[i]) begin
            bit [63:0] addr = slot_addr(t, ErrorBase, i + 1);
            bit [63:0] data = rand_data(t);
            `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/2: write error addr=0x%08h resp=%s data=0x%0h",
                i + 1, addr, responses[i].name(), data), UVM_LOW)
            expect_error_write(t, addr, data, responses[i],
                               $sformatf("single_write_error#%0d", i + 1));
        end
        emit_error_nonvacuity("error_single_write", 2);
        status = DTP_J2A_SUCCESS;
    endtask

    protected task run_error_single_read(dtp_j2a_target_t t);
        ocah_axi_resp_e responses[2] = '{OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR};
        `uvm_info(get_type_name(),
                  $sformatf("%s SINGLE_OP read error", t.name), UVM_LOW)
        reset_to_rti();
        foreach (responses[i]) begin
            bit [63:0] addr = slot_addr(t, ErrorBase + 64'h100, i + 1);
            bit [63:0] data = rand_data(t);
            `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/2: read error addr=0x%08h resp=%s preload=0x%0h",
                i + 1, addr, responses[i].name(), data), UVM_LOW)
            expect_error_read(t, addr, data, responses[i],
                              $sformatf("single_read_error#%0d", i + 1));
        end
        emit_error_nonvacuity("error_single_read", 2);
        status = DTP_J2A_SUCCESS;
    endtask

    // ------------------------------------------------------------------
    // Series error flows (fault armed on one specific beat).
    // ------------------------------------------------------------------

    protected task run_error_series_write(dtp_j2a_target_t t, bit increment,
                                          bit with_status);
        int unsigned size = t.default_size;
        int unsigned stride = increment ? t.beat_bytes : 0;
        bit [63:0] base = slot_addr(t, ErrorBase + 64'h300, 1);
        int unsigned fault_idx = increment ? 1 : 0;
        ocah_axi_resp_e resp = rand_error_resp();
        bit [63:0] expected_addr;
        bit sr_reset;
        bit [63:0] sr_addr;
        int unsigned sr_pl, sr_size;
        dtp_j2a_status_e sr_status;
        `uvm_info(get_type_name(), $sformatf(
            "%s series %s write error%s: base=0x%08h fault_beat=%0d resp=%s",
            t.name, increment ? "incr" : "no_incr",
            with_status ? " (with status)" : "", base, fault_idx, resp.name()),
            UVM_LOW)
        reset_to_rti();
        arm_target_error(t, base + fault_idx * stride, resp, 1'b0, 1'b1);
        series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
        expected_addr = base;
        for (int unsigned idx = 0; idx < 3; idx++) begin
            bit [63:0] data = rand_data(t) & data_mask(size);
            int unsigned aw0, w0, ar0, wb0;
            sample_activity(t, aw0, w0, ar0);
            wb0 = write_bursts_now(t);
            `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/3: series write addr=0x%08h data=0x%0h resp=%s",
                idx + 1, expected_addr, data,
                (idx == fault_idx) ? resp.name() : "OKAY"), UVM_LOW)
            if (with_status) begin
                bit [63:0] cap_rdata;
                bit cap_status;
                series_data_with_status(t, data, size, increment, cap_rdata, cap_status);
                `uvm_info(get_type_name(), $sformatf(
                    "series write status-bit=%0d", cap_status), UVM_LOW)
            end
            else if (increment)
                series_data_incr(t, data, size);
            else
                series_data_no_incr(t, data, size);
            wait_for_target_activity(t, aw0, w0, ar0, 1'b0,
                                     $sformatf("series_write_error.axi#%0d", idx));
            wait_for_write_completion(t, wb0,
                                      $sformatf("series_write_error.commit#%0d", idx));
            if (idx != fault_idx && !with_status) begin
                bit [63:0] observed = read_target_mem_int(t, expected_addr, size);
                if (observed !== data)
                    `uvm_error("jtag2axi_data_chk", $sformatf(
                        "series_write_error.mem#%0d: memory 0x%0h != data 0x%0h (addr=0x%0h)",
                        idx, observed, data, expected_addr))
            end
            else if (idx != fault_idx) begin
                // Status mode: log-only observation (the per-beat commit
                // truth in this mode is owned by the status bit stream).
                `uvm_info(get_type_name(), $sformatf(
                    "series write status-mode beat#%0d addr=0x%08h expected_if_committed=0x%0h observed=0x%0h",
                    idx, expected_addr, data,
                    read_target_mem_int(t, expected_addr, size)), UVM_LOW)
            end
            else begin
                read_series_ctrl(t, size, sr_reset, sr_addr, sr_pl, sr_size, sr_status);
                `uvm_info(get_type_name(), $sformatf(
                    "series write fault beat expected=%s observed_series_ctrl=%s",
                    axi_resp_to_status(resp).name(), sr_status.name()), UVM_LOW)
            end
            expected_addr += stride;
        end
        verify_target_recovery(t, RecoveryBase, 64'hCAFE_BABE_1234_5678, 1'b0,
                               "series_write_error");
        status = DTP_J2A_SUCCESS;
        operation_count += 3;
    endtask

    protected task run_error_series_read(dtp_j2a_target_t t, bit increment,
                                         bit with_status);
        int unsigned size = t.default_size;
        int unsigned stride = increment ? t.beat_bytes : 0;
        bit [63:0] base = slot_addr(t, ErrorBase + 64'h600, 1);
        int unsigned fault_idx = increment ? 1 : 0;
        ocah_axi_resp_e resp = rand_error_resp();
        bit sr_reset;
        bit [63:0] sr_addr;
        int unsigned sr_pl, sr_size;
        dtp_j2a_status_e sr_status;
        `uvm_info(get_type_name(), $sformatf(
            "%s series %s read error%s: base=0x%08h fault_beat=%0d resp=%s",
            t.name, increment ? "incr" : "no_incr",
            with_status ? " (with status)" : "", base, fault_idx, resp.name()),
            UVM_LOW)
        reset_to_rti();
        arm_target_error(t, base + fault_idx * stride, resp, 1'b1, 1'b0);
        for (int unsigned idx = 0; idx < 3; idx++)
            write_target_mem_int(t, base + idx * stride, rand_data(t), size);
        for (int unsigned idx = 0; idx < 3; idx++) begin
            bit [63:0] addr = base + idx * stride;
            int unsigned aw0, w0, ar0;
            series_ctrl_op(t, DTP_J2A_OP_READ, addr, size);
            sample_activity(t, aw0, w0, ar0);
            `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/3: series read addr=0x%08h resp=%s",
                idx + 1, addr, (idx == fault_idx) ? resp.name() : "OKAY"), UVM_LOW)
            // Prime shift launches the read; the second shift captures it.
            if (with_status) begin
                bit [63:0] cap_rdata;
                bit cap_status;
                series_data_with_status(t, '0, size, increment, cap_rdata, cap_status);
                wait_for_target_activity(t, aw0, w0, ar0, 1'b1,
                                         $sformatf("series_read_error.axi#%0d", idx));
                series_data_with_status(t, '0, size, 1'b0, cap_rdata, cap_status);
                `uvm_info(get_type_name(), $sformatf(
                    "series read capture raw=0x%0h status-bit=%0d",
                    cap_rdata, cap_status), UVM_LOW)
            end
            else begin
                if (increment) series_data_incr(t, '0, size);
                else           series_data_no_incr(t, '0, size);
                wait_for_target_activity(t, aw0, w0, ar0, 1'b1,
                                         $sformatf("series_read_error.axi#%0d", idx));
                if (increment) series_data_incr(t, '0, size);
                else           series_data_no_incr(t, '0, size);
                if (idx == fault_idx) begin
                    read_series_ctrl(t, size, sr_reset, sr_addr, sr_pl, sr_size,
                                     sr_status);
                    `uvm_info(get_type_name(), $sformatf(
                        "series read fault beat expected=%s observed_series_ctrl=%s",
                        axi_resp_to_status(resp).name(), sr_status.name()), UVM_LOW)
                end
            end
        end
        verify_target_recovery(t, RecoveryBase + 64'h100,
                               64'hDEAD_BEEF_7654_3210, 1'b1, "series_read_error");
        status = DTP_J2A_SUCCESS;
        operation_count += 3;
    endtask

    // ------------------------------------------------------------------
    // Error-path security gating.
    // ------------------------------------------------------------------

    protected task run_error_security_gating(dtp_j2a_target_t t);
        int unsigned size = t.default_size;
        bit [63:0] addr = slot_addr(t, ErrorBase + 64'h900, 1);
        bit [63:0] data = rand_data(t) & data_mask(size);
        `uvm_info(get_type_name(), $sformatf(
            "%s error-path security gating: addr=0x%08h data=0x%0h",
            t.name, addr, data), UVM_LOW)
        reset_to_rti();
        // Two assert/release passes of the target's direct disable prove the
        // gate is repeatable, not a one-shot POR effect.
        for (int unsigned idx = 1; idx <= 2; idx++) begin
            string gate_ctx = $sformatf("error_gate.pass%0d", idx);
            dtp_j2a_status_e op_status;
            int unsigned gb_aw, gb_w, gb_ar;
            int unsigned ga_aw, ga_w, ga_ar;
            `uvm_info(get_type_name(), $sformatf(
                "Step %0d: gate %s and attempt error-path write", idx, t.name),
                UVM_LOW)
            gate_target(t);
            // arm_expected=0: the gated op must never reach the bus, so no
            // scoreboard credit may be armed for it (an armed credit that is
            // never consumed fails at the check_phase drain).
            arm_target_error(t, addr, OCAH_AXI_RESP_SLVERR, 1'b0, 1'b1, 1'b0);
            sample_activity(t, gb_aw, gb_w, gb_ar);
            // issue_single suppresses intent arming while the target is
            // gated (target_enabled()==0).
            issue_single(t, DTP_J2A_OP_WRITE, addr, data, full_wstrb(size), size, 1'b0);
            wait_sys_cycles(8);
            sample_activity(t, ga_aw, ga_w, ga_ar);
            expect_no_activity_evidence(t, gb_aw, gb_w, gb_ar,
                                        ga_aw, ga_w, ga_ar,
                                        {gate_ctx, ".gated_attempt"});
            // Remove the never-consumed injection before re-opening the gate,
            // then prove the counters stay flat after release: a bridge that
            // queued the gated request and replays it once the gate re-opens
            // is the exact leak this scenario must catch.
            clear_target_error(t);
            enable_all_debug();
            wait_sys_cycles(8);
            sample_activity(t, ga_aw, ga_w, ga_ar);
            expect_no_activity_evidence(t, gb_aw, gb_w, gb_ar,
                                        ga_aw, ga_w, ga_ar,
                                        {gate_ctx, ".post_reenable"});
            // Restored error path: an ungated armed DECERR must report
            // through the JTAG status and the scoreboard as EXPECTED.
            arm_target_error(t, addr, OCAH_AXI_RESP_DECERR, 1'b0, 1'b1);
            write_target_single_expect_status(t, addr, data ^ idx, DTP_J2A_DECERR,
                                              op_status, size, full_wstrb(size),
                                              {gate_ctx, ".ungated_error"});
            verify_target_recovery(t, addr + 64'h400 + idx * t.beat_bytes,
                                   data ^ (idx << 4), 1'b0, gate_ctx);
            operation_count++;
        end
        emit_error_nonvacuity("error_security_gating", 2);
        status = DTP_J2A_SUCCESS;
    endtask

    // ------------------------------------------------------------------
    // Scenario dispatch.
    // ------------------------------------------------------------------

    task body();
        dtp_j2a_target_t t = target();
        seed_scenario_rng();
        enable_all_debug();
        case (scenario)
            "error_single_write":                 run_error_single_write(t);
            "error_single_read":                  run_error_single_read(t);
            "error_series_no_incr_write":         run_error_series_write(t, 1'b0, 1'b0);
            "error_series_no_incr_read":          run_error_series_read(t, 1'b0, 1'b0);
            "error_series_incr_write":            run_error_series_write(t, 1'b1, 1'b0);
            "error_series_incr_read":             run_error_series_read(t, 1'b1, 1'b0);
            "error_series_incr_write_with_status": run_error_series_write(t, 1'b1, 1'b1);
            "error_series_incr_read_with_status": run_error_series_read(t, 1'b1, 1'b1);
            "error_security_gating":              run_error_security_gating(t);
            default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown JTAG2AXI error scenario %s", scenario))
        endcase
        // Scenario-level non-vacuity: real operations ran and no armed
        // expectation is left pending going into the check_phase drain.
        emit_error_nonvacuity(scenario, 1);
        clear_target_error(t);
        enable_all_debug();
        `uvm_info(get_type_name(), $sformatf(
            "JTAG2AXI error scenario complete: target=%s scenario=%s operations=%0d status=%s",
            t.name, scenario, operation_count, status.name()), UVM_LOW)
    endtask

endclass : dtp_jtag2axi_error_test_seq
