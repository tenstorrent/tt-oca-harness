// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC clock and clock-gating functional coverage.
//
// Carries the `clk_bucket` intent of SMC_FCOV.adoc. A cover point cannot
// express the Python bin's bucket index, so the points here cover the
// relationship between the three domains and the clock-gating behaviour, both
// of which have hit-or-miss states.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_clk_fcov #(
  // Ref-clock cycles per measurement window for the domain-ratio points.
  parameter int unsigned WINDOW_CYCLES = 1024
) (
  input wire clk_ref_i,
  input wire clk_smc_i,
  input wire clk_periph_i,
  input wire rst_cold_ni,

  // DFT gate override.
  input wire test_en_i,

  // I2C clock gate.
  input wire i2c_cg_en_i,

  // DMA clock gate.
  input wire dma_cg_en_i,
  input wire dma_gated_clk_i,
  input wire dma_busy_i,
  input wire dma_frontend_busy_i,
  input wire dma_backend_busy_i,
  input wire dma_gater_busy_i,

  // Zeroer clock gates (separate axi / reg clocks).
  input wire zeroer_cg_en_i,
  input wire zeroer_gated_axi_clk_i,
  input wire zeroer_gated_reg_clk_i,
  input wire zeroer_busy_i,
  input wire zeroer_bus_active_i,

  // Telemetry ATB receiver 0, captured in the telemetry clock domain.
  input wire telemetry_atvalid_i,
  input wire telemetry_atready_i,
  input wire [7:0] telemetry_atdata_i
);

  // The clk_periph period point below compares a `$time` delta against a
  // picosecond constant, so the unit this module counts in is pinned here
  // rather than inherited from whichever file precedes it in the compile.
  timeunit 1ps; timeprecision 1fs;

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Domain ratio — which relative clock speeds a seed actually produced.
  // The per-domain counters run in their own clock domains and are read
  // at a ref-clock window boundary; this is an observation, not a check,
  // so a read landing on an increment only shifts a ratio by one count.
  // ------------------------------------------------------------------
  localparam int unsigned CntWidth = 32;
  localparam int unsigned WinWidth = $clog2(WINDOW_CYCLES);
  localparam logic [WinWidth-1:0] WindowLast = WinWidth'(WINDOW_CYCLES - 1);

  // Every register here carries a reset branch. Without one a 4-state
  // simulator holds the counters at X for the whole run, the window never
  // closes, and every ratio point below is unhittable on the commercial
  // path while still reading as covered-by-omission on Verilator, which
  // zero-initialises.
  logic [CntWidth-1:0] cnt_ref_q;
  logic [CntWidth-1:0] cnt_smc_q;
  logic [CntWidth-1:0] cnt_periph_q;

  always_ff @(posedge clk_ref_i) begin
    if (in_reset) cnt_ref_q <= '0;
    else cnt_ref_q <= cnt_ref_q + 1'b1;
  end
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) cnt_smc_q <= '0;
    else cnt_smc_q <= cnt_smc_q + 1'b1;
  end
  always_ff @(posedge clk_periph_i) begin
    if (in_reset) cnt_periph_q <= '0;
    else cnt_periph_q <= cnt_periph_q + 1'b1;
  end

  // The deltas are registered at the closing edge against the base captured
  // when the window opened, so they span WINDOW_CYCLES ref edges. Reading
  // live counters against a base loaded on the same edge would measure a
  // single cycle instead.
  logic [WinWidth-1:0] win_cnt_q;
  logic [CntWidth-1:0] base_ref_q, base_smc_q, base_periph_q;
  logic [CntWidth-1:0] d_ref_q, d_smc_q, d_periph_q;
  logic window_tick_q;

  always_ff @(posedge clk_ref_i) begin
    if (in_reset) begin
      win_cnt_q <= '0;
      base_ref_q <= '0;
      base_smc_q <= '0;
      base_periph_q <= '0;
      d_ref_q <= '0;
      d_smc_q <= '0;
      d_periph_q <= '0;
      window_tick_q <= 1'b0;
    end else if (win_cnt_q == WindowLast) begin
      win_cnt_q <= '0;
      d_ref_q <= cnt_ref_q - base_ref_q;
      d_smc_q <= cnt_smc_q - base_smc_q;
      d_periph_q <= cnt_periph_q - base_periph_q;
      base_ref_q <= cnt_ref_q;
      base_smc_q <= cnt_smc_q;
      base_periph_q <= cnt_periph_q;
      window_tick_q <= 1'b1;
    end else begin
      win_cnt_q <= win_cnt_q + 1'b1;
      window_tick_q <= 1'b0;
    end
  end

  wire [CntWidth-1:0] d_ref = d_ref_q;
  wire [CntWidth-1:0] d_smc = d_smc_q;
  wire [CntWidth-1:0] d_periph = d_periph_q;

`ifdef SMC_FCOV_PHASE2
  // Phase 2 (SMC_FCOV.adoc): a window in which a domain produced no edge at
  // all while ref ran. clk_rst.adoc gives each input clock a domain, and
  // clk_periph_i a 100 MHz minimum, but defines no mode in which one stops.
  wire smc_stalled_e = window_tick_q && (d_ref != '0) && (d_smc == '0);
  wire periph_stalled_e = window_tick_q && (d_ref != '0) && (d_periph == '0);
  `OCAH_FCOV_COVER(c_clk_smc_stalled_window, smc_stalled_e, clk_ref_i, in_reset)
  `OCAH_FCOV_COVER(c_clk_periph_stalled_window, periph_stalled_e, clk_ref_i, in_reset)
`endif

  wire smc_faster_e = window_tick_q && (d_smc > d_ref);
  wire smc_equal_e = window_tick_q && (d_smc == d_ref) && (d_ref != '0);
  wire smc_slower_e = window_tick_q && (d_smc < d_ref) && (d_smc != '0);
  `OCAH_FCOV_COVER(c_clk_ratio_smc_faster_than_ref, smc_faster_e, clk_ref_i, in_reset)
  `OCAH_FCOV_COVER(c_clk_ratio_smc_equal_ref, smc_equal_e, clk_ref_i, in_reset)
  `OCAH_FCOV_COVER(c_clk_ratio_smc_slower_than_ref, smc_slower_e, clk_ref_i, in_reset)

  wire periph_faster_e = window_tick_q && (d_periph > d_ref);
  wire periph_equal_e = window_tick_q && (d_periph == d_ref) && (d_ref != '0);
  wire periph_slower_e = window_tick_q && (d_periph < d_ref) && (d_periph != '0);
  `OCAH_FCOV_COVER(c_clk_ratio_periph_faster_than_ref, periph_faster_e, clk_ref_i, in_reset)
  `OCAH_FCOV_COVER(c_clk_ratio_periph_equal_ref, periph_equal_e, clk_ref_i, in_reset)
  `OCAH_FCOV_COVER(c_clk_ratio_periph_slower_than_ref, periph_slower_e, clk_ref_i, in_reset)

  wire smc_faster_than_periph_e = window_tick_q && (d_smc > d_periph) && (d_periph != '0);
  wire periph_faster_than_smc_e = window_tick_q && (d_periph > d_smc) && (d_smc != '0);
  `OCAH_FCOV_COVER(c_clk_ratio_smc_faster_than_periph, smc_faster_than_periph_e, clk_ref_i,
                   in_reset)
  `OCAH_FCOV_COVER(c_clk_ratio_periph_faster_than_smc, periph_faster_than_smc_e, clk_ref_i,
                   in_reset)

  // ------------------------------------------------------------------
  // Clock-gate enables at both values: the `i2c_state` (resolvable, cg_en)
  // intent split so an un-driven half is a named hole.
  //
  // A closed gate is the quiescent state, so an unqualified closed point is
  // hit at reset release with no stimulus at all. Each closed point is
  // therefore gated on that same gate having been seen open, which makes it
  // mean "the gate closes again after opening" -- the half of the contract
  // the open point cannot show.
  // ------------------------------------------------------------------
  wire i2c_cg_open_e = (i2c_cg_en_i === 1'b1);
  wire dma_cg_open_e = (dma_cg_en_i === 1'b1);
  wire zeroer_cg_open_e = (zeroer_cg_en_i === 1'b1);

  logic i2c_cg_open_seen_q, dma_cg_open_seen_q, zeroer_cg_open_seen_q;
  logic dma_busy_seen_q;

  always_ff @(posedge clk_periph_i) begin
    if (in_reset) i2c_cg_open_seen_q <= 1'b0;
    else if (i2c_cg_open_e) i2c_cg_open_seen_q <= 1'b1;
  end

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      dma_cg_open_seen_q <= 1'b0;
      zeroer_cg_open_seen_q <= 1'b0;
      dma_busy_seen_q <= 1'b0;
    end else begin
      if (dma_cg_open_e) dma_cg_open_seen_q <= 1'b1;
      if (zeroer_cg_open_e) zeroer_cg_open_seen_q <= 1'b1;
      if (dma_gater_busy_i === 1'b1) dma_busy_seen_q <= 1'b1;
    end
  end

  wire i2c_cg_closed_e = i2c_cg_open_seen_q && (i2c_cg_en_i === 1'b0);
  wire dma_cg_closed_e = dma_cg_open_seen_q && (dma_cg_en_i === 1'b0);
  wire zeroer_cg_closed_e = zeroer_cg_open_seen_q && (zeroer_cg_en_i === 1'b0);
  `OCAH_FCOV_COVER(c_i2c_cg_open, i2c_cg_open_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_i2c_cg_closed, i2c_cg_closed_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_cg_open, dma_cg_open_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_cg_closed, dma_cg_closed_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_cg_open, zeroer_cg_open_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_cg_closed, zeroer_cg_closed_e, clk_smc_i, in_reset)

  wire test_en_gate_override_e = (test_en_i === 1'b1);
  `OCAH_FCOV_COVER(c_cg_test_en_override, test_en_gate_override_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Gated clocks actually toggling / actually held. A gate enable that is
  // never observed with its downstream clock moving is not proof the gate
  // works; these two points separate the enable from its effect.
  // ------------------------------------------------------------------
  // A gated clock is observed through a flop it toggles itself. Sampling the
  // clock net on the edge of the clock it is gated from reads the same level
  // every cycle whether it runs or not; the flop changes between two samples
  // exactly when the gated clock had an edge.
  logic dma_clk_div_q, zeroer_axi_div_q, zeroer_reg_div_q;
  always_ff @(posedge dma_gated_clk_i) dma_clk_div_q <= (dma_clk_div_q !== 1'b1);
  always_ff @(posedge zeroer_gated_axi_clk_i) zeroer_axi_div_q <= (zeroer_axi_div_q !== 1'b1);
  always_ff @(posedge zeroer_gated_reg_clk_i) zeroer_reg_div_q <= (zeroer_reg_div_q !== 1'b1);

  logic dma_gated_clk_q, zeroer_axi_clk_q, zeroer_reg_clk_q;
  always_ff @(posedge clk_smc_i) begin
    dma_gated_clk_q <= dma_clk_div_q;
    zeroer_axi_clk_q <= zeroer_axi_div_q;
    zeroer_reg_clk_q <= zeroer_reg_div_q;
  end

  wire dma_clk_toggling = (dma_clk_div_q !== dma_gated_clk_q);
  wire zeroer_axi_clk_toggling = (zeroer_axi_div_q !== zeroer_axi_clk_q);
  wire zeroer_reg_clk_toggling = (zeroer_reg_div_q !== zeroer_reg_clk_q);

  // The held points inherit the open-seen qualifier through *_cg_closed_e.
  // The reg clock is gated by the AXI-Lite snoop rather than by
  // zeroer_cg_en, so its running point is qualified by bus_active, matching
  // how the AXI one is qualified by its own enable.
  wire zeroer_bus_active_e = (zeroer_bus_active_i === 1'b1);

  wire dma_clk_running_e = dma_cg_open_e && dma_clk_toggling;
  wire dma_clk_held_e = dma_cg_closed_e && !dma_clk_toggling;
  `OCAH_FCOV_COVER(c_dma_gated_clk_running, dma_clk_running_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_gated_clk_held, dma_clk_held_e, clk_smc_i, in_reset)

  wire zeroer_axi_running_e = zeroer_cg_open_e && zeroer_axi_clk_toggling;
  wire zeroer_axi_held_e = zeroer_cg_closed_e && !zeroer_axi_clk_toggling;
  wire zeroer_reg_running_e = zeroer_bus_active_e && zeroer_reg_clk_toggling;
  wire zeroer_reg_held_e = zeroer_cg_closed_e && !zeroer_reg_clk_toggling;
  `OCAH_FCOV_COVER(c_zeroer_gated_axi_clk_running, zeroer_axi_running_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_gated_axi_clk_held, zeroer_axi_held_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_gated_reg_clk_running, zeroer_reg_running_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_gated_reg_clk_held, zeroer_reg_held_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Busy / gate agreement. The four DMA frontend-backend busy states and
  // the gate response to each are the clock-gating contract; the
  // busy-with-gate-closed point is the one that should stay empty.
  // ------------------------------------------------------------------
  // fe0_be0 is the idle state, so it carries the busy-seen qualifier and
  // means "the engine returned to idle after working" rather than "nothing
  // has happened yet".
  wire dma_busy_fe0_be0_e = dma_busy_seen_q && (dma_frontend_busy_i === 1'b0)
      && (dma_backend_busy_i === 1'b0);
  wire dma_busy_fe0_be1_e = (dma_frontend_busy_i === 1'b0) && (dma_backend_busy_i === 1'b1);
  wire dma_busy_fe1_be0_e = (dma_frontend_busy_i === 1'b1) && (dma_backend_busy_i === 1'b0);
  wire dma_busy_fe1_be1_e = (dma_frontend_busy_i === 1'b1) && (dma_backend_busy_i === 1'b1);
  `OCAH_FCOV_COVER(c_dma_busy_fe0_be0, dma_busy_fe0_be0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_busy_fe0_be1, dma_busy_fe0_be1_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_busy_fe1_be0, dma_busy_fe1_be0_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_busy_fe1_be1, dma_busy_fe1_be1_e, clk_smc_i, in_reset)

  wire dma_gate_open_on_busy_e = (dma_gater_busy_i === 1'b1) && dma_cg_open_e;
  wire dma_gate_closed_when_idle_e = (dma_gater_busy_i === 1'b0) && dma_cg_closed_e;
  wire dma_hyst_window_e = (dma_gater_busy_i === 1'b0) && dma_cg_open_e;
  `OCAH_FCOV_COVER(c_dma_gate_open_on_busy, dma_gate_open_on_busy_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_gate_closed_when_idle, dma_gate_closed_when_idle_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dma_gate_hysteresis_window, dma_hyst_window_e, clk_smc_i, in_reset)

  wire dma_busy_seen_e = (dma_busy_i === 1'b1);
  `OCAH_FCOV_COVER(c_dma_busy_seen, dma_busy_seen_e, clk_smc_i, in_reset)

  wire zeroer_gate_open_on_busy_e = (zeroer_busy_i === 1'b1) && zeroer_cg_open_e;
  wire zeroer_gate_closed_when_idle_e = (zeroer_busy_i === 1'b0) && zeroer_cg_closed_e;
  wire zeroer_reg_clk_resume_e = zeroer_bus_active_e && zeroer_reg_clk_toggling;
  `OCAH_FCOV_COVER(c_zeroer_gate_open_on_busy, zeroer_gate_open_on_busy_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_gate_closed_when_idle, zeroer_gate_closed_when_idle_e, clk_smc_i,
                   in_reset)
  `OCAH_FCOV_COVER(c_zeroer_bus_active, zeroer_bus_active_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_zeroer_reg_clk_resume_on_access, zeroer_reg_clk_resume_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Peripheral-domain rate. The clock chapter states 100 MHz as the minimum
  // for this domain, so the point is the measured period being at or under
  // 10 ns. The period is the time between two successive rising edges, which
  // is only meaningful once a first edge has been recorded.
  // ------------------------------------------------------------------
  localparam longint unsigned PeriphMinPeriodPs = 10_000;

  logic [63:0] periph_edge_time_q;
  logic [63:0] periph_period_q;
  logic periph_edge_seen_q;
  always_ff @(posedge clk_periph_i) begin
    if (in_reset) begin
      periph_edge_time_q <= 64'($time);
      periph_period_q <= '0;
      periph_edge_seen_q <= 1'b0;
    end else begin
      periph_edge_time_q <= 64'($time);
      periph_period_q <= 64'($time) - periph_edge_time_q;
      periph_edge_seen_q <= 1'b1;
    end
  end

  wire periph_at_min_rate_e =
      periph_edge_seen_q && (periph_period_q != '0) && (periph_period_q <= PeriphMinPeriodPs);
  `OCAH_FCOV_COVER(c_clk_periph_at_minimum_100mhz, periph_at_min_rate_e, clk_periph_i, in_reset)

  // ------------------------------------------------------------------
  // Telemetry domain: an ATB beat accepted on the telemetry clock. The SMC
  // has no telemetry PLL, so this tb runs the receiver on clk_smc_i and the
  // point samples there.
  // ------------------------------------------------------------------
  wire atb_accept_e = (telemetry_atvalid_i === 1'b1) && (telemetry_atready_i === 1'b1);
  logic [7:0] atb_data_q;
  logic atb_accept_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      atb_data_q <= '0;
      atb_accept_q <= 1'b0;
    end else begin
      atb_accept_q <= atb_accept_e;
      if (atb_accept_e) atb_data_q <= telemetry_atdata_i;
    end
  end

  wire atb_capture_e = atb_accept_q && (atb_data_q !== 8'h00);
  `OCAH_FCOV_COVER(c_atb_capture_on_clk_telemetry, atb_capture_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Per-module gating as a contract independent of which module it is: a
  // gate open with its clock moving, a gate closed with its clock held, and
  // the restore edge where activity re-opens a closed gate. The restore
  // point is an edge, so it cannot be satisfied by a gate that was never
  // closed.
  // ------------------------------------------------------------------
  wire module_gate_enabled_e = (dma_cg_open_e && dma_clk_toggling)
      || (zeroer_cg_open_e && zeroer_axi_clk_toggling);
  wire module_gate_disabled_e = dma_clk_held_e || zeroer_axi_held_e || i2c_cg_closed_e;
  `OCAH_FCOV_COVER(c_module_gate_enabled, module_gate_enabled_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_module_gate_disabled, module_gate_disabled_e, clk_smc_i, in_reset)

  logic dma_cg_en_q, zeroer_cg_en_q;
  logic dma_busy_q, zeroer_busy_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      dma_cg_en_q <= 1'b0;
      zeroer_cg_en_q <= 1'b0;
      dma_busy_q <= 1'b0;
      zeroer_busy_q <= 1'b0;
    end else begin
      dma_cg_en_q <= dma_cg_en_i;
      zeroer_cg_en_q <= zeroer_cg_en_i;
      dma_busy_q <= dma_gater_busy_i;
      zeroer_busy_q <= zeroer_busy_i;
    end
  end

  // Restore is the gated clock resuming after having been held, with the
  // activity term up. The cg_en inputs are the CSR controls, so an edge on
  // them is a software write rather than an activity detection.
  logic dma_clk_held_q, zeroer_axi_held_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      dma_clk_held_q <= 1'b0;
      zeroer_axi_held_q <= 1'b0;
    end else begin
      dma_clk_held_q <= !dma_clk_toggling;
      zeroer_axi_held_q <= !zeroer_axi_clk_toggling;
    end
  end

  wire dma_gate_restored_e = dma_clk_held_q && dma_clk_toggling
      && ((dma_gater_busy_i === 1'b1) || (dma_busy_q === 1'b1));
  wire zeroer_gate_restored_e = zeroer_axi_held_q && zeroer_axi_clk_toggling
      && ((zeroer_busy_i === 1'b1) || (zeroer_busy_q === 1'b1));
  wire activity_restores_clock_e = dma_gate_restored_e || zeroer_gate_restored_e;
  `OCAH_FCOV_COVER(c_activity_detected_clock_restored, activity_restores_clock_e, clk_smc_i,
                   in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: the crosses a flat cover-property
  // list cannot express, plus a bucketed view of the domain ratios. A bucket
  // is the domain's edge count per reference edge in quarters; the classes
  // are the relations the clock tree distinguishes (a stalled, slower, equal,
  // faster or much faster domain), not the ratio values themselves. Values
  // above eight times the reference fall in the default bin and are not
  // graded.
  // ------------------------------------------------------------------
  covergroup cg_clk_ratio with function sample (
      logic [31:0] ref_edges, logic [31:0] smc_edges, logic [31:0] periph_edges
  );
    option.per_instance = 1;
    // The bench drives ref / smc / periph at 10 / 1.25 / 5 ns, or a 10 ns SMC
    // clock under +pll_sys_period_ns=10, so the default run lands in the SMC
    // much_faster by periph faster cell. The smc_clk_* ratio leaves in
    // testlists/clock.toml pin the other periods, one leaf per cell of the
    // cross below, so every slower, same, faster and much_faster bin of both
    // coverpoints and every cell of their cross has a driver and is graded.
    // The stalled bins are out: clk_rst.adoc defines no mode in which an input
    // clock stops (the stalled-window cover points are Phase 2), and a clock
    // the clock gates stop is the cg_clk_gate group's subject.
    cp_smc_bucket: coverpoint (smc_edges * 4) / (ref_edges == 0 ? 1 : ref_edges) {
      bins stalled = {0};
      bins slower = {[1 : 3]};
      bins same = {4};
      bins faster = {[5 : 8]};
      bins much_faster = {[9 : 32]};
      bins beyond = default;
      ignore_bins smc_stalled = {0};
    }
    cp_periph_bucket: coverpoint (periph_edges * 4) / (ref_edges == 0 ? 1 : ref_edges) {
      bins stalled = {0};
      bins slower = {[1 : 3]};
      bins same = {4};
      bins faster = {[5 : 8]};
      bins much_faster = {[9 : 32]};
      bins beyond = default;
      ignore_bins periph_stalled = {0};
    }
    x_smc_periph: cross cp_smc_bucket, cp_periph_bucket;
  endgroup

  covergroup cg_clk_gate with function sample (logic cg_en, logic busy, logic clk_toggling);
    option.per_instance = 1;
    cp_cg_en: coverpoint cg_en {bins bypassed = {1'b0}; bins gating = {1'b1};}
    cp_busy: coverpoint busy {bins idle = {1'b0}; bins busy = {1'b1};}
    cp_toggling: coverpoint clk_toggling {bins held = {1'b0}; bins running = {1'b1};}
    // cg_enable_i low bypasses the gate and a busy block keeps its clock
    // (dma.adoc and zeroer.adoc, Clock Gating), so the clock is not held while
    // either holds.
    x_gate_contract: cross cp_cg_en, cp_busy, cp_toggling{
      ignore_bins held_while_bypassed = binsof (cp_cg_en.bypassed) && binsof (cp_toggling.held);
      ignore_bins held_while_busy = binsof (cp_busy.busy) && binsof (cp_toggling.held);
    }
  endgroup

  cg_clk_ratio u_cg_clk_ratio = new();
  cg_clk_gate u_cg_dma_gate = new();
  cg_clk_gate u_cg_zeroer_gate = new();

  always_ff @(posedge clk_ref_i) begin
    if (window_tick_q && !in_reset) u_cg_clk_ratio.sample(d_ref, d_smc, d_periph);
  end

  // A clock movement seen at one sample is the gated edge of the previous
  // cycle, so the gate terms are crossed one sample late.
  logic gate_dma_cg_en_q, gate_dma_busy_q, gate_zeroer_cg_en_q, gate_zeroer_busy_q;
  always_ff @(posedge clk_smc_i) begin
    gate_dma_cg_en_q <= dma_cg_en_i;
    gate_dma_busy_q <= dma_gater_busy_i;
    gate_zeroer_cg_en_q <= zeroer_cg_en_i;
    gate_zeroer_busy_q <= zeroer_busy_i;
  end

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      u_cg_dma_gate.sample(gate_dma_cg_en_q, gate_dma_busy_q, dma_clk_toggling);
      u_cg_zeroer_gate.sample(gate_zeroer_cg_en_q, gate_zeroer_busy_q, zeroer_axi_clk_toggling);
    end
  end
`endif

endmodule : smc_clk_fcov
