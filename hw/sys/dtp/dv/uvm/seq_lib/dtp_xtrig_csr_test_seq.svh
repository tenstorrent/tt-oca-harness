// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// XTRIG CSR and AXI-Lite channel-shape scenarios — the SV analogue of the
// CSR/AXI scenario set in the cocotb dtp_xtrig_base_test_seq. One
// parameterized sequence, dispatched on `scenario`:
//
//   reg_stall        accepted-path CSR writes/reads with quiet cross-trigger
//                    pins and advancing request-activity counters (the local
//                    regblock stall path is structurally unreachable), then
//                    two control routes that move every quiet observable
//   ctp_csr_sweep    full-word CTP config and stretch patterns (all-ones and
//                    inverted patterns drive the reserved bits, which read
//                    back 0), every byte strobe over a nonzero base, a
//                    STATUS write, and a preloaded neighbour that keeps its
//                    words, on every CTP, then one routed stretched pulse
//   ctm_csr_sweep    full-word CT_DST_SELECT patterns and every byte strobe
//                    on every CTM source register, then two swept selects
//                    routing a selected input and ignoring an unselected one
//   ctm_all_source_select  per-source select masks with neighbor
//                    no-aliasing reads
//   axi_channel_skew                       AW-first and W-first skewed
//                    writes, each read back, deferred BREADY, and an
//                    RREADY-hold read with data-stability evidence
//   axi_channel_skew_demux_aw_lock_release two-outstanding skewed writes
//                    judged against the crossbar demux state mirrors and
//                    the bench AW stall and open-write counters, with
//                    response order proven by distinguishable response codes
//   axi_channel_skew_read_decode_backpressure two-outstanding unmapped
//                    reads under an RREADY hold: the second AR waits behind
//                    the open first read (bench open-read counters), both
//                    return DECERR from the crossbar error subordinate

class dtp_xtrig_csr_test_seq extends dtp_xtrig_base_test_seq;
  `uvm_object_utils(dtp_xtrig_csr_test_seq)

  function new(string name = "dtp_xtrig_csr_test_seq");
    super.new(name);
  endfunction

  virtual task dispatch_scenario();
    case (scenario)
      "reg_stall":         run_reg_stall();
      "ctp_csr_sweep":     run_ctp_csr_sweep();
      "ctm_csr_sweep":     run_ctm_csr_sweep();
      "ctm_all_source_select": run_ctm_all_source_select();
      "axi_channel_skew":  run_axi_channel_skew();
      "axi_channel_skew_demux_aw_lock_release":
                run_demux_aw_lock_release();
      "axi_channel_skew_read_decode_backpressure":
                run_read_decode_backpressure();
      default: super.dispatch_scenario();
    endcase
  endtask

  // Accepted-path CSR accesses under an activity window: no internal-lane
  // request, CTP request or acknowledge enable, or CTP busy flop moves while
  // an access is in flight, the crossbar's READY-low stall counters do not
  // advance while its AWVALID and ARVALID counters do, and two routes
  // afterwards, one wire-OR and one point-to-point, are the positive control
  // that moves each of those observables. The pad levels and the receive
  // pulses stay out of the window because they follow the polarity CSR the
  // accesses write.
  protected task run_reg_stall();
    bit [15:0] stretch = 16'($urandom);
    bit [31:0] select = $urandom_range(CtmSelectMask, 1);
    bit [31:0] aw_stall0 = xtrig_pin("xtrig_axil_aw_stall_count");
    bit [31:0] ar_stall0 = xtrig_pin("xtrig_axil_ar_stall_count");
    bit [31:0] awvalid0 = xtrig_pin("xtrig_axil_awvalid_count");
    bit [31:0] arvalid0 = xtrig_pin("xtrig_axil_arvalid_count");
    int unsigned ints[$], ctps[$];
    bit [31:0] control_outputs;
    `uvm_info(get_type_name(), "XTRIG accepted-path CSR access and stall rationale", UVM_LOW)
    require_pulse_mode_lanes("run_reg_stall");
    // Seeded per-pass control ports.
    pick_distinct(XtrigNumIntCt, 3, ints);
    pick_distinct(XtrigNumCtp, 2, ctps);
    idle_inputs();
    start_activity_window_on(in_flight_signals);
    write_read_check(ctp_config_addr(0), pack_ctp_config(.invert(1'b1)), pack_ctp_config(
                     .invert(1'b1)), 4'hF, CtpConfigMask, "regstall.ctp0.config");
    write_read_check(ctp_stretch_addr(0), 32'(stretch), 32'(stretch), 4'hF, CtpStretchMask,
                     "regstall.ctp0.stretch");
    write_read_check(ctm_config_addr(0), select, select, 4'hF, CtmSelectMask, "regstall.ctm0");
    wait_sys_cycles(2);
    stop_activity_window();
    foreach (in_flight_signals[i])
      check_evidence(ChkQuiet, $sformatf("regstall.in_flight.%s", in_flight_signals[i]),
                     64'(window_activity[in_flight_signals[i]]), 64'd0, $sformatf(
                     "cycles=%0d", window_cycles));
    check_quiet("reg_stall_accepted");
    check_evidence(ChkAxil, "regstall.aw_stall_count_delta", 64'(xtrig_pin(
                   "xtrig_axil_aw_stall_count") - aw_stall0), 64'd0);
    check_evidence(ChkAxil, "regstall.awvalid_count_advanced", 64'(xtrig_pin(
                   "xtrig_axil_awvalid_count") - awvalid0 > 0), 64'd1);
    check_evidence(ChkAxil, "regstall.ar_stall_count_delta", 64'(xtrig_pin(
                   "xtrig_axil_ar_stall_count") - ar_stall0), 64'd0);
    check_evidence(ChkAxil, "regstall.arvalid_count_advanced", 64'(xtrig_pin(
                   "xtrig_axil_arvalid_count") - arvalid0 > 0), 64'd1);
    // Positive control: a wire-OR route to a CTP and an internal CT and a
    // point-to-point route to a second CTP move every observable the quiet
    // records judged.
    clear_xtrig();
    control_outputs = (32'd1 << external_ctp_port(ctps[0])) | (32'd1 << internal_ct_port(ints[1]));
    start_live_window(in_flight_signals);
    verify_route_mask(32'd1 << internal_ct_port(ints[0]), control_outputs, CtpModeWireOr,
                      "regstall.control.wire_or");
    verify_route(internal_ct_port(ints[2]), 32'd1 << external_ctp_port(ctps[1]), CtpModeP2p,
                 "regstall.control.p2p");
    stop_live_window();
    foreach (in_flight_signals[i])
      check_evidence(ChkSignal, $sformatf("regstall.control.%s.live", in_flight_signals[i]),
                     64'(m_live_activity[in_flight_signals[i]] != 0), 64'd1);
    clear_xtrig();
  endtask

  protected task run_ctp_csr_sweep();
    bit [31:0] base[4];
    bit [31:0] config_patterns[$];
    bit [31:0] stretch_patterns[$];
    bit [31:0] nbr_config, nbr_stretch, observed;
    int unsigned neighbor;
    string nbr_ctx;
    `uvm_info(get_type_name(), "XTRIG CTP deterministic CSR and byte-strobe sweep", UVM_LOW)
    base[0] = pack_ctp_config(CtpModeWireOr);
    base[1] = pack_ctp_config(CtpModeWireOr, 1'b1);
    base[2] = pack_ctp_config(CtpModeP2p);
    base[3] = pack_ctp_config(CtpModeP2p, 1'b1, 1'b1);
    // Seeded per-pass order and an extra random stretch value: the sweep
    // stays exhaustive while each loop exercises different write orders.
    for (int unsigned i = 3; i > 0; i--) begin
      int unsigned j = $urandom_range(i);
      bit [31:0] tmp = base[i];
      base[i] = base[j];
      base[j] = tmp;
    end
    // Reserved bits are driven to 1 by the all-ones and inverted patterns
    // and must read back 0 (full-word compare).
    foreach (base[i]) config_patterns.push_back(base[i]);
    config_patterns.push_back(FullWord);
    foreach (base[i]) config_patterns.push_back(~base[i]);
    stretch_patterns = {32'h0, 32'h1, 32'h55AA, 32'hFFFF, 32'(16'($urandom)), FullWord, ~32'h55AA};
    for (int unsigned ctp_idx = 0; ctp_idx < XtrigNumCtp; ctp_idx++) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: CTP[%0d] CSR sweep", ctp_idx + 1, XtrigNumCtp, ctp_idx),
                UVM_LOW)
      // The neighbour holds seeded nonzero words the sweep does not end on,
      // so a write that also lands in the neighbour leaves another value
      // there.
      neighbor = (ctp_idx + 1) % XtrigNumCtp;
      nbr_ctx = $sformatf("ctp=%0d", neighbor);
      nbr_config = sweep_config_word();
      nbr_stretch = 32'($urandom_range(16'hFFFF, 1));
      write_read_check(ctp_config_addr(neighbor), nbr_config, nbr_config, 4'hF, CtpConfigMask,
                       $sformatf("ctp%0d.neighbor_preload.config", ctp_idx));
      write_read_check(ctp_stretch_addr(neighbor), nbr_stretch, nbr_stretch, 4'hF, CtpStretchMask,
                       $sformatf("ctp%0d.neighbor_preload.stretch", ctp_idx));
      sweep_ctp_words(ctp_idx, config_patterns, stretch_patterns, sweep_config_word(nbr_config),
                      nbr_stretch ^ 32'($urandom_range(16'hFFFF, 1)));
      csr_read(ctp_config_addr(neighbor), observed, $sformatf(
               "ctp%0d.neighbor_after.config", ctp_idx));
      check_evidence(ChkCsr, $sformatf("ctp%0d.neighbor_no_alias.config", ctp_idx),
                     64'(observed & CtpConfigMask), 64'(nbr_config), nbr_ctx);
      csr_read(ctp_stretch_addr(neighbor), observed, $sformatf(
               "ctp%0d.neighbor_after.stretch", ctp_idx));
      check_evidence(ChkCsr, $sformatf("ctp%0d.neighbor_no_alias.stretch", ctp_idx),
                     64'(observed & CtpStretchMask), 64'(nbr_stretch), nbr_ctx);
    end
    `uvm_info(get_type_name(),
              "Step route: one programmed CTP routes a stretched pulse after the sweep", UVM_LOW)
    clear_xtrig();
    verify_wire_or_pulse($urandom_range(XtrigNumCtp - 1), $urandom_range(XtrigNumIntCt - 1),
                         16'($urandom_range(14, 1)), 1'b0, "ctp_csr_sweep.route");
    clear_xtrig();
  endtask

  // One seeded nonzero CONFIG word other than `exclude`, for the CTP CSR
  // sweep's byte-strobe bases, neighbour words, and final words. MODE|INVERT
  // is left out: the sweep leaves the bench pads at their non-inverted idle
  // levels, which an inverted point-to-point receiver reads as a request.
  protected function bit [31:0] sweep_config_word(bit [31:0] exclude = FullWord);
    bit [31:0] words[$] = '{
        pack_ctp_config(CtpModeP2p),
        pack_ctp_config(CtpModeWireOr, 1'b1),
        pack_ctp_config(CtpModeWireOr, 1'b0, 1'b1),
        pack_ctp_config(CtpModeP2p, 1'b0, 1'b1),
        pack_ctp_config(CtpModeWireOr, 1'b1, 1'b1)
    };
    bit [31:0] pool[$];
    foreach (words[i]) if (words[i] != exclude) pool.push_back(words[i]);
    return pool[$urandom_range(pool.size()-1)];
  endfunction

  // Full-word patterns, every byte strobe, a STATUS write, then the final
  // words, on one CTP.
  protected task sweep_ctp_words(int unsigned ctp_idx, bit [31:0] config_patterns[$],
                                 bit [31:0] stretch_patterns[$], bit [31:0] final_config,
                                 bit [31:0] final_stretch);
    bit [63:0] config_addr = ctp_config_addr(ctp_idx);
    bit [63:0] stretch_addr = ctp_stretch_addr(ctp_idx);
    bit [3:0] strobes[4] = '{4'h1, 4'h2, 4'h4, 4'h8};
    bit [31:0] old_cfg, new_cfg, old_stretch, new_stretch, status_before;
    foreach (config_patterns[pat_idx])
      write_read_check(config_addr, config_patterns[pat_idx],
                       config_patterns[pat_idx] & CtpConfigMask, 4'hF, FullWord, $sformatf(
                       "ctp%0d.cfg%0d", ctp_idx, pat_idx));
    foreach (stretch_patterns[pat_idx])
      write_read_check(stretch_addr, stretch_patterns[pat_idx],
                       stretch_patterns[pat_idx] & CtpStretchMask, 4'hF, FullWord, $sformatf(
                       "ctp%0d.stretch%0d", ctp_idx, pat_idx));
    // Byte strobes over a nonzero base: only the strobed lanes change, and a
    // strobed reserved lane changes nothing.
    foreach (strobes[s]) begin
      old_cfg = sweep_config_word();
      new_cfg = $urandom();
      csr_write(config_addr, old_cfg, 4'hF, $sformatf("ctp%0d.byte_base", ctp_idx));
      write_read_check(config_addr, new_cfg, apply_wstrb(old_cfg, new_cfg, strobes[s]
                       ) & CtpConfigMask, strobes[s], FullWord, $sformatf(
                       "ctp%0d.cfg_wstrb%0h", ctp_idx, strobes[s]));
      old_stretch = 32'($urandom_range(16'hFFFF, 1));
      new_stretch = $urandom();
      csr_write(stretch_addr, old_stretch, 4'hF, $sformatf("ctp%0d.stretch_base", ctp_idx));
      write_read_check(stretch_addr, new_stretch, apply_wstrb(old_stretch, new_stretch, strobes[s]
                       ) & CtpStretchMask, strobes[s], FullWord, $sformatf(
                       "ctp%0d.stretch_wstrb%0h", ctp_idx, strobes[s]));
    end
    csr_read(ctp_status_addr(ctp_idx), status_before, $sformatf("ctp%0d.status", ctp_idx));
    write_read_check(ctp_status_addr(ctp_idx), FullWord, status_before, 4'hF, FullWord, $sformatf(
                     "ctp%0d.status_ro", ctp_idx));
    write_read_check(config_addr, final_config, final_config, 4'hF, CtpConfigMask, $sformatf(
                     "ctp%0d.cfg_final", ctp_idx));
    write_read_check(stretch_addr, final_stretch, final_stretch, 4'hF, CtpStretchMask, $sformatf(
                     "ctp%0d.stretch_final", ctp_idx));
  endtask

  protected task run_ctm_csr_sweep();
    bit [31:0] patterns[$];
    bit [31:0] random_mask = $urandom_range(CtmSelectMask, 1);
    bit [3:0] strobes[4] = '{4'h1, 4'h2, 4'h4, 4'h8};
    bit [31:0] old_mask, new_mask;
    int unsigned outputs[$];
    `uvm_info(get_type_name(), "CTM deterministic CSR byte-strobe and mask sweep", UVM_LOW)
    // Seeded per-pass extra pattern and byte-strobe payloads on top of the
    // deterministic sweep. Reserved bits [31:26] are driven to 1 by the
    // all-ones and inverted patterns and must read back 0.
    patterns = {
      32'h0,
      32'h1,
      32'd1 << external_ctp_port(0),
      32'd1 << internal_ct_port(0),
      CtmSelectMask,
      32'h0155_AA55 & CtmSelectMask,
      random_mask,
      FullWord,
      ~32'h0155_AA55,
      ~random_mask
    };
    for (int unsigned src_idx = 0; src_idx < XtrigNumCtmPorts; src_idx++) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: CT_SRC[%0d] CSR sweep", src_idx + 1, XtrigNumCtmPorts, src_idx),
                UVM_LOW)
      foreach (patterns[pat_idx])
      write_read_check(ctm_config_addr(src_idx), patterns[pat_idx],
                       patterns[pat_idx] & CtmSelectMask, 4'hF, FullWord, $sformatf(
                       "ctm%0d.pat%0d", src_idx, pat_idx));
      foreach (strobes[s]) begin
        old_mask = $urandom() & CtmSelectMask;
        new_mask = $urandom();
        program_ctm_src(src_idx, old_mask);
        write_read_check(ctm_config_addr(src_idx), new_mask, apply_wstrb(
                         old_mask, new_mask, strobes[s]) & CtmSelectMask, strobes[s], FullWord,
                         $sformatf("ctm%0d.wstrb%0h", src_idx, strobes[s]));
      end
    end
    `uvm_info(
        get_type_name(),
        "Step route: two swept output registers route a selected input and ignore an unselected one",
        UVM_LOW)
    pick_distinct(XtrigNumCtmPorts, 2, outputs);
    foreach (outputs[k])
      verify_swept_select(outputs[k], random_mask, $sformatf("ctm_csr_sweep.route%0d", k));
    clear_ctm_routes();
  endtask

  // One output holding a multi-bit select fires for a selected input and
  // stays quiet for an unselected one.
  protected task verify_swept_select(int unsigned output_port, bit [31:0] select, string label);
    int unsigned selected[$], unselected[$];
    int unsigned input_in, input_out;
    select &= CtmSelectMask & ~(32'd1 << output_port);
    port_bits(select, selected);
    port_bits(CtmSelectMask & ~select & ~(32'd1 << output_port), unselected);
    input_in = pick_one(selected);
    configure_ctp_modes_for_route_mask(32'd1 << input_in, 32'd1 << output_port, CtpModeWireOr);
    clear_ctm_routes();
    program_ctm_src(output_port, select);
    run_route_window(32'd1 << input_in, 32'd1 << output_port, CtpModeWireOr, {label, ".selected"});
    if (unselected.size() > 0) begin
      input_out = pick_one(unselected);
      configure_ctp_modes_for_route_mask(32'd1 << input_out, '0, CtpModeWireOr);
      run_route_window(32'd1 << input_out, '0, CtpModeWireOr, {label, ".unselected"});
    end
  endtask

  protected task run_ctm_all_source_select();
    bit [31:0] masks[4];
    bit [31:0] before_neighbor, after_neighbor;
    bit [63:0] neighbor;
    int unsigned nbr_idx;
    `uvm_info(get_type_name(), "CTM all-source select coverage", UVM_LOW)
    // Seeded per-pass extra mask on top of the deterministic
    // per-source set.
    for (int unsigned src_idx = 0; src_idx < XtrigNumCtmPorts; src_idx++) begin
      nbr_idx = (src_idx + 1) % XtrigNumCtmPorts;
      masks[0] = 32'd1 << (src_idx % XtrigNumCtmPorts);
      masks[1] = (32'd1 << src_idx) | (32'd1 << nbr_idx);
      masks[2] = (~(32'd1 << src_idx)) & CtmSelectMask;
      masks[3] = $urandom_range(CtmSelectMask, 1);
      neighbor = ctm_config_addr(nbr_idx);
      csr_read(neighbor, before_neighbor, $sformatf("allsrc%0d.neighbor_before", src_idx));
      foreach (masks[mask_idx])
      write_read_check(ctm_config_addr(src_idx), masks[mask_idx], masks[mask_idx], 4'hF,
                       CtmSelectMask, $sformatf("allsrc%0d.mask%0d", src_idx, mask_idx));
      csr_read(neighbor, after_neighbor, $sformatf("allsrc%0d.neighbor_after", src_idx));
      check_evidence(ChkCsr, $sformatf("allsrc%0d.neighbor_no_alias", src_idx),
                     64'(after_neighbor & CtmSelectMask), 64'(before_neighbor & CtmSelectMask),
                     $sformatf("ct_src=%0d", nbr_idx));
      // One routed pulse per source: its select decodes into the matrix.
      verify_route(src_idx, 32'd1 << nbr_idx, CtpModeWireOr, $sformatf("allsrc%0d.route", src_idx));
    end
  endtask

  protected task run_axi_channel_skew();
    bit [63:0] addr = ctp_stretch_addr($urandom_range(XtrigNumCtp - 1));
    bit [15:0] d1, d2, d3;
    bit [31:0] observed, prior, w_stall_before, w_stall_delta;
    int unsigned aw_delay;
    ocah_axi_item res;
    `uvm_info(get_type_name(), "XTRIG manual AXI-Lite AW/W and RREADY skew", UVM_LOW)
    // Seeded per-pass payloads and skew timing: each loop exercises the
    // channel-skew paths with different data, gaps, and READY delays. Each
    // write replaces a different value, so a dropped write reads back the
    // one before it.
    csr_read(addr, prior, "axi_skew.prior");
    d1 = prior[15:0] ^ 16'($urandom_range(16'hFFFF, 1));
    d2 = d1 ^ 16'($urandom_range(16'hFFFF, 1));
    d3 = d2 ^ 16'($urandom_range(16'hFFFF, 1));
    write_skewed_result(addr, 64'(d1), res, .w_valid_delay($urandom_range(7, 3)),
                        .b_ready_delay($urandom_range(4, 1)));
    check_evidence(ChkAxil, "axi_skew.aw_before_w.bresp", 64'(res.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    csr_read(addr, observed, "axi_skew.aw_before_w.readback");
    check_evidence(ChkAxil, "axi_skew.aw_before_w.stretch", 64'(observed & CtpStretchMask),
                   64'(d1));
    write_read_check(addr, 32'(d2), 32'(d2), 4'hF, CtpStretchMask, "axi_skew.normal_after_aw");
    w_stall_before = xtrig_pin("xtrig_axil_w_stall_count");
    aw_delay = $urandom_range(7, 3);
    write_skewed_result(addr, 64'(d3), res, .aw_valid_delay(aw_delay),
                        .b_ready_delay($urandom_range(4, 1)));
    w_stall_delta = xtrig_pin("xtrig_axil_w_stall_count") - w_stall_before;
    check_evidence(ChkAxil, "axi_skew.w_before_aw.bresp", 64'(res.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    // The W beat waits with WREADY low until its AW arrives, so it stalls at
    // least for the cycles the AW is held back, and the port's W stability
    // rules see the stall.
    check_evidence(ChkAxil, "axi_skew.w_before_aw.w_ready_low_seen", 64'(w_stall_delta >= aw_delay),
                   64'd1, $sformatf("w_stall_cycles=%0d aw_delay=%0d", w_stall_delta, aw_delay));
    csr_read(addr, observed, "axi_skew.final_read");
    check_evidence(ChkAxil, "axi_skew.final_stretch", 64'(observed & CtpStretchMask), 64'(d3));
    read_hold_result(addr, $urandom_range(7, 3), res);
    check_evidence(ChkAxil, "axi_skew.rresp", 64'(res.worst_resp()), 64'(OCAH_AXI_RESP_OKAY));
    check_evidence(ChkAxil, "axi_skew.rstable", 64'(res.hold_stable), 64'd1);
    check_evidence(ChkAxil, "axi_skew.rdata", 64'(res.first_data() & CtpStretchMask), 64'(d3));
  endtask

  protected task run_demux_aw_lock_release();
    int unsigned picks[$];
    bit [31:0] data_a, data_b, observed, select;
    int unsigned select_port;
    bit [63:0] unmapped;
    ocah_axi_item first, second;
    `uvm_info(get_type_name(), "XTRIG AXI-Lite demux AW-lock release", UVM_LOW)
    // Seeded per-pass targets, payloads, and skew timing.
    pick_distinct(XtrigNumCtp, 2, picks);
    data_a = pack_ctp_config($urandom_range(1), bit'($urandom_range(1)));
    data_b = pack_ctp_config($urandom_range(1), bit'($urandom_range(1)));
    `uvm_info(get_type_name(),
              "Step 1: AW-first pair to two CTP ports: the second AW waits behind the pending W",
              UVM_LOW)
    run_write_pair(ctp_config_addr(picks[0]), data_a, ctp_config_addr(picks[1]), data_b, first,
                   second, .w_valid_delay($urandom_range(8, 4)),
                   .b_ready_delay($urandom_range(4, 1)), .label("demux_aw_lock.ctp_pair"));
    csr_read(ctp_config_addr(picks[0]), observed, "demux_aw_lock.ctp_a.readback");
    check_evidence(ChkAxil, "demux_aw_lock.ctp_a.readback", 64'(observed & CtpConfigMask),
                   64'(data_a & CtpConfigMask));
    csr_read(ctp_config_addr(picks[1]), observed, "demux_aw_lock.ctp_b.readback");
    check_evidence(ChkAxil, "demux_aw_lock.ctp_b.readback", 64'(observed & CtpConfigMask),
                   64'(data_b & CtpConfigMask));
    `uvm_info(get_type_name(),
              "Step 2: W-first pair to a CTM register and an unmapped word: responses in order",
              UVM_LOW)
    select_port = $urandom_range(XtrigNumCtmPorts - 1);
    select = $urandom_range(CtmSelectMask, 1);
    unmapped = XtrigUnmappedBase + $urandom_range('h3F) * 4;
    run_write_pair(ctm_config_addr(select_port), select, unmapped, $urandom(), first, second,
                   .aw_valid_delay($urandom_range(8, 4)), .b_ready_delay($urandom_range(4, 1)),
                   .label("demux_aw_lock.order"), .check_response(1'b0));
    check_evidence(ChkAxil, "demux_aw_lock.order.first_bresp", 64'(first.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    check_evidence(ChkAxil, "demux_aw_lock.order.second_bresp", 64'(second.worst_resp()),
                   64'(OCAH_AXI_RESP_DECERR));
    csr_read(ctm_config_addr(select_port), observed, "demux_aw_lock.order");
    check_evidence(ChkAxil, "demux_aw_lock.order.readback", 64'(observed & CtmSelectMask),
                   64'(select));
  endtask

  // Two outstanding skewed writes judged against the demux state mirrors.
  // The demux queues the first AW's port selection until its W passes
  // (xtrig_demux_w_pending) and holds the second AW with AWREADY low
  // meanwhile: the port's open-write counters see the second AW stall, and
  // no AW accepted, while the first is owed its W. The AW lock flag, which
  // needs a subordinate that refuses a presented AW, stays clear. Both
  // responses must complete and the bench stall counter must agree with the
  // VIP's AW observation.
  protected task run_write_pair(
      input bit [63:0] addr_a, input bit [31:0] data_a, input bit [63:0] addr_b,
      input bit [31:0] data_b, output ocah_axi_item first, output ocah_axi_item second,
      input int unsigned aw_valid_delay = 0, input int unsigned w_valid_delay = 0,
      input int unsigned b_ready_delay = 0, input string label = "",
      input bit check_response = 1'b1);
    bit [31:0] stall_before = xtrig_pin("xtrig_axil_aw_stall_count");
    bit [31:0] open_stall_before = xtrig_pin("xtrig_axil_aw_open_stall_count");
    bit [31:0] open_accept_before = xtrig_pin("xtrig_axil_aw_open_accept_count");
    bit [31:0] stall_delta, open_stall_delta, open_accept_delta;
    start_activity_window_on(demux_signals);
    write_pair_skewed(addr_a, data_a, addr_b, data_b, first, second, aw_valid_delay, w_valid_delay,
                      b_ready_delay, check_response);
    stop_activity_window();
    stall_delta = xtrig_pin("xtrig_axil_aw_stall_count") - stall_before;
    open_stall_delta = xtrig_pin("xtrig_axil_aw_open_stall_count") - open_stall_before;
    open_accept_delta = xtrig_pin("xtrig_axil_aw_open_accept_count") - open_accept_before;
    `uvm_info(get_type_name(),
              $sformatf(
                  "%s aw_stall=%0d aw_stable=%0d w_pending_seen=%0d aw_lock_seen=%0d resp=%s/%s",
                  label, first.ax_stall_cycles, first.ax_stable,
                  window_activity["xtrig_demux_w_pending"], window_activity["xtrig_demux_aw_lock"],
                  first.worst_resp().name(), second.worst_resp().name()), UVM_LOW)
    if (check_response) begin
      check_evidence(ChkAxil, {label, ".first_bresp"}, 64'(first.worst_resp()),
                     64'(OCAH_AXI_RESP_OKAY));
      check_evidence(ChkAxil, {label, ".second_bresp"}, 64'(second.worst_resp()),
                     64'(OCAH_AXI_RESP_OKAY));
    end
    check_evidence(ChkAwLock, {label, ".w_pending_engaged"},
                   64'(window_activity["xtrig_demux_w_pending"]), 64'd1);
    check_evidence(ChkAwLock, {label, ".w_pending_released"},
                   64'(window_last["xtrig_demux_w_pending"]), 64'd0);
    check_evidence(ChkAwLock, {label, ".aw_lock_clear"},
                   64'(window_activity["xtrig_demux_aw_lock"]), 64'd0);
    check_evidence(ChkAwLock, {label, ".second_aw_held_while_w_open"}, 64'(open_stall_delta > 0),
                   64'd1, $sformatf("open_stall_cycles=%0d", open_stall_delta));
    check_evidence(ChkAwLock, {label, ".no_aw_accept_while_w_open"}, 64'(open_accept_delta), 64'd0);
    check_evidence(ChkAwLock, {label, ".aw_stall_count"}, 64'(stall_delta),
                   64'(first.ax_stall_cycles));
  endtask

  protected task run_read_decode_backpressure();
    int unsigned offs[$];
    bit [63:0] addr_a, addr_b;
    int unsigned hold = $urandom_range(8, 4);
    bit [31:0] stall_before = xtrig_pin("xtrig_axil_ar_stall_count");
    bit [31:0] arvalid_before = xtrig_pin("xtrig_axil_arvalid_count");
    bit [31:0] open_stall_before = xtrig_pin("xtrig_axil_ar_open_stall_count");
    bit [31:0] open_accept_before = xtrig_pin("xtrig_axil_ar_open_accept_count");
    bit [31:0] stall_delta, arvalid_delta, open_stall_delta, open_accept_delta;
    ocah_axi_item first, second;
    `uvm_info(get_type_name(), "XTRIG AXI-Lite read decode backpressure", UVM_LOW)
    // Seeded per-pass unmapped offsets and RREADY hold width.
    pick_distinct('h40, 2, offs);
    offs.sort();
    addr_a = XtrigUnmappedBase + offs[0] * 4;
    addr_b = XtrigUnmappedBase + offs[1] * 4;
    read_pair_hold(addr_a, addr_b, hold, first, second, .check_response(1'b0));
    stall_delta   = xtrig_pin("xtrig_axil_ar_stall_count") - stall_before;
    arvalid_delta = xtrig_pin("xtrig_axil_arvalid_count") - arvalid_before;
    open_stall_delta = xtrig_pin("xtrig_axil_ar_open_stall_count") - open_stall_before;
    open_accept_delta = xtrig_pin("xtrig_axil_ar_open_accept_count") - open_accept_before;
    `uvm_info(
        get_type_name(),
        $sformatf(
            "unmapped pair a=0x%0h b=0x%0h hold=%0d resp=%s/%s data=0x%08h/0x%08h ar_stall=%0d ar_stable=%0d hold_stable=%0d",
            addr_a, addr_b, hold, first.worst_resp().name(), second.worst_resp().name(),
            first.first_data(), second.first_data(), first.ax_stall_cycles, first.ax_stable,
            first.hold_stable), UVM_LOW)
    // No subordinate decodes an unmapped address: AXI answers DECERR.
    check_evidence(ChkAxil, "read_decode.first.resp", 64'(first.worst_resp()),
                   64'(OCAH_AXI_RESP_DECERR));
    check_evidence(ChkAxil, "read_decode.second.resp", 64'(second.worst_resp()),
                   64'(OCAH_AXI_RESP_DECERR));
    check_evidence(ChkAxil, "read_decode.first.hold_stable", 64'(first.hold_stable), 64'd1);
    // The crossbar admits one read in flight: the second AR stalls, and no AR
    // is accepted, while the first is owed its R beat.
    check_evidence(ChkArStall, "read_decode.second_ar_held_while_read_open",
                   64'(open_stall_delta > 0), 64'd1, $sformatf(
                   "open_stall_cycles=%0d", open_stall_delta));
    check_evidence(ChkArStall, "read_decode.no_ar_accept_while_read_open", 64'(open_accept_delta),
                   64'd0);
    check_evidence(ChkArStall, "read_decode.ar_stall_count", 64'(stall_delta),
                   64'(first.ax_stall_cycles));
    check_evidence(ChkArStall, "read_decode.ar_accepted", 64'(arvalid_delta - stall_delta), 64'd2);
  endtask

endclass : dtp_xtrig_csr_test_seq
