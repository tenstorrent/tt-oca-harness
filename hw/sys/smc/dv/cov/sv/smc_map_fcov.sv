// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC address-map functional coverage on the SEP_IN AXI manager: which
// spec-mapped apertures the suite reached and completed, plus the external
// managers' read/write completions.
//
// Every window below is a `BASE + offset` with BASE the local alias
// 0xC000_0000. The memory and data-processing windows take their bounds from
// the generated address map (smc_top_addrmap_pkg, the same source the
// window-top decode test reads); the remaining region rows are the memmap
// chapter's layout table. A cell is hit when a transaction to the window
// completed, not when its address was merely presented.
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

  // SYS_IN and JTAG inbound managers: completion handshakes only.
  input wire sys_bvalid_i,
  input wire sys_bready_i,
  input wire sys_rvalid_i,
  input wire sys_rready_i,
  input wire sys_rlast_i,
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
  // is its size; a register block's window is the aperture the memory map
  // gives it (smc.rdl `ocah_aperture_size`), which the package does not carry,
  // so the two apertures are stated here beside the base they extend.
  localparam logic [31:0] RomLo = 32'(SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR - LocalBase);
  localparam logic [31:0] RomHi = RomLo + 32'(SMC_TOP_SPM_ROM_MEMORY_SIZE) - 32'd1;
  localparam logic [31:0] SpmLo = 32'(SMC_TOP_SPM_MEMORY_BASE_ADDR - LocalBase);
  localparam logic [31:0] SpmHi = SpmLo + 32'(SMC_TOP_SPM_MEMORY_SIZE) - 32'd1;
  localparam logic [31:0] DmaLo = 32'(SMC_TOP_DMA_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] DmaHi = DmaLo + 32'h200 - 32'd1;
  localparam logic [31:0] ZeroerLo = 32'(SMC_TOP_ZEROER_CTRL_BASE_ADDR - LocalBase);
  localparam logic [31:0] ZeroerHi = ZeroerLo + 32'h100 - 32'd1;
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
  wire dma_top_e = (rd_okay && in_win(rd_addr_q, DmaHi - 32'd7, DmaHi))
      || (wr_okay && in_win(wr_addr_q, DmaHi - 32'd7, DmaHi));
  wire dma_above_top_e = (rd_done && in_win(rd_addr_q, DmaHi + 32'd1, DmaHi + 32'd8))
      || (wr_done && in_win(wr_addr_q, DmaHi + 32'd1, DmaHi + 32'd8));
  wire zeroer_base_e = (rd_okay && in_win(rd_addr_q, ZeroerLo, ZeroerLo + 32'd7))
      || (wr_okay && in_win(wr_addr_q, ZeroerLo, ZeroerLo + 32'd7));
  wire zeroer_top_e = (rd_okay && in_win(rd_addr_q, ZeroerHi - 32'd7, ZeroerHi))
      || (wr_okay && in_win(wr_addr_q, ZeroerHi - 32'd7, ZeroerHi));
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
  // Peripheral block apertures at their mapped base offsets. A cell pinned
  // by two chapters carries one label per cell over the same window.
  // ------------------------------------------------------------------
  wire gpio_intf_e = (rd_okay && in_win(rd_addr_q, 32'h0000_3000, 32'h0000_340F))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_3000, 32'h0000_340F));
  wire i3c_e = (rd_okay && in_win(rd_addr_q, 32'h0000_4000, 32'h0000_5FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_4000, 32'h0000_5FFF));
  wire avsbus_e = (rd_okay && in_win(rd_addr_q, 32'h0000_6000, 32'h0000_6FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_6000, 32'h0000_6FFF));
  wire i2c_e = (rd_okay && in_win(rd_addr_q, 32'h0000_7000, 32'h0000_7FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_7000, 32'h0000_7FFF));
  wire uart_e = (rd_okay && in_win(rd_addr_q, 32'h0000_8000, 32'h0000_8FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_8000, 32'h0000_8FFF));
  wire efuse_map_e = (rd_okay && in_win(rd_addr_q, 32'h0000_9000, 32'h0000_9FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_9000, 32'h0000_9FFF));
  wire efuse_if_e = (rd_okay && in_win(rd_addr_q, 32'h0000_A000, 32'h0000_AFFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_A000, 32'h0000_AFFF));
  wire telemetry_e = (rd_okay && in_win(rd_addr_q, 32'h0000_B000, 32'h0000_BFFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_B000, 32'h0000_BFFF));
  wire octs_e = (rd_okay && in_win(rd_addr_q, 32'h0000_C000, 32'h0000_CFFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_C000, 32'h0000_CFFF));
  wire dtp_ctrl_e = (rd_okay && in_win(rd_addr_q, 32'h0000_D000, 32'h0000_D7FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_D000, 32'h0000_D7FF));
  wire dfx_status_e = (rd_okay && in_win(rd_addr_q, 32'h0000_D800, 32'h0000_DFFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_D800, 32'h0000_DFFF));
  wire reset_unit_e = (rd_okay && in_win(rd_addr_q, 32'h0000_2000, 32'h0000_27FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_2000, 32'h0000_27FF));
  wire misc_wrap_e = (rd_okay && in_win(rd_addr_q, 32'h0000_2800, 32'h0000_2FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_2800, 32'h0000_2FFF));
  wire cla_e = (rd_okay && in_win(rd_addr_q, 32'h0016_0000, 32'h0016_8FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0016_0000, 32'h0016_8FFF));
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
  `OCAH_FCOV_COVER(c_dtp_ctrl_decode, dtp_ctrl_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dfx_status_decode, dfx_status_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_reset_unit_decode, reset_unit_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_misc_wrap_decode, misc_wrap_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_decode, cla_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_cla_region, cla_e, clk_smc_i, in_reset)

  // Multi-instance peripherals at their instance stride: GPIO 0x10, I3C
  // 0x500, mailbox pairs 0x1000 (128 KiB over 32 pairs), UART 0x400 (4 KiB
  // over 4 instances).
  wire gpio_inst0_e = (rd_okay && in_win(rd_addr_q, 32'h0000_3000, 32'h0000_300F))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_3000, 32'h0000_300F));
  wire gpio_inst64_e = (rd_okay && in_win(rd_addr_q, 32'h0000_3400, 32'h0000_340F))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_3400, 32'h0000_340F));
  wire i3c_inst0_e = (rd_okay && in_win(rd_addr_q, 32'h0000_4000, 32'h0000_44FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_4000, 32'h0000_44FF));
  wire i3c_inst5_e = (rd_okay && in_win(rd_addr_q, 32'h0000_5900, 32'h0000_5DFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_5900, 32'h0000_5DFF));
  wire mbx_pair0_e = (rd_okay && in_win(rd_addr_q, 32'h0001_8000, 32'h0001_8FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_8000, 32'h0001_8FFF));
  wire mbx_pair31_e = (rd_okay && in_win(rd_addr_q, 32'h0003_7000, 32'h0003_7FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0003_7000, 32'h0003_7FFF));
  wire uart_inst0_e = (rd_okay && in_win(rd_addr_q, 32'h0000_8000, 32'h0000_83FF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_8000, 32'h0000_83FF));
  wire uart_inst3_e = (rd_okay && in_win(rd_addr_q, 32'h0000_8C00, 32'h0000_8FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_8C00, 32'h0000_8FFF));
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
  wire mbx_ob_pair0_e = (rd_okay && in_win(rd_addr_q, 32'h0001_8000, 32'h0001_804F))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_8000, 32'h0001_804F));
  wire mbx_ib_pair0_e = (rd_okay && in_win(rd_addr_q, 32'h0001_8800, 32'h0001_884F))
      || (wr_okay && in_win(wr_addr_q, 32'h0001_8800, 32'h0001_884F));
  wire mbx_ob_pair31_e = (rd_okay && in_win(rd_addr_q, 32'h0003_7000, 32'h0003_704F))
      || (wr_okay && in_win(wr_addr_q, 32'h0003_7000, 32'h0003_704F));
  wire mbx_ib_pair31_e = (rd_okay && in_win(rd_addr_q, 32'h0003_7800, 32'h0003_784F))
      || (wr_okay && in_win(wr_addr_q, 32'h0003_7800, 32'h0003_784F));
  `OCAH_FCOV_COVER(c_outbound_pair_0, mbx_ob_pair0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_inbound_pair_0, mbx_ib_pair0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_outbound_pair_31, mbx_ob_pair31_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_inbound_pair_31, mbx_ib_pair31_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_uart_instance_0, uart_inst0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_uart_instance_3, uart_inst3_e, clk_smc_i, in_reset)

  // All six I3C instance windows reached within one run.
  logic [5:0] i3c_inst_mask_q;
  logic i3c_inst_all_q;
  logic [5:0] i3c_inst_hit;
  always_comb begin
    for (int unsigned i = 0; i < 6; i++) begin
      i3c_inst_hit[i] = (rd_okay && in_win(rd_addr_q, 32'h0000_4000 + 32'(i * 32'h500),
                                           32'h0000_44FF + 32'(i * 32'h500))) ||
          (wr_okay &&
           in_win(wr_addr_q, 32'h0000_4000 + 32'(i * 32'h500), 32'h0000_44FF + 32'(i * 32'h500)));
    end
  end
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      i3c_inst_mask_q <= '0;
      i3c_inst_all_q <= 1'b0;
    end else begin
      i3c_inst_mask_q <= i3c_inst_mask_q | i3c_inst_hit;
      i3c_inst_all_q <= (i3c_inst_mask_q == 6'h3F);
    end
  end
  wire i3c_count_6_e = (i3c_inst_mask_q == 6'h3F) && !i3c_inst_all_q;
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
  wire misc_wrap_top_e = (rd_okay && in_win(rd_addr_q, 32'h0000_2FF8, 32'h0000_2FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0000_2FF8, 32'h0000_2FFF));
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
  // AXI-Lite external window: mandatory blocks, per-pad control stride and
  // the supplementary region with the captured straps.
  // ------------------------------------------------------------------
  wire pll_obs_intf_e = (rd_okay && in_win(rd_addr_q, 32'h0040_0000, 32'h0040_000B))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_0000, 32'h0040_000B));
  wire pll_obs_ctrl_e = (rd_okay && in_win(rd_addr_q, 32'h0040_000C, 32'h0040_000F))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_000C, 32'h0040_000F));
  wire pvt_obs_intf_e = (rd_okay && in_win(rd_addr_q, 32'h0040_0010, 32'h0040_001B))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_0010, 32'h0040_001B));
  wire pvt_obs_ctrl_e = (rd_okay && in_win(rd_addr_q, 32'h0040_001C, 32'h0040_001F))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_001C, 32'h0040_001F));
  wire gpio_poc_pbias_e = (rd_okay && in_win(rd_addr_q, 32'h0040_0020, 32'h0040_002B))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_0020, 32'h0040_002B));
  wire gpio_refclk_ctrl_e = (rd_okay && in_win(rd_addr_q, 32'h0040_002C, 32'h0040_002F))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_002C, 32'h0040_002F));
  `OCAH_FCOV_COVER(c_pll_obs_intf_decode, pll_obs_intf_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pll_obs_ctrl_decode, pll_obs_ctrl_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pvt_obs_intf_decode, pvt_obs_intf_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pvt_obs_ctrl_decode, pvt_obs_ctrl_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_poc_pbias_decode, gpio_poc_pbias_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_refclk_ctrl_decode, gpio_refclk_ctrl_e, clk_smc_i, in_reset)

  wire per_pad_inst0_e = (rd_okay && in_win(rd_addr_q, 32'h0040_0100, 32'h0040_011F))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_0100, 32'h0040_011F));
  wire per_pad_inst1_e = (rd_okay && in_win(rd_addr_q, 32'h0040_0120, 32'h0040_013F))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_0120, 32'h0040_013F));
  wire per_pad_inst64_e = (rd_okay && in_win(rd_addr_q, 32'h0040_0900, 32'h0040_091F))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_0900, 32'h0040_091F));
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

  wire mandatory_base_e = (rd_okay && in_win(rd_addr_q, 32'h0040_0000, 32'h0040_0007))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_0000, 32'h0040_0007));
  wire pll_wrapper_e = (rd_okay && in_win(rd_addr_q, 32'h0040_1000, 32'h0040_1FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_1000, 32'h0040_1FFF));
  wire pvt_wrapper_e = (rd_okay && in_win(rd_addr_q, 32'h0040_2000, 32'h0040_2FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_2000, 32'h0040_2FFF));
  wire efuse_shim_e = (rd_okay && in_win(rd_addr_q, 32'h0040_3000, 32'h0040_3FFF))
      || (wr_okay && in_win(wr_addr_q, 32'h0040_3000, 32'h0040_3FFF));
  // The supplementary region holds the adopter's own devices, so a completion
  // there is the terminator's rather than a device's. The point takes a
  // completed access that the external port carried.
  wire supplementary_base_e = (rd_ext_done && in_win(rd_addr_q, 32'h0040_4000, 32'h0040_4007))
      || (wr_ext_done && in_win(wr_addr_q, 32'h0040_4000, 32'h0040_4007));
  `OCAH_FCOV_COVER(c_mandatory_region_base_decodes, mandatory_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pll_wrapper_decodes, pll_wrapper_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pvt_wrapper_decode, pvt_wrapper_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_pvt_wrapper_decodes, pvt_wrapper_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_shim_decodes, efuse_shim_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_supplementary_region_base_decodes, supplementary_base_e, clk_smc_i, in_reset)

  // Captured straps, read-only: STRAPS_LO at +0x5800, STRAPS_HI at +0x5804.
  wire straps_lo_read_e = rd_okay && in_win(rd_addr_q, 32'h0040_5800, 32'h0040_5803);
  wire straps_hi_read_e = rd_okay && in_win(rd_addr_q, 32'h0040_5804, 32'h0040_5807);
  wire strap_write_done = wr_done && in_win(wr_addr_q, 32'h0040_5800, 32'h0040_5807);
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

  // PLIC, 4 MiB at offset 0x400_0000.
  wire plic_region_e = (rd_okay_far && in_win(rd_addr_q, 32'h0400_0000, 32'h043F_FFFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0400_0000, 32'h043F_FFFF));
  wire plic_base_e = (rd_okay_far && in_win(rd_addr_q, 32'h0400_0000, 32'h0400_0007))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0400_0000, 32'h0400_0007));
  wire plic_top_e = (rd_okay_far && in_win(rd_addr_q, 32'h043F_FFF8, 32'h043F_FFFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h043F_FFF8, 32'h043F_FFFF));
  wire plic_above_e = (rd_done_far && in_win(rd_addr_q, 32'h0440_0000, 32'h0440_0007))
      || (wr_done_far && in_win(wr_addr_q, 32'h0440_0000, 32'h0440_0007));
  `OCAH_FCOV_COVER(c_plic_region, plic_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_plic_base_access, plic_base_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_plic_top_access, plic_top_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_just_above_plic_not_plic, plic_above_e, clk_smc_i, in_reset)

  // PLIC software initialisation: interrupts.adoc requires firmware to write
  // priority 0 and disabled to every source before enabling external
  // interrupts. The register offsets inside the 4 MiB window are the generated
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

  // CLINT, 64 KiB at offset 0x800_0000, and the 80 KiB timer / bus-error
  // region that holds it together with the four bus-error units.
  wire clint_base_e = (rd_okay_far && in_win(rd_addr_q, 32'h0800_0000, 32'h0800_0007))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0800_0000, 32'h0800_0007));
  wire clint_top_e = (rd_okay_far && in_win(rd_addr_q, 32'h0800_FFF8, 32'h0800_FFFF))
      || (wr_okay_far && in_win(wr_addr_q, 32'h0800_FFF8, 32'h0800_FFFF));
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
  // Address-space layout regions inside the 16 MiB reset aperture. The
  // data-processing row ends at the zeroer aperture and the memory row at the
  // scratchpad, both from the generated map; the other rows are the memmap
  // chapter's layout table.
  // ------------------------------------------------------------------
  localparam int unsigned NumRegions = 14;
  localparam logic [31:0] RegionLo[NumRegions] = '{
      32'h0000_0000,
      32'h0000_1000,
      32'h0000_2000,
      32'h0000_3000,
      32'h0000_4000,
      32'h0000_6000,
      32'h0000_9000,
      32'h0001_0000,
      32'h0001_8000,
      32'h0003_8000,
      32'h0004_0000,
      32'h0016_0000,
      32'h0040_0000,
      32'h0080_0000
  };
  localparam logic [31:0] RegionHi[NumRegions] = '{
      32'h0000_0FFF,
      32'h0000_1FFF,
      32'h0000_2FFF,
      32'h0000_3FFF,
      32'h0000_5FFF,
      32'h0000_8FFF,
      32'h0000_DFFF,
      32'h0001_7FFF,
      32'h0003_7FFF,
      ZeroerHi,
      SpmHi,
      32'h0016_8FFF,
      32'h0040_57FF,
      32'h01FF_FFFF
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
  wire debug_region_e = region_ok[1];
  wire system_control_region_e = region_ok[2];
  wire gpio_region_e = region_ok[3];
  wire peripheral_region_e = region_ok[5];
  wire security_timing_dft_region_e = region_ok[6];
  wire fabric_control_region_e = region_ok[7];
  wire mailbox_region_e = region_ok[8];
  wire data_processing_region_e = region_ok[9];
  wire memory_region_e = region_ok[10];
  wire axil_external_region_e = region_ok[12];
  wire remap_region_e = region_ok[13];
  `OCAH_FCOV_COVER(c_wdt_region, wdt_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_debug_region, debug_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_system_control_region, system_control_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_region, gpio_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_peripheral_region, peripheral_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_security_timing_dft_region, security_timing_dft_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_fabric_control_region, fabric_control_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_mailbox_region, mailbox_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_data_processing_region, data_processing_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_memory_region, memory_region_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axil_external_region, axil_external_region_e, clk_smc_i, in_reset)
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

  wire cla_base_e = region_base_ok[11];
  wire cla_top_e = region_top_ok[11];
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
  covergroup cg_map_access with function sample (
      logic [NumRegions-1:0] region, logic is_write, logic [1:0] resp
  );
    option.per_instance = 1;
    cp_region: coverpoint region {
      bins regions[] = {
        14'b00_0000_0000_0001, 14'b00_0000_0000_0010, 14'b00_0000_0000_0100,
        14'b00_0000_0000_1000, 14'b00_0000_0001_0000, 14'b00_0000_0010_0000,
        14'b00_0000_0100_0000, 14'b00_0000_1000_0000, 14'b00_0001_0000_0000,
        14'b00_0010_0000_0000, 14'b00_0100_0000_0000, 14'b00_1000_0000_0000,
        14'b01_0000_0000_0000, 14'b10_0000_0000_0000
      };
      bins unmapped = {14'b0};
    }
    cp_dir: coverpoint is_write;
    // EXOKAY answers an exclusive access, and no manager on this bench issues
    // one (the c_bresp_exokay / c_rresp_exokay points record the same fact).
    cp_resp: coverpoint resp {
      bins okay = {2'b00};
      bins slverr = {2'b10};
      bins decerr = {2'b11};
      ignore_bins exokay = {2'b01};
    }
    x_region_resp: cross cp_region, cp_dir, cp_resp;
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

endmodule : smc_map_fcov
