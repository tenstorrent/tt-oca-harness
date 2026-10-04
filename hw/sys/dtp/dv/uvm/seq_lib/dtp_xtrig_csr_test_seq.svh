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
//                    STATUS write, a write to the window's hole, and a
//                    preloaded neighbour that keeps its words, on every CTP,
//                    then one routed stretched pulse
//   ctm_csr_sweep    full-word CT_DST_SELECT patterns, every byte strobe, and
//                    a write to the slot's hole on every CTM source register,
//                    a write and a read answered DECERR in the matrix
//                    aperture past its registers and past the last CTP
//                    window, then two swept selects routing a selected input
//                    and ignoring an unselected one
//   ctm_all_source_select  per-source select masks with neighbor
//                    no-aliasing reads
//   axi_channel_skew                       AW-first and W-first skewed
//                    writes, each read back, deferred BREADY, and an
//                    RREADY-hold read with data-stability evidence
//   axi_channel_skew_demux_aw_lock_release two-outstanding skewed writes
//                    judged against the crossbar demux state mirrors and
//                    open-write counters behind the CSR port spill
//                    registers, with response order proven by
//                    distinguishable response codes
//   axi_channel_skew_read_decode_backpressure two outstanding reads under
//                    an RREADY hold, a CTP register and then an unmapped
//                    word: the port's R spill register holds both responses,
//                    the demux holds the second AR until the first response
//                    passes it (demux open-read counters), and the reads
//                    return OKAY with the written data and then DECERR
//   axi_outstanding  seven reads, then seven writes, in flight with the
//                    responses held until the port stalls, the third access
//                    reaching each crossbar subordinate in turn; a write, a
//                    read and a second write to one register block swept
//                    across launch offsets, engaging the demux AW lock; a
//                    read parked behind two held reads alongside a write to
//                    its block; every AxPROT value, a high unmapped word,
//                    unaligned reads and writes, a late W and back-to-back
//                    matrix ARs, with drawn CT_SRC masks held throughout.
//                    Every access answers DECERR exactly when its word is
//                    unmapped, and the port stall counters match the VIP's
//                    stall cycles

class dtp_xtrig_csr_test_seq extends dtp_xtrig_base_test_seq;
  `uvm_object_utils(dtp_xtrig_csr_test_seq)

  // Seeded range of the cycles BREADY waits after a skewed write's request
  // phase: longer than the write response takes to reach the CSR port, so
  // the port holds the response.
  localparam int unsigned SkewBReadyDelayMin = 5;
  localparam int unsigned SkewBReadyDelayMax = 8;
  // Accesses in each outstanding read or write burst. The CSR port holds two
  // requests in its address spill register, the crossbar one, and the
  // response spill register two responses, so with the responses held the
  // sixth and seventh requests find READY low.
  localparam int unsigned OutstandingBurst = 7;
  // Seeded range of the cycles BREADY or RREADY stays low after a burst's
  // first response: long enough for the burst to back up to the port.
  localparam int unsigned OutstandingHoldMin = 12;
  localparam int unsigned OutstandingHoldMax = 16;
  // Crossbar subordinates a burst's third access visits in turn: the matrix,
  // every CTP, and the decode-error subordinate.
  localparam int unsigned OutstandingTargets = XtrigNumCtp + 2;
  // An unmapped word with every address bit above the CSR map set.
  localparam bit [63:0] XtrigHighUnmapped = 64'hFFFF_FC00;
  // Cycles a write waits behind two held reads and a third read to its
  // register block: the sweep lands it while that read's response is stuck
  // in the block.
  localparam int unsigned OutstandingInFlightDelays[5] = '{6, 8, 10, 12, 14};

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
      "axi_outstanding":   run_axi_outstanding();
      default: super.dispatch_scenario();
    endcase
  endtask

  // Accepted-path CSR accesses under an activity window: no internal-lane
  // request, CTP request or acknowledge enable, or CTP busy flop moves while
  // an access is in flight, the crossbar demux's AW and AR stall counters do
  // not advance while the port's AWVALID and ARVALID counters do, and two
  // routes afterwards, one wire-OR and one point-to-point, are the positive
  // control that moves each of those observables. The pad levels and the
  // receive pulses stay out of the window because they follow the polarity
  // CSR the accesses write.
  protected task run_reg_stall();
    bit [15:0] stretch = 16'($urandom);
    bit [31:0] select = $urandom_range(CtmSelectMask, 1);
    bit [31:0] aw_stall0 = xtrig_pin("xtrig_demux_aw_stall_count");
    bit [31:0] ar_stall0 = xtrig_pin("xtrig_demux_ar_stall_count");
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
    // A single access never fills a spill register, so the port keeps its
    // READY high and a regblock stall shows only at the demux behind it.
    check_evidence(ChkAxil, "regstall.aw_stall_count_delta", 64'(xtrig_pin(
                   "xtrig_demux_aw_stall_count") - aw_stall0), 64'd0);
    check_evidence(ChkAxil, "regstall.awvalid_count_advanced", 64'(xtrig_pin(
                   "xtrig_axil_awvalid_count") - awvalid0 > 0), 64'd1);
    check_evidence(ChkAxil, "regstall.ar_stall_count_delta", 64'(xtrig_pin(
                   "xtrig_demux_ar_stall_count") - ar_stall0), 64'd0);
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

  // Full-word patterns, every byte strobe, a STATUS write, the final words,
  // then a hole write, on one CTP.
  protected task sweep_ctp_words(int unsigned ctp_idx, bit [31:0] config_patterns[$],
                                 bit [31:0] stretch_patterns[$], bit [31:0] final_config,
                                 bit [31:0] final_stretch);
    bit [63:0] config_addr = ctp_config_addr(ctp_idx);
    bit [63:0] stretch_addr = ctp_stretch_addr(ctp_idx);
    bit [3:0] strobes[4] = '{4'h1, 4'h2, 4'h4, 4'h8};
    bit [31:0] old_cfg, new_cfg, old_stretch, new_stretch, status_before, observed;
    string ctx = $sformatf("ctp=%0d", ctp_idx);
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
    // The word past STRETCH_MULT is a hole: it reads 0 after an all-ones
    // write, and the write leaves the window's registers on the final words.
    write_read_check(ctp_hole_addr(ctp_idx), FullWord, 32'h0, 4'hF, FullWord, $sformatf(
                     "ctp%0d.hole", ctp_idx));
    csr_read(config_addr, observed, $sformatf("ctp%0d.hole_after.config", ctp_idx));
    check_evidence(ChkCsr, $sformatf("ctp%0d.hole_no_alias.config", ctp_idx),
                   64'(observed & CtpConfigMask), 64'(final_config & CtpConfigMask), ctx);
    csr_read(stretch_addr, observed, $sformatf("ctp%0d.hole_after.stretch", ctp_idx));
    check_evidence(ChkCsr, $sformatf("ctp%0d.hole_no_alias.stretch", ctp_idx),
                   64'(observed & CtpStretchMask), 64'(final_stretch & CtpStretchMask), ctx);
  endtask

  protected task run_ctm_csr_sweep();
    bit [31:0] patterns[$];
    bit [31:0] random_mask = $urandom_range(CtmSelectMask, 1);
    bit [3:0] strobes[4] = '{4'h1, 4'h2, 4'h4, 4'h8};
    bit [31:0] old_mask, new_mask, held, observed;
    bit [63:0] unmapped[2];
    int unsigned outputs[$];
    ocah_axi_item res;
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
        held = apply_wstrb(old_mask, new_mask, strobes[s]) & CtmSelectMask;
        program_ctm_src(src_idx, old_mask);
        write_read_check(ctm_config_addr(src_idx), new_mask, held, strobes[s], FullWord, $sformatf(
                         "ctm%0d.wstrb%0h", src_idx, strobes[s]));
      end
      // The word past CT_SRC[src_idx] in its slot is a hole: it reads 0 after
      // an all-ones write, and the write leaves the register on its last word.
      write_read_check(ctm_hole_addr(src_idx), FullWord, 32'h0, 4'hF, FullWord, $sformatf(
                       "ctm%0d.hole", src_idx));
      csr_read(ctm_config_addr(src_idx), observed, $sformatf("ctm%0d.hole_after", src_idx));
      check_evidence(ChkCsr, $sformatf("ctm%0d.hole_no_alias", src_idx), 64'(observed), 64'(held),
                     $sformatf("src=%0d", src_idx));
    end
    // The matrix aperture past its register extent and every word past the
    // last CTP window decode to no register: a write and a read of a seeded
    // word of each complete with DECERR.
    unmapped[0] = DtpXtrigCtmEnd + 64'($urandom_range((DtpXtrigCtpBase - DtpXtrigCtmEnd) / 4 - 1)) * 4;
    unmapped[1] = XtrigUnmappedBase + 64'($urandom_range('h3F)) * 4;
    foreach (unmapped[k]) begin
      string name = (k == 0) ? "ctm_unmapped" : "unmapped";
      string ctx = $sformatf("addr=0x%03h", unmapped[k]);
      write_skewed_result(unmapped[k], 64'(FullWord), res, .check_response(1'b0));
      check_evidence(ChkCsr, {name, ".bresp"}, 64'(res.worst_resp()), 64'(OCAH_AXI_RESP_DECERR),
                     ctx);
      read_hold_result(unmapped[k], 0, res, .check_response(1'b0));
      check_evidence(ChkCsr, {name, ".rresp"}, 64'(res.worst_resp()), 64'(OCAH_AXI_RESP_DECERR),
                     ctx);
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
    bit [31:0] demux_w_stall_before, demux_w_stall_delta, spill_err_before, spill_err_delta;
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
                        .b_ready_delay($urandom_range(SkewBReadyDelayMax, SkewBReadyDelayMin)));
    check_evidence(ChkAxil, "axi_skew.aw_before_w.bresp", 64'(res.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    csr_read(addr, observed, "axi_skew.aw_before_w.readback");
    check_evidence(ChkAxil, "axi_skew.aw_before_w.stretch", 64'(observed & CtpStretchMask),
                   64'(d1));
    write_read_check(addr, 32'(d2), 32'(d2), 4'hF, CtpStretchMask, "axi_skew.normal_after_aw");
    w_stall_before = xtrig_pin("xtrig_axil_w_stall_count");
    demux_w_stall_before = xtrig_pin("xtrig_demux_w_stall_count");
    spill_err_before = xtrig_pin("xtrig_axil_spill_err_count");
    aw_delay = $urandom_range(7, 3);
    write_skewed_result(addr, 64'(d3), res, .aw_valid_delay(aw_delay),
                        .b_ready_delay($urandom_range(SkewBReadyDelayMax, SkewBReadyDelayMin)));
    w_stall_delta = xtrig_pin("xtrig_axil_w_stall_count") - w_stall_before;
    demux_w_stall_delta = xtrig_pin("xtrig_demux_w_stall_count") - demux_w_stall_before;
    spill_err_delta = xtrig_pin("xtrig_axil_spill_err_count") - spill_err_before;
    check_evidence(ChkAxil, "axi_skew.w_before_aw.bresp", 64'(res.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    // The CSR port's W spill register takes the early W beat with WREADY
    // high. The demux behind it passes a W beat from the cycle after its AW
    // enters the demux's W-select queue, so the beat stalls there for at least
    // the AW delay plus one cycle.
    check_evidence(ChkAxil, "axi_skew.w_before_aw.port_w_unstalled", 64'(w_stall_delta), 64'd0);
    check_evidence(ChkAxil, "axi_skew.w_before_aw.w_ready_low_seen",
                   64'(demux_w_stall_delta >= aw_delay + 1), 64'd1, $sformatf(
                   "demux_w_stall_cycles=%0d aw_delay=%0d", demux_w_stall_delta, aw_delay));
    check_evidence(ChkAxil, "axi_skew.w_before_aw.spill_contract", 64'(spill_err_delta), 64'd0);
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
  // The CSR port's spill registers accept both AWs and both W beats with
  // READY high. Behind them the demux queues the first AW's port selection
  // until its W passes (xtrig_demux_w_pending) and holds the second AW
  // meanwhile: the demux open-write counters see the second AW wait, and no
  // AW admitted, while the first is owed its W. The AW lock flag, which needs
  // a subordinate that refuses a presented AW, stays clear. Both responses
  // must complete, every spill register's READY and VALID must match the
  // beats it holds, and the port stall counter must agree with the VIP's AW
  // observation.
  protected task run_write_pair(
      input bit [63:0] addr_a, input bit [31:0] data_a, input bit [63:0] addr_b,
      input bit [31:0] data_b, output ocah_axi_item first, output ocah_axi_item second,
      input int unsigned aw_valid_delay = 0, input int unsigned w_valid_delay = 0,
      input int unsigned b_ready_delay = 0, input string label = "",
      input bit check_response = 1'b1);
    bit [31:0] stall_before = xtrig_pin("xtrig_axil_aw_stall_count");
    bit [31:0] open_stall_before = xtrig_pin("xtrig_axil_aw_open_stall_count");
    bit [31:0] open_accept_before = xtrig_pin("xtrig_axil_aw_open_accept_count");
    bit [31:0] spill_err_before = xtrig_pin("xtrig_axil_spill_err_count");
    bit [31:0] w_full_before = xtrig_pin("xtrig_axil_w_spill_full_count");
    bit [31:0] demux_open_stall_before = xtrig_pin("xtrig_demux_aw_open_stall_count");
    bit [31:0] demux_open_accept_before = xtrig_pin("xtrig_demux_aw_open_accept_count");
    bit [31:0] stall_delta, open_stall_delta, open_accept_delta, spill_err_delta, w_full_delta;
    bit [31:0] demux_open_stall_delta, demux_open_accept_delta;
    start_activity_window_on(demux_signals);
    write_pair_skewed(addr_a, data_a, addr_b, data_b, first, second, aw_valid_delay, w_valid_delay,
                      b_ready_delay, check_response);
    stop_activity_window();
    stall_delta = xtrig_pin("xtrig_axil_aw_stall_count") - stall_before;
    open_stall_delta = xtrig_pin("xtrig_axil_aw_open_stall_count") - open_stall_before;
    open_accept_delta = xtrig_pin("xtrig_axil_aw_open_accept_count") - open_accept_before;
    spill_err_delta = xtrig_pin("xtrig_axil_spill_err_count") - spill_err_before;
    w_full_delta = xtrig_pin("xtrig_axil_w_spill_full_count") - w_full_before;
    demux_open_stall_delta = xtrig_pin("xtrig_demux_aw_open_stall_count") - demux_open_stall_before;
    demux_open_accept_delta = xtrig_pin("xtrig_demux_aw_open_accept_count") - demux_open_accept_before;
    `uvm_info(get_type_name(),
              $sformatf(
                  {"%s aw_stall=%0d aw_stable=%0d w_pending_seen=%0d aw_lock_seen=%0d resp=%s/%s ",
                   "port_open_accept=%0d w_spill_full=%0d spill_err=%0d demux_open_stall=%0d ",
                   "demux_open_accept=%0d"}, label, first.ax_stall_cycles, first.ax_stable,
                    window_activity["xtrig_demux_w_pending"],
                    window_activity["xtrig_demux_aw_lock"], first.worst_resp().name(),
                    second.worst_resp().name(), open_accept_delta, w_full_delta, spill_err_delta,
                    demux_open_stall_delta, demux_open_accept_delta), UVM_LOW)
    if (check_response) begin
      check_evidence(ChkAxil, {label, ".first_bresp"}, 64'(first.worst_resp()),
                     64'(OCAH_AXI_RESP_OKAY));
      check_evidence(ChkAxil, {label, ".second_bresp"}, 64'(second.worst_resp()),
                     64'(OCAH_AXI_RESP_OKAY));
    end
    check_evidence(ChkAxil, {label, ".spill_contract"}, 64'(spill_err_delta), 64'd0);
    // A W-first pair fills the W spill register with both W beats. In an
    // AW-first pair the port accepts the second AW one cycle after the first,
    // which counts as an acceptance while the first is open only when the
    // first W beat trails its AW by two or more cycles.
    if (aw_valid_delay > 0)
      check_evidence(ChkAxil, {label, ".w_spill_holds_pair"}, 64'(w_full_delta > 0), 64'd1,
                     $sformatf("w_full_cycles=%0d", w_full_delta));
    else if (w_valid_delay >= 2)
      check_evidence(ChkAxil, {label, ".port_second_aw_accepted"}, 64'(open_accept_delta), 64'd1,
                     $sformatf("port_open_stall_cycles=%0d", open_stall_delta));
    check_evidence(ChkAwLock, {label, ".w_pending_engaged"},
                   64'(window_activity["xtrig_demux_w_pending"]), 64'd1);
    check_evidence(ChkAwLock, {label, ".w_pending_released"},
                   64'(window_last["xtrig_demux_w_pending"]), 64'd0);
    check_evidence(ChkAwLock, {label, ".aw_lock_clear"},
                   64'(window_activity["xtrig_demux_aw_lock"]), 64'd0);
    check_evidence(ChkAwLock, {label, ".second_aw_held_while_w_open"},
                   64'(demux_open_stall_delta > 0), 64'd1, $sformatf(
                   "demux_open_stall_cycles=%0d", demux_open_stall_delta));
    check_evidence(ChkAwLock, {label, ".no_aw_accept_while_w_open"}, 64'(demux_open_accept_delta),
                   64'd0);
    check_evidence(ChkAwLock, {label, ".aw_stall_count"}, 64'(stall_delta),
                   64'(first.ax_stall_cycles));
  endtask

  protected task run_read_decode_backpressure();
    bit [63:0] addr_a, addr_b;
    bit [15:0] stretch;
    int unsigned hold;
    bit [31:0] stall_before, arvalid_before, open_stall_before, open_accept_before;
    bit [31:0] spill_err_before, r_full_before, demux_open_stall_before, demux_open_accept_before;
    bit [31:0] stall_delta, arvalid_delta, open_stall_delta, open_accept_delta;
    bit [31:0] spill_err_delta, r_full_delta, demux_open_stall_delta, demux_open_accept_delta;
    ocah_axi_item first, second;
    `uvm_info(get_type_name(), "XTRIG AXI-Lite read decode backpressure", UVM_LOW)
    // Seeded per-pass CTP, STRETCH_MULT value, unmapped offset and RREADY hold
    // width. The two reads target different subordinates: a CTP register, then
    // an unmapped word.
    addr_a = ctp_stretch_addr($urandom_range(XtrigNumCtp - 1));
    addr_b = XtrigUnmappedBase + $urandom_range('h3F) * 4;
    stretch = 16'($urandom_range(16'hFFFF, 1));
    hold = $urandom_range(8, 4);
    csr_write(addr_a, 32'(stretch), 4'hF, "read_decode.first.write");
    stall_before = xtrig_pin("xtrig_axil_ar_stall_count");
    arvalid_before = xtrig_pin("xtrig_axil_arvalid_count");
    open_stall_before = xtrig_pin("xtrig_axil_ar_open_stall_count");
    open_accept_before = xtrig_pin("xtrig_axil_ar_open_accept_count");
    spill_err_before = xtrig_pin("xtrig_axil_spill_err_count");
    r_full_before = xtrig_pin("xtrig_axil_r_spill_full_count");
    demux_open_stall_before = xtrig_pin("xtrig_demux_ar_open_stall_count");
    demux_open_accept_before = xtrig_pin("xtrig_demux_ar_open_accept_count");
    read_pair_hold(addr_a, addr_b, hold, first, second, .check_response(1'b0));
    stall_delta   = xtrig_pin("xtrig_axil_ar_stall_count") - stall_before;
    arvalid_delta = xtrig_pin("xtrig_axil_arvalid_count") - arvalid_before;
    open_stall_delta = xtrig_pin("xtrig_axil_ar_open_stall_count") - open_stall_before;
    open_accept_delta = xtrig_pin("xtrig_axil_ar_open_accept_count") - open_accept_before;
    spill_err_delta = xtrig_pin("xtrig_axil_spill_err_count") - spill_err_before;
    r_full_delta = xtrig_pin("xtrig_axil_r_spill_full_count") - r_full_before;
    demux_open_stall_delta = xtrig_pin("xtrig_demux_ar_open_stall_count") - demux_open_stall_before;
    demux_open_accept_delta = xtrig_pin("xtrig_demux_ar_open_accept_count") - demux_open_accept_before;
    `uvm_info(
        get_type_name(),
        $sformatf(
            {"read pair a=0x%0h b=0x%0h hold=%0d resp=%s/%s data=0x%08h/0x%08h ar_stall=%0d ",
             "ar_stable=%0d hold_stable=%0d port_open_accept=%0d r_spill_full=%0d spill_err=%0d ",
             "demux_open_stall=%0d demux_open_accept=%0d"}, addr_a, addr_b, hold,
              first.worst_resp().name(), second.worst_resp().name(), first.first_data(),
              second.first_data(), first.ax_stall_cycles, first.ax_stable, first.hold_stable,
              open_accept_delta, r_full_delta, spill_err_delta, demux_open_stall_delta,
              demux_open_accept_delta), UVM_LOW)
    // The first read returns the STRETCH_MULT word written before the pair.
    // No subordinate decodes the unmapped second address: AXI answers DECERR.
    check_evidence(ChkAxil, "read_decode.first.resp", 64'(first.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    check_evidence(ChkAxil, "read_decode.first.data", 64'(first.first_data() & CtpStretchMask),
                   64'(stretch));
    check_evidence(ChkAxil, "read_decode.second.resp", 64'(second.worst_resp()),
                   64'(OCAH_AXI_RESP_DECERR));
    check_evidence(ChkAxil, "read_decode.first.hold_stable", 64'(first.hold_stable), 64'd1);
    check_evidence(ChkAxil, "read_decode.spill_contract", 64'(spill_err_delta), 64'd0);
    check_evidence(ChkAxil, "read_decode.port_second_ar_accepted", 64'(open_accept_delta), 64'd1,
                   $sformatf("port_open_stall_cycles=%0d", open_stall_delta));
    check_evidence(ChkAxil, "read_decode.r_spill_holds_pair", 64'(r_full_delta > 0), 64'd1,
                   $sformatf("r_full_cycles=%0d", r_full_delta));
    // The demux admits one read in flight. The two reads go to different
    // subordinates, so the demux alone holds the second AR, and admits none,
    // while the first read is owed its R beat.
    check_evidence(ChkArStall, "read_decode.second_ar_held_while_read_open",
                   64'(demux_open_stall_delta > 0), 64'd1, $sformatf(
                   "demux_open_stall_cycles=%0d", demux_open_stall_delta));
    check_evidence(ChkArStall, "read_decode.no_ar_accept_while_read_open",
                   64'(demux_open_accept_delta), 64'd0);
    check_evidence(ChkArStall, "read_decode.ar_stall_count", 64'(stall_delta),
                   64'(first.ax_stall_cycles));
    check_evidence(ChkArStall, "read_decode.ar_accepted", 64'(arvalid_delta - stall_delta), 64'd2);
  endtask

  // A word of crossbar subordinate `target`: 0 the matrix, 1 to XtrigNumCtp a
  // CTP, XtrigNumCtp + 1 none. Writes land on a CT_SRC select or a
  // STRETCH_MULT, which change no pad while no trigger is pulsed; reads may
  // also land on CONFIG and STATUS.
  protected function bit [63:0] outstanding_word(int unsigned target, bit write);
    bit [63:0] words[3];
    int unsigned ctp;
    if (target == 0) return ctm_config_addr($urandom_range(XtrigNumCtmPorts - 1));
    if (target <= XtrigNumCtp) begin
      ctp = target - 1;
      if (write) return ctp_stretch_addr(ctp);
      words = '{ctp_config_addr(ctp), ctp_stretch_addr(ctp), ctp_status_addr(ctp)};
      return words[$urandom_range(2)];
    end
    return XtrigUnmappedBase + 64'($urandom_range('h3F)) * 4;
  endfunction

  // A write of a drawn word.
  protected function pipeline_op_t outstanding_write(
      bit [63:0] addr, int unsigned aw_valid_delay = 0, int unsigned w_valid_delay = 0,
      bit [2:0] prot = '0, bit [3:0] strb = 4'hF);
    return pipeline_write_op(addr, $urandom(), aw_valid_delay, w_valid_delay, prot, strb);
  endfunction

  // Issue `ops` through the VIP pipeline and judge responses, spill contract
  // and stalls: every access answers DECERR exactly when no subordinate
  // decodes its word, every CSR port spill register keeps READY and VALID
  // matched to the beats it holds, and the port's stall counters agree with
  // the stall cycles the VIP saw on each request channel. `delta` is the
  // advance of each judged counter.
  protected task run_outstanding_pipeline(
      input pipeline_op_t ops[$], input string label, output bit [31:0] delta[string],
      input int unsigned b_hold = 0, input int unsigned r_hold = 0);
    string counters[4] = '{
        "xtrig_axil_spill_err_count",
        "xtrig_axil_aw_stall_count",
        "xtrig_axil_w_stall_count",
        "xtrig_axil_ar_stall_count"
    };
    string channels[3] = '{"aw", "w", "ar"};
    int unsigned vip_stall[3];
    bit [31:0] start_count[string];
    bit [31:0] mask;
    string resps = "";
    string direction;
    ocah_axi_resp_e expected;
    ocah_axi_item result;
    ocah_axi_item op_results[$];
    foreach (counters[i]) start_count[counters[i]] = xtrig_pin(counters[i]);
    pipeline_result(ops, result, op_results, b_hold, r_hold, .check_response(1'b0));
    foreach (counters[i]) delta[counters[i]] = xtrig_pin(counters[i]) - start_count[counters[i]];
    vip_stall = '{result.aw_stall_cycles, result.w_stall_cycles, result.ar_stall_cycles};
    foreach (op_results[i]) begin
      if (i > 0) resps = {resps, ", "};
      resps = {resps, $sformatf("%0d", op_results[i].worst_resp())};
    end
    `uvm_info(get_type_name(),
              $sformatf("%s %0d accesses b_hold=%0d r_hold=%0d resp=[%s] aw/w/ar stall=%0d/%0d/%0d",
                        label, ops.size(), b_hold, r_hold, resps, vip_stall[0], vip_stall[1],
                        vip_stall[2]), UVM_LOW)
    foreach (ops[i]) begin
      direction = (ops[i].direction == OCAH_AXI_DIR_WRITE) ? "write" : "read";
      expected = (dtp_xtrig_csr_decode(ops[i].addr, mask) == DTP_XTRIG_CSR_UNMAPPED) ?
          OCAH_AXI_RESP_DECERR : OCAH_AXI_RESP_OKAY;
      check_evidence(ChkAxil, $sformatf("%s.%s%0d.resp", label, direction, i),
                     64'(op_results[i].worst_resp()), 64'(expected), $sformatf(
                     "addr=0x%08h", ops[i].addr[31:0]));
    end
    check_evidence(ChkAxil, {label, ".spill_contract"}, 64'(delta["xtrig_axil_spill_err_count"]),
                   64'd0);
    foreach (channels[c])
      check_evidence(ChkAxil, $sformatf("%s.%s_stall_count", label, channels[c]),
                     64'(delta[$sformatf("xtrig_axil_%s_stall_count", channels[c])]),
                     64'(vip_stall[c]));
  endtask

  // Several CSR accesses in flight, with the responses held. Read and write
  // bursts deep enough to back up to the port visit every crossbar
  // subordinate as their third access, a sweep of a write, a read and a
  // second write to one register block engages the demux AW lock, a read
  // parked behind two held reads meets a write to its own block, accesses
  // carry every AxPROT value and the address bits outside the map, reads
  // address every subordinate at an unaligned byte, and the matrix and the
  // decode-error subordinate take a late W and back-to-back ARs. Every
  // CT_SRC select holds a drawn mask meanwhile, so the held read data
  // carries the upper select bits; no trigger is pulsed, and the selects are
  // cleared on exit.
  protected task run_axi_outstanding();
    int unsigned targets[$], others[$], picks[$], ports[$];
    int unsigned late_w_targets[2];
    int unsigned block_targets[2];
    bit [63:0] block_write[2], block_read[2];
    int unsigned target, ctp;
    string write_channels[2] = '{"aw", "w"};
    string label;
    bit [63:0] addr, stretch_addr, config_addr;
    bit [3:0] strb;
    bit [2:0] prot;
    bit [31:0] delta[string];
    pipeline_op_t ops[$];
    `uvm_info(get_type_name(), "XTRIG AXI-Lite outstanding accesses", UVM_LOW)
    for (int unsigned t = 0; t < OutstandingTargets; t++) targets.push_back(t);
    ops.delete();
    for (int unsigned port = 0; port < XtrigNumCtmPorts; port++)
      ops.push_back(outstanding_write(ctm_config_addr(port)));
    run_outstanding_pipeline(ops, "outstanding.ct_src_masks", delta);

    targets.shuffle();
    foreach (targets[k]) begin
      label = $sformatf("outstanding.read%0d", targets[k]);
      ops.delete();
      for (int unsigned index = 0; index < OutstandingBurst; index++) begin
        target = (index == 2) ? targets[k] : $urandom_range(OutstandingTargets - 1);
        addr = outstanding_word(target, 1'b0);
        prot = 3'($urandom_range(7));
        ops.push_back(pipeline_read_op(addr, .prot(prot)));
      end
      run_outstanding_pipeline(ops, label, delta,
                               .r_hold($urandom_range(OutstandingHoldMax, OutstandingHoldMin)));
      check_evidence(ChkArStall, {label, ".port_ar_stalled"},
                     64'(delta["xtrig_axil_ar_stall_count"] > 0), 64'd1, $sformatf(
                     "ar_stall_cycles=%0d", delta["xtrig_axil_ar_stall_count"]));
    end

    // The fifth write of each burst waits in the port's AW spill register at
    // an unaligned address: its strobe covers the lanes from that byte up.
    targets.shuffle();
    foreach (targets[k]) begin
      label = $sformatf("outstanding.write%0d", targets[k]);
      ops.delete();
      for (int unsigned index = 0; index < OutstandingBurst; index++) begin
        target = (index == 2) ? targets[k] : $urandom_range(OutstandingTargets - 1);
        addr = outstanding_word(target, 1'b1);
        strb = 4'hF;
        if (index == 4) strb = 4'(4'hF << $urandom_range(3, 1));
        prot = 3'($urandom_range(7));
        ops.push_back(outstanding_write(addr, .prot(prot), .strb(strb)));
      end
      run_outstanding_pipeline(ops, label, delta,
                               .b_hold($urandom_range(OutstandingHoldMax, OutstandingHoldMin)));
      foreach (write_channels[c]) begin
        string counter = $sformatf("xtrig_axil_%s_stall_count", write_channels[c]);
        check_evidence(ChkAxil, $sformatf("%s.port_%s_stalled", label, write_channels[c]),
                       64'(delta[counter] > 0), 64'd1, $sformatf(
                       "%s_stall_cycles=%0d", write_channels[c], delta[counter]));
      end
    end

    // A register block takes a read and a write together, on a seeded CTP and
    // on the matrix. Its AW lock needs the demux to present a write the block
    // refuses, which a read and a second write landing a cycle after the
    // first write produce.
    ctp = $urandom_range(XtrigNumCtp - 1);
    stretch_addr = ctp_stretch_addr(ctp);
    config_addr = ctp_config_addr(ctp);
    pick_distinct(XtrigNumCtmPorts, 2, ports);
    block_targets = '{1 + ctp, 0};
    block_write = '{stretch_addr, ctm_config_addr(ports[0])};
    block_read = '{config_addr, ctm_config_addr(ports[1])};
    start_activity_window_on(demux_signals);
    foreach (block_targets[b]) begin
      for (int unsigned ar_delay = 0; ar_delay < 3; ar_delay++) begin
        for (int unsigned aw_delay = 0; aw_delay < 3; aw_delay++) begin
          for (int unsigned w_lag = 0; w_lag <= 2; w_lag += 2) begin
            ops.delete();
            ops.push_back(outstanding_write(block_write[b]));
            ops.push_back(pipeline_read_op(block_read[b], ar_delay));
            ops.push_back(outstanding_write(block_write[b], aw_delay, aw_delay + w_lag));
            label = $sformatf("outstanding.lock%0d.ar%0d.aw%0d.w%0d", block_targets[b], ar_delay,
                              aw_delay, w_lag);
            run_outstanding_pipeline(ops, label, delta);
          end
          ops.delete();
          ops.push_back(pipeline_read_op(block_read[b]));
          ops.push_back(outstanding_write(block_write[b], ar_delay, ar_delay));
          ops.push_back(pipeline_read_op(block_read[b], aw_delay));
          label =
              $sformatf("outstanding.mixed%0d.aw%0d.ar%0d", block_targets[b], ar_delay, aw_delay);
          run_outstanding_pipeline(ops, label, delta);
        end
      end
    end
    stop_activity_window();
    check_evidence(ChkAwLock, "outstanding.aw_lock_engaged",
                   64'(window_activity["xtrig_demux_aw_lock"]), 64'd1);

    // Two reads parked behind the RREADY hold, a third read stuck at a
    // register block, and a write to the same block, swept so it lands while
    // that read's response waits: the block holds two accesses.
    foreach (block_targets[b]) begin
      others.delete();
      for (int unsigned t = 0; t < OutstandingTargets; t++)
      if (t != block_targets[b]) others.push_back(t);
      foreach (OutstandingInFlightDelays[d]) begin
        pick_distinct(others.size(), 2, picks);
        ops.delete();
        foreach (picks[i])
        ops.push_back(pipeline_read_op(outstanding_word(others[picks[i]], 1'b0)));
        ops.push_back(pipeline_read_op(block_read[b]));
        ops.push_back(outstanding_write(
                      block_write[b], OutstandingInFlightDelays[d], OutstandingInFlightDelays[d]));
        label = $sformatf("outstanding.in_flight%0d.d%0d", block_targets[b],
                          OutstandingInFlightDelays[d]);
        run_outstanding_pipeline(ops, label, delta,
                                 .r_hold($urandom_range(OutstandingHoldMax, OutstandingHoldMin)));
      end
    end

    // Every AxPROT bit set and cleared, and an unmapped word with every
    // address bit above the map set, behind a mapped access on each channel;
    // then a read of every subordinate at an unaligned byte.
    ops.delete();
    ops.push_back(pipeline_read_op(config_addr, .prot(3'd0)));
    ops.push_back(pipeline_read_op(XtrigHighUnmapped, .prot(3'd7)));
    ops.push_back(outstanding_write(stretch_addr, .prot(3'd0)));
    ops.push_back(outstanding_write(XtrigHighUnmapped, .prot(3'd7)));
    ops.push_back(pipeline_read_op(config_addr, .prot(3'd0)));
    ops.push_back(outstanding_write(stretch_addr, .prot(3'd0)));
    run_outstanding_pipeline(ops, "outstanding.address_shape", delta);
    ops.delete();
    for (int unsigned t = 0; t < OutstandingTargets - 1; t++) begin
      addr = outstanding_word(t, 1'b0);
      addr += $urandom_range(3, 1);
      prot = 3'($urandom_range(7));
      ops.push_back(pipeline_read_op(addr, .prot(prot)));
    end
    run_outstanding_pipeline(ops, "outstanding.unaligned", delta);

    // The matrix and the decode-error subordinate each take a write whose W
    // trails its AW, and the matrix a second AR on the cycle after the first.
    late_w_targets = '{0, OutstandingTargets - 1};
    foreach (late_w_targets[i]) begin
      addr = outstanding_word(late_w_targets[i], 1'b1);
      ops.delete();
      ops.push_back(outstanding_write(addr, .w_valid_delay(3)));
      run_outstanding_pipeline(ops, $sformatf("outstanding.late_w%0d", late_w_targets[i]), delta);
    end
    ops.delete();
    ops.push_back(pipeline_read_op(outstanding_word(0, 1'b0)));
    ops.push_back(pipeline_read_op(outstanding_word(0, 1'b0), 1));
    run_outstanding_pipeline(ops, "outstanding.ctm_ar_pair", delta);
    ops.delete();
    for (int unsigned port = 0; port < XtrigNumCtmPorts; port++)
      ops.push_back(pipeline_write_op(ctm_config_addr(port), 32'd0));
    run_outstanding_pipeline(ops, "outstanding.ct_src_clear", delta);
  endtask

endclass : dtp_xtrig_csr_test_seq
