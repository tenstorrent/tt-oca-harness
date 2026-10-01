// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// XTRIG CTP protocol scenarios — the SV analogue of the CTP scenario set in
// the cocotb dtp_xtrig_base_test_seq. One parameterized sequence,
// dispatched on `scenario`:
//
//   wire_or         pulse stretching (enable and busy widths = stretch+1,
//                   aligned rise), BUSY over the CSR for wide pulses,
//                   busy-clear status, and external-to-internal
//                   synchronization on a seeded CTP/internal pair
//   p2p             point-to-point req/ack handshakes in both directions
//                   with STATUS BUSY/REQ_OUT/ACK_IN/REQ_IN/ACK_OUT read at
//                   every phase
//   reset           per-CTP config-reset recovery from a deadlocked P2P
//                   handshake, then a system reset landing on an active
//                   inverted wire-OR pulse and a held P2P receive: reset
//                   window, CSR defaults, fresh route
//   random          seeded CTP configuration mix (mode/invert/stretch)
//                   proving route, isolation, width, and pad polarity per
//                   draw
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
      "wire_or_bus":    run_wire_or_bus();
      "p2p":            run_p2p();
      "reset":          run_reset();
      "random":         run_random();
      "dst_port_sweep": run_dst_port_sweep();
      default: super.dispatch_scenario();
    endcase
  endtask

  protected task run_wire_or();
    int unsigned ctp_idx = $urandom_range(XtrigNumCtp - 1);
    int unsigned int_idx = $urandom_range(XtrigNumIntCt - 1);
    int unsigned int_port = internal_ct_port(int_idx);
    int unsigned ctp_port = external_ctp_port(ctp_idx);
    bit [15:0] stretches[3];
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
      run_wire_or_pulse(ctp_idx, int_idx, stretch);
    end
    for (int unsigned invert = 0; invert < 2; invert++) begin
      `uvm_info(
          get_type_name(), $sformatf(
          "A chiplet pulls the CTP's shared wire (INVERT=%0d) and the internal CT delivers", invert
          ), UVM_LOW)
      program_ctp(ctp_idx, CtpModeWireOr, bit'(invert), 1'b0, 16'd0);
      program_route(ctp_port, 32'd1 << int_port, $sformatf(
                    "wire_or.external_to_internal.inv%0d", invert));
      run_route_window(32'd1 << ctp_port, 32'd1 << int_port, CtpModeWireOr, $sformatf(
                       "wire_or.external_sync.inv%0d", invert));
    end
    program_ctp(ctp_idx, CtpModeWireOr, 1'b0, 1'b0, 16'd0);
  endtask

  // Several CTPs on one shared wire-OR wire: the transmitter's own pull, a
  // chiplet's pull, and the two merged reach every member once.
  protected task run_wire_or_bus();
    int unsigned members[$];
    int unsigned ints[$];
    int unsigned int_outs[$];
    int unsigned int_src, tx, puller;
    bit invert;
    bit [15:0] stretch;
    bit [31:0] member_ports = '0;
    bit [31:0] listener_outputs = '0;
    bit [31:0] transmit_predicted, transmit_intent;
    `uvm_info(get_type_name(), "XTRIG CTPs on one shared wire-OR wire", UVM_LOW)
    // Seeded per pass: the members of the wire, their common sense and
    // stretch, the transmitter, the internal source that triggers it, and
    // one internal output per member.
    pick_distinct(XtrigNumCtp, $urandom_range(4, 2), members);
    invert = bit'($urandom_range(1));
    stretch = 16'($urandom_range(7));
    pick_distinct(XtrigNumIntCt, members.size() + 1, ints);
    int_src = ints.pop_front();
    int_outs = ints;
    tx = members[0];
    puller = members[$];
    foreach (members[i]) member_ports |= 32'd1 << external_ctp_port(members[i]);
    foreach (int_outs[i]) listener_outputs |= 32'd1 << internal_ct_port(int_outs[i]);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "shared wire: CTPs %p (INVERT=%0d, STRETCH_MULT=%0d), transmitter CTP[%0d] from internal CT[%0d], listeners to internal CTs %p",
            members, invert, stretch, tx, int_src, int_outs), UVM_LOW)
    foreach (members[i]) program_ctp(members[i], CtpModeWireOr, invert, 1'b0, stretch);
    share_wire(member_ports, invert);
    clear_ctm_routes();
    program_ctm_src(external_ctp_port(tx), 32'd1 << internal_ct_port(int_src));
    foreach (members[i])
      program_ctm_src(internal_ct_port(int_outs[i]), 32'd1 << external_ctp_port(members[i]));
    transmit_predicted = ctm_model.route(32'd1 << internal_ct_port(int_src))
        | ctm_model.route(member_ports);
    transmit_intent = (32'd1 << external_ctp_port(tx)) | listener_outputs;

    `uvm_info(
        get_type_name(),
        "Step 1: the transmitter pulls the wire: every member, itself included, receives once",
        UVM_LOW)
    open_route_window();
    pulse_ctm_dst_req(32'd1 << int_src, 1);
    check_output_mask(transmit_intent, CtpModeWireOr, transmit_predicted, "wire_or_bus.transmit",
                      IsolationTailCycles + stretch, 32'd1 << internal_ct_port(int_src));
    check_shared_wire_receive(members, "xtrig_ctp_req_out_dout_en", tx, "wire_or_bus.transmit");

    `uvm_info(get_type_name(), "Step 2: a chiplet pulls the wire: every member receives once",
              UVM_LOW)
    open_route_window();
    pull_ctp_wire(puller, $urandom_range(5, 1));
    check_output_mask(listener_outputs, CtpModeWireOr, ctm_model.route(member_ports),
                      "wire_or_bus.chiplet");
    check_shared_wire_receive(members, "xtrig_ctp_wire_ext_assert", puller, "wire_or_bus.chiplet");

    `uvm_info(get_type_name(),
              "Step 3: the transmitter pulls while a chiplet holds the wire: one merged assertion",
              UVM_LOW)
    open_route_window();
    xtrig_vif.xtrig_ctp_wire_ext_assert <= XtrigNumCtp'(32'd1 << puller);
    wait_sys_cycles($urandom_range(3, 1));
    pulse_ctm_dst_req(32'd1 << int_src, 1);
    // The chiplet keeps the wire asserted until the transmitter has released it.
    wait_signal_mask("xtrig_ctp_req_out_dout_en", 32'd1 << tx, 32'd1 << tx, 60,
                     "wire_or_bus.merged.tx_pulls");
    wait_signal_mask("xtrig_ctp_req_out_dout_en", 32'd1 << tx, '0, 60,
                     "wire_or_bus.merged.tx_releases");
    wait_sys_cycles(2);
    xtrig_vif.xtrig_ctp_wire_ext_assert <= '0;
    check_output_mask(transmit_intent, CtpModeWireOr, transmit_predicted, "wire_or_bus.merged",
                      IsolationTailCycles + stretch, '0, 1'b0);
    check_shared_wire_receive(members, "xtrig_ctp_wire_ext_assert", puller, "wire_or_bus.merged");

    share_wire('0, 1'b0);
    clear_ctm_routes();
  endtask

  // One stretched pulse after the internal request: enable and busy widths,
  // aligned rise, BUSY over the CSR, then clear.
  protected task run_wire_or_pulse(int unsigned ctp_idx, int unsigned int_idx, bit [15:0] stretch);
    string label = $sformatf("wire_or.stretch%0d", stretch);
    bit [31:0] mask = 32'd1 << ctp_idx;
    string watched[$] = {"xtrig_ctp_req_out_dout_en", "xtrig_ctp_busy", "xtrig_ctm_dst_req"};
    int unsigned width, pulses, busy_width, busy_pulses;
    int requested_at, enabled_at;
    idle_inputs();
    start_activity_window_on(watched);
    fork
      measure_mask_width(.name("xtrig_ctp_req_out_dout_en"), .mask(mask), .width(width),
                         .pulses(pulses));
      measure_mask_width(.name("xtrig_ctp_busy"), .mask(mask), .width(busy_width),
                         .pulses(busy_pulses));
      begin
        pulse_ctm_dst_req(32'd1 << int_idx, 1);
        wait_signal_mask("xtrig_ctp_req_out_dout_en", mask, mask, 60, {label, ".active"});
        if (stretch >= BusyReadMinStretch) check_status(ctp_idx, {label, ".active"}, .busy(1));
      end
    join
    stop_activity_window();
    requested_at = window_first_rise("xtrig_ctm_dst_req", int_idx);
    enabled_at   = window_first_rise("xtrig_ctp_req_out_dout_en", ctp_idx);
    check_evidence(ChkStretch, {label, ".width"}, 64'(width), 64'(stretch) + 64'd1);
    check_evidence(ChkStretch, {label, ".pulses"}, 64'(pulses), 64'd1);
    check_evidence(ChkStretch, {label, ".busy_width"}, 64'(busy_width), 64'(stretch) + 64'd1);
    check_evidence(ChkStretch, {label, ".busy_pulses"}, 64'(busy_pulses), 64'd1);
    check_evidence(ChkSignal, {label, ".after_input"},
                   64'(requested_at >= 0 && requested_at < enabled_at), 64'd1, $sformatf(
                   "request@%0d enable@%0d", requested_at, enabled_at));
    check_evidence(ChkSignal, {label, ".enable_seen"}, 64'(enabled_at >= 0), 64'd1);
    check_evidence(ChkSignal, {label, ".busy_rise"}, 64'(window_first_rise("xtrig_ctp_busy", ctp_idx
                   )), 64'(enabled_at), "busy rises with the output enable");
    check_status(ctp_idx, {label, ".cleared"}, .busy(0));
    check_evidence(ChkSignal, {label, ".busy_flop_cleared"}, 64'(xtrig_pin("xtrig_ctp_busy"
                   ) & mask), 64'd0);
  endtask

  protected task run_p2p();
    int unsigned ctp_idx = $urandom_range(XtrigNumCtp - 1);
    int unsigned int_idx = $urandom_range(XtrigNumIntCt - 1);
    int unsigned ctp_port = external_ctp_port(ctp_idx);
    int unsigned int_port = internal_ct_port(int_idx);
    bit [31:0] mask = 32'd1 << ctp_idx;
    bit [31:0] inverted, req_out_active;
    string req_out_names[$] = {"xtrig_ctp_req_out_dout"};
    string delivery_names[$] = {"xtrig_ctm_src_req"};
    `uvm_info(get_type_name(), "XTRIG CTP point-to-point handshakes", UVM_LOW)
    // Seeded per-pass port pair: each loop proves the P2P handshakes on
    // a different CTP/internal combination.
    configure_ctp_mode_for_port(ctp_port, CtpModeP2p, 16'd0);

    `uvm_info(get_type_name(),
              "Step 1: internal trigger asserts CT_Req_out and BUSY until CT_Ack_in", UVM_LOW)
    program_route(int_port, 32'd1 << ctp_port, "p2p.internal_to_ctp");
    idle_inputs();
    log_xtrig_sample("p2p.before_request");
    check_evidence(ChkSignal, "p2p.req_out_idle_before", 64'(xtrig_pin("xtrig_ctp_req_out_dout"
                   ) & mask), 64'(pad_level(mask, 1'b0)));
    pulse_ctm_dst_req(32'd1 << int_idx, 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", mask, pad_level(mask, 1'b1), 60, "p2p.req_out");
    check_status(ctp_idx, "p2p.request", .busy(1), .req_out(1), .ack_in(0), .req_in(0),
                 .ack_out(0));
    drive_p2p_ack_in(ctp_idx, 1'b1);
    wait_signal_mask("xtrig_ctp_req_out_dout", mask, pad_level(mask, 1'b0), P2pPhaseMaxCycles,
                     "p2p.req_out_clear");
    check_status(ctp_idx, "p2p.acknowledged", .busy(1), .req_out(0), .ack_in(1), .req_in(0),
                 .ack_out(0));
    // CT_Req_out stays idle from the acknowledge release until STATUS reads
    // the port idle.
    start_activity_window_on(req_out_names);
    drive_p2p_ack_in(ctp_idx, 1'b0);
    wait_signal_mask("xtrig_ctp_busy", mask, '0, 60, "p2p.request_done");
    wait_signal_mask("xtrig_ctp_req_out_dout", mask, pad_level(mask, 1'b0), 60, "p2p.req_out_idle");
    check_status(ctp_idx, "p2p.request_done", .busy(0), .req_out(0), .ack_in(0), .req_in(0),
                 .ack_out(0));
    stop_activity_window();
    inverted = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
    req_out_active = ((window_activity["xtrig_ctp_req_out_dout"] & ~inverted) |
                      (~window_hold["xtrig_ctp_req_out_dout"] & inverted)) & mask;
    check_evidence(ChkSignal, "p2p.request_done.req_out_idle", 64'(req_out_active), 64'd0,
                   $sformatf("cycles=%0d", window_cycles));

    `uvm_info(get_type_name(),
              "Step 2: external CT_Req_in asserts CT_Ack_out, delivers the trigger, then idles",
              UVM_LOW)
    program_route(ctp_port, 32'd1 << int_port, "p2p.ctp_to_internal");
    log_xtrig_sample("p2p.before_response");
    check_evidence(ChkSignal, "p2p.internal_idle_before", 64'(xtrig_pin("xtrig_ctm_src_req"
                   ) & (32'd1 << int_idx)), 64'd0);
    check_evidence(ChkSignal, "p2p.ack_out_idle_before", 64'(xtrig_pin("xtrig_ctp_ack_out_dout"
                   ) & mask), 64'(pad_level(mask, 1'b0)));
    start_activity_window_on(delivery_names);
    drive_p2p_req_in(ctp_idx, 1'b1);
    wait_signal_mask("xtrig_ctp_ack_out_dout", mask, pad_level(mask, 1'b1), 60, "p2p.ack_out");
    wait_signal_mask("xtrig_ctm_src_req", 32'd1 << int_idx, 32'd1 << int_idx, 60,
                     "p2p.internal_delivery");
    wait_signal_mask("xtrig_ctm_src_req", 32'd1 << int_idx, '0, 60, "p2p.internal_released");
    check_status(ctp_idx, "p2p.response", .busy(1), .req_out(0), .ack_in(0), .req_in(1),
                 .ack_out(1));
    drive_p2p_req_in(ctp_idx, 1'b0);
    wait_signal_mask("xtrig_ctp_ack_out_dout", mask, pad_level(mask, 1'b0), P2pPhaseMaxCycles,
                     "p2p.ack_out_clear");
    wait_signal_mask("xtrig_ctp_busy", mask, '0, 60, "p2p.response_done");
    check_status(ctp_idx, "p2p.response_done", .busy(0), .req_out(0), .ack_in(0), .req_in(0),
                 .ack_out(0));
    // One CT_Req_in assertion delivers one pulse, to the routed destination
    // only.
    stop_activity_window();
    check_evidence(ChkSignal, "p2p.internal_delivery.pulses", 64'(window_rise_count(
                   "xtrig_ctm_src_req", int_idx)), 64'd1, $sformatf("cycles=%0d", window_cycles));
    check_evidence(ChkSignal, "p2p.internal_delivery.isolated",
                   64'(window_activity["xtrig_ctm_src_req"] & ~(32'd1 << int_idx)), 64'd0,
                   $sformatf("cycles=%0d", window_cycles));
  endtask

  protected task run_reset();
    int unsigned ctp_idx = $urandom_range(XtrigNumCtp - 1);
    int unsigned int_idx = $urandom_range(XtrigNumIntCt - 1);
    int unsigned ctp_b, int_b, int_c;
    int unsigned ctp_port = external_ctp_port(ctp_idx);
    int unsigned int_port = internal_ct_port(int_idx);
    bit [31:0] mask = 32'd1 << ctp_idx;
    string held[$] = {"xtrig_ctp_req_out_dout", "xtrig_ctp_ack_out_dout", "xtrig_ctp_busy"};
    `uvm_info(get_type_name(), "XTRIG CTP reset recovery", UVM_LOW)
    // Seeded per-pass ports: each loop deadlocks and recovers a
    // different CTP, and system-resets a different second CTP.
    do ctp_b = $urandom_range(XtrigNumCtp - 1); while (ctp_b == ctp_idx);
    do int_b = $urandom_range(XtrigNumIntCt - 1); while (int_b == int_idx);
    do int_c = $urandom_range(XtrigNumIntCt - 1); while (int_c inside {int_idx, int_b});

    `uvm_info(get_type_name(),
              "Step 1: stall the acknowledge of a P2P handshake and recover through CONFIG.RESET",
              UVM_LOW)
    configure_ctp_mode_for_port(ctp_port, CtpModeP2p, 16'd0);
    program_route(int_port, 32'd1 << ctp_port, "reset.deadlock_setup");
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << int_idx, 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", mask, pad_level(mask, 1'b1), 60, "reset.stuck_req");
    check_status(ctp_idx, "reset.before_config_reset", .busy(1), .req_out(1));
    program_ctp(ctp_idx, CtpModeP2p, 1'b0, 1'b1);
    wait_signal_mask("xtrig_ctp_req_out_dout", mask, pad_level(mask, 1'b0), 60,
                     "reset.config_reset_clear");
    check_status(ctp_idx, "reset.config_reset", .busy(0), .req_out(0));
    // The window opens once STATUS has read BUSY=0, because the registered
    // busy flop clears a cycle after RESET forces the sender idle.
    start_activity_window_on(held);
    program_ctp(ctp_idx, CtpModeP2p, 1'b0, 1'b0);
    wait_sys_cycles(IsolationTailCycles);
    stop_activity_window();
    foreach (held[i])
      check_evidence(ChkQuiet, $sformatf("reset.config_reset.%s", held[i]),
                     64'(window_activity[held[i]][ctp_idx]), 64'd0, $sformatf(
                     "cycles=%0d", window_cycles));
    verify_route(int_port, 32'd1 << ctp_port, CtpModeP2p, "reset.post_config_reset");

    `uvm_info(
        get_type_name(),
        "Step 2: system reset while an inverted wire-OR pulse and a P2P receive are active on two CTPs and an internal CT has pulsed",
        UVM_LOW)
    start_live_window(reset_signals);
    program_ctp(ctp_b, CtpModeWireOr, 1'b1, 1'b0, ResetHoldStretch);
    program_ctm_src(ctp_b, 32'd1 << internal_ct_port(int_b));
    program_ctm_src(internal_ct_port(int_c), 32'd1 << internal_ct_port(int_b));
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << int_b, 1);
    wait_signal_mask("xtrig_ctp_req_out_dout_en", 32'd1 << ctp_b, 32'd1 << ctp_b, 60,
                     "reset.active_before");
    wait_window_fired("xtrig_ctm_src_req", 32'd1 << int_c, 60, "reset.internal_active", 1'b1);
    drive_p2p_req_in(ctp_idx, 1'b1);
    wait_signal_mask("xtrig_ctp_ack_out_dout", mask, pad_level(mask, 1'b1), 60,
                     "reset.rx_ack_held");
    reset_window("xtrig_reset", reset_signals);
    check_ctp_defaults("reset.system");
    check_all_ctm_cleared("reset.system");
    verify_route(internal_ct_port(int_b), 32'd1 << external_ctp_port(ctp_b), CtpModeWireOr,
                 "reset.post_system_reset");
  endtask

  protected task run_random();
    `uvm_info(get_type_name(), "XTRIG seeded random CTP configuration", UVM_LOW)
    // The first two iterations take one mode each, so every pass records a
    // stretch width and a P2P handshake; the rest draw the mode at random.
    for (int unsigned idx = 0; idx < random_count; idx++) begin
      int unsigned ctp_idx = $urandom_range(XtrigNumCtp - 1);
      int unsigned mode    = (idx == 0) ? CtpModeWireOr : (idx == 1) ? CtpModeP2p : $urandom_range(1);
      bit          invert  = bit'($urandom_range(1));
      bit [15:0]   stretch = 16'($urandom_range(7));
      int unsigned int_idx = $urandom_range(XtrigNumIntCt - 1);
      string label = $sformatf("random.%0d", idx);
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
      if (mode == CtpModeWireOr) begin
        verify_wire_or_pulse(ctp_idx, int_idx, stretch, invert, label);
        continue;
      end
      csr_write(ctp_config_addr(ctp_idx), pack_ctp_config(mode, invert, 1'b1), 4'hF, $sformatf(
                "ctp%0d.handshake_reset", ctp_idx));
      program_ctp(ctp_idx, mode, invert, 1'b0, stretch);
      program_route(internal_ct_port(int_idx), 32'd1 << external_ctp_port(ctp_idx), label);
      run_route_window(32'd1 << internal_ct_port(int_idx), 32'd1 << external_ctp_port(ctp_idx),
                       CtpModeP2p, label);
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
