// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CTM routing scenarios — the SV analogue of the CTM scenario set in the
// cocotb dtp_xtrig_base_test_seq. One parameterized sequence, dispatched on
// `scenario`:
//
//   ctm_wire_or_{cla_to_ctp, ctp_to_cla, cla_to_cla, ctp_to_ctp}
//       one seeded route of the class plus a two-source overlap onto one
//       shared destination (wire-OR merge proof)
//   ctm_p2p_{cla_to_ctp, ctp_to_cla, cla_to_cla, ctp_to_ctp}
//       three seeded source/destination pairs of the class with full
//       req/ack handshakes
//   ctm_reset_{wire_or_mode, p2p_mode, all_modes}
//       routes established, system reset, select defaults + quiet pins,
//       then fresh routes recover
//   ctm_rand_{all_scenarios, wire_or_only, p2p_only, cla_to_ctp, ctp_to_cla}
//       seeded random route mixes constrained to the named class
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
      "ctm_reset_wire_or_mode": run_reset_mode("wire_or", CtpModeWireOr);
      "ctm_reset_p2p_mode":     run_reset_mode("p2p", CtpModeP2p);
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
    bit [31:0] predicted;
    `uvm_info(get_type_name(), {"CTM wire-OR routing ", name}, UVM_LOW)
    verify_route(input_port, output_mask, CtpModeWireOr, {"wire_or.", name, ".main"});
    // Two sources selected into one destination: either firing input
    // must reach the shared output (wire-OR merge).
    clear_ctm_routes();
    configure_ctp_modes_for_route(input_port, output_mask | (32'd1 << overlap_output),
                                  CtpModeWireOr);
    configure_ctp_mode_for_port(overlap_input, CtpModeWireOr, 16'd1);
    program_ctm_src(overlap_output, (32'd1 << input_port) | (32'd1 << overlap_input));
    predicted = ctm_model.route((32'd1 << input_port) | (32'd1 << overlap_input));
    start_activity_window();
    drive_input_port(input_port, CtpModeWireOr);
    drive_input_port(overlap_input, CtpModeWireOr);
    check_output_mask(32'd1 << overlap_output, CtpModeWireOr, predicted, {
                      "wire_or.", name, ".overlap"});
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
  // Reset scenarios: routes established, system reset, defaults + quiet,
  // fresh routes recover.
  // ------------------------------------------------------------------
  protected task run_reset_mode(string name, int unsigned mode);
    int unsigned ints[$], ctps[$], mask_ports[$];
    bit [31:0] output_mask;
    `uvm_info(get_type_name(), {"CTM reset in ", name, " mode"}, UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 2, ints);
    pick_distinct(XtrigNumCtp, 3, ctps);
    if (mode == CtpModeWireOr) begin
      mask_ports = {ctps[0], ctps[1]};
      output_mask = ports_mask(mask_ports);
    end else output_mask = 32'd1 << external_ctp_port(ctps[0]);
    verify_route(internal_ct_port(ints[0]), output_mask, mode, $sformatf("reset_%s.pre", name));
    pulse_reset(3);
    check_all_ctm_cleared($sformatf("reset_%s", name));
    check_quiet($sformatf("reset_%s", name));
    verify_route(internal_ct_port(ints[1]), 32'd1 << external_ctp_port(ctps[2]), mode, $sformatf(
                 "reset_%s.post", name));
  endtask

  protected task run_reset_all_modes();
    int unsigned ints[$], ctps[$], pre_ports[$];
    `uvm_info(get_type_name(), "CTM reset across wire-OR and P2P modes", UVM_LOW)
    // Seeded per-pass ports: each loop resets and recovers different
    // routes.
    pick_distinct(XtrigNumIntCt, 2, ints);
    pick_distinct(XtrigNumCtp, 4, ctps);
    pre_ports = {ctps[0], ctps[1]};
    verify_route(internal_ct_port(ints[0]), ports_mask(pre_ports), CtpModeWireOr,
                 "reset_all.pre_wire");
    verify_route(internal_ct_port(ints[1]), 32'd1 << external_ctp_port(ctps[2]), CtpModeP2p,
                 "reset_all.pre_p2p");
    pulse_reset(3);
    check_all_ctm_cleared("reset_all");
    check_quiet("reset_all");
    verify_route(internal_ct_port(ints[0]), 32'd1 << external_ctp_port(ctps[0]), CtpModeWireOr,
                 "reset_all.post_wire");
    verify_route(internal_ct_port(ints[1]), 32'd1 << external_ctp_port(ctps[3]), CtpModeP2p,
                 "reset_all.post_p2p");
  endtask

  // ------------------------------------------------------------------
  // Seeded random route mixes.
  // ------------------------------------------------------------------
  protected task run_ctm_random(string name, string source_class, string dest_class, bit multicast,
                                bit allow_p2p);
    int unsigned source_pool[$], dest_pool[$];
    `uvm_info(get_type_name(), {"CTM seeded random routing ", name}, UVM_LOW)
    port_pool(source_class, source_pool);
    port_pool(dest_class, dest_pool);
    for (int unsigned idx = 0; idx < random_count; idx++) begin
      int unsigned input_port = pick_one(source_pool);
      int unsigned mode = (allow_p2p &&
                                 (!multicast || $urandom_range(1)))
                                ? CtpModeP2p : CtpModeWireOr;
      int unsigned choices[$], selected[$];
      bit [31:0] output_mask;
      foreach (dest_pool[i]) begin
        if (dest_pool[i] != input_port) choices.push_back(dest_pool[i]);
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
                "Iteration %0d/%0d: input=%0d mode=%0d outputs=0x%0h",
                idx + 1,
                random_count,
                input_port,
                mode,
                output_mask
                ), UVM_LOW)
      verify_route(input_port, output_mask, mode, $sformatf("rand.%s.%0d", name, idx));
    end
  endtask

endclass : dtp_ctm_route_test_seq
