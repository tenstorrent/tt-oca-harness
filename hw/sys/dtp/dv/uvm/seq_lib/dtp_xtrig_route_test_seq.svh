// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// XTRIG CTP protocol scenarios — the SV analogue of the CTP scenario set in
// the cocotb dtp_xtrig_base_test_seq. One parameterized sequence,
// dispatched on `scenario`:
//
//   wire_or         pulse stretching (width = stretch+1), busy-clear status,
//                   and external-to-internal synchronization on a seeded
//                   CTP/internal pair
//   p2p             point-to-point req/ack handshakes in both directions
//                   with CSR status cross-checks
//   reset           per-CTP config-reset recovery from a deadlocked P2P
//                   handshake, then system-reset defaults with quiet pins
//   random          seeded CTP configuration mix (mode/invert/stretch)
//                   proving enable and pad-polarity behavior per draw
//   dst_port_sweep  one seeded internal source swept across every CTM
//                   destination port
//
// Every scenario draws its ports per pass from the seeded scenario RNG (per
// spec, every CTP and internal CT is interchangeable), so the 16-pass floor
// covers different port/stretch combinations.

class dtp_xtrig_route_test_seq extends dtp_xtrig_base_test_seq;
  `uvm_object_utils(dtp_xtrig_route_test_seq)

  function new(string name = "dtp_xtrig_route_test_seq");
    super.new(name);
  endfunction

  virtual task dispatch_scenario();
    case (scenario)
      "wire_or":        run_wire_or();
      "p2p":            run_p2p();
      "reset":          run_reset();
      "random":         run_random();
      "dst_port_sweep": run_dst_port_sweep();
      default:          super.dispatch_scenario();
    endcase
  endtask

  protected task run_wire_or();
    int unsigned ctp_idx = $urandom_range(XtrigNumCtp - 1);
    int unsigned int_idx = $urandom_range(XtrigNumIntCt - 1);
    int unsigned int_port = internal_ct_port(int_idx);
    int unsigned ctp_port = external_ctp_port(ctp_idx);
    bit [15:0] stretches[3];
    bit [31:0] status;
    int unsigned width;
    `uvm_info(get_type_name(), "XTRIG CTP wire-OR pulse stretching and sync", UVM_LOW)
    // Seeded per-pass port pair and an extra random stretch: per spec
    // every CTP behaves identically, so each loop proves the same
    // properties on a different CTP/internal pair and stretch width.
    stretches = '{16'd15, 16'd0, 16'($urandom_range(14, 1))};
    foreach (stretches[s]) begin
      bit [15:0] stretch = stretches[s];
      `uvm_info(get_type_name(), $sformatf(
                "Configure wire-OR stretch=%0d and route internal CT %0d to CTP %0d",
                stretch,
                int_idx,
                ctp_idx
                ), UVM_LOW)
      program_ctp(ctp_idx, CtpModeWireOr, 1'b0, 1'b0, stretch);
      program_route(int_port, 32'd1 << ctp_port, $sformatf("wire_or.stretch%0d", stretch));
      clear_xtrig_inputs();
      drive_internal_dst_pulse(int_idx, 1);
      measure_mask_width("xtrig_ctp_req_out_dout_en", 32'd1 << ctp_idx, width);
      check_evidence(ChkStretch, $sformatf("wire_or.stretch%0d.width", stretch), 64'(width),
                     64'(stretch) + 64'd1);
      csr_read(ctp_status_addr(ctp_idx), status, $sformatf("wire_or.stretch%0d.status", stretch));
      wait_sys_cycles(stretch + 4);
      csr_read(ctp_status_addr(ctp_idx), status, $sformatf(
               "wire_or.stretch%0d.status_clear", stretch));
      check_evidence(ChkStretch, $sformatf("wire_or.stretch%0d.busy_clear", stretch),
                     64'((status & CtpStatusBusy) != 0), 64'd0);
    end
    `uvm_info(get_type_name(), "Drive external CT_Req_out input and expect internal CT delivery",
              UVM_LOW)
    program_ctp(ctp_idx, CtpModeWireOr, 1'b0, 1'b0, 16'd0);
    program_route(ctp_port, 32'd1 << int_port, "wire_or.external_to_internal");
    drive_ctp_req_out_din_pulse(ctp_idx, 2);
    wait_signal_mask("xtrig_ctm_src_req", 32'd1 << int_idx, 32'd1 << int_idx, 60,
                     "wire_or.external_sync");
  endtask

  protected task run_p2p();
    int unsigned ctp_idx = $urandom_range(XtrigNumCtp - 1);
    int unsigned int_idx = $urandom_range(XtrigNumIntCt - 1);
    int unsigned ctp_port = external_ctp_port(ctp_idx);
    int unsigned int_port = internal_ct_port(int_idx);
    bit [31:0] status;
    `uvm_info(get_type_name(), "XTRIG CTP point-to-point handshakes", UVM_LOW)
    // Seeded per-pass port pair: each loop proves the P2P handshakes on
    // a different CTP/internal combination.
    program_ctp(ctp_idx, CtpModeP2p, 1'b0, 1'b0, 16'd0);

    `uvm_info(get_type_name(), "Step 1: internal trigger asserts CT_Req_out until CT_Ack_in",
              UVM_LOW)
    program_route(int_port, 32'd1 << ctp_port, "p2p.internal_to_ctp");
    pulse_ctm_dst_req(32'd1 << int_idx, 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", 32'd1 << ctp_idx, 32'd1 << ctp_idx, 60,
                     "p2p.req_out");
    csr_read(ctp_status_addr(ctp_idx), status, "p2p.status_busy");
    check_evidence(ChkCsr, "p2p.status.req_out", 64'((status & CtpStatusReqOut) != 0), 64'd1);
    drive_ctp_p2p_ack_in(ctp_idx, 1'b1);
    wait_sys_cycles(3);
    drive_ctp_p2p_ack_in(ctp_idx, 1'b0);
    wait_signal_mask("xtrig_ctp_req_out_dout", 32'd1 << ctp_idx, '0, 60, "p2p.req_out_clear");

    `uvm_info(get_type_name(),
              "Step 2: external CT_Req_in asserts CT_Ack_out and delivers the internal trigger",
              UVM_LOW)
    program_route(ctp_port, 32'd1 << int_port, "p2p.ctp_to_internal");
    drive_ctp_p2p_req_in(ctp_idx, 1'b1);
    wait_signal_mask("xtrig_ctp_ack_out_dout", 32'd1 << ctp_idx, 32'd1 << ctp_idx, 60,
                     "p2p.ack_out");
    wait_signal_mask("xtrig_ctm_src_req", 32'd1 << int_idx, 32'd1 << int_idx, 60,
                     "p2p.internal_delivery");
    drive_ctp_p2p_req_in(ctp_idx, 1'b0);
    wait_sys_cycles(3);
  endtask

  protected task run_reset();
    int unsigned ctp_idx = $urandom_range(XtrigNumCtp - 1);
    int unsigned int_idx = $urandom_range(XtrigNumIntCt - 1);
    int unsigned ctp_b, int_b;
    int unsigned ctp_port = external_ctp_port(ctp_idx);
    int unsigned int_port = internal_ct_port(int_idx);
    bit [31:0] status;
    `uvm_info(get_type_name(), "XTRIG CTP reset recovery", UVM_LOW)
    // Seeded per-pass ports: each loop deadlocks and recovers a
    // different CTP, and system-resets a different second CTP.
    do ctp_b = $urandom_range(XtrigNumCtp - 1); while (ctp_b == ctp_idx);
    do int_b = $urandom_range(XtrigNumIntCt - 1); while (int_b == int_idx);
    program_ctp(ctp_idx, CtpModeP2p);
    program_route(int_port, 32'd1 << ctp_port, "reset.deadlock_setup");
    pulse_ctm_dst_req(32'd1 << int_idx, 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", 32'd1 << ctp_idx, 32'd1 << ctp_idx, 60,
                     "reset.stuck_req");
    csr_read(ctp_status_addr(ctp_idx), status, "reset.busy_before");
    check_evidence(ChkCsr, "reset.busy_before", 64'((status & CtpStatusBusy) != 0), 64'd1);

    // Per-CTP config reset releases the deadlocked handshake without
    // touching any other state.
    program_ctp(ctp_idx, CtpModeP2p, 1'b0, 1'b1);
    wait_sys_cycles(3);
    wait_signal_mask("xtrig_ctp_req_out_dout", 32'd1 << ctp_idx, '0, 60,
                     "reset.config_reset_clear");
    program_ctp(ctp_idx, CtpModeP2p, 1'b0, 1'b0);
    verify_route(int_port, 32'd1 << ctp_port, CtpModeP2p, "reset.post_config_reset");

    // System reset returns configuration and routing to defaults.
    program_ctp(ctp_b, CtpModeWireOr, 1'b1, 1'b0, 16'($urandom_range(15, 1)));
    program_ctm_src(ctp_b, 32'd1 << internal_ct_port(int_b));
    pulse_reset(3);
    write_read_check(ctp_config_addr(ctp_b), '0, '0, 4'hF, CtpConfigMask, $sformatf(
                     "reset.ctp%0d.default_cfg", ctp_b));
    write_read_check(ctp_stretch_addr(ctp_b), '0, '0, 4'hF, CtpStretchMask, $sformatf(
                     "reset.ctp%0d.default_stretch", ctp_b));
    check_all_ctm_cleared("reset.system");
    // The model resets with the hardware.
    ctm_model = new();
    check_quiet("system_reset");
  endtask

  protected task run_random();
    `uvm_info(get_type_name(), "XTRIG seeded random CTP configuration", UVM_LOW)
    for (int unsigned idx = 0; idx < random_count; idx++) begin
      int unsigned        ctp_idx = $urandom_range(XtrigNumCtp - 1);
      int unsigned        mode = $urandom_range(1);
      bit                 invert = bit'($urandom_range(1));
      bit          [15:0] stretch = 16'($urandom_range(7));
      int unsigned        int_idx = $urandom_range(XtrigNumIntCt - 1);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: ctp=%0d mode=%0d invert=%0d stretch=%0d internal=%0d",
                idx + 1,
                random_count,
                ctp_idx,
                mode,
                invert,
                stretch,
                int_idx
                ), UVM_LOW)
      program_ctp(ctp_idx, mode, invert, 1'b0, stretch);
      program_route(internal_ct_port(int_idx), 32'd1 << external_ctp_port(ctp_idx), $sformatf(
                    "random.%0d", idx));
      pulse_ctm_dst_req(32'd1 << int_idx, 1);
      if (mode == CtpModeP2p) begin
        wait_signal_mask("xtrig_ctp_req_out_dout_en", 32'd1 << ctp_idx, 32'd1 << ctp_idx, 60,
                         $sformatf("random.%0d.oen", idx));
        log_xtrig_sample($sformatf("random.%0d.p2p_active", idx));
        drive_ctp_p2p_ack_in(ctp_idx, 1'b1);
        wait_sys_cycles(2);
        drive_ctp_p2p_ack_in(ctp_idx, 1'b0);
      end else begin
        bit [31:0] expected_data = invert ? (32'd1 << ctp_idx) : '0;
        wait_signal_mask("xtrig_ctp_req_out_dout_en", 32'd1 << ctp_idx, 32'd1 << ctp_idx, 60,
                         $sformatf("random.%0d.wire_en", idx));
        wait_signal_mask("xtrig_ctp_req_out_dout", 32'd1 << ctp_idx, expected_data, 60, $sformatf(
                         "random.%0d.wire_polarity", idx));
      end
    end
  endtask

  protected task run_dst_port_sweep();
    int unsigned input_port = internal_ct_port($urandom_range(XtrigNumIntCt - 1));
    `uvm_info(get_type_name(), "XTRIG deterministic destination-port sweep", UVM_LOW)
    // Seeded per-pass source: the output sweep stays exhaustive while
    // each loop drives it from a different internal CT.
    for (int unsigned output_port = 0; output_port < XtrigNumCtmPorts; output_port++) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: input port %0d -> output port %0d",
                output_port + 1,
                XtrigNumCtmPorts,
                input_port,
                output_port
                ), UVM_LOW)
      verify_route(input_port, 32'd1 << output_port, CtpModeWireOr, $sformatf(
                   "dst_sweep.port%0d", output_port));
      if (!is_ctp_port(output_port)) pulse_ctm_src_ack(32'd1 << int_idx_from_port(output_port), 1);
    end
  endtask

endclass : dtp_xtrig_route_test_seq
