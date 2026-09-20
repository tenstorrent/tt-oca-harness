// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Debug-TDR helper base sequence for the DTP SV-UVM flow — the SV analogue
// of the cocotb dtp_debug_tdr_base_test_seq. Layers TMP_STATUS, IC_RESET,
// DEBUG_CONTROL, and CAPS TDR access/pack/decode helpers plus the
// debug-observable sampling surface on top of the basic-JTAG family layer
// (dtp_jtag_base_test_seq); the TDR accesses are dtp_jtag_read_tdr_seq /
// dtp_jtag_write_tdr_seq operations started through the base virtual
// sequence:
//
//   * DEBUG_CONTROL[4:0]: writable boot_stall/boot_stall_ovrd/
//     cla_clock_stop_en/jtag_clock_stop bits plus the read-only
//     cla_clock_stop status bit;
//   * IC_RESET[6:0]: reset_hold plus one {enable, control} pair per
//     default slice in EXT, SEP, SMC order;
//   * JTAG_CAPS[59:0] / *_JTAG2AXI_CAPS[13:0]: read-only capability TDRs
//     compared against the bench's declared DTP configuration (dtp_types);
//   * pin observables through dtp_tb_if (stop_clks, cla_clock_stop_en,
//     boot-stall pair, flattened IC_RESET slices) with a bounded poll —
//     stop_clks passes through a 2-flop synchronizer and an output flop,
//     so clock-stop checks poll instead of assuming an immediate value —
//     and the CLA clock-stop request vector drive.
//
// All comparisons land named family evidence (CHK-DBG-TDR / CHK-DBG-PIN /
// CHK-CAPS / CHK-CAPS-RO plus the shared TMP ids), so the group honors the
// +DTP_JTAG_FAMILY_CHECKER_NEGATIVE falsifiability hook.

class dtp_debug_tdr_base_test_seq extends dtp_jtag_base_test_seq;
  `uvm_object_utils(dtp_debug_tdr_base_test_seq)

  // Register sizes: DEBUG_CONTROL from the interface-unit instruction table;
  // IC_RESET is reset_hold plus one {enable, control} pair per port
  // ("IC_RESET Support" table), one SMC, one SEP, and one external port in
  // the bench's DTP configuration; JTAG_CAPS[59:0] ("JTAG Capabilities"
  // table) and *_JTAG2AXI_CAPS[13:0] from the PTAP document.
  localparam int unsigned DebugControlLen = 5;
  localparam int unsigned IcResetPorts = DtpNumSmcIcReset + DtpNumSepIcReset + DtpNumExtIcReset;
  localparam int unsigned IcResetLen = 2 * IcResetPorts + 1;
  localparam int unsigned JtagCapsLen = 60;
  localparam int unsigned Jtag2AxiCapsLen = DtpJtag2AxiCapsLen;
  localparam int unsigned NumClkStopReq = DtpNumClkStopReq;

  // DEBUG_CONTROL bit positions.
  localparam int unsigned DbgBootStallBit = 0;
  localparam int unsigned DbgBootStallOvrdBit = 1;
  localparam int unsigned DbgClaClockStopEnBit = 2;
  localparam int unsigned DbgJtagClockStopBit = 3;
  localparam int unsigned DbgClaClockStopBit = 4;

  // IC_RESET slice order (bit 0 = reset_hold; then {enable, control}
  // pairs): EXT=0, SEP=1, SMC=2.
  typedef enum int unsigned {
    ICR_EXT = 0,
    ICR_SEP = 1,
    ICR_SMC = 2
  } icr_port_e;

  // Observables already reported X in this pass (one error per name).
  protected bit m_x_reported[string];

  function new(string name = "dtp_debug_tdr_base_test_seq");
    super.new(name);
  endfunction

  // --- generic TDR access (one reusable operation each) ---------------------
  task read_tdr64(input bit [IrWidth-1:0] instr, input int unsigned width,
                  output bit [63:0] observed, input bit [63:0] shift_value = '0);
    read_tdr(instr, width, observed, shift_value);
  endtask

  task write_tdr64(input bit [IrWidth-1:0] instr, input int unsigned width, input bit [63:0] value);
    write_tdr(instr, width, value);
  endtask

  // --- TMP_STATUS (read helper lives in the command library) --------------
  task write_tmp_status(bit [1:0] value);
    write_tdr64(6'(TMP_STATUS_INSTR), TmpStatusLen, 64'(value));
  endtask

  // --- DEBUG_CONTROL --------------------------------------------------------
  static function bit [63:0] pack_debug_control(bit boot_stall = 1'b0, bit boot_stall_ovrd = 1'b0,
                                                bit cla_clock_stop_en = 1'b0,
                                                bit jtag_clock_stop = 1'b0);
    return (64'(boot_stall)        << DbgBootStallBit)
             | (64'(boot_stall_ovrd)   << DbgBootStallOvrdBit)
             | (64'(cla_clock_stop_en) << DbgClaClockStopEnBit)
             | (64'(jtag_clock_stop)   << DbgJtagClockStopBit);
  endfunction

  task read_debug_control(output bit [63:0] observed, input bit [63:0] shift_value = '0);
    read_tdr64(6'(DEBUG_CONTROL_INSTR), DebugControlLen, observed, shift_value);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "DEBUG_CONTROL raw=0x%02h cla_stop=%0d jtag_stop=%0d cla_stop_en=%0d boot_ovrd=%0d boot_stall=%0d",
            observed, observed[DbgClaClockStopBit], observed[DbgJtagClockStopBit],
            observed[DbgClaClockStopEnBit], observed[DbgBootStallOvrdBit],
            observed[DbgBootStallBit]), UVM_MEDIUM)
  endtask

  task write_debug_control(bit [63:0] value);
    write_tdr64(6'(DEBUG_CONTROL_INSTR), DebugControlLen, value);
  endtask

  // Compare one decoded DEBUG_CONTROL bit through the family recorder.
  function void check_debug_control_bit(bit [63:0] value, int unsigned bit_pos, bit expected,
                                        string name, string context_s = "");
    family_check("CHK-DBG-TDR", name, 64'(value[bit_pos]), 64'(expected), context_s);
  endfunction

  // --- IC_RESET --------------------------------------------------------------
  // Pack the IC_RESET TDR: enable/control arrays indexed by icr_port_e
  // (the DTP write-1-inactive convention lives at the call sites).
  static function bit [63:0] pack_ic_reset(bit reset_hold, bit [IcResetPorts-1:0] reset_enable,
                                           bit [IcResetPorts-1:0] reset_control);
    bit [63:0] value = 64'(reset_hold);
    for (int unsigned p = 0; p < IcResetPorts; p++) begin
      value |= 64'(reset_enable[p]) << (1 + 2 * p);
      value |= 64'(reset_control[p]) << (2 + 2 * p);
    end
    return value;
  endfunction

  task read_ic_reset(output bit [63:0] observed, input bit [63:0] shift_value = '0);
    read_tdr64(6'(IC_RESET_INSTR), IcResetLen, observed, shift_value);
    `uvm_info(get_type_name(), $sformatf("IC_RESET raw=0b%07b reset_hold=%0d", observed,
                                         observed[0]), UVM_MEDIUM)
  endtask

  task write_ic_reset(input bit reset_hold, input bit [IcResetPorts-1:0] reset_enable,
                      input bit [IcResetPorts-1:0] reset_control, output bit [63:0] packed_value);
    packed_value = pack_ic_reset(reset_hold, reset_enable, reset_control);
    write_tdr64(6'(IC_RESET_INSTR), IcResetLen, packed_value);
  endtask

  // --- CAPS TDRs ---------------------------------------------------------------
  // Expected JTAG_CAPS of the DTP configuration the bench instantiates
  // (dtp_types bench-configuration constants), packed per the "JTAG
  // Capabilities" table of the PTAP document: every instruction family
  // enabled, one IC_RESET slice per port.
  static function bit [63:0] expected_jtag_caps();
    return (64'(DtpXtrigNumIntCt) << 54)  // num_xtrig_int_ct
    | (64'(DtpXtrigNumCtp) << 48)  // num_xtrig_ctp
    | (64'(DtpNumExtraStaps) << 44)  // num_xtra_stap
    | (64'd1 << 43)  // stap_io_en
    | (64'd1 << 42)  // sep_dbg_en
    | (64'd1 << 41)  // smc_dbg_en
    | (64'(DtpNumSmcIcReset) << 33)  // num_smc_ic_rst
    | (64'(DtpNumSepIcReset) << 25)  // num_sep_ic_rst
    | (64'(DtpNumExtIcReset) << 17)  // num_ext_ic_rst
    | (64'd1 << 16)  // IC_RST_INST_EN
    | (64'd1 << 15)  // TMP_INST_EN
    | (64'd1 << 14)  // RUNBIST_INST_EN
    | (64'd1 << 13)  // HIGHZ_INST_EN
    | (64'd1 << 12)  // CLAMP_INST_EN
    | (64'd1 << 11)  // INTEST_INST_EN
    | (64'd1 << 10)  // EXTEST_PULSE_EN
    | (64'd1 << 9)  // EXTEST_TRAIN_EN
    | (64'd1 << 8)  // BSR_INST_EN
    | 64'(DtpOchVer);  // och_ver
  endfunction

  static function bit [63:0] expected_jtag2axi_caps(bit bus_type, int unsigned addr_width,
                                                    int unsigned data_width_bits,
                                                    int unsigned rd_pl_depth = DtpJ2aPipelineDepth,
                                                    int unsigned wr_pl_depth = DtpJ2aPipelineDepth);
    int unsigned size_enc = $clog2(data_width_bits / 8);
    return (64'(rd_pl_depth) << 12)
             | (64'(wr_pl_depth) << 10)
             | (64'(size_enc)    << 7)
             | (64'(addr_width & 'h3F) << 1)
             | 64'(bus_type);
  endfunction

  task read_caps_tdr(input bit [IrWidth-1:0] instr, input int unsigned width,
                     output bit [63:0] observed);
    read_tdr64(instr, width, observed);
  endtask

  // Repeated CAPS reads must return one stable value.
  task check_caps_multi_read(input bit [IrWidth-1:0] instr, input int unsigned width,
                             input bit [63:0] expected, input string label,
                             input int unsigned count = 5);
    bit [63:0] observed;
    for (int unsigned idx = 1; idx <= count; idx++) begin
      read_caps_tdr(instr, width, observed);
      family_check("CHK-CAPS", {label, " multi-read"}, observed, expected, $sformatf(
                   "read=%0d/%0d", idx, count));
    end
  endtask

  // Directed plus seeded random write attempts into a read-only CAPS TDR
  // must never change the readback.
  task check_caps_read_only_patterns(input bit [IrWidth-1:0] instr, input int unsigned width,
                                     input bit [63:0] expected, input string label);
    bit [63:0] patterns[$];
    bit [63:0] observed;
    patterns = {
      64'h0,
      bit_mask(width),
      64'h5555_5555_5555_5555 & bit_mask(width),
      64'hAAAA_AAAA_AAAA_AAAA & bit_mask(width),
      64'h1234_5678_9ABC_DEF0 & bit_mask(width)
    };
    for (int unsigned r = 0; r < random_count; r++)
      patterns.push_back({$urandom, $urandom} & bit_mask(width));
    foreach (patterns[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: %s write-attempt pattern=0x%0h",
                idx + 1,
                patterns.size(),
                label,
                patterns[idx]
                ), UVM_LOW)
      write_tdr64(instr, width, patterns[idx]);
      read_caps_tdr(instr, width, observed);
      family_check("CHK-CAPS-RO", {label, " read-only"}, observed, expected, $sformatf(
                   "pattern=0x%0h", patterns[idx]));
    end
  endtask

  // Common JTAG2AXI_CAPS flow for one bridge of the dtp_types geometry table:
  // value/field compare, multi-read stability, read-only sweep, and
  // instruction-switch re-reads.
  task check_jtag2axi_caps(input dtp_j2a_target_t t, input string label);
    bit [IrWidth-1:0] instr = IrWidth'(t.caps_instr);
    bit bus_type = t.bus_type;
    int unsigned addr_width = t.addr_width;
    int unsigned data_width_bits = t.data_width;
    bit [63:0] expected = expected_jtag2axi_caps(bus_type, addr_width, data_width_bits);
    bit [63:0] value, reread;
    read_caps_tdr(instr, Jtag2AxiCapsLen, value);
    `uvm_info(
        get_type_name(),
        $sformatf("%s raw=0x%04h rd_pl=%0d wr_pl=%0d size=%0d addr_w=%0d bus_type=%0d", label,
                  value, value[13:12], value[11:10], value[9:7], value[6:1], value[0]), UVM_LOW)
    family_check("CHK-CAPS", label, value, expected, "packed value");
    family_check("CHK-CAPS", {label, ".bus_type"}, 64'(value[0]), 64'(bus_type));
    family_check("CHK-CAPS", {label, ".addr_width"}, 64'(value[6:1]), 64'(addr_width & 'h3F));
    family_check("CHK-CAPS", {label, ".data_size"}, 64'(value[9:7]), 64'($clog2(data_width_bits / 8
                 )));
    family_check("CHK-CAPS", {label, ".wr_pl_depth"}, 64'(value[11:10]), 64'(DtpJ2aPipelineDepth));
    family_check("CHK-CAPS", {label, ".rd_pl_depth"}, 64'(value[13:12]), 64'(DtpJ2aPipelineDepth));
    check_caps_multi_read(instr, Jtag2AxiCapsLen, value, label);
    check_caps_read_only_patterns(instr, Jtag2AxiCapsLen, value, label);
    // Instruction switches must not disturb the stored capability value.
    load_ir(6'(IDCODE_INSTR));
    read_caps_tdr(instr, Jtag2AxiCapsLen, reread);
    family_check("CHK-CAPS", {label, " after IDCODE"}, reread, value);
    load_ir(6'(BYPASS_INSTR));
    read_caps_tdr(instr, Jtag2AxiCapsLen, reread);
    family_check("CHK-CAPS", {label, " after BYPASS"}, reread, value);
  endtask

  // --- pin observables through dtp_tb_if -----------------------------------
  // An X on a debug observable is an error once per name per pass: a zero
  // expectation would otherwise absorb it.
  function bit [63:0] sample_dbg_signal(string name);
    logic [63:0] sampled;
    case (name)
      "stop_clks":                sampled = 64'(tb_vif.stop_clks);
      "cla_clock_stop_en":        sampled = 64'(tb_vif.cla_clock_stop_en);
      "jtag_boot_stall":          sampled = 64'(tb_vif.jtag_boot_stall);
      "jtag_boot_stall_ovrd":     sampled = 64'(tb_vif.jtag_boot_stall_ovrd);
      "jtag_ic_reset_smc_ovrd":   sampled = 64'(tb_vif.jtag_ic_reset_smc_ovrd);
      "jtag_ic_reset_smc_ctrl_n": sampled = 64'(tb_vif.jtag_ic_reset_smc_ctrl_n);
      "jtag_ic_reset_sep_ovrd":   sampled = 64'(tb_vif.jtag_ic_reset_sep_ovrd);
      "jtag_ic_reset_sep_ctrl_n": sampled = 64'(tb_vif.jtag_ic_reset_sep_ctrl_n);
      "jtag_ic_reset_ext_ovrd":   sampled = 64'(tb_vif.jtag_ic_reset_ext_ovrd);
      "jtag_ic_reset_ext_ctrl_n": sampled = 64'(tb_vif.jtag_ic_reset_ext_ctrl_n);
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unknown debug observable '%s'", name))
        sampled = '0;
      end
    endcase
    if ($isunknown(sampled) && !m_x_reported.exists(name)) begin
      m_x_reported[name] = 1'b1;
      `uvm_error(get_type_name(), $sformatf("debug observable %s sampled X", name))
    end
    return sampled;
  endfunction

  // Single-sample observable compare through the family recorder.
  function void expect_dbg_signal(string name, bit expected, string context_s = "");
    family_check("CHK-DBG-PIN", name, sample_dbg_signal(name), 64'(expected), context_s);
  endfunction

  // The debug-TDR pin observables sample_dbg_signal resolves.
  static function void debug_output_names(output string names[$]);
    names = {
      "stop_clks",
      "cla_clock_stop_en",
      "jtag_boot_stall",
      "jtag_boot_stall_ovrd",
      "jtag_ic_reset_smc_ovrd",
      "jtag_ic_reset_smc_ctrl_n",
      "jtag_ic_reset_sep_ovrd",
      "jtag_ic_reset_sep_ctrl_n",
      "jtag_ic_reset_ext_ovrd",
      "jtag_ic_reset_ext_ctrl_n"
    };
  endfunction

  // Their values with DEBUG_CONTROL at 0x00 and IC_RESET at its all-ones
  // default (every slice enable inactive drives ovrd=0, ctrl_n=1).
  static function void debug_output_defaults(output bit [63:0] defaults[string]);
    string names[$];
    debug_output_names(names);
    foreach (names[i]) defaults[names[i]] = 64'd0;
    defaults["jtag_ic_reset_smc_ctrl_n"] = 64'd1;
    defaults["jtag_ic_reset_sep_ctrl_n"] = 64'd1;
    defaults["jtag_ic_reset_ext_ctrl_n"] = 64'd1;
  endfunction

  // Sample every debug-TDR pin observable by name.
  function void snapshot_debug_outputs(output bit [63:0] snapshot[string]);
    string names[$];
    debug_output_names(names);
    foreach (names[i]) snapshot[names[i]] = sample_dbg_signal(names[i]);
  endfunction

  // One comparison per debug-TDR pin observable.
  function void check_debug_outputs(string check_id, bit [63:0] observed[string],
                                    bit [63:0] expected[string], string context_s);
    foreach (expected[name])
    family_check(check_id, name, observed[name], expected[name], context_s);
  endfunction

  // Bounded observable poll: stop_clks passes through a 2-flop
  // synchronizer and an output flop, so clock-stop checks poll across
  // system cycles instead of assuming a fixed immediate value. The final
  // sample lands the evidence either way (a mismatch after the budget
  // records a FAIL).
  task wait_for_signal_value(string name, bit expected, input int unsigned cycles = 6,
                             input string context_s = "");
    bit [63:0] last;
    for (int unsigned cycle = 0; cycle <= cycles; cycle++) begin
      last = sample_dbg_signal(name);
      if (last == 64'(expected)) break;
      if (cycle < cycles) wait_sys_cycles(1);
    end
    family_check("CHK-DBG-PIN", name, last, 64'(expected), context_s);
  endtask

  // Drive the CLA clock-stop request vector exposed through dtp_tb_if.
  task set_clk_stop_requests(bit [NumClkStopReq-1:0] value, int unsigned cycles = 4);
    tb_vif.xtrig_clk_stop_req <= value;
    wait_sys_cycles(cycles);
    `uvm_info(get_type_name(), $sformatf("xtrig_clk_stop_req=0x%03h", value), UVM_MEDIUM)
  endtask

endclass : dtp_debug_tdr_base_test_seq
