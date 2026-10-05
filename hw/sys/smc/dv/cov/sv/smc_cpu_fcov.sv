// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC CPU-cluster and boot functional coverage: cores retiring, the reset
// vector, ROM and scratchpad traffic from the cluster, memory-init and
// cluster-isolation ordering, the cold-boot chain, and the cluster-side
// interrupt and debug outputs.
//
// The cluster's own buses are inside smc_wrapper, so the CPU-side evidence
// is what the tb lifts: the retired PCs, the DV counters bound onto the
// memory macros, and the cpu_ctrl scratch registers firmware writes.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or a smc_wrapper boundary port.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_cpu_fcov #(
  parameter int unsigned CUSTOM_ACTION_WIDTH = 1
) (
  input wire clk_smc_i,
  input wire rst_cold_ni,
  input wire rst_primary_smc_clk_ni,
  input wire powergood_stable_i,
  input wire fuse_sense_done_i,

  // Cluster state.
  input wire core_reset_ni,
  input wire init_mem_done_i,
  input wire cluster_isolate_i,

  // Retirement.
  input wire cpu_trace_valid_i,
  input wire [57:0] cpu_trace_pc_i,
  input wire [57:0] wb_pc1_i,
  input wire [57:0] wb_pc2_i,
  input wire [57:0] wb_pc3_i,

  // Memory-macro DV counters and the cpu_ctrl scratch registers.
  input wire [31:0] rom_read_count_i,
  input wire [31:0] scratch_read_count_i,
  input wire [31:0] scratch_write_count_i,
  input wire [31:0] scratch_0_i,
  input wire [31:0] scratch_2_i,

  // External managers' write handshakes, to attribute a scratch write to the
  // cluster rather than to an inbound manager.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire sys_awvalid_i,
  input wire sys_awready_i,
  input wire sys_bvalid_i,
  input wire sys_bready_i,
  input wire jtag_awvalid_i,
  input wire jtag_awready_i,
  input wire jtag_bvalid_i,
  input wire jtag_bready_i,

  // Cluster-side interrupt vector and debug outputs.
  input wire zeroer_intp_i,
  input wire [CUSTOM_ACTION_WIDTH-1:0] cla_custom_action_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Retirement. Hart 0 has a trace bundle; the other harts expose only the
  // writeback PC, which has no reset, so a change is only counted between
  // two known values.
  // ------------------------------------------------------------------
  logic [57:0] wb_pc1_q, wb_pc2_q, wb_pc3_q;
  always_ff @(posedge clk_smc_i) begin
    wb_pc1_q <= wb_pc1_i;
    wb_pc2_q <= wb_pc2_i;
    wb_pc3_q <= wb_pc3_i;
  end

  wire core_running = (core_reset_ni === 1'b1);
  wire core0_retire_e = core_running && (cpu_trace_valid_i === 1'b1);
  wire core1_retire_e = (wb_pc1_i !== wb_pc1_q) && (^wb_pc1_i !== 1'bx) && (^wb_pc1_q !== 1'bx);
  wire core2_retire_e = (wb_pc2_i !== wb_pc2_q) && (^wb_pc2_i !== 1'bx) && (^wb_pc2_q !== 1'bx);
  wire core3_retire_e = (wb_pc3_i !== wb_pc3_q) && (^wb_pc3_i !== 1'bx) && (^wb_pc3_q !== 1'bx);
  `OCAH_FCOV_COVER(c_core0_retire, core0_retire_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_core1_retire, core1_retire_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_core2_retire, core2_retire_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_core3_retire, core3_retire_e, clk_smc_i, in_reset)

  // The instruction at the cold-reset vector retiring on hart 0.
  wire first_fetch_at_vector_e = (cpu_trace_valid_i === 1'b1)
      && (cpu_trace_pc_i === 58'h0_0000_C004_0000);
  `OCAH_FCOV_COVER(c_first_fetch_at_c0040000, first_fetch_at_vector_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_first_fetch_at_rom_vector, first_fetch_at_vector_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Cluster traffic into the memory macros: the bound DV counters advance.
  // ------------------------------------------------------------------
  logic [31:0] rom_read_count_q, scratch_read_count_q, scratch_write_count_q;
  always_ff @(posedge clk_smc_i) begin
    rom_read_count_q <= rom_read_count_i;
    scratch_read_count_q <= scratch_read_count_i;
    scratch_write_count_q <= scratch_write_count_i;
  end
  wire rom_req_issued_e = (rom_read_count_i != rom_read_count_q);
  wire cpu_to_sram_read_e = (scratch_read_count_i != scratch_read_count_q);
  wire cpu_to_sram_write_e = (scratch_write_count_i != scratch_write_count_q);
  `OCAH_FCOV_COVER(c_rom_req_issued, rom_req_issued_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_cpu_to_sram_read, cpu_to_sram_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_cpu_to_sram_write, cpu_to_sram_write_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // A cluster MMIO write reaching a register block: a cpu_ctrl scratch
  // register changes while no inbound manager has a write in flight. An
  // inbound write updates the register before its B response, so a pending
  // external write is what rules the cluster out.
  // ------------------------------------------------------------------
  wire sep_aw_acc = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire sep_b_acc = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1);
  wire sys_aw_acc = (sys_awvalid_i === 1'b1) && (sys_awready_i === 1'b1);
  wire sys_b_acc = (sys_bvalid_i === 1'b1) && (sys_bready_i === 1'b1);
  wire jtag_aw_acc = (jtag_awvalid_i === 1'b1) && (jtag_awready_i === 1'b1);
  wire jtag_b_acc = (jtag_bvalid_i === 1'b1) && (jtag_bready_i === 1'b1);

  logic [7:0] sep_wr_out_q, sys_wr_out_q, jtag_wr_out_q;
  logic [31:0] scratch_0_q, scratch_2_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      sep_wr_out_q <= '0;
      sys_wr_out_q <= '0;
      jtag_wr_out_q <= '0;
    end else begin
      sep_wr_out_q <= sep_wr_out_q + 8'(sep_aw_acc) - 8'(sep_b_acc);
      sys_wr_out_q <= sys_wr_out_q + 8'(sys_aw_acc) - 8'(sys_b_acc);
      jtag_wr_out_q <= jtag_wr_out_q + 8'(jtag_aw_acc) - 8'(jtag_b_acc);
    end
    scratch_0_q <= scratch_0_i;
    scratch_2_q <= scratch_2_i;
  end

  wire ext_write_idle = (sep_wr_out_q == 8'd0) && (sys_wr_out_q == 8'd0)
      && (jtag_wr_out_q == 8'd0) && !sep_aw_acc && !sys_aw_acc && !jtag_aw_acc;
  wire scratch_changed = ((scratch_0_i !== scratch_0_q) && (^scratch_0_q !== 1'bx))
      || ((scratch_2_i !== scratch_2_q) && (^scratch_2_q !== 1'bx));
  wire mmio_write_peripheral_e = core_running && ext_write_idle && scratch_changed;
  `OCAH_FCOV_COVER(c_mmio_write_peripheral, mmio_write_peripheral_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Memory init and cluster boundary isolation. Low-during-init is the
  // power-up state, so it is qualified by init having completed once and
  // means "back in init after a later reset".
  // ------------------------------------------------------------------
  logic init_mem_done_q, init_done_seen_q, isolate_q, primary_smc_q;
  always_ff @(posedge clk_smc_i) begin
    init_mem_done_q <= init_mem_done_i;
    isolate_q <= cluster_isolate_i;
    primary_smc_q <= rst_primary_smc_clk_ni;
    if (in_reset) init_done_seen_q <= 1'b0;
    else if (init_mem_done_i === 1'b1) init_done_seen_q <= 1'b1;
  end

  wire init_done_rise = (init_mem_done_i === 1'b1) && (init_mem_done_q === 1'b0);
  wire isolate_fall = (cluster_isolate_i === 1'b0) && (isolate_q === 1'b1);
  wire release_primary_smc = (rst_primary_smc_clk_ni === 1'b1) && (primary_smc_q === 1'b0);

  wire init_done_low_during_init_e = init_done_seen_q && (init_mem_done_i === 1'b0);
  wire self_isolated_at_cold_boot_e = release_primary_smc && (cluster_isolate_i === 1'b1);
  wire release_requires_init_done_e = isolate_fall && (init_mem_done_i === 1'b1);
  wire release_requires_cores_out_of_reset_e = isolate_fall && core_running;
  `OCAH_FCOV_COVER(c_init_done_high_after_init, init_done_rise, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_init_done_low_during_init, init_done_low_during_init_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_self_isolated_at_cold_boot, self_isolated_at_cold_boot_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_release_requires_init_done, release_requires_init_done_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_release_requires_cores_out_of_reset, release_requires_cores_out_of_reset_e,
                   clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Cold-boot chain in order: powergood stable, then fuse sense done, then
  // the cluster leaves reset. The repair and MBIST completion inputs are
  // tied high in this tb, so those steps have no edge of their own here.
  // ------------------------------------------------------------------
  logic powergood_seen_q, fuse_sense_after_powergood_q, core_reset_q;
  logic step_out_of_order_q;
  wire fuse_sense_before_powergood = (fuse_sense_done_i === 1'b1) && !powergood_seen_q;
  always_ff @(posedge clk_smc_i) begin
    core_reset_q <= core_reset_ni;
    if (in_reset) begin
      powergood_seen_q <= 1'b0;
      fuse_sense_after_powergood_q <= 1'b0;
      step_out_of_order_q <= 1'b0;
    end else begin
      if (powergood_stable_i === 1'b1) powergood_seen_q <= 1'b1;
      if (powergood_seen_q && (fuse_sense_done_i === 1'b1)) fuse_sense_after_powergood_q <= 1'b1;
      // A step taken before the one the chain puts ahead of it.
      if (fuse_sense_before_powergood) step_out_of_order_q <= 1'b1;
      if (core_running && !fuse_sense_after_powergood_q) step_out_of_order_q <= 1'b1;
    end
  end
  wire core_reset_release = core_running && (core_reset_q === 1'b0);
  wire ordered_boot_chain_e = core_reset_release && fuse_sense_after_powergood_q;
  // The ordered release reached with no earlier step ever seen out of order,
  // which the chain point alone does not rule out.
  wire no_step_out_of_order_e = ordered_boot_chain_e && !step_out_of_order_q;
  `OCAH_FCOV_COVER(c_ordered_powergood_fusesense_repair_mbist_release, ordered_boot_chain_e,
                   clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_no_step_out_of_order, no_step_out_of_order_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Interrupt-vector internal range (zeroer interrupt is bit 323) and the
  // CLA custom action outputs.
  // ------------------------------------------------------------------
  // Both outputs are held levels once asserted, so each point takes the
  // asserting edge: the level is true for the rest of the run.
  logic zeroer_intp_q;
  logic custom_action_active_q;
  wire custom_action_active = (cla_custom_action_i !== '0) && (^cla_custom_action_i !== 1'bx);
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      zeroer_intp_q <= 1'b0;
      custom_action_active_q <= 1'b0;
    end else begin
      zeroer_intp_q <= (zeroer_intp_i === 1'b1);
      custom_action_active_q <= custom_action_active;
    end
  end

  wire internal_range_e = (zeroer_intp_i === 1'b1) && !zeroer_intp_q;
  wire custom_action_driven_e = custom_action_active && !custom_action_active_q;
  `OCAH_FCOV_COVER(c_internal_range_323_320, internal_range_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_custom_action_output_driven, custom_action_driven_e, clk_smc_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: which harts were seen retiring
  // together, which the flat per-hart list cannot cross.
  // ------------------------------------------------------------------
  covergroup cg_hart_retire with function sample (logic [3:0] harts);
    option.per_instance = 1;
    cp_harts: coverpoint harts {
      bins none = {4'b0000};
      bins single[] = {4'b0001, 4'b0010, 4'b0100, 4'b1000};
      bins several = default;
    }
  endgroup

  cg_hart_retire u_cg_hart_retire = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      u_cg_hart_retire.sample({core3_retire_e, core2_retire_e, core1_retire_e, core0_retire_e});
    end
  end
`endif

endmodule : smc_cpu_fcov
