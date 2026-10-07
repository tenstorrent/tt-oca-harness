// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CTM routing scenarios. The cocotb twin is seq_lib/dtp_ctm_route_test_seq.py.
// One parameterized sequence, dispatched on `scenario`:
//
//   ctm_wire_or_{cla_to_ctp, ctp_to_cla, cla_to_cla, ctp_to_ctp}
//       one seeded multicast route of the class, every destination firing
//       in one cycle with one pulse of the route stretch width, plus a
//       two-source overlap onto one shared destination: each source alone,
//       then both in the same cycle merging into one pulse of the
//       single-source width
//   ctm_p2p_{cla_to_ctp, ctp_to_cla, cla_to_cla, ctp_to_ctp}
//       three seeded source/destination pairs of the class with full
//       req/ack handshakes
//   ctm_reset_{wire_or_mode, p2p_mode, all_modes}
//       routes established and traffic active (a long stretched pulse,
//       or a request awaiting its acknowledge and a received request held;
//       both classes programmed together in all_modes), the reset window
//       with every watched output and busy flop active before the reset and
//       quiet across it, select and CTP defaults, then fresh routes recover
//   ctm_rand_{all_scenarios, wire_or_only, p2p_only, cla_to_ctp, ctp_to_cla}
//       seeded random route mixes constrained to the named class; a wire-OR
//       iteration selects one or two sources on every output and pulses
//       them together; a point-to-point iteration adds a second, disjoint
//       route alongside its own and pulses each alone
//
// Every route is proved with the CSR readback, the CTM reference-model
// prediction (CHK-XTRIG-ROUTE-MODEL — the +DTP_XTRIG_CHECKER_NEGATIVE
// target), the routed-output observation, and the unselected-output
// isolation check. Port picks come from the seeded scenario RNG per pass;
// inputs are kept out of the output masks so the isolation check stays
// meaningful.

class dtp_ctm_route_test_seq extends dtp_xtrig_base_test_seq;
  `uvm_object_utils(dtp_ctm_route_test_seq)

  localparam int unsigned RandPulseMaxCycles = 8;
  localparam int unsigned RandLeadMaxCycles = 3;

  // Pending routes of a random mix, as source * 32 + destination in a seeded
  // order, kept across the passes of the test: each iteration starts from
  // the first pending route, and only a window whose one input is a route's
  // source retires that route.
  protected static int unsigned m_route_pending[string][$];
  // The routes of a random mix that a single-source window has driven in the
  // test, keyed by source * 32 + destination.
  protected static bit m_route_driven[string][int unsigned];

  // Passes the test runs; the ctm_rand_cla_to_ctp and ctm_rand_ctp_to_cla
  // mixes need it to find their last pass, which continues until every
  // route of their class has been driven alone.
  int unsigned total_passes;

  function new(string name = "dtp_ctm_route_test_seq");
    super.new(name);
  endfunction

  virtual task dispatch_scenario();
    case (scenario)
      "ctm_wire_or_cla_to_ctp": run_wire_or_cla_to_ctp();
      "ctm_wire_or_ctp_to_cla": run_wire_or_ctp_to_cla();
      "ctm_wire_or_cla_to_cla": run_wire_or_cla_to_cla();
      "ctm_wire_or_ctp_to_ctp": run_wire_or_ctp_to_ctp();
      "ctm_p2p_cla_to_ctp":     run_p2p_cla_to_ctp();
      "ctm_p2p_ctp_to_cla":     run_p2p_ctp_to_cla();
      "ctm_p2p_cla_to_cla":     run_p2p_cla_to_cla();
      "ctm_p2p_ctp_to_ctp":     run_p2p_ctp_to_ctp();
      "ctm_reset_wire_or_mode": run_reset_wire_or_mode();
      "ctm_reset_p2p_mode":     run_reset_p2p_mode();
      "ctm_reset_all_modes":    run_reset_all_modes();
      "ctm_rand_all_scenarios":
      run_ctm_random("all_scenarios", "all", "all", .multicast(1'b1), .allow_p2p(1'b1));
      "ctm_rand_wire_or_only":
      run_ctm_random("wire_or_only", "all", "all", .multicast(1'b1), .allow_p2p(1'b0));
      "ctm_rand_p2p_only":
      run_ctm_random("p2p_only", "all", "all", .multicast(1'b0), .allow_p2p(1'b1));
      "ctm_rand_cla_to_ctp":
      run_ctm_random("cla_to_ctp", "internal", "ctp", .multicast(1'b1), .allow_p2p(1'b1));
      "ctm_rand_ctp_to_cla":
      run_ctm_random("ctp_to_cla", "ctp", "internal", .multicast(1'b1), .allow_p2p(1'b1));
      default: super.dispatch_scenario();
    endcase
  endtask

  // ------------------------------------------------------------------
  // Wire-OR route classes: one seeded route plus the two-source overlap.
  // ------------------------------------------------------------------
  // The main route: every destination fires one pulse of the route stretch
  // width (CHK-XTRIG-STRETCH `wire_or.<class>.main.port<p>.width` and
  // `.pulses`), measured on each destination through the route window.
  protected task run_wire_or_main_route(string name, int unsigned input_port,
                                        bit [31:0] output_mask);
    int unsigned dests[$];
    string sigs[$];
    int unsigned bits[$];
    int unsigned widths[], pulses[];
    port_bits(output_mask, dests);
    foreach (dests[i]) begin
      string sig;
      int unsigned bit_idx;
      request_observable(dests[i], sig, bit_idx);
      sigs.push_back(sig);
      bits.push_back(bit_idx);
    end
    widths = new[dests.size()];
    pulses = new[dests.size()];
    configure_ctp_modes_for_route_mask(32'd1 << input_port, output_mask, CtpModeWireOr);
    program_routes(32'd1 << input_port, output_mask, {"wire_or.", name, ".main"});
    fork
      begin
        foreach (dests[i]) begin
          automatic int unsigned k = i;
          fork
            measure_mask_width(.name(sigs[k]), .mask(32'd1 << bits[k]), .width(widths[k]),
                               .pulses(pulses[k]));
          join_none
        end
        wait fork;
      end
      run_route_window(32'd1 << input_port, output_mask, CtpModeWireOr, {"wire_or.", name, ".main"
                       });
    join
    foreach (dests[i]) begin
      string ctx = $sformatf("output=%0d source=%0d", dests[i], input_port);
      check_evidence(ChkStretch, $sformatf("wire_or.%s.main.port%0d.width", name, dests[i]),
                     64'(widths[i]), 64'(RouteStretchMult) + 64'd1, ctx);
      check_evidence(ChkStretch, $sformatf("wire_or.%s.main.port%0d.pulses", name, dests[i]),
                     64'(pulses[i]), 64'd1, ctx);
    end
  endtask

  protected task run_wire_or_route_class(string name, int unsigned input_port,
                                         bit [31:0] output_mask, int unsigned overlap_input,
                                         int unsigned overlap_output);
    bit [31:0] both = (32'd1 << input_port) | (32'd1 << overlap_input);
    string sig;
    int unsigned bit_idx, width, pulses;
    `uvm_info(get_type_name(), {"CTM wire-OR routing ", name}, UVM_LOW)
    run_wire_or_main_route(name, input_port, output_mask);
    // Two sources selected into one destination: each source alone reaches
    // it, and both pulsed in the same cycle merge into one pulse of the
    // single-source width.
    clear_ctm_routes();
    configure_ctp_modes_for_route_mask(both, 32'd1 << overlap_output, CtpModeWireOr);
    program_ctm_src(overlap_output, both);
    run_route_window(32'd1 << overlap_input, 32'd1 << overlap_output, CtpModeWireOr, {
                     "wire_or.", name, ".overlap_second"});
    run_route_window(32'd1 << input_port, 32'd1 << overlap_output, CtpModeWireOr, {
                     "wire_or.", name, ".overlap_first"});
    request_observable(overlap_output, sig, bit_idx);
    fork
      measure_mask_width(.name(sig), .mask(32'd1 << bit_idx), .width(width), .pulses(pulses));
      run_route_window(both, 32'd1 << overlap_output, CtpModeWireOr, {
                       "wire_or.", name, ".overlap_merged"});
    join
    check_evidence(ChkStretch, {"wire_or.", name, ".merged_width"}, 64'(width),
                   64'(RouteStretchMult) + 64'd1, $sformatf(
                   "output=%0d sources=0x%0h", overlap_output, both));
    check_evidence(ChkStretch, {"wire_or.", name, ".merged_pulses"}, 64'(pulses), 64'd1, $sformatf(
                   "output=%0d sources=0x%0h", overlap_output, both));
  endtask

  protected task run_wire_or_cla_to_ctp();
    int unsigned ints[$], outs[$];
    pick_distinct(XtrigNumIntCt, 2, ints);
    pick_distinct(XtrigNumCtp, 3, outs);
    run_wire_or_route_class("cla_to_ctp", internal_ct_port(ints[0]), ports_mask(outs),
                            internal_ct_port(ints[1]), external_ctp_port(pick_one(outs)));
  endtask

  protected task run_wire_or_ctp_to_cla();
    int unsigned ctps[$], out_ints[$], outs[$];
    pick_distinct(XtrigNumCtp, 2, ctps);
    pick_distinct(XtrigNumIntCt, 3, out_ints);
    foreach (out_ints[i]) outs.push_back(internal_ct_port(out_ints[i]));
    run_wire_or_route_class("ctp_to_cla", external_ctp_port(ctps[0]), ports_mask(outs),
                            external_ctp_port(ctps[1]), pick_one(outs));
  endtask

  protected task run_wire_or_cla_to_cla();
    int unsigned picks[$], outs[$];
    pick_distinct(XtrigNumIntCt, 5, picks);
    for (int unsigned k = 2; k < 5; k++) outs.push_back(internal_ct_port(picks[k]));
    run_wire_or_route_class("cla_to_cla", internal_ct_port(picks[0]), ports_mask(outs),
                            internal_ct_port(picks[1]), pick_one(outs));
  endtask

  protected task run_wire_or_ctp_to_ctp();
    int unsigned picks[$], outs[$];
    pick_distinct(XtrigNumCtp, 5, picks);
    for (int unsigned k = 2; k < 5; k++) outs.push_back(picks[k]);
    run_wire_or_route_class("ctp_to_ctp", external_ctp_port(picks[0]), ports_mask(outs),
                            external_ctp_port(picks[1]), external_ctp_port(pick_one(outs)));
  endtask

  // ------------------------------------------------------------------
  // P2P route classes: three seeded source/destination pairs each.
  // ------------------------------------------------------------------
  protected task run_p2p_route_class(string name, int unsigned inputs[$], int unsigned outputs[$]);
    `uvm_info(get_type_name(), {"CTM point-to-point routing ", name}, UVM_LOW)
    foreach (inputs[idx]) begin
      log_iteration(idx + 1, inputs.size(), $sformatf(
                    "%s input=%0d output=%0d", name, inputs[idx], outputs[idx]));
      verify_route(inputs[idx], 32'd1 << outputs[idx], CtpModeP2p, $sformatf(
                   "p2p.%s.%0d", name, idx + 1));
    end
  endtask

  protected task run_p2p_cla_to_ctp();
    int unsigned ints[$], ctps[$], inputs[$], outputs[$];
    pick_distinct(XtrigNumIntCt, 3, ints);
    pick_distinct(XtrigNumCtp, 3, ctps);
    foreach (ints[i]) begin
      inputs.push_back(internal_ct_port(ints[i]));
      outputs.push_back(external_ctp_port(ctps[i]));
    end
    run_p2p_route_class("cla_to_ctp", inputs, outputs);
  endtask

  protected task run_p2p_ctp_to_cla();
    int unsigned ints[$], ctps[$], inputs[$], outputs[$];
    pick_distinct(XtrigNumCtp, 3, ctps);
    pick_distinct(XtrigNumIntCt, 3, ints);
    foreach (ctps[i]) begin
      inputs.push_back(external_ctp_port(ctps[i]));
      outputs.push_back(internal_ct_port(ints[i]));
    end
    run_p2p_route_class("ctp_to_cla", inputs, outputs);
  endtask

  protected task run_p2p_cla_to_cla();
    int unsigned picks[$], inputs[$], outputs[$];
    pick_distinct(XtrigNumIntCt, 6, picks);
    for (int unsigned k = 0; k < 3; k++) begin
      inputs.push_back(internal_ct_port(picks[k]));
      outputs.push_back(internal_ct_port(picks[k+3]));
    end
    run_p2p_route_class("cla_to_cla", inputs, outputs);
  endtask

  protected task run_p2p_ctp_to_ctp();
    int unsigned picks[$], inputs[$], outputs[$];
    pick_distinct(XtrigNumCtp, 6, picks);
    for (int unsigned k = 0; k < 3; k++) begin
      inputs.push_back(external_ctp_port(picks[k]));
      outputs.push_back(external_ctp_port(picks[k+3]));
    end
    run_p2p_route_class("ctp_to_ctp", inputs, outputs);
  endtask

  // ------------------------------------------------------------------
  // Reset scenarios: routes established and traffic active, the reset
  // window, defaults, fresh routes recover.
  // ------------------------------------------------------------------
  protected task run_reset_wire_or_mode();
    int unsigned ints[$], ctps[$], active_ports[$], post_ports[$];
    bit [31:0] active, pre_outputs;
    int unsigned post_count = $urandom_range(3, 2);
    int unsigned inverted;
    `uvm_info(get_type_name(), "CTM reset in wire-OR mode", UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 3, ints);
    pick_distinct(XtrigNumCtp, 5, ctps);
    inverted = $urandom_range(1);
    active_ports = {ctps[0], ctps[1]};
    active = ports_mask(active_ports);
    pre_outputs = active | (32'd1 << internal_ct_port(ints[2]));
    log_step("1", $sformatf(
             "two outputs, CTP[%0d] inverted, hold a long stretched pulse when the reset lands",
             active_ports[inverted]
             ));
    foreach (active_ports[i])
      program_ctp(active_ports[i], CtpModeWireOr, bit'(i == inverted), 1'b0, ResetHoldStretch);
    program_routes(32'd1 << internal_ct_port(ints[0]), pre_outputs, "reset_wire_or.pre");
    start_live_window(wire_or_reset_signals);
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << ints[0], 1);
    wait_signal_mask("xtrig_ctp_req_out_dout_en", active, active, 60,
                     "reset_wire_or.active_before");
    wait_window_fired("xtrig_ctm_src_req", 32'd1 << ints[2], 60, "reset_wire_or.internal_active",
                      1'b1);
    // Each output drives its own wire, so each receives its own pull.
    wait_window_fired("xtrig_ctp_ct_dst", active, 60, "reset_wire_or.self_receive", 1'b1);
    check_status(ctps[0], "reset_wire_or.active_before", .busy(1));
    reset_window("ctm_reset_wire_or", wire_or_reset_signals);
    log_step("2", "routing and CTP state read their defaults, then fresh routes recover");
    check_all_ctm_cleared("reset_wire_or");
    check_ctp_defaults("reset_wire_or");
    for (int unsigned k = 2; k < 2 + post_count; k++) post_ports.push_back(ctps[k]);
    verify_route(internal_ct_port(ints[1]), ports_mask(post_ports), CtpModeWireOr,
                 "reset_wire_or.post");
  endtask

  protected task run_reset_p2p_mode();
    int unsigned ints[$], ctps[$];
    bit [31:0] mask, rx;
    `uvm_info(get_type_name(), "CTM reset in P2P mode", UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 3, ints);
    pick_distinct(XtrigNumCtp, 3, ctps);
    mask = 32'd1 << ctps[0];
    rx   = 32'd1 << ctps[1];
    log_step("1",
             "a P2P request stays pending without its acknowledge, and a second P2P port holds a received request, when the reset lands");
    configure_ctp_mode_for_port(ctps[0], CtpModeP2p);
    program_route(internal_ct_port(ints[0]), mask, "reset_p2p.pre");
    configure_ctp_mode_for_port(ctps[1], CtpModeP2p);
    program_ctm_src(internal_ct_port(ints[2]), rx);
    start_live_window(reset_signals);
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << ints[0], 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", mask, pad_level(mask, 1'b1), 60,
                     "reset_p2p.stuck_req");
    check_status(ctps[0], "reset_p2p.before", .busy(1), .req_out(1));
    drive_p2p_req_in(ctps[1], 1'b1);
    wait_signal_mask("xtrig_ctp_ack_out_dout", rx, pad_level(rx, 1'b1), 60,
                     "reset_p2p.rx_ack_held");
    wait_window_fired("xtrig_ctm_src_req", 32'd1 << ints[2], 60, "reset_p2p.rx_delivered", 1'b1);
    reset_window("ctm_reset_p2p", reset_signals);
    log_step(
        "2",
        "the handshake, routing, and CTP state read their defaults, then a fresh route completes");
    check_status(ctps[0], "reset_p2p.after", .busy(0), .req_out(0));
    check_all_ctm_cleared("reset_p2p");
    check_ctp_defaults("reset_p2p");
    verify_route(internal_ct_port(ints[1]), 32'd1 << external_ctp_port(ctps[2]), CtpModeP2p,
                 "reset_p2p.post");
  endtask

  protected task run_reset_all_modes();
    int unsigned ints[$], ctps[$], wire_outputs[$];
    bit [31:0] wire_in, wire_mask, p2p_in, p2p_mask, rx;
    `uvm_info(get_type_name(), "CTM reset across wire-OR and P2P modes", UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 3, ints);
    pick_distinct(XtrigNumCtp, 5, ctps);
    // Both classes programmed together and each pulsed, so the reset lands
    // on live routing state of both kinds: one wire-OR source to two CTPs
    // and one internal CT (so the internal request outputs are a live
    // observable of this test), one P2P source to a third CTP, and a fifth
    // CTP in P2P mode that receives a request.
    wire_in      = 32'd1 << internal_ct_port(ints[0]);
    wire_outputs = {external_ctp_port(ctps[0]), external_ctp_port(ctps[1]),
                    internal_ct_port(ints[2])};
    wire_mask    = ports_mask(wire_outputs);
    p2p_in       = 32'd1 << internal_ct_port(ints[1]);
    p2p_mask     = 32'd1 << external_ctp_port(ctps[2]);
    rx           = 32'd1 << external_ctp_port(ctps[4]);
    configure_ctp_modes_for_route_mask(wire_in, wire_mask, CtpModeWireOr);
    configure_ctp_modes_for_route_mask(p2p_in, p2p_mask, CtpModeP2p);
    configure_ctp_mode_for_port(external_ctp_port(ctps[4]), CtpModeP2p);
    clear_ctm_routes();
    foreach (wire_outputs[i]) program_ctm_src(wire_outputs[i], wire_in);
    program_ctm_src(external_ctp_port(ctps[2]), p2p_in);
    start_live_window(reset_signals);
    run_route_window(wire_in, wire_mask, CtpModeWireOr, "reset_all.pre_wire");
    run_route_window(p2p_in, p2p_mask, CtpModeP2p, "reset_all.pre_p2p");
    `uvm_info(
        get_type_name(),
        "A P2P request stays pending without its acknowledge, and a second P2P port holds a received request, when the reset lands",
        UVM_LOW)
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << ints[1], 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", p2p_mask, pad_level(p2p_mask, 1'b1), 60,
                     "reset_all.stuck_req");
    check_status(ctps[2], "reset_all.before", .busy(1), .req_out(1));
    drive_p2p_req_in(ctps[4], 1'b1);
    wait_signal_mask("xtrig_ctp_ack_out_dout", rx, pad_level(rx, 1'b1), 60,
                     "reset_all.rx_ack_held");
    reset_window("ctm_reset_all", reset_signals);
    check_status(ctps[2], "reset_all.after", .busy(0), .req_out(0));
    check_all_ctm_cleared("reset_all");
    check_ctp_defaults("reset_all");
    verify_route(internal_ct_port(ints[0]), 32'd1 << external_ctp_port(ctps[0]), CtpModeWireOr,
                 "reset_all.post_wire");
    verify_route(internal_ct_port(ints[1]), 32'd1 << external_ctp_port(ctps[3]), CtpModeP2p,
                 "reset_all.post_p2p");
  endtask

  protected function void refill_route_pending(string name, int unsigned source_pool[$],
                                               int unsigned dest_pool[$]);
    int unsigned routes[$];
    foreach (source_pool[i])
    foreach (dest_pool[j])
    if (source_pool[i] != dest_pool[j]) routes.push_back(source_pool[i] * 32 + dest_pool[j]);
    routes.shuffle();
    m_route_pending[name] = routes;
  endfunction

  protected function bit route_pending(string name, int unsigned src, int unsigned dst);
    int found[$] = m_route_pending[name].find_first_index(r) with (r == src * 32 + dst);
    return found.size() > 0;
  endfunction

  protected function void drop_route_pending(string name, int unsigned src, int unsigned dst);
    int found[$] = m_route_pending[name].find_first_index(r) with (r == src * 32 + dst);
    if (found.size() > 0) m_route_pending[name].delete(found[0]);
  endfunction

  // A second point-to-point route programmed alongside `input_mask ->
  // output_mask` without clearing it, each pulsed alone: a request on either
  // route reaches only its own destination while the other stays live. A
  // pending route of the mix on free ports is preferred.
  protected task run_p2p_pair_isolation(string name, bit [31:0] input_mask, bit [31:0] output_mask,
                                        int unsigned source_pool[$], int unsigned dest_pool[$],
                                        string label);
    int unsigned free_src[$], free_dst[$], candidates[$];
    int unsigned in2, out2;
    bit [31:0] used = input_mask | output_mask;
    foreach (source_pool[i]) if (!used[source_pool[i]]) free_src.push_back(source_pool[i]);
    foreach (dest_pool[i]) if (!used[dest_pool[i]]) free_dst.push_back(dest_pool[i]);
    foreach (free_src[i])
      foreach (free_dst[j])
        if ((free_src[i] != free_dst[j]) && route_pending(name, free_src[i], free_dst[j]))
          candidates.push_back(free_src[i] * 32 + free_dst[j]);
    if (candidates.size() > 0) begin
      int unsigned route = pick_one(candidates);
      in2  = route / 32;
      out2 = route % 32;
    end else begin
      if (free_src.size() == 0) return;
      in2 = pick_one(free_src);
      free_dst.delete();
      foreach (dest_pool[i])
      if (!used[dest_pool[i]] && (dest_pool[i] != in2)) free_dst.push_back(dest_pool[i]);
      if (free_dst.size() == 0) return;
      out2 = pick_one(free_dst);
    end
    drop_route_pending(name, in2, out2);
    m_route_driven[name][in2*32+out2] = 1'b1;
    `uvm_info(get_type_name(), $sformatf("%s: second P2P route input=%0d output=%0d alongside",
                                         label, in2, out2), UVM_LOW)
    configure_ctp_modes_for_route_mask(32'd1 << in2, 32'd1 << out2, CtpModeP2p);
    program_ctm_src(out2, 32'd1 << in2);
    run_route_window(32'd1 << in2, 32'd1 << out2, CtpModeP2p, {label, ".pair_second"});
    run_route_window(input_mask, output_mask, CtpModeP2p, {label, ".pair_first"});
  endtask

  // ------------------------------------------------------------------
  // Seeded random route mixes: a wire-OR iteration selects one or two
  // sources on every output; a P2P iteration adds a coexisting route. Each
  // iteration starts from the first pending route of the mix, adds a second
  // source that shares its destination and further outputs of its source
  // that are still pending, and draws its trigger timing: the pulse width
  // and the idle lead before it. A point-to-point CTP source holds its
  // request for the drawn width and until its acknowledge. The last pass of
  // the ctm_rand_cla_to_ctp and ctm_rand_ctp_to_cla mixes continues with
  // single-source iterations until every route of the mix has been driven
  // alone, and counts those routes.
  // ------------------------------------------------------------------
  protected task run_ctm_random(string name, string source_class, string dest_class, bit multicast,
                                bit allow_p2p);
    int unsigned source_pool[$], dest_pool[$];
    int unsigned walk_size = 0;
    int unsigned iterations = random_count;
    bit closes_walk = (name == "cla_to_ctp") || (name == "ctp_to_cla");
    `uvm_info(get_type_name(), {"CTM seeded random routing ", name}, UVM_LOW)
    port_pool(source_class, source_pool);
    port_pool(dest_class, dest_pool);
    foreach (source_pool[i]) foreach (dest_pool[j]) if (source_pool[i] != dest_pool[j]) walk_size++;
    if (closes_walk && total_passes == 0)
      `uvm_fatal(get_type_name(), $sformatf(
                 "ctm_rand_%s needs total_passes to find the pass that closes its walk", name))
    for (int unsigned idx = 0; idx < random_count; idx++)
      ctm_random_iteration(name, idx, random_count, source_pool, dest_pool, multicast, allow_p2p);
    if (closes_walk && loop_index == total_passes - 1) begin
      int unsigned driven = routes_driven(name);
      // Every single-source iteration retires at least its head route, so the
      // walk closes within this many iterations.
      int unsigned bound = iterations + walk_size - driven;
      while (driven < walk_size && iterations < bound) begin
        ctm_random_iteration(name, iterations, bound, source_pool, dest_pool, multicast, allow_p2p,
                             1'b1);
        iterations++;
        driven = routes_driven(name);
      end
      check_evidence(ChkRouteModel, $sformatf("rand.%s.routes_driven", name), 64'(driven),
                     64'(walk_size), $sformatf("iterations=%0d", iterations));
    end
  endtask

  // Number of routes of the mix that a single-source window has driven.
  protected function int unsigned routes_driven(string name);
    return m_route_driven.exists(name) ? m_route_driven[name].num() : 0;
  endfunction

  // One route-mix iteration from the head of the walk; a single-source
  // window retires the routes it drives.
  protected task ctm_random_iteration(string name, int unsigned idx, int unsigned total,
                                      int unsigned source_pool[$], int unsigned dest_pool[$],
                                      bit multicast, bit allow_p2p, bit single_source = 1'b0);
    int unsigned mode = (allow_p2p &&
                               (!multicast || $urandom_range(1)))
                              ? CtpModeP2p : CtpModeWireOr;
    int unsigned n_inputs = (!single_source && mode == CtpModeWireOr && $urandom_range(1)) ? 2 : 1;
    int unsigned inputs[$], selected[$];
    int unsigned head_src, head_dst;
    bit [31:0] input_mask, output_mask;
    int unsigned pulse_cycles = $urandom_range(RandPulseMaxCycles, 2);
    int unsigned lead_cycles = $urandom_range(RandLeadMaxCycles, 0);
    if (!m_route_pending.exists(name) || (m_route_pending[name].size() == 0))
      refill_route_pending(name, source_pool, dest_pool);
    head_src = m_route_pending[name][0] / 32;
    head_dst = m_route_pending[name][0] % 32;
    inputs.push_back(head_src);
    if (n_inputs == 2) begin
      int unsigned partners[$], others[$];
      foreach (source_pool[i]) begin
        if ((source_pool[i] == head_src) || (source_pool[i] == head_dst)) continue;
        others.push_back(source_pool[i]);
        if (route_pending(name, source_pool[i], head_dst)) partners.push_back(source_pool[i]);
      end
      if (partners.size() > 0) inputs.push_back(pick_one(partners));
      else if (others.size() > 0) inputs.push_back(pick_one(others));
    end
    input_mask = ports_mask(inputs);
    selected.push_back(head_dst);
    if (mode == CtpModeWireOr) begin
      int unsigned pending_dst[$], other_dst[$];
      int unsigned k;
      foreach (dest_pool[i]) begin
        if ((dest_pool[i] == head_dst) || (dest_pool[i] inside {inputs})) continue;
        if (route_pending(name, head_src, dest_pool[i])) pending_dst.push_back(dest_pool[i]);
        else other_dst.push_back(dest_pool[i]);
      end
      pending_dst.shuffle();
      other_dst.shuffle();
      foreach (other_dst[i]) pending_dst.push_back(other_dst[i]);
      // Two to four wire-OR outputs, as many as the pool allows.
      k = (pending_dst.size() + 1 > 4) ? 4 : pending_dst.size() + 1;
      k = $urandom_range(k, (k < 2) ? k : 2);
      for (int unsigned i = 0; i + 1 < k; i++) selected.push_back(pending_dst[i]);
    end
    output_mask = ports_mask(selected);
    // With two sources selected on every output a missing select bit of
    // either source goes unseen, so only a single-source window retires the
    // routes it drives.
    if (inputs.size() == 1)
      foreach (selected[j]) begin
        drop_route_pending(name, head_src, selected[j]);
        m_route_driven[name][head_src*32+selected[j]] = 1'b1;
      end
    log_iteration(idx + 1, total, $sformatf(
                  "inputs=0x%0h mode=%0d outputs=0x%0h pulse=%0d lead=%0d",
                  input_mask,
                  mode,
                  output_mask,
                  pulse_cycles,
                  lead_cycles
                  ));
    verify_route_mask(input_mask, output_mask, mode, $sformatf("rand.%s.%0d", name, idx),
                      pulse_cycles, lead_cycles);
    if (mode == CtpModeP2p)
      run_p2p_pair_isolation(name, input_mask, output_mask, source_pool, dest_pool, $sformatf(
                             "rand.%s.%0d", name, idx));
  endtask

endclass : dtp_ctm_route_test_seq
