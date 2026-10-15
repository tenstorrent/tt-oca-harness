// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Aggregate external CTPs, internal CTPs, the cross-trigger matrix, and an AXI-Lite CSR crossbar.
//
// NUM_CTP external ports and NUM_INT_CT internal ports attach to the CTM. GPIO pad buses
// expose CT_Req_out/in and CT_Ack_in/out for each external CTP.
//
// INT_CT_MODE selects the internal CTP protocol:
//
// - 0: simple pulse sync; acks are unused.
// - 1: req/ack four-phase handshaking per internal CTP.
//
// CLA clock-stop requests OR-reduce into combinational cla_clock_stop_o and, together with
// the JTAG DEBUG_CONTROL clock stop, into stop_clks_o, synchronized and registered in clk_i.

module cross_trigger_network
    import cross_trigger_network_pkg::DefaultNumCtp;
    import cross_trigger_network_pkg::DefaultNumIntCt;
    import cross_trigger_network_pkg::DefaultNumClkStopReq;
    import cross_trigger_network_pkg::ctn_axil_req_t;
    import cross_trigger_network_pkg::ctn_axil_resp_t;

    `include "axi/typedef.svh"
    `include "prim_assert.sv"
#(
    parameter int unsigned NUM_CTP          = DefaultNumCtp,    // Number of external CTPs, from 1
                                                                // to 32. NUM_CTP + NUM_INT_CT must
                                                                // equal the NumCtSrc and
                                                                // NumCtDst of the generated
                                                                // cross-trigger matrix.
    parameter int unsigned NUM_INT_CT       = DefaultNumIntCt,     // Number of internal CTPs, at
                                                                   // most 32.
    parameter int unsigned NUM_CLK_STOP_REQ = DefaultNumClkStopReq,  // Width of clk_stop_req_i; at least 1.

    parameter logic [NUM_INT_CT-1:0] INT_CT_MODE = '0,  // Mode of each internal CTP, one bit per
                                                        // CTP. 0 selects wire-OR pulse sync and 1 a
                                                        // point-to-point four-phase handshake.

    parameter type axil_req_t  = ctn_axil_req_t,  // CTN AXI-Lite request type.
    parameter type axil_resp_t = ctn_axil_resp_t  // CTN AXI-Lite response type.
) (
    input  logic        clk_i,          // System clock; all CSRs, ports and the matrix run on it.
    input  logic        rst_ni,         // Active-low asynchronous reset.
    input  logic        test_en_i,      // DFT test-mode enable, active-high, for the AXI-Lite CSR
                                        // crossbar.

    input  axil_req_t   axil_req_i,     // AXI-Lite CSR subordinate request; the crossbar routes
                                        // offset 0 to the CTM and the following windows to the
                                        // external CTPs, one transaction at a time.
    output axil_resp_t  axil_resp_o,    // AXI-Lite CSR subordinate response.

    input  logic [NUM_CLK_STOP_REQ-1:0]  clk_stop_req_i,  // Clock stop requests from CLAs,
                                                          // active-high and asynchronous to clk_i.
    input  logic                         jtag_clock_stop_i,  // JTAG DEBUG_CONTROL clock stop,
                                                             // active-high and asynchronous to
                                                             // clk_i.
    output logic                         stop_clks_o,  // Halt, high when the JTAG or any CLA
                                                       // request is high; two-flop synchronized and
                                                       // registered in clk_i, low in reset.
    output logic                         cla_clock_stop_o,  // Combinational OR of clk_stop_req_i,
                                                            // for JTAG status readback.

    output logic [NUM_INT_CT-1:0]  ctm_src_req_o,  // Cross-trigger requests from the CTM to
                                                   // internal CLA sinks; a stretched pulse in
                                                   // pulse-sync mode, a four-phase request level in
                                                   // handshake mode.
    input  logic [NUM_INT_CT-1:0]  ctm_src_ack_i,  // Acknowledges from internal CLA sinks for
                                                   // CTM-sourced requests, synchronized in the
                                                   // port; unused in pulse-sync mode.
    input  logic [NUM_INT_CT-1:0]  ctm_dst_req_i,  // Cross-trigger requests from internal CLA
                                                   // sources to the CTM, active-high and
                                                   // synchronized in the port.
    output logic [NUM_INT_CT-1:0]  ctm_dst_ack_o,  // Acknowledges to internal CLA sources for
                                                   // CTM-destined requests; low in pulse-sync mode.

    output logic [NUM_CTP-1:0]  ctp_req_out_dout_o,  // CT_Req_out pad output data, registered; in
                                                     // wire-OR mode a static low (high when
                                                     // inverted), with the pulse carried by the
                                                     // output enable; in point-to-point mode the
                                                     // handshake request, inverted when the port's
                                                     // invert bit is set.
    output logic [NUM_CTP-1:0]  ctp_req_out_dout_en_o,  // CT_Req_out pad output enables; follow the
                                                        // stretched outgoing pulse in wire-OR mode
                                                        // and stay high in point-to-point mode.
    input  logic [NUM_CTP-1:0]  ctp_req_out_din_i,  // CT_Req_out pad inputs, asynchronous; the
                                                    // shared trigger line sampled in wire-OR mode,
                                                    // unused in point-to-point mode.
    output logic [NUM_CTP-1:0]  ctp_req_out_din_en_o,  // CT_Req_out pad input enables; high in
                                                       // wire-OR mode, low in point-to-point mode.

    output logic [NUM_CTP-1:0]  ctp_req_in_dout_o,  // CT_Req_in pad output data; tied low because
                                                    // CT_Req_in is input-only.
    output logic [NUM_CTP-1:0]  ctp_req_in_dout_en_o,  // CT_Req_in pad output enables; tied low
                                                       // because CT_Req_in is input-only.
    input  logic [NUM_CTP-1:0]  ctp_req_in_din_i,  // CT_Req_in pad inputs, asynchronous; the
                                                   // incoming point-to-point request, unused in
                                                   // wire-OR mode.
    output logic [NUM_CTP-1:0]  ctp_req_in_din_en_o,  // CT_Req_in pad input enables; high in
                                                      // point-to-point mode, low in wire-OR mode.

    output logic [NUM_CTP-1:0]  ctp_ack_in_dout_o,  // CT_Ack_in pad output data; tied low because
                                                    // CT_Ack_in is input-only.
    output logic [NUM_CTP-1:0]  ctp_ack_in_dout_en_o,  // CT_Ack_in pad output enables; tied low
                                                       // because CT_Ack_in is input-only.
    input  logic [NUM_CTP-1:0]  ctp_ack_in_din_i,  // CT_Ack_in pad inputs, asynchronous; the
                                                   // acknowledge for the outgoing point-to-point
                                                   // request, unused in wire-OR mode.
    output logic [NUM_CTP-1:0]  ctp_ack_in_din_en_o,  // CT_Ack_in pad input enables; high in
                                                      // point-to-point mode, low in wire-OR mode.

    output logic [NUM_CTP-1:0]  ctp_ack_out_dout_o,  // CT_Ack_out pad output data, registered; the
                                                     // handshake acknowledge in point-to-point
                                                     // mode, inverted when the port's invert bit is
                                                     // set; low in wire-OR mode.
    output logic [NUM_CTP-1:0]  ctp_ack_out_dout_en_o,  // CT_Ack_out pad output enables; high in
                                                        // point-to-point mode, low in wire-OR mode.
    input  logic [NUM_CTP-1:0]  ctp_ack_out_din_i,  // CT_Ack_out pad inputs; unused because
                                                    // CT_Ack_out is output-only.
    output logic [NUM_CTP-1:0]  ctp_ack_out_din_en_o  // CT_Ack_out pad input enables; tied low
                                                      // because CT_Ack_out is output-only.
);

    // Tie off unused signals to satisfy lint
    logic unused_ct_acks;
    assign unused_ct_acks = ^{ctp_ack_out_din_i, ctm_src_ack_i};

    //--------------------------------------------------------------------------
    // Local Parameters
    //--------------------------------------------------------------------------

    // Total number of CTM ports (external CTPs + internal CTPs). The generated
    // matrix register map has one CT_Src and one CT_Dst for each of these.
    localparam int unsigned NumCtmPorts = NUM_CTP + NUM_INT_CT;

    `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(
        CtmSrcMatchesElaboratedPorts_A, NumCtmPorts == cross_trigger_matrix_pkg::NumCtSrc)
    `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(
        CtmDstMatchesElaboratedPorts_A, NumCtmPorts == cross_trigger_matrix_pkg::NumCtDst)

    // Number of AXI-Lite master ports (external CTPs + CTM)
    // Internal CTPs don't have CSRs
    localparam int unsigned NumXbarMstPorts = NUM_CTP + 1;

    // Address space sizes
    localparam int unsigned AddrCtmSize = cross_trigger_network_pkg::CsrAddrCtmSize;  // 512 bytes for CTM
    localparam int unsigned AddrCtmRegSize = cross_trigger_network_pkg::CsrAddrCtmRegSize;
    localparam int unsigned AddrCtpSize = cross_trigger_network_pkg::CsrAddrCtpSize;  // 16 bytes per CTP

    `OCAH_OT_ASSERT_STATIC_IN_PACKAGE(CtmRegsFitAperture_A, AddrCtmRegSize <= AddrCtmSize)

    //--------------------------------------------------------------------------
    // AXI-Lite Crossbar Type Definitions
    //--------------------------------------------------------------------------

    // Channel types for crossbar
    `AXI_LITE_TYPEDEF_AW_CHAN_T(xbar_aw_chan_t, cross_trigger_network_pkg::ctn_axil_addr_t)
    `AXI_LITE_TYPEDEF_W_CHAN_T(xbar_w_chan_t, cross_trigger_network_pkg::ctn_axil_data_t, cross_trigger_network_pkg::ctn_axil_strb_t)
    `AXI_LITE_TYPEDEF_B_CHAN_T(xbar_b_chan_t)
    `AXI_LITE_TYPEDEF_AR_CHAN_T(xbar_ar_chan_t, cross_trigger_network_pkg::ctn_axil_addr_t)
    `AXI_LITE_TYPEDEF_R_CHAN_T(xbar_r_chan_t, cross_trigger_network_pkg::ctn_axil_data_t)

    // Address map rule type
    typedef struct packed {
        int unsigned idx;
        logic [cross_trigger_network_pkg::AxiLiteAddrWidth-1:0] start_addr;
        logic [cross_trigger_network_pkg::AxiLiteAddrWidth-1:0] end_addr;
    } xbar_rule_t;

    //--------------------------------------------------------------------------
    // Internal Signals
    //--------------------------------------------------------------------------

    // Cross trigger signals between CTPs and CTM
    logic [NumCtmPorts-1:0] ctm_ct_dst;  // CTP ct_dst -> CTM ct_dst_i
    logic [NumCtmPorts-1:0] ctm_ct_src;  // CTM ct_src_o -> CTP ct_src

    // AXI-Lite signals from crossbar to subordinates
    axil_req_t  [NumXbarMstPorts-1:0] xbar_mst_req;
    axil_resp_t [NumXbarMstPorts-1:0] xbar_mst_resp;

    // Address map for crossbar
    xbar_rule_t [NumXbarMstPorts-1:0] addr_map;

    //--------------------------------------------------------------------------
    // Address Map Generation
    //--------------------------------------------------------------------------

    // Generate address map: CTM first at address 0, then external CTPs
    // CTM is the first port (index 0). Its rule ends at the register map's extent, so the
    // rest of its 512-byte aperture decodes as unmapped.
    assign addr_map[0].idx        = 0;
    assign addr_map[0].start_addr = 0;
    assign addr_map[0].end_addr   = AddrCtmRegSize;

    // External CTPs follow (indices 1 to NUM_CTP, starting at 0x0200)
    for (genvar i = 0; i < NUM_CTP; i++) begin : gen_ctp_addr_map
        assign addr_map[i + 1].idx        = i + 1;
        assign addr_map[i + 1].start_addr = AddrCtmSize + (i * AddrCtpSize);
        assign addr_map[i + 1].end_addr   = AddrCtmSize + ((i + 1) * AddrCtpSize);
    end

    //--------------------------------------------------------------------------
    // AXI-Lite Crossbar Configuration
    //--------------------------------------------------------------------------

    localparam axi_pkg::xbar_cfg_t XbarCfg = '{
        NoSlvPorts:         1,                       // Single subordinate port from DTP
        NoMstPorts:         NumXbarMstPorts,         // CTM + CTPs
        MaxMstTrans:        1,                       // Single outstanding transaction
        MaxSlvTrans:        1,
        FallThrough:        1'b0,
        LatencyMode:        axi_pkg::CUT_SLV_PORTS,  // No combinational path across the CSR port
        PipelineStages:     0,
        AxiIdWidthSlvPorts: 1,                       // Not used for AXI-Lite
        AxiIdUsedSlvPorts:  1,
        UniqueIds:          1'b0,
        SelHashIds:         1'b0,
        AxiAddrWidth:       cross_trigger_network_pkg::AxiLiteAddrWidth,
        AxiDataWidth:       cross_trigger_network_pkg::AxiLiteDataWidth,
        NoAddrRules:        NumXbarMstPorts
    };

    //--------------------------------------------------------------------------
    // AXI-Lite Crossbar Instantiation
    //--------------------------------------------------------------------------

    axil_req_t   [0:0] xbar_slv_req;
    axil_resp_t  [0:0] xbar_slv_resp;

    // need this assignment to do casting, cannot do it at the ports
    assign xbar_slv_req[0] = axil_req_i;
    assign axil_resp_o     = xbar_slv_resp[0];

    axi_lite_xbar #(
        .Cfg        (XbarCfg),
        .aw_chan_t  (xbar_aw_chan_t),
        .w_chan_t   (xbar_w_chan_t),
        .b_chan_t   (xbar_b_chan_t),
        .ar_chan_t  (xbar_ar_chan_t),
        .r_chan_t   (xbar_r_chan_t),
        .axi_req_t  (axil_req_t),
        .axi_resp_t (axil_resp_t),
        .rule_t     (xbar_rule_t)
    ) u_axil_xbar (
        .clk_i                  (clk_i),
        .rst_ni                 (rst_ni),
        .test_i                 (test_en_i),
        .slv_ports_req_i        (xbar_slv_req),
        .slv_ports_resp_o       (xbar_slv_resp),
        .mst_ports_req_o        (xbar_mst_req),
        .mst_ports_resp_i       (xbar_mst_resp),
        .addr_map_i             (addr_map),
        .en_default_mst_port_i  ('0),
        .default_mst_port_i     ('0)
    );

    //--------------------------------------------------------------------------
    // External Cross Trigger Port Instantiation
    //--------------------------------------------------------------------------

    for (genvar i = 0; i < NUM_CTP; i++) begin : gen_ext_ctp
        cross_trigger_port #(
            .axil_req_t  (axil_req_t),
            .axil_resp_t (axil_resp_t)
        ) u_ctp (
            .clk_i                  (clk_i),
            .rst_ni                 (rst_ni),

            // AXI-Lite interface from crossbar (CTPs are ports 1 to NUM_CTP)
            .axil_req_i             (xbar_mst_req[i + 1]),
            .axil_resp_o            (xbar_mst_resp[i + 1]),

            // Core-side cross trigger interface (to/from CTM)
            .ct_src_i               (ctm_ct_src[i]),
            .ct_dst_o               (ctm_ct_dst[i]),
            .busy_o                 (),  // Unused at top level

            // GPIO pad interface - CT_Req_out
            .ct_req_out_dout_en_o   (ctp_req_out_dout_en_o[i]),
            .ct_req_out_din_en_o    (ctp_req_out_din_en_o[i]),
            .ct_req_out_dout_o      (ctp_req_out_dout_o[i]),
            .ct_req_out_din_i       (ctp_req_out_din_i[i]),

            // GPIO pad interface - CT_Req_in
            .ct_req_in_din_en_o     (ctp_req_in_din_en_o[i]),
            .ct_req_in_din_i        (ctp_req_in_din_i[i]),

            // GPIO pad interface - CT_Ack_in
            .ct_ack_in_din_en_o     (ctp_ack_in_din_en_o[i]),
            .ct_ack_in_din_i        (ctp_ack_in_din_i[i]),

            // GPIO pad interface - CT_Ack_out
            .ct_ack_out_dout_en_o   (ctp_ack_out_dout_en_o[i]),
            .ct_ack_out_dout_o      (ctp_ack_out_dout_o[i])
        );

        // CT_Req_in and CT_Ack_in/out have unused output signals - tie them off
        assign ctp_req_in_dout_o[i]     = 1'b0;
        assign ctp_req_in_dout_en_o[i]  = 1'b0;
        assign ctp_ack_in_dout_o[i]     = 1'b0;
        assign ctp_ack_in_dout_en_o[i]  = 1'b0;
        assign ctp_ack_out_din_en_o[i]  = 1'b0;
    end

    //--------------------------------------------------------------------------
    // Internal Cross Trigger Port Instantiation (Core-only, no CSRs)
    //--------------------------------------------------------------------------

    for (genvar i = 0; i < NUM_INT_CT; i++) begin : gen_int_ctp
        // Internal CTP uses core module without CSRs
        // Configuration is static via parameters

        // Mode configuration: pulse sync (0) or handshake (1)
        localparam logic ModeWireOr = ~INT_CT_MODE[i];

        // Signals for internal CTP GPIO interface (directly connected to internal signals)
        logic int_ct_req_out_dout, int_ct_req_out_dout_en;
        logic int_ct_req_out_din, int_ct_req_out_din_en;
        logic int_ct_req_in_din, int_ct_req_in_din_en;
        logic int_ct_ack_in_din, int_ct_ack_in_din_en;
        logic int_ct_ack_out_dout, int_ct_ack_out_dout_en;

        cross_trigger_port_core u_int_ctp_core (
            .clk_i                  (clk_i),
            .rst_ni                 (rst_ni),

            // Static configuration (no CSRs)
            .mode_wire_or_i         (ModeWireOr),
            .invert_i               (1'b0),           // No inversion for internal
            .handshake_reset_i      (1'b0),           // No handshake reset
            .stretch_mult_i         (16'h0001),       // Minimal stretch for internal

            // Core-side cross trigger interface (to/from CTM)
            .ct_src_i               (ctm_ct_src[NUM_CTP + i]),
            .ct_dst_o               (ctm_ct_dst[NUM_CTP + i]),
            .busy_o                 (),

            // GPIO interface - repurposed for internal signals
            // CT_Req_out: Used for dst_req (request to CLA)
            .ct_req_out_dout_en_o   (int_ct_req_out_dout_en),
            .ct_req_out_din_en_o    (int_ct_req_out_din_en),
            .ct_req_out_dout_o      (int_ct_req_out_dout),
            .ct_req_out_din_i       (int_ct_req_out_din),

            // CT_Req_in: Used for src_req (request from CLA)
            .ct_req_in_din_en_o     (int_ct_req_in_din_en),
            .ct_req_in_din_i        (int_ct_req_in_din),

            // CT_Ack_in: Used for src_ack (ack from CLA)
            .ct_ack_in_din_en_o     (int_ct_ack_in_din_en),
            .ct_ack_in_din_i        (int_ct_ack_in_din),

            // CT_Ack_out: Used for dst_ack (ack to CLA)
            .ct_ack_out_dout_en_o   (int_ct_ack_out_dout_en),
            .ct_ack_out_dout_o      (int_ct_ack_out_dout),

            // Status outputs (unused)
            .status_busy_o          (),
            .status_req_out_o       (),
            .status_ack_in_o        (),
            .status_req_in_o        (),
            .status_ack_out_o       ()
        );

        // Map internal CTP GPIO signals to internal cross trigger interface
        // Mode-specific signal routing
        if (ModeWireOr) begin : gen_wire_or_signals
            // Wire-OR mode:
            // - CTP sends stretched pulses to CLAs on ct_req_out_dout_en (dout is static)
            // - CTP receives stretched pulses from CLAs on ct_req_out_din
            // - All other signals unused
            assign ctm_src_req_o[i]   = int_ct_req_out_dout_en; // dout_en indicates active pulse
            // The core receives wire-OR triggers on the falling edge of an
            // idle-high wire, so the active-high CLA request is inverted.
            assign int_ct_req_out_din = ~ctm_dst_req_i[i];
            assign int_ct_req_in_din  = 1'b0;                   // Unused in Wire-OR
            assign int_ct_ack_in_din  = 1'b0;                   // Unused in Wire-OR
            assign ctm_dst_ack_o[i]   = 1'b0;                   // Unused in Wire-OR
        end else begin : gen_p2p_signals
            // Point-to-Point mode:
            // - CTP sends handshake requests to CLAs on ct_req_out_dout
            // - CTP receives handshake requests from CLAs on ct_req_in_din
            // - CTP receives handshake acks from CLAs on ct_ack_in_din
            // - CTP sends handshake acks to CLAs on ct_ack_out_dout
            assign ctm_src_req_o[i]   = int_ct_req_out_dout;    // Level-based request
            assign int_ct_req_out_din = 1'b0;                   // Unused in P2P
            assign int_ct_req_in_din  = ctm_dst_req_i[i];       // CLAs send requests here
            assign int_ct_ack_in_din  = ctm_src_ack_i[i];       // CLAs send acks here
            assign ctm_dst_ack_o[i]   = int_ct_ack_out_dout;    // CTP sends acks here
        end
    end

    //--------------------------------------------------------------------------
    // Cross Trigger Matrix Instantiation
    //--------------------------------------------------------------------------

    cross_trigger_matrix #(
        .axil_req_t  (axil_req_t),
        .axil_resp_t (axil_resp_t)
    ) u_ctm (
        .clk_i      (clk_i),
        .rst_ni     (rst_ni),

        // AXI-Lite interface from crossbar (first master port, index 0)
        .axil_req_i (xbar_mst_req[0]),
        .axil_resp_o(xbar_mst_resp[0]),

        // Cross trigger routing
        .ct_dst_i   (ctm_ct_dst),    // Inputs from all CTPs
        .ct_src_o   (ctm_ct_src)     // Outputs to all CTPs
    );

    //--------------------------------------------------------------------------
    // Clock Stop Control Instantiation
    //--------------------------------------------------------------------------

    ctn_clock_stop_ctrl #(
        .NUM_CLK_STOP_REQ (NUM_CLK_STOP_REQ)
    ) u_clock_stop_ctrl (
        .clk_i             (clk_i),
        .rst_ni            (rst_ni),
        .clk_stop_req_i    (clk_stop_req_i),
        .jtag_clock_stop_i (jtag_clock_stop_i),
        .stop_clks_o       (stop_clks_o),
        .cla_clock_stop_o  (cla_clock_stop_o)
    );

endmodule : cross_trigger_network
