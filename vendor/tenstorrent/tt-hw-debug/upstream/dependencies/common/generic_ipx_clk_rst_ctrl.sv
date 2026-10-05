// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
/*
 * generic_ipx_clk_rst_ctrl:
 *
 * Root IPx clock, reset, and functional-clamp control block for a clock domain.
 *
 * - Gates the functional clock from Global Reset Controller (GRC) disable controls, 
 *    functional clock enable, fuse disable, and DFT ICG test enable.
 * - Generates gated active-low reset from GRC reset, qualified by fuse disable,
 *   with DFT/test reset mux override.
 * - Asserts functional clamp when requested by GRC or fuse disable.
 * - Intended as the single root integration point before downstream IPx leaf clock gates.
 */


module generic_ipx_clk_rst_ctrl
(
   // Clock Interface
   input  logic i_clk,              // Ungated functional clock input
   input  logic i_func_clk_en,      // clock enable based on functional controls
   input  logic i_clk_dis_val,      // Clock disable value from Global Reset Controller
   input  logic i_clk_dis_ctrl,     // Clock disable control from Global Reset Controller
   input  logic i_test_icg_en,      // DFT/test integrated clock-gate test enable

   // Reset Interface
   input  logic i_reset_n,          // Ungated functional reset from Global Reset Controller
   input  logic i_fuse_dis,         // Fuse disable control; forces reset off and asserts functional clamp
   input  logic i_test_reset_n,     // DFT/test reset override value (active low)
   input  logic i_test_reset_en,    // Select DFT/test reset enable over functional reset

   // Functional Clamp Interface
   input  logic i_func_clamp,       // Functional clamp control for IPx O/Ps (from Global Reset Controller)

   // IPx Output Clk_Rst Interface
   output logic o_gated_clk,        // Gated functional clock
   output logic o_gated_reset_n,    // Gated functional reset (active low)
   output logic o_gated_func_clamp  // Gated functional clamp
);

   // -------------------------------------------------------------------------
   // Root Clock Gating
   // -------------------------------------------------------------------------
   logic clk_en_sel;
   logic clk_en;

   assign clk_en_sel = i_clk_dis_ctrl ? ~i_clk_dis_val : i_func_clk_en;
   assign clk_en     = clk_en_sel & ~i_fuse_dis;

   generic_clkgate u_clk_gater (
      .clk    (i_clk),
      .en     (clk_en),
      .te     (i_test_icg_en),
      .clk_out(o_gated_clk)
   );


   // -------------------------------------------------------------------------
   // IPx Functional Clamp Generation
   // -------------------------------------------------------------------------
   assign o_gated_func_clamp = i_func_clamp | i_fuse_dis;

   // -------------------------------------------------------------------------
   // IPx Reset Generation
   // -------------------------------------------------------------------------
   logic reset_n_fuse_gated;

   assign reset_n_fuse_gated = i_reset_n & ~i_fuse_dis;

   generic_clkmux2 u_rst_mux (
      .in0   (reset_n_fuse_gated),
      .in1   (i_test_reset_n),
      .select(i_test_reset_en),
      .out   (o_gated_reset_n)
   );

endmodule
