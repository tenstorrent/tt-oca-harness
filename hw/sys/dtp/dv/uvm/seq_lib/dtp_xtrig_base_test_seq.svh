// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base XTRIG sequence — the SV analogue of the cocotb
// dtp_xtrig_base_test_seq helper layer. A virtual sequence on the DTP
// virtual sequencer whose CSR accesses are reusable AXI-Lite operations
// (dtp_axi_csr_write_seq / dtp_axi_csr_read_seq / dtp_axi_csr_pipeline_seq)
// started on the XTRIG master sequencer handle, with the DTP cross-trigger
// layer on top:
//
//   * the XTRIG CSR map (dtp_types: CTM CT_SRC select registers, CTP
//     config/status/stretch registers) and typed write/read/check accessors,
//     including the two-outstanding write and read pairs and pipelined
//     accesses with several in flight,
//   * the CTM routing model (env dtp_xtrig_ctm_model, the cocotb
//     DtpCtmRefModel twin) compared against the DUT output vector on every
//     programmed route,
//   * the cross-trigger pin surface over dtp_xtrig_if (CTM src/dst req-ack
//     pairs for the internal CTs, CTP pad din/dout/en quartets), with
//     polarity-aware pulse drivers, masked-signal polls, width measurement,
//     activity windows, and the reset window,
//   * per-pass named evidence (CHK-XTRIG-*) through the protocol-neutral
//     ocah_checker: body() finalizes with required-ID enforcement so a
//     silently skipped check net cannot report PASS.
//
// test_cfg.xtrig_checker_negative (+DTP_XTRIG_CHECKER_NEGATIVE) is the
// documented negative-validation hook: the CTM reference model is
// programmed with an INVERTED destination select so CHK-XTRIG-ROUTE-MODEL
// must fail on route scenarios, proving the model comparison gates
// pass/fail end to end.
//
// CT_SRC[k].CONFIG_0.CT_DST_SELECT (cross_trigger_matrix.rdl) selects the
// CT_Dst input ports whose pulses are OR'd onto CT_Src output k: CT_Src ports
// are matrix outputs, CT_Dst ports are matrix inputs. The route helpers
// therefore program `output_port <- input_port_mask` and log both the VPLAN
// source/destination intent and the concrete CSR mapping.
//
// Pad polarity follows CONFIG.INVERT. Point-to-point request and acknowledge
// pads of an inverted CTP idle high and assert low, so every such pad the
// sequences drive goes through pad_level(). A wire-OR pad sits on the bench's
// open-drain shared wire: the wire rests at the pull of the board built for
// the CTP's sense (DtpWireOrPull, high for INVERT=0) and a chiplet driver
// pulls it to the asserted level, so the sequences never drive that pad's
// level; the port receives a trigger DtpCtDstLatency cycles after the wire is
// pulled and nothing when it is released. The idle levels and the board pulls
// are re-applied whenever a CTP is programmed.

class dtp_xtrig_base_test_seq extends dtp_base_test_seq;
  `uvm_object_utils(dtp_xtrig_base_test_seq)

  // ------------------------------------------------------------------
  // XTRIG geometry and CSR map (cocotb dtp_xtrig_types parity; dtp_types
  // takes the port counts from the bench configuration and the CSR windows
  // from the generated address maps).
  // ------------------------------------------------------------------
  // dtp_types constants under the family's short names.
  localparam int unsigned XtrigNumCtp = DtpXtrigNumCtp;
  localparam int unsigned XtrigNumIntCt = DtpXtrigNumIntCt;
  localparam int unsigned XtrigNumCtmPorts = DtpXtrigNumCtmPorts;

  localparam bit [63:0] XtrigCtpBase = DtpXtrigCtpBase;
  localparam int unsigned XtrigCtpStride = DtpXtrigCtpStride;
  localparam bit [63:0] XtrigUnmappedBase = DtpXtrigUnmappedBase;

  localparam int unsigned CtpConfigOffset = DtpCtpConfigOffset;
  localparam int unsigned CtpStatusOffset = DtpCtpStatusOffset;
  localparam int unsigned CtpStretchOffset = DtpCtpStretchOffset;

  localparam bit [31:0] CtpConfigModeMask = DtpCtpConfigModeMask;
  localparam bit [31:0] CtpConfigInvertMask = DtpCtpConfigInvertMask;
  localparam bit [31:0] CtpConfigResetMask = DtpCtpConfigResetMask;
  localparam bit [31:0] CtpConfigMask = DtpCtpConfigMask;
  localparam bit [31:0] CtpStretchMask = DtpCtpStretchMask;
  localparam bit [31:0] CtmSelectMask = DtpCtmSelectMask;
  localparam bit [31:0] FullWord = 32'hFFFF_FFFF;

  localparam int unsigned CtpModeWireOr = DtpCtpModeWireOr;
  localparam int unsigned CtpModeP2p = DtpCtpModeP2p;

  localparam bit [31:0] CtpStatusBusy = DtpCtpStatusBusy;
  localparam bit [31:0] CtpStatusReqOut = DtpCtpStatusReqOut;
  localparam bit [31:0] CtpStatusAckIn = DtpCtpStatusAckIn;
  localparam bit [31:0] CtpStatusReqIn = DtpCtpStatusReqIn;
  localparam bit [31:0] CtpStatusAckOut = DtpCtpStatusAckOut;
  // STATUS carries five read-only bits (cross_trigger_port.rdl).
  localparam bit [31:0] CtpStatusMask =
      CtpStatusBusy | CtpStatusReqOut | CtpStatusAckIn | CtpStatusReqIn | CtpStatusAckOut;

  // STRETCH_MULT the route helpers program on every external CTP they use;
  // the internal CTPs carry the same multiplier (cross_trigger_network), so
  // every routed pulse is two cycles wide.
  localparam bit [15:0] RouteStretchMult = 16'd1;
  // A STATUS read issued once the output enable has risen lands several
  // cycles later on the CSR path, so BUSY=1 is read back over the CSR only
  // for pulses at least this many cycles wide (STRETCH_MULT + 1); the busy
  // flop mirror covers every width cycle for cycle.
  localparam int unsigned BusyReadMinStretch = 8;
  // STRETCH_MULT of the pulse a system reset lands on: wide enough that the
  // output enable is active when the reset asserts.
  localparam bit [15:0] ResetHoldStretch = 16'hFFFF;
  // Cycles the window stays open after the last expected output, so a late
  // or stretched pulse on any port is inside it.
  localparam int unsigned IsolationTailCycles = 6;
  // Seeded range of the cycles the bench holds a point-to-point handshake
  // phase, one draw per phase: an acknowledge withheld from a request, an
  // acknowledge held after its request falls, and a request held after its
  // acknowledge rises.
  localparam int unsigned P2pHoldMinCycles = 4;
  localparam int unsigned P2pHoldMaxCycles = 16;
  // Cycles within which a point-to-point pad or BUSY edge follows the peer
  // edge that causes it. The bound is below the span of the seeded holds, so
  // an edge timed from anything but the peer edge falls outside it on some
  // draw.
  localparam int unsigned P2pPhaseMaxCycles = 8;

  // Named-evidence IDs recorded by the shared helpers below.
  localparam string ChkCsr = "CHK-XTRIG-CSR";
  localparam string ChkSignal = "CHK-XTRIG-SIGNAL";
  localparam string ChkRouteModel = "CHK-XTRIG-ROUTE-MODEL";
  localparam string ChkIsolation = "CHK-XTRIG-ISOLATION";
  localparam string ChkQuiet = "CHK-XTRIG-QUIET";
  localparam string ChkStretch = "CHK-XTRIG-STRETCH";
  localparam string ChkAxil = "CHK-XTRIG-AXIL";
  localparam string ChkAwLock = "CHK-XTRIG-AW-LOCK";
  localparam string ChkArStall = "CHK-XTRIG-AR-STALL";
  localparam string ChkWire = "CHK-XTRIG-WIRE";
  localparam string ChkResetCount = "CHK-RESET-COUNT";

  // One access of a pipelined CSR operation.
  typedef dtp_axi_csr_pipeline_seq::op_t pipeline_op_t;

  // Selected by the test before start(); dispatch_scenario() switches on it.
  string scenario = "";

  // Per-pass evidence and routing model.
  ocah_checker            m_check;
  dtp_xtrig_ctm_model ctm_model;
  protected bit           m_negative;
  // Observables already reported X in this pass (one error per name).
  protected bit           m_x_reported[string];

  // Observables a routed pulse can reach, plus the inputs the bench drives
  // (the wire pulls, the point-to-point request pads, and the internal
  // requests) and the receive pulses, which date each output against the
  // window's first input and each receive edge; the activity window ORs and
  // ANDs them per cycle from before the input pulse until the drain tail
  // ends.
  protected string output_signals[$];
  // Observables that must show no activity from the first held cycle of a
  // system reset until after its release: every request and acknowledge
  // output, the CTP busy flops, and every port's receive pulse.
  protected string reset_signals[$];
  // The reset observables that move with every CTP in wire-OR mode, where
  // the acknowledge pads are static.
  protected string wire_or_reset_signals[$];
  // Observables that must show no activity while a CSR access is in flight:
  // the internal-lane requests, the CTP request and acknowledge enables, and
  // the CTP busy flops. The pad levels are left out because they follow the
  // polarity CSR the accesses write, and the internal-lane acknowledge
  // because the pulse-mode lanes leave it unused.
  protected string in_flight_signals[$];
  // Crossbar demux state watched across a two-outstanding write.
  protected string demux_signals[$];
  protected string window_names[$];
  protected bit window_running;
  // The window also tracks the derived per-port observables ctm_port_request
  // (level_vector) and ctm_port_input (input_vector).
  protected bit window_derive;
  protected int unsigned window_cycles;
  protected bit [31:0] window_activity[string];
  protected bit [31:0] window_hold[string];
  protected bit [31:0] window_last[string];
  // Cycle offset (from the window start) at which each bit first rose, and
  // the number of times it rose.
  protected int window_first_seen[string][int unsigned];
  protected int unsigned window_rises[string][int unsigned];
  // Live window: a second sampler, independent of the route window, that ORs
  // its observables from the traffic a reset lands on until the reset.
  protected string m_live_names[$];
  protected bit [31:0] m_live_activity[string];
  protected process m_live_proc;

  function new(string name = "dtp_xtrig_base_test_seq");
    super.new(name);
    ctm_model = new();
    output_signals = '{
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_wire_ext_assert",
        "xtrig_ctp_req_in_din",
        "xtrig_ctm_dst_req",
        "xtrig_ctp_ct_dst",
        "xtrig_int_ct_dst"
    };
    reset_signals = '{
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_ack_out_dout_en",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_ack_out_dout",
        "xtrig_ctp_busy",
        "xtrig_ctp_ct_dst",
        "xtrig_int_ct_dst"
    };
    wire_or_reset_signals = '{
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_req_out_dout",
        "xtrig_ctp_busy",
        "xtrig_ctp_ct_dst",
        "xtrig_int_ct_dst"
    };
    in_flight_signals = '{
        "xtrig_ctm_src_req",
        "xtrig_ctp_req_out_dout_en",
        "xtrig_ctp_ack_out_dout_en",
        "xtrig_ctp_busy"
    };
    demux_signals = '{"xtrig_demux_aw_lock", "xtrig_demux_w_pending"};
  endfunction

  // ------------------------------------------------------------------
  // Body: seed, attach evidence, dispatch, finalize. Scenario families
  // (CSR/AXI, CTP routes, CTM routes) override dispatch_scenario().
  // ------------------------------------------------------------------
  task body();
    string ids[$];
    if (tb_vif == null || xtrig_vif == null || test_cfg == null)
      `uvm_fatal(get_type_name(), "tb_vif/xtrig_vif/test_cfg not plumbed by the test")
    seed_scenario_rng();
    scenario_required_ids(scenario, ids);
    attach_xtrig_checker(ids);
    dispatch_scenario();
    // Every CSR port spill register has kept READY and VALID matched to the
    // beats it holds since the last system reset.
    check_evidence(ChkAxil, "spill_contract_all", 64'(xtrig_pin("xtrig_axil_spill_err_count")),
                   64'd0);
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
      "reg_stall":            ids = {ChkCsr, ChkSignal, ChkQuiet, ChkAxil};
      "axi_channel_skew":     ids = {ChkCsr, ChkAxil};
      "axi_channel_skew_demux_aw_lock_release":     ids = {ChkAxil, ChkAwLock};
      "axi_channel_skew_read_decode_backpressure":  ids = {ChkAxil, ChkArStall};
      "axi_outstanding":      ids = {ChkAxil, ChkAwLock, ChkArStall};
      "ctp_csr_sweep":        begin ids = route_ids; ids.push_back(ChkStretch); end
      "ctm_csr_sweep":        ids = route_ids;
      "ctm_all_source_select": ids = route_ids;
      "wire_or":              ids = {ChkCsr, ChkSignal, ChkStretch, ChkRouteModel, ChkWire};
      "wire_or_bus":          begin ids = route_ids; ids.push_back(ChkWire); end
      "p2p":                  ids = {ChkCsr, ChkSignal};
      "random":               begin ids = route_ids; ids.push_back(ChkStretch); end
      "reset": begin
        ids = route_ids;
        ids.push_back(ChkQuiet);
        ids.push_back(ChkResetCount);
      end
      "ctm_wire_or_cla_to_ctp",
            "ctm_wire_or_ctp_to_cla",
            "ctm_wire_or_cla_to_cla",
            "ctm_wire_or_ctp_to_ctp": begin
        ids = route_ids;
        ids.push_back(ChkStretch);
        ids.push_back(ChkWire);
      end
      "ctm_reset_wire_or_mode": begin
        ids = route_ids;
        ids.push_back(ChkQuiet);
        ids.push_back(ChkWire);
        ids.push_back(ChkResetCount);
      end
      "ctm_reset_p2p_mode",
            "ctm_reset_all_modes": begin
        ids = route_ids;
        ids.push_back(ChkQuiet);
        ids.push_back(ChkResetCount);
      end
      "ctm_rand_wire_or_only":  begin ids = route_ids; ids.push_back(ChkWire); end
      "dst_port_sweep",
            "ctm_p2p_cla_to_ctp",
            "ctm_p2p_ctp_to_cla",
            "ctm_p2p_cla_to_cla",
            "ctm_p2p_ctp_to_ctp",
            "ctm_rand_all_scenarios",
            "ctm_rand_p2p_only",
            "ctm_rand_cla_to_ctp",
            "ctm_rand_ctp_to_cla": ids = route_ids;
      default:
      uvm_pkg::uvm_report_fatal("dtp_xtrig_base_test_seq", $sformatf(
                                "scenario %s has no required-evidence set", scenario));
    endcase
  endfunction

  function void attach_xtrig_checker(string required_ids[$]);
    m_check = ocah_checker::type_id::create({get_name(), ".xtrig"});
    m_check.name_tag = "dtp_xtrig";
    m_check.required_ids = required_ids;
    m_negative = test_cfg.xtrig_checker_negative;
    if (m_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: CTM reference-model selects will be inverted", UVM_LOW)
  endfunction

  function void finalize_xtrig_checker();
    if (m_check == null) `uvm_fatal(get_type_name(), "xtrig checker was never attached")
    m_check.finalize(1'b1);
  endfunction

  // +DTP_XTRIG_NEGATIVE_CHECK=<n> (test_cfg.xtrig_negative_check) is the
  // per-check negative-validation hook: every record of the evidence ID at
  // index n is written with a corrupted observed value, so that ID must
  // fail wherever the scenario records it.
  static function int unsigned negative_check_index(string check_id);
    case (check_id)
      ChkCsr:        return 1;
      ChkSignal:     return 2;
      ChkRouteModel: return 3;
      ChkIsolation:  return 4;
      ChkQuiet:      return 5;
      ChkStretch:    return 6;
      ChkAxil:       return 7;
      ChkAwLock:     return 8;
      ChkArStall:    return 9;
      ChkWire:       return 10;
      default:       return 0;
    endcase
  endfunction

  // Record one named evidence comparison (uvm_error on mismatch).
  function void check_evidence(string check_id, string name, bit [63:0] observed,
                               bit [63:0] expected, string context_s = "");
    if (test_cfg.xtrig_negative_check != 0 && test_cfg.xtrig_negative_check == negative_check_index(
            check_id
        )) begin
      `uvm_info(get_type_name(), $sformatf(
                                     "NEGATIVE VALIDATION: %s observed 0x%0h recorded as 0x%0h",
                                     check_id, observed, observed ^ 64'd1), UVM_LOW)
      observed ^= 64'd1;
    end
    void'(m_check.expect_equal(
        check_id, observed, expected, {name, context_s.len() ? " " : "", context_s}
    ));
  endfunction

  // CHK-RESET-COUNT under the cross-trigger checker: the reset counter
  // advanced by one across the reset.
  function void check_xtrig_reset_counted(string which, logic [31:0] before_count,
                                          logic [31:0] after_count, string context_s);
    string ctx = $sformatf(
        "%s before=%0d after=%0d %s", which, before_count, after_count, context_s
    );
    void'(m_check.expect_equal(ChkResetCount, 64'(after_count - before_count), 64'd1, ctx));
  endfunction

  // ------------------------------------------------------------------
  // CSR map helpers.
  // ------------------------------------------------------------------
  static function bit [63:0] ctm_config_addr(int unsigned src_idx);
    return dtp_xtrig_ctm_config_addr(src_idx);
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

  static function bit [63:0] ctm_hole_addr(int unsigned src_idx);
    return dtp_xtrig_ctm_hole_addr(src_idx);
  endfunction

  static function bit [63:0] ctp_hole_addr(int unsigned ctp_idx);
    return dtp_xtrig_ctp_hole_addr(ctp_idx);
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

  static function void port_bits(bit [31:0] mask, ref int unsigned ports[$]);
    ports.delete();
    for (int unsigned port = 0; port < XtrigNumCtmPorts; port++) begin
      if (mask[port]) ports.push_back(port);
    end
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
    return dtp_xtrig_pack_ctp_config(mode, invert, rst);
  endfunction

  // Apply AXI-Lite byte strobes to a 32-bit word.
  static function bit [31:0] apply_wstrb(bit [31:0] old_value, bit [31:0] new_value,
                                         bit [3:0] wstrb);
    return dtp_xtrig_apply_wstrb(old_value, new_value, wstrb);
  endfunction

  // ------------------------------------------------------------------
  // CSR accessors: reusable AXI-Lite operations on the XTRIG master
  // sequencer (the VIP escalates a non-OKAY response to uvm_error when
  // check_response is set, mirroring the cocotb BRESP asserts).
  // ------------------------------------------------------------------

  // One CSR write, optionally channel-skewed; returns the VIP result item.
  task write_skewed_result(input bit [63:0] addr, input bit [63:0] data,
                           output ocah_axi_item result, input int unsigned aw_valid_delay = 0,
                           input int unsigned w_valid_delay = 0,
                           input int unsigned b_ready_delay = 0, input bit [7:0] strb = 8'hFF,
                           input bit check_response = 1'b1, input bit allow_timeout = 1'b0);
    dtp_axi_csr_write_seq wr = dtp_axi_csr_write_seq::type_id::create("csr_write");
    if (p_sequencer.m_xtrig_seqr == null)
      `uvm_fatal(get_type_name(), "dtp_virtual_sequencer.m_xtrig_seqr is null")
    wr.addr           = addr;
    wr.data           = data[31:0];
    wr.wstrb          = strb[3:0];
    wr.aw_valid_delay = aw_valid_delay;
    wr.w_valid_delay  = w_valid_delay;
    wr.b_ready_delay  = b_ready_delay;
    wr.check_response = check_response;
    wr.allow_timeout  = allow_timeout;
    wr.start(p_sequencer.m_xtrig_seqr, this);
    result = wr.result;
  endtask

  // Two outstanding CSR writes with channel skew on the first; returns both
  // result items in issue order (first.ax_stall_cycles / first.ax_stable
  // observe the AW channel across the pair).
  task write_pair_skewed(input bit [63:0] addr_a, input bit [31:0] data_a, input bit [63:0] addr_b,
                         input bit [31:0] data_b, output ocah_axi_item first,
                         output ocah_axi_item second, input int unsigned aw_valid_delay = 0,
                         input int unsigned w_valid_delay = 0, input int unsigned b_ready_delay = 0,
                         input bit check_response = 1'b1);
    dtp_axi_csr_write_seq wr = dtp_axi_csr_write_seq::type_id::create("csr_write_pair");
    if (p_sequencer.m_xtrig_seqr == null)
      `uvm_fatal(get_type_name(), "dtp_virtual_sequencer.m_xtrig_seqr is null")
    wr.addr           = addr_a;
    wr.data           = data_a;
    wr.pair           = 1'b1;
    wr.pair_addr      = addr_b;
    wr.pair_data      = data_b;
    wr.aw_valid_delay = aw_valid_delay;
    wr.w_valid_delay  = w_valid_delay;
    wr.b_ready_delay  = b_ready_delay;
    wr.check_response = check_response;
    wr.start(p_sequencer.m_xtrig_seqr, this);
    first  = wr.result;
    second = wr.pair_result;
  endtask

  // One CSR read, optionally holding RREADY low; returns the VIP result item.
  task read_hold_result(input bit [63:0] addr, input int unsigned hold_cycles,
                        output ocah_axi_item result, input bit check_response = 1'b1,
                        input bit allow_timeout = 1'b0);
    dtp_axi_csr_read_seq rd = dtp_axi_csr_read_seq::type_id::create("csr_read");
    if (p_sequencer.m_xtrig_seqr == null)
      `uvm_fatal(get_type_name(), "dtp_virtual_sequencer.m_xtrig_seqr is null")
    rd.addr           = addr;
    rd.hold_cycles    = hold_cycles;
    rd.check_response = check_response;
    rd.allow_timeout  = allow_timeout;
    rd.start(p_sequencer.m_xtrig_seqr, this);
    result = rd.result;
  endtask

  // Two outstanding CSR reads, the second AR presented while the first
  // response is held; returns both result items in issue order
  // (first.hold_stable, first.ax_stall_cycles, first.ax_stable).
  task read_pair_hold(input bit [63:0] addr_a, input bit [63:0] addr_b,
                      input int unsigned hold_cycles, output ocah_axi_item first,
                      output ocah_axi_item second, input bit check_response = 1'b1);
    dtp_axi_csr_read_seq rd = dtp_axi_csr_read_seq::type_id::create("csr_read_pair");
    if (p_sequencer.m_xtrig_seqr == null)
      `uvm_fatal(get_type_name(), "dtp_virtual_sequencer.m_xtrig_seqr is null")
    rd.addr           = addr_a;
    rd.pair           = 1'b1;
    rd.pair_addr      = addr_b;
    rd.hold_cycles    = hold_cycles;
    rd.check_response = check_response;
    rd.start(p_sequencer.m_xtrig_seqr, this);
    first  = rd.result;
    second = rd.pair_result;
  endtask

  // A read or a write of a pipelined CSR operation (the cocotb
  // OcahAxiPipelineOp.read and OcahAxiPipelineOp.write).
  static function pipeline_op_t pipeline_read_op(bit [63:0] addr, int unsigned ar_valid_delay = 0,
                                                 bit [2:0] prot = '0);
    pipeline_op_t op;
    op.direction      = OCAH_AXI_DIR_READ;
    op.addr           = addr;
    op.prot           = prot;
    op.ar_valid_delay = ar_valid_delay;
    return op;
  endfunction

  // A partial strobe moves the address to its lowest strobed byte, as the
  // cocotb AXI-Lite master drives it.
  static function pipeline_op_t pipeline_write_op(
      bit [63:0] addr, bit [31:0] data, int unsigned aw_valid_delay = 0,
      int unsigned w_valid_delay = 0, bit [2:0] prot = '0, bit [3:0] strb = 4'hF);
    pipeline_op_t op;
    op.direction      = OCAH_AXI_DIR_WRITE;
    op.addr           = addr;
    for (int unsigned lane = 0; lane < 4; lane++) begin
      if (strb[lane]) begin
        op.addr = addr + lane;
        break;
      end
    end
    op.data           = 64'(data);
    op.strb           = 8'(strb);
    op.prot           = prot;
    op.aw_valid_delay = aw_valid_delay;
    op.w_valid_delay  = w_valid_delay;
    return op;
  endfunction

  // CSR accesses kept in flight together, BREADY and RREADY held for
  // b_hold_cycles and r_hold_cycles after the first response; returns the
  // VIP result item (aw/w/ar_stall_cycles) and the completed item of each op
  // in issue order.
  task pipeline_result(input pipeline_op_t ops[$], output ocah_axi_item result,
                       output ocah_axi_item op_results[$], input int unsigned b_hold_cycles = 0,
                       input int unsigned r_hold_cycles = 0, input bit check_response = 1'b1,
                       input bit allow_timeout = 1'b0);
    dtp_axi_csr_pipeline_seq pl = dtp_axi_csr_pipeline_seq::type_id::create("csr_pipeline");
    if (p_sequencer.m_xtrig_seqr == null)
      `uvm_fatal(get_type_name(), "dtp_virtual_sequencer.m_xtrig_seqr is null")
    pl.ops            = ops;
    pl.b_hold_cycles  = b_hold_cycles;
    pl.r_hold_cycles  = r_hold_cycles;
    pl.check_response = check_response;
    pl.allow_timeout  = allow_timeout;
    pl.start(p_sequencer.m_xtrig_seqr, this);
    result     = pl.result;
    op_results = pl.op_results;
  endtask

  task csr_write(bit [63:0] addr, bit [31:0] data, bit [3:0] wstrb = 4'hF, string label = "");
    ocah_axi_item result;
    write_skewed_result(addr, 64'(data), result, .strb(8'(wstrb)));
    `uvm_info(get_type_name(),
              $sformatf("XTRIG CSR WRITE %-34s addr=0x%03h data=0x%08h wstrb=0x%h resp=%s", label,
                        addr, data, wstrb, result.worst_resp().name()), UVM_MEDIUM)
  endtask

  task csr_read(bit [63:0] addr, output bit [31:0] data, input string label = "");
    ocah_axi_item result;
    read_hold_result(addr, 0, result);
    data = result.first_data();
    `uvm_info(get_type_name(), $sformatf("XTRIG CSR READ  %-34s addr=0x%03h data=0x%08h", label,
                                         addr, data), UVM_MEDIUM)
  endtask

  task write_read_check(bit [63:0] addr, bit [31:0] data, bit [31:0] expected,
                        bit [3:0] wstrb = 4'hF, bit [31:0] mask = FullWord, string label = "");
    bit [31:0] observed;
    csr_write(addr, data, wstrb, label);
    csr_read(addr, observed, label);
    check_evidence(ChkCsr, label.len() ? label : $sformatf("csr_0x%0h", addr), 64'(observed & mask),
                   64'(expected & mask), $sformatf("addr=0x%03h wstrb=0x%h", addr, wstrb));
  endtask

  // Read STATUS and record every named field passed as 0 or 1 (-1 skips).
  task check_status(int unsigned ctp_idx, string label, int busy = -1, int req_out = -1,
                    int ack_in = -1, int req_in = -1, int ack_out = -1);
    bit [31:0] status;
    csr_read(ctp_status_addr(ctp_idx), status, {label, ".status"});
    check_status_bit(ctp_idx, label, "busy", status, CtpStatusBusy, busy);
    check_status_bit(ctp_idx, label, "req_out", status, CtpStatusReqOut, req_out);
    check_status_bit(ctp_idx, label, "ack_in", status, CtpStatusAckIn, ack_in);
    check_status_bit(ctp_idx, label, "req_in", status, CtpStatusReqIn, req_in);
    check_status_bit(ctp_idx, label, "ack_out", status, CtpStatusAckOut, ack_out);
  endtask

  protected function void check_status_bit(int unsigned ctp_idx, string label, string name,
                                           bit [31:0] status, bit [31:0] mask, int expected);
    if (expected < 0) return;
    check_evidence(ChkCsr, $sformatf("%s.status.%s", label, name), 64'((status & mask) != 0),
                   64'(expected), $sformatf("ctp=%0d", ctp_idx));
  endfunction

  task program_ctp(int unsigned ctp_idx, int unsigned mode = CtpModeWireOr, bit invert = 1'b0,
                   bit rst = 1'b0, bit [15:0] stretch = '0);
    bit [31:0] cfg_word = pack_ctp_config(mode, invert, rst);
    p_sequencer.m_xtrig_ctp_shadow.note(ctp_idx, mode, invert);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "Configure CTP[%0d]: mode=%s invert=%0d reset=%0d stretch=%0d (wire rests at %0d)",
            ctp_idx, mode == CtpModeP2p ? "p2p" : "wire_or", invert, rst, stretch,
            DtpWireOrPull[invert]), UVM_MEDIUM)
    // The board comes first: the wire rests at the pull of the new sense
    // before software sets INVERT to match it.
    xtrig_vif.xtrig_ctp_wire_pull <= XtrigNumCtp'(p_sequencer.m_xtrig_ctp_shadow.wire_pull_mask());
    write_read_check(ctp_config_addr(ctp_idx), cfg_word, cfg_word, 4'hF, CtpConfigMask, $sformatf(
                     "ctp%0d.config", ctp_idx));
    write_read_check(ctp_stretch_addr(ctp_idx), 32'(stretch), 32'(stretch), 4'hF, CtpStretchMask,
                     $sformatf("ctp%0d.stretch", ctp_idx));
    apply_idle_levels();
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
      `uvm_info(get_type_name(),
                $sformatf("NEGATIVE VALIDATION: CTM model select 0x%0h instead of 0x%0h",
                          model_mask, input_mask), UVM_LOW)
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
    p_sequencer.m_xtrig_ctp_shadow.clear();
    for (int unsigned ctp_idx = 0; ctp_idx < XtrigNumCtp; ctp_idx++) begin
      csr_write(ctp_config_addr(ctp_idx), '0, 4'hF, $sformatf("cleanup.ctp%0d.cfg", ctp_idx));
      csr_write(ctp_stretch_addr(ctp_idx), '0, 4'hF, $sformatf("cleanup.ctp%0d.stretch", ctp_idx));
    end
    clear_ctm_routes();
  endtask

  // Every CTP CONFIG, STRETCH_MULT, and STATUS reads its reset value.
  task check_ctp_defaults(string label);
    bit [31:0] observed;
    for (int unsigned ctp_idx = 0; ctp_idx < XtrigNumCtp; ctp_idx++) begin
      csr_read(ctp_config_addr(ctp_idx), observed, $sformatf("%s.ctp%0d.config", label, ctp_idx));
      check_evidence(ChkCsr, $sformatf("%s.ctp%0d.config.default", label, ctp_idx),
                     64'(observed & CtpConfigMask), 64'(DtpCtpConfigDefault & CtpConfigMask));
      csr_read(ctp_stretch_addr(ctp_idx), observed, $sformatf("%s.ctp%0d.stretch", label, ctp_idx));
      check_evidence(ChkCsr, $sformatf("%s.ctp%0d.stretch.default", label, ctp_idx),
                     64'(observed & CtpStretchMask), 64'(DtpCtpStretchDefault & CtpStretchMask));
      csr_read(ctp_status_addr(ctp_idx), observed, $sformatf("%s.ctp%0d.status", label, ctp_idx));
      check_evidence(ChkCsr, $sformatf("%s.ctp%0d.status.default", label, ctp_idx),
                     64'(observed & CtpStatusMask), 64'(DtpCtpStatusDefault & CtpStatusMask));
    end
  endtask

  // ------------------------------------------------------------------
  // Cross-trigger pin surface over dtp_xtrig_if.
  // ------------------------------------------------------------------
  // Quiesce every stimulus vector; the wire pulls and the group describe the
  // board and stay.
  task clear_xtrig_inputs();
    xtrig_vif.xtrig_ctm_src_ack         <= '0;
    xtrig_vif.xtrig_ctm_dst_req         <= '0;
    xtrig_vif.xtrig_ctp_wire_ext_assert <= '0;
    xtrig_vif.xtrig_ctp_req_in_din      <= '0;
    xtrig_vif.xtrig_ctp_ack_in_din      <= '0;
    xtrig_vif.xtrig_ctp_ack_out_din     <= '0;
    wait_sys_cycles(1);
  endtask

  // Point-to-point pad levels of `ctp_mask`: asserted high and idle low,
  // inverted CTPs the reverse.
  function bit [31:0] pad_level(bit [31:0] ctp_mask, bit asserted);
    bit [31:0] inverted = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
    return asserted ? (ctp_mask & ~inverted) : (ctp_mask & inverted);
  endfunction

  // Rest every point-to-point pad at its idle level and every wire at its
  // board's pull.
  function void apply_idle_levels();
    bit [31:0] inverted = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
    xtrig_vif.xtrig_ctp_req_in_din <= XtrigNumCtp'(inverted);
    xtrig_vif.xtrig_ctp_ack_in_din <= XtrigNumCtp'(inverted);
    xtrig_vif.xtrig_ctp_wire_pull  <= XtrigNumCtp'(p_sequencer.m_xtrig_ctp_shadow.wire_pull_mask());
  endfunction

  // Put the CTPs of `mask` on one shared wire resting at the pull for `invert`.
  function void share_wire(bit [31:0] mask, bit invert);
    xtrig_vif.xtrig_ctp_wire_group      <= XtrigNumCtp'(mask);
    xtrig_vif.xtrig_ctp_wire_group_pull <= DtpWireOrPull[invert];
  endfunction

  // Return every driven cross-trigger input to its idle level. The idle
  // levels are written in the same time step as the quiesce, so an inverted
  // point-to-point pad never passes through its asserted low level.
  task idle_inputs();
    xtrig_vif.xtrig_ctm_src_ack         <= '0;
    xtrig_vif.xtrig_ctm_dst_req         <= '0;
    xtrig_vif.xtrig_ctp_wire_ext_assert <= '0;
    xtrig_vif.xtrig_ctp_ack_out_din     <= '0;
    apply_idle_levels();
    wait_sys_cycles(1);
  endtask

  // Named cross-trigger observable read (zero-extended to 32 bits). An X on
  // the observable is an error once per name per pass: a zero expectation
  // would otherwise absorb it.
  function bit [31:0] xtrig_pin(string name);
    logic [31:0] sampled;
    case (name)
      "xtrig_ctm_src_req":         sampled = 32'(xtrig_vif.xtrig_ctm_src_req);
      "xtrig_ctm_dst_ack":         sampled = 32'(xtrig_vif.xtrig_ctm_dst_ack);
      "xtrig_ctm_src_ack":         sampled = 32'(xtrig_vif.xtrig_ctm_src_ack);
      "xtrig_ctm_dst_req":         sampled = 32'(xtrig_vif.xtrig_ctm_dst_req);
      "xtrig_ctp_req_out_dout":    sampled = 32'(xtrig_vif.xtrig_ctp_req_out_dout);
      "xtrig_ctp_req_out_dout_en": sampled = 32'(xtrig_vif.xtrig_ctp_req_out_dout_en);
      "xtrig_ctp_req_out_din":     sampled = 32'(xtrig_vif.xtrig_ctp_req_out_din);
      "xtrig_ctp_req_out_din_en":  sampled = 32'(xtrig_vif.xtrig_ctp_req_out_din_en);
      "xtrig_ctp_wire_ext_assert": sampled = 32'(xtrig_vif.xtrig_ctp_wire_ext_assert);
      "xtrig_ctp_wire_pull":       sampled = 32'(xtrig_vif.xtrig_ctp_wire_pull);
      "xtrig_ctp_wire_group":      sampled = 32'(xtrig_vif.xtrig_ctp_wire_group);
      "xtrig_ctp_wire_mismatch":   sampled = 32'(xtrig_vif.xtrig_ctp_wire_mismatch);
      "xtrig_ctp_ct_dst":          sampled = 32'(xtrig_vif.xtrig_ctp_ct_dst);
      "xtrig_int_ct_dst":          sampled = 32'(xtrig_vif.xtrig_int_ct_dst);
      "xtrig_ctp_req_in_dout":     sampled = 32'(xtrig_vif.xtrig_ctp_req_in_dout);
      "xtrig_ctp_req_in_dout_en":  sampled = 32'(xtrig_vif.xtrig_ctp_req_in_dout_en);
      "xtrig_ctp_req_in_din":      sampled = 32'(xtrig_vif.xtrig_ctp_req_in_din);
      "xtrig_ctp_req_in_din_en":   sampled = 32'(xtrig_vif.xtrig_ctp_req_in_din_en);
      "xtrig_ctp_ack_in_dout":     sampled = 32'(xtrig_vif.xtrig_ctp_ack_in_dout);
      "xtrig_ctp_ack_in_dout_en":  sampled = 32'(xtrig_vif.xtrig_ctp_ack_in_dout_en);
      "xtrig_ctp_ack_in_din":      sampled = 32'(xtrig_vif.xtrig_ctp_ack_in_din);
      "xtrig_ctp_ack_in_din_en":   sampled = 32'(xtrig_vif.xtrig_ctp_ack_in_din_en);
      "xtrig_ctp_ack_out_dout":    sampled = 32'(xtrig_vif.xtrig_ctp_ack_out_dout);
      "xtrig_ctp_ack_out_dout_en": sampled = 32'(xtrig_vif.xtrig_ctp_ack_out_dout_en);
      "xtrig_ctp_ack_out_din":     sampled = 32'(xtrig_vif.xtrig_ctp_ack_out_din);
      "xtrig_ctp_ack_out_din_en":  sampled = 32'(xtrig_vif.xtrig_ctp_ack_out_din_en);
      "xtrig_ctp_busy":            sampled = 32'(tb_vif.xtrig_ctp_busy);
      "xtrig_demux_aw_lock":       sampled = 32'(tb_vif.xtrig_demux_aw_lock);
      "xtrig_demux_w_pending":     sampled = 32'(tb_vif.xtrig_demux_w_pending);
      "xtrig_axil_awvalid_count":  sampled = tb_vif.xtrig_axil_awvalid_count;
      "xtrig_axil_wvalid_count":   sampled = tb_vif.xtrig_axil_wvalid_count;
      "xtrig_axil_arvalid_count":  sampled = tb_vif.xtrig_axil_arvalid_count;
      "xtrig_axil_aw_stall_count": sampled = tb_vif.xtrig_axil_aw_stall_count;
      "xtrig_axil_ar_stall_count": sampled = tb_vif.xtrig_axil_ar_stall_count;
      "xtrig_axil_w_stall_count":  sampled = tb_vif.xtrig_axil_w_stall_count;
      "xtrig_axil_aw_open_stall_count": sampled = tb_vif.xtrig_axil_aw_open_stall_count;
      "xtrig_axil_aw_open_accept_count": sampled = tb_vif.xtrig_axil_aw_open_accept_count;
      "xtrig_axil_ar_open_stall_count": sampled = tb_vif.xtrig_axil_ar_open_stall_count;
      "xtrig_axil_ar_open_accept_count": sampled = tb_vif.xtrig_axil_ar_open_accept_count;
      "xtrig_axil_spill_err_count": sampled = tb_vif.xtrig_axil_spill_err_count;
      "xtrig_axil_w_spill_full_count":    sampled = tb_vif.xtrig_axil_w_spill_full_count;
      "xtrig_axil_r_spill_full_count":    sampled = tb_vif.xtrig_axil_r_spill_full_count;
      "xtrig_demux_aw_stall_count": sampled = tb_vif.xtrig_demux_aw_stall_count;
      "xtrig_demux_w_stall_count": sampled = tb_vif.xtrig_demux_w_stall_count;
      "xtrig_demux_ar_stall_count": sampled = tb_vif.xtrig_demux_ar_stall_count;
      "xtrig_demux_aw_open_stall_count": sampled = tb_vif.xtrig_demux_aw_open_stall_count;
      "xtrig_demux_aw_open_accept_count": sampled = tb_vif.xtrig_demux_aw_open_accept_count;
      "xtrig_demux_ar_open_stall_count": sampled = tb_vif.xtrig_demux_ar_open_stall_count;
      "xtrig_demux_ar_open_accept_count": sampled = tb_vif.xtrig_demux_ar_open_accept_count;
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown xtrig observable %s", name))
        sampled = '0;
      end
    endcase
    if ($isunknown(sampled) && !m_x_reported.exists(name)) begin
      m_x_reported[name] = 1'b1;
      `uvm_error(get_type_name(), $sformatf("xtrig observable %s sampled X: 0x%0h", name, sampled))
    end
    return sampled;
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
    xtrig_vif.xtrig_ctm_dst_req <= xtrig_vif.xtrig_ctm_dst_req | (XtrigNumIntCt'(1) << int_idx);
    wait_sys_cycles(cycles);
    xtrig_vif.xtrig_ctm_dst_req <= xtrig_vif.xtrig_ctm_dst_req & ~(XtrigNumIntCt'(1) << int_idx);
  endtask

  // Pull the shared wires of `ctp_mask` and request the internal CTs of
  // `int_mask` in the same cycles: the chiplet on each selected wire pulls it
  // to the asserted level of its sense for `cycles` clocks.
  task pulse_input_mask(bit [31:0] ctp_mask, bit [31:0] int_mask, int unsigned cycles = 2);
    xtrig_vif.xtrig_ctp_wire_ext_assert <= xtrig_vif.xtrig_ctp_wire_ext_assert
        | XtrigNumCtp'(ctp_mask);
    xtrig_vif.xtrig_ctm_dst_req         <= xtrig_vif.xtrig_ctm_dst_req | XtrigNumIntCt'(int_mask);
    wait_sys_cycles(cycles);
    xtrig_vif.xtrig_ctp_wire_ext_assert <= xtrig_vif.xtrig_ctp_wire_ext_assert
        & ~XtrigNumCtp'(ctp_mask);
    xtrig_vif.xtrig_ctm_dst_req         <= xtrig_vif.xtrig_ctm_dst_req & ~XtrigNumIntCt'(int_mask);
  endtask

  // The chiplet on CTP `ctp_idx`'s wire pulls it for `cycles` clocks.
  task pull_ctp_wire(int unsigned ctp_idx, int unsigned cycles = 2);
    pulse_input_mask(32'd1 << ctp_idx, '0, cycles);
  endtask

  task drive_ctp_p2p_req_in(int unsigned ctp_idx, bit value);
    if (value)
      xtrig_vif.xtrig_ctp_req_in_din <= xtrig_vif.xtrig_ctp_req_in_din | (XtrigNumCtp'(1) << ctp_idx);
    else
      xtrig_vif.xtrig_ctp_req_in_din <= xtrig_vif.xtrig_ctp_req_in_din & ~(XtrigNumCtp'(1) << ctp_idx);
    wait_sys_cycles(1);
  endtask

  task drive_ctp_p2p_ack_in(int unsigned ctp_idx, bit value);
    if (value)
      xtrig_vif.xtrig_ctp_ack_in_din <= xtrig_vif.xtrig_ctp_ack_in_din | (XtrigNumCtp'(1) << ctp_idx);
    else
      xtrig_vif.xtrig_ctp_ack_in_din <= xtrig_vif.xtrig_ctp_ack_in_din & ~(XtrigNumCtp'(1) << ctp_idx);
    wait_sys_cycles(1);
  endtask

  // Polarity-aware request-in and acknowledge-in drives.
  task drive_p2p_req_in(int unsigned ctp_idx, bit asserted);
    drive_ctp_p2p_req_in(ctp_idx, pad_level(32'd1 << ctp_idx, asserted) [ctp_idx]);
  endtask

  task drive_p2p_ack_in(int unsigned ctp_idx, bit asserted);
    drive_ctp_p2p_ack_in(ctp_idx, pad_level(32'd1 << ctp_idx, asserted) [ctp_idx]);
  endtask

  task pulse_ctm_dst_req(bit [31:0] mask, int unsigned cycles = 1);
    xtrig_vif.xtrig_ctm_dst_req <= XtrigNumIntCt'(mask);
    wait_sys_cycles(cycles);
    xtrig_vif.xtrig_ctm_dst_req <= '0;
  endtask

  task pulse_ctm_src_ack(bit [31:0] mask, int unsigned cycles = 1);
    xtrig_vif.xtrig_ctm_src_ack <= XtrigNumIntCt'(mask);
    wait_sys_cycles(cycles);
    xtrig_vif.xtrig_ctm_src_ack <= '0;
  endtask

  // The quiet and reset observable lists leave out the internal-lane
  // acknowledge, which only a pulse-mode lane leaves unused.
  function void require_pulse_mode_lanes(string where);
    if (DtpXtrigIntCtMode != '0)
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s: handshake-mode internal lanes (INT_CT_MODE=0x%0h) need their acknowledge watched",
                 where,
                 DtpXtrigIntCtMode
                 ))
  endfunction

  // Start the live window over `names`: one sample per system clock period
  // until stop_live_window().
  task start_live_window(string names[$]);
    if (m_live_proc != null) `uvm_fatal(get_type_name(), "the live window is already running")
    m_live_names = names;
    m_live_activity.delete();
    foreach (m_live_names[i]) m_live_activity[m_live_names[i]] = '0;
    fork
      begin
        m_live_proc = process::self();
        forever begin
          record_live_sample();
          wait_sys_cycles(1);
        end
      end
    join_none
    wait (m_live_proc != null);
  endtask

  function void record_live_sample();
    foreach (m_live_names[i]) m_live_activity[m_live_names[i]] |= xtrig_pin(m_live_names[i]);
  endfunction

  // Stop the live window after a final sample.
  function void stop_live_window();
    if (m_live_proc == null) `uvm_fatal(get_type_name(), "no live window is running")
    m_live_proc.kill();
    m_live_proc = null;
    record_live_sample();
  endfunction

  // System reset watched from its first held cycle until after release. The
  // live window, which the scenario started over `watched` before the
  // traffic the reset lands on, shows every watched observable active
  // (CHK-XTRIG-SIGNAL), and none of them moves while the reset holds or for
  // cycles + 2 cycles after release (CHK-XTRIG-QUIET). The reset is counted
  // (CHK-RESET-COUNT) and the CSR shadows reset with the DUT.
  task reset_window(string label, string watched[$], int unsigned cycles = 3);
    logic [31:0] before_count;
    require_pulse_mode_lanes("reset_window");
    stop_live_window();
    foreach (watched[i]) begin
      if (!m_live_activity.exists(watched[i]))
        `uvm_fatal(get_type_name(), $sformatf(
                   "reset_window %s: the live window does not sample %s", label, watched[i]))
      check_evidence(ChkSignal, $sformatf("reset_window.%s.%s.live_before", label, watched[i]),
                     64'(m_live_activity[watched[i]] != 0), 64'd1);
    end
    before_count = tb_vif.sys_rst_assert_count;
    clear_xtrig_inputs();
    tb_vif.sys_rst_n <= 1'b0;
    wait_sys_cycles(1);
    start_activity_window_on(watched);
    wait_sys_cycles(cycles - 1);
    tb_vif.sys_rst_n <= 1'b1;
    ctm_model = new();
    p_sequencer.m_xtrig_ctp_shadow.clear();
    wait_sys_cycles(cycles + 2);
    stop_activity_window();
    check_xtrig_reset_counted("sys_rst_assert_count", before_count, tb_vif.sys_rst_assert_count,
                              $sformatf("reset_window.%s cycles=%0d", label, cycles));
    foreach (watched[i])
      check_evidence(ChkQuiet, $sformatf("reset_window.%s.%s", label, watched[i]),
                     64'(window_activity[watched[i]]), 64'd0, $sformatf("cycles=%0d", window_cycles
                     ));
  endtask

  // Consecutive-cycle width of the first masked pulse, and the rises counted
  // until tail_cycles after it ends. A masked value already nonzero at the
  // first sample counts as a rise; the measurement ends at timeout_cycles
  // samples in any case.
  task measure_mask_width(input string name, input bit [31:0] mask, output int unsigned width,
                          output int unsigned pulses, input int unsigned timeout_cycles = 80,
                          input int unsigned tail_cycles = IsolationTailCycles);
    bit was_active = 1'b0;
    bit first_done = 1'b0;
    int unsigned done_at = 0;
    width  = 0;
    pulses = 0;
    for (int unsigned c = 0; c < timeout_cycles; c++) begin
      bit active = (xtrig_pin(name) & mask) != 0;
      if (active && !was_active) pulses++;
      if (!first_done) begin
        if (active) width++;
        else if (pulses != 0) begin
          first_done = 1'b1;
          done_at    = c;
        end
      end
      was_active = active;
      if (first_done && (c - done_at >= tail_cycles)) return;
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

  // Every bit of `mask` on `name` has fired: seen by the running activity
  // window (the live window when `live` is set), or high now. A selected
  // output whose pulse ended while its trigger was still held counts as
  // fired.
  task wait_window_fired(string name, bit [31:0] mask, int unsigned cycles = 60, string label = "",
                         bit live = 1'b0);
    bit [31:0] observed = '0;
    for (int unsigned c = 0; c < cycles; c++) begin
      observed = xtrig_pin(name);
      if (live) begin
        if (m_live_proc != null && m_live_activity.exists(name)) observed |= m_live_activity[name];
      end else if (window_running && window_activity.exists(name)) begin
        observed |= window_activity[name];
      end
      observed &= mask;
      if (observed == mask) break;
      wait_sys_cycles(1);
    end
    check_evidence(ChkSignal, {name, ".mask"}, 64'(observed), 64'(mask), label);
  endtask

  // Quiet window: the internal-lane requests and the CTP request and
  // acknowledge enables must show zero activity for the window
  // (CHK-XTRIG-QUIET). The internal lanes run in pulse mode, where their
  // acknowledge is unused.
  task check_quiet(string label, int unsigned cycles = 4);
    string names[$] = {"xtrig_ctm_src_req", "xtrig_ctp_req_out_dout_en",
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
                                   bit [15:0] stretch = RouteStretchMult);
    if (!is_ctp_port(port)) return;
    // The handshake sender latches every delivered trigger whatever the
    // mode, and only an acknowledge or CONFIG.RESET releases it, so a port
    // entering P2P mode would otherwise present a request left pending from
    // wire-OR routing. RESET is a level: assert, then program.
    if (mode == CtpModeP2p)
      csr_write(ctp_config_addr(port), pack_ctp_config(mode, 1'b0, 1'b1), 4'hF, $sformatf(
                "ctp%0d.handshake_reset", port));
    program_ctp(port, mode, 1'b0, 1'b0, stretch);
  endtask

  task configure_ctp_modes_for_route(int unsigned input_port, bit [31:0] output_mask,
                                     int unsigned mode);
    configure_ctp_modes_for_route_mask(32'd1 << input_port, output_mask, mode);
  endtask

  task configure_ctp_modes_for_route_mask(bit [31:0] input_mask, bit [31:0] output_mask,
                                          int unsigned mode);
    int unsigned ports[$];
    port_bits(input_mask | output_mask, ports);
    foreach (ports[i]) configure_ctp_mode_for_port(ports[i], mode);
  endtask

  task program_route(int unsigned input_port, bit [31:0] output_mask, string label);
    program_routes(32'd1 << input_port, output_mask, label);
  endtask

  // Select `input_mask` on every output of `output_mask` (multi-bit =
  // wire-OR merge).
  task program_routes(bit [31:0] input_mask, bit [31:0] output_mask, string label);
    int unsigned outputs[$];
    `uvm_info(
        get_type_name(),
        $sformatf(
            "Program CTM route %-20s input_mask=0x%08h output_mask=0x%08h (CSR output selects inputs)",
            label, input_mask, output_mask), UVM_MEDIUM)
    clear_ctm_routes();
    port_bits(output_mask, outputs);
    foreach (outputs[i]) program_ctm_src(outputs[i], input_mask);
  endtask

  task drive_input_port(int unsigned input_port, int unsigned mode, int unsigned cycles = 2);
    drive_input_mask(32'd1 << input_port, mode, cycles);
  endtask

  // Pulse every input of `input_mask` in the same cycles; a P2P CTP source
  // raises its request pad. Internal sources request through a pulse in
  // every mode. The bench is the four-phase sender of a P2P CTP source:
  // CT_Ack_out is idle before the request and asserts within
  // P2pPhaseMaxCycles of it, the request stays up for `cycles` and for a
  // seeded P2pHoldMinCycles..P2pHoldMaxCycles after CT_Ack_out asserts, and
  // CT_Ack_out stays asserted until the release and drops within
  // P2pPhaseMaxCycles of it.
  task drive_input_mask(bit [31:0] input_mask, int unsigned mode, int unsigned cycles = 2,
                        string label = "");
    bit [31:0] ctp_bits = project_ctp_mask(input_mask);
    int unsigned ports[$];
    if (mode == CtpModeP2p && ctp_bits != 0) begin
      bit [31:0] invert = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
      bit [31:0] ack, held;
      int rose_at, fell_at, hold;
      port_bits(ctp_bits, ports);
      if (ports.size() != 1 || input_mask != ctp_bits)
        `uvm_fatal(get_type_name(), "a P2P request is one CTP source")
      check_evidence(ChkSignal, {label, ".src_ack_idle_before"}, 64'(xtrig_pin(
                     "xtrig_ctp_ack_out_dout") & ctp_bits), 64'(pad_level(ctp_bits, 1'b0)));
      drive_p2p_req_in(ports[0], 1'b1);
      wait_p2p_phase("xtrig_ctp_ack_out_dout", ctp_bits, ctp_bits, invert, ack, rose_at);
      check_evidence(ChkSignal, {label, ".src_ack"}, 64'(ack), 64'(ctp_bits), $sformatf(
                     "CT_Ack_out asserted %0d cycles after CT_Req_in", rose_at));
      hold = $urandom_range(P2pHoldMaxCycles, P2pHoldMinCycles);
      if (int'(cycles) - rose_at > hold) hold = int'(cycles) - rose_at;
      held = ack;
      repeat (hold) begin
        wait_sys_cycles(1);
        held &= xtrig_pin("xtrig_ctp_ack_out_dout") ^ invert;
      end
      check_evidence(ChkSignal, {label, ".src_ack_held"}, 64'(held), 64'(ctp_bits), $sformatf(
                     "CT_Req_in held %0d cycles after CT_Ack_out asserted", hold));
      drive_p2p_req_in(ports[0], 1'b0);
      wait_p2p_phase("xtrig_ctp_ack_out_dout", ctp_bits, '0, invert, ack, fell_at);
      check_evidence(ChkSignal, {label, ".src_ack_idle"}, 64'(ack), 64'd0, $sformatf(
                     "CT_Ack_out fell %0d cycles after CT_Req_in released", fell_at));
      return;
    end
    pulse_input_mask(ctp_bits, project_internal_mask(input_mask), cycles);
  endtask

  // Window sampler: one sample per system clock period from start until stop.
  // The route window over output_signals also tracks the derived per-port
  // observables, each with a value of 0 before the window starts.
  task start_activity_window();
    start_window(output_signals, 1'b1);
  endtask

  task start_activity_window_on(string names[$]);
    start_window(names, 1'b0);
  endtask

  protected task start_window(string names[$], bit derive);
    string tracked[$] = names;
    window_names = names;
    window_derive = derive;
    if (derive) tracked = {tracked, "ctm_port_request", "ctm_port_input"};
    window_cycles = 0;
    window_first_seen.delete();
    window_rises.delete();
    foreach (tracked[i]) begin
      window_activity[tracked[i]] = '0;
      window_hold[tracked[i]] = '1;
      window_last[tracked[i]] = '0;
    end
    window_running = 1'b1;
    fork
      while (window_running) begin
        record_window_sample();
        wait_sys_cycles(1);
      end
    join_none
  endtask

  function void record_window_sample();
    foreach (window_names[i]) track_window_bits(window_names[i], xtrig_pin(window_names[i]));
    if (window_derive) begin
      track_window_bits("ctm_port_request", level_vector());
      track_window_bits("ctm_port_input", input_vector());
    end
    window_cycles++;
  endfunction

  protected function void track_window_bits(string name, bit [31:0] value);
    bit [31:0] new_bits = value & ~window_activity[name];
    bit [31:0] rose = value & ~window_last[name];
    for (int unsigned b = 0; b < 32; b++) begin
      if (new_bits[b]) window_first_seen[name][b] = int'(window_cycles);
      if (rose[b]) window_rises[name][b]++;
    end
    window_activity[name] |= value;
    window_hold[name] &= value;
    window_last[name] = value;
  endfunction

  function void stop_activity_window();
    window_running = 1'b0;
    record_window_sample();
  endfunction

  // Window cycle at which bit `bit_idx` of `name` first rose, -1 when never.
  function int window_first_rise(string name, int unsigned bit_idx);
    if (window_first_seen.exists(name) && window_first_seen[name].exists(bit_idx))
      return window_first_seen[name][bit_idx];
    return -1;
  endfunction

  // Number of times bit `bit_idx` of `name` rose inside the window.
  function int unsigned window_rise_count(string name, int unsigned bit_idx);
    if (window_rises.exists(name) && window_rises[name].exists(bit_idx))
      return window_rises[name][bit_idx];
    return 0;
  endfunction

  // One wire-OR source received its own assertion once, DtpCtDstLatency
  // cycles after `asserted_at` (the window cycle its wire was pulled or its
  // CLA request rose; -1 when it never was), and never again in the window.
  function void check_receive_edge(string receive_name, int unsigned bit_idx, int asserted_at,
                                   string label);
    int received_at = window_first_rise(receive_name, bit_idx);
    int latency = (asserted_at < 0 || received_at < 0) ? -1 : received_at - asserted_at;
    check_evidence(ChkWire, {label, ".ct_dst_latency"}, 64'(latency), 64'(DtpCtDstLatency),
                   $sformatf("asserted@%0d ct_dst@%0d", asserted_at, received_at));
    check_evidence(ChkWire, {label, ".ct_dst_pulses"}, 64'(window_rise_count(receive_name, bit_idx
                   )), 64'd1, "one receive per wire assertion");
  endfunction

  // Every wire-OR source of the window received its own assertion: the CTP
  // sources of `ctp_sources` through the chiplet pull of their wire, the
  // internal sources of `int_sources` through their CLA request (CHK-XTRIG-WIRE).
  function void check_receive_edges(bit [31:0] ctp_sources, bit [31:0] int_sources, string label);
    int unsigned bits[$];
    port_bits(ctp_sources, bits);
    foreach (bits[i])
    check_receive_edge("xtrig_ctp_ct_dst", bits[i], window_first_rise(
                       "xtrig_ctp_wire_ext_assert", bits[i]), $sformatf("%s.ctp%0d", label, bits[i]
                       ));
    port_bits(int_sources, bits);
    foreach (bits[i])
    check_receive_edge("xtrig_int_ct_dst", bits[i], window_first_rise("xtrig_ctm_dst_req", bits[i]),
                       $sformatf("%s.int%0d", label, bits[i]));
  endfunction

  // Every member of a shared wire received the one assertion `pulled_by`
  // made on it, dated by `pulled_at_name`.
  function void check_shared_wire_receive(int unsigned members[$], string pulled_at_name,
                                          int unsigned pulled_by, string label);
    int pulled_at = window_first_rise(pulled_at_name, pulled_by);
    foreach (members[i])
    check_receive_edge("xtrig_ctp_ct_dst", members[i], pulled_at, $sformatf(
                       "%s.ctp%0d", label, members[i]));
  endfunction

  // CTM-port vector (CTP bits low, internal bits high) of every output that
  // requested at some cycle of the window. A wire-OR CTP requests through its
  // output enable; a P2P CTP through its request level, which idles low (or
  // high when inverted). Internal ports request through xtrig_ctm_src_req.
  function bit [31:0] fired_vector();
    bit [31:0] all_ctp = (32'd1 << XtrigNumCtp) - 1;
    bit [31:0] p2p = p_sequencer.m_xtrig_ctp_shadow.p2p_mask();
    bit [31:0] inverted = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
    bit [31:0] dout_any = window_activity["xtrig_ctp_req_out_dout"];
    bit [31:0] dout_all = window_hold["xtrig_ctp_req_out_dout"];
    bit [31:0] p2p_fired = ((dout_any & ~inverted) | (~dout_all & inverted)) & p2p;
    bit [31:0] wire_or_fired = window_activity["xtrig_ctp_req_out_dout_en"] & ~p2p;
    bit [31:0] int_fired = window_activity["xtrig_ctm_src_req"] & ((32'd1 << XtrigNumIntCt) - 1);
    return ((p2p_fired | wire_or_fired) & all_ctp) | (int_fired << XtrigNumCtp);
  endfunction

  // CTM-port vector of every output requesting in the last window sample.
  function bit [31:0] level_vector();
    bit [31:0] all_ctp = (32'd1 << XtrigNumCtp) - 1;
    bit [31:0] p2p = p_sequencer.m_xtrig_ctp_shadow.p2p_mask();
    bit [31:0] inverted = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
    bit [31:0] p2p_level = (window_last["xtrig_ctp_req_out_dout"] ^ inverted) & p2p;
    bit [31:0] wire_or_level = window_last["xtrig_ctp_req_out_dout_en"] & ~p2p;
    bit [31:0] int_level = window_last["xtrig_ctm_src_req"] & ((32'd1 << XtrigNumIntCt) - 1);
    return ((p2p_level | wire_or_level) & all_ctp) | (int_level << XtrigNumCtp);
  endfunction

  // CTM-port vector of every input the bench asserts in the last window
  // sample: a wire-OR CTP input is its chiplet's pull of the wire, a P2P CTP
  // input its request pad at the port's polarity, and an internal input its
  // CLA request.
  function bit [31:0] input_vector();
    bit [31:0] all_ctp = (32'd1 << XtrigNumCtp) - 1;
    bit [31:0] p2p = p_sequencer.m_xtrig_ctp_shadow.p2p_mask();
    bit [31:0] inverted = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
    bit [31:0] wire_or_input = window_last["xtrig_ctp_wire_ext_assert"] & ~p2p;
    bit [31:0] p2p_input = (window_last["xtrig_ctp_req_in_din"] ^ inverted) & p2p;
    bit [31:0] int_input = window_last["xtrig_ctm_dst_req"] & ((32'd1 << XtrigNumIntCt) - 1);
    return ((wire_or_input | p2p_input) & all_ctp) | (int_input << XtrigNumCtp);
  endfunction

  // Sample `name` from the current clock on, one sample per clock for up to
  // P2pPhaseMaxCycles clocks, until its `mask` bits XOR `invert` read
  // `expected`. `level` is the last such sample and `cycle` the clock it
  // matched at: 1 for the current clock, -1 for none.
  task wait_p2p_phase(input string name, input bit [31:0] mask, input bit [31:0] expected,
                      input bit [31:0] invert, output bit [31:0] level, output int cycle);
    cycle = -1;
    for (int c = 1; c <= P2pPhaseMaxCycles; c++) begin
      level = (xtrig_pin(name) ^ invert) & mask;
      if (level == expected) begin
        cycle = c;
        return;
      end
      wait_sys_cycles(1);
    end
  endtask

  // Wait for every selected output to request; acknowledge P2P CTP outputs
  // and see them idle again. The bench is the four-phase responder of a P2P
  // CTP output. The request holds while CT_Ack_in is withheld for a seeded
  // P2pHoldMinCycles..P2pHoldMaxCycles and drops within P2pPhaseMaxCycles
  // of CT_Ack_in. CT_Ack_in stays asserted for a further seeded hold,
  // through which BUSY stays set and the request stays released, and BUSY
  // clears within P2pPhaseMaxCycles of the CT_Ack_in release.
  task await_selected_outputs(bit [31:0] output_mask, int unsigned mode, string label);
    bit [31:0] ctp_outputs = project_ctp_mask(output_mask);
    bit [31:0] int_outputs = project_internal_mask(output_mask);
    if (ctp_outputs != 0 && mode == CtpModeP2p) begin
      bit [31:0] active = pad_level(ctp_outputs, 1'b1);
      bit [31:0] all_idle = p_sequencer.m_xtrig_ctp_shadow.invert_mask();
      bit [31:0] held = ctp_outputs;
      bit [31:0] requested, busy;
      int fell_at, cleared_at;
      string under_ack;
      int unsigned holdoff = $urandom_range(P2pHoldMaxCycles, P2pHoldMinCycles);
      int unsigned ack_hold = $urandom_range(P2pHoldMaxCycles, P2pHoldMinCycles);
      wait_signal_mask("xtrig_ctp_req_out_dout", ctp_outputs, active, 60, {label, ".ctp"});
      for (int unsigned c = 0; c < holdoff; c++) begin
        wait_sys_cycles(1);
        held &= xtrig_pin("xtrig_ctp_req_out_dout") ^ all_idle;
      end
      check_evidence(ChkSignal, {label, ".ctp_held"}, 64'(held), 64'(ctp_outputs), $sformatf(
                     "acknowledge withheld %0d cycles", holdoff));
      xtrig_vif.xtrig_ctp_ack_in_din <= XtrigNumCtp'((all_idle & ~ctp_outputs) | active);
      wait_sys_cycles(1);
      wait_p2p_phase("xtrig_ctp_req_out_dout", ctp_outputs, '0, all_idle, requested, fell_at);
      check_evidence(ChkSignal, {label, ".ctp_released_on_ack"}, 64'(ctp_outputs & ~requested),
                     64'(ctp_outputs), $sformatf("fell %0d cycles after CT_Ack_in", fell_at));
      busy = ctp_outputs;
      repeat (ack_hold) begin
        wait_sys_cycles(1);
        busy &= xtrig_pin("xtrig_ctp_busy");
        requested |= (xtrig_pin("xtrig_ctp_req_out_dout") ^ all_idle) & ctp_outputs;
      end
      under_ack = $sformatf(
          "CT_Ack_in held %0d cycles after the fall busy=0x%0h requested=0x%0h",
          ack_hold,
          busy,
          requested
      );
      check_evidence(ChkSignal, {label, ".ctp_busy_under_ack"}, 64'(busy & ~requested),
                     64'(ctp_outputs), under_ack);
      xtrig_vif.xtrig_ctp_ack_in_din <= XtrigNumCtp'(all_idle);
      wait_sys_cycles(1);
      wait_p2p_phase("xtrig_ctp_busy", ctp_outputs, '0, '0, busy, cleared_at);
      check_evidence(ChkSignal, {label, ".ctp_done"}, 64'(busy), 64'd0, $sformatf(
                     "BUSY cleared %0d cycles after CT_Ack_in released", cleared_at));
    end else if (ctp_outputs != 0) begin
      wait_window_fired("xtrig_ctp_req_out_dout_en", ctp_outputs, 60, {label, ".ctp"});
    end
    if (int_outputs != 0)
      wait_window_fired("xtrig_ctm_src_req", int_outputs, 60, {label, ".internal"});
  endtask

  // Judge one route: selected outputs fire, the window matches the model,
  // nothing else moves. Every predicted output starts requesting once, after
  // the window's first input, and no other output requests. The wire-OR
  // sources of `input_mask` (every internal source, and the CTP sources
  // unless `mode` is point-to-point) also receive their own assertion once,
  // at the receive latency. With `await_outputs` clear the selected outputs
  // have already fired inside the window and only the drain tail is waited
  // for.
  task check_output_mask(bit [31:0] output_mask, int unsigned mode, bit [31:0] predicted,
                         string label, int unsigned drain_cycles = IsolationTailCycles,
                         bit [31:0] input_mask = '0, bit await_outputs = 1'b1);
    bit [31:0] intent = output_mask & CtmSelectMask;
    bit [31:0] fired;
    bit [31:0] ctp_sources = (mode == CtpModeP2p) ? '0 : project_ctp_mask(input_mask);
    int unsigned ports[$];
    int inputs_seen[int unsigned];
    int input_at = -1;
    if (await_outputs) await_selected_outputs(output_mask, mode, label);
    wait_sys_cycles(drain_cycles);
    stop_activity_window();
    fired = fired_vector();
    check_receive_edges(ctp_sources & ~p_sequencer.m_xtrig_ctp_shadow.p2p_mask(),
                        project_internal_mask(input_mask), label);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "XTRIG WINDOW %s fired=0x%07h predicted=0x%07h intent=0x%07h p2p_ctps=0x%04h cycles=%0d",
            label, fired, predicted & CtmSelectMask, intent,
            p_sequencer.m_xtrig_ctp_shadow.p2p_mask(), window_cycles), UVM_LOW)
    // Reference model against the DUT: the outputs that fired anywhere in the
    // window, and only those, are the model's prediction.
    check_evidence(ChkRouteModel, {label, ".model_route"}, 64'(fired),
                   64'(predicted & CtmSelectMask), $sformatf("mode=%0d", mode));
    // One group of inputs pulsed in the same cycles reaches each output a
    // window predicts, so the output asserts once, and only after the
    // window's first input.
    if (window_first_seen.exists("ctm_port_input"))
      inputs_seen = window_first_seen["ctm_port_input"];
    foreach (inputs_seen[b])
      if (input_at < 0 || inputs_seen[b] < input_at) input_at = inputs_seen[b];
    port_bits((predicted | fired) & CtmSelectMask, ports);
    foreach (ports[i]) begin
      int request_at = window_first_rise("ctm_port_request", ports[i]);
      check_evidence(ChkRouteModel, $sformatf("%s.port%0d.asserts", label, ports[i]),
                     64'(window_rise_count("ctm_port_request", ports[i])), 64'(predicted[ports[i]]),
                     $sformatf("mode=%0d", mode));
      if (fired[ports[i]])
        check_evidence(ChkRouteModel, $sformatf("%s.port%0d.after_input", label, ports[i]),
                       64'(input_at >= 0 && input_at < request_at), 64'd1, $sformatf(
                       "input@%0d request@%0d", input_at, request_at));
    end
    // Isolation: no unselected output fired anywhere in the window, and the
    // selected outputs are idle again at its end.
    check_evidence(ChkIsolation, {label, ".unselected_quiet"}, 64'(fired & ~intent), 64'd0,
                   $sformatf("mode=%0d", mode));
    check_evidence(ChkIsolation, {label, ".selected_deasserted"}, 64'(level_vector() & intent),
                   64'd0, $sformatf("mode=%0d", mode));
  endtask

  // Pulse `input_mask` through the programmed routes and judge the output
  // window. The model programmed alongside the CSRs predicts the DUT output
  // vector of this pulse; +DTP_XTRIG_CHECKER_NEGATIVE corrupts the model so
  // the comparison against the DUT must fail.
  task run_route_window(bit [31:0] input_mask, bit [31:0] intent_mask, int unsigned mode,
                        string label, int unsigned drain_cycles = IsolationTailCycles,
                        int unsigned pulse_cycles = 2, int unsigned lead_cycles = 0);
    bit [31:0] predicted = ctm_model.route(input_mask);
    open_route_window();
    wait_sys_cycles(lead_cycles);
    drive_input_mask(input_mask, mode, pulse_cycles, label);
    check_output_mask(intent_mask, mode, predicted, label, drain_cycles, input_mask);
  endtask

  // Idle the inputs and start an activity window over the route observables.
  task open_route_window();
    idle_inputs();
    wait_sys_cycles(2);
    start_activity_window();
  endtask

  task verify_route(int unsigned input_port, bit [31:0] output_mask, int unsigned mode,
                    string label);
    verify_route_mask(32'd1 << input_port, output_mask, mode, label);
  endtask

  // Program every output of `output_mask` with `input_mask`, pulse the
  // inputs together, judge.
  task verify_route_mask(bit [31:0] input_mask, bit [31:0] output_mask, int unsigned mode,
                         string label, int unsigned pulse_cycles = 2, int unsigned lead_cycles = 0);
    configure_ctp_modes_for_route_mask(input_mask, output_mask, mode);
    program_routes(input_mask, output_mask, label);
    run_route_window(input_mask, output_mask, mode, label, IsolationTailCycles, pulse_cycles,
                     lead_cycles);
  endtask

  // Route one internal CT to a wire-OR CTP: window, model, isolation, one
  // pulse of width stretch+1. The data pad holds the level the port pulls
  // its wire to (INVERT) at every cycle of the window, the enable pulse
  // included.
  task verify_wire_or_pulse(int unsigned ctp_idx, int unsigned int_idx, bit [15:0] stretch,
                            bit invert, string label);
    int unsigned width, pulses;
    program_ctp(ctp_idx, CtpModeWireOr, invert, 1'b0, stretch);
    program_route(internal_ct_port(int_idx), 32'd1 << external_ctp_port(ctp_idx), label);
    fork
      measure_mask_width(.name("xtrig_ctp_req_out_dout_en"), .mask(32'd1 << ctp_idx), .width(width),
                         .pulses(pulses), .timeout_cycles(stretch + 60));
      run_route_window(32'd1 << internal_ct_port(int_idx), 32'd1 << external_ctp_port(ctp_idx),
                       CtpModeWireOr, label, IsolationTailCycles + stretch);
    join
    check_evidence(ChkStretch, {label, ".width"}, 64'(width), 64'(stretch) + 64'd1, $sformatf(
                   "ctp=%0d", ctp_idx));
    check_evidence(ChkStretch, {label, ".pulses"}, 64'(pulses), 64'd1, $sformatf("ctp=%0d", ctp_idx
                   ));
    check_evidence(ChkSignal, {label, ".wire_polarity_any"},
                   64'(window_activity["xtrig_ctp_req_out_dout"][ctp_idx]),
                   64'(DtpWireOrAssert[invert]), $sformatf("ctp=%0d invert=%0d", ctp_idx, invert));
    check_evidence(ChkSignal, {label, ".wire_polarity_all"},
                   64'(window_hold["xtrig_ctp_req_out_dout"][ctp_idx]),
                   64'(DtpWireOrAssert[invert]), $sformatf("ctp=%0d invert=%0d", ctp_idx, invert));
  endtask

  // Observable and bit that carry a wire-OR request of `output_port`.
  function void request_observable(int unsigned output_port, ref string sig,
                                   ref int unsigned bit_idx);
    if (is_ctp_port(output_port)) begin
      sig     = "xtrig_ctp_req_out_dout_en";
      bit_idx = output_port;
    end else begin
      sig     = "xtrig_ctm_src_req";
      bit_idx = int_idx_from_port(output_port);
    end
  endfunction

  // Every CT_SRC select reads its reset value.
  task check_all_ctm_cleared(string label);
    bit [31:0] observed;
    for (int unsigned src_idx = 0; src_idx < XtrigNumCtmPorts; src_idx++) begin
      csr_read(ctm_config_addr(src_idx), observed, $sformatf("%s.ctm%0d", label, src_idx));
      check_evidence(ChkCsr, $sformatf("%s.ctm%0d.default", label, src_idx),
                     64'(observed & CtmSelectMask), 64'(DtpCtmSelectDefault & CtmSelectMask),
                     $sformatf("addr=0x%03h", ctm_config_addr(src_idx)));
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
