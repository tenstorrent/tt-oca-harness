// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU traffic-filter functional coverage: smu_filter_match_cg of
// SMU_FCOV.adoc, the match terms and the verdict of the three filter
// instances the wrapper reaches (SMC inbound, SMC outbound, SEP outbound),
// and the five deny-per-term cover properties of the SMC inbound instance.
//
// The entry fields come from the FILTER_CONFIG writes on the bus the owner
// programs them over: the DTP-to-SMC debug AXI (the SMC fabric JTAG2AXI
// bridge) for the two SMC instances, the SEP debug module's system bus for
// the SEP instance. A probe pairs with the entry whose FILTER_CONFIG the
// owner wrote last on that instance. A probe is an access of the owner's
// master outside the local register map of its subsystem (the SMC local
// window for the bridge, the SMU aperture for the system bus); the SMC
// inbound probes are the inbound SMN accesses themselves. The verdict is the
// response code of the probe on its own bus: admitted on OKAY, blocked on
// DECERR (hw/ip/axi_filter/doc/index.adoc, "Blocked Transactions": the filter
// steers a blocked access to an AXI error subordinate that answers DECERR);
// this module's definition of blocked is stricter, it also requires no
// address phase on u_axi_out_if since the probe's accept, so a DECERR a
// subordinate behind the crossbar answers is no verdict. The iDMA copy of
// the SMC outbound instance is sampled at the NEXT_ID_0 read that launches
// it, with the AxPROT[1] of the most recent multi-beat SMC-prefixed AW on
// u_axi_out_if, learned from the reset-entry copy the owner runs first and
// refreshed by each landed copy (the launch read precedes the copy's own
// AWs, and a refused copy presents none). On
// the two outbound instances an admitted verdict also requires an address
// phase on u_axi_out_if since the probe's accept, so an OKAY answered inside
// the subsystem is no verdict either. Four cells the owner walks count only
// at the verdict the documents state for them, while the entry under test is
// the one enabled entry of its instance (index.adoc, "Match, Then Permit":
// allow_ns is an equality test, so an entry whose allow_ns differs from the
// access's AxPROT[1] matches nothing and the access takes the instance's
// unmatched-traffic policy, permitted on the SMC outbound instance and
// blocked on the SEP outbound instance): an entry refusing the bridge's
// AxPROT[1] alone on the SMC outbound instance admits a bridge access; an
// allow_ns 0 entry alone on the SEP outbound instance blocks a system-bus
// access; a src_id 3 entry alone on the SMC outbound instance, SMC_ID on the
// direct path (hw/sys/smc/doc/fabric.adoc, "SMC Source ID by Traffic Path"),
// matches a bridge access and its cleared permission of the channel blocks
// it; and an entry with another non-zero src_id alone admits the access. The
// SEP's source ID is stated by no document, so its non-zero src_id cell
// counts at the address phase. The SEP's SMU path sets AxPROT[1] to the
// inverse of address bit 55 (hw/sys/sep/doc/fabric.adoc, "Source ID and NS
// of SEP outbound traffic"), so a 32-bit system-bus address reaches the SEP
// outbound filter with AxPROT[1] 1: a SEP probe is sampled only when the
// filter's request port carries that value, and one carrying 0 samples no
// cell.
//
// One passive module. Every port is a signal of the bench top: the ext_in
// pins, u_axi_out_if, and three hierarchical taps of tb_wrapper_top.sv, the
// DTP-to-SMC debug AXI (u_dut.u_smu.dtp_axi_smc_dbg_req/resp), the SEP
// debug module's system-bus port (u_sep_cpu.dbg_axi_req_raw/dbg_axi_resp_raw,
// read where the EL2 debug module drives it) and the SEP outbound filter's
// request port (u_sep_system_peripherals.pre_outbound_filter_axi_req/resp).
// The SEP instance's AxPROT[1] is read at the filter's request port: the
// SEP's SMU path sets it from address bit 55, so it differs from the AxPROT
// the debug module issues on its system bus. Samples are taken only while
// the owning leaf holds tb_fcov_gate high; the under-test state clears when
// the gate rises.
//
// The reset values of smc_base_config.rdl LOCAL_BASE and REGION_SIZE and of
// sep_cpu_ctrl.rdl SMU_GLOBAL_BASE_ADDR and SMU_REGION_SIZE, which bound the
// probes, and the FILTER_CONFIG field positions of filter_ctrl.rdl come from
// the generated register headers (smu_fcov_smc_csr_pkg and
// smu_fcov_sep_csr_pkg). The module assumes the reset apertures: a leaf that
// reprograms LOCAL_BASE or SMU_GLOBAL_BASE_ADDR moves the probe windows
// without moving these bounds.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_filter_fcov (
  input wire clk_smu_i,
  input wire rst_cold_ni,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i,

  // Inbound SMN port: the SMC inbound instance's accesses.
  input wire s_axi_awvalid_i,
  input wire s_axi_awready_i,
  input wire [55:0] s_axi_awaddr_i,
  input wire [7:0] s_axi_awlen_i,
  input wire [2:0] s_axi_awprot_i,
  input wire [11:0] s_axi_awuser_i,
  input wire s_axi_bvalid_i,
  input wire s_axi_bready_i,
  input wire [1:0] s_axi_bresp_i,
  input wire s_axi_arvalid_i,
  input wire s_axi_arready_i,
  input wire [55:0] s_axi_araddr_i,
  input wire [7:0] s_axi_arlen_i,
  input wire [2:0] s_axi_arprot_i,
  input wire [11:0] s_axi_aruser_i,
  input wire s_axi_rvalid_i,
  input wire s_axi_rready_i,
  input wire s_axi_rlast_i,
  input wire [1:0] s_axi_rresp_i,

  // DTP-to-SMC debug AXI: the SMC fabric JTAG2AXI bridge's bus.
  input wire smc_dbg_awvalid_i,
  input wire smc_dbg_awready_i,
  input wire [55:0] smc_dbg_awaddr_i,
  input wire [7:0] smc_dbg_awlen_i,
  input wire [2:0] smc_dbg_awprot_i,
  input wire smc_dbg_wvalid_i,
  input wire smc_dbg_wready_i,
  input wire [63:0] smc_dbg_wdata_i,
  input wire smc_dbg_bvalid_i,
  input wire smc_dbg_bready_i,
  input wire [1:0] smc_dbg_bresp_i,
  input wire smc_dbg_arvalid_i,
  input wire smc_dbg_arready_i,
  input wire [55:0] smc_dbg_araddr_i,
  input wire [7:0] smc_dbg_arlen_i,
  input wire [2:0] smc_dbg_arprot_i,
  input wire smc_dbg_rvalid_i,
  input wire smc_dbg_rready_i,
  input wire smc_dbg_rlast_i,
  input wire [1:0] smc_dbg_rresp_i,

  // SEP debug module system bus.
  input wire sep_sb_awvalid_i,
  input wire sep_sb_awready_i,
  input wire [31:0] sep_sb_awaddr_i,
  input wire sep_sb_wvalid_i,
  input wire sep_sb_wready_i,
  input wire [63:0] sep_sb_wdata_i,
  input wire sep_sb_bvalid_i,
  input wire sep_sb_bready_i,
  input wire [1:0] sep_sb_bresp_i,
  input wire sep_sb_arvalid_i,
  input wire sep_sb_arready_i,
  input wire [31:0] sep_sb_araddr_i,
  input wire sep_sb_rvalid_i,
  input wire sep_sb_rready_i,
  input wire sep_sb_rlast_i,
  input wire [1:0] sep_sb_rresp_i,

  // The SEP outbound filter's request port: the AxPROT[1] the filter matches
  // against allow_ns, and the length of the same address phase.
  input wire sep_flt_awvalid_i,
  input wire sep_flt_awready_i,
  input wire [7:0] sep_flt_awlen_i,
  input wire [2:0] sep_flt_awprot_i,
  input wire sep_flt_arvalid_i,
  input wire sep_flt_arready_i,
  input wire [7:0] sep_flt_arlen_i,
  input wire [2:0] sep_flt_arprot_i,

  // Outbound boundary interface (u_axi_out_if): the address phases that tell
  // a reached responder from a blocked access, and the iDMA copy's AxPROT.
  input wire out_awvalid_i,
  input wire out_awready_i,
  input wire [15:0] out_awid_i,
  input wire [7:0] out_awlen_i,
  input wire [2:0] out_awprot_i,
  input wire out_arvalid_i,
  input wire out_arready_i
);

  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR;
  import smc_top_addrmap_pkg::
      SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE;
  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_NEXT_ID_0_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM;
  import sep_top_addrmap_pkg::SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE;
  import smu_fcov_smc_csr_pkg::SMC_BASE_CONFIG_LOCAL_BASE_REG_DEFAULT;
  import smu_fcov_smc_csr_pkg::SMC_BASE_CONFIG_REGION_SIZE_REG_DEFAULT;
  import smu_fcov_smc_csr_pkg::FILTER_CTRL_FILTER_CONFIG_READ_ALLOWED_SHIFT;
  import smu_fcov_smc_csr_pkg::FILTER_CTRL_FILTER_CONFIG_WRITE_ALLOWED_SHIFT;
  import smu_fcov_smc_csr_pkg::FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_SHIFT;
  import smu_fcov_smc_csr_pkg::FILTER_CTRL_FILTER_CONFIG_ALLOW_NS_SHIFT;
  import smu_fcov_smc_csr_pkg::FILTER_CTRL_FILTER_CONFIG_SRC_ID_SHIFT;
  import smu_fcov_smc_csr_pkg::FILTER_CTRL_FILTER_CONFIG_SRC_ID_MASK;
  import smu_fcov_smc_csr_pkg::FILTER_CTRL_FILTER_CONFIG_ALLOW_BURST_SHIFT;
  import smu_fcov_sep_csr_pkg::SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_DEFAULT;
  import smu_fcov_sep_csr_pkg::SEP_CPU_CTRL_SMU_REGION_SIZE_REG_DEFAULT;

  // Entry registers per instance (filter_ctrl.rdl): the base of the entries,
  // their stride and the offsets of FILTER_CONFIG, START_ADDR and END_ADDR
  // inside an entry, from the generated address map.
  localparam logic [55:0] SysInBase =
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(
      0
  ));
  localparam logic [55:0] SysInSpan = 56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM
                                          * SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  localparam logic [55:0] SmcOutBase =
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(
      0
  ));
  localparam logic [55:0] SmcOutSpan = 56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM
                                           * SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  localparam logic [31:0] SepOutBase =
      32'(SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(
      0
  ));
  localparam logic [31:0] SepOutSpan = 32'(SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM
                                           * SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  localparam logic [55:0] SysInStride =
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  localparam logic [55:0] SmcOutStride =
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  localparam logic [31:0] SepOutStride = 32'(SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_STRIDE);
  localparam int unsigned SysInIdxLsb = $clog2(SysInStride);
  localparam int unsigned SmcOutIdxLsb = $clog2(SmcOutStride);
  localparam int unsigned SepOutIdxLsb = $clog2(SepOutStride);
  localparam logic [55:0] SysInCfgOff =
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(
      0
  )) - SysInBase;
  localparam logic [55:0] SysInStartOff =
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR(
      0
  )) - SysInBase;
  localparam logic [55:0] SysInEndOff =
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR(
      0
  )) - SysInBase;
  localparam logic [55:0] SmcOutCfgOff =
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(
      0
  )) - SmcOutBase;
  localparam logic [31:0] SepOutCfgOff =
      32'(SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(
      0
  )) - SepOutBase;
  localparam logic [55:0] DmaNextIdAddr = 56'(SMC_TOP_DMA_CTRL_NEXT_ID_0_BASE_ADDR);
  // smc_base_config.rdl LOCAL_BASE and REGION_SIZE reset values: the SMC local
  // window, inside which a bridge access is a register access, not a probe.
  localparam logic [55:0] SmcLocalBase = 56'(SMC_BASE_CONFIG_LOCAL_BASE_REG_DEFAULT);
  localparam logic [55:0] SmcLocalSize = 56'(SMC_BASE_CONFIG_REGION_SIZE_REG_DEFAULT);
  // sep_cpu_ctrl.rdl SMU_GLOBAL_BASE_ADDR and SMU_REGION_SIZE reset values:
  // the SMU aperture, through which the system bus reaches the responder.
  localparam logic [31:0] SmuApertureBase = 32'(SEP_CPU_CTRL_SMU_GLOBAL_BASE_ADDR_REG_DEFAULT);
  localparam logic [31:0] SmuApertureSize = 32'(SEP_CPU_CTRL_SMU_REGION_SIZE_REG_DEFAULT);
  localparam logic [1:0] RespOkay = 2'b00;
  localparam logic [1:0] RespDecerr = 2'b11;
  // Bits [9:8] of an outbound ID are the crossbar's slave-port index, the
  // prefix cg_smn_ids (smu_ext_fcov.sv) decodes: 1 for smc_out.
  localparam logic [1:0] PrefixFromSmc = 2'b01;

  // FILTER_CONFIG field positions (filter_ctrl.rdl).
  localparam int unsigned CfgReadAllowed = FILTER_CTRL_FILTER_CONFIG_READ_ALLOWED_SHIFT;
  localparam int unsigned CfgWriteAllowed = FILTER_CTRL_FILTER_CONFIG_WRITE_ALLOWED_SHIFT;
  localparam int unsigned CfgEntryEnabled = FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_SHIFT;
  localparam int unsigned CfgAllowNs = FILTER_CTRL_FILTER_CONFIG_ALLOW_NS_SHIFT;
  localparam int unsigned CfgSrcIdLsb = FILTER_CTRL_FILTER_CONFIG_SRC_ID_SHIFT;
  localparam int unsigned CfgSrcIdWidth = $countones(FILTER_CTRL_FILTER_CONFIG_SRC_ID_MASK);
  localparam int unsigned CfgAllowBurst = FILTER_CTRL_FILTER_CONFIG_ALLOW_BURST_SHIFT;

  // Instance codes of the tuples.
  localparam logic [1:0] InstSysIn = 2'd0;
  localparam logic [1:0] InstSmcOut = 2'd1;
  localparam logic [1:0] InstSepOut = 2'd2;
  // Source-ID classes: wildcard (src_id 0), equal, differing, and a non-zero
  // src_id on the SEP outbound instance, whose source ID is not stated. On
  // the SMC outbound instance the bridge's direct-path source ID is SMC_ID 3
  // (hw/sys/smc/doc/fabric.adoc), so a non-zero src_id is equal or differing.
  localparam logic [CfgSrcIdWidth-1:0] SmcSourceId = CfgSrcIdWidth'(3);
  localparam logic [1:0] SrcWildcard = 2'd0;
  localparam logic [1:0] SrcEqual = 2'd1;
  localparam logic [1:0] SrcDiffering = 2'd2;
  localparam logic [1:0] SrcNonzero = 2'd3;
  // The AxPROT[1] of a 32-bit system-bus address at the SEP outbound filter:
  // the inverse of address bit 55 (hw/sys/sep/doc/fabric.adoc, "Source ID and
  // NS of SEP outbound traffic").
  localparam logic SepOutNs = 1'b1;

  wire in_reset = (rst_cold_ni !== 1'b1);
  wire gate_on = (fcov_gate_i === 1'b1);

  logic gate_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) gate_q <= 1'b0;
    else gate_q <= gate_on;
  end
  wire gate_rose = gate_on && !gate_q;

  // ------------------------------------------------------------------
  // Register writes on the two debug buses: the address at the AW accept,
  // the data at the W accept, committed on an OKAY B. Both masters issue
  // single-beat operations with one outstanding.
  // ------------------------------------------------------------------
  wire smc_aw_acc = (smc_dbg_awvalid_i === 1'b1) && (smc_dbg_awready_i === 1'b1);
  wire smc_w_acc = (smc_dbg_wvalid_i === 1'b1) && (smc_dbg_wready_i === 1'b1);
  wire smc_b_acc = (smc_dbg_bvalid_i === 1'b1) && (smc_dbg_bready_i === 1'b1);
  wire smc_ar_acc = (smc_dbg_arvalid_i === 1'b1) && (smc_dbg_arready_i === 1'b1);
  wire smc_r_last_acc = (smc_dbg_rvalid_i === 1'b1) && (smc_dbg_rready_i === 1'b1)
      && (smc_dbg_rlast_i === 1'b1);
  wire sep_aw_acc = (sep_sb_awvalid_i === 1'b1) && (sep_sb_awready_i === 1'b1);
  wire sep_w_acc = (sep_sb_wvalid_i === 1'b1) && (sep_sb_wready_i === 1'b1);
  wire sep_b_acc = (sep_sb_bvalid_i === 1'b1) && (sep_sb_bready_i === 1'b1);
  wire sep_ar_acc = (sep_sb_arvalid_i === 1'b1) && (sep_sb_arready_i === 1'b1);
  wire sep_r_last_acc = (sep_sb_rvalid_i === 1'b1) && (sep_sb_rready_i === 1'b1)
      && (sep_sb_rlast_i === 1'b1);
  wire sep_flt_aw_acc = (sep_flt_awvalid_i === 1'b1) && (sep_flt_awready_i === 1'b1);
  wire sep_flt_ar_acc = (sep_flt_arvalid_i === 1'b1) && (sep_flt_arready_i === 1'b1);

  logic [55:0] smc_wr_addr_q;
  logic [63:0] smc_wr_data_q;
  logic [31:0] sep_wr_addr_q;
  logic [63:0] sep_wr_data_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      smc_wr_addr_q <= '0;
      smc_wr_data_q <= '0;
      sep_wr_addr_q <= '0;
      sep_wr_data_q <= '0;
    end else begin
      if (smc_aw_acc) smc_wr_addr_q <= smc_dbg_awaddr_i;
      if (smc_w_acc) smc_wr_data_q <= smc_dbg_wdata_i;
      if (sep_aw_acc) sep_wr_addr_q <= sep_sb_awaddr_i;
      if (sep_w_acc) sep_wr_data_q <= sep_sb_wdata_i;
    end
  end

  wire smc_wr_commit = smc_b_acc && (smc_dbg_bresp_i === RespOkay);
  wire sep_wr_commit = sep_b_acc && (sep_sb_bresp_i === RespOkay);
  wire [55:0] sys_in_off = smc_wr_addr_q - SysInBase;
  wire [55:0] smc_out_off = smc_wr_addr_q - SmcOutBase;
  wire [31:0] sep_out_off = sep_wr_addr_q - SepOutBase;
  wire sys_in_wr = smc_wr_commit && (smc_wr_addr_q >= SysInBase) && (sys_in_off < SysInSpan);
  wire smc_out_wr = smc_wr_commit && (smc_wr_addr_q >= SmcOutBase) && (smc_out_off < SmcOutSpan);
  wire sep_out_wr = sep_wr_commit && (sep_wr_addr_q >= SepOutBase) && (sep_out_off < SepOutSpan);
  wire [3:0] sys_in_wr_idx = 4'(sys_in_off >> SysInIdxLsb);
  wire [3:0] smc_out_wr_idx = 4'(smc_out_off >> SmcOutIdxLsb);
  wire [4:0] sep_out_wr_idx = 5'(sep_out_off >> SepOutIdxLsb);
  wire [55:0] sys_in_wr_reg = sys_in_off & (SysInStride - 56'd1);
  wire [55:0] smc_out_wr_reg = smc_out_off & (SmcOutStride - 56'd1);
  wire [31:0] sep_out_wr_reg = sep_out_off & (SepOutStride - 32'd1);

  // ------------------------------------------------------------------
  // Per-instance state: the entry under test (the last FILTER_CONFIG
  // written), the enabled-entry set and the order of its two most recent
  // members (the overlap cell's programming order), the read and write
  // permissions of every entry (the overlap cell's permission split), and
  // for the SMC inbound
  // instance the START_ADDR and END_ADDR of every entry (the range term).
  // ------------------------------------------------------------------
  logic [31:0] eut_cfg_q[3];
  logic [4:0] eut_idx_q[3];
  logic eut_valid_q[3];
  logic [31:0] en_map_q[3];
  logic [31:0] rd_map_q[3];
  logic [31:0] wr_map_q[3];
  logic [4:0] last_en_q[3];
  logic [4:0] prev_en_q[3];
  logic [55:0] sys_in_start_q[16];
  logic [55:0] sys_in_end_q[16];

  function automatic logic [31:0] cfg_commit(input logic [63:0] data);
    return data[31:0];
  endfunction

  function automatic logic [5:0] popcount32(input logic [31:0] v);
    logic [5:0] n;
    n = '0;
    for (int unsigned i = 0; i < 32; i++) n = n + 6'(v[i]);
    return n;
  endfunction

  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      for (int unsigned k = 0; k < 3; k++) begin
        eut_cfg_q[k] <= '0;
        eut_idx_q[k] <= '0;
        eut_valid_q[k] <= 1'b0;
        en_map_q[k] <= '0;
        rd_map_q[k] <= '0;
        wr_map_q[k] <= '0;
        last_en_q[k] <= '0;
        prev_en_q[k] <= '0;
      end
      for (int unsigned e = 0; e < 16; e++) begin
        sys_in_start_q[e] <= '0;
        sys_in_end_q[e] <= '0;
      end
    end else if (gate_rose) begin
      for (int unsigned k = 0; k < 3; k++) begin
        eut_valid_q[k] <= 1'b0;
        en_map_q[k] <= '0;
        rd_map_q[k] <= '0;
        wr_map_q[k] <= '0;
      end
    end else begin
      if (sys_in_wr && (sys_in_wr_reg == SysInCfgOff)) begin
        eut_cfg_q[InstSysIn] <= cfg_commit(smc_wr_data_q);
        eut_idx_q[InstSysIn] <= 5'(sys_in_wr_idx);
        eut_valid_q[InstSysIn] <= 1'b1;
        en_map_q[InstSysIn][sys_in_wr_idx] <= smc_wr_data_q[CfgEntryEnabled];
        rd_map_q[InstSysIn][sys_in_wr_idx] <= smc_wr_data_q[CfgReadAllowed];
        wr_map_q[InstSysIn][sys_in_wr_idx] <= smc_wr_data_q[CfgWriteAllowed];
        if (smc_wr_data_q[CfgEntryEnabled] && (last_en_q[InstSysIn] != 5'(sys_in_wr_idx))) begin
          prev_en_q[InstSysIn] <= last_en_q[InstSysIn];
          last_en_q[InstSysIn] <= 5'(sys_in_wr_idx);
        end
      end
      if (sys_in_wr && (sys_in_wr_reg == SysInStartOff)) begin
        sys_in_start_q[sys_in_wr_idx] <= smc_wr_data_q[55:0];
      end
      if (sys_in_wr && (sys_in_wr_reg == SysInEndOff)) begin
        sys_in_end_q[sys_in_wr_idx] <= smc_wr_data_q[55:0];
      end
      if (smc_out_wr && (smc_out_wr_reg == SmcOutCfgOff)) begin
        eut_cfg_q[InstSmcOut] <= cfg_commit(smc_wr_data_q);
        eut_idx_q[InstSmcOut] <= 5'(smc_out_wr_idx);
        eut_valid_q[InstSmcOut] <= 1'b1;
        en_map_q[InstSmcOut][smc_out_wr_idx] <= smc_wr_data_q[CfgEntryEnabled];
        rd_map_q[InstSmcOut][smc_out_wr_idx] <= smc_wr_data_q[CfgReadAllowed];
        wr_map_q[InstSmcOut][smc_out_wr_idx] <= smc_wr_data_q[CfgWriteAllowed];
        if (smc_wr_data_q[CfgEntryEnabled] && (last_en_q[InstSmcOut] != 5'(smc_out_wr_idx))) begin
          prev_en_q[InstSmcOut] <= last_en_q[InstSmcOut];
          last_en_q[InstSmcOut] <= 5'(smc_out_wr_idx);
        end
      end
      if (sep_out_wr && (sep_out_wr_reg == SepOutCfgOff)) begin
        eut_cfg_q[InstSepOut] <= cfg_commit(sep_wr_data_q);
        eut_idx_q[InstSepOut] <= sep_out_wr_idx;
        eut_valid_q[InstSepOut] <= 1'b1;
        en_map_q[InstSepOut][sep_out_wr_idx] <= sep_wr_data_q[CfgEntryEnabled];
        rd_map_q[InstSepOut][sep_out_wr_idx] <= sep_wr_data_q[CfgReadAllowed];
        wr_map_q[InstSepOut][sep_out_wr_idx] <= sep_wr_data_q[CfgWriteAllowed];
        if (sep_wr_data_q[CfgEntryEnabled] && (last_en_q[InstSepOut] != sep_out_wr_idx)) begin
          prev_en_q[InstSepOut] <= last_en_q[InstSepOut];
          last_en_q[InstSepOut] <= sep_out_wr_idx;
        end
      end
    end
  end

  // The fixed entries of the entries the owner extends (SMU_FCOV.adoc,
  // smu_filter_match_cg Ignore bins) pair with no cell.
  function automatic logic fixed_entry(input logic [1:0] inst, input logic [4:0] idx);
    case (inst)
      InstSysIn: return idx == 5'd0;
      InstSmcOut: return idx <= 5'd1;
      default: return (idx <= 5'd1) || (idx == 5'd15) || (idx == 5'd16) || (idx >= 5'd30);
    endcase
  endfunction

  function automatic logic eut_usable(input logic [1:0] inst);
    return eut_valid_q[inst] && !fixed_entry(inst, eut_idx_q[inst]);
  endfunction

  function automatic logic pair_programmed(input logic [1:0] inst);
    return (popcount32(en_map_q[inst]) >= 6'd2) && en_map_q[inst][last_en_q[inst]] &&
        en_map_q[inst][prev_en_q[inst]];
  endfunction

  // 0: the lower-numbered entry was programmed first; 1: the higher first.
  function automatic logic pair_order(input logic [1:0] inst);
    return prev_en_q[inst] > last_en_q[inst];
  endfunction

  localparam logic [1:0] ChAr = 2'd0;
  localparam logic [1:0] ChAw = 2'd1;

  // The overlap cell's permissions: the lower-numbered entry of the pair has
  // the channel's permission clear and the higher-numbered entry has it set.
  function automatic logic pair_perm_split(input logic [1:0] inst, input logic [1:0] ch);
    logic [4:0] lower;
    logic [4:0] higher;
    logic [31:0] perm;
    lower = pair_order(inst) ? last_en_q[inst] : prev_en_q[inst];
    higher = pair_order(inst) ? prev_en_q[inst] : last_en_q[inst];
    perm = (ch == ChAw) ? wr_map_q[inst] : rd_map_q[inst];
    return !perm[lower] && perm[higher];
  endfunction

  function automatic logic [CfgSrcIdWidth-1:0] cfg_src_id(input logic [31:0] cfg);
    return cfg[CfgSrcIdLsb+:CfgSrcIdWidth];
  endfunction

  // ------------------------------------------------------------------
  // The iDMA's AxPROT[1]: the most recent multi-beat SMC-prefixed AW on
  // u_axi_out_if (a non-zero length; the bridge issues single beats only),
  // learned from the reset-entry copy and refreshed by each landed copy.
  // ------------------------------------------------------------------
  wire out_aw_acc = (out_awvalid_i === 1'b1) && (out_awready_i === 1'b1);
  wire out_ar_acc = (out_arvalid_i === 1'b1) && (out_arready_i === 1'b1);
  wire out_addr_phase = out_aw_acc || out_ar_acc;
  wire out_idma_aw = out_aw_acc && (out_awid_i[9:8] == PrefixFromSmc) && (out_awlen_i != 8'd0);

  logic idma_prot1_q, idma_prot1_known_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      idma_prot1_q <= 1'b0;
      idma_prot1_known_q <= 1'b0;
    end else if (out_idma_aw) begin
      idma_prot1_q <= out_awprot_i[1];
      idma_prot1_known_q <= 1'b1;
    end
  end

  // ------------------------------------------------------------------
  // Probes. The SMC inbound probes are the inbound SMN address phases; the
  // SMC outbound probes the bridge accesses outside the SMC local window; the
  // SEP outbound probes the system-bus accesses inside the SMU aperture. One
  // access is outstanding per channel on each master. A pending record keeps
  // the entry the probe paired with, the terms the SMC inbound access met,
  // whether an address phase reached u_axi_out_if since the accept, and for
  // a SEP probe whether the filter's request port has yet to present it.
  // ------------------------------------------------------------------
  wire sys_aw_acc = (s_axi_awvalid_i === 1'b1) && (s_axi_awready_i === 1'b1);
  wire sys_ar_acc = (s_axi_arvalid_i === 1'b1) && (s_axi_arready_i === 1'b1);
  wire sys_b_acc = (s_axi_bvalid_i === 1'b1) && (s_axi_bready_i === 1'b1);
  wire sys_r_last_acc = (s_axi_rvalid_i === 1'b1) && (s_axi_rready_i === 1'b1)
      && (s_axi_rlast_i === 1'b1);
  wire smc_probe_aw = smc_aw_acc && ((smc_dbg_awaddr_i < SmcLocalBase)
                                     || (smc_dbg_awaddr_i >= SmcLocalBase + SmcLocalSize));
  wire smc_probe_ar = smc_ar_acc && ((smc_dbg_araddr_i < SmcLocalBase)
                                     || (smc_dbg_araddr_i >= SmcLocalBase + SmcLocalSize));
  wire smc_launch_ar = smc_ar_acc && (smc_dbg_araddr_i == DmaNextIdAddr);
  wire sep_probe_aw = sep_aw_acc && (sep_sb_awaddr_i >= SmuApertureBase)
      && (sep_sb_awaddr_i < SmuApertureBase + SmuApertureSize);
  wire sep_probe_ar = sep_ar_acc && (sep_sb_araddr_i >= SmuApertureBase)
      && (sep_sb_araddr_i < SmuApertureBase + SmuApertureSize);

  // The match terms of an SMC inbound access against the entry under test
  // (index.adoc "Match, Then Permit"; the range on the granule the entry's
  // allow_burst selects, "Address Range Granule").
  function automatic logic [4:0] sys_in_terms(input logic [31:0] cfg, input logic [55:0] start,
                                              input logic [55:0] last, input logic [55:0] addr,
                                              input logic [2:0] prot, input logic [3:0] user,
                                              input logic [7:0] len);
    logic [55:0] a_g, s_g, e_g;
    logic in_range;
    if (cfg[CfgAllowBurst]) begin
      a_g = {12'd0, addr[55:12]};
      s_g = {12'd0, start[55:12]};
      e_g = {12'd0, last[55:12]};
    end else begin
      a_g = {3'd0, addr[55:3]};
      s_g = {3'd0, start[55:3]};
      e_g = {3'd0, last[55:3]};
    end
    in_range = (a_g >= s_g) && (a_g <= e_g);
    return {
      cfg[CfgEntryEnabled],
      in_range,
      cfg[CfgAllowNs] == prot[1],
      (cfg_src_id(cfg) == '0) || (cfg_src_id(cfg) == user),
      cfg[CfgAllowBurst] || (len == 8'd0)
    };
  endfunction

  function automatic logic [1:0] sys_in_src_class(input logic [31:0] cfg, input logic [3:0] user);
    if (cfg_src_id(cfg) == '0) return SrcWildcard;
    if (cfg_src_id(cfg) == user) return SrcEqual;
    return SrcDiffering;
  endfunction

  function automatic logic [1:0] smc_src_class(input logic [31:0] cfg);
    if (cfg_src_id(cfg) == '0) return SrcWildcard;
    if (cfg_src_id(cfg) == SmcSourceId) return SrcEqual;
    return SrcDiffering;
  endfunction

  function automatic logic [1:0] sep_src_class(input logic [31:0] cfg);
    return (cfg_src_id(cfg) == '0) ? SrcWildcard : SrcNonzero;
  endfunction

  // meas marks a probe of one of the four walked cells; it counts at the
  // verdict when blocked equals meas_blocked, the stated verdict, with the
  // entry's allow_burst meas_ab and the source-ID class meas_src in its
  // tuple (wildcard for the refusing allow_ns cells, equal or differing for
  // the SMC outbound src_id cells).
  typedef struct packed {
    logic valid;
    logic usable;
    logic [4:0] terms;
    logic out_seen;
    logic flt_pending;
    logic meas;
    logic meas_blocked;
    logic meas_ab;
    logic [1:0] meas_src;
  } probe_t;

  probe_t sys_aw_q, sys_ar_q, smc_aw_q, smc_ar_q, sep_aw_q, sep_ar_q;

  function automatic probe_t probe_open(
      input logic usable, input logic [4:0] terms, input logic flt_pending, input logic meas,
      input logic meas_blocked, input logic meas_ab, input logic [1:0] meas_src);
    probe_t p;
    p.valid = 1'b1;
    p.usable = usable;
    p.terms = terms;
    p.out_seen = 1'b0;
    p.flt_pending = flt_pending;
    p.meas = meas;
    p.meas_blocked = meas_blocked;
    p.meas_ab = meas_ab;
    p.meas_src = meas_src;
    return p;
  endfunction

  function automatic logic alone(input logic [1:0] inst);
    return popcount32(en_map_q[inst]) == 6'd1;
  endfunction

  // The tuples of the two SMC outbound src_id cells: a single beat against an
  // entry whose allow_ns admits it, with src_id 3 (equal: the entry matches,
  // and the cell is its cleared permission of the channel blocking the
  // access) or another non-zero src_id (differing: unmatched, admitted);
  // never sampled at the address phase.
  function automatic logic smc_walked(input logic [2:0] prot, input logic [7:0] len,
                                      input int unsigned perm_bit);
    return (smc_src_class(eut_cfg_q[InstSmcOut]) != SrcWildcard) &&
        (eut_cfg_q[InstSmcOut][CfgAllowNs] == prot[1]) && (len == 8'd0) &&
        ((smc_src_class(eut_cfg_q[InstSmcOut]) != SrcEqual) || !eut_cfg_q[InstSmcOut][perm_bit]);
  endfunction

  // The tuple of the SMC outbound refusing allow_ns cell: a single beat with
  // src_id 0 against an entry whose allow_ns refuses it; never sampled at the
  // address phase.
  function automatic logic smc_walked_ns(input logic [2:0] prot, input logic [7:0] len);
    return (smc_src_class(eut_cfg_q[InstSmcOut]) == SrcWildcard) &&
        (eut_cfg_q[InstSmcOut][CfgAllowNs] != prot[1]) && (len == 8'd0);
  endfunction

  // A bridge probe of one of the three cells with the entry under test alone
  // enabled.
  function automatic logic smc_meas(input logic [2:0] prot, input logic [7:0] len,
                                    input int unsigned perm_bit);
    return eut_usable(InstSmcOut) && alone(InstSmcOut) &&
        (smc_walked(prot, len, perm_bit) || smc_walked_ns(prot, len));
  endfunction

  // Its stated verdict: the refusing allow_ns cell and the differing src_id
  // cell are admitted (the entry matches nothing and unmatched traffic
  // passes); the equal src_id cell is blocked.
  function automatic logic smc_meas_blocked(input logic [2:0] prot, input logic [7:0] len);
    return !smc_walked_ns(prot, len) && (smc_src_class(eut_cfg_q[InstSmcOut]) == SrcEqual);
  endfunction

  // The source-ID class of the SMC outbound walked cell a probe presents.
  function automatic logic [1:0] smc_meas_src(input logic [2:0] prot, input logic [7:0] len);
    return smc_walked_ns(prot, len) ? SrcWildcard : smc_src_class(eut_cfg_q[InstSmcOut]);
  endfunction

  // The tuple of the SEP outbound refusing allow_ns cell: a single beat with
  // src_id 0 against an allow_ns 0 entry, the one refusing the AxPROT[1] 1
  // every 32-bit system-bus address carries at the filter; never sampled at
  // the address phase.
  function automatic logic sep_walked(input logic [7:0] len);
    return (sep_src_class(eut_cfg_q[InstSepOut]) == SrcWildcard) &&
        (eut_cfg_q[InstSepOut][CfgAllowNs] != SepOutNs) && (len == 8'd0);
  endfunction

  // A system-bus probe of that cell with the entry under test alone enabled;
  // its stated verdict is blocked.
  function automatic logic sep_meas(input logic [7:0] len);
    return alone(InstSepOut) && sep_walked(len);
  endfunction

  // A SEP probe at the filter's request port carrying the stated AxPROT[1];
  // one carrying the other value samples no cell.
  wire sep_flt_aw_ns_ok = (sep_flt_awprot_i[1] === SepOutNs);
  wire sep_flt_ar_ns_ok = (sep_flt_arprot_i[1] === SepOutNs);

  // A SEP probe at the filter's request port: the first address phase the
  // filter receives on that channel after the probe's system-bus accept,
  // while the probe is open.
  wire sep_terms_aw_e = sep_flt_aw_acc && sep_aw_q.valid && sep_aw_q.flt_pending;
  wire sep_terms_ar_e = sep_flt_ar_acc && sep_ar_q.valid && sep_ar_q.flt_pending;

  always_ff @(posedge clk_smu_i) begin
    if (in_reset || gate_rose) begin
      sys_aw_q <= '0;
      sys_ar_q <= '0;
      smc_aw_q <= '0;
      smc_ar_q <= '0;
      sep_aw_q <= '0;
      sep_ar_q <= '0;
    end else begin
      if (sys_aw_acc) begin
        sys_aw_q <= probe_open(
            eut_usable(
                InstSysIn
            ),
            sys_in_terms(
                eut_cfg_q[InstSysIn],
                sys_in_start_q[eut_idx_q[InstSysIn][3:0]],
                sys_in_end_q[eut_idx_q[InstSysIn][3:0]],
                s_axi_awaddr_i,
                s_axi_awprot_i,
                s_axi_awuser_i[3:0],
                s_axi_awlen_i
            ),
            1'b0,
            1'b0,
            1'b0,
            1'b0,
            1'b0
        );
      end else if (sys_b_acc) begin
        sys_aw_q <= '0;
      end
      if (sys_ar_acc) begin
        sys_ar_q <= probe_open(
            eut_usable(
                InstSysIn
            ),
            sys_in_terms(
                eut_cfg_q[InstSysIn],
                sys_in_start_q[eut_idx_q[InstSysIn][3:0]],
                sys_in_end_q[eut_idx_q[InstSysIn][3:0]],
                s_axi_araddr_i,
                s_axi_arprot_i,
                s_axi_aruser_i[3:0],
                s_axi_arlen_i
            ),
            1'b0,
            1'b0,
            1'b0,
            1'b0,
            1'b0
        );
      end else if (sys_r_last_acc) begin
        sys_ar_q <= '0;
      end
      if (smc_probe_aw) begin
        smc_aw_q <= probe_open(
            eut_usable(
                InstSmcOut
            ),
            5'h1f,
            1'b0,
            smc_meas(
                smc_dbg_awprot_i, smc_dbg_awlen_i, CfgWriteAllowed
            ),
            smc_meas_blocked(
                smc_dbg_awprot_i, smc_dbg_awlen_i
            ),
            eut_cfg_q[InstSmcOut][CfgAllowBurst],
            smc_meas_src(
                smc_dbg_awprot_i, smc_dbg_awlen_i)
        );
      end else if (smc_b_acc) begin
        smc_aw_q <= '0;
      end else if (out_addr_phase) begin
        smc_aw_q.out_seen <= 1'b1;
      end
      if (smc_probe_ar) begin
        smc_ar_q <= probe_open(
            eut_usable(
                InstSmcOut
            ),
            5'h1f,
            1'b0,
            smc_meas(
                smc_dbg_arprot_i, smc_dbg_arlen_i, CfgReadAllowed
            ),
            smc_meas_blocked(
                smc_dbg_arprot_i, smc_dbg_arlen_i
            ),
            eut_cfg_q[InstSmcOut][CfgAllowBurst],
            smc_meas_src(
                smc_dbg_arprot_i, smc_dbg_arlen_i)
        );
      end else if (smc_r_last_acc) begin
        smc_ar_q <= '0;
      end else if (out_addr_phase) begin
        smc_ar_q.out_seen <= 1'b1;
      end
      if (sep_probe_aw) begin
        sep_aw_q <= probe_open(eut_usable(InstSepOut), 5'h1f, 1'b1, 1'b0, 1'b1, 1'b0, SrcWildcard);
      end else if (sep_b_acc) begin
        sep_aw_q <= '0;
      end else begin
        if (out_addr_phase) sep_aw_q.out_seen <= 1'b1;
        if (sep_terms_aw_e) begin
          sep_aw_q.flt_pending <= 1'b0;
          sep_aw_q.usable <= sep_aw_q.usable && sep_flt_aw_ns_ok;
          sep_aw_q.meas <= sep_aw_q.usable && sep_flt_aw_ns_ok && sep_meas(sep_flt_awlen_i);
          sep_aw_q.meas_ab <= eut_cfg_q[InstSepOut][CfgAllowBurst];
        end
      end
      if (sep_probe_ar) begin
        sep_ar_q <= probe_open(eut_usable(InstSepOut), 5'h1f, 1'b1, 1'b0, 1'b1, 1'b0, SrcWildcard);
      end else if (sep_r_last_acc) begin
        sep_ar_q <= '0;
      end else begin
        if (out_addr_phase) sep_ar_q.out_seen <= 1'b1;
        if (sep_terms_ar_e) begin
          sep_ar_q.flt_pending <= 1'b0;
          sep_ar_q.usable <= sep_ar_q.usable && sep_flt_ar_ns_ok;
          sep_ar_q.meas <= sep_ar_q.usable && sep_flt_ar_ns_ok && sep_meas(sep_flt_arlen_i);
          sep_ar_q.meas_ab <= eut_cfg_q[InstSepOut][CfgAllowBurst];
        end
      end
    end
  end

  // Verdict events: a probe's response while its record is open; on the
  // outbound instances admitted needs an address phase on u_axi_out_if since
  // the accept and blocked needs its absence.
  wire sys_aw_okay_e = sys_b_acc && sys_aw_q.valid && sys_aw_q.usable && (s_axi_bresp_i === RespOkay);
  wire sys_aw_blocked_e = sys_b_acc && sys_aw_q.valid && sys_aw_q.usable
      && (s_axi_bresp_i === RespDecerr);
  wire sys_ar_okay_e = sys_r_last_acc && sys_ar_q.valid && sys_ar_q.usable
      && (s_axi_rresp_i === RespOkay);
  wire sys_ar_blocked_e = sys_r_last_acc && sys_ar_q.valid && sys_ar_q.usable
      && (s_axi_rresp_i === RespDecerr);
  wire smc_aw_okay_e = smc_b_acc && smc_aw_q.valid && smc_aw_q.usable && smc_aw_q.out_seen
      && (smc_dbg_bresp_i === RespOkay);
  wire smc_aw_blocked_e = smc_b_acc && smc_aw_q.valid && smc_aw_q.usable && !smc_aw_q.out_seen
      && (smc_dbg_bresp_i === RespDecerr);
  wire smc_ar_okay_e = smc_r_last_acc && smc_ar_q.valid && smc_ar_q.usable && smc_ar_q.out_seen
      && (smc_dbg_rresp_i === RespOkay);
  wire smc_ar_blocked_e = smc_r_last_acc && smc_ar_q.valid && smc_ar_q.usable && !smc_ar_q.out_seen
      && (smc_dbg_rresp_i === RespDecerr);
  wire sep_aw_okay_e = sep_b_acc && sep_aw_q.valid && sep_aw_q.usable && sep_aw_q.out_seen
      && (sep_sb_bresp_i === RespOkay);
  wire sep_aw_blocked_e = sep_b_acc && sep_aw_q.valid && sep_aw_q.usable && !sep_aw_q.out_seen
      && (sep_sb_bresp_i === RespDecerr);
  wire sep_ar_okay_e = sep_r_last_acc && sep_ar_q.valid && sep_ar_q.usable && sep_ar_q.out_seen
      && (sep_sb_rresp_i === RespOkay);
  wire sep_ar_blocked_e = sep_r_last_acc && sep_ar_q.valid && sep_ar_q.usable && !sep_ar_q.out_seen
      && (sep_sb_rresp_i === RespDecerr);

  // ------------------------------------------------------------------
  // Deny per term on the SMC inbound instance: a blocked probe whose access
  // fails exactly one match term of the entry under test, inside the graded
  // window. The terms are {entry_enabled, range, allow_ns, src_id,
  // allow_burst}.
  // ------------------------------------------------------------------
  wire [4:0] sys_aw_fails = ~sys_aw_q.terms;
  wire [4:0] sys_ar_fails = ~sys_ar_q.terms;
  wire sys_aw_one_fail = sys_aw_blocked_e && gate_on && (popcount32(32'(sys_aw_fails)) == 6'd1);
  wire sys_ar_one_fail = sys_ar_blocked_e && gate_on && (popcount32(32'(sys_ar_fails)) == 6'd1);
  wire deny_entry_enabled_e = (sys_aw_one_fail && sys_aw_fails[4]) || (sys_ar_one_fail && sys_ar_fails[4]);
  wire deny_range_e = (sys_aw_one_fail && sys_aw_fails[3]) || (sys_ar_one_fail && sys_ar_fails[3]);
  wire deny_allow_ns_e = (sys_aw_one_fail && sys_aw_fails[2]) || (sys_ar_one_fail && sys_ar_fails[2]);
  wire deny_src_id_e = (sys_aw_one_fail && sys_aw_fails[1]) || (sys_ar_one_fail && sys_ar_fails[1]);
  wire deny_allow_burst_e = (sys_aw_one_fail && sys_aw_fails[0]) || (sys_ar_one_fail && sys_ar_fails[0]);
  `OCAH_FCOV_COVER(c_filter_deny_entry_enabled, deny_entry_enabled_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_filter_deny_range, deny_range_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_filter_deny_allow_ns, deny_allow_ns_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_filter_deny_src_id, deny_src_id_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_filter_deny_allow_burst, deny_allow_burst_e, clk_smu_i, in_reset)

  // ------------------------------------------------------------------
  // smu_filter_match_cg (SMU_FCOV.adoc, smu_filter_match_cg): the match
  // terms of each access and the verdict of each probe, per instance.
  // ------------------------------------------------------------------
  // cp_terms is {inst, ns, src, ab, multi}: on SYS_IN ns is the entry's
  // allow_ns value; on the outbound instances it is the relation to the
  // access's AxPROT[1] (0 admitting, 1 refusing), on the SEP instance the
  // stated value 1 at the filter's request port. Every bin of an SMC inbound
  // cell lists inst 0; the differing class with a multi-beat access has no
  // bin (the owner's src_id break is a single-beat probe) and is ignored.
  // smc_out_ns_refusing, sep_out_ns_refusing, smc_out_src_smc_id_blocked and
  // smc_out_src_other_admitted are sampled at the probe's response, at the
  // stated verdict only; the other bins at the address phase, the outbound
  // stimulus bins against a src_id 0 entry.
  // cp_verdict_priority is {kind, a, blocked, inst}: kind 0 pairs the channel
  // (a: 0 AR, 1 AW) with the verdict; kind 1 is the overlap cell with a the
  // programming order (0 lower first, 1 higher first), on any instance,
  // sampled at a blocked verdict while the two most recently enabled entries
  // are enabled, the lower-numbered one with the channel's permission clear
  // and the higher-numbered one with it set.
  covergroup smu_filter_match_cg with function sample (
      logic [1:0] inst,
      logic ns,
      logic [1:0] src,
      logic ab,
      logic multi,
      logic kind,
      logic [1:0] a,
      logic blocked,
      logic [1:0] vinst
  );
    option.per_instance = 1;
    cp_terms: coverpoint {
      inst, ns, src, ab, multi
    } {
      bins sys_in_ns0_wild_ab0_single = {7'b00_0_00_0_0};
      bins sys_in_ns0_wild_ab0_multi = {7'b00_0_00_0_1};
      bins sys_in_ns0_wild_ab1_single = {7'b00_0_00_1_0};
      bins sys_in_ns0_wild_ab1_multi = {7'b00_0_00_1_1};
      bins sys_in_ns0_equal_ab0_single = {7'b00_0_01_0_0};
      bins sys_in_ns0_equal_ab0_multi = {7'b00_0_01_0_1};
      bins sys_in_ns0_equal_ab1_single = {7'b00_0_01_1_0};
      bins sys_in_ns0_equal_ab1_multi = {7'b00_0_01_1_1};
      bins sys_in_ns0_differing_ab0_single = {7'b00_0_10_0_0};
      bins sys_in_ns0_differing_ab1_single = {7'b00_0_10_1_0};
      bins sys_in_ns1_wild_ab0_single = {7'b00_1_00_0_0};
      bins sys_in_ns1_wild_ab0_multi = {7'b00_1_00_0_1};
      bins sys_in_ns1_wild_ab1_single = {7'b00_1_00_1_0};
      bins sys_in_ns1_wild_ab1_multi = {7'b00_1_00_1_1};
      bins sys_in_ns1_equal_ab0_single = {7'b00_1_01_0_0};
      bins sys_in_ns1_equal_ab0_multi = {7'b00_1_01_0_1};
      bins sys_in_ns1_equal_ab1_single = {7'b00_1_01_1_0};
      bins sys_in_ns1_equal_ab1_multi = {7'b00_1_01_1_1};
      bins sys_in_ns1_differing_ab0_single = {7'b00_1_10_0_0};
      bins sys_in_ns1_differing_ab1_single = {7'b00_1_10_1_0};
      bins smc_out_ab0_single = {7'b01_0_00_0_0};
      bins smc_out_ab0_multi = {7'b01_0_00_0_1};
      bins smc_out_ab1_single = {7'b01_0_00_1_0};
      bins smc_out_ab1_multi = {7'b01_0_00_1_1};
      bins sep_out_ab0_single = {7'b10_0_00_0_0};
      bins sep_out_ab1_single = {7'b10_0_00_1_0};
      bins smc_out_ns_refusing = {7'b01_1_00_0_0, 7'b01_1_00_1_0};
      bins sep_out_ns_refusing = {7'b10_1_00_0_0, 7'b10_1_00_1_0};
      bins smc_out_src_smc_id_blocked = {7'b01_0_01_0_0, 7'b01_0_01_1_0};
      bins smc_out_src_other_admitted = {7'b01_0_10_0_0, 7'b01_0_10_1_0};
      bins sep_out_src_nonzero = {7'b10_0_11_0_0, 7'b10_0_11_1_0};
      ignore_bins sys_in_differing_multi = {
        7'b00_0_10_0_1, 7'b00_0_10_1_1, 7'b00_1_10_0_1, 7'b00_1_10_1_1
      };
    }
    cp_verdict_priority: coverpoint {
      kind, a, blocked, vinst
    } {
      bins sys_in_ar_admitted = {6'b0_00_0_00};
      bins sys_in_ar_blocked = {6'b0_00_1_00};
      bins sys_in_aw_admitted = {6'b0_01_0_00};
      bins sys_in_aw_blocked = {6'b0_01_1_00};
      bins smc_out_ar_admitted = {6'b0_00_0_01};
      bins smc_out_ar_blocked = {6'b0_00_1_01};
      bins smc_out_aw_admitted = {6'b0_01_0_01};
      bins smc_out_aw_blocked = {6'b0_01_1_01};
      bins sep_out_ar_admitted = {6'b0_00_0_10};
      bins sep_out_ar_blocked = {6'b0_00_1_10};
      bins sep_out_aw_admitted = {6'b0_01_0_10};
      bins sep_out_aw_blocked = {6'b0_01_1_10};
      bins overlap_lower_first = {6'b1_00_1_00, 6'b1_00_1_01, 6'b1_00_1_10};
      bins overlap_higher_first = {6'b1_01_1_00, 6'b1_01_1_01, 6'b1_01_1_10};
    }
  endgroup

  smu_filter_match_cg u_cg_filter_match = new();

  // Each sample fills one coverpoint and hands the other a value no bin
  // lists (inst 3 for cp_terms, vinst 3 for cp_verdict_priority).
  localparam logic [1:0] NoInst = 2'd3;

  task automatic sample_terms(input logic [1:0] inst, input logic ns, input logic [1:0] src,
                              input logic ab, input logic multi);
    u_cg_filter_match.sample(inst, ns, src, ab, multi, 1'b0, 2'd0, 1'b0, NoInst);
  endtask

  task automatic sample_verdict(input logic [1:0] ch, input logic blocked, input logic [1:0] inst);
    u_cg_filter_match.sample(NoInst, 1'b0, 2'd0, 1'b0, 1'b0, 1'b0, ch, blocked, inst);
    if (blocked && pair_programmed(inst) && pair_perm_split(inst, ch)) begin
      u_cg_filter_match.sample(NoInst, 1'b0, 2'd0, 1'b0, 1'b0, 1'b1, {1'b0, pair_order(inst)}, 1'b1,
                               inst);
    end
  endtask

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset && gate_on) begin
      // SMC inbound: the inbound address phases, with the entry's field values.
      if (sys_aw_acc && eut_usable(InstSysIn)) begin
        sample_terms(InstSysIn, eut_cfg_q[InstSysIn][CfgAllowNs], sys_in_src_class(
                     eut_cfg_q[InstSysIn], s_axi_awuser_i[3:0]),
                     eut_cfg_q[InstSysIn][CfgAllowBurst], s_axi_awlen_i != 8'd0);
      end
      if (sys_ar_acc && eut_usable(InstSysIn)) begin
        sample_terms(InstSysIn, eut_cfg_q[InstSysIn][CfgAllowNs], sys_in_src_class(
                     eut_cfg_q[InstSysIn], s_axi_aruser_i[3:0]),
                     eut_cfg_q[InstSysIn][CfgAllowBurst], s_axi_arlen_i != 8'd0);
      end
      // SMC outbound: the bridge probes and the iDMA launch against a src_id 0
      // entry (a non-zero src_id entry pairs with a walked cell only).
      if (smc_probe_aw && eut_usable(
              InstSmcOut
          ) && (smc_src_class(
              eut_cfg_q[InstSmcOut]
          ) == SrcWildcard) && !smc_walked_ns(
              smc_dbg_awprot_i, smc_dbg_awlen_i
          )) begin
        sample_terms(InstSmcOut, eut_cfg_q[InstSmcOut][CfgAllowNs] != smc_dbg_awprot_i[1],
                     SrcWildcard, eut_cfg_q[InstSmcOut][CfgAllowBurst], smc_dbg_awlen_i != 8'd0);
      end
      if (smc_probe_ar && eut_usable(
              InstSmcOut
          ) && (smc_src_class(
              eut_cfg_q[InstSmcOut]
          ) == SrcWildcard) && !smc_walked_ns(
              smc_dbg_arprot_i, smc_dbg_arlen_i
          )) begin
        sample_terms(InstSmcOut, eut_cfg_q[InstSmcOut][CfgAllowNs] != smc_dbg_arprot_i[1],
                     SrcWildcard, eut_cfg_q[InstSmcOut][CfgAllowBurst], smc_dbg_arlen_i != 8'd0);
      end
      if (smc_launch_ar && eut_usable(InstSmcOut) && idma_prot1_known_q) begin
        sample_terms(InstSmcOut, eut_cfg_q[InstSmcOut][CfgAllowNs] != idma_prot1_q, smc_src_class(
                     eut_cfg_q[InstSmcOut]), eut_cfg_q[InstSmcOut][CfgAllowBurst], 1'b1);
      end
      // SEP outbound: the system-bus probes, at the filter's request port,
      // carrying the stated AxPROT[1].
      if (sep_terms_aw_e && sep_aw_q.usable && sep_flt_aw_ns_ok && !sep_walked(
              sep_flt_awlen_i
          )) begin
        sample_terms(InstSepOut, eut_cfg_q[InstSepOut][CfgAllowNs] != SepOutNs, sep_src_class(
                     eut_cfg_q[InstSepOut]), eut_cfg_q[InstSepOut][CfgAllowBurst],
                     sep_flt_awlen_i != 8'd0);
      end
      if (sep_terms_ar_e && sep_ar_q.usable && sep_flt_ar_ns_ok && !sep_walked(
              sep_flt_arlen_i
          )) begin
        sample_terms(InstSepOut, eut_cfg_q[InstSepOut][CfgAllowNs] != SepOutNs, sep_src_class(
                     eut_cfg_q[InstSepOut]), eut_cfg_q[InstSepOut][CfgAllowBurst],
                     sep_flt_arlen_i != 8'd0);
      end
      // Verdicts at the probe's response; the four walked cells at their stated verdict.
      if (sys_aw_okay_e || sys_aw_blocked_e) sample_verdict(ChAw, sys_aw_blocked_e, InstSysIn);
      if (sys_ar_okay_e || sys_ar_blocked_e) sample_verdict(ChAr, sys_ar_blocked_e, InstSysIn);
      if (smc_aw_okay_e || smc_aw_blocked_e) begin
        sample_verdict(ChAw, smc_aw_blocked_e, InstSmcOut);
        if (smc_aw_q.meas && (smc_aw_blocked_e == smc_aw_q.meas_blocked)) begin
          sample_terms(InstSmcOut, smc_aw_q.meas_src == SrcWildcard, smc_aw_q.meas_src,
                       smc_aw_q.meas_ab, 1'b0);
        end
      end
      if (smc_ar_okay_e || smc_ar_blocked_e) begin
        sample_verdict(ChAr, smc_ar_blocked_e, InstSmcOut);
        if (smc_ar_q.meas && (smc_ar_blocked_e == smc_ar_q.meas_blocked)) begin
          sample_terms(InstSmcOut, smc_ar_q.meas_src == SrcWildcard, smc_ar_q.meas_src,
                       smc_ar_q.meas_ab, 1'b0);
        end
      end
      if (sep_aw_okay_e || sep_aw_blocked_e) begin
        sample_verdict(ChAw, sep_aw_blocked_e, InstSepOut);
        if (sep_aw_q.meas && (sep_aw_blocked_e == sep_aw_q.meas_blocked)) begin
          sample_terms(InstSepOut, 1'b1, SrcWildcard, sep_aw_q.meas_ab, 1'b0);
        end
      end
      if (sep_ar_okay_e || sep_ar_blocked_e) begin
        sample_verdict(ChAr, sep_ar_blocked_e, InstSepOut);
        if (sep_ar_q.meas && (sep_ar_blocked_e == sep_ar_q.meas_blocked)) begin
          sample_terms(InstSepOut, 1'b1, SrcWildcard, sep_ar_q.meas_ab, 1'b0);
        end
      end
    end
  end

endmodule : smu_filter_fcov
