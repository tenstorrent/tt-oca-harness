// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP bench constants, DUT geometry, and pure codec functions shared by the
// environment (reference models, virtual sequencer, cfgs) and the
// sequence library (reusable operations, scenario helpers). The cocotb twin
// is env/dtp_types.py plus env/dtp_xtrig_types.py. Every value the checks
// expect has a source other than the RTL: the instruction encodings and the
// TAP-state encoding are transcribed from the JTAG interface-unit and PTAP
// documents, the cross-trigger register offsets and field masks come from the
// generated cross_trigger_* collateral and its CSR windows and port counts from
// the cross-trigger network document, the JTAG2AXI bridge geometries are the
// values each bridge publishes in its DTMCS and sbcs registers (compared with
// the DUT every pass by the geometry gate), and the TDR field layouts come
// from the PTAP document; the few bench-only constants cite their source. No class
// lives here: everything is a package-scope type, constant, or
// `function automatic`.

// ---------------------------------------------------------------------------
// Primary TAP.
// ---------------------------------------------------------------------------

// "The JTAG interface unit uses 6-bit instruction encodings"
// (hw/ip/jtag/jtag_intf_unit/doc/interface.adoc, "Instruction Encodings").
localparam int unsigned DtpIrWidth = 6;

// Primary TAP instruction opcodes, one member per 6-bit encoding: the
// "Instruction Encodings" table of hw/ip/jtag/jtag_intf_unit/doc/interface.adoc
// (the PTAP document's own table lists the same encodings for the instructions
// it defines). Member names are the table's names with an _INSTR suffix; the
// two BYPASS rows and the encodings without a row carry the encoding. Both
// tables map every encoding without a row to BYPASS.
typedef enum logic [DtpIrWidth-1:0] {
  BYPASS_ALT_INSTR                                = 6'h00,
  IDCODE_INSTR                                    = 6'h01,
  RUNBIST_INSTR                                   = 6'h02,
  SAMPLE_PRELOAD_INSTR                            = 6'h03,
  EXTEST_INSTR                                    = 6'h04,
  EXTEST_TRAIN_INSTR                              = 6'h05,
  EXTEST_PULSE_INSTR                              = 6'h06,
  CLAMP_INSTR                                     = 6'h07,
  HIGHZ_INSTR                                     = 6'h08,
  INTEST_INSTR                                    = 6'h09,
  CLAMP_HOLD_INSTR                                = 6'h0A,
  CLAMP_RELEASE_INSTR                             = 6'h0B,
  TMP_STATUS_INSTR                                = 6'h0C,
  IC_RESET_INSTR                                  = 6'h0D,
  TAP_3DCR_INSTR                                  = 6'h0E,
  UNDEFINED_BYPASS_0F_INSTR                       = 6'h0F,
  // "Reserved for RISC-V" (0x10-0x17): no instruction, so BYPASS.
  RISCV_RESERVED_0_INSTR                          = 6'h10,
  RISCV_RESERVED_1_INSTR                          = 6'h11,
  RISCV_RESERVED_2_INSTR                          = 6'h12,
  RISCV_RESERVED_3_INSTR                          = 6'h13,
  RISCV_RESERVED_4_INSTR                          = 6'h14,
  RISCV_RESERVED_5_INSTR                          = 6'h15,
  RISCV_RESERVED_6_INSTR                          = 6'h16,
  RISCV_RESERVED_7_INSTR                          = 6'h17,
  DEBUG_CONTROL_INSTR                             = 6'h18,
  JTAG_CAPS_INSTR                                 = 6'h19,
  SELECT_IJTAG_INSTR                              = 6'h1A,
  // JTAG2AXI bridges: a DTMCS TDR and a DMI TDR each.
  SMC_OTP_DTMCS_INSTR                             = 6'h1B,
  SMC_OTP_DMI_INSTR                               = 6'h1C,
  SEP_OTP_DTMCS_INSTR                             = 6'h1D,
  SEP_OTP_DMI_INSTR                               = 6'h1E,
  SMC_DTMCS_INSTR                                 = 6'h1F,
  SMC_DMI_INSTR                                   = 6'h20,
  // No row for 0x21-0x3C: BYPASS.
  UNDEFINED_BYPASS_21_INSTR                       = 6'h21,
  UNDEFINED_BYPASS_22_INSTR                       = 6'h22,
  UNDEFINED_BYPASS_23_INSTR                       = 6'h23,
  UNDEFINED_BYPASS_24_INSTR                       = 6'h24,
  UNDEFINED_BYPASS_25_INSTR                       = 6'h25,
  UNDEFINED_BYPASS_26_INSTR                       = 6'h26,
  UNDEFINED_BYPASS_27_INSTR                       = 6'h27,
  UNDEFINED_BYPASS_28_INSTR                       = 6'h28,
  UNDEFINED_BYPASS_29_INSTR                       = 6'h29,
  UNDEFINED_BYPASS_2A_INSTR                       = 6'h2A,
  UNDEFINED_BYPASS_2B_INSTR                       = 6'h2B,
  UNDEFINED_BYPASS_2C_INSTR                       = 6'h2C,
  UNDEFINED_BYPASS_2D_INSTR                       = 6'h2D,
  UNDEFINED_BYPASS_2E_INSTR                       = 6'h2E,
  UNDEFINED_BYPASS_2F_INSTR                       = 6'h2F,
  UNDEFINED_BYPASS_30_INSTR                       = 6'h30,
  UNDEFINED_BYPASS_31_INSTR                       = 6'h31,
  UNDEFINED_BYPASS_32_INSTR                       = 6'h32,
  UNDEFINED_BYPASS_33_INSTR                       = 6'h33,
  UNDEFINED_BYPASS_34_INSTR                       = 6'h34,
  UNDEFINED_BYPASS_35_INSTR                       = 6'h35,
  UNDEFINED_BYPASS_36_INSTR                       = 6'h36,
  UNDEFINED_BYPASS_37_INSTR                       = 6'h37,
  UNDEFINED_BYPASS_38_INSTR                       = 6'h38,
  UNDEFINED_BYPASS_39_INSTR                       = 6'h39,
  UNDEFINED_BYPASS_3A_INSTR                       = 6'h3A,
  UNDEFINED_BYPASS_3B_INSTR                       = 6'h3B,
  UNDEFINED_BYPASS_3C_INSTR                       = 6'h3C,
  ZERO_LENGTH_BYPASS_INSTR                        = 6'h3D,
  INV_BYPASS_INSTR                                = 6'h3E,
  BYPASS_INSTR                                    = 6'h3F
} dtp_jtag_instr_e;

// IEEE 1149.1 TAP controller states as the DUT exports them on
// jtag_ptap_state_o: the 16-bit one-hot encoding of the "TAP Controller State
// Machine" table in hw/ip/jtag/jtag_ptap/doc/architecture.adoc (bit index =
// the IEEE state number the shared VIP enumerates).
typedef enum logic [15:0] {
  TEST_LOGIC_RESET = 16'h0001,
  RUN_TEST_IDLE    = 16'h0002,
  SELECT_DR_SCAN   = 16'h0004,
  CAPTURE_DR       = 16'h0008,
  SHIFT_DR         = 16'h0010,
  EXIT1_DR         = 16'h0020,
  PAUSE_DR         = 16'h0040,
  EXIT2_DR         = 16'h0080,
  UPDATE_DR        = 16'h0100,
  SELECT_IR_SCAN   = 16'h0200,
  CAPTURE_IR       = 16'h0400,
  SHIFT_IR         = 16'h0800,
  EXIT1_IR         = 16'h1000,
  PAUSE_IR         = 16'h2000,
  EXIT2_IR         = 16'h4000,
  UPDATE_IR        = 16'h8000
} dtp_tap_state_e;

// The DUT is in a Shift state: one data bit moves through the selected register
// on every TCK cycle the exported state spends here.
function automatic bit dtp_tap_state_is_shift(logic [15:0] state, bit is_ir);
  return state === (is_ir ? SHIFT_IR : SHIFT_DR);
endfunction

// The bench configuration tb_top elaborates the DUT from (dtp_dv_cfg_pkg;
// dtp_dv_cfg.py parity): the identification IDCODE publishes, and the STAP
// count, IC_RESET slice widths, and version JTAG_CAPS publishes ("JTAG
// Capabilities" table, PTAP document); the cross-trigger counts are in the
// cross-trigger section below.
localparam bit [31:0] DtpDefaultIdcode = dtp_dv_cfg_pkg::Idcode;
localparam int unsigned DtpNumExtraStaps = dtp_dv_cfg_pkg::NumExtraStaps;
localparam int unsigned DtpNumSmcIcReset = dtp_dv_cfg_pkg::NumSmcIcReset;
localparam int unsigned DtpNumSepIcReset = dtp_dv_cfg_pkg::NumSepIcReset;
localparam int unsigned DtpNumExtIcReset = dtp_dv_cfg_pkg::NumExtIcReset;
localparam int unsigned DtpOchVer = int'(dtp_dv_cfg_pkg::OchVer);

// IC_RESET across Test-Logic-Reset ("PTAP IC_RESET fields" table, PTAP
// document): with reset_hold 0 a TLR keeps every reset_enable and
// reset_control bit, and reset_hold with them; with reset_hold 1 a TLR
// restores the reset image. TRST and POR restore every bit.
function automatic bit [63:0] dtp_ic_reset_after_tlr(bit reset_hold, bit [63:0] written,
                                                     bit [63:0] reset_image);
  return reset_hold ? reset_image : written;
endfunction

// Capture-IR loads the instruction shift register with 01 in its two LSBs
// (IEEE 1149.1 7.1.1) and zeros above (jtag_inst_reg), so an IR scan that
// reaches Update-IR without a Shift-IR cycle activates this opcode, the
// IDCODE instruction.
localparam bit [DtpIrWidth-1:0] DtpIrCapturePattern = DtpIrWidth'(2'b01);

// Scoreboard feature names: one dtp_<feature>_ref_model each (test cfg
// policy names them in required_features).
localparam string DtpFeatureIrDecode = "ir_decode";
localparam string DtpFeatureIdcode = "idcode";
localparam string DtpFeatureBypass = "bypass";
localparam string DtpFeatureXtrigCsr = "xtrig_csr";
localparam string DtpFeatureXtrigDecode = "xtrig_decode";
localparam string DtpFeatureJtag2axiReq = "jtag2axi_req";
localparam string DtpFeatureJtag2axiStatus = "jtag2axi_status";

// ---------------------------------------------------------------------------
// Debug-disable paths: the "DTP debug-disable paths" table of the DTP JTAG
// document (hw/sys/dtp/doc/jtag.adoc, "Debug Disable") binds each debug path
// to the active-high dbg_disable_i field that disables it. The document names
// the fields, not their bit positions, so the bench reaches every field by
// name through these functions: each driven disable vector and each gating
// prediction starts from a path.
// ---------------------------------------------------------------------------

typedef enum int unsigned {
  DTP_DBG_PATH_STAP_IO          = 0,
  DTP_DBG_PATH_STAP_SMC         = 1,
  DTP_DBG_PATH_STAP_SEP         = 2,
  DTP_DBG_PATH_STAP_EXTRA       = 3,
  DTP_DBG_PATH_STAP_HOST        = 4,
  DTP_DBG_PATH_DFT_SECURE       = 5,
  DTP_DBG_PATH_DFT_NONSECURE    = 6,
  DTP_DBG_PATH_DFD              = 7,
  DTP_DBG_PATH_SMC_JTAG2AXI     = 8,
  DTP_DBG_PATH_SMC_OTP_JTAG2AXI = 9,
  DTP_DBG_PATH_SEP_OTP_JTAG2AXI = 10
} dtp_dbg_path_e;

function automatic bit dtp_dbg_path_disabled(sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                             dtp_dbg_path_e p);
  case (p)
    DTP_DBG_PATH_STAP_IO:          return d.stap_io;
    DTP_DBG_PATH_STAP_SMC:         return d.stap_smc;
    DTP_DBG_PATH_STAP_SEP:         return d.stap_sep;
    DTP_DBG_PATH_STAP_EXTRA:       return d.stap_extra;
    DTP_DBG_PATH_STAP_HOST:        return d.stap_host;
    DTP_DBG_PATH_DFT_SECURE:       return d.dft_secure;
    DTP_DBG_PATH_DFT_NONSECURE:    return d.dft_nonsecure;
    DTP_DBG_PATH_DFD:              return d.dfd;
    DTP_DBG_PATH_SMC_JTAG2AXI:     return d.smc_jtag2axi;
    DTP_DBG_PATH_SMC_OTP_JTAG2AXI: return d.smc_otp_jtag2axi;
    default:                       return d.sep_otp_jtag2axi;
  endcase
endfunction

function automatic void dtp_dbg_path_set(ref sep_lifecycle_ctrl_pkg::dbg_disable_t d,
                                         input dtp_dbg_path_e p, input bit disabled = 1'b1);
  case (p)
    DTP_DBG_PATH_STAP_IO:          d.stap_io = disabled;
    DTP_DBG_PATH_STAP_SMC:         d.stap_smc = disabled;
    DTP_DBG_PATH_STAP_SEP:         d.stap_sep = disabled;
    DTP_DBG_PATH_STAP_EXTRA:       d.stap_extra = disabled;
    DTP_DBG_PATH_STAP_HOST:        d.stap_host = disabled;
    DTP_DBG_PATH_DFT_SECURE:       d.dft_secure = disabled;
    DTP_DBG_PATH_DFT_NONSECURE:    d.dft_nonsecure = disabled;
    DTP_DBG_PATH_DFD:              d.dfd = disabled;
    DTP_DBG_PATH_SMC_JTAG2AXI:     d.smc_jtag2axi = disabled;
    DTP_DBG_PATH_SMC_OTP_JTAG2AXI: d.smc_otp_jtag2axi = disabled;
    default:                       d.sep_otp_jtag2axi = disabled;
  endcase
endfunction

// The disable vector that disables exactly one path.
function automatic sep_lifecycle_ctrl_pkg::dbg_disable_t dtp_dbg_disable_only(dtp_dbg_path_e p);
  sep_lifecycle_ctrl_pkg::dbg_disable_t d = '0;
  dtp_dbg_path_set(d, p);
  return d;
endfunction

// ---------------------------------------------------------------------------
// JTAG2AXI bridges (dtp_types.py JTAG2AXI_TARGETS parity). Each bridge is a
// DTMCS TDR and a DMI TDR in front of a RISC-V Debug Module whose System Bus
// Access drives the bridge port (hw/ip/jtag/jtag_ptap/doc/architecture.adoc,
// "PTAP JTAG2AXI Support").
// ---------------------------------------------------------------------------

// DTMCS and DMI register widths ("PTAP JTAG2AXI DTMCS fields" and "PTAP
// JTAG2AXI DMI fields").
localparam int unsigned DtpDtmcsLen = 32;
localparam int unsigned DtpDmiLen = 41;
// DTMCS capture with no sticky DMI status: idle 7 (14:12), abits 7 (9:4),
// version 1 (3:0). dmistat is 11:10; an update with dmireset (16) clears the
// sticky DMI status.
localparam bit [31:0] DtpExpectedDtmcs = 32'h0000_7071;
localparam int unsigned DtpDtmcsDmistatLsb = 10;
localparam int unsigned DtpDtmcsDmiresetBit = 16;
localparam int unsigned DtpDtmcsDmihardresetBit = 17;
// TCK cycles from the Update-DR of a DMI read or write to the first DMI
// capture or update that finds it complete: the request crosses into the
// system clock domain and the response back through the bridge's two-phase
// CDCs, three synchronizer stages each, at a system clock no slower than TCK,
// with the simulation CDC delay on every crossing.
localparam int unsigned DtpDmiSettleTck = 24;
// TCK cycles from the Update-DR of a DMI read or write in which every DMI
// capture or update still finds it in progress, at any clock ratio: the
// request leaves on the next TCK cycle, and the response then passes a
// three-stage synchronizer and one more register in the TCK domain before
// the bridge state machine samples it.
localparam int unsigned DtpDmiBusyTck = 6;

// The DMI register: address 40:34, data 33:2, op 1:0.
typedef struct packed {
  bit [6:0]  address;
  bit [31:0] data;
  bit [1:0]  op;
} dtp_dmi_t;

// DMI op as written by the debugger.
typedef enum bit [1:0] {
  DTP_DMI_OP_NOP   = 2'd0,
  DTP_DMI_OP_READ  = 2'd1,
  DTP_DMI_OP_WRITE = 2'd2,
  DTP_DMI_OP_CLEAR = 2'd3
} dtp_dmi_op_e;

// DMI op as captured: the sticky status of the last operation.
typedef enum bit [1:0] {
  DTP_DMI_SUCCESS = 2'd0,
  DTP_DMI_FAILED  = 2'd2,
  DTP_DMI_BUSY    = 2'd3
} dtp_dmi_status_e;

// Debug Module register addresses ("PTAP JTAG2AXI Debug Module registers").
typedef enum bit [6:0] {
  DTP_DM_DMCONTROL  = 7'h10,
  DTP_DM_DMSTATUS   = 7'h11,
  DTP_DM_SBCS       = 7'h38,
  DTP_DM_SBADDRESS0 = 7'h39,
  DTP_DM_SBADDRESS1 = 7'h3A,
  DTP_DM_SBDATA0    = 7'h3C,
  DTP_DM_SBDATA1    = 7'h3D
} dtp_dm_reg_e;

// sbcs of the RISC-V debug specification 0.13.
typedef struct packed {
  bit [2:0] sbversion;
  bit [5:0] reserved;
  bit       sbbusyerror;
  bit       sbbusy;
  bit       sbreadonaddr;
  bit [2:0] sbaccess;
  bit       sbautoincrement;
  bit       sbreadondata;
  bit [2:0] sberror;
  bit [6:0] sbasize;
  bit       sbaccess128;
  bit       sbaccess64;
  bit       sbaccess32;
  bit       sbaccess16;
  bit       sbaccess8;
} dtp_sbcs_t;

// Which JTAG2AXI register a DR scan addressed, from the active instruction.
typedef enum int unsigned {
  DTP_J2A_SCAN_NONE = 0,
  DTP_J2A_SCAN_DTMCS,
  DTP_J2A_SCAN_DMI
} dtp_j2a_scan_kind_e;

typedef struct {
  string              name;
  ocah_axi_protocol_e protocol;
  dtp_jtag_instr_e    dtmcs_instr;
  dtp_jtag_instr_e    dmi_instr;
  int unsigned        addr_width;
  int unsigned        data_width;
  int unsigned        beat_bytes;
  // sbaccess of a full beat, the largest the bridge supports.
  int unsigned        default_size;
  // The debug path whose disable gates this bridge.
  dtp_dbg_path_e      dbg_path;
  // The bridge's bit in dtp_tb_if.sys_rst_on_ar_arm, j2a_b_hold and
  // j2a_r_hold.
  int unsigned        reset_arm_bit;
} dtp_j2a_target_t;

// Responder memory footprint (every slave agent; addresses wrap).
localparam int unsigned DtpJ2aTargetMemBytes = 65536;
// Evidence ID of the per-pass geometry gate every JTAG2AXI scenario records.
localparam string DtpJ2aGeometryCheckId = "CHK-J2A-GEOMETRY";
// Per-access bus request: exactly one completed transaction per bus access,
// the one the access asked for.
localparam string DtpJ2aBusReqCheckId = "CHK-J2A-BUS-REQ";
// The DMI status of every capture and the sberror and sbbusyerror of every
// completed access.
localparam string DtpJ2aFaultStatusCheckId = "CHK-J2A-FAULT-STATUS";
// The address and data of a DMI capture, and the fields of a DTMCS capture
// other than dmistat.
localparam string DtpJ2aDtmCaptureCheckId = "CHK-J2A-DTM-CAPTURE";

// One function per bridge: the widths come from the bench configuration
// tb_top elaborates the DUT with (dtp_dv_cfg_pkg), and the TDR opcodes from
// the interface-unit instruction table. The geometry gate compares each
// bridge's DTMCS and sbcs publication with them every pass. The SMC fabric
// bridge drives SMC jtag_axi_in_req_i, whose row in the SMC port table
// states a 56-bit address and 64-bit data.
function automatic dtp_j2a_target_t dtp_j2a_target(
    string name, ocah_axi_protocol_e protocol, dtp_jtag_instr_e dtmcs_instr,
    dtp_jtag_instr_e dmi_instr, int unsigned addr_width, int unsigned data_width,
    dtp_dbg_path_e dbg_path, int unsigned reset_arm_bit);
  dtp_j2a_target_t t;
  t.name         = name;
  t.protocol     = protocol;
  t.dtmcs_instr  = dtmcs_instr;
  t.dmi_instr    = dmi_instr;
  t.addr_width   = addr_width;
  t.data_width   = data_width;
  t.beat_bytes   = data_width / 8;
  t.default_size = $clog2(data_width / 8);
  t.dbg_path     = dbg_path;
  t.reset_arm_bit = reset_arm_bit;
  return t;
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_smc_otp();
  return dtp_j2a_target(
      "smc_otp",
      OCAH_AXI_PROTO_AXI4_LITE,
      SMC_OTP_DTMCS_INSTR,
      SMC_OTP_DMI_INSTR,
      dtp_dv_cfg_pkg::OtpAxilAddrWidth,
      dtp_dv_cfg_pkg::OtpAxilDataWidth,
      DTP_DBG_PATH_SMC_OTP_JTAG2AXI,
      1
  );
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_sep_otp();
  return dtp_j2a_target(
      "sep_otp",
      OCAH_AXI_PROTO_AXI4_LITE,
      SEP_OTP_DTMCS_INSTR,
      SEP_OTP_DMI_INSTR,
      dtp_dv_cfg_pkg::OtpAxilAddrWidth,
      dtp_dv_cfg_pkg::OtpAxilDataWidth,
      DTP_DBG_PATH_SEP_OTP_JTAG2AXI,
      2
  );
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_smc_axi();
  return dtp_j2a_target(
      "smc_axi",
      OCAH_AXI_PROTO_AXI4,
      SMC_DTMCS_INSTR,
      SMC_DMI_INSTR,
      dtp_dv_cfg_pkg::SmcAxiAddrWidth,
      dtp_dv_cfg_pkg::SmcAxiDataWidth,
      DTP_DBG_PATH_SMC_JTAG2AXI,
      0
  );
endfunction

// Target by name ("smc_otp", "sep_otp", "smc_axi"); any other name is a
// configuration defect.
function automatic dtp_j2a_target_t dtp_j2a_target_by_name(string name);
  case (name)
    "smc_axi": return dtp_j2a_target_smc_axi();
    "sep_otp": return dtp_j2a_target_sep_otp();
    "smc_otp": return dtp_j2a_target_smc_otp();
    default: begin
      `uvm_fatal("dtp_types", {"unknown JTAG2AXI bridge ", name})
      return dtp_j2a_target_smc_otp();
    end
  endcase
endfunction

// The bridge and register a 6-bit instruction selects; SCAN_NONE when the
// instruction is not a JTAG2AXI register.
function automatic dtp_j2a_scan_kind_e dtp_j2a_classify_instr(bit [DtpIrWidth-1:0] ir,
                                                              output dtp_j2a_target_t t);
  string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
  foreach (names[i]) begin
    t = dtp_j2a_target_by_name(names[i]);
    if (ir == t.dtmcs_instr) return DTP_J2A_SCAN_DTMCS;
    if (ir == t.dmi_instr) return DTP_J2A_SCAN_DMI;
  end
  return DTP_J2A_SCAN_NONE;
endfunction

function automatic int unsigned dtp_j2a_scan_len(dtp_j2a_scan_kind_e kind);
  return (kind == DTP_J2A_SCAN_DTMCS) ? DtpDtmcsLen : DtpDmiLen;
endfunction

function automatic bit [63:0] dtp_j2a_pack_dmi(bit [6:0] address, bit [31:0] data, bit [1:0] op);
  dtp_dmi_t dmi = '{address: address, data: data, op: op};
  return 64'(dmi);
endfunction

function automatic dtp_dmi_t dtp_j2a_unpack_dmi(bit [63:0] value);
  return dtp_dmi_t'(value[DtpDmiLen-1:0]);
endfunction

function automatic int unsigned dtp_j2a_size_bytes(int unsigned size);
  return 1 << size;
endfunction

function automatic bit [63:0] dtp_j2a_data_mask(int unsigned size);
  return ocah_rng::bit_mask(8 * dtp_j2a_size_bytes(size));
endfunction

function automatic bit [7:0] dtp_j2a_full_wstrb(int unsigned size);
  return 8'((1 << dtp_j2a_size_bytes(size)) - 1);
endfunction

// The data bits of the byte lanes a strobe enables.
function automatic bit [63:0] dtp_j2a_strobe_lanes(bit [7:0] strb);
  bit [63:0] lanes = '0;
  for (int unsigned lane = 0; lane < 8; lane++) if (strb[lane]) lanes[8*lane+:8] = 8'hFF;
  return lanes;
endfunction

// ---------------------------------------------------------------------------
// Scan network: iJTAG SIBs, STAP host ports, downstream STAP TAPs.
// ---------------------------------------------------------------------------

// Index order for the iJTAG SIBs and the STAP ports (TDI to TDO).
typedef enum int unsigned {
  IJ_DFT_SECURE = 0,
  IJ_DFT        = 1,
  IJ_DFD        = 2
} dtp_ijtag_sib_e;

typedef enum int unsigned {
  ST_IO     = 0,
  ST_SMC    = 1,
  ST_SEP    = 2,
  ST_EXTRA0 = 3
} dtp_stap_e;

// The debug path that gates each iJTAG SIB and each STAP host port ("DTP
// debug-disable paths" table).
function automatic dtp_dbg_path_e dtp_ijtag_sib_dbg_path(int unsigned sib);
  case (sib)
    int'(IJ_DFT_SECURE): return DTP_DBG_PATH_DFT_SECURE;
    int'(IJ_DFT):        return DTP_DBG_PATH_DFT_NONSECURE;
    default:             return DTP_DBG_PATH_DFD;
  endcase
endfunction

function automatic dtp_dbg_path_e dtp_stap_dbg_path(int unsigned stap);
  case (stap)
    int'(ST_IO):  return DTP_DBG_PATH_STAP_IO;
    int'(ST_SMC): return DTP_DBG_PATH_STAP_SMC;
    int'(ST_SEP): return DTP_DBG_PATH_STAP_SEP;
    default:      return DTP_DBG_PATH_STAP_EXTRA;
  endcase
endfunction

localparam int unsigned DtpIjtagSibCount = 3;
// Instrument stub widths behind each SIB (tb_top), dtp_ijtag_sib_e order:
// every subset of open SIBs sums to a distinct chain length.
localparam int unsigned DtpIjtagInstrumentWidths[DtpIjtagSibCount] = '{4, 5, 6};
// A latency-measuring scan shifts a marker word ahead of the chain's
// maintain image; the marker's MSB is set, so the stream's highest set bit
// lands at chain_len + DtpScanMarkerWidth - 1.
localparam int unsigned DtpScanMarkerWidth = 16;
localparam int unsigned DtpIjtagObserveScanWidth = 40;
localparam int unsigned DtpStapCount = 4;
// Host segment behind the extended STAP host scan interface (tb_top): a scan
// register that captures its own update register.
localparam int unsigned DtpStapHostSegmentWidth = 7;
localparam int unsigned DtpPtapIrWidth = DtpIrWidth;
// IEEE 1149.1: a TAP's IR capture presents 01 in its two LSBs.
localparam bit [63:0] DtpStapDsIrCapture = 64'h1;

// Composed-scan kind: TAP_3DCR data scan (PTAP 3DCR first), instruction
// scan (PTAP IR first, PTAP 3DCR absent), or a data scan under
// ZERO_LENGTH_BYPASS or BYPASS (the PTAP bypass register first; under
// ZERO_LENGTH_BYPASS only while the PTAP select is set).
typedef enum int unsigned {
  DTP_SCAN_DR     = 0,
  DTP_SCAN_IR     = 1,
  DTP_SCAN_ZLB    = 2,
  DTP_SCAN_BYPASS = 3
} dtp_scan_kind_e;

// What a window over one host chain's scan controls shows across a DR scan:
// SELECTED = select high and the TAP's capture/shift/update strobes pulse;
// UNSELECTED = select low while the strobes pulse (the strobes are the
// TAP's and only select is qualified by the instruction); GATED = the
// chain's host holds select and every strobe low.
typedef enum int unsigned {
  DTP_SCAN_CTRL_SELECTED   = 0,
  DTP_SCAN_CTRL_UNSELECTED = 1,
  DTP_SCAN_CTRL_GATED      = 2
} dtp_scan_ctrl_expect_e;

// One data register of a downstream TAP.
typedef struct {
  string       name;
  bit [63:0]   opcode;
  int unsigned width;
  bit          writable;
} dtp_stap_ds_reg_t;

typedef struct {
  bit config_hold;
  bit stap_sel;
  bit tms_hold;
} dtp_stap_3dcr_state_t;

// End state one composed STAP chain scan writes. A negative int field and an
// absent associative entry keep the stored value; a spliced downstream TAP
// takes its ds_values entry as its selected register (IR scans: its
// instruction).
typedef struct {
  int                   ptap_select = -1;
  int                   ptap_config_hold = -1;
  bit [63:0]            ptap_instr;  // IR scans
  int                   sib_en[int];
  dtp_stap_3dcr_state_t payloads[int];
  bit [63:0]            ds_values[int];
  int                   host_segment = -1;
} dtp_stap_scan_update_t;

// Downstream STAP TAP device map, the parity contract with the cocotb
// env/dtp_stap_ds_agent.py: IR width 5, IDCODE at opcode 0x1, one writable
// DS_TDR at opcode 0x2, and a per-port IDCODE and DS_TDR width so a swapped
// or misaligned splice is caught by the chain readback.
localparam int unsigned DtpStapDsIrWidth = 5;
localparam bit [63:0] DtpStapDsTdrOpcode = 64'h2;
localparam string DtpStapDsTdrName = "DS_TDR";

function automatic string dtp_stap_ds_name(int unsigned idx);
  case (idx)
    0:       return "io";
    1:       return "smc";
    2:       return "sep";
    default: return "extra0";
  endcase
endfunction

function automatic bit [31:0] dtp_stap_ds_idcode(int unsigned idx);
  case (idx)
    0:       return 32'h1D51_0101;
    1:       return 32'h1D51_0203;
    2:       return 32'h1D51_0305;
    default: return 32'h1D51_0407;
  endcase
endfunction

function automatic int unsigned dtp_stap_ds_tdr_width(int unsigned idx);
  case (idx)
    0:       return 12;
    1:       return 16;
    2:       return 20;
    default: return 8;
  endcase
endfunction

// ---------------------------------------------------------------------------
// Cross-trigger CSR block (dtp_xtrig_types.py parity). The port counts come
// from the bench configuration, the CSR windows and register offsets from the
// generated address-map packages, and the field masks, field positions, and
// reset values from the generated cross_trigger_port_reg.svh and
// cross_trigger_matrix_reg.svh headers. dtp_env cross-checks the port count
// against the generated CT_DST_SELECT field width, and the JTAG_CAPS scenario
// compares both counts with the values the DUT publishes.
// ---------------------------------------------------------------------------

// The external and internal cross-trigger port counts and the CLA clock-stop
// request lanes of the bench configuration (dtp_dv_cfg_pkg, which takes the
// port counts from the generated network address map).
localparam int unsigned DtpXtrigNumCtp = dtp_dv_cfg_pkg::NumCtp;
localparam int unsigned DtpXtrigNumIntCt = dtp_dv_cfg_pkg::NumIntCt;
localparam int unsigned DtpXtrigNumCtmPorts = DtpXtrigNumCtp + DtpXtrigNumIntCt;
localparam int unsigned DtpNumClkStopReq = dtp_dv_cfg_pkg::NumClkStopReq;
// Bit per internal cross-trigger lane: 0 = pulse mode, where the lane
// acknowledge is unused.
localparam logic [DtpXtrigNumIntCt-1:0] DtpXtrigIntCtMode = dtp_dv_cfg_pkg::IntCtMode;
// Shared-wire polarity per CONFIG.INVERT (bit index = INVERT) and the receive
// latency of a port, from the bench configuration.
localparam logic [1:0] DtpWireOrPull = dtp_dv_cfg_pkg::WireOrPull;
localparam logic [1:0] DtpWireOrAssert = dtp_dv_cfg_pkg::WireOrAssert;
localparam int unsigned DtpCtDstLatency = dtp_dv_cfg_pkg::CtDstLatency;

localparam bit [63:0] DtpXtrigCtmBase = 64'(CROSS_TRIGGER_NETWORK_CTM_BASE_ADDR);
localparam int unsigned DtpXtrigCtmStride =
    int'(cross_trigger_matrix_addrmap_pkg::CROSS_TRIGGER_MATRIX_CT_SRC_STRIDE);
localparam bit [63:0] DtpXtrigCtpBase = 64'(CROSS_TRIGGER_NETWORK_CTP_BASE_ADDR(0));
localparam int unsigned DtpXtrigCtpStride = int'(CROSS_TRIGGER_NETWORK_CTP_STRIDE);
localparam bit [63:0] DtpXtrigUnmappedBase = DtpXtrigCtpBase + DtpXtrigNumCtp * DtpXtrigCtpStride;
// End of the matrix register extent, and the bytes the registers of one
// CT_SRC slot and of one port window back. The matrix aperture runs on from
// its extent to the first port window.
localparam bit [63:0] DtpXtrigCtmEnd = DtpXtrigCtmBase + 64'(CROSS_TRIGGER_NETWORK_CTM_SIZE);
localparam int unsigned DtpXtrigCtSrcSize = int'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_SIZE);
localparam int unsigned DtpXtrigCtpRegSize = int'(CROSS_TRIGGER_NETWORK_CTP_SIZE);

localparam int unsigned DtpCtpConfigOffset  =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR);
localparam int unsigned DtpCtpStatusOffset  =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_STATUS_BASE_ADDR);
localparam int unsigned DtpCtpStretchOffset =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_STRETCH_MULT_BASE_ADDR);

// CONFIG, STRETCH_MULT, and CT_SRC CONFIG_0 field masks and the CONFIG field
// positions from the generated headers.
localparam bit [31:0] DtpCtpConfigModeMask = 32'(CROSS_TRIGGER_PORT_CONFIG_MODE_MASK);
localparam bit [31:0] DtpCtpConfigInvertMask = 32'(CROSS_TRIGGER_PORT_CONFIG_INVERT_MASK);
localparam bit [31:0] DtpCtpConfigResetMask = 32'(CROSS_TRIGGER_PORT_CONFIG_RESET_MASK);
localparam bit [31:0] DtpCtpConfigMask =
    DtpCtpConfigModeMask | DtpCtpConfigInvertMask | DtpCtpConfigResetMask;
localparam bit [31:0] DtpCtpStretchMask = 32'(CROSS_TRIGGER_PORT_STRETCH_MULT_STRETCH_MULT_MASK);
localparam bit [31:0] DtpCtmSelectMask = 32'(CT_SRC_CONFIG_0_CT_DST_SELECT_MASK);
localparam int unsigned DtpCtpConfigModeShift = CROSS_TRIGGER_PORT_CONFIG_MODE_SHIFT;
localparam int unsigned DtpCtpConfigInvertShift = CROSS_TRIGGER_PORT_CONFIG_INVERT_SHIFT;
localparam int unsigned DtpCtpConfigResetShift = CROSS_TRIGGER_PORT_CONFIG_RESET_SHIFT;

// Register reset values from the generated headers.
localparam bit [31:0] DtpCtpConfigDefault = 32'(CROSS_TRIGGER_PORT_CONFIG_REG_DEFAULT);
localparam bit [31:0] DtpCtpStatusDefault = 32'(CROSS_TRIGGER_PORT_STATUS_REG_DEFAULT);
localparam bit [31:0] DtpCtpStretchDefault = 32'(CROSS_TRIGGER_PORT_STRETCH_MULT_REG_DEFAULT);
localparam bit [31:0] DtpCtmSelectDefault = 32'(CT_SRC_CONFIG_0_REG_DEFAULT);

// CONFIG.MODE encoding (cross_trigger_port.rdl): 0 wire-OR, 1 point-to-point.
localparam int unsigned DtpCtpModeWireOr = 0;
localparam int unsigned DtpCtpModeP2p = 1;

// STATUS fields (read-only, volatile).
localparam bit [31:0] DtpCtpStatusBusy = 32'(CROSS_TRIGGER_PORT_STATUS_BUSY_MASK);
localparam bit [31:0] DtpCtpStatusReqOut = 32'(CROSS_TRIGGER_PORT_STATUS_REQ_OUT_MASK);
localparam bit [31:0] DtpCtpStatusAckIn = 32'(CROSS_TRIGGER_PORT_STATUS_ACK_IN_MASK);
localparam bit [31:0] DtpCtpStatusReqIn = 32'(CROSS_TRIGGER_PORT_STATUS_REQ_IN_MASK);
localparam bit [31:0] DtpCtpStatusAckOut = 32'(CROSS_TRIGGER_PORT_STATUS_ACK_OUT_MASK);

// What a CSR word holds: a register, a HOLE (a word inside the matrix
// register extent or a port window that no register backs), or nothing any
// block decodes (UNMAPPED).
typedef enum int unsigned {
  DTP_XTRIG_CSR_UNMAPPED    = 0,
  DTP_XTRIG_CSR_CTM_SELECT  = 1,
  DTP_XTRIG_CSR_CTP_CONFIG  = 2,
  DTP_XTRIG_CSR_CTP_STATUS  = 3,
  DTP_XTRIG_CSR_CTP_STRETCH = 4,
  DTP_XTRIG_CSR_HOLE        = 5
} dtp_xtrig_csr_kind_e;

// Reset value of the register a CSR kind names; 0 for a kind that names no
// register.
function automatic bit [31:0] dtp_xtrig_csr_default(dtp_xtrig_csr_kind_e kind);
  case (kind)
    DTP_XTRIG_CSR_CTM_SELECT:  return DtpCtmSelectDefault;
    DTP_XTRIG_CSR_CTP_CONFIG:  return DtpCtpConfigDefault;
    DTP_XTRIG_CSR_CTP_STATUS:  return DtpCtpStatusDefault;
    DTP_XTRIG_CSR_CTP_STRETCH: return DtpCtpStretchDefault;
    default:                   return '0;
  endcase
endfunction

// CONFIG word of the given fields, each at its generated position.
function automatic bit [31:0] dtp_xtrig_pack_ctp_config(int unsigned mode, bit invert, bit rst);
  return ((32'(mode) << DtpCtpConfigModeShift) & DtpCtpConfigModeMask) |
      ((32'(invert) << DtpCtpConfigInvertShift) & DtpCtpConfigInvertMask) |
      ((32'(rst) << DtpCtpConfigResetShift) & DtpCtpConfigResetMask);
endfunction

function automatic bit [63:0] dtp_xtrig_ctm_config_addr(int unsigned src_idx);
  return 64'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_CONFIG_0_BASE_ADDR(src_idx));
endfunction

function automatic bit [63:0] dtp_xtrig_ctp_config_addr(int unsigned ctp_idx);
  return DtpXtrigCtpBase + ctp_idx * DtpXtrigCtpStride + DtpCtpConfigOffset;
endfunction

function automatic bit [63:0] dtp_xtrig_ctp_status_addr(int unsigned ctp_idx);
  return DtpXtrigCtpBase + ctp_idx * DtpXtrigCtpStride + DtpCtpStatusOffset;
endfunction

function automatic bit [63:0] dtp_xtrig_ctp_stretch_addr(int unsigned ctp_idx);
  return DtpXtrigCtpBase + ctp_idx * DtpXtrigCtpStride + DtpCtpStretchOffset;
endfunction

// The first hole word of a CT_SRC slot and of a port window: the word past
// the registers the slot or window holds.
function automatic bit [63:0] dtp_xtrig_ctm_hole_addr(int unsigned src_idx);
  return 64'(CROSS_TRIGGER_NETWORK_CTM_CT_SRC_BASE_ADDR(src_idx)) + DtpXtrigCtSrcSize;
endfunction

function automatic bit [63:0] dtp_xtrig_ctp_hole_addr(int unsigned ctp_idx);
  return DtpXtrigCtpBase + ctp_idx * DtpXtrigCtpStride + DtpXtrigCtpRegSize;
endfunction

// The CSR word an access addresses. Every AXI4-Lite access uses the full
// width of the 32-bit data bus, and a transfer's aligned address is its
// address rounded down to the transfer size (AMBA AXI protocol
// specification: the AXI4-Lite definition and the transfer address
// equations), so a byte address selects the word that contains it and WSTRB
// the bytes within that word.
function automatic bit [63:0] dtp_xtrig_csr_word(bit [63:0] addr);
  return addr & ~64'h3;
endfunction

// Classify the word a CSR access addresses and return the writable
// (readback) mask of the register it names. The classes follow the
// cross-trigger network memory map (the generated table
// hw/ip/cross_trigger/cross_trigger_network/regs/gen/adoc/memory_map.adoc
// and the text after it in that block's doc/memmap.adoc): a HOLE completes
// OKAY, reads 0, and ignores writes; the matrix aperture past its register
// extent and every address past the last port window are UNMAPPED and
// complete DECERR.
function automatic dtp_xtrig_csr_kind_e dtp_xtrig_csr_decode(bit [63:0] addr,
                                                             output bit [31:0] mask);
  bit [63:0] word = dtp_xtrig_csr_word(addr);
  bit [63:0] offset;
  mask = '0;
  if (word < DtpXtrigCtmEnd) begin
    if (((word - DtpXtrigCtmBase) % DtpXtrigCtmStride) >= DtpXtrigCtSrcSize)
      return DTP_XTRIG_CSR_HOLE;
    mask = DtpCtmSelectMask;
    return DTP_XTRIG_CSR_CTM_SELECT;
  end
  if (word < DtpXtrigCtpBase || word >= DtpXtrigUnmappedBase) return DTP_XTRIG_CSR_UNMAPPED;
  offset = (word - DtpXtrigCtpBase) % DtpXtrigCtpStride;
  case (offset)
    DtpCtpConfigOffset: begin
      mask = DtpCtpConfigMask;
      return DTP_XTRIG_CSR_CTP_CONFIG;
    end
    DtpCtpStatusOffset: begin
      mask = '0;
      return DTP_XTRIG_CSR_CTP_STATUS;
    end
    DtpCtpStretchOffset: begin
      mask = DtpCtpStretchMask;
      return DTP_XTRIG_CSR_CTP_STRETCH;
    end
    default:             return DTP_XTRIG_CSR_HOLE;
  endcase
endfunction

// Apply AXI-Lite byte strobes to a 32-bit word.
function automatic bit [31:0] dtp_xtrig_apply_wstrb(bit [31:0] old_value, bit [31:0] new_value,
                                                    bit [3:0] wstrb);
  bit [31:0] merged = old_value;
  for (int unsigned byte_idx = 0; byte_idx < 4; byte_idx++) begin
    if (wstrb[byte_idx])
      merged = (merged & ~(32'hFF << (8 * byte_idx))) | (new_value & (32'hFF << (8 * byte_idx)));
  end
  return merged;
endfunction

// ---------------------------------------------------------------------------
// Shared-VIP AXI port descriptors: the interface key tb_top publishes, the
// evidence identity, and the port geometry the env hands each VIP config.
// ---------------------------------------------------------------------------

typedef struct {
  string              name;       // env component stem (m_<port>)
  string              vif_key;    // uvm_config_db key of the ocah_axi_if
  string              name_tag;   // evidence identity on the VIP config
  ocah_axi_protocol_e protocol;
  int unsigned        addr_width;
  int unsigned        data_width;
  int unsigned        id_width;
} dtp_axi_port_t;

// tb_top drives the XTRIG CSR port axil_xtrig_req_i with a
// dtp_pkg::dtp_axil_32_32_req_t: 32-bit address and data.
localparam int unsigned DtpXtrigCsrAddrWidth = 32;
localparam int unsigned DtpXtrigCsrDataWidth = 32;

// Descriptor of the port of JTAG2AXI bridge `target`, its geometry taken
// from the bridge target: the passive observer of the port, or with
// `responder` set the memory-backed responder behind it.
function automatic dtp_axi_port_t dtp_j2a_port(string target, bit responder);
  dtp_j2a_target_t t = dtp_j2a_target_by_name(target);
  bit fabric = (target == "smc_axi");
  dtp_axi_port_t p;
  if (responder) begin
    p.name     = {"m_", target, "_slave"};
    p.vif_key  = {target, "_slave_vif"};
    p.name_tag = {"dtp_", target, "_slave"};
  end else begin
    p.name     = {"m_", target, fabric ? "" : "_axi"};
    p.vif_key  = fabric ? "m_axi_vif" : {target, "_axil_vif"};
    p.name_tag = {"dtp_", target, fabric ? "" : "_axil"};
  end
  p.protocol   = t.protocol;
  p.addr_width = t.addr_width;
  p.data_width = t.data_width;
  p.id_width   = fabric ? dtp_dv_cfg_pkg::SmcAxiIdWidth : 0;
  return p;
endfunction

// ---------------------------------------------------------------------------
// Evidence policy carried from the test cfg to the env cfg.
// ---------------------------------------------------------------------------

// Required-ID policy of one shared-VIP evidence recorder (a passive AXI port
// or the aggregate JTAG checker).
typedef struct {
  bit    require_checks;
  string required_ids[$];
} dtp_evidence_policy_t;
