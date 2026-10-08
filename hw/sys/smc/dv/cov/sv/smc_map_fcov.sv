// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC address-map functional coverage on the SEP_IN AXI manager: which
// spec-mapped apertures the suite reached and completed, plus the external
// managers' read/write completions.
//
// Every window below is a `BASE + offset` with BASE the local alias
// 0xC000_0000. Unit bases, instance strides and instance counts come from the
// generated address map (smc_top_addrmap_pkg); a unit's aperture is the `Size`
// column of the generated component map (regs/gen/adoc/memory_map.adoc), which
// the package does not carry, and the layout regions are that file's
// functional-organization table. Placements inside the adopter external window
// are the reference integration's, from the generated SMC address header
// (regs/gen/c/smc_addr.h, SMC_TOP_SMC_EXTERNAL_*). A cell is
// hit when a transaction to the window completed, not when its address was
// merely presented.
//
// Attributing a response to an address needs the two channels tied to one
// transaction. This module keeps a single-outstanding tracker per direction:
// the address is latched when it is the only transaction in flight, and the
// completing response is attributed to it only while it is still the only one.
// Overlapping transactions are not attributed, so the points under-count
// rather than correlate unrelated beats.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_map_fcov (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // SEP_IN inbound manager.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire [55:0] sep_awaddr_i,
  input wire sep_wvalid_i,
  input wire sep_wready_i,
  input wire sep_wlast_i,
  input wire [63:0] sep_wdata_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire [1:0] sep_bresp_i,
  input wire sep_arvalid_i,
  input wire sep_arready_i,
  input wire [55:0] sep_araddr_i,
  input wire sep_rvalid_i,
  input wire sep_rready_i,
  input wire sep_rlast_i,
  input wire [1:0] sep_rresp_i,
  input wire [63:0] sep_rdata_i,

  // SYS_IN inbound manager: completion handshakes only.
  input wire sys_bvalid_i,
  input wire sys_bready_i,
  input wire sys_rvalid_i,
  input wire sys_rready_i,
  input wire sys_rlast_i,

  // JTAG inbound manager: address and completion handshakes, for the remap
  // windows only this manager's path reaches.
  input wire jtag_awvalid_i,
  input wire jtag_awready_i,
  input wire [55:0] jtag_awaddr_i,
  input wire jtag_arvalid_i,
  input wire jtag_arready_i,
  input wire [55:0] jtag_araddr_i,
  input wire [1:0] jtag_bresp_i,
  input wire [1:0] jtag_rresp_i,
  input wire jtag_bvalid_i,
  input wire jtag_bready_i,
  input wire jtag_rvalid_i,
  input wire jtag_rready_i,
  input wire jtag_rlast_i,

  // Lifecycle state driven into lc_state_i, for the readback point.
  input wire [7:0] lc_state_i,

  // REGION_SIZE, which sets how much of the local window escapes folding.
  input wire [31:0] region_size_i,

  // High while the adopter external AXI-Lite port carries a request.
  input wire ext_active_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  import smc_top_addrmap_pkg::*;

  localparam logic [55:0] LocalBase = 56'h00_C000_0000;

  // Generated-map windows as offsets from the local alias. A memory's window
  // is its size; a register block's window is its aperture from the generated
  // component map.
  localparam logic [31:0] RomLo = 32'(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR - LocalBase);
  localparam logic [31:0] RomHi = RomLo + 32'(SMC_TOP_SPM_ROM_MEMORY_SIZE) - 32'd1;
  localparam logic [31:0] SpmLo = 32'(SMC_TOP_SPM_MEMORY_BASE_ADDR - LocalBase);
  localparam logic [31:0] SpmHi = SpmLo + 32'(SMC_TOP_SPM_MEMORY_SIZE) - 32'd1;
  localparam logic [31:0] DmaLo = 32'(SMC_TOP_DMA_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] DmaHi = DmaLo + 32'h200 - 32'd1;
  localparam logic [31:0] ZeroerLo = 32'(SMC_TOP_ZEROER_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] ZeroerHi = ZeroerLo + 32'h100 - 32'd1;
  // Last aligned 64-bit word of a unit's decoded extent: past it the fabric
  // refuses the access even inside the unit's aperture (memmap.adoc, Address
  // Space Organization).
  localparam logic [31:0] DmaTop = ((DmaLo + 32'(SMC_TOP_DMA_CTRL_SIZE)) & ~32'd7) - 32'd8;
  localparam logic [31:0] ZeroerTop = ((ZeroerLo + 32'(SMC_TOP_ZEROER_CTRL_SIZE)) & ~32'd7) - 32'd8;
  localparam logic [31:0] PlicLo = 32'(SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR - LocalBase);
  localparam logic [31:0] PlicHi = PlicLo + 32'h0400_0000 - 32'd1;
  localparam logic [31:0] PlicEnd = PlicLo + 32'(SMC_TOP_SMC_CLUSTER_PLIC_SIZE);
  localparam logic [31:0] PlicTop = (PlicEnd & ~32'd7) - 32'd8;
  localparam logic [31:0] ClintLo = 32'(SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR - LocalBase);
  localparam logic [31:0] ClintTop =
      ((ClintLo + 32'(SMC_TOP_SMC_CLUSTER_CLINT_SIZE)) & ~32'd7) - 32'd8;
  localparam logic [31:0] ResetUnitLo = 32'(SMC_TOP_SMC_RESET_UNIT_BASE_ADDR - LocalBase);
  localparam logic [31:0] MiscWrapLo = 32'(SMC_TOP_SMC_MISC_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] MiscWrapLast = MiscWrapLo + 32'(SMC_TOP_SMC_MISC_WRAP_SIZE) - 32'd4;
  localparam logic [31:0] GpioIntfLo = 32'(SMC_TOP_GPIO_INTF_BASE_ADDR(0) - LocalBase);
  localparam logic [31:0] GpioIntfStride = 32'(SMC_TOP_GPIO_INTF_STRIDE);
  localparam int unsigned GpioIntfNum = int'(SMC_TOP_GPIO_INTF_NUM);
  localparam logic [31:0] AvsLo = 32'(SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR - LocalBase);
  localparam logic [31:0] I2cLo = 32'(SMC_TOP_SMC_I2C_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] UartLo = 32'(SMC_TOP_SMC_UART_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] UartStride = 32'(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_STRIDE);
  localparam int unsigned UartNum = int'(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_NUM);
  localparam logic [31:0] EfuseMapLo = 32'(SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] EfuseIfLo = 32'(SMC_TOP_EFUSE_INTERFACE_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] TelemetryLo =
      32'(SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] OctsLo = 32'(SMC_TOP_SMC_SYSTEM_TIMER_OCTS_BASE_ADDR - LocalBase);
  localparam logic [31:0] DtpCtrlLo = 32'(SMC_TOP_DTP_CTRL_REG_BASE_ADDR - LocalBase);
  localparam logic [31:0] DfxLo = 32'(SMC_TOP_DFX_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] I3cLo = 32'(SMC_TOP_OCA_I3C_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] I3cHi = I3cLo + 32'h6000 - 32'd1;
  localparam logic [31:0] I3cStride = 32'(SMC_TOP_OCA_I3C_WRAP_I3C_CSR_STRIDE);
  localparam int unsigned I3cNum = int'(SMC_TOP_OCA_I3C_WRAP_I3C_CSR_NUM);
  localparam logic [31:0] ClaLo = 32'(SMC_TOP_SMC_CLA_BASE_ADDR - LocalBase);
  localparam logic [31:0] ClaHi = ClaLo + 32'(SMC_TOP_SMC_CLA_SIZE) - 32'd1;
  localparam logic [1:0] RespOkay = 2'b00;

  // Inclusive offset window against the local alias base.
  function automatic logic in_win(input logic [55:0] addr, input logic [31:0] lo,
                                  input logic [31:0] hi);
    return (addr >= (LocalBase + 56'(lo))) && (addr <= (LocalBase + 56'(hi)));
  endfunction

  // ------------------------------------------------------------------
  // Single-outstanding transaction tracker, one per direction.
  // ------------------------------------------------------------------
  wire aw_acc = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire w_last_acc = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1) && (sep_wlast_i === 1'b1);
  wire b_acc = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1);
  wire ar_acc = (sep_arvalid_i === 1'b1) && (sep_arready_i === 1'b1);
  wire r_last_acc = (sep_rvalid_i === 1'b1) && (sep_rready_i === 1'b1) && (sep_rlast_i === 1'b1);

  logic [7:0] rd_out_q, wr_out_q;
  logic rd_single_q, wr_single_q;
  logic [55:0] rd_addr_q, wr_addr_q;
  logic [63:0] wr_data_q;

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      rd_out_q <= '0;
      wr_out_q <= '0;
      rd_single_q <= 1'b0;
      wr_single_q <= 1'b0;
      rd_addr_q <= '0;
      wr_addr_q <= '0;
      wr_data_q <= '0;
    end else begin
      rd_out_q <= rd_out_q + 8'(ar_acc) - 8'(r_last_acc);
      wr_out_q <= wr_out_q + 8'(aw_acc) - 8'(b_acc);
      if (ar_acc) begin
        rd_addr_q <= sep_araddr_i;
        rd_single_q <= (rd_out_q == 8'd0) || ((rd_out_q == 8'd1) && r_last_acc);
      end
      if (aw_acc) begin
        wr_addr_q <= sep_awaddr_i;
        wr_single_q <= (wr_out_q == 8'd0) || ((wr_out_q == 8'd1) && b_acc);
      end
      if (w_last_acc) wr_data_q <= sep_wdata_i;
    end
  end

  // A completion attributed to the latched address.
  wire rd_done = r_last_acc && (rd_out_q == 8'd1) && rd_single_q;
  wire wr_done = b_acc && (wr_out_q == 8'd1) && wr_single_q;
  wire rd_okay = rd_done && (sep_rresp_i == RespOkay);
  wire wr_okay = wr_done && (sep_bresp_i == RespOkay);

  // Reads or writes completing OKAY inside [lo, hi].
  `define SMC_MAP_OK(lo, hi) \
      ((rd_okay && in_win(rd_addr_q, (lo), (hi))) || (wr_okay && in_win(wr_addr_q, (lo), (hi))))

  // 32-bit register lane selected by the transaction address.
  wire [31:0] rd_lane = rd_addr_q[2] ? sep_rdata_i[63:32] : sep_rdata_i[31:0];
  wire [31:0] wr_lane = wr_addr_q[2] ? wr_data_q[63:32] : wr_data_q[31:0];

  // The adopter external port carried the transaction currently latched. The
  // reference integration terminates most of the external window with an
  // error slave, so a completion there is the same response the fabric error
  // slave gives for an address with no rule; only this flag separates the two.
  logic rd_ext_seen_q, wr_ext_seen_q;
  wire ext_active = (ext_active_i === 1'b1);
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      rd_ext_seen_q <= 1'b0;
      wr_ext_seen_q <= 1'b0;
    end else begin
      if (ar_acc) rd_ext_seen_q <= ext_active;
      else if (ext_active) rd_ext_seen_q <= 1'b1;
      if (aw_acc) wr_ext_seen_q <= ext_active;
      else if (ext_active) wr_ext_seen_q <= 1'b1;
    end
  end
  wire rd_ext_done = rd_done && rd_ext_seen_q;
  wire wr_ext_done = wr_done && wr_ext_seen_q;

  // ------------------------------------------------------------------
  // Per-core watchdog windows, 1 KiB each.
  // ------------------------------------------------------------------
  wire wdt0_e = (rd_okay && in_win(rd_addr_q, 32'h0000_0000, 32'h0000_03FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_0000, 32'h0000_03FF));
  wire wdt1_e = (rd_okay && in_win(rd_addr_q, 32'h0000_0400, 32'h0000_07FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_0400, 32'h0000_07FF));
  wire wdt2_e = (rd_okay && in_win(rd_addr_q, 32'h0000_0800, 32'h0000_0BFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_0800, 32'h0000_0BFF));
  wire wdt3_e = (rd_okay && in_win(rd_addr_q, 32'h0000_0C00, 32'h0000_0FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_0C00, 32'h0000_0FFF));
  `OCAH_FCOV_COVER(c_wdt0_decode, wdt0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_wdt1_decode, wdt1_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_wdt2_decode, wdt2_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_wdt3_decode, wdt3_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_wdt_instance_3, wdt3_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // ROM window edges. The word above the top is the scratchpad base, so
  // that point records the completed access; which macro answered is the
  // checker's to decide from the data.
  // ------------------------------------------------------------------
  wire rom_base_read_e = rd_okay && in_win(rd_addr_q, RomLo, RomLo + 32'd7);
  wire rom_top_read_e = rd_okay && in_win(rd_addr_q, RomHi - 32'd7, RomHi);
  wire rom_above_top_e = rd_done && in_win(rd_addr_q, RomHi + 32'd1, RomHi + 32'd8);
  `OCAH_FCOV_COVER(c_rom_base_read, rom_base_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_rom_top_read, rom_top_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_rom_just_above_top_not_rom, rom_above_top_e, clk_smc_i, in_reset)

  // Scratchpad region edges, and a read after a write landed in the region.
  wire spm_rd_ok = rd_okay && in_win(rd_addr_q, SpmLo, SpmHi);
  wire spm_wr_ok = wr_okay && in_win(wr_addr_q, SpmLo, SpmHi);
  logic spm_written_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) spm_written_seen_q <= 1'b0;
    else if (spm_wr_ok) spm_written_seen_q <= 1'b1;
  end
  wire spm_base_e = (rd_okay && in_win(rd_addr_q, SpmLo, SpmLo + 32'd7))
      || (wr_okay && in_win(wr_addr_q, SpmLo, SpmLo + 32'd7));
  wire spm_top_e = (rd_okay && in_win(rd_addr_q, SpmHi - 32'd7, SpmHi))
      || (wr_okay && in_win(wr_addr_q, SpmHi - 32'd7, SpmHi));
  wire spm_write_then_read_e = spm_rd_ok && spm_written_seen_q;
  `OCAH_FCOV_COVER(c_spm_region_base, spm_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_spm_region_top, spm_top_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_spm_write_then_read, spm_write_then_read_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // DMA (512 B) and zeroer (256 B) apertures, adjacent.
  // ------------------------------------------------------------------
  wire dma_win_ok = (rd_okay && in_win(rd_addr_q, DmaLo, DmaHi))
      || (wr_okay && in_win(wr_addr_q, DmaLo, DmaHi));
  wire zeroer_win_ok = (rd_okay && in_win(rd_addr_q, ZeroerLo, ZeroerHi))
      || (wr_okay && in_win(wr_addr_q, ZeroerLo, ZeroerHi));
  wire dma_base_e = (rd_okay && in_win(rd_addr_q, DmaLo, DmaLo + 32'd7))
      || (wr_okay && in_win(wr_addr_q, DmaLo, DmaLo + 32'd7));
  wire dma_top_e = `SMC_MAP_OK(DmaTop, DmaTop + 32'd7);
  wire dma_above_top_e = (rd_done && in_win(rd_addr_q, DmaHi + 32'd1, DmaHi + 32'd8))
      || (wr_done && in_win(wr_addr_q, DmaHi + 32'd1, DmaHi + 32'd8));
  wire zeroer_base_e = (rd_okay && in_win(rd_addr_q, ZeroerLo, ZeroerLo + 32'd7))
      || (wr_okay && in_win(wr_addr_q, ZeroerLo, ZeroerLo + 32'd7));
  wire zeroer_top_e = `SMC_MAP_OK(ZeroerTop, ZeroerTop + 32'd7);
  `OCAH_FCOV_COVER(c_dma_aperture_base, dma_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_aperture_top, dma_top_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_just_above_top_not_dma, dma_above_top_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_aperture_base, zeroer_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_aperture_top, zeroer_top_e, clk_smc_i, in_reset)

  // Both apertures reached within one run.
  logic dma_ok_seen_q, zeroer_ok_seen_q, dma_zeroer_both_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      dma_ok_seen_q <= 1'b0;
      zeroer_ok_seen_q <= 1'b0;
      dma_zeroer_both_q <= 1'b0;
    end else begin
      if (dma_win_ok) dma_ok_seen_q <= 1'b1;
      if (zeroer_win_ok) zeroer_ok_seen_q <= 1'b1;
      dma_zeroer_both_q <= dma_ok_seen_q && zeroer_ok_seen_q;
    end
  end
  wire zeroer_distinct_e = dma_ok_seen_q && zeroer_ok_seen_q && !dma_zeroer_both_q;
  `OCAH_FCOV_COVER(c_zeroer_distinct_from_dma_aperture, zeroer_distinct_e, clk_smc_i, in_reset)

  // All sixteen DMA stream banks read: NEXT_ID_n sits at 0x48 + 8n.
  logic [15:0] dma_bank_mask_q;
  logic dma_banks_all_q;
  logic [15:0] dma_bank_hit;
  always_comb begin
    for (int unsigned i = 0; i < 16; i++) begin
      dma_bank_hit[i] = rd_okay &&
          in_win(rd_addr_q, 32'h0003_8048 + 32'(i * 8), 32'h0003_804F + 32'(i * 8));
    end
  end
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      dma_bank_mask_q <= '0;
      dma_banks_all_q <= 1'b0;
    end else begin
      dma_bank_mask_q <= dma_bank_mask_q | dma_bank_hit;
      dma_banks_all_q <= (dma_bank_mask_q == 16'hFFFF);
    end
  end
  wire all_16_banks_e = (dma_bank_mask_q == 16'hFFFF) && !dma_banks_all_q;
  `OCAH_FCOV_COVER(c_all_16_banks_decode, all_16_banks_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Peripheral block apertures at their generated bases, each as wide as the
  // component map's `Size` column. A cell pinned by two chapters carries one
  // label per cell over the same window.
  // ------------------------------------------------------------------
  wire gpio_intf_e = `SMC_MAP_OK(GpioIntfLo,
                                 GpioIntfLo + GpioIntfStride * 32'(GpioIntfNum) - 32'd1);
  wire i3c_e = `SMC_MAP_OK(I3cLo, I3cHi);
  wire avsbus_e = `SMC_MAP_OK(AvsLo, AvsLo + 32'h0FFF);
  wire i2c_e = `SMC_MAP_OK(I2cLo, I2cLo + 32'h0FFF);
  wire uart_e = `SMC_MAP_OK(UartLo, UartLo + 32'h0FFF);
  wire efuse_map_e = `SMC_MAP_OK(EfuseMapLo, EfuseMapLo + 32'h0FFF);
  wire efuse_if_e = `SMC_MAP_OK(EfuseIfLo, EfuseIfLo + 32'h0FFF);
  wire telemetry_e = `SMC_MAP_OK(TelemetryLo, TelemetryLo + 32'h0FFF);
  wire octs_e = `SMC_MAP_OK(OctsLo, OctsLo + 32'h0FFF);
  wire dtp_ctrl_e = `SMC_MAP_OK(DtpCtrlLo, DtpCtrlLo + 32'h07FF);
  wire dfx_status_e = `SMC_MAP_OK(DfxLo, DfxLo + 32'h07FF);
  wire reset_unit_e = `SMC_MAP_OK(ResetUnitLo, ResetUnitLo + 32'h07FF);
  wire misc_wrap_e = `SMC_MAP_OK(MiscWrapLo, MiscWrapLo + 32'h07FF);
  wire cla_e = `SMC_MAP_OK(ClaLo, ClaHi);
  `OCAH_FCOV_COVER(c_gpio_interface_decode, gpio_intf_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_i3c_decode, i3c_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_i3c_region, i3c_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_avsbus_decode, avsbus_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_avsbus_aperture_decode, avsbus_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c_decode, i2c_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_uart_decode, uart_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_map_decode, efuse_map_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_if_map_decode, efuse_map_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_interface_decode, efuse_if_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_if_interface_decode, efuse_if_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_telemetry_decode, telemetry_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_octs_decode, octs_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_octs_aperture_decode, octs_e, clk_smc_i, in_reset)
`ifdef SMC_FCOV_PHASE2
  // Phase 2 (SMC_FCOV.adoc): the DTP control window is served by the DTP,
  // which smc_wrapper leaves outside the bench with its CSR port unterminated.
  `OCAH_FCOV_COVER(c_dtp_ctrl_decode, dtp_ctrl_e, clk_smc_i, in_reset)
`endif
  `OCAH_FCOV_COVER(c_dfx_status_decode, dfx_status_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_reset_unit_decode, reset_unit_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_misc_wrap_decode, misc_wrap_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_decode, cla_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_region, cla_e, clk_smc_i, in_reset)

  // Multi-instance peripherals at their generated instance stride: GPIO
  // interfaces, the I3C CSR windows and the UART log-engine wraps. Mailbox
  // pairs are 0x1000 apart (128 KiB over 32 pairs).
  wire gpio_inst0_e = `SMC_MAP_OK(GpioIntfLo, GpioIntfLo + GpioIntfStride - 32'd1);
  wire gpio_inst64_e = `SMC_MAP_OK(GpioIntfLo + GpioIntfStride * 32'(GpioIntfNum - 1),
                                   GpioIntfLo + GpioIntfStride * 32'(GpioIntfNum) - 32'd1);
  wire i3c_inst0_e = `SMC_MAP_OK(I3cLo, I3cLo + I3cStride - 32'd1);
  wire i3c_inst5_e = `SMC_MAP_OK(I3cLo + I3cStride * 32'd5, I3cLo + I3cStride * 32'd6 - 32'd1);
  wire mbx_pair0_e = `SMC_MAP_OK(32'h0001_8000, 32'h0001_8FFF);
  wire mbx_pair31_e = `SMC_MAP_OK(32'h0003_7000, 32'h0003_7FFF);
  wire uart_inst0_e = `SMC_MAP_OK(UartLo, UartLo + UartStride - 32'd1);
  wire uart_inst3_e = `SMC_MAP_OK(UartLo + UartStride * 32'd3, UartLo + UartStride * 32'd4 - 32'd1);
  `OCAH_FCOV_COVER(c_gpio_instance_0, gpio_inst0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_instance_64, gpio_inst64_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_i3c_instance_0, i3c_inst0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_i3c_instance_5, i3c_inst5_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_mailbox_pair_0, mbx_pair0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_mailbox_pair_31, mbx_pair31_e, clk_smc_i, in_reset)

  // The two halves of a pair. memmap.adoc gives the 128 KiB range and the
  // "32 inbound + 32 outbound" split but not the offset of each half inside a
  // pair; those come from the generated map (smc_addr.h
  // SMC_TOP_SMC_MAILBOX_{OUT,IN}BOUND_MAILBOX_n_BASE_ADDR), 0x50 of registers
  // at pair base + 0x0 and pair base + 0x800.
  wire mbx_ob_pair0_e = `SMC_MAP_OK(32'h0001_8000, 32'h0001_804F);
  wire mbx_ib_pair0_e = `SMC_MAP_OK(32'h0001_8800, 32'h0001_884F);
  wire mbx_ob_pair31_e = `SMC_MAP_OK(32'h0003_7000, 32'h0003_704F);
  wire mbx_ib_pair31_e = `SMC_MAP_OK(32'h0003_7800, 32'h0003_784F);
  `OCAH_FCOV_COVER(c_outbound_pair_0, mbx_ob_pair0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_inbound_pair_0, mbx_ib_pair0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_outbound_pair_31, mbx_ob_pair31_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_inbound_pair_31, mbx_ib_pair31_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_uart_instance_0, uart_inst0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_uart_instance_3, uart_inst3_e, clk_smc_i, in_reset)

  // Every I3C CSR window reached within one run.
  logic [I3cNum-1:0] i3c_inst_mask_q;
  logic i3c_inst_all_q;
  logic [I3cNum-1:0] i3c_inst_hit;
  always_comb begin
    for (int unsigned i = 0; i < I3cNum; i++) begin
      i3c_inst_hit[i] = `SMC_MAP_OK(I3cLo + I3cStride * 32'(i),
                                    I3cLo + I3cStride * 32'(i + 1) - 32'd1);
    end
  end
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      i3c_inst_mask_q <= '0;
      i3c_inst_all_q <= 1'b0;
    end else begin
      i3c_inst_mask_q <= i3c_inst_mask_q | i3c_inst_hit;
      i3c_inst_all_q <= (&i3c_inst_mask_q);
    end
  end
  wire i3c_count_6_e = (&i3c_inst_mask_q) && !i3c_inst_all_q;
  `OCAH_FCOV_COVER(c_i3c_count_6, i3c_count_6_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Fabric control block: base config, alias remap regions and filters.
  // ------------------------------------------------------------------
  wire config_reg_read_e = rd_okay && in_win(rd_addr_q, 32'h0001_0000, 32'h0001_7FFF);
  wire config_reg_write_e = wr_okay && in_win(wr_addr_q, 32'h0001_0000, 32'h0001_7FFF);
  wire alias_region_0_e = wr_okay && in_win(wr_addr_q, 32'h0001_2000, 32'h0001_201F);
  wire alias_region_7_e = wr_okay && in_win(wr_addr_q, 32'h0001_20E0, 32'h0001_20FF);
  wire local_alias_base_e = rd_okay && in_win(rd_addr_q, 32'h0000_0000, 32'h0000_0007);
  `OCAH_FCOV_COVER(c_config_reg_read, config_reg_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_config_reg_write, config_reg_write_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_alias_region_0_configured, alias_region_0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_alias_region_7_configured, alias_region_7_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_local_alias_base_reaches_local_resource, local_alias_base_e, clk_smc_i,
                   in_reset)

  // Remap transparent at its reset setting: a local-window access completing
  // OKAY while no alias region has been written yet. The sticky flag covers
  // the whole 8-region config block, so a later configured run cannot hit it.
  wire alias_cfg_write = wr_done && in_win(wr_addr_q, 32'h0001_2000, 32'h0001_20FF);
  logic alias_cfg_written_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) alias_cfg_written_seen_q <= 1'b0;
    else if (alias_cfg_write) alias_cfg_written_seen_q <= 1'b1;
  end
  wire transparent_at_reset_e = local_alias_base_e && !alias_cfg_written_seen_q;
  `OCAH_FCOV_COVER(c_transparent_at_reset, transparent_at_reset_e, clk_smc_i, in_reset)

  // GLOBAL_BASE at +0x0, LOCAL_BASE at +0x8 of the base config block. The
  // write point records the completed write; the readback point carries the
  // value that proves it had no effect.
  wire global_base_readable_e = rd_okay && in_win(rd_addr_q, 32'h0001_0000, 32'h0001_0007);
  wire local_base_reads_e = rd_okay && in_win(rd_addr_q, 32'h0001_0008, 32'h0001_000B)
      && (rd_lane == 32'hC000_0000);
  wire local_base_write_done = wr_done && in_win(wr_addr_q, 32'h0001_0008, 32'h0001_000F);
  `OCAH_FCOV_COVER(c_global_base_readable, global_base_readable_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_local_base_readonly_c0000000, local_base_reads_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_local_base_reads_c0000000, local_base_reads_e, clk_smc_i, in_reset)

  // "No effect" needs the readback after the write, not the write alone: the
  // point is the reset value still reading back once a write has landed.
  logic local_base_written_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) local_base_written_seen_q <= 1'b0;
    else if (local_base_write_done) local_base_written_seen_q <= 1'b1;
  end
  wire local_base_write_e = local_base_reads_e && local_base_written_seen_q;
  `OCAH_FCOV_COVER(c_local_base_write_has_no_effect, local_base_write_e, clk_smc_i, in_reset)

  wire base_config_read_e = rd_okay && in_win(rd_addr_q, 32'h0001_0000, 32'h0001_004B);
  wire hang_det_ctrl_e = rd_okay && (in_win(rd_addr_q, 32'h0001_0020, 32'h0001_0027)
      || in_win(rd_addr_q, 32'h0001_0030, 32'h0001_0037)
      || in_win(rd_addr_q, 32'h0001_0040, 32'h0001_0047));
  `OCAH_FCOV_COVER(c_base_config_read, base_config_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_hang_det_control_fields_present, hang_det_ctrl_e, clk_smc_i, in_reset)

  // Inbound and outbound filter entries, 32 B each.
  wire inbound_entry_0_e = (rd_okay && in_win(rd_addr_q, 32'h0001_5000, 32'h0001_501F))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_5000, 32'h0001_501F));
  wire inbound_entry_15_e = (rd_okay && in_win(rd_addr_q, 32'h0001_51E0, 32'h0001_51FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_51E0, 32'h0001_51FF));
  wire outbound_entry_0_e = (rd_okay && in_win(rd_addr_q, 32'h0001_6000, 32'h0001_601F))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_6000, 32'h0001_601F));
  wire outbound_entry_1_e = (rd_okay && in_win(rd_addr_q, 32'h0001_6020, 32'h0001_603F))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_6020, 32'h0001_603F));
  wire outbound_entry_15_e = (rd_okay && in_win(rd_addr_q, 32'h0001_61E0, 32'h0001_61FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_61E0, 32'h0001_61FF));
  `OCAH_FCOV_COVER(c_inbound_entry_0, inbound_entry_0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_inbound_entry_15, inbound_entry_15_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_outbound_entry_0, outbound_entry_0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_outbound_entry_15, outbound_entry_15_e, clk_smc_i, in_reset)

  // Two consecutive outbound entries reached: the stride, not just the ends.
  logic ob_entry0_seen_q, ob_entry1_seen_q, ob_stride_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      ob_entry0_seen_q <= 1'b0;
      ob_entry1_seen_q <= 1'b0;
      ob_stride_q <= 1'b0;
    end else begin
      if (outbound_entry_0_e) ob_entry0_seen_q <= 1'b1;
      if (outbound_entry_1_e) ob_entry1_seen_q <= 1'b1;
      ob_stride_q <= ob_entry0_seen_q && ob_entry1_seen_q;
    end
  end
  wire outbound_stride_e = ob_entry0_seen_q && ob_entry1_seen_q && !ob_stride_q;
  `OCAH_FCOV_COVER(c_outbound_entry_stride_32b, outbound_stride_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Miscellaneous wrapper: scratch at +0x0, chip config at +0x100, NDM
  // reset at +0x200, LC_STATE at +0x10C.
  // ------------------------------------------------------------------
  wire scratch_rd_ok = rd_okay && in_win(rd_addr_q, 32'h0000_2800, 32'h0000_281F);
  wire scratch_wr_ok = wr_okay && in_win(wr_addr_q, 32'h0000_2800, 32'h0000_281F);
  logic scratch_written_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) scratch_written_seen_q <= 1'b0;
    else if (scratch_wr_ok) scratch_written_seen_q <= 1'b1;
  end
  wire scratch_readback_e = scratch_rd_ok && scratch_written_seen_q;
  wire scratch_all_zeros_e = scratch_wr_ok && (wr_lane == 32'h0000_0000);
  wire scratch_all_ones_e = scratch_wr_ok && (wr_lane == 32'hFFFF_FFFF);
  `OCAH_FCOV_COVER(c_scratch_write_readback, scratch_readback_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_scratch_all_zeros, scratch_all_zeros_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_scratch_all_ones, scratch_all_ones_e, clk_smc_i, in_reset)

  wire chip_config_read_e = rd_okay && in_win(rd_addr_q, 32'h0000_2900, 32'h0000_290F);
  wire chip_config_write_e = wr_done && in_win(wr_addr_q, 32'h0000_2900, 32'h0000_290F);
  wire misc_wrap_base_e = (rd_okay && in_win(rd_addr_q, 32'h0000_2800, 32'h0000_2807))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_2800, 32'h0000_2807));
  // The top that decodes is the last register of the decoded extent; the rest
  // of the 2 KiB aperture is refused by the fabric (memmap.adoc, Address Space
  // Organization).
  wire misc_wrap_top_e = `SMC_MAP_OK(MiscWrapLast, MiscWrapLast + 32'd3);
  wire ndm_reset_block_e = (rd_okay && in_win(rd_addr_q, 32'h0000_2A00, 32'h0000_2A0B))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_2A00, 32'h0000_2A0B));
  wire lc_state_readback_e = rd_okay && in_win(rd_addr_q, 32'h0000_290C, 32'h0000_290F)
      && (rd_lane[7:0] === lc_state_i);
  `OCAH_FCOV_COVER(c_chip_config_read, chip_config_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_chip_config_write, chip_config_write_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_misc_wrap_base_decodes, misc_wrap_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_misc_wrap_top_decodes, misc_wrap_top_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_ndm_reset_block_decode, ndm_reset_block_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_lc_state_readback_matches_input, lc_state_readback_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // AXI-Lite external window: mandatory blocks with the captured straps,
  // per-pad control stride and the supplementary region. Offsets are the
  // reference placement in smc_addr.h (SMC_TOP_SMC_EXTERNAL_MANDATORY_*).
  //
  // The window belongs to the adopter: SMC routes every access in it to the
  // external AXI-Lite port and specifies nothing behind it (memmap.adoc,
  // AXI-Lite External Window). The supplementary-region block and per-pad
  // control points therefore take a completion the external port carried,
  // whatever the response; the reference integration implements none of those
  // blocks and terminates them with an error slave.
  // ------------------------------------------------------------------
  `define SMC_MAP_EXT(lo, hi) \
      ((rd_ext_done && in_win(rd_addr_q, (lo), (hi))) \
       || (wr_ext_done && in_win(wr_addr_q, (lo), (hi))))
  localparam logic [31:0] ControllerWrapLo =
      32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_CONTROLLER_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] ControllerWrapHi =
      ControllerWrapLo + 32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_CONTROLLER_WRAP_SIZE) - 32'd1;
  localparam logic [31:0] GpioExtraIntfLo =
      32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_INTF_BASE_ADDR - LocalBase);
  localparam logic [31:0] GpioExtraIntfHi =
      GpioExtraIntfLo + 32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_INTF_SIZE) - 32'd1;
  localparam logic [31:0] GpioExtraCtrlLo =
      32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] GpioExtraCtrlHi =
      GpioExtraCtrlLo + 32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_GPIO_EXTRA_CTRL_SIZE) - 32'd1;
  wire controller_wrap_e = `SMC_MAP_EXT(ControllerWrapLo, ControllerWrapHi);
  wire gpio_extra_intf_e = `SMC_MAP_EXT(GpioExtraIntfLo, GpioExtraIntfHi);
  wire gpio_extra_ctrl_e = `SMC_MAP_EXT(GpioExtraCtrlLo, GpioExtraCtrlHi);
  `OCAH_FCOV_COVER(c_controller_wrap_decode, controller_wrap_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_extra_intf_decode, gpio_extra_intf_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_extra_ctrl_decode, gpio_extra_ctrl_e, clk_smc_i, in_reset)

  // Per-pad GPIO control: the first, second and last of the array.
  localparam logic [31:0] PadStride = 32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_STRIDE);
  localparam logic [31:0] Pad0Lo = 32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR(
      0
  ) - LocalBase);
  localparam logic [31:0] Pad1Lo = 32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR(
      1
  ) - LocalBase);
  localparam logic [31:0] PadLastLo = 32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR(
      32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_NUM) - 1
  ) - LocalBase);
  wire per_pad_inst0_e = `SMC_MAP_EXT(Pad0Lo, Pad0Lo + PadStride - 32'd1);
  wire per_pad_inst1_e = `SMC_MAP_EXT(Pad1Lo, Pad1Lo + PadStride - 32'd1);
  wire per_pad_inst64_e = `SMC_MAP_EXT(PadLastLo, PadLastLo + PadStride - 32'd1);
  `OCAH_FCOV_COVER(c_per_pad_instance_0, per_pad_inst0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_per_pad_block_first, per_pad_inst0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_per_pad_instance_64, per_pad_inst64_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_per_pad_block_last, per_pad_inst64_e, clk_smc_i, in_reset)

  logic pad_inst0_seen_q, pad_inst1_seen_q, pad_stride_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      pad_inst0_seen_q <= 1'b0;
      pad_inst1_seen_q <= 1'b0;
      pad_stride_q <= 1'b0;
    end else begin
      if (per_pad_inst0_e) pad_inst0_seen_q <= 1'b1;
      if (per_pad_inst1_e) pad_inst1_seen_q <= 1'b1;
      pad_stride_q <= pad_inst0_seen_q && pad_inst1_seen_q;
    end
  end
  wire per_pad_stride_e = pad_inst0_seen_q && pad_inst1_seen_q && !pad_stride_q;
  `OCAH_FCOV_COVER(c_per_pad_stride_0x20, per_pad_stride_e, clk_smc_i, in_reset)

  localparam logic [31:0] MandatoryLo = 32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_BASE_ADDR - LocalBase);
  localparam logic [31:0] PllWrapLo =
      32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] PllWrapHi =
      PllWrapLo + 32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_SIZE) - 32'd1;
  localparam logic [31:0] PvtWrapLo =
      32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_SMC_PVT_WRAP_BASE_ADDR - LocalBase);
  localparam logic [31:0] PvtWrapHi =
      PvtWrapLo + 32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_SMC_PVT_WRAP_SIZE) - 32'd1;
  localparam logic [31:0] EfuseShimLo =
      32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] EfuseShimHi =
      EfuseShimLo + 32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_EFUSE_SHIM_CTRL_SIZE) - 32'd1;
  localparam logic [31:0] SupplementaryLo =
      32'(SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_BASE_ADDR - LocalBase);


  // The eFuse SHIM CSR at the window base, then the PLL and PVT wrappers, each
  // over its register extent. The bench answers all three OKAY.
  wire mandatory_base_e = `SMC_MAP_OK(MandatoryLo, MandatoryLo + 32'd7);
  wire efuse_shim_e = `SMC_MAP_OK(EfuseShimLo, EfuseShimHi);
  wire pll_wrapper_e = `SMC_MAP_OK(PllWrapLo, PllWrapHi);
  wire pvt_wrapper_e = `SMC_MAP_OK(PvtWrapLo, PvtWrapHi);
  // The supplementary region holds the adopter's own devices, so a completion
  // there is the terminator's rather than a device's. The point takes a
  // completed access that the external port carried.
  wire supplementary_base_e = `SMC_MAP_EXT(SupplementaryLo, SupplementaryLo + 32'd7);
  `OCAH_FCOV_COVER(c_mandatory_region_base_decodes, mandatory_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pll_wrapper_decodes, pll_wrapper_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pvt_wrapper_decode, pvt_wrapper_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pvt_wrapper_decodes, pvt_wrapper_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_shim_decodes, efuse_shim_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_supplementary_region_base_decodes, supplementary_base_e, clk_smc_i, in_reset)

  // Captured straps, read-only.
  localparam logic [31:0] StrapsLoLo =
      32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_LO_BASE_ADDR - LocalBase);
  localparam logic [31:0] StrapsHiLo =
      32'(SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_STRAPS_HI_BASE_ADDR - LocalBase);
  wire straps_lo_read_e = rd_okay && in_win(rd_addr_q, StrapsLoLo, StrapsLoLo + 32'd3);
  wire straps_hi_read_e = rd_okay && in_win(rd_addr_q, StrapsHiLo, StrapsHiLo + 32'd3);
  wire strap_write_done = wr_done && in_win(wr_addr_q, StrapsLoLo, StrapsHiLo + 32'd3);
  `OCAH_FCOV_COVER(c_straps_lo_read, straps_lo_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_straps_lo_decodes, straps_lo_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_straps_hi_read, straps_hi_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_straps_hi_decodes, straps_hi_read_e, clk_smc_i, in_reset)

  // STRAPS_LO before any write to the strap words, and the same value still
  // reading back after one landed. The pre-write read is what makes the
  // second read evidence of no effect rather than evidence of a read.
  logic [31:0] straps_lo_pre_q;
  logic straps_lo_pre_valid_q, strap_written_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      straps_lo_pre_q <= '0;
      straps_lo_pre_valid_q <= 1'b0;
      strap_written_seen_q <= 1'b0;
    end else begin
      if (straps_lo_read_e && !strap_written_seen_q) begin
        straps_lo_pre_q <= rd_lane;
        straps_lo_pre_valid_q <= 1'b1;
      end
      if (strap_write_done) strap_written_seen_q <= 1'b1;
    end
  end
  wire strap_write_e = straps_lo_read_e && strap_written_seen_q && straps_lo_pre_valid_q
      && (rd_lane == straps_lo_pre_q);
  `OCAH_FCOV_COVER(c_strap_write_has_no_effect, strap_write_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Windows above the reset REGION_SIZE. smc_local_fabric replaces the
  // address bits above REGION_SIZE with LOCAL_BASE, so an access presented
  // at the PLIC or CLINT offset aliases onto the bottom of the local window
  // and completes from the watchdog rule while REGION_SIZE is its 16 MiB
  // reset value. Each point below therefore qualifies on the offset still
  // being inside the programmed size, which is what makes the completion
  // evidence of reaching that window rather than of the fold.
  // ------------------------------------------------------------------
  wire region_size_known = (^region_size_i !== 1'bx);
  wire rd_unfolded = region_size_known && (rd_addr_q >= LocalBase)
      && ((rd_addr_q - LocalBase) < 56'(region_size_i));
  wire wr_unfolded = region_size_known && (wr_addr_q >= LocalBase)
      && ((wr_addr_q - LocalBase) < 56'(region_size_i));
  wire rd_okay_far = rd_okay && rd_unfolded;
  wire wr_okay_far = wr_okay && wr_unfolded;
  wire rd_done_far = rd_done && rd_unfolded;
  wire wr_done_far = wr_done && wr_unfolded;

  // PLIC, 64 MiB aperture at offset 0x400_0000. Its top is the last word of
  // the decoded extent, and anything above that inside the aperture is
  // refused.
  wire plic_region_e = (rd_okay_far && in_win(rd_addr_q, PlicLo, PlicHi))
      || (wr_okay_far && in_win(wr_addr_q, PlicLo, PlicHi));
  wire plic_base_e = (rd_okay_far && in_win(rd_addr_q, PlicLo, PlicLo + 32'd7))
      || (wr_okay_far && in_win(wr_addr_q, PlicLo, PlicLo + 32'd7));
  wire plic_top_e = (rd_okay_far && in_win(rd_addr_q, PlicTop, PlicTop + 32'd7))
      || (wr_okay_far && in_win(wr_addr_q, PlicTop, PlicTop + 32'd7));
  wire plic_above_e = (rd_done_far && in_win(rd_addr_q, PlicEnd, PlicHi))
      || (wr_done_far && in_win(wr_addr_q, PlicEnd, PlicHi));
  `OCAH_FCOV_COVER(c_plic_region, plic_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_plic_base_access, plic_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_plic_top_access, plic_top_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_just_above_plic_not_plic, plic_above_e, clk_smc_i, in_reset)

  // PLIC software initialisation: interrupts.adoc requires firmware to write
  // priority 0 and disabled to every source before enabling external
  // interrupts. The register offsets inside the PLIC window are the generated
  // map's (smc_addr.h SMC_TOP_SMC_CLUSTER_PLIC_PRIORITY / _COREn_MEIP_ENABLE):
  // 337 priority words at +0x0 and eleven enable words per core from +0x2000.
  wire plic_prio_win_rd = rd_okay_far && in_win(rd_addr_q, 32'h0400_0000, 32'h0400_0543);
  wire plic_prio_win_wr = wr_okay_far && in_win(wr_addr_q, 32'h0400_0000, 32'h0400_0543);
  wire plic_en_win_rd = rd_okay_far && in_win(rd_addr_q, 32'h0400_2000, 32'h0400_23FF);
  wire plic_en_win_wr = wr_okay_far && in_win(wr_addr_q, 32'h0400_2000, 32'h0400_23FF);
  wire plic_prio_zero_e = plic_prio_win_wr && (wr_lane == 32'h0000_0000);
  wire plic_en_disabled_e = plic_en_win_wr && (wr_lane == 32'h0000_0000);
  logic plic_zero_written_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) plic_zero_written_seen_q <= 1'b0;
    else if (plic_prio_zero_e || plic_en_disabled_e) plic_zero_written_seen_q <= 1'b1;
  end
  wire plic_readback_e = (plic_prio_win_rd || plic_en_win_rd) && plic_zero_written_seen_q
      && (rd_lane == 32'h0000_0000);
  `OCAH_FCOV_COVER(c_priority_written_to_zero, plic_prio_zero_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_enables_written_to_disabled, plic_en_disabled_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_readback_matches, plic_readback_e, clk_smc_i, in_reset)

  // CLINT, 64 KiB at offset 0x800_0000 with its top at the end of the decoded
  // extent, and the 80 KiB timer / bus-error region that holds it together
  // with the four bus-error units.
  wire clint_base_e = (rd_okay_far && in_win(rd_addr_q, 32'h0800_0000, 32'h0800_0007))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0800_0000, 32'h0800_0007));
  wire clint_top_e = (rd_okay_far && in_win(rd_addr_q, ClintTop, ClintTop + 32'd7))
      || (wr_okay_far && in_win(wr_addr_q, ClintTop, ClintTop + 32'd7));
  wire clint_above_e = (rd_done_far && in_win(rd_addr_q, 32'h0801_0000, 32'h0801_0007))
      || (wr_done_far && in_win(wr_addr_q, 32'h0801_0000, 32'h0801_0007));
  wire timer_buserror_region_e = (rd_okay_far && in_win(rd_addr_q, 32'h0800_0000, 32'h0801_3FFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0800_0000, 32'h0801_3FFF));
  `OCAH_FCOV_COVER(c_clint_base_access, clint_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_clint_top_access, clint_top_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_just_above_clint_not_clint, clint_above_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_timer_buserror_region, timer_buserror_region_e, clk_smc_i, in_reset)

  // Bus-error units, 4 KiB each at offset 0x801_0000 + N * 0x1000.
  wire beu0_e = (rd_okay_far && in_win(rd_addr_q, 32'h0801_0000, 32'h0801_0FFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0801_0000, 32'h0801_0FFF));
  wire beu1_e = (rd_okay_far && in_win(rd_addr_q, 32'h0801_1000, 32'h0801_1FFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0801_1000, 32'h0801_1FFF));
  wire beu2_e = (rd_okay_far && in_win(rd_addr_q, 32'h0801_2000, 32'h0801_2FFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0801_2000, 32'h0801_2FFF));
  wire beu3_e = (rd_okay_far && in_win(rd_addr_q, 32'h0801_3000, 32'h0801_3FFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0801_3000, 32'h0801_3FFF));
  `OCAH_FCOV_COVER(c_beu0_decode, beu0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_beu1_decode, beu1_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_beu2_decode, beu2_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_beu3_decode, beu3_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_beu_instance_3, beu3_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Address-space layout regions inside the 16 MiB reset aperture, from the
  // functional-organization table of the generated memory map. Its "System
  // and Peripheral Control" row is split into the four component groups the
  // component table lists under it: reset and misc control, the GPIO
  // interfaces, the serial controllers, and the eFuse / telemetry / timer /
  // DTP / DFT blocks. The PLIC and core-local rows lie above the reset
  // aperture and have their own points below.
  // ------------------------------------------------------------------
  localparam int unsigned NumRegions = 13;
  localparam logic [31:0] RegionLo[NumRegions] = '{
      32'h0000_0000,
      ResetUnitLo,
      GpioIntfLo,
      AvsLo,
      EfuseMapLo,
      32'h0001_0000,
      32'(SMC_TOP_SMC_MAILBOX_BASE_ADDR - LocalBase),
      DmaLo,
      32'(SMC_TOP_SMC_CPU_CTRL_BASE_ADDR - LocalBase),
      RomLo,
      ClaLo,
      32'(SMC_TOP_SMC_EXTERNAL_BASE_ADDR - LocalBase),
      32'(SMC_TOP_MMODE_REGION_BASE_ADDR - LocalBase)
  };
  localparam logic [31:0] RegionHi[NumRegions] = '{
      32'h0000_0FFF,
      MiscWrapLo + 32'h07FF,
      GpioIntfLo + 32'h0FFF,
      UartLo + 32'h0FFF,
      DfxLo + 32'h07FF,
      32'h0001_6FFF,
      32'h0003_7FFF,
      ZeroerHi,
      I3cHi,
      SpmHi,
      ClaHi,
      32'(SMC_TOP_SMC_EXTERNAL_BASE_ADDR - LocalBase) + 32'(SMC_TOP_SMC_EXTERNAL_SIZE) - 32'd1,
      32'(SMC_TOP_XVISOR_REGION_BASE_ADDR - LocalBase) + 32'(SMC_TOP_XVISOR_REGION_SIZE) - 32'd1
  };

  logic [NumRegions-1:0] region_ok, region_base_ok, region_top_ok, region_beyond_done;
  always_comb begin
    for (int unsigned i = 0; i < NumRegions; i++) begin
      region_ok[i] = (rd_okay && in_win(rd_addr_q, RegionLo[i], RegionHi[i]))
          || (wr_okay && in_win(wr_addr_q, RegionLo[i], RegionHi[i]));
      region_base_ok[i] = (rd_okay && in_win(rd_addr_q, RegionLo[i], RegionLo[i] + 32'd7))
          || (wr_okay && in_win(wr_addr_q, RegionLo[i], RegionLo[i] + 32'd7));
      region_top_ok[i] = (rd_okay && in_win(rd_addr_q, RegionHi[i] - 32'd7, RegionHi[i]))
          || (wr_okay && in_win(wr_addr_q, RegionHi[i] - 32'd7, RegionHi[i]));
      region_beyond_done[i] = (rd_done && in_win(rd_addr_q, RegionHi[i] + 32'd1,
                                                 RegionHi[i] + 32'd8))
          || (wr_done && in_win(wr_addr_q, RegionHi[i] + 32'd1, RegionHi[i] + 32'd8));
    end
  end

  wire wdt_region_e = region_ok[0];
  wire system_control_region_e = region_ok[1];
  wire gpio_region_e = region_ok[2];
  wire peripheral_region_e = region_ok[3];
  wire security_timing_dft_region_e = region_ok[4];
  wire fabric_control_region_e = region_ok[5];
  wire mailbox_region_e = region_ok[6];
  wire data_processing_region_e = region_ok[7];
  wire memory_region_e = region_ok[9];
  wire axil_external_region_e = region_ok[11];
  `OCAH_FCOV_COVER(c_wdt_region, wdt_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_system_control_region, system_control_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_region, gpio_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_peripheral_region, peripheral_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_security_timing_dft_region, security_timing_dft_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_fabric_control_region, fabric_control_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_mailbox_region, mailbox_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_data_processing_region, data_processing_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_memory_region, memory_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axil_external_region, axil_external_region_e, clk_smc_i, in_reset)

  // The address-remapping row serves the managers whose traffic passes the
  // output fabric's remap stages (fabric.adoc, SMC Fabric Traffic Managers:
  // DMA, JTAG2AXI, log engine, CPU external path). SEP_IN enters the local
  // fabric directly, so the point takes the JTAG manager's completions,
  // attributed with the same single-outstanding rule as SEP_IN.
  wire jtag_aw_acc = (jtag_awvalid_i === 1'b1) && (jtag_awready_i === 1'b1);
  wire jtag_ar_acc = (jtag_arvalid_i === 1'b1) && (jtag_arready_i === 1'b1);
  wire jtag_b_done_acc = (jtag_bvalid_i === 1'b1) && (jtag_bready_i === 1'b1);
  wire jtag_r_done_acc = (jtag_rvalid_i === 1'b1) && (jtag_rready_i === 1'b1)
      && (jtag_rlast_i === 1'b1);
  logic [7:0] jtag_rd_out_q, jtag_wr_out_q;
  logic jtag_rd_single_q, jtag_wr_single_q;
  logic [55:0] jtag_rd_addr_q, jtag_wr_addr_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      jtag_rd_out_q <= '0;
      jtag_wr_out_q <= '0;
      jtag_rd_single_q <= 1'b0;
      jtag_wr_single_q <= 1'b0;
      jtag_rd_addr_q <= '0;
      jtag_wr_addr_q <= '0;
    end else begin
      jtag_rd_out_q <= jtag_rd_out_q + 8'(jtag_ar_acc) - 8'(jtag_r_done_acc);
      jtag_wr_out_q <= jtag_wr_out_q + 8'(jtag_aw_acc) - 8'(jtag_b_done_acc);
      if (jtag_ar_acc) begin
        jtag_rd_addr_q <= jtag_araddr_i;
        jtag_rd_single_q <= (jtag_rd_out_q == 8'd0)
            || ((jtag_rd_out_q == 8'd1) && jtag_r_done_acc);
      end
      if (jtag_aw_acc) begin
        jtag_wr_addr_q <= jtag_awaddr_i;
        jtag_wr_single_q <= (jtag_wr_out_q == 8'd0)
            || ((jtag_wr_out_q == 8'd1) && jtag_b_done_acc);
      end
    end
  end
  wire jtag_rd_okay = jtag_r_done_acc && (jtag_rd_out_q == 8'd1) && jtag_rd_single_q
      && (jtag_rresp_i == RespOkay);
  wire jtag_wr_okay = jtag_b_done_acc && (jtag_wr_out_q == 8'd1) && jtag_wr_single_q
      && (jtag_bresp_i == RespOkay);
  wire remap_region_e =
      (jtag_rd_okay && in_win(jtag_rd_addr_q, RegionLo[12], RegionHi[12]))
      || (jtag_wr_okay && in_win(jtag_wr_addr_q, RegionLo[12], RegionHi[12]));
  `OCAH_FCOV_COVER(c_remap_region, remap_region_e, clk_smc_i, in_reset)

  // Region edges: the first and last word of any region completing OKAY, and
  // a completed access to the first word beyond any region top. For a region
  // with a mapped neighbour that access legitimately completes OKAY, so the
  // point records the completion and the checker judges the responder.
  wire region_base_decodes_e = (region_base_ok != '0);
  wire region_top_decodes_e = (region_top_ok != '0);
  wire beyond_region_e = (region_beyond_done != '0);
  `OCAH_FCOV_COVER(c_region_base_decodes, region_base_decodes_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_region_top_decodes, region_top_decodes_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_beyond_region_does_not, beyond_region_e, clk_smc_i, in_reset)

  wire cla_base_e = region_base_ok[10];
  wire cla_top_e = region_top_ok[10];
  `OCAH_FCOV_COVER(c_cla_base_decodes, cla_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_top_decodes, cla_top_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // External manager completions. The per-channel points in
  // smc_axi_chan_fcov share one label across its three instances, so the
  // manager-named points live here.
  // ------------------------------------------------------------------
  wire sys_b_acc = (sys_bvalid_i === 1'b1) && (sys_bready_i === 1'b1);
  wire sys_r_last_acc = (sys_rvalid_i === 1'b1) && (sys_rready_i === 1'b1)
      && (sys_rlast_i === 1'b1);
  wire jtag_b_acc = (jtag_bvalid_i === 1'b1) && (jtag_bready_i === 1'b1);
  wire jtag_r_last_acc = (jtag_rvalid_i === 1'b1) && (jtag_rready_i === 1'b1)
      && (jtag_rlast_i === 1'b1);
  `OCAH_FCOV_COVER(c_sep_axi_in_read, r_last_acc, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_axi_in_write, b_acc, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_axi_in_read, sys_r_last_acc, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_axi_in_write, sys_b_acc, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_jtag_axi_in_read, jtag_r_last_acc, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_jtag_axi_in_write, jtag_b_acc, clk_smc_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the attributed completion against the
  // layout region and response code, which the flat list cannot cross.
  // ------------------------------------------------------------------
  localparam logic [NumRegions-1:0] RegionMemory = NumRegions'(1) << 9;
  localparam logic [NumRegions-1:0] RegionCla = NumRegions'(1) << 10;
  localparam logic [NumRegions-1:0] RegionRemap = NumRegions'(1) << 12;

  covergroup cg_map_access with function sample (
      logic [NumRegions-1:0] region, logic is_write, logic [1:0] resp
  );
    option.per_instance = 1;
    cp_region: coverpoint region {
      bins regions[] = {
        13'b0_0000_0000_0001, 13'b0_0000_0000_0010, 13'b0_0000_0000_0100,
        13'b0_0000_0000_1000, 13'b0_0000_0001_0000, 13'b0_0000_0010_0000,
        13'b0_0000_0100_0000, 13'b0_0000_1000_0000, 13'b0_0001_0000_0000,
        13'b0_0010_0000_0000, 13'b0_0100_0000_0000, 13'b0_1000_0000_0000,
        13'b1_0000_0000_0000
      };
      bins unmapped = {13'b0};
    }
    cp_dir: coverpoint is_write;
    // memmap.adoc says the fabric refuses an address between unit apertures
    // or past a unit's decoded extent, and fabric.adoc names an error slave
    // for invalid addresses; neither fixes which error code a refusal
    // carries, so the bins are a completion and a refusal. EXOKAY answers an
    // exclusive access, and no manager on this bench issues one (the
    // per-manager channel points record the same fact).
    cp_resp: coverpoint resp {
      bins okay = {2'b00}; bins error = {2'b10, 2'b11}; ignore_bins exokay = {2'b01};
    }
    // Per-region facts:
    // * CLA: the unit's decoded extent fills the region (memory_map.adoc,
    //   smc_cla 16 KiB of 16 KiB), so no address in it is refused.
    // * Address remapping: the remap stages serve the DMA, JTAG2AXI, log
    //   engine and CPU external-path managers (fabric.adoc, SMC Fabric Traffic
    //   Managers). This group samples SEP_IN, which the fabric refuses there.
    // * Local memories: the ROM and scratchpad fill the region, so a read is
    //   refused only for an uncorrectable ECC error, which needs fault
    //   injection and is in the Phase 2 set (SMC_FCOV.adoc).
    x_region_resp: cross cp_region, cp_dir, cp_resp{
      ignore_bins cla_fills_region = binsof (cp_region) intersect {RegionCla} &&
          binsof (cp_resp.error);
      ignore_bins sep_in_not_remapped = binsof (cp_region) intersect {RegionRemap} &&
          binsof (cp_resp.okay);
      ignore_bins memory_read_refused = binsof (cp_region) intersect {RegionMemory} &&
          binsof (cp_dir) intersect {1'b0} && binsof (cp_resp.error);
    }
  endgroup

  cg_map_access u_cg_map_access = new();

  logic [NumRegions-1:0] rd_region_hit, wr_region_hit;
  always_comb begin
    for (int unsigned i = 0; i < NumRegions; i++) begin
      rd_region_hit[i] = in_win(rd_addr_q, RegionLo[i], RegionHi[i]);
      wr_region_hit[i] = in_win(wr_addr_q, RegionLo[i], RegionHi[i]);
    end
  end

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      if (rd_done) u_cg_map_access.sample(rd_region_hit, 1'b0, sep_rresp_i);
      if (wr_done) u_cg_map_access.sample(wr_region_hit, 1'b1, sep_bresp_i);
    end
  end
`endif

  `undef SMC_MAP_OK
  `undef SMC_MAP_EXT

endmodule : smc_map_fcov
