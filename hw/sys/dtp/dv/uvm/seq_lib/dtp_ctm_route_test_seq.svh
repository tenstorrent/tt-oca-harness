// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CTM routing scenarios — the SV analogue of the CTM scenario set in the
// cocotb dtp_xtrig_base_test_seq. One parameterized sequence, dispatched on
// `scenario`:
//
//   ctm_wire_or_{cla_to_ctp, ctp_to_cla, cla_to_cla, ctp_to_ctp}
//       one seeded route of the class plus a two-source overlap onto one
//       shared destination: each source alone, then both in the same cycle
//       merging into one pulse of the single-source width
//   ctm_p2p_{cla_to_ctp, ctp_to_cla, cla_to_cla, ctp_to_ctp}
//       three seeded source/destination pairs of the class with full
//       req/ack handshakes
//   ctm_reset_{wire_or_mode, p2p_mode, all_modes}
//       routes established and traffic active (a long stretched pulse,
//       or a request awaiting its acknowledge; both classes programmed
//       together in all_modes), the reset window with every output and busy
//       flop quiet, select and CTP defaults, then fresh routes recover
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
      "ctm_rand_all_scenarios": run_ctm_random("all_scenarios", "all", "all", 1'b1, 1'b1);
      "ctm_rand_wire_or_only":  run_ctm_random("wire_or_only", "all", "all", 1'b1, 1'b0);
      "ctm_rand_p2p_only":      run_ctm_random("p2p_only", "all", "all", 1'b0, 1'b1);
      "ctm_rand_cla_to_ctp":    run_ctm_random("cla_to_ctp", "internal", "ctp", 1'b1, 1'b1);
      "ctm_rand_ctp_to_cla":    run_ctm_random("ctp_to_cla", "ctp", "internal", 1'b1, 1'b1);
      default: super.dispatch_scenario();
    endcase
  endtask

  // ------------------------------------------------------------------
  // Wire-OR route classes: one seeded route plus the two-source overlap.
  // ------------------------------------------------------------------
  protected task run_wire_or_route_class(string name, int unsigned input_port,
                                         bit [31:0] output_mask, int unsigned overlap_input,
                                         int unsigned overlap_output);
    bit [31:0] both = (32'd1 << input_port) | (32'd1 << overlap_input);
    string sig;
    int unsigned bit_idx, width;
    `uvm_info(get_type_name(), {"CTM wire-OR routing ", name}, UVM_LOW)
    verify_route(input_port, output_mask, CtpModeWireOr, {"wire_or.", name, ".main"});
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
      measure_mask_width(sig, 32'd1 << bit_idx, width);
      run_route_window(both, 32'd1 << overlap_output, CtpModeWireOr, {
                       "wire_or.", name, ".overlap_merged"});
    join
    check_evidence(ChkStretch, {"wire_or.", name, ".merged_width"}, 64'(width),
                   64'(RouteStretchMult) + 64'd1, $sformatf(
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
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: %s input=%0d output=%0d",
                idx + 1,
                inputs.size(),
                name,
                inputs[idx],
                outputs[idx]
                ), UVM_LOW)
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
    bit [31:0] active;
    int unsigned post_count = $urandom_range(3, 2);
    `uvm_info(get_type_name(), "CTM reset in wire-OR mode", UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 2, ints);
    pick_distinct(XtrigNumCtp, 5, ctps);
    active_ports = {ctps[0], ctps[1]};
    active = ports_mask(active_ports);
    `uvm_info(get_type_name(),
              "Step 1: two outputs hold a long stretched pulse when the reset lands", UVM_LOW)
    foreach (active_ports[i])
      program_ctp(active_ports[i], CtpModeWireOr, 1'b0, 1'b0, ResetHoldStretch);
    program_routes(32'd1 << internal_ct_port(ints[0]), active, "reset_wire_or.pre");
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << ints[0], 1);
    wait_signal_mask("xtrig_ctp_req_out_dout_en", active, active, 60,
                     "reset_wire_or.active_before");
    check_status(ctps[0], "reset_wire_or.active_before", .busy(1));
    reset_window("ctm_reset_wire_or");
    `uvm_info(get_type_name(),
              "Step 2: routing and CTP state read their defaults, then fresh routes recover",
              UVM_LOW)
    check_all_ctm_cleared("reset_wire_or");
    check_ctp_defaults("reset_wire_or");
    for (int unsigned k = 2; k < 2 + post_count; k++) post_ports.push_back(ctps[k]);
    verify_route(internal_ct_port(ints[1]), ports_mask(post_ports), CtpModeWireOr,
                 "reset_wire_or.post");
  endtask

  protected task run_reset_p2p_mode();
    int unsigned ints[$], ctps[$];
    bit [31:0] mask;
    `uvm_info(get_type_name(), "CTM reset in P2P mode", UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 2, ints);
    pick_distinct(XtrigNumCtp, 3, ctps);
    mask = 32'd1 << ctps[0];
    `uvm_info(get_type_name(),
              "Step 1: a P2P request stays pending without its acknowledge when the reset lands",
              UVM_LOW)
    configure_ctp_mode_for_port(ctps[0], CtpModeP2p);
    program_route(internal_ct_port(ints[0]), mask, "reset_p2p.pre");
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << ints[0], 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", mask, pad_level(mask, 1'b1), 60,
                     "reset_p2p.stuck_req");
    check_status(ctps[0], "reset_p2p.before", .busy(1), .req_out(1));
    reset_window("ctm_reset_p2p");
    `uvm_info(
        get_type_name(),
        "Step 2: the handshake, routing, and CTP state read their defaults, then a fresh route completes",
        UVM_LOW)
    check_status(ctps[0], "reset_p2p.after", .busy(0), .req_out(0));
    check_all_ctm_cleared("reset_p2p");
    check_ctp_defaults("reset_p2p");
    verify_route(internal_ct_port(ints[1]), 32'd1 << external_ctp_port(ctps[2]), CtpModeP2p,
                 "reset_p2p.post");
  endtask

  protected task run_reset_all_modes();
    int unsigned ints[$], ctps[$], wire_outputs[$];
    bit [31:0] wire_in, wire_mask, p2p_in, p2p_mask;
    `uvm_info(get_type_name(), "CTM reset across wire-OR and P2P modes", UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 3, ints);
    pick_distinct(XtrigNumCtp, 4, ctps);
    // Both classes programmed together and each pulsed, so the reset lands
    // on live routing state of both kinds: one wire-OR source to two CTPs
    // and one internal CT (so the internal request outputs are a live
    // observable of this test), and one P2P source to a third CTP.
    wire_in      = 32'd1 << internal_ct_port(ints[0]);
    wire_outputs = {external_ctp_port(ctps[0]), external_ctp_port(ctps[1]),
                    internal_ct_port(ints[2])};
    wire_mask    = ports_mask(wire_outputs);
    p2p_in       = 32'd1 << internal_ct_port(ints[1]);
    p2p_mask     = 32'd1 << external_ctp_port(ctps[2]);
    configure_ctp_modes_for_route_mask(wire_in, wire_mask, CtpModeWireOr);
    configure_ctp_modes_for_route_mask(p2p_in, p2p_mask, CtpModeP2p);
    clear_ctm_routes();
    foreach (wire_outputs[i]) program_ctm_src(wire_outputs[i], wire_in);
    program_ctm_src(external_ctp_port(ctps[2]), p2p_in);
    run_route_window(wire_in, wire_mask, CtpModeWireOr, "reset_all.pre_wire");
    run_route_window(p2p_in, p2p_mask, CtpModeP2p, "reset_all.pre_p2p");
    `uvm_info(get_type_name(),
              "Step: a P2P request stays pending without its acknowledge when the reset lands",
              UVM_LOW)
    idle_inputs();
    pulse_ctm_dst_req(32'd1 << ints[1], 2);
    wait_signal_mask("xtrig_ctp_req_out_dout", p2p_mask, pad_level(p2p_mask, 1'b1), 60,
                     "reset_all.stuck_req");
    check_status(ctps[2], "reset_all.before", .busy(1), .req_out(1));
    reset_window("ctm_reset_all");
    check_status(ctps[2], "reset_all.after", .busy(0), .req_out(0));
    check_all_ctm_cleared("reset_all");
    check_ctp_defaults("reset_all");
    verify_route(internal_ct_port(ints[0]), 32'd1 << external_ctp_port(ctps[0]), CtpModeWireOr,
                 "reset_all.post_wire");
    verify_route(internal_ct_port(ints[1]), 32'd1 << external_ctp_port(ctps[3]), CtpModeP2p,
                 "reset_all.post_p2p");
  endtask

  // A second point-to-point route programmed alongside `input_mask ->
  // output_mask` without clearing it, each pulsed alone: a request on either
  // route reaches only its own destination while the other stays live.
  protected task run_p2p_pair_isolation(bit [31:0] input_mask, bit [31:0] output_mask,
                                        int unsigned source_pool[$], int unsigned dest_pool[$],
                                        string label);
    int unsigned free_src[$], free_dst[$];
    int unsigned in2, out2;
    bit [31:0] used = input_mask | output_mask;
    foreach (source_pool[i]) if (!used[source_pool[i]]) free_src.push_back(source_pool[i]);
    if (free_src.size() == 0) return;
    in2 = pick_one(free_src);
    used[in2] = 1'b1;
    foreach (dest_pool[i]) if (!used[dest_pool[i]]) free_dst.push_back(dest_pool[i]);
    if (free_dst.size() == 0) return;
    out2 = pick_one(free_dst);
    `uvm_info(get_type_name(), $sformatf("%s: second P2P route input=%0d output=%0d alongside",
                                         label, in2, out2), UVM_LOW)
    configure_ctp_modes_for_route_mask(32'd1 << in2, 32'd1 << out2, CtpModeP2p);
    program_ctm_src(out2, 32'd1 << in2);
    run_route_window(32'd1 << in2, 32'd1 << out2, CtpModeP2p, {label, ".pair_second"});
    run_route_window(input_mask, output_mask, CtpModeP2p, {label, ".pair_first"});
  endtask

  // ------------------------------------------------------------------
  // Seeded random route mixes: a wire-OR iteration selects one or two
  // sources on every output; a P2P iteration adds a coexisting route.
  // ------------------------------------------------------------------
  protected task run_ctm_random(string name, string source_class, string dest_class, bit multicast,
                                bit allow_p2p);
    int unsigned source_pool[$], dest_pool[$];
    `uvm_info(get_type_name(), {"CTM seeded random routing ", name}, UVM_LOW)
    port_pool(source_class, source_pool);
    port_pool(dest_class, dest_pool);
    for (int unsigned idx = 0; idx < random_count; idx++) begin
      int unsigned mode = (allow_p2p &&
                                 (!multicast || $urandom_range(1)))
                                ? CtpModeP2p : CtpModeWireOr;
      int unsigned n_inputs = (mode == CtpModeWireOr && $urandom_range(1)) ? 2 : 1;
      int unsigned inputs[$], choices[$], selected[$], input_picks[$];
      bit [31:0] input_mask, output_mask;
      pick_distinct(source_pool.size(),
                    (n_inputs < source_pool.size()) ? n_inputs : source_pool.size(), input_picks);
      foreach (input_picks[i]) inputs.push_back(source_pool[input_picks[i]]);
      input_mask = ports_mask(inputs);
      foreach (dest_pool[i]) begin
        if (!(dest_pool[i] inside {inputs})) choices.push_back(dest_pool[i]);
      end
      if (choices.size() == 0) choices = dest_pool;
      if (mode == CtpModeP2p) selected.push_back(pick_one(choices));
      else begin
        int unsigned k;
        for (int unsigned i = choices.size() - 1; i > 0; i--) begin
          int unsigned j = $urandom_range(i);
          int unsigned tmp = choices[i];
          choices[i] = choices[j];
          choices[j] = tmp;
        end
        k = (choices.size() > 4) ? 4 : choices.size();
        for (int unsigned i = 0; i < k; i++) selected.push_back(choices[i]);
      end
      output_mask = ports_mask(selected);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: inputs=0x%0h mode=%0d outputs=0x%0h",
                idx + 1,
                random_count,
                input_mask,
                mode,
                output_mask
                ), UVM_LOW)
      verify_route_mask(input_mask, output_mask, mode, $sformatf("rand.%s.%0d", name, idx));
      if (mode == CtpModeP2p)
        run_p2p_pair_isolation(input_mask, output_mask, source_pool, dest_pool, $sformatf(
                               "rand.%s.%0d", name, idx));
    end
  endtask

endclass : dtp_ctm_route_test_seq
