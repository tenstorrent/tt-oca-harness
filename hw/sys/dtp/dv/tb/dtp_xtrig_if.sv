// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP cross-trigger TB interface, shared by the cocotb and SV-UVM flows:
// the CTM internal-CT req/ack pairs and the CTP pad-cell din/dout/en
// quartets. The request-side vectors are stimulus the XTRIG sequences
// drive (init '0 = quiescent); the remaining vectors are DUT-driven
// observables tb_top mirrors from the DUT pins.

interface dtp_xtrig_if;

  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_src_ack = '0;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_dst_req = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_out_din = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_req_in_din  = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_in_din  = '0;
  logic [dtp_dv_cfg_pkg::NumCtp-1:0]    xtrig_ctp_ack_out_din = '0;

  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_src_req;
  logic [dtp_dv_cfg_pkg::NumIntCt-1:0] xtrig_ctm_dst_ack;
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
