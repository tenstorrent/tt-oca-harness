// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC eFuse and lifecycle-state functional coverage at the wrapper boundary:
// fuse sense completion, the delayed fuse reset, the shadow-register output
// carrying sensed values, and the TEST_DEV lifecycle tie.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or a smc_wrapper boundary port.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_efuse_fcov #(
  parameter int unsigned ShadowWidth = 1,
  parameter int unsigned LcStateWidth = 8,
  parameter logic [7:0] LcStateTestDev = 8'hF0
) (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  input wire fuse_sense_done_i,
  input wire fuse_reset_ni,
  input wire skip_mem_repair_i,
  input wire [ShadowWidth-1:0] shadow_regs_i,

  input wire [LcStateWidth-1:0] lc_state_i,
  input wire lc_sigint_err_i,

  // Bank-control AXI-Lite port and the SHIM custom-command handshake.
  input wire bank_awvalid_i,
  input wire bank_wvalid_i,
  input wire bank_arvalid_i,
  input wire bank_bvalid_i,
  input wire bank_rvalid_i,
  input wire shim_cmd_valid_i,
  input wire shim_resp_valid_i,
  input wire shim_resp_status_i,

  // OTP JTAG AXI-Lite path.
  input wire jtag_otp_awvalid_i,
  input wire jtag_otp_awready_i,
  input wire jtag_otp_bvalid_i,
  input wire jtag_otp_arvalid_i,
  input wire jtag_otp_arready_i,
  input wire jtag_otp_rvalid_i,

  // LOCKS enforcement observables.
  input wire [63:0] locks_i,
  input wire locked_access_irq_i,
  input wire read_done_i,
  input wire [31:0] readback_i,
  input wire program_done_i,
  input wire [31:0] programmed_word0_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Sense completion, and the fuse reset releasing at least sixteen cycles
  // after it.
  // ------------------------------------------------------------------
  logic fuse_sense_done_q, fuse_reset_q;
  logic [7:0] since_sense_cnt_q;
  always_ff @(posedge clk_smc_i) begin
    fuse_sense_done_q <= fuse_sense_done_i;
    fuse_reset_q <= fuse_reset_ni;
    if (in_reset || (fuse_sense_done_i !== 1'b1)) since_sense_cnt_q <= '0;
    else if (since_sense_cnt_q != 8'hFF) since_sense_cnt_q <= since_sense_cnt_q + 8'd1;
  end

  wire fuse_sense_done_asserted_e = (fuse_sense_done_i === 1'b1) && (fuse_sense_done_q === 1'b0);
  wire release_fuse_reset = (fuse_reset_ni === 1'b1) && (fuse_reset_q === 1'b0);
  wire fuse_reset_delayed_e = release_fuse_reset && (since_sense_cnt_q >= 8'd16);
  `OCAH_FCOV_COVER(c_fuse_sense_done_asserted, fuse_sense_done_asserted_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_fuse_reset_delayed_16_stages, fuse_reset_delayed_e, clk_smc_i, in_reset)

  // The repair trigger, as far as the wrapper boundary carries it: the sense
  // edge arriving while skip_mem_repair_o is low. The repair engine's own
  // start and completion are inside the cluster and mem_repair_done_i is tied
  // high in this tb, so the low skip output is what separates a sense edge
  // that starts repair from one that is bypassed.
  wire repair_triggered_e = fuse_sense_done_asserted_e && (skip_mem_repair_i === 1'b0);
  `OCAH_FCOV_COVER(c_repair_triggered_by_fuse_sense_done, repair_triggered_e, clk_smc_i, in_reset)

  // Sensed values present on the shadow output once sense has completed.
  wire shadow_regs_reflect_e = (fuse_sense_done_i === 1'b1) && ((|shadow_regs_i) === 1'b1);
  `OCAH_FCOV_COVER(c_shadow_regs_reflect_sensed_values, shadow_regs_reflect_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // TEST_DEV tie accepted without a signal-integrity error. TEST_DEV is the
  // tb's default drive, so the point qualifies on the encoding having
  // changed at least once: it means "TEST_DEV accepted after another
  // encoding was driven".
  // ------------------------------------------------------------------
  logic [LcStateWidth-1:0] lc_state_q;
  logic lc_state_changed_q;
  always_ff @(posedge clk_smc_i) begin
    lc_state_q <= lc_state_i;
    if (in_reset) lc_state_changed_q <= 1'b0;
    else if ((lc_state_i !== lc_state_q) && (^lc_state_q !== 1'bx)) lc_state_changed_q <= 1'b1;
  end
  wire lc_state_test_dev_tie_e = lc_state_changed_q && (lc_state_i === LcStateTestDev)
      && (lc_sigint_err_i === 1'b0);
  `OCAH_FCOV_COVER(c_lc_state_test_dev_tie, lc_state_test_dev_tie_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Bank-control AXI-Lite. Each direction is tracked to its own response so
  // a request that was presented and never answered is not counted.
  // ------------------------------------------------------------------
  logic bank_wr_open_q, bank_rd_open_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      bank_wr_open_q <= 1'b0;
      bank_rd_open_q <= 1'b0;
    end else begin
      if ((bank_awvalid_i === 1'b1) && (bank_wvalid_i === 1'b1)) bank_wr_open_q <= 1'b1;
      else if (bank_bvalid_i === 1'b1) bank_wr_open_q <= 1'b0;
      if (bank_arvalid_i === 1'b1) bank_rd_open_q <= 1'b1;
      else if (bank_rvalid_i === 1'b1) bank_rd_open_q <= 1'b0;
    end
  end

  wire bank_ctrl_write_e = bank_wr_open_q && (bank_bvalid_i === 1'b1);
  wire bank_ctrl_read_e = bank_rd_open_q && (bank_rvalid_i === 1'b1);
  wire bank_ctrl_response_e = (bank_bvalid_i === 1'b1) || (bank_rvalid_i === 1'b1);
  `OCAH_FCOV_COVER(c_bank_ctrl_write, bank_ctrl_write_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_bank_ctrl_read, bank_ctrl_read_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_bank_ctrl_response_returned, bank_ctrl_response_e, clk_smc_i, in_reset)

  // SHIM custom-command handshake. The response point requires a command to
  // have been issued first, so a stuck response valid cannot satisfy it.
  logic shim_cmd_open_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) shim_cmd_open_q <= 1'b0;
    else if (shim_cmd_valid_i === 1'b1) shim_cmd_open_q <= 1'b1;
    else if (shim_resp_valid_i === 1'b1) shim_cmd_open_q <= 1'b0;
  end

  wire shim_command_issued_e = (shim_cmd_valid_i === 1'b1);
  wire shim_response_consumed_e = shim_cmd_open_q && (shim_resp_valid_i === 1'b1)
      && (shim_resp_status_i !== 1'bx);
  `OCAH_FCOV_COVER(c_shim_command_issued, shim_command_issued_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_shim_response_consumed, shim_response_consumed_e, clk_smc_i, in_reset)

  // OTP JTAG AXI-Lite path, request accepted through to its response.
  logic jtag_wr_open_q, jtag_rd_open_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      jtag_wr_open_q <= 1'b0;
      jtag_rd_open_q <= 1'b0;
    end else begin
      if ((jtag_otp_awvalid_i === 1'b1) && (jtag_otp_awready_i === 1'b1)) jtag_wr_open_q <= 1'b1;
      else if (jtag_otp_bvalid_i === 1'b1) jtag_wr_open_q <= 1'b0;
      if ((jtag_otp_arvalid_i === 1'b1) && (jtag_otp_arready_i === 1'b1)) jtag_rd_open_q <= 1'b1;
      else if (jtag_otp_rvalid_i === 1'b1) jtag_rd_open_q <= 1'b0;
    end
  end

  wire jtag_otp_write_e = jtag_wr_open_q && (jtag_otp_bvalid_i === 1'b1);
  wire jtag_otp_read_e = jtag_rd_open_q && (jtag_otp_rvalid_i === 1'b1);
  `OCAH_FCOV_COVER(c_jtag_otp_write, jtag_otp_write_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_jtag_otp_read, jtag_otp_read_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // LOCKS as the enforcement point. Each pair is one completion with the
  // lock field clear and one with it set, so the two halves of the contract
  // cannot be satisfied by the same stimulus.
  // ------------------------------------------------------------------
  wire locks_valid = (^locks_i !== 1'bx);
  wire locks_clear = locks_valid && (locks_i === 64'd0);
  wire locks_set = locks_valid && (locks_i !== 64'd0);

  wire access_completed = (read_done_i === 1'b1) || (program_done_i === 1'b1);
  wire locks_cleared_permitted_e = locks_clear && access_completed;
  wire locks_set_refused_e = (locked_access_irq_i === 1'b1);
  `OCAH_FCOV_COVER(c_locks_cleared_access_permitted, locks_cleared_permitted_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_locks_set_access_refused, locks_set_refused_e, clk_smc_i, in_reset)

  logic [31:0] programmed_word0_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) programmed_word0_q <= '0;
    else programmed_word0_q <= programmed_word0_i;
  end

  wire write_locked_unchanged_e = (program_done_i === 1'b1) && locks_set
      && (programmed_word0_i === programmed_word0_q);
  wire write_unlocked_updated_e = (program_done_i === 1'b1) && locks_clear
      && (programmed_word0_i !== programmed_word0_q) && (^programmed_word0_q !== 1'bx);
  `OCAH_FCOV_COVER(c_write_locked_field_unchanged, write_locked_unchanged_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_write_unlocked_field_updated, write_unlocked_updated_e, clk_smc_i, in_reset)

  wire read_locked_masked_e = (read_done_i === 1'b1) && locks_set && (readback_i === 32'd0);
  wire read_unlocked_returned_e = (read_done_i === 1'b1) && locks_clear && (readback_i !== 32'd0)
      && (^readback_i !== 1'bx);
  `OCAH_FCOV_COVER(c_read_locked_field_masked, read_locked_masked_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_read_unlocked_field_returned, read_unlocked_returned_e, clk_smc_i, in_reset)

endmodule : smc_efuse_fcov
