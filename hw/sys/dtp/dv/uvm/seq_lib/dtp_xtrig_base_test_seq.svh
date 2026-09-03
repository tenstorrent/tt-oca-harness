// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base XTRIG sequence — the SV analogue of the cocotb
// dtp_xtrig_base_test_seq helper layer. Extends the shared VIP master
// sequence (the CSR AXI-Lite stimulus surface, running on the env's XTRIG
// master sequencer) with the DTP cross-trigger layer:
//
//   * the XTRIG CSR map (CTM CT_SRC select registers, CTP config/status/
//     stretch registers) and typed write/read/check accessors,
//   * the CTM reference model (OR-of-selected-destinations routing, the
//     cocotb DtpCtmRefModel twin) cross-checked on every programmed route,
//   * the cross-trigger pin surface over dtp_tb_if (CTM src/dst req-ack
//     pairs for the internal CTs, CTP pad din/dout/en quartets), with
//     pulse drivers, masked-signal polls, width measurement, and quiet
//     windows,
//   * per-pass named evidence (CHK-XTRIG-*) through the protocol-neutral
//     ocah_checker: body() finalizes with required-ID enforcement so a
//     silently skipped check net cannot report PASS.
//
// +DTP_XTRIG_CHECKER_NEGATIVE is the documented negative-validation hook
// (the plusarg twin of the cocotb env knob): the CTM reference model is
// programmed with an INVERTED destination select so CHK-XTRIG-ROUTE-MODEL
// must fail on route scenarios, proving the model comparison gates
// pass/fail end to end.
//
// CTM register names use the RTL convention: CT_SRC[i].CT_DST_SELECT
// selects which CTM destination-input bits feed output/source port i. The
// route helpers therefore program `output_port <- input_port_mask` and log
// both the VPLAN source/destination intent and the concrete CSR mapping.

// Small CTM model matching the OR-of-selected-destinations RTL behavior
// (the cocotb DtpCtmRefModel twin).
class dtp_xtrig_ctm_ref_model;

  localparam int unsigned NumPorts = dtp_pkg::DEFAULT_NUM_CTP + dtp_pkg::DEFAULT_NUM_INT_CT;
  localparam bit [31:0] SelectMask = (32'd1 << NumPorts) - 1;

  bit [31:0] select[NumPorts];

  function new();
    foreach (select[i]) select[i] = '0;
  endfunction

  function void program_src(int unsigned src_idx, bit [31:0] dst_mask);
    select[src_idx] = dst_mask & SelectMask;
  endfunction

  function bit [31:0] route(bit [31:0] dst_value);
    bit [31:0] routed = '0;
    dst_value &= SelectMask;
    foreach (select[src_idx]) begin
      if ((dst_value & select[src_idx]) != 0) routed |= 32'd1 << src_idx;
    end
    return routed & SelectMask;
  endfunction

endclass : dtp_xtrig_ctm_ref_model

class dtp_xtrig_base_test_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(dtp_xtrig_base_test_seq)

  // ------------------------------------------------------------------
  // XTRIG geometry and CSR map (cocotb dtp_xtrig_types parity; the port
  // counts come from the RTL package).
  // ------------------------------------------------------------------
  localparam int unsigned XtrigNumCtp = dtp_pkg::DEFAULT_NUM_CTP;
  localparam int unsigned XtrigNumIntCt = dtp_pkg::DEFAULT_NUM_INT_CT;
  localparam int unsigned XtrigNumCtmPorts = XtrigNumCtp + XtrigNumIntCt;

  localparam bit [63:0] XtrigCtmBase = 64'h000;
  localparam int unsigned XtrigCtmStride = 8;
  localparam bit [63:0] XtrigCtpBase = 64'h200;
  localparam int unsigned XtrigCtpStride = 16;
  localparam bit [63:0] XtrigUnmappedBase = XtrigCtpBase + XtrigNumCtp * XtrigCtpStride;

  localparam int unsigned CtpConfigOffset = 0;
  localparam int unsigned CtpStatusOffset = 4;
  localparam int unsigned CtpStretchOffset = 8;

  localparam bit [31:0] CtpConfigModeMask = 32'h1;
  localparam bit [31:0] CtpConfigInvertMask = 32'h2;
  localparam bit [31:0] CtpConfigResetMask = 32'h4;
  localparam bit [31:0] CtpConfigMask = 32'h7;
  localparam bit [31:0] CtpStretchMask = 32'hFFFF;
  localparam bit [31:0] CtmSelectMask = (32'd1 << XtrigNumCtmPorts) - 1;

  localparam int unsigned CtpModeWireOr = 0;
  localparam int unsigned CtpModeP2p = 1;

  localparam bit [31:0] CtpStatusBusy = 32'h01;
  localparam bit [31:0] CtpStatusReqOut = 32'h10;
  localparam bit [31:0] CtpStatusAckIn = 32'h20;
  localparam bit [31:0] CtpStatusReqIn = 32'h40;
  localparam bit [31:0] CtpStatusAckOut = 32'h80;

  // Named-evidence IDs recorded by the shared helpers below.
  localparam string ChkCsr = "CHK-XTRIG-CSR";
  localparam string ChkSignal = "CHK-XTRIG-SIGNAL";
  localparam string ChkRouteModel = "CHK-XTRIG-ROUTE-MODEL";
  localparam string ChkIsolation = "CHK-XTRIG-ISOLATION";
  localparam string ChkQuiet = "CHK-XTRIG-QUIET";
  localparam string ChkStretch = "CHK-XTRIG-STRETCH";
  localparam string ChkAxil = "CHK-XTRIG-AXIL";

  localparam time SysClkPeriod = 10ns;

  // Selected by the test before start(); dispatch_scenario() switches on it.
  string scenario = "";

  // Plumbed by the test from dtp_env before start(sequencer).
  virtual dtp_tb_if tb_vif;

  // Looped-scenario contract (dtp_base_test runner parity): per-pass seed,
  // random volume, and pass index.
  int unsigned scenario_seed = 0;
  int unsigned random_count  = 5;
  int unsigned loop_index    = 0;

  // Per-pass evidence and routing model.
  ocah_checker            m_check;
  dtp_xtrig_ctm_ref_model ctm_model;
  protected bit           m_negative;

  function new(string name = "dtp_xtrig_base_test_seq");
    super.new(name);
    ctm_model = new();
  endfunction

  // Seed this body() process from the per-pass scenario seed (start()
  // forks body() in its own process, so the seed scopes to this pass).
  function void seed_scenario_rng();
    process p = process::self();
    if (p != null) p.srandom(scenario_seed);
  endfunction

  // ------------------------------------------------------------------
  // Body: seed, attach evidence, dispatch, finalize. Scenario families
  // (CSR/AXI, CTP routes, CTM routes) override dispatch_scenario().
  // ------------------------------------------------------------------
  task body();
    string ids[$];
    if (tb_vif == null) `uvm_fatal(get_type_name(), "tb_vif not plumbed by the test")
    seed_scenario_rng();
    scenario_required_ids(scenario, ids);
    attach_xtrig_checker(ids);
    dispatch_scenario();
    finalize_xtrig_checker();
  endtask

  virtual task dispatch_scenario();
    `uvm_fatal(get_type_name(), $sformatf("scenario %s not handled by this sequence family",
                                          scenario))
  endtask

  // ------------------------------------------------------------------
  // Evidence plumbing.
  // ------------------------------------------------------------------

  // Required evidence IDs per scenario: finalize() rejects a pass with
  // zero checks or a missing required ID.
  static function void scenario_required_ids(string scenario, ref string ids[$]);
    string route_ids[$] = {ChkCsr, ChkSignal, ChkRouteModel, ChkIsolation};
    ids.delete();
    case (scenario)
      "reg_stall":            ids = {ChkCsr, ChkQuiet, ChkAxil};
      "axi_channel_skew":     ids = {ChkCsr, ChkAxil};
      "axi_channel_skew_demux_aw_lock_release":     ids = {ChkAxil};
      "axi_channel_skew_read_decode_backpressure":  ids = {ChkAxil};
      "ctp_csr_sweep":        ids = {ChkCsr};
      "ctm_csr_sweep":        ids = {ChkCsr};
      "ctm_all_source_select": ids = {ChkCsr};
      "wire_or":              ids = {ChkCsr, ChkSignal, ChkStretch};
      "p2p":                  ids = {ChkCsr, ChkSignal};
      "random":               ids = {ChkCsr, ChkSignal};
      "reset":                begin ids = route_ids; ids.push_back(ChkQuiet); end
      "ctm_reset_wire_or_mode",
            "ctm_reset_p2p_mode",
            "ctm_reset_all_modes":  begin ids = route_ids; ids.push_back(ChkQuiet); end
      default:                ids = route_ids;
    endcase
  endfunction

  function void attach_xtrig_checker(string required_ids[$]);
    m_check = ocah_checker::type_id::create({get_name(), ".xtrig"});
    m_check.name_tag = "dtp_xtrig";
    m_check.required_ids = required_ids;
    m_negative = $test$plusargs("DTP_XTRIG_CHECKER_NEGATIVE");
    if (m_negative)
      `uvm_warning(get_type_name(),
                   "NEGATIVE VALIDATION: CTM reference-model selects will be inverted")
  endfunction

  function void finalize_xtrig_checker();
    if (m_check == null) `uvm_fatal(get_type_name(), "xtrig checker was never attached")
    m_check.finalize(1'b1);
  endfunction

  // Record one named evidence comparison (uvm_error on mismatch).
  function void check_evidence(string check_id, string name, bit [63:0] observed,
                               bit [63:0] expected, string context_s = "");
    void'(m_check.expect_equal(check_id, observed, expected,
                               {name, context_s.len() ? " " : "", context_s}));
  endfunction

  // ------------------------------------------------------------------
  // CSR map helpers.
  // ------------------------------------------------------------------
  static function bit [63:0] ctm_config_addr(int unsigned src_idx);
    return XtrigCtmBase + src_idx * XtrigCtmStride;
  endfunction

  static function bit [63:0] ctp_config_addr(int unsigned ctp_idx);
    return XtrigCtpBase + ctp_idx * XtrigCtpStride + CtpConfigOffset;
  endfunction

  static function bit [63:0] ctp_status_addr(int unsigned ctp_idx);
    return XtrigCtpBase + ctp_idx * XtrigCtpStride + CtpStatusOffset;
  endfunction

  static function bit [63:0] ctp_stretch_addr(int unsigned ctp_idx);
    return XtrigCtpBase + ctp_idx * XtrigCtpStride + CtpStretchOffset;
  endfunction

  // CTM port numbering: external CTP[i] occupies port i, internal CT[i]
  // occupies port XtrigNumCtp + i.
  static function int unsigned external_ctp_port(int unsigned ctp_idx);
    return ctp_idx;
  endfunction

  static function int unsigned internal_ct_port(int unsigned int_idx);
    return XtrigNumCtp + int_idx;
  endfunction

  static function bit is_ctp_port(int unsigned port);
    return port < XtrigNumCtp;
  endfunction

  static function int unsigned int_idx_from_port(int unsigned port);
    return port - XtrigNumCtp;
  endfunction

  static function bit [31:0] ports_mask(int unsigned ports[$]);
    bit [31:0] mask = '0;
    foreach (ports[i]) mask |= 32'd1 << ports[i];
    return mask & CtmSelectMask;
  endfunction

  // Project a full CTM-port mask into the external-CTP / internal-CT
  // pin vectors.
  static function bit [31:0] project_ctp_mask(bit [31:0] ctm_mask);
    return ctm_mask & ((32'd1 << XtrigNumCtp) - 1);
  endfunction

  static function bit [31:0] project_internal_mask(bit [31:0] ctm_mask);
    return (ctm_mask >> XtrigNumCtp) & ((32'd1 << XtrigNumIntCt) - 1);
  endfunction

  static function bit [31:0] pack_ctp_config(int unsigned mode = CtpModeWireOr, bit invert = 1'b0,
                                             bit rst = 1'b0);
    return (32'(mode) & 32'h1) | (32'(invert) << 1) | (32'(rst) << 2);
  endfunction

  // Apply AXI-Lite byte strobes to a 32-bit word.
  static function bit [31:0] apply_wstrb(bit [31:0] old_value, bit [31:0] new_value,
                                         bit [3:0] wstrb);
    bit [31:0] merged = old_value;
    for (int unsigned byte_idx = 0; byte_idx < 4; byte_idx++) begin
      if (wstrb[byte_idx])
        merged = (merged & ~(32'hFF << (8 * byte_idx))) | (new_value & (32'hFF << (8 * byte_idx)));
    end
    return merged;
  endfunction

  // ------------------------------------------------------------------
  // CSR accessors (the master-sequence write/read already escalate a
  // non-OKAY response to uvm_error, mirroring the cocotb BRESP asserts).
  // ------------------------------------------------------------------
  task csr_write(bit [63:0] addr, bit [31:0] data, bit [3:0] wstrb = 4'hF, string label = "");
    ocah_axi_resp_e resp;
    write(addr, 64'(data), resp, '0, 8'(wstrb));
    `uvm_info(get_type_name(),
              $sformatf("XTRIG CSR WRITE %-34s addr=0x%03h data=0x%08h wstrb=0x%h resp=%s", label,
                        addr, data, wstrb, resp.name()), UVM_MEDIUM)
  endtask

  task csr_read(bit [63:0] addr, output bit [31:0] data, input string label = "");
    bit [63:0] data64;
    read(addr, data64);
    data = data64[31:0];
    `uvm_info(get_type_name(), $sformatf("XTRIG CSR READ  %-34s addr=0x%03h data=0x%08h", label,
                                         addr, data), UVM_MEDIUM)
  endtask

  task write_read_check(bit [63:0] addr, bit [31:0] data, bit [31:0] expected,
                        bit [3:0] wstrb = 4'hF, bit [31:0] mask = 32'hFFFF_FFFF, string label = "");
    bit [31:0] observed;
    csr_write(addr, data, wstrb, label);
    csr_read(addr, observed, label);
    check_evidence(ChkCsr, label.len() ? label : $sformatf("csr_0x%0h", addr), 64'(observed & mask),
                   64'(expected & mask), $sformatf("addr=0x%03h wstrb=0x%h", addr, wstrb));
  endtask

  task program_ctp(int unsigned ctp_idx, int unsigned mode = CtpModeWireOr, bit invert = 1'b0,
                   bit rst = 1'b0, bit [15:0] stretch = '0);
    bit [31:0] cfg_word = pack_ctp_config(mode, invert, rst);
    `uvm_info(get_type_name(),
              $sformatf("Configure CTP[%0d]: mode=%s invert=%0d reset=%0d stretch=%0d", ctp_idx,
                        mode == CtpModeP2p ? "p2p" : "wire_or", invert, rst, stretch), UVM_MEDIUM)
    write_read_check(ctp_config_addr(ctp_idx), cfg_word, cfg_word, 4'hF, CtpConfigMask, $sformatf(
                     "ctp%0d.config", ctp_idx));
    write_read_check(ctp_stretch_addr(ctp_idx), 32'(stretch), 32'(stretch), 4'hF, CtpStretchMask,
                     $sformatf("ctp%0d.stretch", ctp_idx));
  endtask

  task program_ctm_src(int unsigned output_port, bit [31:0] input_mask);
    bit [31:0] model_mask;
    input_mask &= CtmSelectMask;
    model_mask = input_mask;
    // Negative-validation hook: program the reference model with an
    // INVERTED select so CHK-XTRIG-ROUTE-MODEL must fail (route
    // scenarios only), proving the model comparison gates pass/fail.
    if (m_negative) begin
      model_mask = (~input_mask) & CtmSelectMask;
      `uvm_warning(get_type_name(),
                   $sformatf("NEGATIVE VALIDATION: CTM model select 0x%0h instead of 0x%0h",
                             model_mask, input_mask))
    end
    ctm_model.program_src(output_port, model_mask);
    write_read_check(ctm_config_addr(output_port), input_mask, input_mask, 4'hF, CtmSelectMask,
                     $sformatf("ctm.output%0d.select", output_port));
  endtask

  task clear_ctm_routes();
    ctm_model = new();
    for (int unsigned src_idx = 0; src_idx < XtrigNumCtmPorts; src_idx++)
      csr_write(ctm_config_addr(src_idx), '0, 4'hF, $sformatf("clear.ctm%0d", src_idx));
  endtask

  task clear_xtrig();
    clear_xtrig_inputs();
    for (int unsigned ctp_idx = 0; ctp_idx < XtrigNumCtp; ctp_idx++) begin
      csr_write(ctp_config_addr(ctp_idx), '0, 4'hF, $sformatf("cleanup.ctp%0d.cfg", ctp_idx));
      csr_write(ctp_stretch_addr(ctp_idx), '0, 4'hF, $sformatf("cleanup.ctp%0d.stretch", ctp_idx));
    end
    clear_ctm_routes();
  endtask

  // ------------------------------------------------------------------
  // Cross-trigger pin surface over dtp_tb_if.
  // ------------------------------------------------------------------
  task wait_sys_cycles(int unsigned cycles);
    #(cycles * SysClkPeriod);
  endtask

  task clear_xtrig_inputs();
    tb_vif.xtrig_ctm_src_ack     <= '0;
    tb_vif.xtrig_ctm_dst_req     <= '0;
    tb_vif.xtrig_ctp_req_out_din <= '0;
    tb_vif.xtrig_ctp_req_in_din  <= '0;
    tb_vif.xtrig_ctp_ack_in_din  <= '0;
    tb_vif.xtrig_ctp_ack_out_din <= '0;
    wait_sys_cycles(1);
  endtask

  // Named cross-trigger observable read (zero-extended to 32 bits).
  function bit [31:0] xtrig_pin(string name);
    case (name)
      "xtrig_ctm_src_req":         return 32'(tb_vif.xtrig_ctm_src_req);
      "xtrig_ctm_dst_ack":         return 32'(tb_vif.xtrig_ctm_dst_ack);
      "xtrig_ctm_src_ack":         return 32'(tb_vif.xtrig_ctm_src_ack);
      "xtrig_ctm_dst_req":         return 32'(tb_vif.xtrig_ctm_dst_req);
      "xtrig_ctp_req_out_dout":    return 32'(tb_vif.xtrig_ctp_req_out_dout);
      "xtrig_ctp_req_out_dout_en": return 32'(tb_vif.xtrig_ctp_req_out_dout_en);
      "xtrig_ctp_req_out_din":     return 32'(tb_vif.xtrig_ctp_req_out_din);
      "xtrig_ctp_req_out_din_en":  return 32'(tb_vif.xtrig_ctp_req_out_din_en);
      "xtrig_ctp_req_in_dout":     return 32'(tb_vif.xtrig_ctp_req_in_dout);
      "xtrig_ctp_req_in_dout_en":  return 32'(tb_vif.xtrig_ctp_req_in_dout_en);
      "xtrig_ctp_req_in_din":      return 32'(tb_vif.xtrig_ctp_req_in_din);
      "xtrig_ctp_req_in_din_en":   return 32'(tb_vif.xtrig_ctp_req_in_din_en);
      "xtrig_ctp_ack_in_dout":     return 32'(tb_vif.xtrig_ctp_ack_in_dout);
      "xtrig_ctp_ack_in_dout_en":  return 32'(tb_vif.xtrig_ctp_ack_in_dout_en);
      "xtrig_ctp_ack_in_din":      return 32'(tb_vif.xtrig_ctp_ack_in_din);
      "xtrig_ctp_ack_in_din_en":   return 32'(tb_vif.xtrig_ctp_ack_in_din_en);
      "xtrig_ctp_ack_out_dout":    return 32'(tb_vif.xtrig_ctp_ack_out_dout);
      "xtrig_ctp_ack_out_dout_en": return 32'(tb_vif.xtrig_ctp_ack_out_dout_en);
      "xtrig_ctp_ack_out_din":     return 32'(tb_vif.xtrig_ctp_ack_out_din);
      "xtrig_ctp_ack_out_din_en":  return 32'(tb_vif.xtrig_ctp_ack_out_din_en);
      "xtrig_axil_awvalid_count":  return tb_vif.xtrig_axil_awvalid_count;
      "xtrig_axil_wvalid_count":   return tb_vif.xtrig_axil_wvalid_count;
      "xtrig_axil_arvalid_count":  return tb_vif.xtrig_axil_arvalid_count;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown xtrig observable %s", name))
        return '0;
      end
    endcase
  endfunction

  function void log_xtrig_sample(string label);
    `uvm_info(get_type_name(), $sformatf(
              "XTRIG SAMPLE %-28s ctm_src_req=0x%03h req_out_en=0x%04h req_out=0x%04h ack_out=0x%04h",
              label,
              xtrig_pin(
                  "xtrig_ctm_src_req"
              ),
              xtrig_pin(
                  "xtrig_ctp_req_out_dout_en"
              ),
              xtrig_pin(
                  "xtrig_ctp_req_out_dout"
              ),
              xtrig_pin(
                  "xtrig_ctp_ack_out_dout"
              )
              ), UVM_MEDIUM)
  endfunction

  task drive_internal_dst_pulse(int unsigned int_idx, int unsigned cycles = 1);
    tb_vif.xtrig_ctm_dst_req <= tb_vif.xtrig_ctm_dst_req | (XtrigNumIntCt'(1) << int_idx);
    wait_sys_cycles(cycles);
    tb_vif.xtrig_ctm_dst_req <= tb_vif.xtrig_ctm_dst_req & ~(XtrigNumIntCt'(1) << int_idx);
  endtask

  task drive_ctp_req_out_din_pulse(int unsigned ctp_idx, int unsigned cycles = 2);
    tb_vif.xtrig_ctp_req_out_din <= tb_vif.xtrig_ctp_req_out_din | (XtrigNumCtp'(1) << ctp_idx);
    wait_sys_cycles(cycles);
    tb_vif.xtrig_ctp_req_out_din <= tb_vif.xtrig_ctp_req_out_din & ~(XtrigNumCtp'(1) << ctp_idx);
  endtask

  task drive_ctp_p2p_req_in(int unsigned ctp_idx, bit value);
    if (value)
      tb_vif.xtrig_ctp_req_in_din <= tb_vif.xtrig_ctp_req_in_din | (XtrigNumCtp'(1) << ctp_idx);
    else tb_vif.xtrig_ctp_req_in_din <= tb_vif.xtrig_ctp_req_in_din & ~(XtrigNumCtp'(1) << ctp_idx);
    wait_sys_cycles(1);
  endtask

  task drive_ctp_p2p_ack_in(int unsigned ctp_idx, bit value);
    if (value)
      tb_vif.xtrig_ctp_ack_in_din <= tb_vif.xtrig_ctp_ack_in_din | (XtrigNumCtp'(1) << ctp_idx);
    else tb_vif.xtrig_ctp_ack_in_din <= tb_vif.xtrig_ctp_ack_in_din & ~(XtrigNumCtp'(1) << ctp_idx);
    wait_sys_cycles(1);
  endtask

  task drive_ctp_ack_in_mask(bit [31:0] mask, int unsigned cycles = 3);
    tb_vif.xtrig_ctp_ack_in_din <= XtrigNumCtp'(mask);
    wait_sys_cycles(cycles);
    tb_vif.xtrig_ctp_ack_in_din <= '0;
  endtask

  task pulse_ctm_dst_req(bit [31:0] mask, int unsigned cycles = 1);
    tb_vif.xtrig_ctm_dst_req <= XtrigNumIntCt'(mask);
    wait_sys_cycles(cycles);
    tb_vif.xtrig_ctm_dst_req <= '0;
  endtask

  task pulse_ctm_src_ack(bit [31:0] mask, int unsigned cycles = 1);
    tb_vif.xtrig_ctm_src_ack <= XtrigNumIntCt'(mask);
    wait_sys_cycles(cycles);
    tb_vif.xtrig_ctm_src_ack <= '0;
  endtask

  // Pulse system reset while the cross-trigger inputs idle (the cocotb
  // pulse_reset twin; POR and TRST stay released).
  task pulse_reset(int unsigned cycles = 3);
    clear_xtrig_inputs();
    tb_vif.sys_rst_n <= 1'b0;
    wait_sys_cycles(cycles);
    tb_vif.sys_rst_n <= 1'b1;
    wait_sys_cycles(cycles + 2);
  endtask

  // Consecutive-cycle width of the first observed masked pulse.
  task measure_mask_width(input string name, input bit [31:0] mask, output int unsigned width,
                          input int unsigned timeout_cycles = 80);
    bit started = 1'b0;
    width = 0;
    for (int unsigned c = 0; c < timeout_cycles; c++) begin
      bit active = (xtrig_pin(name) & mask) != 0;
      if (active) begin
        width++;
        started = 1'b1;
      end else if (started) return;
      wait_sys_cycles(1);
    end
  endtask

  // Poll a masked observable until it matches (bounded), then record
  // CHK-XTRIG-SIGNAL on the final sample.
  task wait_signal_mask(string name, bit [31:0] mask, bit [31:0] expected, int unsigned cycles = 60,
                        string label = "");
    bit [31:0] observed = '0;
    for (int unsigned c = 0; c < cycles; c++) begin
      observed = xtrig_pin(name) & mask;
      wait_sys_cycles(1);
      if (observed == (expected & mask)) break;
    end
    check_evidence(ChkSignal, {name, ".mask"}, 64'(observed), 64'(expected & mask), label);
  endtask

  // Quiet window: the request/acknowledge observables must show zero
  // activity for the window (CHK-XTRIG-QUIET).
  task check_quiet(string label, int unsigned cycles = 4);
    string names[$] = {"xtrig_ctm_src_req", "xtrig_ctm_dst_ack",
                           "xtrig_ctp_req_out_dout_en",
                           "xtrig_ctp_ack_out_dout_en"};
    bit [31:0] activity[string];
    foreach (names[i]) activity[names[i]] = '0;
    for (int unsigned c = 0; c < cycles; c++) begin
      foreach (names[i]) activity[names[i]] |= xtrig_pin(names[i]);
      wait_sys_cycles(1);
    end
    foreach (names[i])
      check_evidence(ChkQuiet, $sformatf("quiet.%s.%s", label, names[i]), 64'(activity[names[i]]),
                     64'd0, $sformatf("cycles=%0d", cycles));
  endtask

  // ------------------------------------------------------------------
  // Route programming and verification.
  // ------------------------------------------------------------------
  task configure_ctp_mode_for_port(int unsigned port, int unsigned mode,
                                   bit [15:0] stretch = 16'd1);
    if (is_ctp_port(port)) program_ctp(port, mode, 1'b0, 1'b0, stretch);
  endtask

  task configure_ctp_modes_for_route(int unsigned input_port, bit [31:0] output_mask,
                                     int unsigned mode);
    configure_ctp_mode_for_port(input_port, mode, 16'd1);
    for (int unsigned port = 0; port < XtrigNumCtmPorts; port++) begin
      if (output_mask[port]) configure_ctp_mode_for_port(port, mode, 16'd1);
    end
  endtask

  task program_route(int unsigned input_port, bit [31:0] output_mask, string label);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "Program CTM route %-20s input_port=%0d output_mask=0x%08h (CSR output selects input)",
            label, input_port, output_mask), UVM_MEDIUM)
    clear_ctm_routes();
    for (int unsigned output_port = 0; output_port < XtrigNumCtmPorts; output_port++) begin
      if (output_mask[output_port]) program_ctm_src(output_port, 32'd1 << input_port);
    end
  endtask

  task drive_input_port(int unsigned input_port, int unsigned mode, int unsigned cycles = 2);
    if (is_ctp_port(input_port)) begin
      if (mode == CtpModeP2p) begin
        drive_ctp_p2p_req_in(input_port, 1'b1);
        wait_sys_cycles(cycles);
        drive_ctp_p2p_req_in(input_port, 1'b0);
      end else drive_ctp_req_out_din_pulse(input_port, cycles);
    end else drive_internal_dst_pulse(int_idx_from_port(input_port), cycles);
  endtask

  task check_output_mask(bit [31:0] output_mask, int unsigned mode, string label);
    bit [31:0] ctp_outputs = project_ctp_mask(output_mask);
    bit [31:0] int_outputs = project_internal_mask(output_mask);
    if (ctp_outputs != 0) begin
      string sig = (mode == CtpModeP2p) ? "xtrig_ctp_req_out_dout" : "xtrig_ctp_req_out_dout_en";
      wait_signal_mask(sig, ctp_outputs, ctp_outputs, 60, {label, ".ctp"});
      if (mode == CtpModeP2p) drive_ctp_ack_in_mask(ctp_outputs, 3);
    end
    if (int_outputs != 0)
      wait_signal_mask("xtrig_ctm_src_req", int_outputs, int_outputs, 60, {label, ".internal"});
    // Negative check: after the event drains, no unselected-output
    // residue may remain (CHK-XTRIG-ISOLATION).
    wait_sys_cycles(6);
    log_xtrig_sample({label, ".post"});
    check_evidence(ChkIsolation, {label, ".unselected_internal_quiet"}, 64'(xtrig_pin(
                   "xtrig_ctm_src_req") & ~int_outputs), 64'd0);
  endtask

  task verify_route(int unsigned input_port, bit [31:0] output_mask, int unsigned mode,
                    string label);
    bit [31:0] predicted;
    configure_ctp_modes_for_route(input_port, output_mask, mode);
    program_route(input_port, output_mask, label);
    // Reference-model cross-check: the CTM model programmed alongside
    // the CSRs must predict exactly the outputs this route intends to
    // fire. +DTP_XTRIG_CHECKER_NEGATIVE corrupts the model so this
    // must fail.
    predicted = ctm_model.route(32'd1 << input_port);
    check_evidence(ChkRouteModel, {label, ".model_route"}, 64'(predicted),
                   64'(output_mask & CtmSelectMask), $sformatf("input_port=%0d", input_port));
    clear_xtrig_inputs();
    wait_sys_cycles(2);
    drive_input_port(input_port, mode);
    check_output_mask(output_mask, mode, label);
  endtask

  task check_all_ctm_cleared(string label);
    bit [31:0] observed;
    for (int unsigned src_idx = 0; src_idx < XtrigNumCtmPorts; src_idx++) begin
      csr_read(ctm_config_addr(src_idx), observed, $sformatf("%s.ctm%0d", label, src_idx));
      if ((observed & CtmSelectMask) != 0)
        `uvm_error("xtrig_reset_chk", $sformatf(
                   "%s.ctm%0d.default: select 0x%0h not cleared by reset",
                   label,
                   src_idx,
                   observed & CtmSelectMask
                   ))
    end
  endtask

  // ------------------------------------------------------------------
  // Seeded-draw helpers (cocotb rng.sample/choice parity on the process
  // RNG seeded by seed_scenario_rng()).
  // ------------------------------------------------------------------

  // k distinct draws from 0..n-1 (Fisher-Yates prefix).
  function void pick_distinct(int unsigned n, int unsigned k, ref int unsigned out[$]);
    int unsigned pool[$];
    out.delete();
    for (int unsigned i = 0; i < n; i++) pool.push_back(i);
    for (int unsigned i = 0; i < k; i++) begin
      int unsigned j = i + $urandom_range(n - 1 - i);
      int unsigned tmp = pool[i];
      pool[i] = pool[j];
      pool[j] = tmp;
      out.push_back(pool[i]);
    end
  endfunction

  // One draw from a pool.
  function int unsigned pick_one(int unsigned pool[$]);
    return pool[$urandom_range(pool.size()-1)];
  endfunction

  // CTM port pool by class ("ctp", "internal", "all").
  static function void port_pool(string port_class, ref int unsigned pool[$]);
    pool.delete();
    case (port_class)
      "ctp":
                for (int unsigned i = 0; i < XtrigNumCtp; i++)
                    pool.push_back(i);
      "internal":
                for (int unsigned i = 0; i < XtrigNumIntCt; i++)
                    pool.push_back(internal_ct_port(i));
      default:
                for (int unsigned i = 0; i < XtrigNumCtmPorts; i++)
                    pool.push_back(i);
    endcase
  endfunction

endclass : dtp_xtrig_base_test_seq
