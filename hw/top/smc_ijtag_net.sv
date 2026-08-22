// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//----------------------------------------------------------
// SMC iJTAG Instrument Network
//
// IEEE 1687 SIB chain hosted off the DTP's DFD iJTAG port.
// One SIB per instrument, chained client-to-client:
//
//   cgm[0] -> cgm[1] -> awm[0] -> awm[1] -> pvt -> postdiv
//
// Each vendor SIB gates a 2-bit control TDR followed by the
// vendor macro's own TDR chain:
//
//   host_scan_out_o -> ctrl TDR -> macro i_tdr
//   macro o_tdr     -> host_scan_in_i
//
// The control TDR supplies the Movellus i_tdr_mode and
// i_tdr_readback pins, both reset to 0. The Movellus TDR
// overlays the entire pin boundary, including PCLK and all
// three resets, so raising mode against a zeroed chain holds
// the macro in reset. Preload the chain with the live pin
// state before raising mode.
//
// Copyright 2026 Tenstorrent Inc.
//----------------------------------------------------------

module smc_ijtag_net
    import prim_jtag_pkg::*;
#(
    parameter int unsigned NUM_CGMS = 2,
    parameter int unsigned NUM_AWMS = 2
) (
    // Client interface (from the DTP DFD SIB)
    input  jtag_scan_ctrl_t  client_scan_ctrl_i,
    input  logic             client_scan_in_i,
    output logic             client_scan_out_o,

    // Movellus CGM TDR buses
    output logic [NUM_CGMS-1:0] cgm_tdr_select_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_mode_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_clk_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_rst_n_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_capture_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_shift_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_update_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_readback_o,
    output logic [NUM_CGMS-1:0] cgm_tdr_o,
    input  logic [NUM_CGMS-1:0] cgm_tdr_i,

    // Movellus AWM TDR buses
    output logic [NUM_AWMS-1:0] awm_tdr_select_o,
    output logic [NUM_AWMS-1:0] awm_tdr_mode_o,
    output logic [NUM_AWMS-1:0] awm_tdr_clk_o,
    output logic [NUM_AWMS-1:0] awm_tdr_rst_n_o,
    output logic [NUM_AWMS-1:0] awm_tdr_capture_o,
    output logic [NUM_AWMS-1:0] awm_tdr_shift_o,
    output logic [NUM_AWMS-1:0] awm_tdr_update_o,
    output logic [NUM_AWMS-1:0] awm_tdr_readback_o,
    output logic [NUM_AWMS-1:0] awm_tdr_o,
    input  logic [NUM_AWMS-1:0] awm_tdr_i,

    // Movellus droop TDR bus. The PVT segment continues from the droop macro
    // into the temperature sensor inside tt_combined_pvt_sensor_wrap, so
    // droop_tdr_i is the tail of both.
    output logic droop_tdr_select_o,
    output logic droop_tdr_mode_o,
    output logic droop_tdr_clk_o,
    output logic droop_tdr_rst_n_o,
    output logic droop_tdr_capture_o,
    output logic droop_tdr_shift_o,
    output logic droop_tdr_update_o,
    output logic droop_tdr_readback_o,
    output logic droop_tdr_o,
    input  logic droop_tdr_i,

    // PLL post-divider instrument (native scan interface)
    output jtag_scan_ctrl_t  postdiv_scan_ctrl_o,
    output logic             postdiv_scan_out_o,
    input  logic             postdiv_scan_in_i
);

    // SIB chain positions
    localparam int unsigned SibCgmBase = 0;
    localparam int unsigned SibAwmBase = SibCgmBase + NUM_CGMS;
    localparam int unsigned SibPvt     = SibAwmBase + NUM_AWMS;
    localparam int unsigned SibPostdiv = SibPvt + 1;
    localparam int unsigned NumSibs    = SibPostdiv + 1;

    // Control TDR bit assignment
    localparam int unsigned CtrlBitMode     = 0;
    localparam int unsigned CtrlBitReadback = 1;
    localparam int unsigned CtrlTdrWidth    = 2;

    logic [NumSibs-1:0]  sib_client_scan_in;
    logic [NumSibs-1:0]  sib_client_scan_out;
    logic [NumSibs-1:0]  sib_host_scan_in;
    logic [NumSibs-1:0]  sib_host_scan_out;

    jtag_scan_ctrl_t [NumSibs-1:0] sib_host_scan_ctrl;

    // The DTP's DFD SIB is LOCKUP(0) and launches on rising TCK. Retiming on
    // the falling edge gives uniform hold margin across the hierarchy boundary
    // without adding a chain bit.
    logic chain_head_scan_in;

    always_ff @(negedge client_scan_ctrl_i.tck) begin
        chain_head_scan_in <= client_scan_in_i;
    end

    // Chain the SIBs client-to-client
    always_comb begin
        sib_client_scan_in[0] = chain_head_scan_in;
        for (int unsigned i = 1; i < NumSibs; i++) begin
            sib_client_scan_in[i] = sib_client_scan_out[i-1];
        end
    end

    assign client_scan_out_o = sib_client_scan_out[NumSibs-1];

    for (genvar i = 0; i < NumSibs; i++) begin : g_sib
        prim_jtag_sib_mux_pre #(
            .LOCKUP      (1),
            .SAFE_SELECT (1)
        ) u_sib (
            .client_scan_ctrl_i  (client_scan_ctrl_i),
            .client_scan_in_i    (sib_client_scan_in[i]),
            .client_scan_out_o   (sib_client_scan_out[i]),
            // The DTP's DFD SIB already applies dfd_security_disable upstream.
            .security_disable_i  (1'b0),

            .host_scan_ctrl_o    (sib_host_scan_ctrl[i]),
            .host_scan_in_i      (sib_host_scan_in[i]),
            .host_scan_out_o     (sib_host_scan_out[i])
        );
    end

    // CGM instruments
    for (genvar i = 0; i < NUM_CGMS; i++) begin : g_cgm
        localparam int unsigned SibIdx = SibCgmBase + i;

        logic [CtrlTdrWidth-1:0] ctrl_data;

        // LOCKUP(1) because the vendor macro's internal TCK insertion delay is
        // not under our control. data_in_i ties back to data_out_o so
        // Capture-DR returns the programmed value rather than clobbering it.
        prim_jtag_scan_reg #(
            .LOCKUP    (1),
            .WIDTH     (CtrlTdrWidth),
            .RESET_VAL ('0)
        ) u_ctrl_tdr (
            .scan_ctrl_i (sib_host_scan_ctrl[SibIdx]),
            .scan_in_i   (sib_host_scan_out[SibIdx]),
            .scan_out_o  (cgm_tdr_o[i]),
            .data_in_i   (ctrl_data),
            .data_out_o  (ctrl_data)
        );

        assign cgm_tdr_clk_o[i]      = sib_host_scan_ctrl[SibIdx].tck;
        assign cgm_tdr_rst_n_o[i]    = sib_host_scan_ctrl[SibIdx].rst_n;
        assign cgm_tdr_select_o[i]   = sib_host_scan_ctrl[SibIdx].select;
        assign cgm_tdr_capture_o[i]  = sib_host_scan_ctrl[SibIdx].capture_en;
        assign cgm_tdr_shift_o[i]    = sib_host_scan_ctrl[SibIdx].shift_en;
        assign cgm_tdr_update_o[i]   = sib_host_scan_ctrl[SibIdx].update_en;
        assign cgm_tdr_mode_o[i]     = ctrl_data[CtrlBitMode];
        assign cgm_tdr_readback_o[i] = ctrl_data[CtrlBitReadback];

        assign sib_host_scan_in[SibIdx] = cgm_tdr_i[i];
    end

    // AWM instruments
    for (genvar i = 0; i < NUM_AWMS; i++) begin : g_awm
        localparam int unsigned SibIdx = SibAwmBase + i;

        logic [CtrlTdrWidth-1:0] ctrl_data;

        prim_jtag_scan_reg #(
            .LOCKUP    (1),
            .WIDTH     (CtrlTdrWidth),
            .RESET_VAL ('0)
        ) u_ctrl_tdr (
            .scan_ctrl_i (sib_host_scan_ctrl[SibIdx]),
            .scan_in_i   (sib_host_scan_out[SibIdx]),
            .scan_out_o  (awm_tdr_o[i]),
            .data_in_i   (ctrl_data),
            .data_out_o  (ctrl_data)
        );

        assign awm_tdr_clk_o[i]      = sib_host_scan_ctrl[SibIdx].tck;
        assign awm_tdr_rst_n_o[i]    = sib_host_scan_ctrl[SibIdx].rst_n;
        assign awm_tdr_select_o[i]   = sib_host_scan_ctrl[SibIdx].select;
        assign awm_tdr_capture_o[i]  = sib_host_scan_ctrl[SibIdx].capture_en;
        assign awm_tdr_shift_o[i]    = sib_host_scan_ctrl[SibIdx].shift_en;
        assign awm_tdr_update_o[i]   = sib_host_scan_ctrl[SibIdx].update_en;
        assign awm_tdr_mode_o[i]     = ctrl_data[CtrlBitMode];
        assign awm_tdr_readback_o[i] = ctrl_data[CtrlBitReadback];

        assign sib_host_scan_in[SibIdx] = awm_tdr_i[i];
    end

    // PVT instrument: droop macro, then the temperature sensor TDR downstream
    // of it inside tt_combined_pvt_sensor_wrap.
    logic [CtrlTdrWidth-1:0] droop_ctrl_data;

    prim_jtag_scan_reg #(
        .LOCKUP    (1),
        .WIDTH     (CtrlTdrWidth),
        .RESET_VAL ('0)
    ) u_droop_ctrl_tdr (
        .scan_ctrl_i (sib_host_scan_ctrl[SibPvt]),
        .scan_in_i   (sib_host_scan_out[SibPvt]),
        .scan_out_o  (droop_tdr_o),
        .data_in_i   (droop_ctrl_data),
        .data_out_o  (droop_ctrl_data)
    );

    assign droop_tdr_clk_o      = sib_host_scan_ctrl[SibPvt].tck;
    assign droop_tdr_rst_n_o    = sib_host_scan_ctrl[SibPvt].rst_n;
    assign droop_tdr_select_o   = sib_host_scan_ctrl[SibPvt].select;
    assign droop_tdr_capture_o  = sib_host_scan_ctrl[SibPvt].capture_en;
    assign droop_tdr_shift_o    = sib_host_scan_ctrl[SibPvt].shift_en;
    assign droop_tdr_update_o   = sib_host_scan_ctrl[SibPvt].update_en;
    assign droop_tdr_mode_o     = droop_ctrl_data[CtrlBitMode];
    assign droop_tdr_readback_o = droop_ctrl_data[CtrlBitReadback];

    assign sib_host_scan_in[SibPvt] = droop_tdr_i;

    // PLL post-divider instrument: native scan interface, no mode/readback
    // adaptation.
    assign postdiv_scan_ctrl_o          = sib_host_scan_ctrl[SibPostdiv];
    assign postdiv_scan_out_o           = sib_host_scan_out[SibPostdiv];
    assign sib_host_scan_in[SibPostdiv] = postdiv_scan_in_i;

endmodule
