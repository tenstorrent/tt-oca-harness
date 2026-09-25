// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP cross-trigger TB interface, shared by the cocotb and SV-UVM flows:
// the CTM internal-CT req/ack pairs, the CTP pad-cell din/dout/en quartets,
// and the shared wires the CT_Req_out pads sit on. The request-side vectors
// are stimulus the XTRIG sequences drive (init '0 = quiescent); the wire
// vectors describe the board (every private wire rests at the pull-up of the
// reset-default INVERT=0, no chiplet pulling, no shared group); the remaining
// vectors are DUT-driven observables tb_top mirrors from the DUT pins and
// from the ports' receive pulses.

interface dtp_xtrig_if;

  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_src_ack = '0;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_dst_req = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_in_din  = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_in_din  = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_out_din = '0;

  // CT_Req_out shared wires: one chiplet driver per wire, the pull of each
  // private wire, the pads that share the group wire and that wire's pull.
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_wire_ext_assert = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_wire_pull       = '1;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_wire_group      = '0;
  logic                                 xtrig_ctp_wire_group_pull = 1'b1;

  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_src_req;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_dst_ack;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_out_din;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_wire_mismatch;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ct_dst;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_int_ct_dst;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_out_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_out_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_out_din_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_in_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_in_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_in_din_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_in_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_in_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_in_din_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_out_dout;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_out_dout_en;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_out_din_en;

endinterface : dtp_xtrig_if
