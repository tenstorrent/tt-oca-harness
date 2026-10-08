// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Environment of the ctn_xtrig tasks on the cross_trigger_network formal top, read by those tasks
// beside dtp_cross_trigger_network_sby_env.sv: the stretch bound of external port 0. The pulse
// stretcher counts down from STRETCH_MULT, so the bound keeps a stretched pulse inside the cover
// depth. Bound to cross_trigger_network by the statement at the end of this file.

`include "ocah_fv_macros.svh"

module dtp_ctn_xtrig_sby_env (
  input logic        clk_i,
  input logic        rst_ni,
  input logic [15:0] ctp0_stretch_mult_i  // STRETCH_MULT field
);

`ifdef FORMAL
  `OCAH_FV_ASSUME(asm_env_ctp_stretch_small, ctp0_stretch_mult_i <= 16'd4, clk_i, rst_ni)
`endif

endmodule : dtp_ctn_xtrig_sby_env

bind cross_trigger_network dtp_ctn_xtrig_sby_env u_dtp_ctn_xtrig_sby_env (
  .clk_i               (clk_i),
  .rst_ni              (rst_ni),
  .ctp0_stretch_mult_i (gen_ext_ctp[0].u_ctp.reg_out.STRETCH_MULT.STRETCH_MULT.value)
);
