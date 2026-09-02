// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// XTRIG CSR and AXI-Lite channel-shape scenarios — the SV analogue of the
// CSR/AXI scenario set in the cocotb dtp_xtrig_base_test_seq. One
// parameterized sequence, dispatched on `scenario`:
//
//   reg_stall        accepted-path CSR writes/reads with quiet cross-trigger
//                    pins and nonzero request-activity counters (the local
//                    regblock stall path is structurally unreachable)
//   ctp_csr_sweep    exhaustive CTP config patterns, stretch values, and a
//                    byte-strobe merge on every CTP, in seeded order
//   ctm_csr_sweep    deterministic + seeded CT_DST_SELECT patterns and a
//                    byte-lane merge on every CTM source register
//   ctm_all_source_select  per-source select masks with neighbor
//                    no-aliasing reads
//   axi_channel_skew                       AW-first and W-first skewed
//                    writes, deferred BREADY, and an RREADY-hold read with
//                    data-stability evidence
//   axi_channel_skew_demux_aw_lock_release three skewed writes across CTP
//                    and CTM registers proving the demux AW lock releases
//   axi_channel_skew_read_decode_backpressure unmapped reads return DECERR
//                    with stable RDATA/RRESP under RREADY backpressure

class dtp_xtrig_csr_test_seq extends dtp_xtrig_base_test_seq;
  `uvm_object_utils(dtp_xtrig_csr_test_seq)

  function new(string name = "dtp_xtrig_csr_test_seq");
    super.new(name);
  endfunction

  virtual task dispatch_scenario();
    case (scenario)
      "reg_stall":                                 run_reg_stall();
      "ctp_csr_sweep":                             run_ctp_csr_sweep();
      "ctm_csr_sweep":                             run_ctm_csr_sweep();
      "ctm_all_source_select":                     run_ctm_all_source_select();
      "axi_channel_skew":                          run_axi_channel_skew();
      "axi_channel_skew_demux_aw_lock_release":    run_demux_aw_lock_release();
      "axi_channel_skew_read_decode_backpressure": run_read_decode_backpressure();
      default:                                     super.dispatch_scenario();
    endcase
  endtask

  protected task run_reg_stall();
    bit [15:0] stretch = 16'($urandom);
    bit [31:0] select = $urandom_range(CtmSelectMask, 1);
    `uvm_info(get_type_name(), "XTRIG accepted-path CSR access and stall rationale", UVM_LOW)
    write_read_check(ctp_config_addr(0), pack_ctp_config(.invert(1'b1)), pack_ctp_config(
                     .invert(1'b1)), 4'hF, CtpConfigMask, "regstall.ctp0.config");
    write_read_check(ctp_stretch_addr(0), 32'(stretch), 32'(stretch), 4'hF, CtpStretchMask,
                     "regstall.ctp0.stretch");
    write_read_check(ctm_config_addr(0), select, select, 4'hF, CtmSelectMask, "regstall.ctm0");
    check_quiet("reg_stall_accepted");
    check_evidence(ChkAxil, "regstall.awvalid_count_nonzero", 64'(xtrig_pin(
                   "xtrig_axil_awvalid_count") > 0), 64'd1);
    check_evidence(ChkAxil, "regstall.arvalid_count_nonzero", 64'(xtrig_pin(
                   "xtrig_axil_arvalid_count") > 0), 64'd1);
  endtask

  protected task run_ctp_csr_sweep();
    bit [31:0] patterns[4];
    bit [31:0] stretch_values[5];
    bit [31:0] base_cfg, byte_new, expected;
    `uvm_info(get_type_name(), "XTRIG CTP deterministic CSR and byte-strobe sweep", UVM_LOW)
    patterns[0] = pack_ctp_config(CtpModeWireOr);
    patterns[1] = pack_ctp_config(CtpModeWireOr, 1'b1);
    patterns[2] = pack_ctp_config(CtpModeP2p);
    patterns[3] = pack_ctp_config(CtpModeP2p, 1'b1, 1'b1);
    // Seeded per-pass order and an extra random stretch value: the sweep
    // stays exhaustive while each loop exercises different write orders.
    for (int unsigned i = 3; i > 0; i--) begin
      int unsigned j = $urandom_range(i);
      bit [31:0] tmp = patterns[i];
      patterns[i] = patterns[j];
      patterns[j] = tmp;
    end
    stretch_values = '{32'h0, 32'h1, 32'h55AA, 32'hFFFF, 32'(16'($urandom))};
    for (int unsigned ctp_idx = 0; ctp_idx < XtrigNumCtp; ctp_idx++) begin
      foreach (patterns[pat_idx]) begin
        `uvm_info(get_type_name(), $sformatf(
                  "Iteration %0d/%0d: CTP[%0d] cfg=0x%0h",
                  ctp_idx * 4 + pat_idx + 1,
                  XtrigNumCtp * 4,
                  ctp_idx,
                  patterns[pat_idx]
                  ), UVM_LOW)
        write_read_check(ctp_config_addr(ctp_idx), patterns[pat_idx], patterns[pat_idx], 4'hF,
                         CtpConfigMask, $sformatf("ctp%0d.cfg%0d", ctp_idx, pat_idx));
      end
      foreach (stretch_values[s])
      write_read_check(ctp_stretch_addr(ctp_idx), stretch_values[s], stretch_values[s], 4'hF,
                       CtpStretchMask, $sformatf(
                       "ctp%0d.stretch%04h", ctp_idx, stretch_values[s][15:0]));
      base_cfg = pack_ctp_config(CtpModeWireOr);
      csr_write(ctp_config_addr(ctp_idx), base_cfg, 4'hF, $sformatf("ctp%0d.byte_base", ctp_idx));
      byte_new = pack_ctp_config(CtpModeP2p, 1'b1);
      expected = apply_wstrb(base_cfg, byte_new, 4'h1);
      write_read_check(ctp_config_addr(ctp_idx), byte_new, expected, 4'h1, CtpConfigMask, $sformatf(
                       "ctp%0d.byte0", ctp_idx));
    end
  endtask

  protected task run_ctm_csr_sweep();
    bit [31:0] patterns[$];
    bit [31:0] old_mask, new_mask, expected;
    `uvm_info(get_type_name(), "CTM deterministic CSR byte-strobe and mask sweep", UVM_LOW)
    // Seeded per-pass extra pattern and byte-strobe payloads on top of
    // the deterministic sweep.
    patterns = {
      32'h0,
      32'h1,
      32'd1 << external_ctp_port(0),
      32'd1 << internal_ct_port(0),
      CtmSelectMask,
      32'h0155_AA55 & CtmSelectMask,
      $urandom_range(CtmSelectMask, 1)
    };
    for (int unsigned src_idx = 0; src_idx < XtrigNumCtmPorts; src_idx++) begin
      foreach (patterns[pat_idx])
      write_read_check(ctm_config_addr(src_idx), patterns[pat_idx], patterns[pat_idx], 4'hF,
                       CtmSelectMask, $sformatf("ctm%0d.pat%0d", src_idx, pat_idx));
      old_mask = 32'(8'($urandom));
      new_mask = 32'(8'($urandom)) << 8;
      program_ctm_src(src_idx, old_mask);
      expected = apply_wstrb(old_mask, new_mask, 4'h2) & CtmSelectMask;
      write_read_check(ctm_config_addr(src_idx), new_mask, expected, 4'h2, CtmSelectMask, $sformatf(
                       "ctm%0d.byte1", src_idx));
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
      nbr_idx  = (src_idx + 1) % XtrigNumCtmPorts;
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
      if ((after_neighbor & CtmSelectMask) !== (before_neighbor & CtmSelectMask))
        `uvm_error("xtrig_csr_chk", $sformatf(
                   "allsrc%0d.neighbor_no_alias: neighbor CT_SRC[%0d] moved 0x%0h -> 0x%0h",
                   src_idx,
                   nbr_idx,
                   before_neighbor & CtmSelectMask,
                   after_neighbor & CtmSelectMask
                   ))
    end
  endtask

  protected task run_axi_channel_skew();
    bit [15:0] d1 = 16'($urandom);
    bit [15:0] d2 = 16'($urandom);
    bit [15:0] d3 = 16'($urandom);
    bit [63:0] addr = ctp_stretch_addr($urandom_range(XtrigNumCtp - 1));
    bit [31:0] observed;
    ocah_axi_item res;
    `uvm_info(get_type_name(), "XTRIG manual AXI-Lite AW/W and RREADY skew", UVM_LOW)
    // Seeded per-pass payloads and skew timing: each loop exercises the
    // channel-skew paths with different data, gaps, and READY delays.
    write_skewed_result(addr, 64'(d1), res, .w_valid_delay($urandom_range(7, 3)),
                        .b_ready_delay($urandom_range(4, 1)));
    check_evidence(ChkAxil, "axi_skew.aw_before_w.bresp", 64'(res.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    write_read_check(addr, 32'(d2), 32'(d2), 4'hF, CtpStretchMask, "axi_skew.normal_after_aw");
    write_skewed_result(addr, 64'(d3), res, .aw_valid_delay($urandom_range(7, 3)),
                        .b_ready_delay($urandom_range(4, 1)));
    check_evidence(ChkAxil, "axi_skew.w_before_aw.bresp", 64'(res.worst_resp()),
                   64'(OCAH_AXI_RESP_OKAY));
    csr_read(addr, observed, "axi_skew.final_read");
    check_evidence(ChkAxil, "axi_skew.final_stretch", 64'(observed & CtpStretchMask), 64'(d3));
    read_hold_result(addr, $urandom_range(7, 3), res);
    check_evidence(ChkAxil, "axi_skew.rresp", 64'(res.worst_resp()), 64'(OCAH_AXI_RESP_OKAY));
    check_evidence(ChkAxil, "axi_skew.rstable", 64'(res.hold_stable), 64'd1);
    check_evidence(ChkAxil, "axi_skew.rdata", 64'(res.first_data() & CtpStretchMask), 64'(d3));
  endtask

  protected task run_demux_aw_lock_release();
    bit [63:0] case_addr    [3];
    bit [31:0] case_data    [3];
    bit        case_aw_first[3];
    bit [31:0] observed, mask;
    int unsigned  picks[$];
    ocah_axi_item res;
    `uvm_info(get_type_name(), "XTRIG AXI-Lite demux AW-lock release", UVM_LOW)
    // Seeded per-pass targets, payloads, and skew timing.
    pick_distinct(XtrigNumCtp, 2, picks);
    case_addr[0]     = ctp_config_addr(picks[0]);
    case_data[0]     = pack_ctp_config($urandom_range(1), bit'($urandom_range(1)));
    case_aw_first[0] = 1'b1;
    case_addr[1]     = ctp_config_addr(picks[1]);
    case_data[1]     = pack_ctp_config($urandom_range(1), bit'($urandom_range(1)));
    case_aw_first[1] = 1'b1;
    case_addr[2]     = ctm_config_addr($urandom_range(XtrigNumCtmPorts - 1));
    case_data[2]     = $urandom_range(CtmSelectMask, 1);
    case_aw_first[2] = 1'b0;
    foreach (case_addr[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/3: addr=0x%0h data=0x%0h aw_first=%0d",
                idx + 1,
                case_addr[idx],
                case_data[idx],
                case_aw_first[idx]
                ), UVM_LOW)
      write_skewed_result(case_addr[idx], 64'(case_data[idx]), res,
                          .aw_valid_delay(case_aw_first[idx] ? 0 : $urandom_range(8, 4)),
                          .w_valid_delay(case_aw_first[idx] ? $urandom_range(8, 4) : 0),
                          .b_ready_delay($urandom_range(4, 1)));
      check_evidence(ChkAxil, $sformatf("demux_aw_lock.%0d.bresp", idx + 1), 64'(res.worst_resp()),
                     64'(OCAH_AXI_RESP_OKAY));
      csr_read(case_addr[idx], observed, $sformatf("demux_aw_lock.%0d.readback", idx + 1));
      mask = (case_addr[idx] >= XtrigCtpBase) ? CtpConfigMask : CtmSelectMask;
      check_evidence(ChkAxil, $sformatf("demux_aw_lock.%0d.readback", idx + 1),
                     64'(observed & mask), 64'(case_data[idx] & mask));
    end
  endtask

  protected task run_read_decode_backpressure();
    int unsigned offs[$];
    bit [63:0] addr;
    ocah_axi_item res;
    `uvm_info(get_type_name(), "XTRIG AXI-Lite read decode backpressure", UVM_LOW)
    // Seeded per-pass unmapped offsets and RREADY hold width.
    pick_distinct('h40, 2, offs);
    offs.sort();
    foreach (offs[idx]) begin
      addr = XtrigUnmappedBase + offs[idx] * 4;
      read_hold_result(addr, $urandom_range(8, 4), res, .check_response(1'b0));
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/2: unmapped addr=0x%0h data=0x%0h resp=%s stable=%0d",
                idx + 1,
                addr,
                res.first_data(),
                res.worst_resp().name(),
                res.hold_stable
                ), UVM_LOW)
      check_evidence(ChkAxil, $sformatf("read_decode.%0d.resp", idx + 1), 64'(res.worst_resp()),
                     64'(OCAH_AXI_RESP_DECERR));
      check_evidence(ChkAxil, $sformatf("read_decode.%0d.stable", idx + 1), 64'(res.hold_stable),
                     64'd1);
    end
  endtask

endclass : dtp_xtrig_csr_test_seq
