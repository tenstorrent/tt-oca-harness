// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-------------------------------------------------
// SMC Subsystem Resets
//
//-------------------------------------------------

module smc_subsystem_resets (
  input  logic                                   clk_i,
  input  logic                                   rst_primary_ni,              // stable_cold_rst_n && stable_cool_rst_n && rst_cool_from_flr_ni -> synced to smc_clk

  // Register Interface
  input  reset_unit_reg_pkg::reset_unit__out_t   hwif_out,
  output reset_unit_reg_pkg::reset_unit__in_t    hwif_in,

  input  logic [31:0]                            ss_reset_complete_i,
  output logic [31:0]                            ss_config_o,
  output smc_reset_unit_pkg::reset_ctrl_t        ss_reset_ctrl_o[31:0]
);

  ///////////////////////////////////
  // Subsystem Reset Configuration //
  ///////////////////////////////////

  // Signal Declarations
  logic [31:0] ss_reset_complete;
  logic [31:0] ss_config_wr_data;
  logic [31:0] ss_config_wr_mask;
  logic        ss_config_wr_en;
  logic [31:0] ss_cold_reset_n_n0_scan;
  logic        ss_cold_reset_n_wr_en;
  logic [31:0] ss_cold_reset_n_wr_data;
  logic [31:0] ss_cold_reset_n_wr_mask;
  logic [31:0] ss_warm_reset_n;
  logic [31:0] ss_force_to_ref_clk_n;
  logic [31:0] ss_configuration_state_hold;
  logic [31:0] ss_sram_hold;
  logic [31:0] ss_debug_hold;
  logic [31:0] ss_critical_signal_hold;
  logic [31:0] ss_config_lock;
  logic [31:0] ss_cold_reset_lock;

  logic [31:0] config_filtered_wr_mask;
  logic [31:0] cold_reset_filtered_wr_mask;

  prim_sync3 #(
    .WIDTH(32)
  ) u_reset_complete_sync (
    .clk_i(clk_i),
    .d_i(ss_reset_complete_i),
    .q_o(ss_reset_complete)
  );

  // Register Interface (Normal Registers)
  assign ss_config_lock                                   = hwif_out.SS_CONFIG_LOCK.config_lock.value;
  assign ss_force_to_ref_clk_n                            = hwif_out.SS_FORCE_TO_REF_CLK.force_ss_to_ref_clk_n.value;
  assign ss_warm_reset_n                                  = hwif_out.SS_WARM_RESET_N.reset_n_n0_scan.value;
  assign ss_configuration_state_hold                      = hwif_out.SS_CONFIG_HOLD.configuration_state_hold.value;
  assign ss_critical_signal_hold                          = hwif_out.SS_CRITICAL_HOLD.critical_signal_hold.value;
  assign ss_sram_hold                                     = hwif_out.SS_SRAM_HOLD.sram_hold.value;
  assign ss_debug_hold                                    = hwif_out.SS_DEBUG_HOLD.debug_hold.value;
  assign ss_cold_reset_lock                               = hwif_out.SS_COLD_RESET_LOCK.cold_reset_lock.value;
  always_comb begin
    hwif_in                                          = '{default: '0};
    hwif_in.SS_RESET_COMPLETE.reset_complete.next    = ss_reset_complete;
    hwif_in.SS_CONFIG.rd_ack                         = hwif_out.SS_CONFIG.req && !hwif_out.SS_CONFIG.req_is_wr;
    hwif_in.SS_CONFIG.rd_data                        = ss_config_o;
    hwif_in.SS_CONFIG.wr_ack                         = ss_config_wr_en;
    hwif_in.SS_COLD_RESET_N.rd_ack                   = hwif_out.SS_COLD_RESET_N.req && !hwif_out.SS_COLD_RESET_N.req_is_wr;
    hwif_in.SS_COLD_RESET_N.rd_data                  = ss_cold_reset_n_n0_scan;
    hwif_in.SS_COLD_RESET_N.wr_ack                   = ss_cold_reset_n_wr_en;
  end

  // Subsystem Configuration Register (External Register)
  assign ss_config_wr_data                                = hwif_out.SS_CONFIG.wr_data;
  assign ss_config_wr_mask                                = hwif_out.SS_CONFIG.wr_biten;
  assign ss_config_wr_en                                  = hwif_out.SS_CONFIG.req && hwif_out.SS_CONFIG.req_is_wr;

  // if a field is locked (== 1), don't allow writes to it
  assign config_filtered_wr_mask = (~ss_config_lock) & ss_config_wr_mask;

  // group all resets and controls together
  always_ff @(posedge clk_i or negedge rst_primary_ni) begin
    if (~rst_primary_ni) begin
      ss_config_o <= '0;
    end else begin
      if (ss_config_wr_en) begin
        ss_config_o <= (ss_config_wr_data & config_filtered_wr_mask) | (ss_config_o & ~config_filtered_wr_mask);
      end
    end
  end

  // Subsystem Cold Reset Register (External Register)
  assign ss_cold_reset_n_wr_data                          = hwif_out.SS_COLD_RESET_N.wr_data;
  assign ss_cold_reset_n_wr_mask                          = hwif_out.SS_COLD_RESET_N.wr_biten;
  assign ss_cold_reset_n_wr_en                            = hwif_out.SS_COLD_RESET_N.req && hwif_out.SS_COLD_RESET_N.req_is_wr;

  // if a field is locked (== 1), don't allow writes to it
  assign cold_reset_filtered_wr_mask = (~ss_cold_reset_lock) & ss_cold_reset_n_wr_mask;

  // group all resets and controls together
  always_ff @(posedge clk_i or negedge rst_primary_ni) begin
    if (~rst_primary_ni) begin
      ss_cold_reset_n_n0_scan <= '0;
    end else begin
      if (ss_cold_reset_n_wr_en) begin
        ss_cold_reset_n_n0_scan <= (ss_cold_reset_n_wr_data & cold_reset_filtered_wr_mask) | (ss_cold_reset_n_n0_scan & ~cold_reset_filtered_wr_mask);
      end
    end
  end

  // Subsystem Reset Control
  always_comb begin
    for (int i = 0; i < 32; i = i + 1) begin
      ss_reset_ctrl_o[i].cold_reset_n         = ss_cold_reset_n_n0_scan[i];
      ss_reset_ctrl_o[i].warm_reset_n         = ss_warm_reset_n[i];
      ss_reset_ctrl_o[i].config_state_hold    = ss_configuration_state_hold[i];
      ss_reset_ctrl_o[i].sram_hold            = ss_sram_hold[i];
      ss_reset_ctrl_o[i].critical_signal_hold = ss_critical_signal_hold[i];
      ss_reset_ctrl_o[i].debug_hold           = ss_debug_hold[i];
      ss_reset_ctrl_o[i].force_to_ref_clk_n   = ss_force_to_ref_clk_n[i];
    end
  end

endmodule
