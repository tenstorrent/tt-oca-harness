// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

package dfd_addr_map_pkg;

    //Cluster Address Width
    localparam int unsigned CLUSTER_ADDR_WIDTH = 52;
    
    //Base address for Ascalon Scratch Pad Memory
    localparam [CLUSTER_ADDR_WIDTH-1:0] CLUSTER_SP_BASE  = 52'h6000_0000;
    localparam [CLUSTER_ADDR_WIDTH-1:0] CLUSTER_MMR_BASE = 52'h4000_0000;

    //MMR Address Bit Positions
    localparam int unsigned BG_ADDR_MSB = 51;
    localparam int unsigned SW_ADDR_MSB = 22;
    localparam int unsigned MMR_Base_Addr_LSB = 27;
    localparam int unsigned SPD_Base_Addr_LSB = 28;
    localparam int unsigned Priv_LSB = 25;
    localparam int unsigned Priv_MSB = 26;
    localparam int unsigned ClusterID_LSB = 21;
    localparam int unsigned ClusterID_MSB = 24;
    localparam int unsigned Offset_4k_MSB = 11; 
    localparam int unsigned Offset_64k_MSB = 15; 
    localparam int unsigned Offset_256k_MSB = 17; 
    localparam int unsigned ITF_S_Mode_GuestID_MSB = 17;
    localparam int unsigned ITF_S_Mode_GuestID_LSB = 12;
    localparam int unsigned ITF_CoreID_MSB = 20;
    localparam int unsigned ITF_CoreID_LSB = 18;
    localparam int unsigned MMR_DeviceID_MSB = 20;
    localparam int unsigned MMR_DeviceID_LSB = 16;
    
    //MMR Categories
    localparam [1:0] M_MMR                      = 2'b01;
    localparam [1:0] S_MMR                      = 2'b11;
    localparam [1:0] M_ITF                      = 2'b00;
    localparam [1:0] S_ITF                      = 2'b10;

    //Core ID
    localparam [2:0] CoreID_C0                  = 3'b000;
    localparam [2:0] CoreID_C1                  = 3'b001;
    localparam [2:0] CoreID_C2                  = 3'b010;
    localparam [2:0] CoreID_C3                  = 3'b011;
    localparam [2:0] CoreID_C4                  = 3'b100;
    localparam [2:0] CoreID_C5                  = 3'b101;
    localparam [2:0] CoreID_C6                  = 3'b110;
    localparam [2:0] CoreID_C7                  = 3'b111;

    //Device ID
    localparam [4:0] MMR_DeviceID_C0            = {2'b00, CoreID_C0};
    localparam [4:0] MMR_DeviceID_C1            = {2'b00, CoreID_C1};
    localparam [4:0] MMR_DeviceID_C2            = {2'b00, CoreID_C2};
    localparam [4:0] MMR_DeviceID_C3            = {2'b00, CoreID_C3};
    localparam [4:0] MMR_DeviceID_C4            = {2'b00, CoreID_C4};
    localparam [4:0] MMR_DeviceID_C5            = {2'b00, CoreID_C5};
    localparam [4:0] MMR_DeviceID_C6            = {2'b00, CoreID_C6};
    localparam [4:0] MMR_DeviceID_C7            = {2'b00, CoreID_C7};
    localparam [4:0] MMR_DeviceID_TR            = 5'b01000;
    localparam [4:0] MMR_DeviceID_RG_RSVD_MIN   = 5'b01001;
    localparam [4:0] MMR_DeviceID_RG_RSVD_MAX   = 5'b01111;

    localparam [4:0] MMR_DeviceID_CP_MIN        = 5'b10000;
    localparam [4:0] MMR_DeviceID_CP_MAX        = 5'b10111;
    localparam [4:0] MMR_DeviceID_AC            = 5'b11000;
    localparam [4:0] MMR_DeviceID_DM            = 5'b11001;
    localparam [4:0] MMR_DeviceID_SC            = 5'b11010;
    localparam [4:0] MMR_DeviceID_SW            = 5'b11011;

    //MMR Address Map

        //SPD Base Address
            localparam [BG_ADDR_MSB-SPD_Base_Addr_LSB:0] BG_SPD_BASE_ADDR   = CLUSTER_SP_BASE[BG_ADDR_MSB:SPD_Base_Addr_LSB];
        //MMR Base Address
            localparam [BG_ADDR_MSB-MMR_Base_Addr_LSB:0] MMR_BASE_ADDR      = CLUSTER_MMR_BASE[BG_ADDR_MSB:MMR_Base_Addr_LSB];

        //SratchPad Memory Address Space
            function automatic [BG_ADDR_MSB:0] func_MMR_SPD_AddrStart ([3:0] cluster_id);
                func_MMR_SPD_AddrStart = {BG_SPD_BASE_ADDR, cluster_id, 24'h00_0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_SPD_AddrEnd ([3:0] cluster_id);
                func_MMR_SPD_AddrEnd = {BG_SPD_BASE_ADDR, cluster_id, 24'hFF_FFFF};
            endfunction

        //Interrupt File Memory Region
            function automatic [BG_ADDR_MSB:0] func_M_ITF_AddrStart;
                input logic [3:0] cluster_id;
                return  {MMR_BASE_ADDR, M_ITF, cluster_id, 21'h000000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_M_ITF_AddrEnd ([3:0] cluster_id);
                func_M_ITF_AddrEnd = {MMR_BASE_ADDR, M_ITF, cluster_id, 21'h1FFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_S_ITF_AddrStart ([3:0] cluster_id);
                func_S_ITF_AddrStart = {MMR_BASE_ADDR, S_ITF, cluster_id, 21'h000000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_S_ITF_AddrEnd ([3:0] cluster_id);
                func_S_ITF_AddrEnd = {MMR_BASE_ADDR, S_ITF, cluster_id, 21'h1FFFFF};
            endfunction

        //Cores MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_C0_AddrStart ([3:0] cluster_id);
                func_MMR_C0_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C0, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C1_AddrStart ([3:0] cluster_id);
                func_MMR_C1_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C1, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C2_AddrStart ([3:0] cluster_id);
                func_MMR_C2_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C2, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C3_AddrStart ([3:0] cluster_id);
                func_MMR_C3_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C3, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C4_AddrStart ([3:0] cluster_id);
                func_MMR_C4_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C4, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C5_AddrStart ([3:0] cluster_id);
                func_MMR_C5_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C5, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C6_AddrStart ([3:0] cluster_id);
                func_MMR_C6_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C6, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C7_AddrStart ([3:0] cluster_id);
                func_MMR_C7_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C7, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C0_AddrEnd ([3:0] cluster_id);
                func_MMR_C0_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C0, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C1_AddrEnd ([3:0] cluster_id);
                func_MMR_C1_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C1, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C2_AddrEnd ([3:0] cluster_id);
                func_MMR_C2_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C2, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C3_AddrEnd ([3:0] cluster_id);
                func_MMR_C3_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C3, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C4_AddrEnd ([3:0] cluster_id);
                func_MMR_C4_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C4, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C5_AddrEnd ([3:0] cluster_id);
                func_MMR_C5_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C5, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C6_AddrEnd ([3:0] cluster_id);
                func_MMR_C6_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C6, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_C7_AddrEnd ([3:0] cluster_id);
                func_MMR_C7_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_C7, 16'hFFFF};
            endfunction

        //Trace_Funnel MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_TR_AddrStart ([3:0] cluster_id);
                func_MMR_TR_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_TR, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_TR_AddrEnd ([3:0] cluster_id);
                func_MMR_TR_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_TR, 16'hFFFF};
            endfunction

        //Ring_Reserved MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_RGRS_AddrStart ([3:0] cluster_id);
                func_MMR_RGRS_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_RG_RSVD_MIN, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_RGRS_AddrEnd ([3:0] cluster_id);
                func_MMR_RGRS_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_RG_RSVD_MAX, 16'hFFFF};
            endfunction

        //Debug_Module MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_DM_AddrStart ([3:0] cluster_id);
                func_MMR_DM_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_DM, 16'h0000};
            endfunction

        //CPL MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_DM_AddrEnd ([3:0] cluster_id);
                func_MMR_DM_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_DM, 16'hFFFF};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_CP_AddrStart ([3:0] cluster_id);
                func_MMR_CP_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_CP_MIN, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_CP_AddrEnd ([3:0] cluster_id);
                func_MMR_CP_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_CP_MAX, 16'hFFFF};
            endfunction

        //ACLINT MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_AC_AddrStart ([3:0] cluster_id);
                func_MMR_AC_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_AC, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_AC_AddrEnd ([3:0] cluster_id);
                func_MMR_AC_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_AC, 16'hFFFF};
            endfunction

        //Shared_Cache MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_SC_AddrStart ([3:0] cluster_id);
                func_MMR_SC_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_SC, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_SC_AddrEnd ([3:0] cluster_id);
                func_MMR_SC_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_SC, 16'hFFFF};
            endfunction

        //AXI_Switch_Config MMRs
            function automatic [BG_ADDR_MSB:0] func_MMR_SW_AddrStart ([3:0] cluster_id);
                func_MMR_SW_AddrStart = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_SW, 16'h0000};
            endfunction

            function automatic [BG_ADDR_MSB:0] func_MMR_SW_AddrEnd ([3:0] cluster_id);
                func_MMR_SW_AddrEnd = {MMR_BASE_ADDR, M_MMR, cluster_id, MMR_DeviceID_SW, 16'hFFFF};
            endfunction


    //Assume it's MMR access, this function is used to check the MMR access is within Cluster or not
    function automatic func_IsWithinCluster;    
    input [3:0]           cluster_id;
    input [BG_ADDR_MSB:0] addr_in;
        begin
            func_IsWithinCluster = ((addr_in[ClusterID_MSB:ClusterID_LSB] == cluster_id) && (addr_in[MMR_DeviceID_MSB:MMR_DeviceID_LSB]<(MMR_DeviceID_SC+1'b1)));
        end
    endfunction

    //NOTE: this function is used by SCB to distinguish between SC_MMR access and ScratchPad access
    function automatic  IsMMRaccess_SC;    
    input [BG_ADDR_MSB:0] addr_in;
        begin
            IsMMRaccess_SC = (addr_in[MMR_DeviceID_MSB:MMR_DeviceID_LSB] == MMR_DeviceID_SC) && (addr_in[BG_ADDR_MSB:MMR_Base_Addr_LSB] == MMR_BASE_ADDR);
        end
    endfunction

endpackage

