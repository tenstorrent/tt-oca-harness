// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU address-remap functional coverage: smu_remap_cg of SMU_FCOV.adoc, the
// window edges of the SMC alias table and of the SEP AP and STEE output
// tables, and the cache and valid attributes the register descriptions
// define. A hit's AxCACHE cell counts only when the access leaves with the
// AxCACHE the region's cacheable field states (alias_remap.rdl: the field
// overrides every AxCACHE bit); a hit leaving with another value samples no
// cell.
//
// The region registers come from the writes on the bus the owner programs
// them over: the DTP-to-SMC debug AXI (the SMC fabric JTAG2AXI bridge) for
// the alias table, the SEP debug module's system bus for the AP and STEE
// tables. An access pairs with the region whose REGION_ATTRS the owner wrote
// last on that table and is classed at its issued address on the same bus
// (an alias access is a bridge access outside the SMC local window, an
// output access a system-bus access inside the AP or STEE region); it counts
// at its leaving address phase on u_axi_out_if, SMC-prefixed for the bridge
// and SEP-prefixed for the system bus, and only when the leaving address is
// the one the register description states: for an alias hit the issued page
// plus the region's offset modulo 2^44 and for a miss the issued address
// (alias_remap.rdl), for an output access inside a valid region the upper
// bits of the region's offset over the in-window bits of the issued address
// and inside an invalid region the issued address (output_remap.rdl). An
// access leaving at another address samples no cell. The two cells the owner
// walks and grades, an address inside two valid alias regions and an offset
// sum that carries out of bit 55, count only when the access leaves at the
// address alias_remap.rdl states for them: the issued page plus the offset
// of the lowest-numbered valid region that contains it, modulo 2^44. The
// overlap cell counts only when the region under test is that lowest region,
// so the leaving address differs from the other region's translation and
// shows both regions valid and the priority; with the other region the lower
// one the leaving address is the region under test's own and samples no
// cell. An access of either walked cell counts in its own cell only, not in
// the address-class or AxCACHE rows.
//
// One passive module. Every port is a signal of the bench top: u_axi_out_if
// and two hierarchical taps of tb_wrapper_top.sv, the DTP-to-SMC debug AXI
// (u_dut.u_smu.dtp_axi_smc_dbg_req/resp) and the SEP debug module's
// system-bus port (u_sep_cpu.dbg_axi_req_raw/dbg_axi_resp_raw, read where
// the EL2 debug module drives it). Samples are taken only while the owning
// leaf holds tb_fcov_gate high; the under-test state clears when the gate
// rises.
//
// The reset values of smc_base_config.rdl LOCAL_BASE and REGION_SIZE, which
// bound the alias accesses, and the REGION_ATTRS field positions of
// alias_remap.rdl and output_remap.rdl come from the generated register
// headers (smu_fcov_smc_csr_pkg and smu_fcov_sep_csr_pkg). The module
// assumes the reset SMC local window: a leaf that reprograms LOCAL_BASE
// moves the alias accesses without moving this bound.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_remap_fcov (
  input wire clk_smu_i,
  input wire rst_cold_ni,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i,

  // DTP-to-SMC debug AXI: the SMC fabric JTAG2AXI bridge's bus.
  input wire smc_dbg_awvalid_i,
  input wire smc_dbg_awready_i,
  input wire [55:0] smc_dbg_awaddr_i,
  input wire smc_dbg_wvalid_i,
  input wire smc_dbg_wready_i,
  input wire [63:0] smc_dbg_wdata_i,
  input wire smc_dbg_bvalid_i,
  input wire smc_dbg_bready_i,
  input wire [1:0] smc_dbg_bresp_i,
  input wire smc_dbg_arvalid_i,
  input wire smc_dbg_arready_i,
  input wire [55:0] smc_dbg_araddr_i,

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

  // Outbound boundary interface (u_axi_out_if): the leaving address of the
  // bridge's and the system bus's accesses, and the AxCACHE of the bridge's.
  input wire out_awvalid_i,
  input wire out_awready_i,
  input wire [15:0] out_awid_i,
  input wire [55:0] out_awaddr_i,
  input wire [3:0] out_awcache_i,
  input wire out_arvalid_i,
  input wire out_arready_i,
  input wire [15:0] out_arid_i,
  input wire [55:0] out_araddr_i,
  input wire [3:0] out_arcache_i
);

  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR;
  import smc_top_addrmap_pkg::
      SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_NUM;
  import smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE;
  import sep_top_addrmap_pkg::SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_REGION_ATTRS_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_REGION_ATTRS_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_NUM;
  import sep_top_addrmap_pkg::SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_STRIDE;
  import sep_top_addrmap_pkg::SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_NUM;
  import sep_top_addrmap_pkg::SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_STRIDE;
  import sep_top_addrmap_pkg::SEP_TOP_AP_REGION_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_AP_REGION_SIZE;
  import sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_BASE_ADDR;
  import sep_top_addrmap_pkg::SEP_TOP_STEE_REGION_SIZE;
  import smu_fcov_smc_csr_pkg::SMC_BASE_CONFIG_LOCAL_BASE_REG_DEFAULT;
  import smu_fcov_smc_csr_pkg::SMC_BASE_CONFIG_REGION_SIZE_REG_DEFAULT;
  import smu_fcov_smc_csr_pkg::REMAP_REGION_REGION_ATTRS_OFFSET_SHIFT;
  import smu_fcov_smc_csr_pkg::REMAP_REGION_REGION_ATTRS_CACHEABLE_SHIFT;
  import smu_fcov_smc_csr_pkg::REMAP_REGION_REGION_ATTRS_CACHEABLE_MASK;
  import smu_fcov_smc_csr_pkg::REMAP_REGION_REGION_ATTRS_VALID_SHIFT;
  import smu_fcov_sep_csr_pkg::OUTPUT_REMAP_REGION_REGION_ATTRS_OFFSET_SHIFT;
  import smu_fcov_sep_csr_pkg::OUTPUT_REMAP_REGION_REGION_ATTRS_VALID_SHIFT;

  // Alias table (alias_remap.rdl): the base of the regions, their stride and
  // the offsets of REGION_START, REGION_END and REGION_ATTRS inside a region,
  // from the generated address map.
  localparam logic [55:0] AliasBase =
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR(
      0
  ));
  localparam logic [55:0] AliasSpan = 56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_NUM
                                          * SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE);
  localparam int unsigned AliasRegions = int'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_NUM);
  localparam logic [55:0] AliasStride = 56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE);
  localparam int unsigned AliasIdxLsb = $clog2(AliasStride);
  localparam logic [55:0] AliasStartOff =
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR(
      0
  )) - AliasBase;
  localparam logic [55:0] AliasEndOff =
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR(
      0
  )) - AliasBase;
  localparam logic [55:0] AliasAttrsOff =
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR(
      0
  )) - AliasBase;
  // Output tables (output_remap.rdl): one REGION_ATTRS per region stride,
  // sixteen regions per table, each over a fixed window of the table's region.
  localparam logic [31:0] ApCsrBase =
      32'(SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_REGION_ATTRS_BASE_ADDR(
      0
  ));
  localparam logic [31:0] SteeCsrBase =
      32'(SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_REGION_ATTRS_BASE_ADDR(
      0
  ));
  localparam logic [31:0] ApCsrSpan = 32'(SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_NUM
                                          * SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_STRIDE);
  localparam logic [31:0] SteeCsrSpan =
      32'(SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_NUM
          * SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_STRIDE);
  localparam int unsigned ApIdxLsb = $clog2(SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_STRIDE);
  localparam int unsigned SteeIdxLsb = $clog2(
      SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_STRIDE
  );
  // Each table's window: its base and size from the generated address map,
  // its region count from its own table, and the in-window bits of an
  // output access, which the leaving address keeps under the upper bits of
  // the region's offset (output_remap.rdl, offset).
  localparam int unsigned ApRegions =
      int'(SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_NUM);
  localparam int unsigned SteeRegions =
      int'(SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_NUM);
  localparam logic [31:0] ApWindowBase = 32'(SEP_TOP_AP_REGION_BASE_ADDR);
  localparam logic [31:0] SteeWindowBase = 32'(SEP_TOP_STEE_REGION_BASE_ADDR);
  localparam logic [31:0] ApWindowSpan = 32'(SEP_TOP_AP_REGION_SIZE);
  localparam logic [31:0] SteeWindowSpan = 32'(SEP_TOP_STEE_REGION_SIZE);
  localparam logic [31:0] ApRegionSize = ApWindowSpan / ApRegions;
  localparam logic [31:0] SteeRegionSize = SteeWindowSpan / SteeRegions;
  localparam int unsigned ApRegionBits = $clog2(ApRegionSize);
  localparam int unsigned SteeRegionBits = $clog2(SteeRegionSize);
  // smc_base_config.rdl LOCAL_BASE and REGION_SIZE reset values: the SMC local
  // window, inside which a bridge access is a register access.
  localparam logic [55:0] SmcLocalBase = 56'(SMC_BASE_CONFIG_LOCAL_BASE_REG_DEFAULT);
  localparam logic [55:0] SmcLocalSize = 56'(SMC_BASE_CONFIG_REGION_SIZE_REG_DEFAULT);
  localparam logic [1:0] RespOkay = 2'b00;
  // Bits [9:8] of an outbound ID are the crossbar's slave-port index, the
  // prefix cg_smn_ids (smu_ext_fcov.sv) decodes: 0 for sep_out, 1 for smc_out.
  localparam logic [1:0] PrefixFromSep = 2'b00;
  localparam logic [1:0] PrefixFromSmc = 2'b01;
  // REGION_ATTRS field positions: alias_remap.rdl offset, cacheable and valid
  // (the offset's bit 0 is the alias granule; cacheable is the AxCACHE a hit
  // leaves with); output_remap.rdl offset and valid.
  localparam int unsigned AliasAttrOffsetLsb = REMAP_REGION_REGION_ATTRS_OFFSET_SHIFT;
  localparam int unsigned AliasAttrCacheLsb = REMAP_REGION_REGION_ATTRS_CACHEABLE_SHIFT;
  localparam int unsigned AliasCacheBits = $countones(REMAP_REGION_REGION_ATTRS_CACHEABLE_MASK);
  localparam int unsigned AliasAttrValid = REMAP_REGION_REGION_ATTRS_VALID_SHIFT;
  localparam int unsigned OutAttrOffsetLsb = OUTPUT_REMAP_REGION_REGION_ATTRS_OFFSET_SHIFT;
  localparam int unsigned OutAttrValid = OUTPUT_REMAP_REGION_REGION_ATTRS_VALID_SHIFT;
  localparam int unsigned PageBits = 56 - AliasAttrOffsetLsb;
  localparam logic [55:0] Granule = 56'(1) << AliasAttrOffsetLsb;
  localparam int unsigned OutControlRegion = 7;

  // Table codes of the tuples.
  localparam logic [1:0] TabAlias = 2'd0;
  localparam logic [1:0] TabAp = 2'd1;
  localparam logic [1:0] TabStee = 2'd2;
  localparam logic [1:0] TabAliasWalked = 2'd3;

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
  // the data at the W accept, committed on an OKAY B; one outstanding.
  // ------------------------------------------------------------------
  wire smc_aw_acc = (smc_dbg_awvalid_i === 1'b1) && (smc_dbg_awready_i === 1'b1);
  wire smc_w_acc = (smc_dbg_wvalid_i === 1'b1) && (smc_dbg_wready_i === 1'b1);
  wire smc_b_acc = (smc_dbg_bvalid_i === 1'b1) && (smc_dbg_bready_i === 1'b1);
  wire smc_ar_acc = (smc_dbg_arvalid_i === 1'b1) && (smc_dbg_arready_i === 1'b1);
  wire sep_aw_acc = (sep_sb_awvalid_i === 1'b1) && (sep_sb_awready_i === 1'b1);
  wire sep_w_acc = (sep_sb_wvalid_i === 1'b1) && (sep_sb_wready_i === 1'b1);
  wire sep_b_acc = (sep_sb_bvalid_i === 1'b1) && (sep_sb_bready_i === 1'b1);
  wire sep_ar_acc = (sep_sb_arvalid_i === 1'b1) && (sep_sb_arready_i === 1'b1);

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
  wire [55:0] alias_off = smc_wr_addr_q - AliasBase;
  wire alias_wr = smc_wr_commit && (smc_wr_addr_q >= AliasBase) && (alias_off < AliasSpan);
  wire [2:0] alias_wr_idx = 3'(alias_off >> AliasIdxLsb);
  wire [55:0] alias_wr_reg = alias_off & (AliasStride - 56'd1);
  wire [31:0] ap_off = sep_wr_addr_q - ApCsrBase;
  wire [31:0] stee_off = sep_wr_addr_q - SteeCsrBase;
  wire ap_wr = sep_wr_commit && (sep_wr_addr_q >= ApCsrBase) && (ap_off < ApCsrSpan);
  wire stee_wr = sep_wr_commit && (sep_wr_addr_q >= SteeCsrBase) && (stee_off < SteeCsrSpan);
  wire [3:0] ap_wr_idx = 4'(ap_off >> ApIdxLsb);
  wire [3:0] stee_wr_idx = 4'(stee_off >> SteeIdxLsb);

  // ------------------------------------------------------------------
  // Table state: every region's registers and, per table, the region under
  // test (the last REGION_ATTRS written).
  // ------------------------------------------------------------------
  logic [55:0] alias_start_q[AliasRegions];
  logic [55:0] alias_end_q[AliasRegions];
  logic [63:0] alias_attrs_q[AliasRegions];
  logic [63:0] ap_attrs_q[ApRegions];
  logic [63:0] stee_attrs_q[SteeRegions];
  logic [2:0] alias_ut_q;
  logic [3:0] ap_ut_q, stee_ut_q;
  logic alias_ut_valid_q, ap_ut_valid_q, stee_ut_valid_q;

  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      for (int unsigned r = 0; r < AliasRegions; r++) begin
        alias_start_q[r] <= '0;
        alias_end_q[r] <= '0;
        alias_attrs_q[r] <= '0;
      end
      for (int unsigned k = 0; k < ApRegions; k++) ap_attrs_q[k] <= '0;
      for (int unsigned k = 0; k < SteeRegions; k++) stee_attrs_q[k] <= '0;
      alias_ut_q <= '0;
      ap_ut_q <= '0;
      stee_ut_q <= '0;
      alias_ut_valid_q <= 1'b0;
      ap_ut_valid_q <= 1'b0;
      stee_ut_valid_q <= 1'b0;
    end else begin
      if (gate_rose) begin
        alias_ut_valid_q <= 1'b0;
        ap_ut_valid_q <= 1'b0;
        stee_ut_valid_q <= 1'b0;
      end
      if (alias_wr && (alias_wr_reg == AliasStartOff)) begin
        alias_start_q[alias_wr_idx] <= smc_wr_data_q[55:0];
      end
      if (alias_wr && (alias_wr_reg == AliasEndOff)) begin
        alias_end_q[alias_wr_idx] <= smc_wr_data_q[55:0];
      end
      if (alias_wr && (alias_wr_reg == AliasAttrsOff)) begin
        alias_attrs_q[alias_wr_idx] <= smc_wr_data_q;
        alias_ut_q <= alias_wr_idx;
        alias_ut_valid_q <= 1'b1;
      end
      if (ap_wr) begin
        ap_attrs_q[ap_wr_idx] <= sep_wr_data_q;
        ap_ut_q <= ap_wr_idx;
        ap_ut_valid_q <= 1'b1;
      end
      if (stee_wr) begin
        stee_attrs_q[stee_wr_idx] <= sep_wr_data_q;
        stee_ut_q <= stee_wr_idx;
        stee_ut_valid_q <= 1'b1;
      end
    end
  end

  // ------------------------------------------------------------------
  // Alias accesses: a bridge address phase outside the SMC local window,
  // classified against the region under test. The access is outstanding
  // until its leaving address phase on u_axi_out_if (one per channel).
  // ------------------------------------------------------------------
  wire smc_outside_aw = smc_aw_acc && ((smc_dbg_awaddr_i < SmcLocalBase)
                                       || (smc_dbg_awaddr_i >= SmcLocalBase + SmcLocalSize));
  wire smc_outside_ar = smc_ar_acc && ((smc_dbg_araddr_i < SmcLocalBase)
                                       || (smc_dbg_araddr_i >= SmcLocalBase + SmcLocalSize));

  // Address classes against a region: 0 one granule below start_addr, 1 at
  // start_addr, 2 one granule below end_addr, 3 at end_addr, 7 none.
  function automatic logic [2:0] alias_class(input logic [55:0] addr, input logic [55:0] start,
                                             input logic [55:0] stop);
    if ((addr >= start - Granule) && (addr < start)) return 3'd0;
    if ((addr >= start) && (addr < start + Granule)) return 3'd1;
    if ((addr >= stop - Granule) && (addr < stop)) return 3'd2;
    if ((addr >= stop) && (addr < stop + Granule)) return 3'd3;
    return 3'd7;
  endfunction

  function automatic logic [1:0] alias_position(input logic [2:0] idx);
    if (idx == 3'd0) return 2'd0;
    if (idx == 3'(AliasRegions - 1)) return 2'd2;
    return 2'd1;
  endfunction

  function automatic logic alias_in_region(input logic [55:0] addr, input int unsigned r);
    return alias_attrs_q[r][AliasAttrValid] && (addr >= alias_start_q[r])
        && (addr < alias_end_q[r]);
  endfunction

  function automatic logic [3:0] alias_valid_hits(input logic [55:0] addr);
    logic [3:0] n;
    n = '0;
    for (int unsigned r = 0; r < AliasRegions; r++) n = n + 4'(alias_in_region(addr, r));
    return n;
  endfunction

  // The leaving page of a hit: the offset added to the page bits, modulo the
  // page-bit width.
  function automatic logic [55:0] alias_leaving(input logic [55:0] addr, input logic [63:0] attrs);
    logic [PageBits-1:0] page;
    page = addr[55:AliasAttrOffsetLsb] + attrs[55:AliasAttrOffsetLsb];
    return {page, addr[AliasAttrOffsetLsb-1:0]};
  endfunction

  // The REGION_ATTRS of the lowest-numbered valid region that contains the
  // address, the region alias_remap.rdl applies when several contain it.
  function automatic logic [63:0] alias_lowest_attrs(input logic [55:0] addr);
    for (int unsigned r = 0; r < AliasRegions; r++) begin
      if (alias_in_region(addr, r)) return alias_attrs_q[r];
    end
    return '0;
  endfunction

  function automatic logic alias_carries(input logic [55:0] addr, input logic [63:0] attrs);
    logic [PageBits:0] sum;
    sum = {1'b0, addr[55:AliasAttrOffsetLsb]} + {1'b0, attrs[55:AliasAttrOffsetLsb]};
    return sum[PageBits];
  endfunction

  // cls and pos class the issued address against the region under test;
  // cache is the region's cacheable field, the AxCACHE a hit leaves with;
  // overlap and carry mark the two walked cells; stated is the leaving
  // address alias_remap.rdl gives them (the lowest valid region's offset,
  // modulo 2^44).
  typedef struct packed {
    logic valid;
    logic hit;
    logic overlap;
    logic carry;
    logic [2:0] cls;
    logic [1:0] pos;
    logic [AliasCacheBits-1:0] cache;
    logic [55:0] issued;
    logic [55:0] leaving;
    logic [55:0] stated;
  } alias_access_t;

  alias_access_t alias_aw_q, alias_ar_q;

  function automatic alias_access_t alias_open(input logic [55:0] addr);
    alias_access_t a;
    a.valid = alias_ut_valid_q;
    a.hit = alias_in_region(addr, alias_ut_q);
    a.overlap = alias_valid_hits(addr) >= 4'd2;
    a.carry = a.hit && alias_carries(addr, alias_attrs_q[alias_ut_q]);
    a.cls = alias_class(addr, alias_start_q[alias_ut_q], alias_end_q[alias_ut_q]);
    a.pos = alias_position(alias_ut_q);
    a.cache = alias_attrs_q[alias_ut_q][AliasAttrCacheLsb+:AliasCacheBits];
    a.issued = addr;
    a.leaving = alias_leaving(addr, alias_attrs_q[alias_ut_q]);
    a.stated = alias_leaving(addr, alias_lowest_attrs(addr));
    return a;
  endfunction

  wire out_aw_acc = (out_awvalid_i === 1'b1) && (out_awready_i === 1'b1);
  wire out_ar_acc = (out_arvalid_i === 1'b1) && (out_arready_i === 1'b1);
  wire out_smc_aw = out_aw_acc && (out_awid_i[9:8] == PrefixFromSmc);
  wire out_smc_ar = out_ar_acc && (out_arid_i[9:8] == PrefixFromSmc);

  always_ff @(posedge clk_smu_i) begin
    if (in_reset || gate_rose) begin
      alias_aw_q <= '0;
      alias_ar_q <= '0;
    end else begin
      if (smc_outside_aw) alias_aw_q <= alias_open(smc_dbg_awaddr_i);
      else if (out_smc_aw) alias_aw_q <= '0;
      if (smc_outside_ar) alias_ar_q <= alias_open(smc_dbg_araddr_i);
      else if (out_smc_ar) alias_ar_q <= '0;
    end
  end

  // A leaving access is a hit when it leaves at the issued page plus the
  // region's offset, a miss when it leaves at the issued address; a hit's
  // AxCACHE cell needs the region's cacheable value on the leaving access.
  wire alias_aw_leave_hit = out_smc_aw && alias_aw_q.valid && alias_aw_q.hit
      && (out_awaddr_i == alias_aw_q.leaving);
  wire alias_aw_leave_miss = out_smc_aw && alias_aw_q.valid && !alias_aw_q.hit
      && (out_awaddr_i == alias_aw_q.issued);
  wire alias_ar_leave_hit = out_smc_ar && alias_ar_q.valid && alias_ar_q.hit
      && (out_araddr_i == alias_ar_q.leaving);
  wire alias_ar_leave_miss = out_smc_ar && alias_ar_q.valid && !alias_ar_q.hit
      && (out_araddr_i == alias_ar_q.issued);
  wire alias_aw_cache_stated = alias_aw_leave_hit && (out_awcache_i == alias_aw_q.cache);
  wire alias_ar_cache_stated = alias_ar_leave_hit && (out_arcache_i == alias_ar_q.cache);
  // The two walked cells, at the leaving address the register description
  // states; the overlap cell only when the region under test is the lowest
  // valid region containing the address (its own translation is the stated
  // one). The address-class and AxCACHE rows take neither walked access.
  wire alias_aw_leave_stated = out_smc_aw && alias_aw_q.valid && (out_awaddr_i == alias_aw_q.stated);
  wire alias_ar_leave_stated = out_smc_ar && alias_ar_q.valid && (out_araddr_i == alias_ar_q.stated);
  wire alias_overlap_stated_e =
      (alias_aw_leave_stated && alias_aw_q.overlap && (alias_aw_q.stated == alias_aw_q.leaving))
      || (alias_ar_leave_stated && alias_ar_q.overlap && (alias_ar_q.stated == alias_ar_q.leaving));
  wire alias_carry_stated_e = (alias_aw_leave_stated && alias_aw_q.carry)
      || (alias_ar_leave_stated && alias_ar_q.carry);
  wire alias_aw_generic = !alias_aw_q.overlap && !alias_aw_q.carry;
  wire alias_ar_generic = !alias_ar_q.overlap && !alias_ar_q.carry;

  // AxCACHE classes of alias_remap.rdl cacheable: 0, 15, other.
  function automatic logic [1:0] cache_class(input logic [3:0] cache);
    if (cache == 4'h0) return 2'd0;
    if (cache == 4'hf) return 2'd1;
    return 2'd2;
  endfunction

  // ------------------------------------------------------------------
  // Output accesses: a system-bus address phase inside the AP or STEE
  // region, classified against that table's region under test. The index
  // class is 0 for region 1 and 1 for regions 2 to 14; regions 0 and 15 have
  // no class (never programmed; no region past it).
  // ------------------------------------------------------------------
  function automatic logic out_in_window(input logic [31:0] addr, input logic [31:0] base,
                                         input logic [31:0] span);
    return (addr >= base) && (addr < base + span);
  endfunction

  // 0 inside the window below its last word, 1 the last word, 2 the first
  // word past it while region k+1 is invalid, 7 none.
  function automatic logic [2:0] out_class(input logic [31:0] addr, input logic [31:0] base,
                                           input logic [31:0] size, input logic [3:0] k,
                                           input logic next_valid);
    logic [31:0] win, off;
    win = base + 32'(k) * size;
    off = addr - win;
    if (addr < win) return 3'd7;
    if (off < size - 32'd8) return 3'd0;
    if (off == size - 32'd8) return 3'd1;
    if ((off == size) && !next_valid) return 3'd2;
    return 3'd7;
  endfunction

  function automatic logic [1:0] out_index_class(input logic [3:0] k);
    if (k == 4'd1) return 2'd0;
    if ((k >= 4'd2) && (k <= 4'd14)) return 2'd1;
    return 2'd3;
  endfunction

  wire sep_ap_aw = sep_aw_acc && out_in_window(sep_sb_awaddr_i, ApWindowBase, ApWindowSpan);
  wire sep_ap_ar = sep_ar_acc && out_in_window(sep_sb_araddr_i, ApWindowBase, ApWindowSpan);
  wire sep_stee_aw = sep_aw_acc && out_in_window(sep_sb_awaddr_i, SteeWindowBase, SteeWindowSpan);
  wire sep_stee_ar = sep_ar_acc && out_in_window(sep_sb_araddr_i, SteeWindowBase, SteeWindowSpan);
  wire ap_next_valid = ap_attrs_q[ap_ut_q+4'd1][OutAttrValid];
  wire stee_next_valid = stee_attrs_q[stee_ut_q+4'd1][OutAttrValid];

  // The leaving address output_remap.rdl states for an output access: inside
  // a valid region the upper bits of the region's offset over the in-window
  // bits of the issued address, inside an invalid region the issued address.
  function automatic logic [55:0] out_stated(input logic [1:0] table_sel, input logic [31:0] addr);
    logic [3:0] k;
    logic [63:0] attrs;
    if (table_sel == TabAp) begin
      k = 4'((addr - ApWindowBase) >> ApRegionBits);
      attrs = ap_attrs_q[k];
      if (attrs[OutAttrValid]) begin
        return {attrs[OutAttrOffsetLsb+ApRegionBits+:56-ApRegionBits], addr[ApRegionBits-1:0]};
      end
      return 56'(addr);
    end
    k = 4'((addr - SteeWindowBase) >> SteeRegionBits);
    attrs = stee_attrs_q[k];
    if (attrs[OutAttrValid]) begin
      return {attrs[OutAttrOffsetLsb+SteeRegionBits+:56-SteeRegionBits], addr[SteeRegionBits-1:0]};
    end
    return 56'(addr);
  endfunction

  // An output access is outstanding from its system-bus accept to its
  // SEP-prefixed leaving address phase on u_axi_out_if (one per channel);
  // the record carries its table, classes and stated leaving address.
  typedef struct packed {
    logic valid;
    logic [1:0] table_sel;
    logic [2:0] cls;
    logic [1:0] pos;
    logic [55:0] stated;
  } out_access_t;

  out_access_t out_aw_q, out_ar_q;

  function automatic out_access_t out_open(input logic [1:0] table_sel, input logic [31:0] addr);
    out_access_t o;
    o.valid = (table_sel == TabAp) ? ap_ut_valid_q : stee_ut_valid_q;
    o.table_sel = table_sel;
    if (table_sel == TabAp) begin
      o.cls = out_class(addr, ApWindowBase, ApRegionSize, ap_ut_q, ap_next_valid);
      o.pos = out_index_class(ap_ut_q);
    end else begin
      o.cls = out_class(addr, SteeWindowBase, SteeRegionSize, stee_ut_q, stee_next_valid);
      o.pos = out_index_class(stee_ut_q);
    end
    o.stated = out_stated(table_sel, addr);
    return o;
  endfunction

  wire out_sep_aw = out_aw_acc && (out_awid_i[9:8] == PrefixFromSep);
  wire out_sep_ar = out_ar_acc && (out_arid_i[9:8] == PrefixFromSep);

  always_ff @(posedge clk_smu_i) begin
    if (in_reset || gate_rose) begin
      out_aw_q <= '0;
      out_ar_q <= '0;
    end else begin
      if (sep_ap_aw) out_aw_q <= out_open(TabAp, sep_sb_awaddr_i);
      else if (sep_stee_aw) out_aw_q <= out_open(TabStee, sep_sb_awaddr_i);
      else if (out_sep_aw) out_aw_q <= '0;
      if (sep_ap_ar) out_ar_q <= out_open(TabAp, sep_sb_araddr_i);
      else if (sep_stee_ar) out_ar_q <= out_open(TabStee, sep_sb_araddr_i);
      else if (out_sep_ar) out_ar_q <= '0;
    end
  end

  // A leaving output access at the stated address.
  wire out_aw_leave_stated = out_sep_aw && out_aw_q.valid && (out_awaddr_i == out_aw_q.stated);
  wire out_ar_leave_stated = out_sep_ar && out_ar_q.valid && (out_araddr_i == out_ar_q.stated);

  // ------------------------------------------------------------------
  // smu_remap_cg (SMU_FCOV.adoc, smu_remap_cg).
  // ------------------------------------------------------------------
  // cp_table_hit is {table, class, position}: the alias rows pair the address
  // class with the region position (first, middle, last of the eight), the
  // AP and STEE rows pair the address class with the index class, and the
  // alias-walked rows carry the two cells the owner walks and grades (two
  // valid regions over one page, an offset sum past bit 55); every row
  // counts at the leaving address phase on u_axi_out_if when the leaving
  // address is the one the register description states. A class of 7 or an
  // index class of 3 lists no bin.
  // cp_attr is {kind, x, y, z}: kind 0 pairs the AxCACHE class (x) of a
  // leaving access with hit (y), a hit sampled only when it leaves with the
  // region's cacheable value; a miss carries the AxCACHE its initiator
  // issued, the reference the owner measures and cross-checks against the
  // AxCACHE on the DTP-to-SMC debug AXI tap (class other), so a miss at
  // class 0 or 15 is ignored. Kind 1 pairs the table
  // (x) with valid set (y 1) or cleared after programming (y 0); z marks the
  // output control region 7, whose clear the owner logs and which has no bin.
  covergroup smu_remap_cg with function sample (
      logic [1:0] table_sel,
      logic [2:0] cls,
      logic [1:0] pos,
      logic kind,
      logic [1:0] x,
      logic y,
      logic z
  );
    option.per_instance = 1;
    cp_table_hit: coverpoint {
      table_sel, cls, pos
    } {
      bins alias_below_start_first = {7'b00_000_00};
      bins alias_below_start_middle = {7'b00_000_01};
      bins alias_below_start_last = {7'b00_000_10};
      bins alias_at_start_first = {7'b00_001_00};
      bins alias_at_start_middle = {7'b00_001_01};
      bins alias_at_start_last = {7'b00_001_10};
      bins alias_below_end_first = {7'b00_010_00};
      bins alias_below_end_middle = {7'b00_010_01};
      bins alias_below_end_last = {7'b00_010_10};
      bins alias_at_end_first = {7'b00_011_00};
      bins alias_at_end_middle = {7'b00_011_01};
      bins alias_at_end_last = {7'b00_011_10};
      bins ap_inside_index1 = {7'b01_000_00};
      bins ap_inside_index2_14 = {7'b01_000_01};
      bins ap_last_word_index1 = {7'b01_001_00};
      bins ap_last_word_index2_14 = {7'b01_001_01};
      bins ap_first_past_index1 = {7'b01_010_00};
      bins ap_first_past_index2_14 = {7'b01_010_01};
      bins stee_inside_index1 = {7'b10_000_00};
      bins stee_inside_index2_14 = {7'b10_000_01};
      bins stee_last_word_index1 = {7'b10_001_00};
      bins stee_last_word_index2_14 = {7'b10_001_01};
      bins stee_first_past_index1 = {7'b10_010_00};
      bins stee_first_past_index2_14 = {7'b10_010_01};
      bins two_valid_regions = {7'b11_000_00};
      bins offset_past_bit55 = {7'b11_001_00};
    }
    cp_attr: coverpoint {
      kind, x, y, z
    } {
      bins cache_0_hit = {5'b0_00_1_0};
      bins cache_15_hit = {5'b0_01_1_0};
      bins cache_other_hit = {5'b0_10_1_0};
      bins cache_other_miss = {5'b0_10_0_0};
      bins alias_valid_set = {5'b1_00_1_0};
      bins alias_valid_cleared = {5'b1_00_0_0};
      bins ap_valid_set = {5'b1_01_1_0};
      bins ap_valid_cleared = {5'b1_01_0_0};
      bins stee_valid_set = {5'b1_10_1_0};
      bins stee_valid_cleared = {5'b1_10_0_0};
      ignore_bins miss_cache_0_15 = {5'b0_00_0_0, 5'b0_01_0_0};
    }
  endgroup

  smu_remap_cg u_cg_remap = new();

  // Each sample fills one coverpoint and hands the other a value no bin
  // lists (class 7 for cp_table_hit, kind 1 with table 3 for cp_attr).
  task automatic sample_hit(input logic [1:0] table_sel, input logic [2:0] cls,
                            input logic [1:0] pos);
    u_cg_remap.sample(table_sel, cls, pos, 1'b1, 2'd3, 1'b0, 1'b0);
  endtask

  task automatic sample_attr(input logic kind, input logic [1:0] x, input logic y, input logic z);
    u_cg_remap.sample(2'd0, 3'd7, 2'd0, kind, x, y, z);
  endtask

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset && gate_on) begin
      // Alias accesses at the leaving address the register description
      // states, with their class and attributes.
      if ((alias_aw_leave_hit || alias_aw_leave_miss) && alias_aw_generic) begin
        sample_hit(TabAlias, alias_aw_q.cls, alias_aw_q.pos);
      end
      if ((alias_ar_leave_hit || alias_ar_leave_miss) && alias_ar_generic) begin
        sample_hit(TabAlias, alias_ar_q.cls, alias_ar_q.pos);
      end
      if (alias_overlap_stated_e) sample_hit(TabAliasWalked, 3'd0, 2'd0);
      if (alias_carry_stated_e) sample_hit(TabAliasWalked, 3'd1, 2'd0);
      if (alias_aw_cache_stated && alias_aw_generic) begin
        sample_attr(1'b0, cache_class(out_awcache_i), 1'b1, 1'b0);
      end
      if (alias_aw_leave_miss && alias_aw_generic) begin
        sample_attr(1'b0, cache_class(out_awcache_i), 1'b0, 1'b0);
      end
      if (alias_ar_cache_stated && alias_ar_generic) begin
        sample_attr(1'b0, cache_class(out_arcache_i), 1'b1, 1'b0);
      end
      if (alias_ar_leave_miss && alias_ar_generic) begin
        sample_attr(1'b0, cache_class(out_arcache_i), 1'b0, 1'b0);
      end
      // Output accesses at the leaving address the register description states.
      if (out_aw_leave_stated) sample_hit(out_aw_q.table_sel, out_aw_q.cls, out_aw_q.pos);
      if (out_ar_leave_stated) sample_hit(out_ar_q.table_sel, out_ar_q.cls, out_ar_q.pos);
      // Valid set, and cleared after a write that set it, at the register write.
      if (alias_wr && (alias_wr_reg == AliasAttrsOff)) begin
        if (smc_wr_data_q[AliasAttrValid]) sample_attr(1'b1, TabAlias, 1'b1, 1'b0);
        else if (alias_attrs_q[alias_wr_idx][AliasAttrValid]) begin
          sample_attr(1'b1, TabAlias, 1'b0, 1'b0);
        end
      end
      if (ap_wr) begin
        if (sep_wr_data_q[OutAttrValid]) sample_attr(1'b1, TabAp, 1'b1, 1'b0);
        else if (ap_attrs_q[ap_wr_idx][OutAttrValid]) begin
          sample_attr(1'b1, TabAp, 1'b0, ap_wr_idx == 4'(OutControlRegion));
        end
      end
      if (stee_wr) begin
        if (sep_wr_data_q[OutAttrValid]) sample_attr(1'b1, TabStee, 1'b1, 1'b0);
        else if (stee_attrs_q[stee_wr_idx][OutAttrValid]) begin
          sample_attr(1'b1, TabStee, 1'b0, stee_wr_idx == 4'(OutControlRegion));
        end
      end
    end
  end

endmodule : smu_remap_fcov
