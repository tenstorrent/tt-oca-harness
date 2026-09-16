// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP bench constants, DUT geometry, and pure codec functions shared by the
// environment (reference models, virtual sequencer, cfgs) and the
// sequence library (reusable operations, scenario helpers). The cocotb twin
// is env/dtp_types.py plus env/dtp_xtrig_types.py. Register opcodes come from
// the generated jtag_inst_reg_pkg, the cross-trigger CSR map from the
// generated cross_trigger_* collateral, the JTAG2AXI bridge geometries from
// the values each bridge publishes in its *_JTAG2AXI_CAPS TDR (compared with
// the DUT every pass by the geometry gate), and the TDR field layouts from the
// PTAP document; the few bench-only constants cite their
// source. No class lives here: everything is a package-scope type, constant,
// or `function automatic`.

// ---------------------------------------------------------------------------
// Primary TAP.
// ---------------------------------------------------------------------------

localparam int unsigned DtpIrWidth = jtag_inst_reg_pkg::IR_WIDTH;

// Device identification of the public DTP elaboration: the jtag_ptap IDCODE
// parameters default to manufacturer 0, part 0, revision 0, leaving only the
// IEEE 1149.1 marker bit.
localparam bit [31:0] DtpDefaultIdcode = 32'h0000_0001;

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

// Bridge AXI FSM state as dtp_tb_if samples it from jtag2axi.sv (axi_state_e).
typedef enum logic [2:0] {
  DTP_J2A_FSM_IDLE          = 0,
  DTP_J2A_FSM_SEND_ADDR_W   = 1,
  DTP_J2A_FSM_SEND_DATA_W   = 2,
  DTP_J2A_FSM_WAIT_BRESP    = 3,
  DTP_J2A_FSM_SEND_ADDR_R   = 4,
  DTP_J2A_FSM_WAIT_RDATA    = 5,
  DTP_J2A_FSM_UPDATE_STATUS = 6
} dtp_j2a_fsm_state_e;

typedef struct {
  string                                name;
  ocah_axi_protocol_e protocol;
  // *_JTAG2AXI_CAPS bus_type: 0 AXI4, 1 AXI4-Lite.
  bit                                   bus_type;
  jtag_inst_reg_pkg::jtag_instruction_e caps_instr;
  jtag_inst_reg_pkg::jtag_instruction_e single_op_instr;
  jtag_inst_reg_pkg::jtag_instruction_e series_ctrl_instr;
  jtag_inst_reg_pkg::jtag_instruction_e series_data_incr_instr;
  jtag_inst_reg_pkg::jtag_instruction_e series_data_no_incr_instr;
  jtag_inst_reg_pkg::jtag_instruction_e series_data_with_status_instr;
  int unsigned                          addr_width;
  int unsigned                          data_width;
  int unsigned                          size_bits;
  int unsigned                          wstrb_bits;
  int unsigned                          default_size;
  int unsigned                          beat_bytes;
  // The one dbg_disable_t field that gates this bridge (one-hot mask).
  sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_mask;
} dtp_j2a_target_t;

// Bridge status polls before a stuck-BUSY bridge fails CHK-AXI-COMPLETION.
localparam int unsigned DtpJ2aMaxStatusPolls = 16;
// Responder memory footprint (every slave agent; addresses wrap).
localparam int unsigned DtpJ2aTargetMemBytes = 65536;
// Idle TCK cycles after a series-data shift for the op to launch in the
// system domain (bridge series pipeline, cocotb parity).
localparam int unsigned DtpJ2aSeriesLaunchCycles = 5;
// TCK cycles an AXI completion needs to cross into the bridge's TCK domain
// before a Capture-DR shows it (jtag2axi status CDC); a status capture
// inside this window after a completion is not checkable.
localparam int unsigned DtpJ2aStatusSettleTck = 4;
// Read and write pipeline depth every bridge publishes in the rd_pl_depth and
// wr_pl_depth fields of its *_JTAG2AXI_CAPS TDR; the CAPS scenarios compare them.
localparam int unsigned DtpJ2aPipelineDepth = 3;
// Series read requests one CTRL programming may enqueue: pipeline_depth + 1,
// with the depth capped at the bridge's read pipeline depth.
localparam int unsigned DtpJ2aMaxPipelineDepth = DtpJ2aPipelineDepth;
// *_JTAG2AXI_CAPS[13:0] (PTAP document, "*_JTAG2AXI_CAPS" table).
localparam int unsigned DtpJtag2AxiCapsLen = 14;
// Evidence ID of the per-pass geometry gate every JTAG2AXI scenario records.
localparam string DtpJ2aGeometryCheckId = "CHK-J2A-GEOMETRY";
localparam string DtpJ2aStatusBitCheckId = "CHK-J2A-STATUS-BIT";
localparam string DtpJ2aErrRdataCheckId = "CHK-J2A-ERR-RDATA";
localparam string DtpJ2aSeriesAddrCheckId = "CHK-J2A-SERIES-ADDR";
// Reset-abort scenario evidence: the bridge observed mid-flight before the
// reset, its FSM back in IDLE after it, the CDC's TCK-side clear seen, no
// escaped write, and a recovered status.
localparam string DtpJ2aAbortMidFlightCheckId = "CHK-J2A-ABORT-MIDFLIGHT";
localparam string DtpJ2aAbortFsmCheckId = "CHK-J2A-ABORT-FSM";
localparam string DtpJ2aCdcClearCheckId = "CHK-J2A-CDC-CLEAR";
localparam string DtpJ2aAbortEscapeCheckId = "CHK-J2A-ABORT-ESCAPE";
localparam string DtpJ2aAbortRecoveryCheckId = "CHK-J2A-ABORT-RECOVERY";
localparam int unsigned DtpJ2aSeriesStatusBeats = 4;
// Increment flag per beat of the WITH_ERROR_STATUS streams (bit i = beat i):
// the second beat re-writes the held address.
localparam bit [DtpJ2aSeriesStatusBeats-1:0] DtpJ2aSeriesStatusIncrements = 4'b1101;

// *_JTAG2AXI_CAPS data_size: the beat width in bytes as a power of two.
function automatic int unsigned dtp_j2a_data_size(dtp_j2a_target_t t);
  return $clog2(t.data_width / 8);
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

// One function per bridge: bus type, address width, and data width are the
// values the bridge publishes in its *_JTAG2AXI_CAPS TDR; the geometry gate
// compares them with the DUT every pass.
function automatic dtp_j2a_target_t dtp_j2a_target_smc_otp();
  dtp_j2a_target_t t;
  t.name                          = "smc_otp";
  t.protocol = OCAH_AXI_PROTO_AXI4_LITE;
  t.caps_instr                    = jtag_inst_reg_pkg::SMC_OTP_JTAG2AXI_CAPS_INSTR;
  t.single_op_instr               = jtag_inst_reg_pkg::SMC_OTP_AXI_SINGLE_OP_INSTR;
  t.series_ctrl_instr             = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_CTRL_INSTR;
  t.series_data_incr_instr        = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_INCR_INSTR;
  t.series_data_no_incr_instr     = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
  t.series_data_with_status_instr =
        jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
  t.addr_width       = 32;
  t.data_width       = 32;
  dtp_j2a_derive_geometry(t);
  t.dbg_disable_mask = '0;
  t.dbg_disable_mask.smc_otp_jtag2axi = 1'b1;
  return t;
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_sep_otp();
  dtp_j2a_target_t t;
  t.name                          = "sep_otp";
  t.protocol = OCAH_AXI_PROTO_AXI4_LITE;
  t.caps_instr                    = jtag_inst_reg_pkg::SEP_OTP_JTAG2AXI_CAPS_INSTR;
  t.single_op_instr               = jtag_inst_reg_pkg::SEP_OTP_AXI_SINGLE_OP_INSTR;
  t.series_ctrl_instr             = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_CTRL_INSTR;
  t.series_data_incr_instr        = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_INCR_INSTR;
  t.series_data_no_incr_instr     = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
  t.series_data_with_status_instr =
        jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
  t.addr_width       = 32;
  t.data_width       = 32;
  dtp_j2a_derive_geometry(t);
  t.dbg_disable_mask = '0;
  t.dbg_disable_mask.sep_otp_jtag2axi = 1'b1;
  return t;
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_smc_axi();
  dtp_j2a_target_t t;
  t.name                          = "smc_axi";
  t.protocol = OCAH_AXI_PROTO_AXI4;
  t.caps_instr                    = jtag_inst_reg_pkg::SMC_JTAG2AXI_CAPS_INSTR;
  t.single_op_instr               = jtag_inst_reg_pkg::SMC_AXI_SINGLE_OP_INSTR;
  t.series_ctrl_instr             = jtag_inst_reg_pkg::SMC_AXI_SERIES_CTRL_INSTR;
  t.series_data_incr_instr        = jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_INCR_INSTR;
  t.series_data_no_incr_instr     = jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_NO_INCR_INSTR;
  t.series_data_with_status_instr =
        jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
  t.addr_width       = 56;
  t.data_width       = 64;
  dtp_j2a_derive_geometry(t);
  t.dbg_disable_mask = '0;
  t.dbg_disable_mask.smc_jtag2axi = 1'b1;
  return t;
endfunction

// Target by name ("smc_otp", "sep_otp", "smc_axi").
function automatic dtp_j2a_target_t dtp_j2a_target_by_name(string name);
  case (name)
    "smc_axi": return dtp_j2a_target_smc_axi();
    "sep_otp": return dtp_j2a_target_sep_otp();
    default:   return dtp_j2a_target_smc_otp();
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

// Series transfers ride the byte lanes the current address selects
// (jtag2axi series_lane_wstrb / series_lane_wdata); SINGLE_OP keeps the
// host-packed strobes and data.
function automatic int unsigned dtp_j2a_lane_offset(dtp_j2a_target_t t, bit [63:0] addr);
  return int'(addr % t.beat_bytes);
endfunction

function automatic bit [7:0] dtp_j2a_series_wstrb(dtp_j2a_target_t t, bit [63:0] addr,
                                                  int unsigned size);
  int unsigned nbytes = dtp_j2a_size_bytes(size);
  if (nbytes >= t.beat_bytes) return 8'((1 << t.beat_bytes) - 1);
  return 8'(((1 << nbytes) - 1) << dtp_j2a_lane_offset(t, addr));
endfunction

function automatic bit [63:0] dtp_j2a_series_wdata(dtp_j2a_target_t t, bit [63:0] data,
                                                   bit [63:0] addr);
  return (data << (8 * dtp_j2a_lane_offset(t, addr))) & ocah_rng::bit_mask(t.data_width);
endfunction

// Read data as the bridge presents it in a series capture: the addressed
// lanes shifted down to bit 0 (jtag2axi series_lane_rdata).
function automatic bit [63:0] dtp_j2a_series_rdata(dtp_j2a_target_t t, bit [63:0] word,
                                                   bit [63:0] addr);
  return (word >> (8 * dtp_j2a_lane_offset(t, addr))) & ocah_rng::bit_mask(t.data_width);
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

localparam int unsigned DtpIjtagSibCount = 3;
// Instrument stub widths behind each SIB (tb_top), dtp_ijtag_sib_e order:
// every subset of open SIBs sums to a distinct chain length.
localparam int unsigned DtpIjtagInstrumentWidths[DtpIjtagSibCount] = '{4, 5, 6};
localparam int unsigned DtpIjtagChainLenMax = DtpIjtagSibCount + 4 + 5 + 6;
// A latency-measuring scan shifts a marker word ahead of the chain's
// maintain image; the marker's MSB is set, so the stream's highest set bit
// lands at chain_len + DtpScanMarkerWidth - 1.
localparam int unsigned DtpScanMarkerWidth = 16;
localparam int unsigned DtpIjtagObserveScanWidth = 40;
localparam int unsigned DtpStapCount = 4;
localparam int unsigned DtpPtapIrWidth = DtpIrWidth;
// IEEE 1149.1: a TAP's IR capture presents 01 in its two LSBs.
localparam bit [63:0] DtpStapDsIrCapture = 64'h1;

// Composed-scan kind: TAP_3DCR data scan (PTAP 3DCR first) or instruction
// scan (PTAP IR first, PTAP 3DCR absent).
typedef enum int unsigned {
  DTP_SCAN_DR = 0,
  DTP_SCAN_IR = 1
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
// Cross-trigger CSR block (dtp_xtrig_types.py parity). Port counts come from
// dtp_pkg, the window split from cross_trigger_network_pkg, register offsets
// from the generated address-map packages, and field masks from the generated
// cross_trigger_port_reg.svh and cross_trigger_matrix_reg.svh headers.
// ---------------------------------------------------------------------------

localparam int unsigned DtpXtrigNumCtp = dtp_pkg::DEFAULT_NUM_CTP;
localparam int unsigned DtpXtrigNumIntCt = dtp_pkg::DEFAULT_NUM_INT_CT;
localparam int unsigned DtpXtrigNumCtmPorts = DtpXtrigNumCtp + DtpXtrigNumIntCt;

localparam bit [63:0] DtpXtrigCtmBase = 64'h0;
localparam int unsigned DtpXtrigCtmStride =
    int'(cross_trigger_matrix_addrmap_pkg::CROSS_TRIGGER_MATRIX_CT_SRC_STRIDE);
localparam bit [63:0] DtpXtrigCtpBase = 64'(cross_trigger_network_pkg::CSR_ADDR_CTM_SIZE);
localparam int unsigned DtpXtrigCtpStride = cross_trigger_network_pkg::CSR_ADDR_CTP_SIZE;
localparam bit [63:0] DtpXtrigUnmappedBase = DtpXtrigCtpBase + DtpXtrigNumCtp * DtpXtrigCtpStride;

localparam int unsigned DtpCtpConfigOffset  =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR);
localparam int unsigned DtpCtpStatusOffset  =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_STATUS_BASE_ADDR);
localparam int unsigned DtpCtpStretchOffset =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_STRETCH_MULT_BASE_ADDR);

// CONFIG, STRETCH_MULT, and CT_SRC CONFIG_0 field masks from the generated headers.
localparam bit [31:0] DtpCtpConfigModeMask = 32'(CROSS_TRIGGER_PORT_CONFIG_MODE_MASK);
localparam bit [31:0] DtpCtpConfigInvertMask = 32'(CROSS_TRIGGER_PORT_CONFIG_INVERT_MASK);
localparam bit [31:0] DtpCtpConfigResetMask = 32'(CROSS_TRIGGER_PORT_CONFIG_RESET_MASK);
localparam bit [31:0] DtpCtpConfigMask =
    DtpCtpConfigModeMask | DtpCtpConfigInvertMask | DtpCtpConfigResetMask;
localparam bit [31:0] DtpCtpStretchMask = 32'(CROSS_TRIGGER_PORT_STRETCH_MULT_STRETCH_MULT_MASK);
localparam bit [31:0] DtpCtmSelectMask = 32'(CT_SRC_CONFIG_0_CT_DST_SELECT_MASK);

// CONFIG.MODE encoding (cross_trigger_port.rdl): 0 wire-OR, 1 point-to-point.
localparam int unsigned DtpCtpModeWireOr = 0;
localparam int unsigned DtpCtpModeP2p = 1;

// STATUS fields (read-only, volatile).
localparam bit [31:0] DtpCtpStatusBusy = 32'(CROSS_TRIGGER_PORT_STATUS_BUSY_MASK);
localparam bit [31:0] DtpCtpStatusReqOut = 32'(CROSS_TRIGGER_PORT_STATUS_REQ_OUT_MASK);
localparam bit [31:0] DtpCtpStatusAckIn = 32'(CROSS_TRIGGER_PORT_STATUS_ACK_IN_MASK);
localparam bit [31:0] DtpCtpStatusReqIn = 32'(CROSS_TRIGGER_PORT_STATUS_REQ_IN_MASK);
localparam bit [31:0] DtpCtpStatusAckOut = 32'(CROSS_TRIGGER_PORT_STATUS_ACK_OUT_MASK);

typedef enum int unsigned {
  DTP_XTRIG_CSR_UNMAPPED    = 0,
  DTP_XTRIG_CSR_CTM_SELECT  = 1,
  DTP_XTRIG_CSR_CTP_CONFIG  = 2,
  DTP_XTRIG_CSR_CTP_STATUS  = 3,
  DTP_XTRIG_CSR_CTP_STRETCH = 4
} dtp_xtrig_csr_kind_e;

function automatic bit [63:0] dtp_xtrig_ctm_config_addr(int unsigned src_idx);
  return DtpXtrigCtmBase + src_idx * DtpXtrigCtmStride;
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

// Classify a CSR address and return the writable (readback) mask of the
// register it names; UNMAPPED covers holes and the DECERR space.
function automatic dtp_xtrig_csr_kind_e dtp_xtrig_csr_decode(bit [63:0] addr,
                                                             output bit [31:0] mask);
  bit [63:0] offset;
  mask = '0;
  if (addr < DtpXtrigCtpBase) begin
    if ((addr % DtpXtrigCtmStride) != 0 || (addr / DtpXtrigCtmStride) >= DtpXtrigNumCtmPorts)
      return DTP_XTRIG_CSR_UNMAPPED;
    mask = DtpCtmSelectMask;
    return DTP_XTRIG_CSR_CTM_SELECT;
  end
  if (addr >= DtpXtrigUnmappedBase) return DTP_XTRIG_CSR_UNMAPPED;
  offset = (addr - DtpXtrigCtpBase) % DtpXtrigCtpStride;
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
    default:             return DTP_XTRIG_CSR_UNMAPPED;
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

// ---------------------------------------------------------------------------
// Evidence policy carried from the test cfg to the env cfg.
// ---------------------------------------------------------------------------

// Required-ID policy of one shared-VIP evidence recorder (a passive AXI port
// or the aggregate JTAG checker).
typedef struct {
  bit    require_checks;
  string required_ids[$];
} dtp_evidence_policy_t;
