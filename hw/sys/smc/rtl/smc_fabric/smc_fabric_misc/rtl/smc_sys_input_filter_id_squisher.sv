// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// System Input Filter + ID Squisher for System Management Controller
//
//-----------------------------------------------------------------------------


module smc_sys_input_filter_id_squisher
#(
    parameter int unsigned SYS_IN_ID_WIDTH = 9,
    parameter int unsigned XBAR_IN_ID_WIDTH = 8,
    parameter int unsigned OUT_ADDR_WIDTH = 32,
    parameter bit FILTER_REQ_PIPELINE_ENABLE = 1'b0,
    parameter bit FILTER_RSP_PIPELINE_ENABLE = 1'b0,

    parameter bit          FilterReqPipelineEnable = 1'b0,
    parameter bit          FilterRspPipelineEnable = 1'b0,
    parameter int unsigned NumFilters = 16
) (
    input  logic                                        clk_i,
    input  logic                                        rst_ni,
    input  logic                                        test_en_i,

    input  smc_pkg::smc_sys_in_56_64_6_12_axi_req_t     axi_in_req_i,
    output smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t    axi_in_resp_o,
    output smc_pkg::smc_local_32_64_6_12_axi_req_t      axi_out_req_o,
    input  smc_pkg::smc_local_32_64_6_12_axi_resp_t     axi_out_resp_i,

    // Config struct from register block
    input  filter_ctrl_reg_pkg::filter_ctrl__out_t      filter_ctrl_i   [NumFilters],
    output filter_ctrl_reg_pkg::filter_ctrl__in_t       filter_status_o [NumFilters],

    output axi_filter_pkg::filter_debug_t                filter_debug_o
);

    smc_pkg::smc_sys_in_56_64_6_12_axi_req_t    axi_filtered_req;
    smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t   axi_filtered_resp;

    smc_pkg::smc_local_32_64_6_12_axi_req_t     axi_remapped_req;
    smc_pkg::smc_local_32_64_6_12_axi_resp_t    axi_remapped_resp;

    smc_pkg::smc_local_32_64_6_12_axi_req_t     axi_prepended_req;
    smc_pkg::smc_local_32_64_6_12_axi_resp_t    axi_prepended_resp;

    //------------------//
    // System In Filter //
    //------------------//

    axi_filter_wrap #(
        .NumFilters          (NumFilters),
        .DebugOutput         (0),
        .BlockByDefault      (1'b0),
        .EnSrcIdFilter       (1'b1),
        .SrcIdUserBitStart   (0),
        .SrcIdWidth          (4),
        .EnGroupIdFilter     (1'b0),
        .GroupIdUserBitStart (4),
        .GroupIdWidth        (4),
        .EnNsFilter          (1'b1),
        .AxiAddrWidth        (smc_pkg::AXI_ADDR_WIDTH),
        .AxiIdWidth          (smc_pkg::SYS_IN_ID_WIDTH),
        .AxiDataWidth        (smc_pkg::AXI_DATA_WIDTH),
        .MaxTrans            (smc_pkg::FABRIC_MAX_TRANS),
        .ErrSlvMaxTrans      (smc_pkg::ERR_SLV_MAX_TRANS),
        .FlopReqEn           (FilterReqPipelineEnable),
        .FlopRespEn          (FilterRspPipelineEnable),
        .filter_axi_req_t    (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
        .filter_axi_resp_t   (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t),
        .filter_aw_chan_t    (smc_pkg::smc_sys_in_56_64_6_12_axi_aw_chan_t),
        .filter_w_chan_t	 (smc_pkg::smc_sys_in_56_64_6_12_axi_w_chan_t),
        .filter_b_chan_t	 (smc_pkg::smc_sys_in_56_64_6_12_axi_b_chan_t),
        .filter_ar_chan_t    (smc_pkg::smc_sys_in_56_64_6_12_axi_ar_chan_t),
        .filter_r_chan_t     (smc_pkg::smc_sys_in_56_64_6_12_axi_r_chan_t)
    ) smc_sys_inbound_filter (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .test_en_i(test_en_i),

        .filter_skip_i(1'b0),

        // Config struct from register block
        .filter_ctrl_i(filter_ctrl_i),
        .filter_status_o(filter_status_o),

        // AXI interface to the filter
        .axi_in_req_i(axi_in_req_i),
        .axi_in_resp_o(axi_in_resp_o),

        // AXI interface to the filtered output
        .axi_filtered_out_req_o(axi_filtered_req),
        .axi_filtered_out_resp_i(axi_filtered_resp),

        .filter_debug_o(filter_debug_o)
    );

    //--------------//
    // AXI ID Remap //
    //--------------//

    // Squish to 4 bits
    prim_axi_id_remap #(
        .AXI_ADDR_WIDTH(smc_pkg::AXI_ADDR_WIDTH),
        .AXI_DATA_WIDTH(smc_pkg::AXI_DATA_WIDTH),
        .AXI_USER_WIDTH(smc_pkg::AXI_USER_WIDTH),

        .AXI_ID_WIDTH_IN (SYS_IN_ID_WIDTH),
        .AXI_ID_WIDTH_OUT(XBAR_IN_ID_WIDTH),

        .input_axi_req_t  (smc_pkg::smc_sys_in_56_64_6_12_axi_req_t),
        .input_axi_resp_t (smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t),
        .output_axi_req_t (smc_pkg::smc_local_32_64_6_12_axi_req_t),
        .output_axi_resp_t(smc_pkg::smc_local_32_64_6_12_axi_resp_t),

        .MAX_INFLIGHT_IDS(smc_pkg::MAX_INFLIGHT_IDS),
        .MAX_TXNS_PER_ID (smc_pkg::FABRIC_MAX_TRANS)
    ) smc_axi_id_remap (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .test_en_i(test_en_i),

        .axi_in_req_i  (axi_filtered_req), // from filter
        .axi_in_resp_o (axi_filtered_resp), // to filter
        .axi_out_req_o (axi_remapped_req), // to prepend
        .axi_out_resp_i(axi_remapped_resp) // from prepend

    );

    //----------------//
    // AXI ID Prepend //
    //----------------//

    // Tie upper 2 id bits down
    prim_axi_id_prepend_wrap #(
        .AxiInIdWidth  (smc_pkg::SMC_INPUT_FABRIC_SLAVE_ID_WIDTH),
        .AxiOutIdWidth (smc_pkg::SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH),
        .AxiDataWidth  (smc_pkg::AXI_DATA_WIDTH),
        .AxiAddrWidth  (smc_pkg::AXI_ADDR_WIDTH),
        .AxiUserWidth  (smc_pkg::AXI_USER_WIDTH),

        .axi_in_req_t   (smc_pkg::smc_local_32_64_6_12_axi_req_t),
        .axi_in_resp_t  (smc_pkg::smc_local_32_64_6_12_axi_resp_t),
        .axi_out_req_t  (smc_pkg::smc_local_32_64_6_12_axi_req_t),
        .axi_out_resp_t (smc_pkg::smc_local_32_64_6_12_axi_resp_t)
    ) smc_axi_id_prepend_wrap (
        .axi_in_req_i   (axi_remapped_req), // from remap
        .axi_in_resp_o  (axi_remapped_resp), // to remap
        .axi_out_req_o  (axi_prepended_req), // to addr fixer
        .axi_out_resp_i (axi_prepended_resp) // from addr fixer
    );

    //------------------//
    // AXI Addres Fixer //
    //------------------//

    // cut off top address bits since going into local xbar
  	prim_axi_addr_fixer #(
		.INPUT_ADDR_W     (smc_pkg::AXI_ADDR_WIDTH),
		.OUTPUT_ADDR_W    (smc_pkg::SMC_LOCAL_ADDR_WIDTH),
		.input_axi_req_t  (smc_pkg::smc_local_32_64_6_12_axi_req_t),
		.input_axi_resp_t (smc_pkg::smc_local_32_64_6_12_axi_resp_t),
		.output_axi_req_t (smc_pkg::smc_local_32_64_6_12_axi_req_t),
		.output_axi_resp_t(smc_pkg::smc_local_32_64_6_12_axi_resp_t)
	) smc_axi_addr_fixer (
		.axi_in_req_i     (axi_prepended_req),  // from prepend
		.axi_in_resp_o    (axi_prepended_resp), // to prepend
		.axi_out_req_o    (axi_out_req_o),      // to top-level IO
		.axi_out_resp_i   (axi_out_resp_i)      // from top-level IO
	);

endmodule
