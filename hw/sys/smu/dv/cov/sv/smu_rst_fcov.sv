// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU reset, power-good and boot-completion functional coverage, from the
// SMU-RST-*, SMU-PWRGOOD, SMU-BOOTSEQ-GATE, SMU-FUSE-SENSE, SMU-MEMINIT and
// SMU-CLK-DOMAINS.S4 scenarios of the feature list. The point names are the
// scenarios' required_cells.
//
// One passive, signal-driven module. Every port is a signal the bench
// exposes at its top level; a port the bench has no signal for is tied
// off, and the cell map records which points can fire.
//
// DISABLE CONVENTION, as in smu_boot_fcov: the gate is powergood, not reset,
// so the reset sequence itself stays observable. smu_secure_tm_window_cg
// also samples only while the owning leaf holds tb_fcov_gate high.
//
// SEP PRESENCE: the points whose observable only exists with SEP elaborated
// sit in the `g_sep` generate block, so a SEP=0 build carries no unhittable
// point and one coverage policy can grade both elaborations.
//
// Points must need stimulus beyond power-up and reset release: every point
// is an edge, or a level qualified by a sticky record of the event that
// makes it meaningful.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_rst_fcov #(
  // 0 on an elaboration without SEP. The SEP and crossbar block resets and
  // the SEP fuse-sense pin come out of smu.sv's gen_sep branch; gen_no_sep
  // ties sep_fuse_sense_done_o to 0 and the bench ties the two block
  // resets off, so the points that read them are dropped rather than
  // carried unhittable.
  parameter bit SEP_PRESENT = 1'b1
) (
  input wire clk_ref_i,
  input wire clk_smu_i,
  input wire clk_periph_i,

  // Power and cold reset stimulus, and the boot-sequence gate.
  input wire powergood_i,
  input wire rst_cold_ni,
  input wire ext_boot_seq_done_i,

  // Reset outputs at the SMU boundary.
  input wire rst_cold_stable_ref_clk_ni,
  input wire rst_primary_ref_clk_ni,
  input wire rst_primary_smc_clk_ni,
  input wire rst_primary_periph_clk_ni,

  // Per-block resets in the primary domain, as the blocks see them.
  input wire smc_rst_ni,
  input wire dtp_rst_ni,
  input wire sep_rst_ni,
  input wire xbar_rst_ni,

  // Boot-time completion pins.
  input wire fuse_sense_done_i,
  input wire sep_fuse_sense_done_i,
  input wire fuse_reset_n_delayed_i,
  input wire skip_mem_repair_i,
  input wire init_mem_done_i,
  input wire disable_sram_auto_init_i,

  // PTAP state, one-hot jtag_tap_pkg::tap_state_e widened to 32 bits.
  input wire [31:0] jtag_ptap_state_i,
  input wire fcov_gate_i,  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire sep_clk_i,  // SEP wrapper clock mirror; its edges time the early capture.
  input wire secure_tm_req_i,  // Secure test-mode request strap the bench drives.
  input wire secure_tm_i,  // Secure test-mode output of the SEP eFuse wrapper.
  input wire sep_efuse_shim_resp_valid_i  // SEP eFuse SHIM fuse-command response valid.
);

  localparam logic [31:0] PtapTestLogicReset = 32'(jtag_tap_pkg::TEST_LOGIC_RESET);
  // `port_table.adoc`, `rst_cold_ni`: assertion is de-glitched for 32 clk_ref
  // cycles.
  localparam logic [5:0] ColdDeglitchCycles = 6'd32;

  wire not_powered = (powergood_i !== 1'b1);
  wire gate_on = (fcov_gate_i === 1'b1);

  // ------------------------------------------------------------------
  // Cold reset pin against the stable ref-clock output, on clk_ref.
  // ------------------------------------------------------------------
  logic cold_ni_q, cold_ni_qq, cold_stable_q, primary_ref_q;
  logic [5:0] cold_low_cnt_q;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered) begin
      cold_ni_q <= 1'b0;
      cold_ni_qq <= 1'b0;
      cold_stable_q <= 1'b0;
      primary_ref_q <= 1'b0;
      cold_low_cnt_q <= '0;
    end else begin
      cold_ni_q <= rst_cold_ni;
      cold_ni_qq <= cold_ni_q;
      cold_stable_q <= rst_cold_stable_ref_clk_ni;
      primary_ref_q <= rst_primary_ref_clk_ni;
      if (rst_cold_ni !== 1'b0) cold_low_cnt_q <= '0;
      else if (cold_low_cnt_q != ColdDeglitchCycles) cold_low_cnt_q <= cold_low_cnt_q + 6'd1;
    end
  end

  wire cold_stable_fell_e = (rst_cold_stable_ref_clk_ni === 1'b0) && (cold_stable_q === 1'b1);
  wire cold_stable_rose_e = (rst_cold_stable_ref_clk_ni === 1'b1) && (cold_stable_q === 1'b0);
  wire primary_ref_rose_e = (rst_primary_ref_clk_ni === 1'b1) && (primary_ref_q === 1'b0);

  // Assertion reached the output only after the pin had been sampled low on
  // ColdDeglitchCycles consecutive clk_ref edges.
  wire cold_reset_deglitched_assert_e =
      cold_stable_fell_e && (cold_low_cnt_q == ColdDeglitchCycles);
  // Release reached the output at least one full clk_ref period after the pin
  // rose; two periods is the synchronizer depth.
  wire cold_reset_sync_deassert_e = cold_stable_rose_e && (cold_ni_q === 1'b1);
  wire cold_stable_ref_clk_synchronized_e =
      cold_reset_sync_deassert_e && (cold_ni_qq === 1'b1);
  // The output falls only while the pin is asserted low.
  wire cold_stable_ref_clk_active_low_e = cold_stable_fell_e && (rst_cold_ni === 1'b0);
  wire primary_ref_reset_synchronized_to_clk_ref_e =
      primary_ref_rose_e && (cold_ni_q === 1'b1) && (cold_ni_qq === 1'b1);
  `OCAH_FCOV_COVER(c_cold_reset_deglitched_assert, cold_reset_deglitched_assert_e, clk_ref_i,
                   not_powered)
  `OCAH_FCOV_COVER(c_cold_reset_sync_deassert, cold_reset_sync_deassert_e, clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_cold_stable_ref_clk_synchronized, cold_stable_ref_clk_synchronized_e,
                   clk_ref_i, not_powered)
  `OCAH_FCOV_COVER(c_cold_stable_ref_clk_active_low, cold_stable_ref_clk_active_low_e, clk_ref_i,
                   not_powered)
  `OCAH_FCOV_COVER(c_primary_ref_reset_synchronized_to_clk_ref,
                   primary_ref_reset_synchronized_to_clk_ref_e, clk_ref_i, not_powered)

  // ------------------------------------------------------------------
  // Primary-domain release and the per-block resets, on clk_smu.
  // ------------------------------------------------------------------
  logic cold_ni_smu_q, cold_ni_smu_qq, cold_stable_smu_q, primary_smc_q;
  logic smc_rst_q, dtp_rst_q;
  always_ff @(posedge clk_smu_i) begin
    if (not_powered) begin
      cold_ni_smu_q <= 1'b0;
      cold_ni_smu_qq <= 1'b0;
      cold_stable_smu_q <= 1'b0;
      primary_smc_q <= 1'b0;
      smc_rst_q <= 1'b0;
      dtp_rst_q <= 1'b0;
    end else begin
      cold_ni_smu_q <= rst_cold_ni;
      cold_ni_smu_qq <= cold_ni_smu_q;
      cold_stable_smu_q <= rst_cold_stable_ref_clk_ni;
      primary_smc_q <= rst_primary_smc_clk_ni;
      smc_rst_q <= smc_rst_ni;
      dtp_rst_q <= dtp_rst_ni;
    end
  end

  wire primary_smc_rose_e = (rst_primary_smc_clk_ni === 1'b1) && (primary_smc_q === 1'b0);
  wire primary_released = (rst_primary_smc_clk_ni === 1'b1);
  wire primary_smc_reset_synchronized_to_clk_smu_e =
      primary_smc_rose_e && (cold_ni_smu_q === 1'b1) && (cold_ni_smu_qq === 1'b1);
  wire smc_released_e = (smc_rst_ni === 1'b1) && (smc_rst_q === 1'b0) && primary_released;
  wire dtp_released_e = (dtp_rst_ni === 1'b1) && (dtp_rst_q === 1'b0) && primary_released;
  `OCAH_FCOV_COVER(c_primary_smc_reset_synchronized_to_clk_smu,
                   primary_smc_reset_synchronized_to_clk_smu_e, clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_smc_released, smc_released_e, clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_dtp_released, dtp_released_e, clk_smu_i, not_powered)

  // ------------------------------------------------------------------
  // Boot-time completions: fuse sense, the boot-sequence gate, memory init.
  // The gate point is qualified by the gate having been held low after the
  // cold release, so it means "the held release went ahead" rather than
  // "the gate was never applied".
  // ------------------------------------------------------------------
  logic fuse_sense_q, fuse_rst_q, init_mem_q, gate_low_seen_q;
  always_ff @(posedge clk_smu_i) begin
    if (not_powered) begin
      fuse_sense_q <= 1'b0;
      fuse_rst_q <= 1'b0;
      init_mem_q <= 1'b0;
      gate_low_seen_q <= 1'b0;
    end else begin
      fuse_sense_q <= fuse_sense_done_i;
      fuse_rst_q <= fuse_reset_n_delayed_i;
      init_mem_q <= init_mem_done_i;
      if ((ext_boot_seq_done_i === 1'b0) && (rst_cold_ni === 1'b1)) gate_low_seen_q <= 1'b1;
    end
  end

  wire fuse_sense_done_e = (fuse_sense_done_i === 1'b1) && (fuse_sense_q === 1'b0);
  wire fuse_reset_release_e = (fuse_reset_n_delayed_i === 1'b1) && (fuse_rst_q === 1'b0);
  wire init_mem_done_e = (init_mem_done_i === 1'b1) && (init_mem_q === 1'b0);
  wire fuse_reset_n_delayed_released_after_sense_e =
      fuse_reset_release_e && (fuse_sense_q === 1'b1) && (cold_stable_smu_q === 1'b1);
  wire reset_release_after_boot_seq_done_e =
      fuse_reset_release_e && gate_low_seen_q && (ext_boot_seq_done_i === 1'b1);
  wire skip_mem_repair_present_e = fuse_sense_done_e && !$isunknown(skip_mem_repair_i);
  wire auto_init_runs_e = init_mem_done_e && (disable_sram_auto_init_i === 1'b0);
  `OCAH_FCOV_COVER(c_fuse_reset_n_delayed_released_after_sense,
                   fuse_reset_n_delayed_released_after_sense_e, clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_reset_release_after_boot_seq_done, reset_release_after_boot_seq_done_e,
                   clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_skip_mem_repair_present, skip_mem_repair_present_e, clk_smu_i, not_powered)
  `OCAH_FCOV_COVER(c_auto_init_runs, auto_init_runs_e, clk_smu_i, not_powered)

  // ------------------------------------------------------------------
  // SEP-side release and completion: the SEP and crossbar block resets
  // rising inside the released primary domain, and the SEP fuse-sense pin
  // asserting. Only elaborated with SEP present -- both blocks live in
  // smu.sv's gen_sep branch and the pin is tied to 0 without it.
  // ------------------------------------------------------------------
  if (SEP_PRESENT) begin : g_sep
    logic sep_rst_q, xbar_rst_q, sep_fuse_sense_q;
    always_ff @(posedge clk_smu_i) begin
      if (not_powered) begin
        sep_rst_q <= 1'b0;
        xbar_rst_q <= 1'b0;
        sep_fuse_sense_q <= 1'b0;
      end else begin
        sep_rst_q <= sep_rst_ni;
        xbar_rst_q <= xbar_rst_ni;
        sep_fuse_sense_q <= sep_fuse_sense_done_i;
      end
    end

    wire sep_released_e = (sep_rst_ni === 1'b1) && (sep_rst_q === 1'b0) && primary_released;
    wire xbar_released_e = (xbar_rst_ni === 1'b1) && (xbar_rst_q === 1'b0) && primary_released;
    wire sep_fuse_sense_done_asserted_e =
        (sep_fuse_sense_done_i === 1'b1) && (sep_fuse_sense_q === 1'b0);
    `OCAH_FCOV_COVER(c_sep_released, sep_released_e, clk_smu_i, not_powered)
    `OCAH_FCOV_COVER(c_xbar_released, xbar_released_e, clk_smu_i, not_powered)
    `OCAH_FCOV_COVER(c_sep_fuse_sense_done_asserted, sep_fuse_sense_done_asserted_e, clk_smu_i,
                     not_powered)

    // smu_secure_tm_window_cg (SMU_FCOV.adoc): the strap pulse inside the
    // owner's window, from its cold-reset release to after the sense that
    // follows. cp_early_position is measured only: the pulse against the
    // first and second rising SEP clock edges after the SEP reset rises (ends
    // before the first, covers the first only, the second only, both, starts
    // after the second). cp_sense_position is the response strobe count of
    // the sense at the strap's fall, in thirds of the 256-word sense, sampled
    // at the gate's fall after at least 512 clk_smu samples past the
    // completion rise, with the strap at 0 at the rise and secure_tm_o never 1
    // in the window. A sample of one coverpoint hands the other a value no bin
    // lists. The strobe count and the edge tracker clear while rst_cold_ni is
    // low, since a cold reset starts a new sense (test_mode.adoc).
    covergroup smu_secure_tm_window_cg with function sample (
        logic [2:0] early_cls, logic [1:0] drop_third
    );
      option.per_instance = 1;
      cp_early_position: coverpoint early_cls {
        bins ends_before_first = {3'd0};
        bins covers_first_only = {3'd1};
        bins covers_second_only = {3'd2};
        bins covers_both = {3'd3};
        bins starts_after_second = {3'd4};
      }
      cp_sense_position: coverpoint drop_third {
        bins drop_1_85 = {2'd0}; bins drop_86_170 = {2'd1}; bins drop_171_255 = {2'd2};
      }
    endgroup

    smu_secure_tm_window_cg u_cg_secure_tm_window = new();

    localparam logic [2:0] EarlyEndsBeforeFirst = 3'd0;
    localparam logic [2:0] EarlyCoversFirstOnly = 3'd1;
    localparam logic [2:0] EarlyCoversSecondOnly = 3'd2;
    localparam logic [2:0] EarlyCoversBoth = 3'd3;
    localparam logic [2:0] EarlyStartsAfterSecond = 3'd4;
    localparam logic [2:0] NoEarly = 3'd7;
    localparam logic [1:0] NoThird = 2'd3;

    // Thirds of the 256-word sense: 1 to 85, 86 to 170, 171 to 255.
    function automatic logic [1:0] third_of(input logic [8:0] strobes);
      if (strobes == '0 || strobes > 9'd255) return NoThird;
      if (strobes <= 9'd85) return 2'd0;
      if (strobes <= 9'd170) return 2'd1;
      return 2'd2;
    endfunction

    wire cold_low = (rst_cold_ni !== 1'b1);
    wire strap_on = (secure_tm_req_i === 1'b1);

    // Response strobes of the sense, the strobe count at the strap's fall,
    // secure_tm_o seen at 1, the strap at 0 at the completion rise and the
    // clk_smu samples after it, on clk_smu.
    localparam logic [9:0] AfterRiseSamples = 10'd512;
    logic resp_valid_q, strap_q, dropped_q, tm_seen_q, rise_ok_q, gate_q;
    logic [8:0] strobe_cnt_q, drop_cnt_q;
    logic [9:0] after_cnt_q;
    wire resp_rose = (sep_efuse_shim_resp_valid_i === 1'b1) && (resp_valid_q === 1'b0);
    wire strap_fell = (secure_tm_req_i === 1'b0) && (strap_q === 1'b1);
    wire rise_ok_e = gate_on && sep_fuse_sense_done_asserted_e && dropped_q
        && (secure_tm_req_i === 1'b0);
    wire sense_position_e = gate_q && !gate_on && rise_ok_q
        && (after_cnt_q >= AfterRiseSamples) && !tm_seen_q;
    always_ff @(posedge clk_smu_i) begin
      if (not_powered) begin
        resp_valid_q <= 1'b0;
        strap_q <= 1'b0;
        dropped_q <= 1'b0;
        tm_seen_q <= 1'b0;
        rise_ok_q <= 1'b0;
        gate_q <= 1'b0;
        strobe_cnt_q <= '0;
        drop_cnt_q <= '0;
        after_cnt_q <= '0;
      end else begin
        resp_valid_q <= sep_efuse_shim_resp_valid_i;
        strap_q <= strap_on;
        if (cold_low) begin
          dropped_q <= 1'b0;
          tm_seen_q <= 1'b0;
          rise_ok_q <= 1'b0;
          gate_q <= 1'b0;
          strobe_cnt_q <= '0;
          drop_cnt_q <= '0;
          after_cnt_q <= '0;
        end else begin
          gate_q <= gate_on;
          if (resp_rose && (strobe_cnt_q != '1)) strobe_cnt_q <= strobe_cnt_q + 9'd1;
          if (gate_on && strap_fell) begin
            drop_cnt_q <= strobe_cnt_q;
            dropped_q <= 1'b1;
          end
          if (gate_on && (secure_tm_i === 1'b1)) tm_seen_q <= 1'b1;
          if (rise_ok_e) rise_ok_q <= 1'b1;
          if (rise_ok_q && (after_cnt_q != '1)) after_cnt_q <= after_cnt_q + 10'd1;
        end
        if (sense_position_e) u_cg_secure_tm_window.sample(NoEarly, third_of(drop_cnt_q));
      end
    end

    // The two rising SEP clock edges after the SEP reset rises, the strap at
    // each, and a pulse that rose and fell before the first, on the SEP clock.
    logic sep_rst_s_q, strap_s_q, rose_s_q, pulse_before_e1_q, strap_e1_q, pending_q;
    logic [1:0] edge_cnt_q;
    wire sep_rst_rose_s = (sep_rst_ni === 1'b1) && (sep_rst_s_q === 1'b0);
    wire strap_rose_s = strap_on && (strap_s_q === 1'b0);
    wire strap_fell_s = (secure_tm_req_i === 1'b0) && (strap_s_q === 1'b1);
    wire early_e1 = gate_on && sep_rst_rose_s && (edge_cnt_q == 2'd0);
    wire early_e2 = gate_on && (edge_cnt_q == 2'd1);
    wire [2:0] early_at_e2 = (strap_e1_q && strap_on) ? EarlyCoversBoth
        : strap_e1_q ? EarlyCoversFirstOnly
        : strap_on ? EarlyCoversSecondOnly
        : pulse_before_e1_q ? EarlyEndsBeforeFirst : NoEarly;
    always_ff @(posedge sep_clk_i) begin
      if (not_powered) begin
        sep_rst_s_q <= 1'b0;
        strap_s_q <= 1'b0;
        rose_s_q <= 1'b0;
        pulse_before_e1_q <= 1'b0;
        strap_e1_q <= 1'b0;
        pending_q <= 1'b0;
        edge_cnt_q <= '0;
      end else begin
        sep_rst_s_q <= sep_rst_ni;
        strap_s_q <= strap_on;
        if (cold_low) begin
          rose_s_q <= 1'b0;
          pulse_before_e1_q <= 1'b0;
          strap_e1_q <= 1'b0;
          pending_q <= 1'b0;
          edge_cnt_q <= '0;
        end else begin
          if (gate_on && (edge_cnt_q == 2'd0)) begin
            if (strap_rose_s) rose_s_q <= 1'b1;
            if (strap_fell_s && rose_s_q) pulse_before_e1_q <= 1'b1;
          end
          if (early_e1) begin
            strap_e1_q <= strap_on;
            edge_cnt_q <= 2'd1;
          end
          if (early_e2) begin
            edge_cnt_q <= 2'd2;
            if (early_at_e2 != NoEarly) u_cg_secure_tm_window.sample(early_at_e2, NoThird);
            else pending_q <= 1'b1;
          end
          if (gate_on && pending_q && strap_rose_s) begin
            u_cg_secure_tm_window.sample(EarlyStartsAfterSecond, NoThird);
            pending_q <= 1'b0;
          end
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // DTP responsive under power-good: the PTAP was seen in Test-Logic-Reset
  // and has since left it.
  // ------------------------------------------------------------------
  logic tlr_seen_q;
  always_ff @(posedge clk_smu_i) begin
    if (not_powered) begin
      tlr_seen_q <= 1'b0;
    end else begin
      if (jtag_ptap_state_i === PtapTestLogicReset) tlr_seen_q <= 1'b1;
    end
  end

  wire dtp_responsive_after_powergood_stable_e =
      tlr_seen_q && (jtag_ptap_state_i !== PtapTestLogicReset) && (powergood_i === 1'b1);
  `OCAH_FCOV_COVER(c_dtp_responsive_after_powergood_stable,
                   dtp_responsive_after_powergood_stable_e, clk_smu_i, not_powered)

  // ------------------------------------------------------------------
  // Peripheral domain: its reset release observed in its own clock domain.
  // ------------------------------------------------------------------
  logic periph_rst_q;
  always_ff @(posedge clk_periph_i) begin
    if (not_powered) begin
      periph_rst_q <= 1'b0;
    end else begin
      periph_rst_q <= rst_primary_periph_clk_ni;
    end
  end

  wire periph_domain_active_e = (rst_primary_periph_clk_ni === 1'b1) && (periph_rst_q === 1'b0);
  `OCAH_FCOV_COVER(c_periph_domain_active, periph_domain_active_e, clk_periph_i, not_powered)

  // ------------------------------------------------------------------
  // Covergroup: the release ordering across the four blocks, which a flat
  // point list cannot cross.
  // ------------------------------------------------------------------
  covergroup cg_block_release with function sample (
      logic smc_rst, logic dtp_rst, logic sep_rst, logic xbar_rst
  );
    option.per_instance = 1;
    // Sampled at the primary SMC reset's release edge. The block resets
    // release ahead of the primary, so every one of them reads released
    // at that edge.
    cp_smc: coverpoint smc_rst {
      ignore_bins held_at_primary_release = {1'b0};
    }
    cp_dtp: coverpoint dtp_rst {ignore_bins held_at_primary_release = {1'b0};}
    cp_sep: coverpoint sep_rst {ignore_bins held_at_primary_release = {1'b0};}
    cp_xbar: coverpoint xbar_rst {ignore_bins held_at_primary_release = {1'b0};}
    x_blocks: cross cp_smc, cp_dtp, cp_sep, cp_xbar;
  endgroup

  cg_block_release u_cg_block_release = new();

  always_ff @(posedge clk_smu_i) begin
    if (!not_powered && primary_smc_rose_e) begin
      u_cg_block_release.sample(smc_rst_ni, dtp_rst_ni, sep_rst_ni, xbar_rst_ni);
    end
  end

endmodule : smu_rst_fcov
