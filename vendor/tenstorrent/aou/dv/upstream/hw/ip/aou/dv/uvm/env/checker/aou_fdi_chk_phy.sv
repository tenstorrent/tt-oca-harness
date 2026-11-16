// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: © 2026 Tenstorrent USA Inc

// AOU_FDI_CHECKER on one PHY of the T1 bench, with its per-direction tap,
// reporting through an aou_fdi_checker_if. LP is the DUT's TX, PL the flits
// driven to it. A two-PHY build has one per PHY, each at that PHY's width; the
// top holds the PHY that I_PHY_TYPE does not select in link reset and shows
// the adapter the selected one's reports.
module aou_fdi_chk_phy #(
    parameter int WD       = 512,
    parameter int RP_COUNT = 1
) (
    input  logic          clk,
    input  logic          rst_n,
    // Starts a new observed-link epoch (the Adapter reports Reset), or holds an
    // unselected PHY's instance idle.
    input  logic          link_reset,
    input  logic          lp_valid,
    input  logic          lp_irdy,
    input  logic [WD-1:0] lp_data,
    input  logic          pl_trdy,
    input  logic          pl_valid,
    input  logic [WD-1:0] pl_data,
    input  logic          pl_flit_cancel,
    input  logic          act_st_disabled,
    input  logic          act_st_enabled,
    // The adapter's clear, taken as a port: a two-PHY top drives both instances
    // from the one aou_fdi_checker_if the adapter writes.
    input  logic          err_clear,
    aou_fdi_checker_if    chk
);
  logic [15:0] xchk_cnt;
  logic        xchk_trigger, xchk_capture_valid, xchk_capture_code, xchk_capture_die;
  logic [1:0]  xchk_capture_chk_st, xchk_capture_obs_st, xchk_compared;
  logic [31:0] xchk_capture_flit_seq;

  // DEST_RP is the identity map the DUT resets to.
  AOU_FDI_CHECKER #(
      .FDI_IF_BYTES(WD / 8),
      .RP_COUNT    (RP_COUNT),
      .FDID        (0)
  ) u_fdi_chk (
      .I_CLK                  (clk),
      .I_RESETN               (rst_n),
      .I_LINK_RESET           (link_reset),
      .I_LP_VALID             (lp_valid),
      .I_LP_IRDY              (lp_irdy),
      .I_LP_DATA              (lp_data),
      .I_PL_TRDY              (pl_trdy),
      .I_PL_VALID             (pl_valid),
      .I_PL_DATA              (pl_data),
      .I_PL_FLIT_CANCEL       (pl_flit_cancel),
      .I_CFG_RP_DEST_RP       ({2'd3, 2'd2, 2'd1, 2'd0}),
      .I_LP_ACT_ST_DISABLED   (act_st_disabled),
      .I_LP_ACT_ST_ENABLED    (act_st_enabled),
      .I_PL_ACT_ST_DISABLED   (1'b0),
      .I_PL_ACT_ST_ENABLED    (1'b0),
      .O_VIOLATION            (chk.violation),
      .O_VIOLATION_TRIGGER    (chk.trigger),
      .O_VIOLATION_CNT        (chk.viol_cnt),
      .O_CAPTURE_VALID        (chk.capture_valid),
      .O_CAPTURE_CODE         (chk.capture_code),
      .O_CAPTURE_DIR          (chk.capture_dir),
      .O_CAPTURE_FLIT_SEQ     (chk.capture_flit_seq),
      .O_CAPTURE_GRANULE_IDX  (chk.capture_granule_idx),
      .O_CAPTURE_GRANULE      (chk.capture_granule),
      .O_CHECK_ENABLED        (chk.check_enabled),
      .O_LP_FLIT_SEQ          (chk.lp_flit_seq),
      .O_PL_FLIT_SEQ          (chk.pl_flit_seq),
      .O_XCHK_VIOLATION       (chk.xchk_violation),
      .O_XCHK_TRIGGER         (xchk_trigger),
      .O_XCHK_CNT             (xchk_cnt),
      .O_XCHK_CAPTURE_VALID   (xchk_capture_valid),
      .O_XCHK_CAPTURE_CODE    (xchk_capture_code),
      .O_XCHK_CAPTURE_DIE     (xchk_capture_die),
      .O_XCHK_CAPTURE_CHK_ST  (xchk_capture_chk_st),
      .O_XCHK_CAPTURE_OBS_ST  (xchk_capture_obs_st),
      .O_XCHK_CAPTURE_FLIT_SEQ(xchk_capture_flit_seq),
      .O_XCHK_COMPARED        (xchk_compared),
      .I_ERR_CLEAR            (err_clear)
  );

  aou_fdi_chk_dir_tap u_fdi_chk_dir (
      .clk          (clk),
      .rst_n        (rst_n),
      .clr          (err_clear),
      .go           (u_fdi_chk.w_chk_go),
      .granule_viol (u_fdi_chk.w_granule_viol),
      .flit_seq     (u_fdi_chk.r_flit_seq),
      .dir_violation(chk.dir_violation),
      .dir_flit_seq (chk.dir_flit_seq)
  );

  assign chk.rst_n    = rst_n;
  assign chk.late_adv = u_fdi_chk.w_late_adv_seen;
endmodule
