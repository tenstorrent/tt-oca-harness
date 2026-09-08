// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// clk_rst_wrapper:
//
// Central clock/reset/clamp hub for the DFD functional blocks. It owns every
// *functional* rv_ipx_clk_rst_ctrl instance (cla, dst, ntr per-instance, the
// combined tnif trace-network domain, and the dst_sink/ntr_sink/funnel domains)
// and distributes the gated clock, gated reset, warm-override reset, and gated
// functional clamp to the feature wrappers, which are pure consumers.
//
// mmrs keeps its own clk_rst_ctrl instances (its register space cannot be gated
// by its own MMR-based clock disable), so this hub does not drive mmrs.
//
// The per-instance functional clock enables that come from the MMR space
// (EnableCla / Trdstenable) are routed in as the ClaMmrs/DstMmrs structs and
// extracted here; all other domains use a hardwired functional enable.

module clk_rst_wrapper
#(
    parameter int unsigned NUM_CLA_INST    = 8,
    parameter int unsigned NUM_DST_INST    = 8,
    parameter int unsigned NUM_NTRACE_INST = 8,

    // Zero-safe port widths so a single-block flavor (e.g. NTRACE-only,
    // NUM_DST_INST==0) never produces a [-1:0] port. Generate logic below uses
    // the real counts.
    localparam int unsigned CLA_W = (NUM_CLA_INST    == 0) ? 32'd1 : NUM_CLA_INST,
    localparam int unsigned DST_W = (NUM_DST_INST    == 0) ? 32'd1 : NUM_DST_INST,
    localparam int unsigned NTR_W = (NUM_NTRACE_INST == 0) ? 32'd1 : NUM_NTRACE_INST,

    // Combined trace-network (tnif) connection count = larger of DST/NTRACE.
    localparam int unsigned TNIF_CONNECTIONS = (NUM_NTRACE_INST > NUM_DST_INST) ? NUM_NTRACE_INST : NUM_DST_INST,
    localparam int unsigned TNIF_W = ((NUM_DST_INST == 0) && (NUM_NTRACE_INST == 0)) ? 32'd1
                                     : ((NUM_NTRACE_INST > NUM_DST_INST) ? NUM_NTRACE_INST : NUM_DST_INST)
)(
    // Global controls (from Global Reset Controller / DFT)
    input  logic i_clk,
    input  logic i_rst_n,
    input  logic i_critical_signal_hold,

    input  logic i_test_icg_en,
    input  logic i_test_reset_en,
    input  logic i_test_reset_n,

    // CLA controls
    input  logic [CLA_W-1:0]         i_cla_fuse_dis,
    input  logic [CLA_W-1:0]         i_cla_clk_dis,
    input  logic [CLA_W-1:0]         i_cla_clk_dis_ctrl,
    input  logic [CLA_W-1:0]         i_cla_func_clamp,

    // DST controls
    input  logic [DST_W-1:0]         i_dst_fuse_dis,
    input  logic [DST_W-1:0]         i_dst_clk_dis,
    input  logic [DST_W-1:0]         i_dst_clk_dis_ctrl,
    input  logic [DST_W-1:0]         i_dst_func_clamp,

    // NTRACE controls
    input  logic [NTR_W-1:0]         i_ntr_fuse_dis,
    input  logic [NTR_W-1:0]         i_ntr_clk_dis,
    input  logic [NTR_W-1:0]         i_ntr_clk_dis_ctrl,
    input  logic [NTR_W-1:0]         i_ntr_func_clamp,

    // DST sink controls
    input  logic                     i_dst_sink_fuse_dis,
    input  logic                     i_dst_sink_clk_dis,
    input  logic                     i_dst_sink_clk_dis_ctrl,
    input  logic                     i_dst_sink_func_clamp,

    // NTR sink controls
    input  logic                     i_ntr_sink_fuse_dis,
    input  logic                     i_ntr_sink_clk_dis,
    input  logic                     i_ntr_sink_clk_dis_ctrl,
    input  logic                     i_ntr_sink_func_clamp,

    // Funnel controls
    input  logic                     i_funnel_fuse_dis,
    input  logic                     i_funnel_clk_dis,
    input  logic                     i_funnel_clk_dis_ctrl,
    input  logic                     i_funnel_func_clamp,

    // MMR enables that gate the functional clock (per-instance).
    input  logic [CLA_W-1:0] cla_func_enable,
    input  logic [DST_W-1:0] dst_func_enable,
    input  logic [NTR_W-1:0] ntr_func_enable,
    input  logic dst_sink_func_enable,
    input  logic ntr_sink_func_enable,
    input  logic funnel_func_enable,

    // CLA gated outputs (per-instance)
    output logic [CLA_W-1:0]         cla_gated_clock,
    output logic [CLA_W-1:0]         cla_gated_reset_n,
    output logic [CLA_W-1:0]         cla_gated_reset_n_warm_ovrride,
    output logic [CLA_W-1:0]         cla_gated_func_clamp,

    // DST gated outputs (per-instance)
    output logic [DST_W-1:0]         dst_gated_clock,
    output logic [DST_W-1:0]         dst_gated_reset_n,
    output logic [DST_W-1:0]         dst_gated_reset_n_warm_ovrride,
    output logic [DST_W-1:0]         dst_gated_func_clamp,

    // NTRACE gated outputs (per-instance)
    output logic [NTR_W-1:0]         ntr_gated_clock,
    output logic [NTR_W-1:0]         ntr_gated_reset_n,
    output logic [NTR_W-1:0]         ntr_gated_reset_n_warm_ovrride,
    output logic [NTR_W-1:0]         ntr_gated_func_clamp,

    // TNIF (combined trace-network) gated outputs (per-connection)
    output logic [TNIF_W-1:0]        tnif_gated_clock,
    output logic [TNIF_W-1:0]        tnif_gated_reset_n,
    output logic [TNIF_W-1:0]        tnif_gated_reset_n_warm_ovrride,
    output logic [TNIF_W-1:0]        tnif_gated_func_clamp,

    // DST sink gated outputs (scalar)
    output logic                     dst_sink_gated_clock,
    output logic                     dst_sink_gated_reset_n,
    output logic                     dst_sink_gated_reset_n_warm_ovrride,
    output logic                     dst_sink_gated_func_clamp,

    // NTR sink gated outputs (scalar)
    output logic                     ntr_sink_gated_clock,
    output logic                     ntr_sink_gated_reset_n,
    output logic                     ntr_sink_gated_reset_n_warm_ovrride,
    output logic                     ntr_sink_gated_func_clamp,

    // Funnel gated outputs (scalar)
    output logic                     funnel_gated_clock,
    output logic                     funnel_gated_reset_n,
    output logic                     funnel_gated_reset_n_warm_ovrride,
    output logic                     funnel_gated_func_clamp
);

    // -------------------------------------------------------------------------
    // CLA per-instance i_clk / rst / clamp. Functional clock enable comes from the
    // per-instance CLA control register (EnableCla).
    // -------------------------------------------------------------------------
    if (NUM_CLA_INST > 0) begin : cla_crc_gen
        for (genvar ii = 0; ii < NUM_CLA_INST; ii++) begin : cla_crc
            generic_ipx_clk_rst_ctrl u_cla_ipx_clk_rst_ctrl(
                .i_clk(i_clk),
                .i_func_clk_en(cla_func_enable[ii]),
                .i_clk_dis_val(i_cla_clk_dis[ii]),
                .i_clk_dis_ctrl(i_cla_clk_dis_ctrl[ii]),
                .i_test_icg_en(i_test_icg_en),
                .i_reset_n(i_rst_n),
                .i_fuse_dis(i_cla_fuse_dis[ii]),
                .i_test_reset_n(i_test_reset_n),
                .i_test_reset_en(i_test_reset_en),
                .i_func_clamp(i_cla_func_clamp[ii]),
                .o_gated_clk(cla_gated_clock[ii]),
                .o_gated_reset_n(cla_gated_reset_n[ii]),
                .o_gated_func_clamp(cla_gated_func_clamp[ii])
            );
        end
    end else begin : cla_crc_tie
        assign cla_gated_clock      = '0;
        assign cla_gated_reset_n    = '0;
        assign cla_gated_func_clamp = '1;
    end
    assign cla_gated_reset_n_warm_ovrride = {CLA_W{i_critical_signal_hold}} | cla_gated_reset_n;

    // -------------------------------------------------------------------------
    // DST per-instance i_clk / rst / clamp. Functional clock enable comes from the
    // per-instance DST control register (Trdstenable).
    // -------------------------------------------------------------------------
    if (NUM_DST_INST > 0) begin : dst_crc_gen
        for (genvar ii = 0; ii < NUM_DST_INST; ii++) begin : dst_crc
            generic_ipx_clk_rst_ctrl u_dst_ipx_clk_rst_ctrl(
                .i_clk(i_clk),
                .i_func_clk_en(dst_func_enable[ii]),
                .i_clk_dis_val(i_dst_clk_dis[ii]),
                .i_clk_dis_ctrl(i_dst_clk_dis_ctrl[ii]),
                .i_test_icg_en(i_test_icg_en),
                .i_reset_n(i_rst_n),
                .i_fuse_dis(i_dst_fuse_dis[ii]),
                .i_test_reset_n(i_test_reset_n),
                .i_test_reset_en(i_test_reset_en),
                .i_func_clamp(i_dst_func_clamp[ii]),
                .o_gated_clk(dst_gated_clock[ii]),
                .o_gated_reset_n(dst_gated_reset_n[ii]),
                .o_gated_func_clamp(dst_gated_func_clamp[ii])
            );
        end
    end else begin : dst_crc_tie
        assign dst_gated_clock      = '0;
        assign dst_gated_reset_n    = '0;
        assign dst_gated_func_clamp = '1;
    end
    assign dst_gated_reset_n_warm_ovrride = {DST_W{i_critical_signal_hold}} | dst_gated_reset_n;

    // -------------------------------------------------------------------------
    // NTRACE per-instance i_clk / rst / clamp.
    // -------------------------------------------------------------------------
    if (NUM_NTRACE_INST > 0) begin : ntr_crc_gen
        for (genvar ii = 0; ii < NUM_NTRACE_INST; ii++) begin : ntr_crc
            generic_ipx_clk_rst_ctrl u_ntr_ipx_clk_rst_ctrl(
                .i_clk(i_clk),
                .i_func_clk_en(ntr_func_enable[ii]),
                .i_clk_dis_val(i_ntr_clk_dis[ii]),
                .i_clk_dis_ctrl(i_ntr_clk_dis_ctrl[ii]),
                .i_test_icg_en(i_test_icg_en),
                .i_reset_n(i_rst_n),
                .i_fuse_dis(i_ntr_fuse_dis[ii]),
                .i_test_reset_n(i_test_reset_n),
                .i_test_reset_en(i_test_reset_en),
                .i_func_clamp(i_ntr_func_clamp[ii]),
                .o_gated_clk(ntr_gated_clock[ii]),
                .o_gated_reset_n(ntr_gated_reset_n[ii]),
                .o_gated_func_clamp(ntr_gated_func_clamp[ii])
            );
        end
    end else begin : ntr_crc_tie
        assign ntr_gated_clock      = '0;
        assign ntr_gated_reset_n    = '0;
        assign ntr_gated_func_clamp = '1;
    end
    assign ntr_gated_reset_n_warm_ovrride = {NTR_W{i_critical_signal_hold}} | ntr_gated_reset_n;

    // -------------------------------------------------------------------------
    // TNIF (combined trace-network) i_clk / rst / clamp. The per-feature (DST_W /
    // NTR_W) controls are width-cast up to the connection count. Absent upper
    // instances are filled with 1'b1 so the AND'ed combination simply tracks
    // whichever block is present at that index (the fill mask is the bitwise
    // complement of the cast all-ones vector). Clock/clamp/fuse-disable all
    // track both features with a bitwise AND per connection index, so a tnif
    // lane is only fused off when both the DST and NTRACE instance feeding that
    // lane are fused off.
    // -------------------------------------------------------------------------
    if ((NUM_DST_INST > 0) || (NUM_NTRACE_INST > 0)) begin : tnif_crc_gen
        logic [TNIF_W-1:0] dst_func_clamp_ext,   ntr_func_clamp_ext;
        logic [TNIF_W-1:0] dst_clk_dis_ext,      ntr_clk_dis_ext;
        logic [TNIF_W-1:0] dst_clk_dis_ctrl_ext, ntr_clk_dis_ctrl_ext;
        logic [TNIF_W-1:0] dst_fuse_dis_ext,     ntr_fuse_dis_ext;
        logic [TNIF_W-1:0] tnif_func_clk_en;

        // func_clamp, clk_dis and clk_dis_ctrl are all AND-combined into the
        // tnif controls below, so an ABSENT block must contribute the AND-
        // identity ('1) — not '0 — so the present block governs. Defaulting to
        // '0 forces the AND result to 0, which:
        //   - for clk_dis_ctrl: drops the GRC clock-enable override, leaving the
        //     tnif clock gated on func_clk_en (= dst/ntr func_enable = 0 while
        //     idle/in reset). The tnif clock then stays OFF across the whole
        //     reset window, so its synchronous-reset staging flops
        //     (tnif_tr_valid/src_int) never clock in and stay X, propagating X
        //     into the trace network and sink RAM.
        //   - for func_clamp: leaves the tnif output UNclamped even when the
        //     sole present block asserts its clamp.
        assign dst_func_clamp_ext   = NUM_DST_INST > 0 ? TNIF_W'(i_dst_func_clamp)   | ~(TNIF_W'({DST_W{1'b1}})) : '1;
        assign dst_clk_dis_ext      = NUM_DST_INST > 0 ? TNIF_W'(i_dst_clk_dis)      | ~(TNIF_W'({DST_W{1'b1}})) : '1;
        assign dst_clk_dis_ctrl_ext = NUM_DST_INST > 0 ? TNIF_W'(i_dst_clk_dis_ctrl) | ~(TNIF_W'({DST_W{1'b1}})) : '1;
        assign ntr_func_clamp_ext   = NUM_NTRACE_INST > 0 ? TNIF_W'(i_ntr_func_clamp)   | ~(TNIF_W'({NTR_W{1'b1}})) : '1;
        assign ntr_clk_dis_ext      = NUM_NTRACE_INST > 0 ? TNIF_W'(i_ntr_clk_dis)      | ~(TNIF_W'({NTR_W{1'b1}})) : '1;
        assign ntr_clk_dis_ctrl_ext = NUM_NTRACE_INST > 0 ? TNIF_W'(i_ntr_clk_dis_ctrl) | ~(TNIF_W'({NTR_W{1'b1}})) : '1;
        assign dst_fuse_dis_ext     = NUM_DST_INST    > 0 ? TNIF_W'(i_dst_fuse_dis)     | ~(TNIF_W'({DST_W{1'b1}})) : '1;
        assign ntr_fuse_dis_ext     = NUM_NTRACE_INST > 0 ? TNIF_W'(i_ntr_fuse_dis)     | ~(TNIF_W'({NTR_W{1'b1}})) : '1;

        logic [TNIF_W-1:0] tnif_clk_dis, tnif_clk_dis_ctrl, tnif_func_clamp;
        logic [TNIF_W-1:0] tnif_fuse_dis;
        assign tnif_clk_dis      = dst_clk_dis_ext      & ntr_clk_dis_ext;
        assign tnif_clk_dis_ctrl = dst_clk_dis_ctrl_ext & ntr_clk_dis_ctrl_ext;
        assign tnif_func_clamp   = dst_func_clamp_ext   & ntr_func_clamp_ext;
        assign tnif_fuse_dis     = dst_fuse_dis_ext     & ntr_fuse_dis_ext;
        assign tnif_func_clk_en  = TNIF_W'(dst_func_enable) | TNIF_W'(ntr_func_enable);

        for (genvar ii = 0; ii < TNIF_CONNECTIONS; ii++) begin : tnif_crc
            generic_ipx_clk_rst_ctrl u_tnif_ipx_clk_rst_ctrl(
                .i_clk(i_clk),
                .i_func_clk_en(tnif_func_clk_en[ii]),
                .i_clk_dis_val(tnif_clk_dis[ii]),
                .i_clk_dis_ctrl(tnif_clk_dis_ctrl[ii]),
                .i_test_icg_en(i_test_icg_en),
                .i_reset_n(i_rst_n),
                .i_fuse_dis(tnif_fuse_dis[ii]),
                .i_test_reset_n(i_test_reset_n),
                .i_test_reset_en(i_test_reset_en),
                .i_func_clamp(tnif_func_clamp[ii]),
                .o_gated_clk(tnif_gated_clock[ii]),
                .o_gated_reset_n(tnif_gated_reset_n[ii]),
                .o_gated_func_clamp(tnif_gated_func_clamp[ii])
            );
        end
    end else begin : tnif_crc_tie
        assign tnif_gated_clock      = '0;
        assign tnif_gated_reset_n    = '0;
        assign tnif_gated_func_clamp = '1;
    end
    assign tnif_gated_reset_n_warm_ovrride = {TNIF_W{i_critical_signal_hold}} | tnif_gated_reset_n;

    // -------------------------------------------------------------------------
    // DST sink i_clk / rst / clamp (scalar domain).
    // -------------------------------------------------------------------------
    generic_ipx_clk_rst_ctrl u_dst_sink_ipx_clk_rst_ctrl(
        .i_clk(i_clk),
        .i_func_clk_en(dst_sink_func_enable),
        .i_clk_dis_val(i_dst_sink_clk_dis),
        .i_clk_dis_ctrl(i_dst_sink_clk_dis_ctrl),
        .i_test_icg_en(i_test_icg_en),
        .i_reset_n(i_rst_n),
        .i_fuse_dis(i_dst_sink_fuse_dis),
        .i_test_reset_n(i_test_reset_n),
        .i_test_reset_en(i_test_reset_en),
        .i_func_clamp(i_dst_sink_func_clamp),
        .o_gated_clk(dst_sink_gated_clock),
        .o_gated_reset_n(dst_sink_gated_reset_n),
        .o_gated_func_clamp(dst_sink_gated_func_clamp)
    );
    assign dst_sink_gated_reset_n_warm_ovrride = i_critical_signal_hold | dst_sink_gated_reset_n;

    // -------------------------------------------------------------------------
    // NTR sink i_clk / rst / clamp (scalar domain).
    // -------------------------------------------------------------------------
    generic_ipx_clk_rst_ctrl u_ntr_sink_ipx_clk_rst_ctrl(
        .i_clk(i_clk),
        .i_func_clk_en(ntr_sink_func_enable),
        .i_clk_dis_val(i_ntr_sink_clk_dis),
        .i_clk_dis_ctrl(i_ntr_sink_clk_dis_ctrl),
        .i_test_icg_en(i_test_icg_en),
        .i_reset_n(i_rst_n),
        .i_fuse_dis(i_ntr_sink_fuse_dis),
        .i_test_reset_n(i_test_reset_n),
        .i_test_reset_en(i_test_reset_en),
        .i_func_clamp(i_ntr_sink_func_clamp),
        .o_gated_clk(ntr_sink_gated_clock),
        .o_gated_reset_n(ntr_sink_gated_reset_n),
        .o_gated_func_clamp(ntr_sink_gated_func_clamp)
    );
    assign ntr_sink_gated_reset_n_warm_ovrride = i_critical_signal_hold | ntr_sink_gated_reset_n;

    // -------------------------------------------------------------------------
    // Funnel i_clk / rst / clamp (scalar domain).
    // -------------------------------------------------------------------------
    generic_ipx_clk_rst_ctrl u_funnel_ipx_clk_rst_ctrl(
        .i_clk(i_clk),
        .i_func_clk_en(funnel_func_enable),
        .i_clk_dis_val(i_funnel_clk_dis),
        .i_clk_dis_ctrl(i_funnel_clk_dis_ctrl),
        .i_test_icg_en(i_test_icg_en),
        .i_reset_n(i_rst_n),
        .i_fuse_dis(i_funnel_fuse_dis),
        .i_test_reset_n(i_test_reset_n),
        .i_test_reset_en(i_test_reset_en),
        .i_func_clamp(i_funnel_func_clamp),
        .o_gated_clk(funnel_gated_clock),
        .o_gated_reset_n(funnel_gated_reset_n),
        .o_gated_func_clamp(funnel_gated_func_clamp)
    );
    assign funnel_gated_reset_n_warm_ovrride = i_critical_signal_hold | funnel_gated_reset_n;

endmodule
