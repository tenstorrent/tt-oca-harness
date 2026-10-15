// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC peripheral functional coverage: the `i2c_state`, `gpio_state` and
// `irq_state` intent of SMC_FCOV.adoc as native cover-property points.
//
// Each observable is its own point, so an undriven source stays a named,
// individually reportable hole the coverage policy can carry with evidence.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_periph_fcov #(
  parameter int unsigned GPIO_WIDTH = 64
) (
  input wire clk_periph_i,
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // I2C0 open-drain bus: resolved level, per-driver pulldowns, and the
  // CDC'd controller-side sense.
  input wire i2c0_scl_i,
  input wire i2c0_sda_i,
  input wire i2c0_scl_dut_low_i,
  input wire i2c0_sda_dut_low_i,
  input wire i2c0_scl_ext_low_i,
  input wire i2c0_sda_ext_low_i,
  input wire i2c0_scl_sense_i,
  input wire i2c0_sda_sense_i,
  input wire i2c0_enable_i,
  input wire i2c0_smbalert_i,

  // I3C0 shared bus (SMC side only; CCC/IBI stay with IP-level DV).
  input wire i3c0_scl_i,
  input wire i3c0_sda_i,
  input wire i3c0_scl_dut_low_i,
  input wire i3c0_sda_dut_low_i,

  // GPIO pad buses.
  input wire gpio_core2pad_any_i,
  input wire gpio_core2pad_en_any_i,
  input wire gpio_pad2core_en_any_i,
  input wire [GPIO_WIDTH-1:0] core2pad_i,
  input wire [GPIO_WIDTH-1:0] core2pad_en_i,
  input wire [GPIO_WIDTH-1:0] lsio_select_i,
  input wire gpio_pad57_i,

  // Interrupt sources.
  input wire sync_irq_i,
  input wire gpio_irq_any_i,
  input wire uart_irq_any_i,
  input wire mailbox_irq_any_i,
  input wire avsbus_irq_i,
  input wire telemetry_irq_any_i,
  input wire temp_interrupt_irq_i,
  input wire efuse_locked_access_irq_i,
  input wire axi_hang_irq_i,
  input wire axi_hang_irq_sys_i,
  input wire axi_hang_irq_sep_i,
  input wire axi_hang_irq_data_i,
  input wire axi_hang_irq_periph30_i,
  input wire axi_hang_irq_plic_src_i,
  input wire ext_interrupt_0_sync_i,

  // Peripheral-domain AXI-Lite CDC bridge, peripheral-clock side.
  input wire cdc_awvalid_i,
  input wire cdc_awready_i,
  input wire cdc_wvalid_i,
  input wire cdc_bvalid_i,
  input wire cdc_arvalid_i,
  input wire cdc_arready_i,
  input wire cdc_rvalid_i,

  // Mailbox 0 FIFO occupancy and the 32-channel interrupt vector.
  input wire [1:0] mbx0_full_i,
  input wire [1:0] mbx0_empty_i,
  input wire [31:0] mailbox_interrupts_i,

  // Telemetry ATB receivers.
  input wire [2:0] telem_atvalid_i,
  input wire [2:0] telem_atready_i,
  input wire [6:0] telem_atid0_i,
  input wire [6:0] telem_atid1_i,
  input wire [6:0] telem_atid2_i,

  // UART TX lines and I2C mode enables.
  input wire [3:0] uart_tx_i,
  input wire [2:0] i2c_host_enable_i,
  input wire [2:0] i2c_target_enable_i,

  // OCTS system timer count.
  input wire clk_ref_i,
  input wire [63:0] timer_count_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // I2C0 bus protocol events. START and STOP are edges of the resolved
  // SDA while SCL is high — real protocol activity, not a level.
  // ------------------------------------------------------------------
  logic i2c0_scl_q, i2c0_sda_q;
  always_ff @(posedge clk_periph_i) begin
    i2c0_scl_q <= i2c0_scl_i;
    i2c0_sda_q <= i2c0_sda_i;
  end

  wire i2c0_scl_high = (i2c0_scl_i === 1'b1);
  wire i2c0_sda_falling = (i2c0_sda_i === 1'b0) && (i2c0_sda_q === 1'b1);
  wire i2c0_sda_rising = (i2c0_sda_i === 1'b1) && (i2c0_sda_q === 1'b0);
  wire i2c0_scl_falling = (i2c0_scl_i === 1'b0) && (i2c0_scl_q === 1'b1);
  wire i2c0_scl_rising = (i2c0_scl_i === 1'b1) && (i2c0_scl_q === 1'b0);

  wire i2c0_start_e = i2c0_scl_high && i2c0_sda_falling;
  wire i2c0_stop_e = i2c0_scl_high && i2c0_sda_rising;
  `OCAH_FCOV_COVER(c_i2c0_start_condition, i2c0_start_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_stop_condition, i2c0_stop_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_scl_falling, i2c0_scl_falling, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_scl_rising, i2c0_scl_rising, clk_periph_i, in_reset)

  // Which side pulled the line down. The wired-AND makes the resolved
  // level ambiguous on its own; these separate DUT drive from VIP drive.
  wire i2c0_scl_dut_drive_e = (i2c0_scl_dut_low_i === 1'b1);
  wire i2c0_sda_dut_drive_e = (i2c0_sda_dut_low_i === 1'b1);
  wire i2c0_scl_ext_drive_e = (i2c0_scl_ext_low_i === 1'b1);
  wire i2c0_sda_ext_drive_e = (i2c0_sda_ext_low_i === 1'b1);
  `OCAH_FCOV_COVER(c_i2c0_scl_driven_by_dut, i2c0_scl_dut_drive_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_sda_driven_by_dut, i2c0_sda_dut_drive_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_scl_driven_by_ext, i2c0_scl_ext_drive_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_sda_driven_by_ext, i2c0_sda_ext_drive_e, clk_periph_i, in_reset)

  // Both sides pulling at once, and the DUT stretching the clock while the
  // host has released it.
  wire i2c0_scl_contention_e = i2c0_scl_dut_drive_e && i2c0_scl_ext_drive_e;
  wire i2c0_sda_contention_e = i2c0_sda_dut_drive_e && i2c0_sda_ext_drive_e;
  wire i2c0_clock_stretch_e = i2c0_scl_dut_drive_e && !i2c0_scl_ext_drive_e;
  `OCAH_FCOV_COVER(c_i2c0_scl_contention, i2c0_scl_contention_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_sda_contention, i2c0_sda_contention_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_clock_stretch_by_dut, i2c0_clock_stretch_e, clk_periph_i, in_reset)

  // LSIO enable and the CDC'd sense tracking the bus. SMC_FCOV.adoc notes
  // host traffic sits unconsumed unless enable=1 and scl_i tracks the bus,
  // so the tracking point is the one that makes an enable meaningful.
  wire i2c0_enabled_e = (i2c0_enable_i === 1'b1);
  wire i2c0_sense_tracks_e = i2c0_enabled_e && (i2c0_scl_sense_i === i2c0_scl_i)
      && (i2c0_sda_sense_i === i2c0_sda_i);
  `OCAH_FCOV_COVER(c_i2c0_enabled, i2c0_enabled_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c0_sense_tracks_bus, i2c0_sense_tracks_e, clk_periph_i, in_reset)

  // SMBALERT# is active low with a pullup when the DUT releases OE. Only the
  // asserted level gets a point: released is the quiescent state, true from
  // reset with no stimulus, so covering it would prove nothing.
  wire i2c0_smbalert_asserted_e = (i2c0_smbalert_i === 1'b0);
  `OCAH_FCOV_COVER(c_i2c0_smbalert_asserted, i2c0_smbalert_asserted_e, clk_periph_i, in_reset)

  // ------------------------------------------------------------------
  // I3C0 bus activity, SMC side. Scope is shallow: the CCC
  // and IBI protocol coverage is owned by IP-level DV per SMC_FCOV.adoc.
  // ------------------------------------------------------------------
  logic i3c0_scl_q;
  always_ff @(posedge clk_periph_i) i3c0_scl_q <= i3c0_scl_i;
  wire i3c0_scl_falling = (i3c0_scl_i === 1'b0) && (i3c0_scl_q === 1'b1);
  wire i3c0_scl_dut_drive_e = (i3c0_scl_dut_low_i === 1'b1);
  wire i3c0_sda_dut_drive_e = (i3c0_sda_dut_low_i === 1'b1);
  `OCAH_FCOV_COVER(c_i3c0_scl_falling, i3c0_scl_falling, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i3c0_scl_driven_by_dut, i3c0_scl_dut_drive_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i3c0_sda_driven_by_dut, i3c0_sda_dut_drive_e, clk_periph_i, in_reset)

  // ------------------------------------------------------------------
  // GPIO. The three `gpio_state` scalars at both values, plus a multi-pad
  // point: one pad driving and the whole bus driving are different states
  // that the OR-reduced scalar cannot distinguish.
  // ------------------------------------------------------------------
  wire gpio_core2pad_active_e = (gpio_core2pad_any_i === 1'b1);
  wire gpio_core2pad_en_active_e = (gpio_core2pad_en_any_i === 1'b1);
  wire gpio_pad2core_en_active_e = (gpio_pad2core_en_any_i === 1'b1);
  `OCAH_FCOV_COVER(c_gpio_core2pad_active, gpio_core2pad_active_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_core2pad_en_active, gpio_core2pad_en_active_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_pad2core_en_active, gpio_pad2core_en_active_e, clk_periph_i, in_reset)

  // The single-pad point counts the output enables GPIO software owns: a pad
  // an LSIO function selects is driven by that function (Programmer's
  // Guide, Selecting and Reclaiming LSIO), and several such pads are
  // enabled from reset.
  logic [$clog2(GPIO_WIDTH+1)-1:0] core2pad_en_count, sw_core2pad_en_count;
  always_comb begin
    core2pad_en_count = '0;
    sw_core2pad_en_count = '0;
    for (int unsigned i = 0; i < GPIO_WIDTH; i++) begin
      if (core2pad_en_i[i] === 1'b1) core2pad_en_count = core2pad_en_count + 1'b1;
      if ((core2pad_en_i[i] === 1'b1) && (lsio_select_i[i] === 1'b0))
        sw_core2pad_en_count = sw_core2pad_en_count + 1'b1;
    end
  end

  wire gpio_single_pad_enabled_e = (sw_core2pad_en_count == 1);
  wire gpio_multi_pad_enabled_e = (core2pad_en_count > 1);
  wire gpio_output_value_set_e = (core2pad_i !== '0) && gpio_core2pad_en_active_e;
  `OCAH_FCOV_COVER(c_gpio_single_pad_enabled, gpio_single_pad_enabled_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_multi_pad_enabled, gpio_multi_pad_enabled_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_output_value_driven, gpio_output_value_set_e, clk_periph_i, in_reset)

  // BootStallPad at both values through the pad shim. Both are product
  // states, but one of them is whatever the straps leave at power-up, so
  // each level is qualified by the pad having changed at least once --
  // otherwise the power-on value is covered with no stimulus at all.
  logic gpio_pad57_q;
  logic gpio_pad57_changed_q;
  always_ff @(posedge clk_periph_i) begin
    if (in_reset) begin
      gpio_pad57_q <= gpio_pad57_i;
      gpio_pad57_changed_q <= 1'b0;
    end else begin
      gpio_pad57_q <= gpio_pad57_i;
      if (gpio_pad57_i !== gpio_pad57_q) gpio_pad57_changed_q <= 1'b1;
    end
  end

  wire gpio_pad57_high_e = gpio_pad57_changed_q && (gpio_pad57_i === 1'b1);
  wire gpio_pad57_low_e = gpio_pad57_changed_q && (gpio_pad57_i === 1'b0);
  `OCAH_FCOV_COVER(c_gpio_boot_stall_pad_high, gpio_pad57_high_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_gpio_boot_stall_pad_low, gpio_pad57_low_e, clk_periph_i, in_reset)

  // ------------------------------------------------------------------
  // Interrupts. One point per source.
  // ------------------------------------------------------------------
  wire irq_sync_e = (sync_irq_i === 1'b1);
  wire irq_gpio_e = (gpio_irq_any_i === 1'b1);
  wire irq_uart_e = (uart_irq_any_i === 1'b1);
  wire irq_mailbox_e = (mailbox_irq_any_i === 1'b1);
  wire irq_avsbus_e = (avsbus_irq_i === 1'b1);
  wire irq_telemetry_e = (telemetry_irq_any_i === 1'b1);
  wire irq_temp_e = (temp_interrupt_irq_i === 1'b1);
  wire irq_efuse_locked_e = (efuse_locked_access_irq_i === 1'b1);
  wire irq_ext0_e = (ext_interrupt_0_sync_i === 1'b1);
  `OCAH_FCOV_COVER(c_irq_sync, irq_sync_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_gpio, irq_gpio_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_uart, irq_uart_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_mailbox, irq_mailbox_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_avsbus, irq_avsbus_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_telemetry, irq_telemetry_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_temp_interrupt, irq_temp_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_efuse_locked_access, irq_efuse_locked_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_ext_interrupt_0, irq_ext0_e, clk_smc_i, in_reset)

  // AXI hang detector: the combinational OR, each per-master leg, and the
  // two hops on the way to the PLIC.
  wire irq_hang_any_e = (axi_hang_irq_i === 1'b1);
  wire irq_hang_sys_e = (axi_hang_irq_sys_i === 1'b1);
  wire irq_hang_sep_e = (axi_hang_irq_sep_i === 1'b1);
  wire irq_hang_data_e = (axi_hang_irq_data_i === 1'b1);
  wire irq_hang_periph30_e = (axi_hang_irq_periph30_i === 1'b1);
  wire irq_hang_plic_src_e = (axi_hang_irq_plic_src_i === 1'b1);
  `OCAH_FCOV_COVER(c_irq_axi_hang_any, irq_hang_any_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_axi_hang_sys, irq_hang_sys_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_axi_hang_sep, irq_hang_sep_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_axi_hang_data, irq_hang_data_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_axi_hang_periph30, irq_hang_periph30_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_axi_hang_plic_src, irq_hang_plic_src_e, clk_smc_i, in_reset)

  // Independence: exactly one hang leg up proves the legs are separate,
  // which a single OR-reduced point cannot show.
  wire [2:0] hang_legs = {axi_hang_irq_sys_i, axi_hang_irq_sep_i, axi_hang_irq_data_i};
  wire irq_hang_single_leg_e = (hang_legs === 3'b001) || (hang_legs === 3'b010)
      || (hang_legs === 3'b100);
  wire irq_hang_multi_leg_e = (hang_legs === 3'b011) || (hang_legs === 3'b101)
      || (hang_legs === 3'b110) || (hang_legs === 3'b111);
  `OCAH_FCOV_COVER(c_irq_axi_hang_single_leg, irq_hang_single_leg_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_irq_axi_hang_multi_leg, irq_hang_multi_leg_e, clk_smc_i, in_reset)

  // Concurrency across unrelated sources.
  wire [3:0] irq_group = {irq_gpio_e, irq_uart_e, irq_mailbox_e, irq_sync_e};
  wire irq_multiple_concurrent_e = (irq_group != 4'b0000)
      && ((irq_group & (irq_group - 4'b0001)) != 4'b0000);
  `OCAH_FCOV_COVER(c_irq_multiple_concurrent, irq_multiple_concurrent_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Peripheral-domain AXI-Lite CDC bridge. The point is a request accepted
  // on the peripheral-clock side with its response returning there, so a
  // bridge that accepts and never answers is not covered.
  // ------------------------------------------------------------------
  logic cdc_wr_open_q, cdc_rd_open_q;
  always_ff @(posedge clk_periph_i) begin
    if (in_reset) begin
      cdc_wr_open_q <= 1'b0;
      cdc_rd_open_q <= 1'b0;
    end else begin
      if ((cdc_awvalid_i === 1'b1) && (cdc_awready_i === 1'b1)) cdc_wr_open_q <= 1'b1;
      else if (cdc_bvalid_i === 1'b1) cdc_wr_open_q <= 1'b0;
      if ((cdc_arvalid_i === 1'b1) && (cdc_arready_i === 1'b1)) cdc_rd_open_q <= 1'b1;
      else if (cdc_rvalid_i === 1'b1) cdc_rd_open_q <= 1'b0;
    end
  end

  wire cdc_bridge_write_e = cdc_wr_open_q && (cdc_bvalid_i === 1'b1);
  wire cdc_bridge_read_e = cdc_rd_open_q && (cdc_rvalid_i === 1'b1);
  `OCAH_FCOV_COVER(c_axil_cdc_bridge_write, cdc_bridge_write_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_axil_cdc_bridge_read, cdc_bridge_read_e, clk_periph_i, in_reset)
  // The peripheral-clock side carrying a request at all, kept separate so a
  // bridge that never opened is distinguishable from one that never answered.
  wire cdc_request_e = (cdc_awvalid_i === 1'b1) || (cdc_arvalid_i === 1'b1);
  `OCAH_FCOV_COVER(c_axil_cdc_request_seen, cdc_request_e, clk_periph_i, in_reset)

  // ------------------------------------------------------------------
  // Mailbox instantiation. The vector is 32 bits wide by construction, so
  // the count point is a channel above the low byte raising its own bit --
  // that cannot be satisfied by a narrower instantiation. The depth point
  // is the FIFO reporting full, which at depth two means two entries.
  // ------------------------------------------------------------------
  wire mailbox_count_32_e = (mailbox_interrupts_i[31:8] !== 24'd0)
      && (^mailbox_interrupts_i !== 1'bx);
  wire mailbox_depth_two_e = (mbx0_full_i !== 2'd0) && (^mbx0_full_i !== 1'bx);
  wire mailbox_single_entry_e = (mbx0_full_i === 2'd0) && (mbx0_empty_i !== 2'b11)
      && (^mbx0_empty_i !== 1'bx);
  `OCAH_FCOV_COVER(c_mailbox_count_32, mailbox_count_32_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_mailbox_depth_2_full_at_two_entries, mailbox_depth_two_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_single_entry_message, mailbox_single_entry_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_two_entry_message, mailbox_depth_two_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Telemetry ATB. An accepted beat is valid and ready in the same cycle;
  // the per-receiver points keep the three instances separable, and the
  // distinct-ID point needs two different IDs across the run.
  // ------------------------------------------------------------------
  wire [2:0] atb_accept = telem_atvalid_i & telem_atready_i;
  wire atb_transfer_accepted_e = (atb_accept !== 3'd0) && (^atb_accept !== 1'bx);
  wire receiver_0_decode_e = (atb_accept[0] === 1'b1);
  wire receiver_1_decode_e = (atb_accept[1] === 1'b1);
  wire receiver_2_decode_e = (atb_accept[2] === 1'b1);
  `OCAH_FCOV_COVER(c_atb_transfer_accepted, atb_transfer_accepted_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_receiver_0_decode, receiver_0_decode_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_receiver_1_decode, receiver_1_decode_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_receiver_2_decode, receiver_2_decode_e, clk_smc_i, in_reset)

  logic [6:0] first_atid_q;
  logic first_atid_valid_q;
  logic distinct_atid_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      first_atid_q <= '0;
      first_atid_valid_q <= 1'b0;
      distinct_atid_q <= 1'b0;
    end else if (atb_accept[0] === 1'b1) begin
      if (!first_atid_valid_q) begin
        first_atid_q <= telem_atid0_i;
        first_atid_valid_q <= 1'b1;
      end else if (telem_atid0_i !== first_atid_q) begin
        distinct_atid_q <= 1'b1;
      end
    end
  end

  wire distinct_atid_values_e = distinct_atid_q
      || ((atb_accept[1] === 1'b1) && (telem_atid1_i !== telem_atid0_i))
      || ((atb_accept[2] === 1'b1) && (telem_atid2_i !== telem_atid0_i));
  `OCAH_FCOV_COVER(c_distinct_atid_values, distinct_atid_values_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // UART transmission. A character starts with the line falling from idle;
  // one such edge is a character, two are more than one.
  // ------------------------------------------------------------------
  logic uart0_tx_q;
  logic [7:0] uart0_start_count_q;
  always_ff @(posedge clk_periph_i) begin
    if (in_reset) begin
      uart0_tx_q <= 1'b1;
      uart0_start_count_q <= '0;
    end else begin
      uart0_tx_q <= uart_tx_i[0];
      if ((uart_tx_i[0] === 1'b0) && (uart0_tx_q === 1'b1) && (uart0_start_count_q != 8'hFF)) begin
        uart0_start_count_q <= uart0_start_count_q + 8'd1;
      end
    end
  end

  wire tx_single_char_e = (uart0_start_count_q >= 8'd1);
  wire tx_multi_char_e = (uart0_start_count_q >= 8'd2);
  `OCAH_FCOV_COVER(c_tx_single_char, tx_single_char_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_tx_multi_char, tx_multi_char_e, clk_periph_i, in_reset)

  // ------------------------------------------------------------------
  // I2C direction and repeated start. The address byte's eighth bit is the
  // read/write flag, so the bit counter after a START selects it; a START
  // with a transfer already open is a repeated start.
  // ------------------------------------------------------------------
  logic i2c0_in_transfer_q;
  logic [3:0] i2c0_bit_cnt_q;
  logic i2c0_rw_valid_q;
  logic i2c0_rw_q;
  always_ff @(posedge clk_periph_i) begin
    if (in_reset) begin
      i2c0_in_transfer_q <= 1'b0;
      i2c0_bit_cnt_q <= '0;
      i2c0_rw_valid_q <= 1'b0;
      i2c0_rw_q <= 1'b0;
    end else if (i2c0_start_e) begin
      i2c0_in_transfer_q <= 1'b1;
      i2c0_bit_cnt_q <= '0;
      i2c0_rw_valid_q <= 1'b0;
    end else if (i2c0_stop_e) begin
      i2c0_in_transfer_q <= 1'b0;
      i2c0_rw_valid_q <= 1'b0;
    end else if (i2c0_in_transfer_q && i2c0_scl_rising) begin
      if (i2c0_bit_cnt_q != 4'd15) i2c0_bit_cnt_q <= i2c0_bit_cnt_q + 4'd1;
      if (i2c0_bit_cnt_q == 4'd7) begin
        i2c0_rw_valid_q <= 1'b1;
        i2c0_rw_q <= i2c0_sda_i;
      end
    end
  end

  wire i2c0_host = (i2c_host_enable_i[0] === 1'b1);
  wire i2c0_target = (i2c_target_enable_i[0] === 1'b1);
  wire controller_write_e = i2c0_host && i2c0_rw_valid_q && (i2c0_rw_q === 1'b0);
  wire controller_read_e = i2c0_host && i2c0_rw_valid_q && (i2c0_rw_q === 1'b1);
  wire controller_repeated_start_e = i2c0_host && i2c0_start_e && i2c0_in_transfer_q;
  wire target_write_received_e = i2c0_target && !i2c0_host && i2c0_rw_valid_q
      && (i2c0_rw_q === 1'b0);
  wire target_read_served_e = i2c0_target && !i2c0_host && i2c0_rw_valid_q
      && (i2c0_rw_q === 1'b1);
  `OCAH_FCOV_COVER(c_controller_write, controller_write_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_controller_read, controller_read_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_controller_repeated_start, controller_repeated_start_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_target_write_received, target_write_received_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_target_read_served, target_read_served_e, clk_periph_i, in_reset)

  // ------------------------------------------------------------------
  // OCTS system timer. Advance is a change of the count; monotonic is the
  // stronger form, a change that is an increase.
  // ------------------------------------------------------------------
  logic [63:0] timer_count_q;
  always_ff @(posedge clk_ref_i) begin
    if (in_reset) timer_count_q <= '0;
    else timer_count_q <= timer_count_i;
  end

  wire timer_valid = (^timer_count_q !== 1'bx) && (^timer_count_i !== 1'bx);
  wire octs_count_advances_e = timer_valid && (timer_count_i !== timer_count_q);
  wire octs_count_monotonic_e = timer_valid && (timer_count_i > timer_count_q);
  `OCAH_FCOV_COVER(c_octs_count_advances, octs_count_advances_e, clk_ref_i, in_reset)
  `OCAH_FCOV_COVER(c_octs_count_monotonic, octs_count_monotonic_e, clk_ref_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: the driver-pair and irq-source
  // crosses, which the flat point list cannot express.
  // ------------------------------------------------------------------
  covergroup cg_i2c0_bus with function sample (
      logic scl_dut_low, logic sda_dut_low, logic scl_ext_low, logic sda_ext_low, logic enable
  );
    option.per_instance = 1;
    cp_scl_dut: coverpoint scl_dut_low;
    cp_sda_dut: coverpoint sda_dut_low;
    cp_scl_ext: coverpoint scl_ext_low;
    cp_sda_ext: coverpoint sda_ext_low;
    cp_enable: coverpoint enable;
    x_scl_drivers: cross cp_scl_dut, cp_scl_ext;
    x_sda_drivers: cross cp_sda_dut, cp_sda_ext;
  endgroup

  covergroup cg_gpio_state with function sample (
      logic core2pad, logic core2pad_en, logic pad2core_en, int unsigned en_count
  );
    option.per_instance = 1;
    cp_core2pad: coverpoint core2pad;
    cp_core2pad_en: coverpoint core2pad_en;
    // smc_padring ties the UART RX and CTS pads' input enables on, so the
    // any-pad reduction never reads 0 outside reset.
    cp_pad2core_en: coverpoint pad2core_en {
      ignore_bins tied_on = {1'b0};
    }
    // smc_padring ties the UART TX and RTS pads' and two further pads' output
    // enables on, so outside reset the count never settles at exactly one.
    cp_en_count: coverpoint en_count {
      bins none = {0}; ignore_bins one = {1}; bins few = {[2 : 8]}; bins many = default;
    }
    x_gpio_dir: cross cp_core2pad_en, cp_pad2core_en;
  endgroup

  covergroup cg_irq_sources with function sample (logic [8:0] sources);
    option.per_instance = 1;
    cp_any: coverpoint |sources;
    cp_sync: coverpoint sources[0];
    cp_gpio: coverpoint sources[1];
    cp_uart: coverpoint sources[2];
    cp_mailbox: coverpoint sources[3];
    cp_avsbus: coverpoint sources[4];
    cp_telemetry: coverpoint sources[5];
    cp_temp: coverpoint sources[6];
    cp_efuse: coverpoint sources[7];
    cp_hang: coverpoint sources[8];
    x_gpio_uart: cross cp_gpio, cp_uart;
  endgroup

  cg_i2c0_bus u_cg_i2c0_bus = new();
  cg_gpio_state u_cg_gpio_state = new();
  cg_irq_sources u_cg_irq_sources = new();

  // Bit order matches the cp_* indices in cg_irq_sources.
  wire [8:0] irq_sources = {irq_hang_any_e, irq_efuse_locked_e, irq_temp_e, irq_telemetry_e,
                            irq_avsbus_e, irq_mailbox_e, irq_uart_e, irq_gpio_e, irq_sync_e};

  always_ff @(posedge clk_periph_i) begin
    if (!in_reset) begin
      u_cg_i2c0_bus.sample(i2c0_scl_dut_low_i, i2c0_sda_dut_low_i, i2c0_scl_ext_low_i,
                           i2c0_sda_ext_low_i, i2c0_enable_i);
      u_cg_gpio_state.sample(gpio_core2pad_any_i, gpio_core2pad_en_any_i, gpio_pad2core_en_any_i,
                             core2pad_en_count);
    end
  end

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) u_cg_irq_sources.sample(irq_sources);
  end
`endif

endmodule : smc_periph_fcov
