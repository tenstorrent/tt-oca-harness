// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

package dfd_CL_pkg;
localparam bit [51:27]      CL_CLUSTER_MMR_BASE              = 25'h8;
localparam bit [51:28]      CL_CLUSTER_SP_BASE               = 24'h6;
localparam bit [3:0]        CL_CLUSTER_LOCAL_SRCID           = 4'b0001;
localparam bit [3:0]        CL_CLUSTER_REMOTE_SRCID          = 4'b0000;
localparam bit [3:0]        CL_CLUSTER_CPL_SRCID             = 4'b0011;
localparam bit [55:2]       CL_DEFAULT_RESET_VECTOR          = 54'h4000; // This parameter does not match athena spec value (54'h0)
localparam bit [55:2]       CL_DEFAULT_NMI_INTERRUPT_VECTOR  = 54'h0;
localparam bit [55:2]       CL_DEFAULT_NMI_EXCEPTION_VECTOR  = 54'h0;
localparam bit [15:0][63:0] CL_DEFAULT_PMA_REGISTER          = { {15{64'h0}}, {64'hD000_0000_0000_0017}};   // This parameter does not match athena spec value (0xFC00_0000_0000_0017)
localparam bit [31:0]       CL_DTM_IDCODE_VALUE              = 32'h01000F43; // IDCODE for Ascalon IP 
endpackage
