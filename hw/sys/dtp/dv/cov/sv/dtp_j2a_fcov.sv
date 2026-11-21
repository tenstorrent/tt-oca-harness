// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI functional coverage: the DMI operations each bridge's DTM updates
// with the status their own scan captured, and the dmireset strobes with the
// sticky status they clear (cg_j2a_dmi_status).
//
// One instance in the shared tb_top serves both flows. Each bridge's DMI
// capture and update strobes, its captured status, the op its bridge state
// machine receives and its DTMCS dmireset strobe come through hierarchical
// references into its jtag_dmi2axi, in the bit order of dtp_tb_if.j2a_b_hold
// (0 smc_axi, 1 smc_otp, 2 sep_otp). Every strobe is high for the one rising
// TCK edge that leaves Capture-DR or Update-DR, which is the edge each sample
// is taken on. The captured status includes the busy a capture during a read
// sets.
//
// Covergroups follow the cross rules dtp_fcov.sv states.
//
// CONVENTION: no declaration initializers on always_ff-driven variables,
// which VCS rejects (initializer_driver_checks); declare wires before use.

module dtp_j2a_fcov (
  input wire            tck_i,
  input wire            tap_rst_ni,
  input wire [2:0]      capture_en_i,
  input wire [2:0]      update_en_i,
  input wire [2:0]      dmireset_i,
  input wire [2:0][1:0] capture_status_i,
  input wire [2:0][1:0] update_op_i
);

  localparam int unsigned Bridges = 3;

  // The status each bridge's last DMI capture presented, which its next DMI
  // update closes the scan of.
  logic [Bridges-1:0][1:0] scan_status_q;

  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) begin
      scan_status_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (capture_en_i[b]) scan_status_q[b] <= capture_status_i[b];
      end
    end
  end

  // One sample per DMI update, with the op it carries and the status its own
  // capture presented, and one per dmireset, with the sticky status it
  // clears. The DMI defines no status 1, and this integration's Debug Module
  // never fails an access, so no status reads 2.
  covergroup cg_j2a_dmi_status with function sample (
      logic [1:0] bridge, logic dmireset, logic [1:0] op, logic [1:0] status
  );
    option.per_instance = 1;
    cp_bridge: coverpoint bridge {
      bins smc_axi = {2'd0};
      bins smc_otp = {2'd1};
      bins sep_otp = {2'd2};
      illegal_bins none = {2'd3};
    }
    cp_op: coverpoint op {
      bins nop = {2'd0}; bins read = {2'd1}; bins write = {2'd2}; bins clear = {2'd3};
    }
    cp_status: coverpoint status {
      bins success = {2'd0};
      bins busy = {2'd3};
      illegal_bins reserved = {2'd1};
      illegal_bins failed = {2'd2};
    }
    x_update: cross cp_bridge, cp_op, cp_status iff (!dmireset);
    x_dmireset: cross cp_bridge, cp_status iff (dmireset);
  endgroup

  cg_j2a_dmi_status u_cg_j2a_dmi_status = new();

  always_ff @(posedge tck_i) begin
    if (tap_rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (update_en_i[b])
          u_cg_j2a_dmi_status.sample(2'(b), 1'b0, update_op_i[b], scan_status_q[b]);
        if (dmireset_i[b]) u_cg_j2a_dmi_status.sample(2'(b), 1'b1, 2'd3, capture_status_i[b]);
      end
    end
  end

endmodule : dtp_j2a_fcov
