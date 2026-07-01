// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`include "axi/typedef.svh"

package dfd_CL_axi_pkg;
	import dfd_CL_pkg::*;


	//------------------------------------------------------------------------------
	// Convert AXI Bridge Address for AXI Switch Address Map
	//------------------------------------------------------------------------------
	function automatic [dfd_addr_map_pkg::SW_ADDR_MSB:0] sw_addr_conv;
		input [dfd_addr_map_pkg::BG_ADDR_MSB:0] bg_addr;
		begin
			sw_addr_conv = {bg_addr[dfd_addr_map_pkg::Priv_MSB:dfd_addr_map_pkg::Priv_LSB], bg_addr[dfd_addr_map_pkg::ITF_CoreID_MSB:0]};
		end
	endfunction


	localparam SMC_SRCID = dfd_CL_pkg::CL_CLUSTER_CPL_SRCID;
	localparam PMNW_SRCID = 4'h3;
	localparam CPL_SRCID = SMC_SRCID;

	// AXI Bridge Configuration
	localparam int unsigned BgNumMasters            = 4;
	localparam int unsigned BgNumSlaves             = 3;
	localparam int unsigned BgMaxMstTrans           = 256;
	localparam int unsigned BgMaxSlvTrans           = 256;
	localparam int unsigned BgAxiIdWidthSlvPorts    = 10;
	localparam int unsigned BgAxiIdWidthMstPorts    = BgAxiIdWidthSlvPorts + $clog2(BgNumMasters);
	localparam int unsigned BgAxiIdUsed             = 4; // false id conflicts
	localparam bit          BgUniqueIds             = 1'b0;
	localparam bit          BgSelHashIds            = 1'b1;
	localparam int unsigned BgAxiAddrWidth          = 52;
	localparam int unsigned BgAxiDataWidth          = 512;
	localparam int unsigned BgAxiStrbWidth          = BgAxiDataWidth / 8;
	localparam int unsigned BgAxiUserWidth          = 8;
	localparam int unsigned BgNoAddrRules           = 6;

	localparam axi_pkg::xbar_cfg_t bg_cfg = '{
		NoSlvPorts:         BgNumMasters,
		NoMstPorts:         BgNumSlaves,
		MaxMstTrans:        BgMaxMstTrans,
		MaxSlvTrans:        BgMaxSlvTrans,
		FallThrough:        1'b0,
		LatencyMode:        axi_pkg::CUT_ALL_PORTS,
		AxiIdWidthSlvPorts: BgAxiIdWidthSlvPorts,
		AxiIdUsedSlvPorts:  BgAxiIdUsed,
		UniqueIds:          BgUniqueIds,
		SelHashIds:         BgSelHashIds,
		AxiAddrWidth:       BgAxiAddrWidth,
		AxiDataWidth:       BgAxiDataWidth,
		NoAddrRules:        BgNoAddrRules,
		default:            '0
	};

	typedef struct packed {
		int unsigned idx;
		logic [BgAxiAddrWidth-1:0] start_addr;
		logic [BgAxiAddrWidth-1:0] end_addr;
	} xbar_bg_rule_t;


	typedef logic [BgAxiIdWidthSlvPorts-1:0] bg_id_slv_t;
	typedef logic [BgAxiIdWidthMstPorts-1:0] bg_id_mst_t;
	typedef logic       [BgAxiAddrWidth-1:0]   bg_addr_t;
	typedef logic       [BgAxiDataWidth-1:0]   bg_data_t;
	typedef logic       [BgAxiStrbWidth-1:0]   bg_strb_t;
	typedef logic       [BgAxiUserWidth-1:0]   bg_user_t;
	typedef xbar_bg_rule_t                     bg_rule_t; // Has to be the same width as axi addr

	`AXI_TYPEDEF_ALL_CT(bg_mst, bg_mst_axi_req_t, bg_mst_axi_rsp_t, bg_addr_t, bg_id_mst_t, bg_data_t, bg_strb_t, bg_user_t)
	`AXI_TYPEDEF_ALL_CT(bg_slv, bg_slv_axi_req_t, bg_slv_axi_rsp_t, bg_addr_t, bg_id_slv_t, bg_data_t, bg_strb_t, bg_user_t)

	// Trace AXI configuration
	localparam int unsigned TrAxiIdWidthSlvPorts = BgAxiIdWidthSlvPorts - 1;
	typedef logic [TrAxiIdWidthSlvPorts-1:0] tr_id_slv_t;

	`AXI_TYPEDEF_ALL_CT(tr_slv, tr_slv_axi_req_t, tr_slv_axi_rsp_t, bg_addr_t, tr_id_slv_t, bg_data_t, bg_strb_t, bg_user_t)

	// Index mapping for BG
	localparam int unsigned BG_SLV_IDX_SZ  = 0;
	localparam int unsigned BG_SLV_IDX_SC  = 1;
	localparam int unsigned BG_SLV_IDX_MEM = 2;


	localparam int unsigned BG_MST_IDX_SZ  = 0;
	localparam int unsigned BG_MST_IDX_SC  = 1;
	localparam int unsigned BG_MST_IDX_TR  = 2;
	localparam int unsigned BG_MST_IDX_MEM = 3;


	localparam bit [BgNumMasters - 1 : 0][BgNumSlaves - 1 : 0] bg_connectivity_map = {  //   MEM       SC      SZ
		{   1'b0,    1'b1,   1'b1}, // MEM
		{   1'b1,    1'b1,   1'b1}, // TR
		{   1'b1,    1'b1,   1'b1}, // SC
		{   1'b1,    1'b1,   1'b0}  // SZ
	};

	// AXI Switch Configuration
	localparam int unsigned SwNumMasters            = 3;
	localparam int unsigned SwNumSlaves             = 6;
	localparam int unsigned SwMaxMstTrans           = 4;
	localparam int unsigned SwMaxSlvTrans           = 4;
	localparam int unsigned SwAxiIdWidthSlvPorts    = BgAxiIdWidthMstPorts;
	localparam int unsigned SwAxiIdWidthMstPorts    = SwAxiIdWidthSlvPorts + $clog2(SwNumMasters);
	localparam int unsigned SwAxiIdUsed             = 4; // false id conflicts
	localparam bit          SwUniqueIds             = 1'b0;
	localparam bit          SwSelHashIds            = 1'b1;
	localparam int unsigned SwAxiAddrWidth          = 23;
	localparam int unsigned SwAxiDataWidth          = 64;
	localparam int unsigned SwAxiStrbWidth          = SwAxiDataWidth / 8;
	localparam int unsigned SwAxiUserWidth          = 8;
	localparam int unsigned SwNoAddrRules           = 7;

	localparam int SwEffId_MSB = BgAxiIdWidthSlvPorts - 1 - (SwAxiIdWidthMstPorts - SwAxiIdWidthSlvPorts);    //Effective AXI ID bits from Switch to Bridge
	localparam int SwEffId_LSB = 0;
	localparam int SwMstId_MSB = SwAxiIdWidthMstPorts - 1;
	localparam int SwMstId_LSB = SwAxiIdWidthSlvPorts;
	localparam int SzMstId_MSB = BgAxiIdWidthSlvPorts-1;
	localparam int SzMstId_LSB = BgAxiIdWidthSlvPorts-(SwAxiIdWidthMstPorts-SwAxiIdWidthSlvPorts);

	localparam axi_pkg::xbar_cfg_t sw_cfg = '{
		NoSlvPorts:         SwNumMasters,
		NoMstPorts:         SwNumSlaves,
		MaxMstTrans:        SwMaxMstTrans,
		MaxSlvTrans:        SwMaxSlvTrans,
		FallThrough:        1'b0,
		LatencyMode:        axi_pkg::CUT_ALL_PORTS,
		AxiIdWidthSlvPorts: SwAxiIdWidthSlvPorts,
		AxiIdUsedSlvPorts:  SwAxiIdUsed,
		UniqueIds:          SwUniqueIds,
		SelHashIds:         SwSelHashIds,
		AxiAddrWidth:       SwAxiAddrWidth,
		AxiDataWidth:       SwAxiDataWidth,
		NoAddrRules:        SwNoAddrRules,
		default:            '0
	};

	typedef struct packed {
		int unsigned idx;
		logic [SwAxiAddrWidth-1:0] start_addr;
		logic [SwAxiAddrWidth-1:0] end_addr;
	} xbar_sw_rule_t;

	typedef logic [SwAxiIdWidthSlvPorts-1:0] sw_id_slv_t;
	typedef logic [SwAxiIdWidthMstPorts-1:0] sw_id_mst_t;
	typedef logic       [SwAxiAddrWidth-1:0]   sw_addr_t;
	typedef logic       [SwAxiDataWidth-1:0]   sw_data_t;
	typedef logic       [SwAxiStrbWidth-1:0]   sw_strb_t;
	typedef logic       [SwAxiUserWidth-1:0]   sw_user_t;
	typedef xbar_sw_rule_t                     sw_rule_t; // Has to be the same width as axi addr

	`AXI_TYPEDEF_ALL_CT(sw_mst, sw_mst_axi_req_t, sw_mst_axi_rsp_t, sw_addr_t, sw_id_mst_t, sw_data_t, sw_strb_t, sw_user_t)
	`AXI_TYPEDEF_ALL_CT(sw_slv, sw_slv_axi_req_t, sw_slv_axi_rsp_t, sw_addr_t, sw_id_slv_t, sw_data_t, sw_strb_t, sw_user_t)


	// Index mapping for SW
	localparam int unsigned SW_SLV_IDX_RING = 0;
	localparam int unsigned SW_SLV_IDX_DM = 1;
	localparam int unsigned SW_SLV_IDX_CPL = 2;
	localparam int unsigned SW_SLV_IDX_ACLINT = 3;
	localparam int unsigned SW_SLV_IDX_SZ = 4;

	localparam int unsigned SW_MST_IDX_SZ = 0;
	localparam int unsigned SW_MST_IDX_CPL = 1;
	localparam int unsigned SW_MST_IDX_JT = 2;

	localparam bit [SwNumMasters - 1 : 0][SwNumSlaves - 1 : 0] sw_connectivity_map = {  //    SZ      MMR   ACLINT     CPL       DM     RING
		{   1'b1,    1'b1,    1'b1,   1'b1,    1'b1,    1'b1}, // JT
		{   1'b1,    1'b1,    1'b1,   1'b0,    1'b1,    1'b1}, // CPL
		{   1'b0,    1'b1,    1'b1,   1'b1,    1'b1,    1'b1}  // SZ
	};


	// Cluster Ring Configuration
	// axi xbar node configuration
	localparam int unsigned MaxNoAddrRules  = 3;    //MAX(s_cfg.NoAddrRules,m_cfg.NoAddrRules)
	localparam int unsigned MaxNoIdRules    = 1;    //MAX(s_cfg.NoIdRules,m_cfg.NoIdRules)
	// axi configuration
	localparam int unsigned RgAxiAddrWidth      =  23;
	localparam int unsigned RgAxiDataWidth      =  64;
	localparam int unsigned RgAxiStrbWidth      =  RgAxiDataWidth / 8;
	localparam int unsigned RgAxiUserWidth      =  8;                                   // Axi User Width
	localparam int unsigned RgAxiSrcIdWidth     =  2;                                   // Axi Source ID portion Width
	localparam int unsigned RgAxiTxIdWidth      =  SwAxiIdWidthMstPorts;                // Axi Transaction ID portion Width
	localparam int unsigned RgAxiIdWidth        =  RgAxiSrcIdWidth + RgAxiTxIdWidth;    // Axi ID Width

	localparam axi_pkg::axinode_cfg_t s_cfg = '{
		NoSlvPorts:         1,
		NoMstPorts:         2,
		MaxMstTrans:        32'd4,
		MaxSlvTrans:        32'd4,
		FallThrough:        1'b0,
		LatencyMode:        axi_pkg::CUT_ALL_PORTS,
		AxiIdWidth:         RgAxiIdWidth,
		AxiSrcIdWidth:      RgAxiSrcIdWidth,
		AxiTxIdWidth:       RgAxiTxIdWidth,
		AxiAddrWidth:       RgAxiAddrWidth,
		AxiDataWidth:       RgAxiDataWidth,
		AxiUserWidth:       RgAxiUserWidth,
		NoAddrRules:        3,
		NoIdRules:          1,
		default:            '0
	};  //1S2M_node

	localparam axi_pkg::axinode_cfg_t m_cfg = '{
		NoSlvPorts:         2,
		NoMstPorts:         1,
		MaxMstTrans:        32'd4,
		MaxSlvTrans:        32'd4,
		FallThrough:        1'b0,
		LatencyMode:        axi_pkg::CUT_ALL_PORTS,
		AxiIdWidth:         RgAxiIdWidth,
		AxiSrcIdWidth:      RgAxiSrcIdWidth,
		AxiTxIdWidth:       RgAxiTxIdWidth,
		AxiAddrWidth:       RgAxiAddrWidth,
		AxiDataWidth:       RgAxiDataWidth,
		AxiUserWidth:       RgAxiUserWidth,
		NoAddrRules:        3,
		NoIdRules:          1,
		default:            '0
	};  //2S1M_node

	typedef struct packed {
		int unsigned idx;
		logic [RgAxiAddrWidth-1:0] start_addr;
		logic [RgAxiAddrWidth-1:0] end_addr;
	} xbar_rg_rule_t;

	typedef struct packed {
		int unsigned idx;
		logic [RgAxiSrcIdWidth-1:0] start_addr;
		logic [RgAxiSrcIdWidth-1:0] end_addr;
	} srcid1_rule_t;


	typedef logic    [RgAxiIdWidth-1:0]     rg_id_mst_t;
	typedef logic  [RgAxiAddrWidth-1:0]       rg_addr_t;
	typedef logic  [RgAxiDataWidth-1:0]       rg_data_t;
	typedef logic  [RgAxiStrbWidth-1:0]       rg_strb_t;
	typedef logic  [RgAxiUserWidth-1:0]       rg_user_t;
	typedef                xbar_rg_rule_t     rg_rule_t;
	typedef                 srcid1_rule_t     id_rule_t;

	`AXI_TYPEDEF_ALL_CT(rg_mst, rg_mst_axi_req_t, rg_mst_axi_rsp_t, rg_addr_t, rg_id_mst_t, rg_data_t, rg_strb_t, rg_user_t)

	// 4B AXI Bus for Trace
	typedef logic       [32-1:0]               rg_4b_data_t;
	typedef logic       [4-1:0]                rg_4b_strb_t;
	`AXI_TYPEDEF_ALL_CT(rg_mst_4b, rg_mst_axi_4b_req_t, rg_mst_axi_4b_rsp_t, rg_addr_t, rg_id_mst_t, rg_4b_data_t, rg_4b_strb_t, rg_user_t)

//Struct Nomenclature: "A_B_mst": Request direction from A master port to B slave port
	//Match bridge slave port id width to avoid ID remapping in the bridge
	`AXI_TYPEDEF_ALL_CT(sw_sz_mst, sw_sz_mst_axi_req_t, sw_sz_mst_axi_rsp_t, sw_addr_t, bg_id_slv_t, sw_data_t, sw_strb_t, sw_user_t)
	//address 23 coming from axi_switch
	`AXI_TYPEDEF_ALL_CT(sz_bg_mst, sz_bg_mst_axi_req_t, sz_bg_mst_axi_rsp_t, sw_addr_t, bg_id_slv_t, bg_data_t, bg_strb_t, bg_user_t)
	//Only 23 bits address needed @ BG -> SZ & SZ -> SW (Assume any request sent this way is MMR (including Core Interrupt File) access.
	`AXI_TYPEDEF_ALL_CT(bg_sz_mst, bg_sz_mst_axi_req_t, bg_sz_mst_axi_rsp_t, sw_addr_t, bg_id_mst_t, bg_data_t, bg_strb_t, bg_user_t)
	`AXI_TYPEDEF_ALL_CT(sz_sw_mst, sz_sw_mst_axi_req_t, sz_sw_mst_axi_rsp_t, sw_addr_t, sw_id_slv_t, sw_data_t, sw_strb_t, sw_user_t)   // same as sw_slv

//DM AXI Splitter Configuration
	localparam int unsigned DmNumMasters            = 1;
	localparam int unsigned DmNumSlaves             = 4;
	localparam int unsigned DmMaxMstTrans           = 1;
	localparam int unsigned DmMaxSlvTrans           = 1;
	localparam int unsigned DmAxiIdWidthSlvPorts    = SwAxiIdWidthMstPorts;
// localparam int unsigned DmAxiIdWidthMstPorts    = DmAxiIdWidthSlvPorts + $clog2(DmNumMasters);
	localparam int unsigned DmAxiIdWidthMstPorts    = DmAxiIdWidthSlvPorts;
	localparam int unsigned DmAxiIdUsed             = 4; //False ID conflicts
	localparam bit          DmUniqueIds             = 1'b0;
	localparam int unsigned DmAxiAddrWidth          = SwAxiAddrWidth;
	localparam int unsigned DmAxiDataWidth          = 64;
	localparam int unsigned DmAxiStrbWidth          = DmAxiDataWidth / 8;
	localparam int unsigned DmAxiUserWidth          = 8;
	localparam int unsigned DmNoAddrRules           = 4;

	localparam axi_pkg::xbar_cfg_t dm_cfg = '{
		NoSlvPorts:         DmNumMasters,
		NoMstPorts:         DmNumSlaves,
		MaxMstTrans:        DmMaxMstTrans,
		MaxSlvTrans:        DmMaxSlvTrans,
		FallThrough:        1'b0,
		LatencyMode:        axi_pkg::CUT_SLV_PORTS,
		AxiIdWidthSlvPorts: DmAxiIdWidthSlvPorts,
		AxiIdUsedSlvPorts:  DmAxiIdUsed,
		UniqueIds:          DmUniqueIds,
		AxiAddrWidth:       DmAxiAddrWidth,
		AxiDataWidth:       DmAxiDataWidth,
		NoAddrRules:        DmNoAddrRules,
		default:            '0
	};

	//typedef axi_pkg::xbar_rule_27_t            dm_rule_t; // Has to be the same width as axi addr
	typedef struct packed {
		int unsigned idx;
		logic [SwAxiAddrWidth-1:0] start_addr;
		logic [SwAxiAddrWidth-1:0] end_addr;
	} dm_rule_t;

	typedef logic       [32-1:0]               dmi_4B_data_t;
	typedef logic       [4-1:0]                dmi_4B_strb_t;

	`AXI_TYPEDEF_ALL_CT(dm_mst, dm_mst_axi_4b_req_t, dm_mst_axi_4b_rsp_t, sw_addr_t, sw_id_mst_t, dmi_4B_data_t, dmi_4B_strb_t, sw_user_t)
endpackage
