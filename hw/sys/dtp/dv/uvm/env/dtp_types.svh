// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP bench constants, DUT geometry, and pure codec functions shared by the
// environment (scoreboard predictors, virtual sequencer, cfgs) and the
// sequence library (reusable operations, scenario helpers). The cocotb twin
// is env/dtp_types.py plus env/dtp_xtrig_types.py. Register opcodes and
// geometry come from the generated DUT collateral (jtag_inst_reg_pkg,
// cross_trigger_*_pkg, dtp_pkg); the few bench-only constants cite their
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

// Scoreboard feature names (dtp_scoreboard predictors; test cfg policy).
localparam string DtpFeatureIrDecode = "ir_decode";
localparam string DtpFeatureIdcode   = "idcode";
localparam string DtpFeatureBypass   = "bypass";
localparam string DtpFeatureXtrigCsr    = "xtrig_csr";
localparam string DtpFeatureXtrigDecode = "xtrig_decode";

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

function automatic dtp_j2a_target_t dtp_j2a_target_smc_otp();
    dtp_j2a_target_t t;
    t.name                          = "smc_otp";
    t.single_op_instr               = jtag_inst_reg_pkg::SMC_OTP_AXI_SINGLE_OP_INSTR;
    t.series_ctrl_instr             = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_CTRL_INSTR;
    t.series_data_incr_instr        = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_INCR_INSTR;
    t.series_data_no_incr_instr     = jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
    t.series_data_with_status_instr =
        jtag_inst_reg_pkg::SMC_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
    t.addr_width       = 32;
    t.data_width       = 32;
    t.size_bits        = 2;
    t.wstrb_bits       = 4;
    t.default_size     = 2;
    t.beat_bytes       = 4;
    t.dbg_disable_mask = '0;
    t.dbg_disable_mask.smc_otp_jtag2axi = 1'b1;
    return t;
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_sep_otp();
    dtp_j2a_target_t t;
    t.name                          = "sep_otp";
    t.single_op_instr               = jtag_inst_reg_pkg::SEP_OTP_AXI_SINGLE_OP_INSTR;
    t.series_ctrl_instr             = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_CTRL_INSTR;
    t.series_data_incr_instr        = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_INCR_INSTR;
    t.series_data_no_incr_instr     = jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_NO_INCR_INSTR;
    t.series_data_with_status_instr =
        jtag_inst_reg_pkg::SEP_OTP_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
    t.addr_width       = 32;
    t.data_width       = 32;
    t.size_bits        = 2;
    t.wstrb_bits       = 4;
    t.default_size     = 2;
    t.beat_bytes       = 4;
    t.dbg_disable_mask = '0;
    t.dbg_disable_mask.sep_otp_jtag2axi = 1'b1;
    return t;
endfunction

function automatic dtp_j2a_target_t dtp_j2a_target_smc_axi();
    dtp_j2a_target_t t;
    t.name                          = "smc_axi";
    t.single_op_instr               = jtag_inst_reg_pkg::SMC_AXI_SINGLE_OP_INSTR;
    t.series_ctrl_instr             = jtag_inst_reg_pkg::SMC_AXI_SERIES_CTRL_INSTR;
    t.series_data_incr_instr        = jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_INCR_INSTR;
    t.series_data_no_incr_instr     = jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_NO_INCR_INSTR;
    t.series_data_with_status_instr =
        jtag_inst_reg_pkg::SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS_INSTR;
    t.addr_width       = 56;
    t.data_width       = 64;
    t.size_bits        = 2;
    t.wstrb_bits       = 8;
    t.default_size     = 3;
    t.beat_bytes       = 8;
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

function automatic int unsigned dtp_j2a_size_bytes(int unsigned size);
    return 1 << size;
endfunction

function automatic bit [63:0] dtp_j2a_data_mask(int unsigned size);
    return ocah_rng::bit_mask(8 * dtp_j2a_size_bytes(size));
endfunction

function automatic bit [7:0] dtp_j2a_full_wstrb(int unsigned size);
    return 8'((1 << dtp_j2a_size_bytes(size)) - 1);
endfunction

// SINGLE_OP DR packing (LSB-first: OP | SIZE | WSTRB | DATA | ADDR).
function automatic void dtp_j2a_pack_single_op(
    dtp_j2a_target_t t,
    dtp_j2a_op_e     op,
    bit [63:0]       addr,
    bit [63:0]       data,
    bit [7:0]        wstrb,
    int unsigned     size,
    ref bit          dr[]
);
    int unsigned offset = 0;
    dr = new[dtp_j2a_single_op_len(t)];
    foreach (dr[i]) dr[i] = 1'b0;
    for (int unsigned i = 0; i < 2; i++)            dr[offset++] = (int'(op) >> i) & 1'b1;
    for (int unsigned i = 0; i < t.size_bits; i++)  dr[offset++] = (size >> i) & 1'b1;
    for (int unsigned i = 0; i < t.wstrb_bits; i++) dr[offset++] = (wstrb >> i) & 1'b1;
    for (int unsigned i = 0; i < t.data_width; i++) dr[offset++] = (data >> i) & 1'b1;
    for (int unsigned i = 0; i < t.addr_width; i++) dr[offset++] = (addr >> i) & 1'b1;
endfunction

function automatic void dtp_j2a_unpack_single_op(
    dtp_j2a_target_t        t,
    bit                     rbits[],
    output dtp_j2a_status_e status,
    output bit [63:0]       rdata
);
    int unsigned data_off   = 2 + t.size_bits + t.wstrb_bits;
    int unsigned status_raw = 0;
    rdata = '0;
    for (int unsigned i = 0; i < 2 && i < rbits.size(); i++)
        status_raw |= int'(rbits[i]) << i;
    status = dtp_j2a_status_e'(status_raw);
    for (int unsigned i = 0; i < t.data_width && (data_off + i) < rbits.size(); i++)
        rdata[i] = rbits[data_off + i];
endfunction

// SERIES_CTRL packing (LSB-first: OP | SIZE | PL_DEPTH | ADDR | RESET).
function automatic bit [63:0] dtp_j2a_pack_series_ctrl(
    dtp_j2a_target_t t,
    dtp_j2a_op_e     op,
    bit [63:0]       addr,
    int unsigned     pipeline_depth,
    int unsigned     size,
    bit              series_reset
);
    int unsigned size_off     = 2;
    int unsigned pl_depth_off = size_off + t.size_bits;
    int unsigned addr_off     = pl_depth_off + 2;
    int unsigned reset_off    = addr_off + t.addr_width;
    return (64'(int'(op)) & 64'h3)
         | ((64'(size) & ocah_rng::bit_mask(t.size_bits)) << size_off)
         | ((64'(pipeline_depth) & 64'h3) << pl_depth_off)
         | ((addr & ocah_rng::bit_mask(t.addr_width)) << addr_off)
         | (64'(series_reset) << reset_off);
endfunction

function automatic void dtp_j2a_unpack_series_ctrl(
    dtp_j2a_target_t        t,
    bit [63:0]              value,
    output bit              series_reset,
    output bit [63:0]       addr,
    output int unsigned     pipeline_depth,
    output int unsigned     size,
    output dtp_j2a_status_e status
);
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
localparam int unsigned DtpStapCount     = 4;
localparam int unsigned DtpPtapIrWidth   = DtpIrWidth;
// IEEE 1149.1: a TAP's IR capture presents 01 in its two LSBs.
localparam bit [63:0]   DtpStapDsIrCapture = 64'h1;

// Composed-scan kind: TAP_3DCR data scan (PTAP 3DCR first) or instruction
// scan (PTAP IR first, PTAP 3DCR absent).
typedef enum int unsigned {
    DTP_SCAN_DR = 0,
    DTP_SCAN_IR = 1
} dtp_scan_kind_e;

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
localparam int unsigned DtpStapDsIrWidth   = 5;
localparam bit [63:0]   DtpStapDsTdrOpcode = 64'h2;
localparam string       DtpStapDsTdrName   = "DS_TDR";

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
// Cross-trigger CSR block (dtp_xtrig_types.py parity). The port counts and
// the block layout come from the RTL and register packages; the register
// masks follow the generated cross_trigger_port_reg_pkg field widths.
// ---------------------------------------------------------------------------

localparam int unsigned DtpXtrigNumCtp      = dtp_pkg::DEFAULT_NUM_CTP;
localparam int unsigned DtpXtrigNumIntCt    = dtp_pkg::DEFAULT_NUM_INT_CT;
localparam int unsigned DtpXtrigNumCtmPorts = DtpXtrigNumCtp + DtpXtrigNumIntCt;

localparam bit [63:0]   DtpXtrigCtmBase   = 64'h0;
localparam int unsigned DtpXtrigCtmStride =
    int'(cross_trigger_matrix_addrmap_pkg::CROSS_TRIGGER_MATRIX_CT_SRC_STRIDE);
localparam bit [63:0]   DtpXtrigCtpBase   = 64'(cross_trigger_network_pkg::CSR_ADDR_CTM_SIZE);
localparam int unsigned DtpXtrigCtpStride = cross_trigger_network_pkg::CSR_ADDR_CTP_SIZE;
localparam bit [63:0]   DtpXtrigUnmappedBase = DtpXtrigCtpBase + DtpXtrigNumCtp * DtpXtrigCtpStride;

localparam int unsigned DtpCtpConfigOffset  =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_CONFIG_BASE_ADDR);
localparam int unsigned DtpCtpStatusOffset  =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_STATUS_BASE_ADDR);
localparam int unsigned DtpCtpStretchOffset =
    int'(cross_trigger_port_addrmap_pkg::CROSS_TRIGGER_PORT_STRETCH_MULT_BASE_ADDR);

// CONFIG fields MODE[0], INVERT[1], RESET[2]; STRETCH_MULT[15:0]; CT_SRC
// CONFIG_0 select[NumCtmPorts-1:0]. Every field resets to zero.
localparam bit [31:0] DtpCtpConfigModeMask   = 32'h1;
localparam bit [31:0] DtpCtpConfigInvertMask = 32'h2;
localparam bit [31:0] DtpCtpConfigResetMask  = 32'h4;
localparam bit [31:0] DtpCtpConfigMask       = 32'h7;
localparam bit [31:0] DtpCtpStretchMask      = 32'hFFFF;
localparam bit [31:0] DtpCtmSelectMask       = (32'd1 << DtpXtrigNumCtmPorts) - 1;

localparam int unsigned DtpCtpModeWireOr = 0;
localparam int unsigned DtpCtpModeP2p    = 1;

// STATUS fields (read-only, volatile).
localparam bit [31:0] DtpCtpStatusBusy   = 32'h01;
localparam bit [31:0] DtpCtpStatusReqOut = 32'h10;
localparam bit [31:0] DtpCtpStatusAckIn  = 32'h20;
localparam bit [31:0] DtpCtpStatusReqIn  = 32'h40;
localparam bit [31:0] DtpCtpStatusAckOut = 32'h80;

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
    if (addr >= DtpXtrigUnmappedBase)
        return DTP_XTRIG_CSR_UNMAPPED;
    offset = (addr - DtpXtrigCtpBase) % DtpXtrigCtpStride;
    case (offset)
        DtpCtpConfigOffset:  begin mask = DtpCtpConfigMask;  return DTP_XTRIG_CSR_CTP_CONFIG;  end
        DtpCtpStatusOffset:  begin mask = '0;                return DTP_XTRIG_CSR_CTP_STATUS;  end
        DtpCtpStretchOffset: begin mask = DtpCtpStretchMask; return DTP_XTRIG_CSR_CTP_STRETCH; end
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
