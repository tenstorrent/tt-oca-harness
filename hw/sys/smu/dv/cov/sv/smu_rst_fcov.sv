// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU reset, power-good and boot-completion functional coverage, from the
// SMU-RST-*, SMU-PWRGOOD, SMU-BOOTSEQ-GATE, SMU-FUSE-SENSE, SMU-MEMINIT and
// SMU-CLK-DOMAINS.S4 scenarios of the feature list. The point names are the
// scenarios' required_cells.
//
// One passive, signal-driven module shared by tb_top and tb_wrapper_top.
// Every port is a signal both benches expose at their top level; a bench
// without a signal ties the port off, and the cell map records the bench
// the point can fire in.
//
// DISABLE CONVENTION, as in smu_boot_fcov: the gate is powergood, not reset,
// so the reset sequence itself stays observable.
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
  // ties sep_fuse_sense_done_o to 0 and both benches tie the two block
  // resets off, so the points that read them are dropped rather than
  // carried unhittable.
  parameter bit SepPresent = 1'b1
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

  // Per-block resets in the primary domain, as the blocks see them. The
  // block bench exposes only the SMC one and ties the rest off.
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
  input wire [31:0] jtag_ptap_state_i
);

  localparam logic [31:0] PtapTestLogicReset = 32'(jtag_tap_pkg::TEST_LOGIC_RESET);

  wire not_powered = (powergood_i !== 1'b1);

  // ------------------------------------------------------------------
  // Cold reset pin against the stable ref-clock output, on clk_ref.
  // ------------------------------------------------------------------
  logic cold_ni_q, cold_ni_qq, cold_stable_q, primary_ref_q;
  always_ff @(posedge clk_ref_i) begin
    if (not_powered) begin
      cold_ni_q <= 1'b0;
      cold_ni_qq <= 1'b0;
      cold_stable_q <= 1'b0;
      primary_ref_q <= 1'b0;
    end else begin
      cold_ni_q <= rst_cold_ni;
      cold_ni_qq <= cold_ni_q;
      cold_stable_q <= rst_cold_stable_ref_clk_ni;
      primary_ref_q <= rst_primary_ref_clk_ni;
    end
  end

  wire cold_pin_fell_e = (rst_cold_ni === 1'b0) && (cold_ni_q === 1'b1);
  wire cold_stable_fell_e = (rst_cold_stable_ref_clk_ni === 1'b0) && (cold_stable_q === 1'b1);
  wire cold_stable_rose_e = (rst_cold_stable_ref_clk_ni === 1'b1) && (cold_stable_q === 1'b0);
  wire primary_ref_rose_e = (rst_primary_ref_clk_ni === 1'b1) && (primary_ref_q === 1'b0);

  // Assertion reached the output inside the same clk_ref period the pin fell
  // in: no clock edge was needed between the two.
  wire cold_reset_async_assert_without_clock_e = cold_pin_fell_e && cold_stable_fell_e;
  // Release reached the output at least one full clk_ref period after the pin
  // rose; two periods is the synchronizer depth.
  wire cold_reset_sync_deassert_e = cold_stable_rose_e && (cold_ni_q === 1'b1);
  wire cold_stable_ref_clk_synchronized_e =
      cold_reset_sync_deassert_e && (cold_ni_qq === 1'b1);
  // The output falls only while the pin is asserted low.
  wire cold_stable_ref_clk_active_low_e = cold_stable_fell_e && (rst_cold_ni === 1'b0);
  wire primary_ref_reset_synchronized_to_clk_ref_e =
      primary_ref_rose_e && (cold_ni_q === 1'b1) && (cold_ni_qq === 1'b1);
  `OCAH_FCOV_COVER(c_cold_reset_async_assert_without_clock,
                   cold_reset_async_assert_without_clock_e, clk_ref_i, not_powered)
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
  if (SepPresent) begin : g_sep
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

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroups: the release ordering across the
  // four blocks, which a flat point list cannot cross.
  // ------------------------------------------------------------------
  covergroup cg_block_release with function sample (
      logic smc_rst, logic dtp_rst, logic sep_rst, logic xbar_rst
  );
    option.per_instance = 1;
    cp_smc: coverpoint smc_rst;
    cp_dtp: coverpoint dtp_rst;
    cp_sep: coverpoint sep_rst;
    cp_xbar: coverpoint xbar_rst;
    x_blocks: cross cp_smc, cp_dtp, cp_sep, cp_xbar;
  endgroup

  cg_block_release u_cg_block_release = new();

  always_ff @(posedge clk_smu_i) begin
    if (!not_powered && primary_smc_rose_e) begin
      u_cg_block_release.sample(smc_rst_ni, dtp_rst_ni, sep_rst_ni, xbar_rst_ni);
    end
  end
`endif

endmodule : smu_rst_fcov
