// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC memory-map row-response functional coverage: the covergroup
// smc_map_row_response_cg of SMC_FCOV.adoc. Every SEP_IN and SYS_IN
// completion whose address lies past a unit's decoded extent, between two
// unit apertures or outside both inbound apertures is classed into one of
// the 44 kinds of the group (30 past-extent rows, 7 gaps, 7 outside-window
// classes) and counted with its direction, AxSIZE and port against the
// DECERR response the map states.
//
// The decode is a table of the generated component map: every row's base and
// decoded extent are the smc_top_addrmap_pkg symbols, the aperture end of a
// row is the next row's base less one or, where the decoded extent fills the
// aperture, base plus extent less one. Three rows are followed by a gap and
// their aperture size has no generated SV symbol: it is the RDL property
// ocah_aperture_size of hw/sys/smc/regs/include/smc_memory_map.rdl, kept as
// a localparam below. The window edge BASE + REGION_SIZE is the DUT's
// smc_region_size_o, cross-checked against the register's reset word.
//
// The group counts only inside the owner's graded window (tb_fcov_gate) and
// only while inbound filter entry 0 has been written over SEP_IN since the
// gate rose (the owner's pass-all for the SYS_IN legs), which keeps the
// outside-window DECERR accesses other owners issue under their own gates
// out, and while the sampler's shadow of CLOCK_GATE_CONTROL holds the five
// peripheral-window enables clear (a gated window answers SLVERR, which no
// cell counts). A completion whose code or read word is not the stated one
// samples no cell.
//
// One instance in the shared tb_top. Every port is a smc_tb_signal_list.svh
// signal or a smc_wrapper boundary port.
//
// CONVENTION (see dtp_fcov.sv): no declaration initializers on
// always_ff-driven variables; declare wires before use.

module smc_map_row_fcov (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // SEP_IN request, write data, write response and read channels.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire [55:0] sep_awaddr_i,
  input wire [2:0] sep_awsize_i,
  input wire sep_wvalid_i,
  input wire sep_wready_i,
  input wire sep_wlast_i,
  input wire [63:0] sep_wdata_i,
  input wire [7:0] sep_wstrb_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire [1:0] sep_bresp_i,
  input wire sep_arvalid_i,
  input wire sep_arready_i,
  input wire [55:0] sep_araddr_i,
  input wire [2:0] sep_arsize_i,
  input wire sep_rvalid_i,
  input wire sep_rready_i,
  input wire sep_rlast_i,
  input wire [1:0] sep_rresp_i,
  input wire [63:0] sep_rdata_i,

  // SYS_IN request, write response and read channels.
  input wire sys_awvalid_i,
  input wire sys_awready_i,
  input wire [55:0] sys_awaddr_i,
  input wire [2:0] sys_awsize_i,
  input wire sys_bvalid_i,
  input wire sys_bready_i,
  input wire [1:0] sys_bresp_i,
  input wire sys_arvalid_i,
  input wire sys_arready_i,
  input wire [55:0] sys_araddr_i,
  input wire [2:0] sys_arsize_i,
  input wire sys_rvalid_i,
  input wire sys_rready_i,
  input wire sys_rlast_i,
  input wire [1:0] sys_rresp_i,
  input wire [63:0] sys_rdata_i,

  // REGION_SIZE as the DUT applies it, and the I2C clock-gate enable it
  // drives from CLOCK_GATE_CONTROL.
  input wire [31:0] region_size_i,
  input wire i2c_cg_en_i,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i
);

  import smc_top_addrmap_pkg::*;
  import filter_ctrl_addrmap_pkg::FILTER_CTRL_FILTER_CONFIG_BASE_ADDR;
  import filter_ctrl_addrmap_pkg::FILTER_CTRL_START_ADDR_BASE_ADDR;
  import filter_ctrl_addrmap_pkg::FILTER_CTRL_END_ADDR_BASE_ADDR;
  // The SMC_BASE_CONFIG register addresses, reset words and the
  // CLOCK_GATE_CONTROL field masks. The header's include guard is cleared
  // before and after, so this module and the SV-UVM environment package,
  // which includes the same header, each get its contents whatever their
  // order in one compilation unit. The generated header sizes its 32-bit
  // reset words as 64-bit localparams, which Verilator reports per constant.
`ifdef SMC_TOP_REG_SVH
  `undef SMC_TOP_REG_SVH
`endif
  // verilator lint_off WIDTHEXPAND
  // verilator lint_off SYMRSVDWORD
  `include "smc_reg.svh"
  // verilator lint_on SYMRSVDWORD
  // verilator lint_on WIDTHEXPAND
  `undef SMC_TOP_REG_SVH

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // The inbound apertures. LOCAL_BASE is fixed and GLOBAL_BASE is left at
  // its reset word by every owner (memmap.adoc, Address Space Organization);
  // REGION_SIZE is read from the DUT and the table below holds at its reset
  // word only.
  // ------------------------------------------------------------------
  localparam logic [55:0] LocalBase = 56'(SMC_BASE_CONFIG_LOCAL_BASE_REG_DEFAULT);
  localparam logic [55:0] GlobalBase = 56'(SMC_BASE_CONFIG_GLOBAL_BASE_REG_DEFAULT);
  localparam logic [31:0] RegionSizeReset = 32'(SMC_BASE_CONFIG_REGION_SIZE_REG_DEFAULT);
  localparam logic [55:0] XvisorOff = 56'(SMC_TOP_XVISOR_REGION_BASE_ADDR) - LocalBase;
  localparam logic [55:0] XvisorEnd = XvisorOff + 56'(SMC_TOP_XVISOR_REGION_SIZE);
  // The first address above the last row of the generated map.
  localparam logic [55:0] MapTop = 56'(SMC_TOP_BASE_ADDR) + 56'(SMC_TOP_SIZE);
  localparam logic [55:0] FourGib = 56'h100_0000_0000;

  // The aperture sizes the generated SV collateral does not carry:
  // ocah_aperture_size of hw/sys/smc/regs/include/smc_memory_map.rdl for
  // the three rows a gap follows.
  localparam logic [55:0] DfxCtrlAperture = 56'h800;
  localparam logic [55:0] OutboundFilterAperture = 56'h1000;
  localparam logic [55:0] ZeroerCtrlAperture = 56'h100;

  // ------------------------------------------------------------------
  // The component map, in address order (memory_map.adoc, SMC Component
  // Address Map): base, decoded extent and aperture end of every row, and
  // the kind code of the rows whose Past Extent cell states a response.
  // ------------------------------------------------------------------
  localparam int unsigned NumRows = 41;
  localparam int unsigned NumKinds = 44;
  localparam logic [5:0] KindNone = 6'd44;

  localparam logic [55:0] RowBase[NumRows] = '{
      56'(SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR),
      56'(SMC_TOP_DEBUG_MODULE_BASE_ADDR),
      56'(SMC_TOP_SMC_RESET_UNIT_BASE_ADDR),
      56'(SMC_TOP_SMC_MISC_WRAP_BASE_ADDR),
      56'(SMC_TOP_GPIO_INTF_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR),
      56'(SMC_TOP_SMC_I2C_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_UART_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR),
      56'(SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR),
      56'(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR),
      56'(SMC_TOP_DTP_CTRL_REG_BASE_ADDR),
      56'(SMC_TOP_DFX_CTRL_BASE_ADDR),
      56'(SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR),
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_MMODE_REMAP_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_XVISOR_REMAP_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_BASE_ADDR),
      56'(SMC_TOP_SMC_MAILBOX_BASE_ADDR),
      56'(SMC_TOP_DMA_CTRL_BASE_ADDR),
      56'(SMC_TOP_ZEROER_CTRL_BASE_ADDR),
      56'(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR),
      56'(SMC_TOP_OCA_I3C_WRAP_BASE_ADDR),
      56'(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR),
      56'(SMC_TOP_SPM_MEMORY_BASE_ADDR),
      56'(SMC_TOP_SMC_CLA_BASE_ADDR),
      56'(SMC_TOP_SMC_EXTERNAL_BASE_ADDR),
      56'(SMC_TOP_MMODE_REGION_BASE_ADDR),
      56'(SMC_TOP_XVISOR_REGION_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR),
      56'(SMC_TOP_SMC_CLUSTER_ERROR_DEVICE_BASE_ADDR)
  };
  localparam logic [55:0] RowExtent[NumRows] = '{
      56'(SMC_TOP_SMC_CLUSTER_CORE0_WDT_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CORE1_WDT_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CORE2_WDT_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CORE3_WDT_SIZE),
      56'(SMC_TOP_DEBUG_MODULE_SIZE),
      56'(SMC_TOP_SMC_RESET_UNIT_SIZE),
      56'(SMC_TOP_SMC_MISC_WRAP_SIZE),
      56'(SMC_TOP_GPIO_INTF_WRAP_SIZE),
      56'(SMC_TOP_SMC_AVSBUS_CONTROLLER_SIZE),
      56'(SMC_TOP_SMC_I2C_WRAP_SIZE),
      56'(SMC_TOP_SMC_UART_WRAP_SIZE),
      56'(SMC_TOP_SMC_EFUSE_MAP_SIZE),
      56'(SMC_TOP_EFUSE_INTERFACE_CTRL_SIZE),
      56'(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_SIZE),
      56'(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_SIZE),
      56'(SMC_TOP_DTP_CTRL_REG_SIZE),
      56'(SMC_TOP_DFX_CTRL_SIZE),
      56'(SMC_TOP_SMC_BASE_CONFIG_SIZE),
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_SIZE),
      56'(SMC_TOP_SMC_MMODE_REMAP_WRAP_SIZE),
      56'(SMC_TOP_SMC_XVISOR_REMAP_WRAP_SIZE),
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_SIZE),
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_SIZE),
      56'(SMC_TOP_SMC_MAILBOX_SIZE),
      56'(SMC_TOP_DMA_CTRL_SIZE),
      56'(SMC_TOP_ZEROER_CTRL_SIZE),
      56'(SMC_TOP_SMC_CPU_CTRL_SIZE),
      56'(SMC_TOP_OCA_I3C_WRAP_SIZE),
      56'(SMC_TOP_SPM_ROM_MEMORY_SIZE),
      56'(SMC_TOP_SPM_MEMORY_SIZE),
      56'(SMC_TOP_SMC_CLA_SIZE),
      56'(SMC_TOP_SMC_EXTERNAL_SIZE),
      56'(SMC_TOP_MMODE_REGION_SIZE),
      56'(SMC_TOP_XVISOR_REGION_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_PLIC_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CLINT_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CORE0_BEU_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CORE1_BEU_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CORE2_BEU_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_CORE3_BEU_SIZE),
      56'(SMC_TOP_SMC_CLUSTER_ERROR_DEVICE_SIZE)
  };
  // The last address of each aperture: the next row's base less one where
  // the rows abut, base plus extent less one where the extent fills the
  // aperture, base plus the RDL aperture size less one for the three rows a
  // gap follows.
  localparam logic [55:0] RowLast[NumRows] = '{
      56'(SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_DEBUG_MODULE_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_DEBUG_MODULE_BASE_ADDR) + 56'(SMC_TOP_DEBUG_MODULE_SIZE) - 56'd1,
      56'(SMC_TOP_SMC_MISC_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_GPIO_INTF_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_I2C_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_UART_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_UART_WRAP_BASE_ADDR) + 56'(SMC_TOP_SMC_UART_WRAP_SIZE) - 56'd1,
      56'(SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_DTP_CTRL_REG_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_DTP_CTRL_REG_BASE_ADDR) + 56'(SMC_TOP_DTP_CTRL_REG_SIZE) - 56'd1,
      56'(SMC_TOP_DFX_CTRL_BASE_ADDR) + DfxCtrlAperture - 56'd1,
      56'(SMC_TOP_SMC_ALIAS_REMAP_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_MMODE_REMAP_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_XVISOR_REMAP_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_BASE_ADDR) + OutboundFilterAperture - 56'd1,
      56'(SMC_TOP_DMA_CTRL_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_ZEROER_CTRL_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_ZEROER_CTRL_BASE_ADDR) + ZeroerCtrlAperture - 56'd1,
      56'(SMC_TOP_OCA_I3C_WRAP_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_OCA_I3C_WRAP_BASE_ADDR) + 56'(SMC_TOP_OCA_I3C_WRAP_SIZE) - 56'd1,
      56'(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR) + 56'(SMC_TOP_SPM_ROM_MEMORY_SIZE) - 56'd1,
      56'(SMC_TOP_SPM_MEMORY_BASE_ADDR) + 56'(SMC_TOP_SPM_MEMORY_SIZE) - 56'd1,
      56'(SMC_TOP_SMC_CLA_BASE_ADDR) + 56'(SMC_TOP_SMC_CLA_SIZE) - 56'd1,
      56'(SMC_TOP_SMC_EXTERNAL_BASE_ADDR) + 56'(SMC_TOP_SMC_EXTERNAL_SIZE) - 56'd1,
      56'(SMC_TOP_MMODE_REGION_BASE_ADDR) + 56'(SMC_TOP_MMODE_REGION_SIZE) - 56'd1,
      56'(SMC_TOP_XVISOR_REGION_BASE_ADDR) + 56'(SMC_TOP_XVISOR_REGION_SIZE) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR) - 56'd1,
      56'(SMC_TOP_SMC_CLUSTER_ERROR_DEVICE_BASE_ADDR) - 56'd1,
      56'(
      SMC_TOP_SMC_CLUSTER_ERROR_DEVICE_BASE_ADDR
      ) + 56'(
      SMC_TOP_SMC_CLUSTER_ERROR_DEVICE_SIZE
      ) - 56'd1
  };
  // The kind code of the 30 rows whose Past Extent cell states a response
  // (0 to 29 in map order); the 11 rows whose decoded extent fills the
  // aperture have no past-extent address and no code.
  localparam logic [5:0] RowKind[NumRows] = '{
      6'd0,
      6'd1,
      6'd2,
      6'd3,
      KindNone,
      6'd4,
      6'd5,
      6'd6,
      6'd7,
      6'd8,
      KindNone,
      6'd9,
      6'd10,
      6'd11,
      6'd12,
      KindNone,
      6'd13,
      6'd14,
      6'd15,
      6'd16,
      6'd17,
      6'd18,
      6'd19,
      6'd20,
      6'd21,
      6'd22,
      6'd23,
      KindNone,
      KindNone,
      KindNone,
      KindNone,
      KindNone,
      KindNone,
      KindNone,
      6'd24,
      6'd25,
      6'd26,
      6'd27,
      6'd28,
      6'd29,
      KindNone
  };
  // The gaps between consecutive rows take codes 30 to 36 in address order;
  // the outside-window classes codes 37 to 43.
  localparam logic [5:0] KindGap0 = 6'd30;
  localparam logic [5:0] KindBelowBoth = 6'd37;
  localparam logic [5:0] KindBetween = 6'd38;
  localparam logic [5:0] KindAboveBoth = 6'd39;
  localparam logic [5:0] KindAbove4Gib = 6'd40;
  localparam logic [5:0] KindRegionEndLocal = 6'd41;
  localparam logic [5:0] KindRegionEndGlobal = 6'd42;
  localparam logic [5:0] KindXvisorFirst = 6'd43;

  // The decode of a request address: the kind, whether the kind is a
  // past-extent row and whether it lies inside the window (the 24 rows and 6
  // gaps whose 4-byte read answers 0xBADCAB1E). The pinned classes take
  // precedence over the rows they sit in: BASE + REGION_SIZE is the first
  // word of the M-mode region at the reset value.
  typedef struct packed {
    logic [5:0] kind;
    logic row;
    logic in_win;
  } dec_t;

  function automatic dec_t decode(input logic [55:0] a, input logic [55:0] win);
    logic [5:0] gap;
    decode = '{kind: KindNone, row: 1'b0, in_win: 1'b0};
    if ((a == LocalBase + win) || (a == GlobalBase + win)) begin
      decode.kind = (a == LocalBase + win) ? KindRegionEndLocal : KindRegionEndGlobal;
      return decode;
    end
    if ((a == LocalBase + XvisorOff) || (a == GlobalBase + XvisorOff)) begin
      decode.kind = KindXvisorFirst;
      return decode;
    end
    gap = KindGap0;
    for (int unsigned i = 0; i < NumRows; i++) begin
      if ((RowKind[i] != KindNone) && (a >= RowBase[i] + RowExtent[i]) && (a <= RowLast[i])) begin
        decode = '{kind: RowKind[i], row: 1'b1, in_win: (RowLast[i] < LocalBase + win)};
        return decode;
      end
      if ((i + 1 < NumRows) && (RowLast[i] + 56'd1 < RowBase[i+1])) begin
        if ((a > RowLast[i]) && (a < RowBase[i+1])) begin
          decode = '{kind: gap, row: 1'b0, in_win: (RowBase[i+1] - 56'd1 < LocalBase + win)};
          return decode;
        end
        gap = gap + 6'd1;
      end
    end
    if (a < GlobalBase) decode.kind = KindBelowBoth;
    else if ((a >= GlobalBase + XvisorEnd) && (a < LocalBase)) decode.kind = KindBetween;
    else if ((a >= MapTop) && (a < FourGib)) decode.kind = KindAboveBoth;
    else if (a >= FourGib) decode.kind = KindAbove4Gib;
    return decode;
  endfunction

  // ------------------------------------------------------------------
  // SEP_IN write decode (the form of smc_filt_fcov): address at the AW
  // accept, data and strobe at the W-last accept, commit at the B accept
  // with OKAY; one SEP_IN write is outstanding at a time. Two consumers: the
  // shadow of CLOCK_GATE_CONTROL (a 32-bit register in the lane its address
  // selects) and the inbound entry 0 written flag (64-bit registers, every
  // strobe set).
  // ------------------------------------------------------------------
  wire sep_aw_acc = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire sep_w_last_acc = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1)
      && (sep_wlast_i === 1'b1);
  wire sep_b_acc = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1);
  wire sep_b_okay = sep_b_acc && (sep_bresp_i === 2'b00);
  wire sep_ar_acc = (sep_arvalid_i === 1'b1) && (sep_arready_i === 1'b1);
  wire sep_r_last_acc = (sep_rvalid_i === 1'b1) && (sep_rready_i === 1'b1)
      && (sep_rlast_i === 1'b1);
  wire sys_aw_acc = (sys_awvalid_i === 1'b1) && (sys_awready_i === 1'b1);
  wire sys_b_acc = (sys_bvalid_i === 1'b1) && (sys_bready_i === 1'b1);
  wire sys_ar_acc = (sys_arvalid_i === 1'b1) && (sys_arready_i === 1'b1);
  wire sys_r_last_acc = (sys_rvalid_i === 1'b1) && (sys_rready_i === 1'b1)
      && (sys_rlast_i === 1'b1);

  localparam logic [55:0] CgAddr = 56'(SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_ADDR);
  localparam logic [31:0] CgReset = 32'(SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_DEFAULT);
  // The enables of the windows the owner probes with the clock running.
  localparam logic [31:0] CgWindowMask = 32'(SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_I2C_CG_EN_MASK)
      | 32'(SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_UART_CG_EN_MASK)
      | 32'(SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_I3C_CG_EN_MASK)
      | 32'(SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_AVS_CG_EN_MASK)
      | 32'(SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_TELEMETRY_CG_EN_MASK);
  localparam int unsigned I2cCgShift = SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_I2C_CG_EN_SHIFT;
  localparam logic [55:0] Inb0Base = 56'(SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_BASE_ADDR);
  localparam logic [55:0] Inb0Config = Inb0Base + 56'(FILTER_CTRL_FILTER_CONFIG_BASE_ADDR);
  localparam logic [55:0] Inb0Start = Inb0Base + 56'(FILTER_CTRL_START_ADDR_BASE_ADDR);
  localparam logic [55:0] Inb0End = Inb0Base + 56'(FILTER_CTRL_END_ADDR_BASE_ADDR);

  logic [55:0] sep_waddr_q;
  logic [63:0] sep_wdata_q;
  logic [7:0] sep_wstrb_q;
  logic [31:0] cg_q;
  wire sep_w_lane_hi = sep_waddr_q[2];
  wire sep_w_lane_full = sep_w_lane_hi ? (sep_wstrb_q[7:4] === 4'hF) : (sep_wstrb_q[3:0] === 4'hF);
  wire [31:0] sep_w_lane = sep_w_lane_hi ? sep_wdata_q[63:32] : sep_wdata_q[31:0];
  wire cg_w = sep_b_okay && sep_w_lane_full && ((sep_waddr_q & ~56'h7) == (CgAddr & ~56'h7))
      && (sep_waddr_q[2] == CgAddr[2]);
  wire inb0_w = sep_b_okay && (sep_wstrb_q === 8'hFF)
      && ((sep_waddr_q == Inb0Config) || (sep_waddr_q == Inb0Start) || (sep_waddr_q == Inb0End));

  // Owner qualifier beside the gate: the group samples while inbound entry 0
  // has been written since the gate rose (a SEP_IN write completed OKAY at
  // its FILTER_CONFIG, START_ADDR or END_ADDR register with every strobe
  // set); the flag clears on every rise. The one gate net opens every live
  // group; an owner that programs entry 0 before raising its gate, or
  // programs it never, counts nothing here.
  wire gate_on = (fcov_gate_i === 1'b1);
  logic gate_q;
  wire gate_rise = gate_on && !gate_q;
  logic inb0_written_q;

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      sep_waddr_q <= '0;
      sep_wdata_q <= '0;
      sep_wstrb_q <= '0;
      cg_q <= CgReset;
      gate_q <= 1'b0;
      inb0_written_q <= 1'b0;
    end else begin
      if (sep_aw_acc) sep_waddr_q <= sep_awaddr_i;
      if (sep_w_last_acc) begin
        sep_wdata_q <= sep_wdata_i;
        sep_wstrb_q <= sep_wstrb_i;
      end
      if (cg_w) cg_q <= sep_w_lane;
      gate_q <= gate_on;
      if (gate_rise) inb0_written_q <= 1'b0;
      else if (inb0_w) inb0_written_q <= 1'b1;
    end
  end

  // The five enables clear in the shadow, the DUT's I2C enable agreeing with
  // it, and REGION_SIZE at the reset word the table holds at.
  wire cg_clear = ((cg_q & CgWindowMask) == 32'd0);
  wire i2c_agrees = (i2c_cg_en_i === cg_q[I2cCgShift]);
  wire win_ok = (region_size_i === RegionSizeReset);
  wire [55:0] win = 56'(region_size_i);
  wire mrr_live = gate_on && inb0_written_q && cg_clear && i2c_agrees && win_ok;

  // ------------------------------------------------------------------
  // Request records, one per port and direction: the address decode and the
  // AxSIZE at the AW or AR accept, released at the B or R-last accept, when
  // the response code and the read word are known. The owner issues one
  // access at a time.
  // ------------------------------------------------------------------
  typedef struct packed {
    logic pending;
    dec_t dec;
    logic [2:0] addr_lo;
    logic [1:0] size;
  } probe_t;

  probe_t sep_wr_q, sep_rd_q, sys_wr_q, sys_rd_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      sep_wr_q <= '0;
      sep_rd_q <= '0;
      sys_wr_q <= '0;
      sys_rd_q <= '0;
    end else begin
      if (sep_aw_acc) begin
        sep_wr_q <= '{
            pending: 1'b1,
            dec: decode(sep_awaddr_i, win),
            addr_lo: sep_awaddr_i[2:0],
            size: sep_awsize_i[1:0]
        };
      end else if (sep_b_acc) begin
        sep_wr_q.pending <= 1'b0;
      end
      if (sep_ar_acc) begin
        sep_rd_q <= '{
            pending: 1'b1,
            dec: decode(sep_araddr_i, win),
            addr_lo: sep_araddr_i[2:0],
            size: sep_arsize_i[1:0]
        };
      end else if (sep_r_last_acc) begin
        sep_rd_q.pending <= 1'b0;
      end
      if (sys_aw_acc) begin
        sys_wr_q <= '{
            pending: 1'b1,
            dec: decode(sys_awaddr_i, win),
            addr_lo: sys_awaddr_i[2:0],
            size: sys_awsize_i[1:0]
        };
      end else if (sys_b_acc) begin
        sys_wr_q.pending <= 1'b0;
      end
      if (sys_ar_acc) begin
        sys_rd_q <= '{
            pending: 1'b1,
            dec: decode(sys_araddr_i, win),
            addr_lo: sys_araddr_i[2:0],
            size: sys_arsize_i[1:0]
        };
      end else if (sys_r_last_acc) begin
        sys_rd_q.pending <= 1'b0;
      end
    end
  end

  // The word a read returns in the lane its address selects (the manager
  // takes the addressed bytes), compared with the stated 0xBADCAB1E on a
  // 4-byte read of an inside row or gap (ocah_gap_resp and
  // ocah_past_extent_resp of smc_memory_map.rdl, memmap.adoc, Address Space
  // Organization).
  localparam logic [31:0] PastWord = 32'hBADCAB1E;
  localparam logic [1:0] SizeFour = 2'd2;
  localparam logic [1:0] RespDecerr = 2'b11;

  function automatic logic [31:0] lane_word(input logic [63:0] data, input logic [2:0] lo);
    logic [63:0] shifted;
    shifted = data >> (8 * lo);
    return shifted[31:0];
  endfunction

  // One completion at a time per port is the owner's issue order; a read and
  // a write completing in the same cycle on one port sample the write only,
  // which never arises under one outstanding access.
  wire sep_wr_done = sep_b_acc && sep_wr_q.pending;
  wire sep_rd_done = sep_r_last_acc && sep_rd_q.pending;
  wire sys_wr_done = sys_b_acc && sys_wr_q.pending;
  wire sys_rd_done = sys_r_last_acc && sys_rd_q.pending;
  wire sep_done = sep_wr_done || sep_rd_done;
  wire sys_done = sys_wr_done || sys_rd_done;

  probe_t sep_p, sys_p;
  assign sep_p = sep_wr_done ? sep_wr_q : sep_rd_q;
  assign sys_p = sys_wr_done ? sys_wr_q : sys_rd_q;
  wire [1:0] sep_resp = sep_wr_done ? sep_bresp_i : sep_rresp_i;
  wire [1:0] sys_resp = sys_wr_done ? sys_bresp_i : sys_rresp_i;
  wire [31:0] sep_word = lane_word(sep_rdata_i, sep_p.addr_lo);
  wire [31:0] sys_word = lane_word(sys_rdata_i, sys_p.addr_lo);

  // Per completion: a counted cell needs DECERR, and 0xBADCAB1E on a 4-byte
  // read of an inside row or gap; the 1-, 2- and 8-byte accesses of an inside
  // row are recorded (their code), as is the read word of a 1-, 2- or 8-byte
  // read of an inside row or gap.
  function automatic logic goal_of(input probe_t p);
    if (p.dec.kind == KindNone) return 1'b0;
    if (p.dec.row && p.dec.in_win && (p.size != SizeFour)) return 1'b0;
    return 1'b1;
  endfunction

  function automatic logic outcome_of(input probe_t p, input logic write, input logic [1:0] resp,
                                      input logic [31:0] word);
    if (resp !== RespDecerr) return 1'b0;
    if (!write && p.dec.in_win && (p.size == SizeFour)) return (word === PastWord);
    return 1'b1;
  endfunction

  wire sep_graded = mrr_live && sep_done && goal_of(sep_p)
      && outcome_of(sep_p, sep_wr_done, sep_resp, sep_word);
  wire sys_graded = mrr_live && sys_done && goal_of(sys_p)
      && outcome_of(sys_p, sys_wr_done, sys_resp, sys_word);
  wire sep_rec_resp = mrr_live && sep_done && sep_p.dec.row && sep_p.dec.in_win
      && (sep_p.size != SizeFour);
  wire sys_rec_resp = mrr_live && sys_done && sys_p.dec.row && sys_p.dec.in_win
      && (sys_p.size != SizeFour);
  wire sep_rec_word = mrr_live && sep_rd_done && sep_p.dec.in_win && (sep_p.size != SizeFour)
      && (sep_p.dec.kind != KindNone);
  wire sys_rec_word = mrr_live && sys_rd_done && sys_p.dec.in_win && (sys_p.size != SizeFour)
      && (sys_p.dec.kind != KindNone);

  localparam logic [1:0] FlagGoal = 2'd1;
  localparam logic [1:0] FlagRecResp = 2'd2;
  localparam logic [1:0] FlagRecWord = 2'd3;

  // The 11 bins of a past-extent row inside the window: the counted 4-byte
  // read and write, the recorded codes of its other sizes, the recorded read
  // words of its other sizes.
  `define SMC_MRR_INSIDE_ROW_BINS(name, k) \
      bins name``_r4 = {{FlagGoal, k, 1'b0, 2'd2}}; \
      bins name``_w4 = {{FlagGoal, k, 1'b1, 2'd2}}; \
      bins rec_``name``_r1 = {{FlagRecResp, k, 1'b0, 2'd0}}; \
      bins rec_``name``_r2 = {{FlagRecResp, k, 1'b0, 2'd1}}; \
      bins rec_``name``_r8 = {{FlagRecResp, k, 1'b0, 2'd3}}; \
      bins rec_``name``_w1 = {{FlagRecResp, k, 1'b1, 2'd0}}; \
      bins rec_``name``_w2 = {{FlagRecResp, k, 1'b1, 2'd1}}; \
      bins rec_``name``_w8 = {{FlagRecResp, k, 1'b1, 2'd3}}; \
      bins rec_``name``_rd1 = {{FlagRecWord, k, 1'b0, 2'd0}}; \
      bins rec_``name``_rd2 = {{FlagRecWord, k, 1'b0, 2'd1}}; \
      bins rec_``name``_rd8 = {{FlagRecWord, k, 1'b0, 2'd3}};

  // The 8 counted bins of a kind whose code is counted on every size and
  // direction.
  `define SMC_MRR_FULL_BINS(name, k) \
      bins name``_r1 = {{FlagGoal, k, 1'b0, 2'd0}}; \
      bins name``_r2 = {{FlagGoal, k, 1'b0, 2'd1}}; \
      bins name``_r4 = {{FlagGoal, k, 1'b0, 2'd2}}; \
      bins name``_r8 = {{FlagGoal, k, 1'b0, 2'd3}}; \
      bins name``_w1 = {{FlagGoal, k, 1'b1, 2'd0}}; \
      bins name``_w2 = {{FlagGoal, k, 1'b1, 2'd1}}; \
      bins name``_w4 = {{FlagGoal, k, 1'b1, 2'd2}}; \
      bins name``_w8 = {{FlagGoal, k, 1'b1, 2'd3}};

  // The 11 bins of a gap inside the window: the 8 counted codes and the
  // recorded read words of the other sizes.
  `define SMC_MRR_INSIDE_GAP_BINS(name, k) \
      `SMC_MRR_FULL_BINS(name, k) \
      bins rec_``name``_rd1 = {{FlagRecWord, k, 1'b0, 2'd0}}; \
      bins rec_``name``_rd2 = {{FlagRecWord, k, 1'b0, 2'd1}}; \
      bins rec_``name``_rd8 = {{FlagRecWord, k, 1'b0, 2'd3}};

  // The two port bins of a kind.
  `define SMC_MRR_PORT_BINS(name, k) \
      bins name``_sep = {{1'b1, k, 1'b0}}; \
      bins name``_sys = {{1'b1, k, 1'b1}};

  // Each sample fills the coverpoints of its event and passes the others a
  // value no bin lists. Every cell of a row has a bin; the group has no
  // ignore_bins.
  covergroup smc_map_row_response_cg with function sample (
      logic graded, logic [5:0] kind, logic [1:0] flag, logic write, logic [1:0] size, logic port
  );
    option.per_instance = 1;
    // {graded, kind}: the 30 past-extent rows, 7 gaps and 7 outside-window
    // classes, 44 bins.
    cp_row_kind: coverpoint {
      graded, kind
    } {
      bins core0_wdt = {{1'b1, 6'd0}};
      bins core1_wdt = {{1'b1, 6'd1}};
      bins core2_wdt = {{1'b1, 6'd2}};
      bins core3_wdt = {{1'b1, 6'd3}};
      bins reset_unit = {{1'b1, 6'd4}};
      bins misc_wrap = {{1'b1, 6'd5}};
      bins gpio_intf = {{1'b1, 6'd6}};
      bins avsbus = {{1'b1, 6'd7}};
      bins i2c = {{1'b1, 6'd8}};
      bins efuse_map = {{1'b1, 6'd9}};
      bins efuse_if = {{1'b1, 6'd10}};
      bins telemetry = {{1'b1, 6'd11}};
      bins octs = {{1'b1, 6'd12}};
      bins dfx = {{1'b1, 6'd13}};
      bins base_config = {{1'b1, 6'd14}};
      bins alias_remap = {{1'b1, 6'd15}};
      bins mmode_remap = {{1'b1, 6'd16}};
      bins xvisor_remap = {{1'b1, 6'd17}};
      bins inbound_filter = {{1'b1, 6'd18}};
      bins outbound_filter = {{1'b1, 6'd19}};
      bins mailbox = {{1'b1, 6'd20}};
      bins dma = {{1'b1, 6'd21}};
      bins zeroer = {{1'b1, 6'd22}};
      bins cpu_ctrl = {{1'b1, 6'd23}};
      bins plic = {{1'b1, 6'd24}};
      bins clint = {{1'b1, 6'd25}};
      bins core0_beu = {{1'b1, 6'd26}};
      bins core1_beu = {{1'b1, 6'd27}};
      bins core2_beu = {{1'b1, 6'd28}};
      bins core3_beu = {{1'b1, 6'd29}};
      bins gap_debug_module = {{1'b1, 6'd30}};
      bins gap_dfx = {{1'b1, 6'd31}};
      bins gap_outbound_filter = {{1'b1, 6'd32}};
      bins gap_zeroer = {{1'b1, 6'd33}};
      bins gap_cla = {{1'b1, 6'd34}};
      bins gap_external = {{1'b1, 6'd35}};
      bins gap_xvisor = {{1'b1, 6'd36}};
      bins below_both = {{1'b1, 6'd37}};
      bins between = {{1'b1, 6'd38}};
      bins above_both = {{1'b1, 6'd39}};
      bins above_4gib = {{1'b1, 6'd40}};
      bins region_end_local = {{1'b1, 6'd41}};
      bins region_end_global = {{1'b1, 6'd42}};
      bins xvisor_first = {{1'b1, 6'd43}};
    }
    // {flag, kind, direction, AxSIZE}: 208 counted cells and 234 recorded
    // bins (SMC_FCOV.adoc, cp_dir_size).
    cp_dir_size: coverpoint {
      flag, kind, write, size
    } {
      `SMC_MRR_INSIDE_ROW_BINS(core0_wdt, 6'd0)
      `SMC_MRR_INSIDE_ROW_BINS(core1_wdt, 6'd1)
      `SMC_MRR_INSIDE_ROW_BINS(core2_wdt, 6'd2)
      `SMC_MRR_INSIDE_ROW_BINS(core3_wdt, 6'd3)
      `SMC_MRR_INSIDE_ROW_BINS(reset_unit, 6'd4)
      `SMC_MRR_INSIDE_ROW_BINS(misc_wrap, 6'd5)
      `SMC_MRR_INSIDE_ROW_BINS(gpio_intf, 6'd6)
      `SMC_MRR_INSIDE_ROW_BINS(avsbus, 6'd7)
      `SMC_MRR_INSIDE_ROW_BINS(i2c, 6'd8)
      `SMC_MRR_INSIDE_ROW_BINS(efuse_map, 6'd9)
      `SMC_MRR_INSIDE_ROW_BINS(efuse_if, 6'd10)
      `SMC_MRR_INSIDE_ROW_BINS(telemetry, 6'd11)
      `SMC_MRR_INSIDE_ROW_BINS(octs, 6'd12)
      `SMC_MRR_INSIDE_ROW_BINS(dfx, 6'd13)
      `SMC_MRR_INSIDE_ROW_BINS(base_config, 6'd14)
      `SMC_MRR_INSIDE_ROW_BINS(alias_remap, 6'd15)
      `SMC_MRR_INSIDE_ROW_BINS(mmode_remap, 6'd16)
      `SMC_MRR_INSIDE_ROW_BINS(xvisor_remap, 6'd17)
      `SMC_MRR_INSIDE_ROW_BINS(inbound_filter, 6'd18)
      `SMC_MRR_INSIDE_ROW_BINS(outbound_filter, 6'd19)
      `SMC_MRR_INSIDE_ROW_BINS(mailbox, 6'd20)
      `SMC_MRR_INSIDE_ROW_BINS(dma, 6'd21)
      `SMC_MRR_INSIDE_ROW_BINS(zeroer, 6'd22)
      `SMC_MRR_INSIDE_ROW_BINS(cpu_ctrl, 6'd23)
      `SMC_MRR_FULL_BINS(plic, 6'd24)
      `SMC_MRR_FULL_BINS(clint, 6'd25)
      `SMC_MRR_FULL_BINS(core0_beu, 6'd26)
      `SMC_MRR_FULL_BINS(core1_beu, 6'd27)
      `SMC_MRR_FULL_BINS(core2_beu, 6'd28)
      `SMC_MRR_FULL_BINS(core3_beu, 6'd29)
      `SMC_MRR_INSIDE_GAP_BINS(gap_debug_module, 6'd30)
      `SMC_MRR_INSIDE_GAP_BINS(gap_dfx, 6'd31)
      `SMC_MRR_INSIDE_GAP_BINS(gap_outbound_filter, 6'd32)
      `SMC_MRR_INSIDE_GAP_BINS(gap_zeroer, 6'd33)
      `SMC_MRR_INSIDE_GAP_BINS(gap_cla, 6'd34)
      `SMC_MRR_INSIDE_GAP_BINS(gap_external, 6'd35)
      `SMC_MRR_FULL_BINS(gap_xvisor, 6'd36)
      `SMC_MRR_FULL_BINS(below_both, 6'd37)
      `SMC_MRR_FULL_BINS(between, 6'd38)
      `SMC_MRR_FULL_BINS(above_both, 6'd39)
      `SMC_MRR_FULL_BINS(above_4gib, 6'd40)
      `SMC_MRR_FULL_BINS(region_end_local, 6'd41)
      `SMC_MRR_FULL_BINS(region_end_global, 6'd42)
      `SMC_MRR_FULL_BINS(xvisor_first, 6'd43)
    }
    // {graded, kind, port}: 88 cells.
    cp_port: coverpoint {
      graded, kind, port
    } {
      `SMC_MRR_PORT_BINS(core0_wdt, 6'd0)
      `SMC_MRR_PORT_BINS(core1_wdt, 6'd1)
      `SMC_MRR_PORT_BINS(core2_wdt, 6'd2)
      `SMC_MRR_PORT_BINS(core3_wdt, 6'd3)
      `SMC_MRR_PORT_BINS(reset_unit, 6'd4)
      `SMC_MRR_PORT_BINS(misc_wrap, 6'd5)
      `SMC_MRR_PORT_BINS(gpio_intf, 6'd6)
      `SMC_MRR_PORT_BINS(avsbus, 6'd7)
      `SMC_MRR_PORT_BINS(i2c, 6'd8)
      `SMC_MRR_PORT_BINS(efuse_map, 6'd9)
      `SMC_MRR_PORT_BINS(efuse_if, 6'd10)
      `SMC_MRR_PORT_BINS(telemetry, 6'd11)
      `SMC_MRR_PORT_BINS(octs, 6'd12)
      `SMC_MRR_PORT_BINS(dfx, 6'd13)
      `SMC_MRR_PORT_BINS(base_config, 6'd14)
      `SMC_MRR_PORT_BINS(alias_remap, 6'd15)
      `SMC_MRR_PORT_BINS(mmode_remap, 6'd16)
      `SMC_MRR_PORT_BINS(xvisor_remap, 6'd17)
      `SMC_MRR_PORT_BINS(inbound_filter, 6'd18)
      `SMC_MRR_PORT_BINS(outbound_filter, 6'd19)
      `SMC_MRR_PORT_BINS(mailbox, 6'd20)
      `SMC_MRR_PORT_BINS(dma, 6'd21)
      `SMC_MRR_PORT_BINS(zeroer, 6'd22)
      `SMC_MRR_PORT_BINS(cpu_ctrl, 6'd23)
      `SMC_MRR_PORT_BINS(plic, 6'd24)
      `SMC_MRR_PORT_BINS(clint, 6'd25)
      `SMC_MRR_PORT_BINS(core0_beu, 6'd26)
      `SMC_MRR_PORT_BINS(core1_beu, 6'd27)
      `SMC_MRR_PORT_BINS(core2_beu, 6'd28)
      `SMC_MRR_PORT_BINS(core3_beu, 6'd29)
      `SMC_MRR_PORT_BINS(gap_debug_module, 6'd30)
      `SMC_MRR_PORT_BINS(gap_dfx, 6'd31)
      `SMC_MRR_PORT_BINS(gap_outbound_filter, 6'd32)
      `SMC_MRR_PORT_BINS(gap_zeroer, 6'd33)
      `SMC_MRR_PORT_BINS(gap_cla, 6'd34)
      `SMC_MRR_PORT_BINS(gap_external, 6'd35)
      `SMC_MRR_PORT_BINS(gap_xvisor, 6'd36)
      `SMC_MRR_PORT_BINS(below_both, 6'd37)
      `SMC_MRR_PORT_BINS(between, 6'd38)
      `SMC_MRR_PORT_BINS(above_both, 6'd39)
      `SMC_MRR_PORT_BINS(above_4gib, 6'd40)
      `SMC_MRR_PORT_BINS(region_end_local, 6'd41)
      `SMC_MRR_PORT_BINS(region_end_global, 6'd42)
      `SMC_MRR_PORT_BINS(xvisor_first, 6'd43)
    }
  endgroup
  `undef SMC_MRR_INSIDE_ROW_BINS
  `undef SMC_MRR_FULL_BINS
  `undef SMC_MRR_INSIDE_GAP_BINS
  `undef SMC_MRR_PORT_BINS

  smc_map_row_response_cg u_cg_map_row_response = new();

  // A counted completion fills the three coverpoints at once; a recorded
  // completion fills cp_dir_size alone, with the row-kind and port
  // coverpoints passed an ungraded value.
  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      if (sep_graded) begin
        u_cg_map_row_response.sample(1'b1, sep_p.dec.kind, FlagGoal, sep_wr_done, sep_p.size, 1'b0);
      end
      if (sep_rec_resp) begin
        u_cg_map_row_response.sample(1'b0, sep_p.dec.kind, FlagRecResp, sep_wr_done, sep_p.size,
                                     1'b0);
      end
      if (sep_rec_word) begin
        u_cg_map_row_response.sample(1'b0, sep_p.dec.kind, FlagRecWord, 1'b0, sep_p.size, 1'b0);
      end
      if (sys_graded) begin
        u_cg_map_row_response.sample(1'b1, sys_p.dec.kind, FlagGoal, sys_wr_done, sys_p.size, 1'b1);
      end
      if (sys_rec_resp) begin
        u_cg_map_row_response.sample(1'b0, sys_p.dec.kind, FlagRecResp, sys_wr_done, sys_p.size,
                                     1'b1);
      end
      if (sys_rec_word) begin
        u_cg_map_row_response.sample(1'b0, sys_p.dec.kind, FlagRecWord, 1'b0, sys_p.size, 1'b1);
      end
    end
  end

endmodule : smc_map_row_fcov
