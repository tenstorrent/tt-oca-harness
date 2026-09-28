// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC interrupt-routing functional coverage: the raw cpu_interrupts vector
// against the PLIC source index it becomes, the AXI hang OR, the NDM reset
// request on its way to its vector bit, and the SYNC_REG software bit.
//
// The interrupt chapter states the PLIC source ID is the raw vector bit index
// plus one, so each point pairs a raw bit with the PLIC pending bit that must
// carry it. A point on either half alone would not show the relationship.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_int_fcov #(
  parameter int unsigned CpuInterruptCount = 328,
  parameter int unsigned ExtInterruptCount = 256,
  parameter int unsigned CpuClusterCount = 4
) (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  input wire [CpuInterruptCount-1:0] cpu_interrupts_i,

  // AXI hang detector legs, whose OR is the peripheral bit.
  input wire hang_sys_i,
  input wire hang_sep_i,
  input wire hang_data_i,

  // PLIC pending bits for sources 1..3 and 324.
  input wire [2:0] plic_pending_low_i,
  input wire plic_pending_324_i,

  // PLIC claim and the winning source it returns, plus one context's
  // programmed threshold / enable word and the machine-mode delivery pin.
  input wire plic_claim0_i,
  input wire [8:0] plic_maxdev0_i,
  input wire [2:0] plic_threshold0_i,
  input wire [6:0] plic_enables0_i,
  input wire [CpuClusterCount-1:0] plic_meip_i,

  // NDM reset request, before and after the synchronizer.
  input wire [CpuClusterCount-1:0] ndmreset_request_i,
  input wire [CpuClusterCount-1:0] ndmreset_request_sync_i,

  // SYNC_REG.sync reflected on sync_irq_o.
  input wire sync_irq_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  localparam int unsigned HangBit = ExtInterruptCount + 30;
  localparam int unsigned NdmBit = ExtInterruptCount + 11;
  localparam int unsigned ZeroerBit = ExtInterruptCount + 64 + 3;

  // ------------------------------------------------------------------
  // The AXI hang OR on its vector bit. The bit alone is the OR output; the
  // point is qualified by a leg being up so it cannot be read as a stuck
  // vector bit.
  // ------------------------------------------------------------------
  wire hang_leg_up = (hang_sys_i === 1'b1) || (hang_sep_i === 1'b1) || (hang_data_i === 1'b1);
  wire hang_or_bit286_e = hang_leg_up && (cpu_interrupts_i[HangBit] === 1'b1);
  `OCAH_FCOV_COVER(c_hang_or_bit286, hang_or_bit286_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Raw vector bit index to PLIC source index. Source N+1 pending while raw
  // bit N is asserted is the relationship the chapter states.
  // ------------------------------------------------------------------
  // The zeroer completion is a one-cycle pulse on the raw vector and the PLIC
  // gateway latches it some cycles later, so the raw half is held from the
  // pulse until the pending bit it raised falls again.
  logic zeroer_bit_seen_q, pending_324_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      zeroer_bit_seen_q <= 1'b0;
      pending_324_q <= 1'b0;
    end else begin
      pending_324_q <= (plic_pending_324_i === 1'b1);
      if (cpu_interrupts_i[ZeroerBit] === 1'b1) zeroer_bit_seen_q <= 1'b1;
      else if (pending_324_q && (plic_pending_324_i === 1'b0)) zeroer_bit_seen_q <= 1'b0;
    end
  end

  wire bit0_source1_e = (cpu_interrupts_i[0] === 1'b1) && (plic_pending_low_i[0] === 1'b1);
  wire bit323_source324_e = zeroer_bit_seen_q && (plic_pending_324_i === 1'b1);
  wire arbitrary_bit_plus_one_e =
      ((cpu_interrupts_i[1] === 1'b1) && (plic_pending_low_i[1] === 1'b1))
      || ((cpu_interrupts_i[2] === 1'b1) && (plic_pending_low_i[2] === 1'b1));
  `OCAH_FCOV_COVER(c_bit0_source1, bit0_source1_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_bit323_source324, bit323_source324_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_arbitrary_bit_plus_one, arbitrary_bit_plus_one_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Claim. maxDevs is the winning source the claim read returns; zero means
  // nothing was pending above the threshold.
  // ------------------------------------------------------------------
  wire claim = (plic_claim0_i === 1'b1);
  wire claim_highest_e = claim && (plic_maxdev0_i !== 9'd0) && (^plic_maxdev0_i !== 1'bx);
  wire claim_zero_e = claim && (plic_maxdev0_i === 9'd0);
  `OCAH_FCOV_COVER(c_claim_returns_highest_priority, claim_highest_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_claim_returns_zero_when_none_pending, claim_zero_e, clk_smc_i, in_reset)

  // Delivery once the context registers carry programmed values: an enable
  // word written and the machine-mode pin up. The reset state of both is
  // zero, so the point cannot fire on an uninitialised PLIC.
  wire plic_initialised = (plic_enables0_i !== 7'd0) && (^plic_enables0_i !== 1'bx)
      && (^plic_threshold0_i !== 1'bx);
  wire delivery_after_init_e = plic_initialised && (plic_meip_i !== '0);
  `OCAH_FCOV_COVER(c_delivery_after_full_initialization, delivery_after_init_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // NDM reset request: the asynchronous request, its synchronized copy and
  // the OR-reduction that drives the vector bit.
  // ------------------------------------------------------------------
  logic ndm_sync_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) ndm_sync_seen_q <= 1'b0;
    else if (ndmreset_request_sync_i !== '0) ndm_sync_seen_q <= 1'b1;
  end

  wire ndm_synchronized_e = (ndmreset_request_i !== '0) && (ndmreset_request_sync_i !== '0);
  wire ndm_or_reduced_e = (ndmreset_request_sync_i !== '0)
      && (cpu_interrupts_i[NdmBit] === 1'b1);
  wire ndm_cleared_e = ndm_sync_seen_q && (ndmreset_request_sync_i === '0)
      && (cpu_interrupts_i[NdmBit] === 1'b0);
  `OCAH_FCOV_COVER(c_ndm_request_synchronized, ndm_synchronized_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_ndm_or_reduced_to_bit267, ndm_or_reduced_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_ndm_request_cleared, ndm_cleared_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // SYNC_REG.sync on sync_irq_o. Both points are edges: the deasserted level
  // is the power-on state and would be hit with no software write at all.
  // ------------------------------------------------------------------
  logic sync_irq_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) sync_irq_q <= 1'b0;
    else sync_irq_q <= sync_irq_i;
  end

  wire sync_bit_set_e = (sync_irq_i === 1'b1) && (sync_irq_q === 1'b0);
  wire sync_bit_cleared_e = (sync_irq_i === 1'b0) && (sync_irq_q === 1'b1);
  `OCAH_FCOV_COVER(c_sync_bit_set, sync_bit_set_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sync_bit_cleared, sync_bit_cleared_e, clk_smc_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the claimed source id, which a flat
  // point list can only bucket as zero / non-zero.
  // ------------------------------------------------------------------
  covergroup cg_plic_claim with function sample (logic [8:0] dev, logic [2:0] threshold);
    option.per_instance = 1;
    cp_dev: coverpoint dev {
      bins none = {0};
      bins low[] = {[1 : 16]};
      bins mid = {[17 : 255]};
      bins high = {[256 : 336]};
      bins out_of_range = default;
    }
    cp_threshold: coverpoint threshold;
    x_claim: cross cp_dev, cp_threshold{
      // Priorities are three bits wide, so threshold 7 passes no source and
      // the only claim it can pair with is the idle one.
      ignore_bins masked_all = binsof (cp_threshold) intersect {7} && !binsof (cp_dev) intersect {
        0
      };
    }
  endgroup

  cg_plic_claim u_cg_plic_claim = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset && claim) u_cg_plic_claim.sample(plic_maxdev0_i, plic_threshold0_i);
  end
`endif

endmodule : smc_int_fcov
