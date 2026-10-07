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
// values each bridge publishes in its *_JTAG2AXI_CAPS TDR (compared with the
// DUT every pass by the geometry gate), and the TDR field layouts come from
// the PTAP document; the few bench-only constants cite their source. No class
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
  SMC_OTP_JTAG2AXI_CAPS_INSTR                     = 6'h1B,
  SMC_OTP_AXI_SINGLE_OP_INSTR                     = 6'h1C,
  SMC_OTP_AXI_SERIES_CTRL_INSTR                   = 6'h1D,
  SMC_OTP_AXI_SERIES_DATA_INCR_INSTR              = 6'h1E,
  SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR           = 6'h1F,
  SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR = 6'h20,
  SEP_OTP_JTAG2AXI_CAPS_INSTR                     = 6'h21,
  SEP_OTP_AXI_SINGLE_OP_INSTR                     = 6'h22,
  SEP_OTP_AXI_SERIES_CTRL_INSTR                   = 6'h23,
  SEP_OTP_AXI_SERIES_DATA_INCR_INSTR              = 6'h24,
  SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR           = 6'h25,
  SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR = 6'h26,
  SMC_JTAG2AXI_CAPS_INSTR                         = 6'h27,
  SMC_AXI_SINGLE_OP_INSTR                         = 6'h28,
  SMC_AXI_SERIES_CTRL_INSTR                       = 6'h29,
  SMC_AXI_SERIES_DATA_INCR_INSTR                  = 6'h2A,
  SMC_AXI_SERIES_DATA_NO_INCR_INSTR               = 6'h2B,
  SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR     = 6'h2C,
  // No row for 0x2D-0x3C: BYPASS.
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

// A legal exported TAP state is exactly one of the sixteen one-hot codes.
function automatic bit dtp_tap_state_is_valid(logic [15:0] state);
  if ($isunknown(state)) return 1'b0;
  return $countones(state) == 1;
endfunction

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
// JTAG2AXI bridges (dtp_types.py JTAG2AXI_TARGETS parity).
//   SINGLE_OP DR (LSB-first): OP[2] | SIZE | WSTRB | DATA | ADDR
//     smc_otp / sep_otp: 2 + 2 + 4 + 32 + 32 = 72 bits
//     smc_axi:           2 + 2 + 8 + 64 + 56 = 132 bits
//   SERIES_CTRL DR (LSB-first): OP[2] | SIZE | PL_DEPTH[2] | ADDR | RESET
//     smc_otp / sep_otp: 39 bits; smc_axi: 63 bits
//   Capture: status = bits[1:0] (SUCCESS=0/SLVERR=1/DECERR=2/BUSY_OR_FULL=3,
//   NOT the AXI resp encoding), rdata at the DATA offset.
// ---------------------------------------------------------------------------

typedef enum int unsigned {
  DTP_J2A_OP_NOP   = 0,
  DTP_J2A_OP_READ  = 1,
  DTP_J2A_OP_WRITE = 2
} dtp_j2a_op_e;

typedef enum int unsigned {
  DTP_J2A_SUCCESS      = 0,
  DTP_J2A_SLVERR       = 1,
  DTP_J2A_DECERR       = 2,
  DTP_J2A_BUSY_OR_FULL = 3
} dtp_j2a_status_e;

typedef struct {
  string                                name;
  ocah_axi_protocol_e protocol;
  // *_JTAG2AXI_CAPS bus_type: 0 AXI4, 1 AXI4-Lite.
  bit                                   bus_type;
  dtp_jtag_instr_e                      caps_instr;
  dtp_jtag_instr_e                      single_op_instr;
  dtp_jtag_instr_e                      series_ctrl_instr;
  dtp_jtag_instr_e                      series_data_incr_instr;
  dtp_jtag_instr_e                      series_data_no_incr_instr;
  dtp_jtag_instr_e                      series_data_with_status_instr;
  int unsigned                          addr_width;
  int unsigned                          data_width;
  int unsigned                          size_bits;
  int unsigned                          wstrb_bits;
  int unsigned                          default_size;
  int unsigned                          beat_bytes;
  int unsigned                          rd_pl_depth;
  int unsigned                          wr_pl_depth;
  // The debug path whose disable gates this bridge.
  dtp_dbg_path_e                        dbg_path;
} dtp_j2a_target_t;

// Bridge status polls before a stuck-BUSY bridge fails CHK-AXI-COMPLETION.
localparam int unsigned DtpJ2aMaxStatusPolls = 16;
// Responder memory footprint (every slave agent; addresses wrap).
localparam int unsigned DtpJ2aTargetMemBytes = 65536;
// Idle TCK cycles after a series-data shift for the op to launch in the
// system domain (bridge series pipeline, cocotb parity).
localparam int unsigned DtpJ2aSeriesLaunchCycles = 5;
// TCK cycles from the AXI-side response handshake to the first scan whose
// Capture-DR shows it: the B/R beat crosses the bridge's axi_cdc_clearable
// (three synchronizer stages on the gray pointer, then the FIFO pop), the
// bridge steps from its response wait through its status update into the
// status register, and the first crossing edge adds up to one TCK of phase;
// measured from the scan's start. A status capture whose scan starts inside
// this window after a completion is not checkable.
localparam int unsigned DtpJ2aStatusSettleTck = 8;
// *_JTAG2AXI_CAPS[13:0] (PTAP document, "*_JTAG2AXI_CAPS" table).
localparam int unsigned DtpJtag2AxiCapsLen = 14;
// Evidence ID of the per-pass geometry gate every JTAG2AXI scenario records.
localparam string DtpJ2aGeometryCheckId = "CHK-J2A-GEOMETRY";
localparam string DtpJ2aStatusBitCheckId = "CHK-J2A-STATUS-BIT";
localparam string DtpJ2aErrRdataCheckId = "CHK-J2A-ERR-RDATA";
localparam string DtpJ2aSeriesAddrCheckId = "CHK-J2A-SERIES-ADDR";
// Per-operation bus request: exactly one completed transaction per bridge
// operation, the one the request asked for.
localparam string DtpJ2aBusReqCheckId = "CHK-J2A-BUS-REQ";
// A READY stall observed from the DUT side: the bridge FSM dwells on the
// stalled path and the first status poll reads BUSY_OR_FULL.
localparam string DtpJ2aStallFsmCheckId = "CHK-J2A-STALL-FSM";
localparam string DtpJ2aStallBusyCheckId = "CHK-J2A-STALL-BUSY";
// The READY stall observed on the bridge port: the tb_top stall counter of
// each channel the operation stalls advanced across it, and a channel of the
// operation the stall leaves alone counted no stall cycle.
localparam string DtpJ2aStallHoldCheckId = "CHK-J2A-STALL-HOLD";
// A gated bridge's SINGLE_OP register stays in the scan path and latches no
// update: every capture while gated equals the NOP capture taken before the
// disable, field by field.
localparam string DtpJ2aGateTdrCheckId = "CHK-J2A-GATE-TDR";
// The op-status or SERIES_CTRL status carries the injected error code, and
// the WITH_ERROR_STATUS bit follows the faulted beat.
localparam string DtpJ2aFaultStatusCheckId = "CHK-J2A-FAULT-STATUS";
// Random-ops end state: every byte lane a stream wrote holds its last word
// and every untouched lane of a touched word holds its prior value.
localparam string DtpJ2aMemImageCheckId = "CHK-J2A-MEM-IMAGE";
// Reset-abort scenario evidence: the bridge observed mid-flight before the
// reset, its FSM back in IDLE after it, the CDC's TCK-side clear seen, no
// escaped write, and a recovered status.
localparam string DtpJ2aAbortMidFlightCheckId = "CHK-J2A-ABORT-MIDFLIGHT";
localparam string DtpJ2aAbortFsmCheckId = "CHK-J2A-ABORT-FSM";
localparam string DtpJ2aCdcClearCheckId = "CHK-J2A-CDC-CLEAR";
// A reset placed inside a CDC clear sequence lands in the phase the
// scenario selected: the dtp_tb_if phase observable is set at the deposit.
localparam string DtpJ2aCdcPhaseCheckId = "CHK-J2A-CDC-PHASE";
localparam string DtpJ2aAbortEscapeCheckId = "CHK-J2A-ABORT-ESCAPE";
localparam string DtpJ2aAbortRecoveryCheckId = "CHK-J2A-ABORT-RECOVERY";
// TCK-side clear evidence with a request held on the fabric: the held
// request reaches the fabric exactly once, in the clear phase the scenario
// selects; its response never reaches the JTAG side; and a request of the
// new session queued behind it completes after it with its own status and
// data.
localparam string DtpJ2aOrphanDrainCheckId = "CHK-J2A-ORPHAN-DRAIN";
localparam string DtpJ2aOrphanDiscardCheckId = "CHK-J2A-ORPHAN-DISCARD";
localparam string DtpJ2aOrphanOrderCheckId = "CHK-J2A-ORPHAN-ORDER";
localparam int unsigned DtpJ2aSeriesStatusBeats = 4;
// Increment flag per beat of the WITH_ERROR_STATUS streams (bit i = beat i):
// the second beat re-writes the held address.
localparam bit [DtpJ2aSeriesStatusBeats-1:0] DtpJ2aSeriesStatusIncrements = 4'b1101;

// *_JTAG2AXI_CAPS data_size: the beat width in bytes as a power of two.
function automatic int unsigned dtp_j2a_data_size(dtp_j2a_target_t t);
  return $clog2(t.data_width / 8);
endfunction

// The transfer size the bridge uses for a scanned size field: a size above
// data_size transfers one full beat (PTAP document, "*_AXI_SINGLE_OP").
function automatic int unsigned dtp_j2a_axsize(dtp_j2a_target_t t, int unsigned size);
  return (size > dtp_j2a_data_size(t)) ? dtp_j2a_data_size(t) : size;
endfunction

// Width of the SINGLE_OP and SERIES_CTRL size field: the smallest width that
// encodes every AxSIZE up to a full beat, and at least one bit; the PTAP
// document's "*_AXI_SINGLE_OP" table names this width $bits(size).
function automatic int unsigned dtp_j2a_size_field_bits(int unsigned data_width);
  int unsigned data_size = $clog2(data_width / 8);
  return (data_size == 0) ? 1 : $clog2(data_size + 1);
endfunction

// Every width other than the bus type, address width, and data width follows
// from the data width (PTAP document, "*_AXI_SINGLE_OP" and
// "*_AXI_SERIES_CTRL" tables).
function automatic void dtp_j2a_derive_geometry(ref dtp_j2a_target_t t);
  t.bus_type     = (t.protocol == OCAH_AXI_PROTO_AXI4_LITE);
  t.beat_bytes   = t.data_width / 8;
  t.default_size = dtp_j2a_data_size(t);
  t.size_bits    = dtp_j2a_size_field_bits(t.data_width);
  t.wstrb_bits   = 1 << dtp_j2a_data_size(t);
endfunction

// One function per bridge: the bus type, widths, and pipeline depths come from
// the bench configuration tb_top elaborates the DUT with (dtp_dv_cfg_pkg); the
// geometry gate compares the bridge's *_JTAG2AXI_CAPS publication with them
// every pass.
function automatic dtp_j2a_target_t dtp_j2a_target_smc_otp();
  dtp_j2a_target_t t;
  t.name                          = "smc_otp";
  t.protocol = OCAH_AXI_PROTO_AXI4_LITE;
  t.caps_instr                    = SMC_OTP_JTAG2AXI_CAPS_INSTR;
  t.single_op_instr               = SMC_OTP_AXI_SINGLE_OP_INSTR;
  t.series_ctrl_instr             = SMC_OTP_AXI_SERIES_CTRL_INSTR;
  t.series_data_incr_instr        = SMC_OTP_AXI_SERIES_DATA_INCR_INSTR;
  t.series_data_no_incr_instr     = SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
  t.series_data_with_status_instr =
        SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
  t.addr_width                    = dtp_dv_cfg_pkg::OtpAxilAddrWidth;
  t.data_width                    = dtp_dv_cfg_pkg::OtpAxilDataWidth;
  t.rd_pl_depth                   = int'(dtp_dv_cfg_pkg::SmcOtpRdPlDepth);
  t.wr_pl_depth                   = int'(dtp_dv_cfg_pkg::SmcOtpWrPlDepth);
  dtp_j2a_derive_geometry(t);
  t.dbg_path = DTP_DBG_PATH_SMC_OTP_JTAG2AXI;
  return t;
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_sep_otp();
  dtp_j2a_target_t t;
  t.name                          = "sep_otp";
  t.protocol = OCAH_AXI_PROTO_AXI4_LITE;
  t.caps_instr                    = SEP_OTP_JTAG2AXI_CAPS_INSTR;
  t.single_op_instr               = SEP_OTP_AXI_SINGLE_OP_INSTR;
  t.series_ctrl_instr             = SEP_OTP_AXI_SERIES_CTRL_INSTR;
  t.series_data_incr_instr        = SEP_OTP_AXI_SERIES_DATA_INCR_INSTR;
  t.series_data_no_incr_instr     = SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
  t.series_data_with_status_instr =
        SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
  t.addr_width                    = dtp_dv_cfg_pkg::OtpAxilAddrWidth;
  t.data_width                    = dtp_dv_cfg_pkg::OtpAxilDataWidth;
  t.rd_pl_depth                   = int'(dtp_dv_cfg_pkg::SepOtpRdPlDepth);
  t.wr_pl_depth                   = int'(dtp_dv_cfg_pkg::SepOtpWrPlDepth);
  dtp_j2a_derive_geometry(t);
  t.dbg_path = DTP_DBG_PATH_SEP_OTP_JTAG2AXI;
  return t;
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_smc_axi();
  dtp_j2a_target_t t;
  t.name                          = "smc_axi";
  t.protocol = OCAH_AXI_PROTO_AXI4;
  t.caps_instr                    = SMC_JTAG2AXI_CAPS_INSTR;
  t.single_op_instr               = SMC_AXI_SINGLE_OP_INSTR;
  t.series_ctrl_instr             = SMC_AXI_SERIES_CTRL_INSTR;
  t.series_data_incr_instr        = SMC_AXI_SERIES_DATA_INCR_INSTR;
  t.series_data_no_incr_instr     = SMC_AXI_SERIES_DATA_NO_INCR_INSTR;
  t.series_data_with_status_instr =
        SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
  t.addr_width                    = dtp_dv_cfg_pkg::SmcAxiAddrWidth;
  t.data_width                    = dtp_dv_cfg_pkg::SmcAxiDataWidth;
  t.rd_pl_depth                   = int'(dtp_dv_cfg_pkg::SmcRdPlDepth);
  t.wr_pl_depth                   = int'(dtp_dv_cfg_pkg::SmcWrPlDepth);
  dtp_j2a_derive_geometry(t);
  t.dbg_path = DTP_DBG_PATH_SMC_JTAG2AXI;
  return t;
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

function automatic int unsigned dtp_j2a_single_op_len(dtp_j2a_target_t t);
  return 2 + t.size_bits + t.wstrb_bits + t.data_width + t.addr_width;
endfunction

function automatic int unsigned dtp_j2a_series_ctrl_len(dtp_j2a_target_t t);
  return 2 + t.size_bits + 2 + t.addr_width + 1;
endfunction

function automatic dtp_j2a_status_e dtp_j2a_axi_resp_to_status(ocah_axi_resp_e resp);
  case (resp)
    OCAH_AXI_RESP_SLVERR: return DTP_J2A_SLVERR;
    OCAH_AXI_RESP_DECERR: return DTP_J2A_DECERR;
    default:              return DTP_J2A_SUCCESS;
  endcase
endfunction

// One WITH_ERROR_STATUS stream: its geometry and the beat that carries the
// fault (-1 for a clean stream). The status bit a shift returns belongs to
// the previous beat, so only the shift after the fault beat expects a 1.
typedef struct {
  bit [63:0]       base;
  int unsigned     size;
  int unsigned     stride;
  int              fault_idx;
  dtp_j2a_status_e expected;
} dtp_j2a_series_status_plan_t;

function automatic bit [63:0] dtp_j2a_series_status_addr(dtp_j2a_series_status_plan_t p,
                                                         int unsigned idx);
  bit [63:0] addr = p.base;
  for (int unsigned i = 0; i < idx && i < DtpJ2aSeriesStatusBeats; i++)
  if (DtpJ2aSeriesStatusIncrements[i]) addr += p.stride;
  return addr;
endfunction

function automatic bit [63:0] dtp_j2a_series_status_final_addr(dtp_j2a_series_status_plan_t p);
  return dtp_j2a_series_status_addr(p, DtpJ2aSeriesStatusBeats);
endfunction

// Bytes from base through the slot the trailing shift touches.
function automatic bit [63:0] dtp_j2a_series_status_span(dtp_j2a_series_status_plan_t p);
  return dtp_j2a_series_status_final_addr(p) - p.base + p.stride;
endfunction

function automatic bit dtp_j2a_series_status_is_fault(dtp_j2a_series_status_plan_t p,
                                                      int unsigned idx);
  return (p.fault_idx >= 0) && (int'(idx) == p.fault_idx);
endfunction

function automatic bit dtp_j2a_series_status_expected_bit(dtp_j2a_series_status_plan_t p,
                                                          int unsigned shift);
  return (shift > 0) && dtp_j2a_series_status_is_fault(p, shift - 1);
endfunction

// Beats whose address no earlier beat touched; a one-shot fault fires on
// the first access.
function automatic void dtp_j2a_series_status_first_visits(dtp_j2a_series_status_plan_t p,
                                                           output int unsigned beats[$]);
  for (int unsigned idx = 0; idx < DtpJ2aSeriesStatusBeats; idx++) begin
    bit seen = 1'b0;
    for (int unsigned j = 0; j < idx; j++)
    if (dtp_j2a_series_status_addr(p, j) == dtp_j2a_series_status_addr(p, idx)) seen = 1'b1;
    if (!seen) beats.push_back(idx);
  end
endfunction

// The word each beat's address holds after the stream: the last one written
// there.
function automatic void dtp_j2a_series_status_final_words(
    dtp_j2a_series_status_plan_t p, bit [63:0] words[], output bit [63:0] expected[]);
  expected = new[words.size()];
  foreach (words[idx]) begin
    expected[idx] = words[idx];
    for (int unsigned j = idx + 1; j < words.size(); j++)
    if (dtp_j2a_series_status_addr(p, j) == dtp_j2a_series_status_addr(p, idx))
      expected[idx] = words[j];
  end
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

// SINGLE_OP DR packing, the *_AXI_SINGLE_OP table order LSB-first:
// OP | SIZE | WSTRB | DATA | ADDR.
function automatic void dtp_j2a_pack_single_op(dtp_j2a_target_t t, dtp_j2a_op_e op, bit [63:0] addr,
                                               bit [63:0] data, bit [7:0] wstrb, int unsigned size,
                                               ref bit dr[]);
  int unsigned offset = 0;
  dr = new[dtp_j2a_single_op_len(t)];
  foreach (dr[i]) dr[i] = 1'b0;
  for (int unsigned i = 0; i < 2; i++) dr[offset++] = (int'(op) >> i) & 1'b1;
  for (int unsigned i = 0; i < t.size_bits; i++) dr[offset++] = (size >> i) & 1'b1;
  for (int unsigned i = 0; i < t.wstrb_bits; i++) dr[offset++] = (wstrb >> i) & 1'b1;
  for (int unsigned i = 0; i < t.data_width; i++) dr[offset++] = (data >> i) & 1'b1;
  for (int unsigned i = 0; i < t.addr_width; i++) dr[offset++] = (addr >> i) & 1'b1;
endfunction

function automatic void dtp_j2a_unpack_single_op(
    dtp_j2a_target_t t, bit rbits[], output dtp_j2a_status_e status, output bit [63:0] rdata);
  int unsigned data_off   = 2 + t.size_bits + t.wstrb_bits;
  int unsigned status_raw = 0;
  rdata = '0;
  for (int unsigned i = 0; i < 2 && i < rbits.size(); i++) status_raw |= int'(rbits[i]) << i;
  status = dtp_j2a_status_e'(status_raw);
  for (int unsigned i = 0; i < t.data_width && (data_off + i) < rbits.size(); i++)
  rdata[i] = rbits[data_off+i];
endfunction

// SERIES_CTRL packing, the *_AXI_SERIES_CTRL table order LSB-first:
// OP | SIZE | PL_DEPTH | ADDR | RESET.
function automatic bit [63:0] dtp_j2a_pack_series_ctrl(dtp_j2a_target_t t, dtp_j2a_op_e op,
                                                       bit [63:0] addr, int unsigned pipeline_depth,
                                                       int unsigned size, bit series_reset);
  int unsigned size_off     = 2;
  int unsigned pl_depth_off = size_off + t.size_bits;
  int unsigned addr_off     = pl_depth_off + 2;
  int unsigned reset_off    = addr_off + t.addr_width;
  return (64'(int'(op)) & 64'h3) | ((64'(size) & ocah_rng::bit_mask(
      t.size_bits
  )) << size_off) | ((64'(pipeline_depth) & 64'h3) << pl_depth_off) | ((addr & ocah_rng::bit_mask(
      t.addr_width
  )) << addr_off) | (64'(series_reset) << reset_off);
endfunction

function automatic void dtp_j2a_unpack_series_ctrl(
    dtp_j2a_target_t t, bit [63:0] value, output bit series_reset, output bit [63:0] addr,
    output int unsigned pipeline_depth, output int unsigned size, output dtp_j2a_status_e status);
  int unsigned size_off     = 2;
  int unsigned pl_depth_off = size_off + t.size_bits;
  int unsigned addr_off     = pl_depth_off + 2;
  int unsigned reset_off    = addr_off + t.addr_width;
  status         = dtp_j2a_status_e'(value & 64'h3);
  size           = int'((value >> size_off) & ocah_rng::bit_mask(t.size_bits));
  pipeline_depth = int'((value >> pl_depth_off) & 64'h3);
  addr           = (value >> addr_off) & ocah_rng::bit_mask(t.addr_width);
  series_reset   = value[reset_off];
endfunction

// Which JTAG2AXI register a DR scan addressed, from the active instruction.
typedef enum int unsigned {
  DTP_J2A_SCAN_NONE = 0,
  DTP_J2A_SCAN_SINGLE_OP,
  DTP_J2A_SCAN_SERIES_CTRL,
  DTP_J2A_SCAN_SERIES_DATA_INCR,
  DTP_J2A_SCAN_SERIES_DATA_NO_INCR,
  DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS
} dtp_j2a_scan_kind_e;

// One decoded JTAG2AXI request: the TDI image of a DR scan, as the bridge
// latches it at Update-DR.
typedef struct {
  dtp_j2a_scan_kind_e kind;
  dtp_j2a_op_e        op;              // SINGLE_OP and SERIES_CTRL op field
  bit [63:0]          addr;
  bit [63:0]          data;
  bit [7:0]           wstrb;
  int unsigned        size;
  int unsigned        pipeline_depth;  // SERIES_CTRL
  bit                 series_reset;    // SERIES_CTRL
  bit                 incr;            // series data: advance the address
} dtp_j2a_request_t;

// The bridge and register a 6-bit instruction selects; SCAN_NONE when the
// instruction is not a JTAG2AXI register.
function automatic dtp_j2a_scan_kind_e dtp_j2a_classify_instr(bit [DtpIrWidth-1:0] ir,
                                                              output dtp_j2a_target_t t);
  string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
  foreach (names[i]) begin
    t = dtp_j2a_target_by_name(names[i]);
    if (ir == t.single_op_instr) return DTP_J2A_SCAN_SINGLE_OP;
    if (ir == t.series_ctrl_instr) return DTP_J2A_SCAN_SERIES_CTRL;
    if (ir == t.series_data_incr_instr) return DTP_J2A_SCAN_SERIES_DATA_INCR;
    if (ir == t.series_data_no_incr_instr) return DTP_J2A_SCAN_SERIES_DATA_NO_INCR;
    if (ir == t.series_data_with_status_instr) return DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS;
  end
  return DTP_J2A_SCAN_NONE;
endfunction

// Field of an LSB-first shift image (a scan item's bit queue), zero-extended
// and clipped to 64 bits.
function automatic bit [63:0] dtp_bits_field(ref bit bits[$], input int unsigned offset,
                                             input int unsigned width);
  bit [63:0] value = '0;
  for (int unsigned i = 0; i < width && i < 64; i++)
  if (offset + i < bits.size()) value[i] = bits[offset+i];
  return value;
endfunction

// Hex image of an LSB-first shift image, without leading zeros.
function automatic string dtp_bits_hex(bit bits[]);
  string s = "";
  for (int d = (int'(bits.size()) + 3) / 4 - 1; d >= 0; d--) begin
    int unsigned nibble = 0;
    for (int unsigned b = 0; b < 4; b++)
    if (4 * d + b < bits.size() && bits[4*d+b]) nibble |= 1 << b;
    if (s.len() > 0 || nibble != 0) s = {s, $sformatf("%0h", nibble)};
  end
  return (s.len() > 0) ? s : "0";
endfunction

// Decode the TDI image of a SINGLE_OP scan (inverse of dtp_j2a_pack_single_op).
function automatic void dtp_j2a_decode_single_op(dtp_j2a_target_t t, ref bit tdi[$],
                                                 output dtp_j2a_request_t r);
  int unsigned size_off  = 2;
  int unsigned wstrb_off = size_off + t.size_bits;
  int unsigned data_off  = wstrb_off + t.wstrb_bits;
  int unsigned addr_off  = data_off + t.data_width;
  r.kind  = DTP_J2A_SCAN_SINGLE_OP;
  r.op    = dtp_j2a_op_e'(dtp_bits_field(tdi, 0, 2));
  r.size  = int'(dtp_bits_field(tdi, size_off, t.size_bits));
  r.wstrb = 8'(dtp_bits_field(tdi, wstrb_off, t.wstrb_bits));
  r.data  = dtp_bits_field(tdi, data_off, t.data_width);
  r.addr  = dtp_bits_field(tdi, addr_off, t.addr_width);
endfunction

// Decode the TDI image of a SERIES_CTRL scan (inverse of dtp_j2a_pack_series_ctrl).
function automatic void dtp_j2a_decode_series_ctrl(dtp_j2a_target_t t, ref bit tdi[$],
                                                   output dtp_j2a_request_t r);
  int unsigned size_off     = 2;
  int unsigned pl_depth_off = size_off + t.size_bits;
  int unsigned addr_off     = pl_depth_off + 2;
  int unsigned reset_off    = addr_off + t.addr_width;
  r.kind           = DTP_J2A_SCAN_SERIES_CTRL;
  r.op             = dtp_j2a_op_e'(dtp_bits_field(tdi, 0, 2));
  r.size           = int'(dtp_bits_field(tdi, size_off, t.size_bits));
  r.pipeline_depth = int'(dtp_bits_field(tdi, pl_depth_off, 2));
  r.addr           = dtp_bits_field(tdi, addr_off, t.addr_width);
  r.series_reset   = dtp_bits_field(tdi, reset_off, 1) != 64'd0;
endfunction

// Decode the TDI image of a series-data scan under the latched series size:
// the payload, and for the with-status register the increment bit above it.
function automatic void dtp_j2a_decode_series_data(dtp_j2a_scan_kind_e kind, int unsigned size,
                                                   ref bit tdi[$], output dtp_j2a_request_t r);
  int unsigned payload_bits = 8 * dtp_j2a_size_bytes(size);
  r.kind = kind;
  r.size = size;
  r.data = dtp_bits_field(tdi, 0, payload_bits);
  r.incr = (kind == DTP_J2A_SCAN_SERIES_DATA_INCR) ||
             ((kind == DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS) &&
              (dtp_bits_field(tdi, payload_bits, 1) != 64'd0));
endfunction

// Shift-register length of a series-data scan under the latched size.
function automatic int unsigned dtp_j2a_series_data_len(dtp_j2a_scan_kind_e kind,
                                                        int unsigned size);
  return 8 * dtp_j2a_size_bytes(size) + ((kind == DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS) ? 1 : 0);
endfunction

// Series data rides the AXI byte lanes the current address and
// AXI_SERIES_CTRL.size select, and Capture-DR returns the payload from those
// lanes (PTAP document, "*_AXI_SERIES_DATA_INCR"). The lanes are those of an
// AXI narrow transfer (AMBA AXI protocol specification, "Narrow transfers"):
// a transfer of 2**size bytes at address A on an N-byte bus uses lanes
// A mod N through the last lane of its 2**size-aligned container, whose first
// byte sits on lane (A aligned down to 2**size) mod N. SINGLE_OP keeps the
// host-packed strobes and data.
function automatic int unsigned dtp_j2a_container_lane(dtp_j2a_target_t t, bit [63:0] addr,
                                                       int unsigned size);
  int unsigned nbytes = dtp_j2a_size_bytes(size);
  if (nbytes >= t.beat_bytes) return 0;
  return int'((addr & ~64'(nbytes - 1)) % t.beat_bytes);
endfunction

function automatic bit [7:0] dtp_j2a_series_wstrb(dtp_j2a_target_t t, bit [63:0] addr,
                                                  int unsigned size);
  int unsigned nbytes = dtp_j2a_size_bytes(size);
  int unsigned lower = int'(addr % t.beat_bytes);
  int unsigned upper = dtp_j2a_container_lane(t, addr, size) +
      ((nbytes >= t.beat_bytes) ? t.beat_bytes : nbytes) - 1;
  bit [7:0] strobe = '0;
  for (int unsigned lane = lower; lane <= upper; lane++) strobe[lane] = 1'b1;
  return strobe;
endfunction

function automatic bit [63:0] dtp_j2a_series_wdata(dtp_j2a_target_t t, bit [63:0] data,
                                                   bit [63:0] addr, int unsigned size);
  return (data << (8 * dtp_j2a_container_lane(t, addr, size))) & ocah_rng::bit_mask(t.data_width);
endfunction

function automatic bit [63:0] dtp_j2a_series_rdata(dtp_j2a_target_t t, bit [63:0] word,
                                                   bit [63:0] addr, int unsigned size);
  return (word >> (8 * dtp_j2a_container_lane(t, addr, size))) & dtp_j2a_data_mask(size) &
      ocah_rng::bit_mask(t.data_width);
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
