// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// System Management Controller Miscellaneous Package
//
//-----------------------------------------------------------------------------

package smc_misc_pkg;

	function automatic int unsigned max(int unsigned a, int unsigned b);
		return a > b ? a : b;
	endfunction

	localparam int unsigned NumRegMaps   = 5;

	// // Get the maximum address width of the registers needed for the misc unit
	// localparam int unsigned RegAddrWidth = 32;

	// typedef logic [RegAddrWidth-1:0]                                        reg_addr_t;
	// typedef logic [scratch_reg_pkg::SCRATCH_REG_DATA_WIDTH-1:0]             reg_data_t;
	// typedef logic [scratch_reg_pkg::SCRATCH_REG_DATA_WIDTH/8-1:0]           reg_strb_t;

	// `AXI_LITE_TYPEDEF_ALL(reg_axi_lite, reg_addr_t, reg_data_t, reg_strb_t)

	typedef enum logic [$clog2(NumRegMaps)-1:0] {
		SCRATCH_COLD        = 3'b000,
		SCRATCH_COLD_WARM   = 3'b001,
		CHIP_CONFIG         = 3'b010,
		NDM_RESET           = 3'b011,
		ERR_SLV             = 3'b100
	} select_t;

endpackage
