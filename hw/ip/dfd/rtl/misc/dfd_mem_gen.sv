// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module dfd_mem_gen #(
		parameter int                     R      = 0,
		parameter int                     DW     = 1,
		parameter int                     RWP    = 0,
		parameter int                     ROP    = 0,
		parameter int                     WOP    = 0,
		parameter int                     WMG    = 0,
		parameter mem_gen_pkg::MemCell_e  CELL   = mem_gen_pkg::mem_cell_undefined,

		parameter bit SHUTDOWN_SUPPORT           = 0,
		parameter bit DPSLP_SUPPORT              = 0,
		parameter bit BYPASS_MODE_SUPPORT        = 0,
		parameter bit DFT_SUPPORT                = 0,
		parameter bit TSEL_CONFIGURABLE          = 0,

		parameter int                     AW     = $clog2(R),
		parameter int                     WMW    = DW / WMG,
		parameter int                     WP     = RWP + WOP,
		parameter int                     RP     = RWP + ROP,

		parameter int FAULTY_IO_WIDTH            = mem_gen_pkg::FAULTY_IO_WIDTHS[CELL][mem_gen_pkg::TECHNOLOGY],

		parameter int TSEL_WIDTH                 = mem_gen_pkg::TSEL_WIDTH
	) (
		input  logic             i_clk                            ,

		// RW ports
		input  logic [(RWP ? RWP : 1) - 1 : 0]           i_mem_chip_enb    ,
		input  logic [(RWP ? RWP : 1) - 1 : 0][AW -1:0]  i_mem_addr        ,

		// RO ports
		// spyglass disable_block W240
		input  logic [(ROP ? ROP : 1) - 1 : 0]           i_mem_rd_enb      ,
		input  logic [(ROP ? ROP : 1) - 1 : 0][AW -1:0]  i_mem_rd_addr     ,
		// spyglass enable_block W240

		// RW and WO ports
		input  logic [(WP           ) - 1 : 0]           i_mem_wr_enb      ,
		// spyglass disable_block W240
		input  logic [(WP           ) - 1 : 0][WMW-1:0]  i_mem_wr_mask_enb ,
		input  logic [(WP           ) - 1 : 0][DW -1:0]  i_mem_wr_data     ,

		// WO ports
		input  logic [(WOP ? WOP : 1) - 1 : 0][AW -1:0]  i_mem_wr_addr     ,
		// spyglass enable_block W240

		output logic [(RP           ) - 1 : 0][DW -1:0]  o_mem_rd_data     ,

		// spyglass disable_block W240
		input  logic                                     i_reg_mem_shut_down_mode   , // active high
		input  logic                                     i_reg_mem_deep_sleep_mode  , // active high
		input  logic                                     i_reg_mem_diode_bypass_mode, // active high
		input  logic                                     i_mem_dft_bypass_enable, // active high
		input  logic                                     i_mem_scan_enable, // active high
		input  logic                                     i_mem_scan_in_left,
		input  logic                                     i_mem_scan_in_right,
		input  logic [TSEL_WIDTH-1:0]                    i_mem_tsel_settings,
		// spyglass enable_block W240
		output logic                                     o_mem_pudelay_shut_down    ,
		output logic                                     o_mem_pudelay_deep_sleep   ,
		output logic                                     o_mem_scan_out_left        ,
		output logic                                     o_mem_scan_out_right       ,
		// spyglass disable_block W240
		input  logic [mem_gen_pkg::FAULTY_IO_WIDTHS[CELL][mem_gen_pkg::TECHNOLOGY]-1:0]
		i_reg_mem_faulty_io        ,
		input  logic                                     i_reg_mem_column_repair
		// spyglass enable_block W240
	);

	import mem_gen_pkg::TECHNOLOGY;

	logic [WP - 1 : 0][DW - 1:0] mem_wr_bit_enb_expanded;
	for (genvar p = 0; p < WP; p++) begin
		always_comb begin
			if (WMW == 1) begin
				mem_wr_bit_enb_expanded[p] = '0;
			end else begin
				mem_wr_bit_enb_expanded[p] = '1;
				for (int b = 0; b < WMW; b++) begin
					mem_wr_bit_enb_expanded[p][b * WMG +: WMG] = {WMG{i_mem_wr_mask_enb[p][b]}};
				end
			end
		end
	end

	if (TECHNOLOGY != mem_gen_pkg::TSMC7) begin
		if (SHUTDOWN_SUPPORT   ) $error("shutdown unsupported in %s", TECHNOLOGY.name());
		// if (DPSLP_SUPPORT      ) $error("dpslp unsupported in %s", TECHNOLOGY.name());
		if (BYPASS_MODE_SUPPORT) $error("bypass mode unsupported in %s", TECHNOLOGY.name());
	end

	case ({TECHNOLOGY, CELL})

		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_128x128_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("1prf_128x128_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 128) $error("1prf_128x128_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 1) $error("1prf_128x128_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_128x128_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_128x128_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_128x128_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_128x152_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("1prf_128x152_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 152) $error("1prf_128x152_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 152, DW);

			if (RWP != 1) $error("1prf_128x152_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_128x152_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_128x152_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_128x152_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_128x256_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("1prf_128x256_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 256) $error("1prf_128x256_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 256, DW);

			if (RWP != 1) $error("1prf_128x256_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_128x256_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_128x256_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_128x256_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_128x30_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("1prf_128x30_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 30) $error("1prf_128x30_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 30, DW);

			if (RWP != 1) $error("1prf_128x30_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_128x30_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_128x30_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_128x30_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_128x56_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("1prf_128x56_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 56) $error("1prf_128x56_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("1prf_128x56_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_128x56_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_128x56_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_128x56_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_128x60_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("1prf_128x60_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 60) $error("1prf_128x60_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 60, DW);

			if (RWP != 1) $error("1prf_128x60_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_128x60_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_128x60_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_128x60_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_128x78_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("1prf_128x78_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 78) $error("1prf_128x78_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("1prf_128x78_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_128x78_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_128x78_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_128x78_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x128_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x128_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 128) $error("1prf_256x128_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 1) $error("1prf_256x128_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x128_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x128_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x128_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x132_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x132_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 132) $error("1prf_256x132_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 132, DW);

			if (RWP != 1) $error("1prf_256x132_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x132_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x132_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x132_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x30_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x30_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 30) $error("1prf_256x30_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 30, DW);

			if (RWP != 1) $error("1prf_256x30_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x30_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x30_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x30_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x32_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x32_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 32) $error("1prf_256x32_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 32, DW);

			if (RWP != 1) $error("1prf_256x32_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x32_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x32_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x32_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x32_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x32_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 32) $error("1prf_256x32_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 32, DW);

			if (RWP != 1) $error("1prf_256x32_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x32_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x32_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x32_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x48_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x48_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 48) $error("1prf_256x48_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 48, DW);

			if (RWP != 1) $error("1prf_256x48_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x48_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x48_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x48_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x50_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x50_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 50) $error("1prf_256x50_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("1prf_256x50_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x50_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x50_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x50_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x56_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x56_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 56) $error("1prf_256x56_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("1prf_256x56_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x56_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x56_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x56_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x56_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x56_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 56) $error("1prf_256x56_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("1prf_256x56_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x56_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x56_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x56_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x60_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x60_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 60) $error("1prf_256x60_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 60, DW);

			if (RWP != 1) $error("1prf_256x60_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x60_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x60_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x60_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x72_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x72_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 72) $error("1prf_256x72_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("1prf_256x72_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x72_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x72_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x72_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x78_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x78_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 78) $error("1prf_256x78_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("1prf_256x78_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x78_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x78_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x78_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x78_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x78_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 78) $error("1prf_256x78_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("1prf_256x78_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x78_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x78_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x78_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x80_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x80_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 80) $error("1prf_256x80_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 80, DW);

			if (RWP != 1) $error("1prf_256x80_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x80_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x80_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x80_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x84_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x84_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 84) $error("1prf_256x84_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 84, DW);

			if (RWP != 1) $error("1prf_256x84_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x84_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x84_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x84_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x88_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x88_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 88) $error("1prf_256x88_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 88, DW);

			if (RWP != 1) $error("1prf_256x88_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x88_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x88_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x88_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_256x96_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("1prf_256x96_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("1prf_256x96_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("1prf_256x96_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_256x96_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_256x96_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_256x96_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_512x30_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("1prf_512x30_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 30) $error("1prf_512x30_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 30, DW);

			if (RWP != 1) $error("1prf_512x30_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_512x30_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_512x30_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_512x30_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_512x60_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("1prf_512x60_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 60) $error("1prf_512x60_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 60, DW);

			if (RWP != 1) $error("1prf_512x60_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_512x60_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_512x60_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_512x60_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_64x256_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("1prf_64x256_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 256) $error("1prf_64x256_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 256, DW);

			if (RWP != 1) $error("1prf_64x256_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_64x256_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_64x256_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_64x256_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_64x30_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("1prf_64x30_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 30) $error("1prf_64x30_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 30, DW);

			if (RWP != 1) $error("1prf_64x30_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_64x30_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_64x30_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_64x30_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_64x50_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("1prf_64x50_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 50) $error("1prf_64x50_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("1prf_64x50_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_64x50_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_64x50_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_64x50_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_64x56_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("1prf_64x56_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 56) $error("1prf_64x56_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("1prf_64x56_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_64x56_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_64x56_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_64x56_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_64x60_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("1prf_64x60_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 60) $error("1prf_64x60_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 60, DW);

			if (RWP != 1) $error("1prf_64x60_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_64x60_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_64x60_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_64x60_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_64x78_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("1prf_64x78_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 78) $error("1prf_64x78_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("1prf_64x78_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_64x78_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_64x78_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_64x78_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_1prf_64x96_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("1prf_64x96_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 96) $error("1prf_64x96_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("1prf_64x96_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("1prf_64x96_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("1prf_64x96_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_1prf_64x96_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_2prf_256x64_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("2prf_256x64_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 64) $error("2prf_256x64_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 0) $error("2prf_256x64_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("2prf_256x64_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("2prf_256x64_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_2prf_256x64_ulvt mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_2prf_256x96_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("2prf_256x96_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("2prf_256x96_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 0) $error("2prf_256x96_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("2prf_256x96_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("2prf_256x96_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_2prf_256x96_ulvt mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_2prf_512x128_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("2prf_512x128_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 128) $error("2prf_512x128_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 0) $error("2prf_512x128_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("2prf_512x128_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("2prf_512x128_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_2prf_512x128_ulvt mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_2prf_512x48_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("2prf_512x48_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 48) $error("2prf_512x48_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 48, DW);

			if (RWP != 0) $error("2prf_512x48_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("2prf_512x48_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("2prf_512x48_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_2prf_512x48_ulvt mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_2prf_512x72_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("2prf_512x72_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 72) $error("2prf_512x72_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 0) $error("2prf_512x72_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("2prf_512x72_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("2prf_512x72_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_2prf_512x72_ulvt mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_2prf_512x96_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("2prf_512x96_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 96) $error("2prf_512x96_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 0) $error("2prf_512x96_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("2prf_512x96_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("2prf_512x96_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_2prf_512x96_ulvt mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_hssp_256x96_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("hssp_256x96_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("hssp_256x96_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("hssp_256x96_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("hssp_256x96_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("hssp_256x96_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_hssp_256x96_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_HSSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_hssp_512x56_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("hssp_512x56_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 56) $error("hssp_512x56_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("hssp_512x56_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("hssp_512x56_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("hssp_512x56_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_hssp_512x56_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_HSSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_hssp_512x78_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("hssp_512x78_lvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 78) $error("hssp_512x78_lvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("hssp_512x78_lvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("hssp_512x78_lvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("hssp_512x78_lvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_hssp_512x78_lvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_HSSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spmb_2048x134_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("spmb_2048x134_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 134) $error("spmb_2048x134_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 134, DW);

			if (RWP != 1) $error("spmb_2048x134_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spmb_2048x134_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spmb_2048x134_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spmb_2048x134_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPMB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spmb_2048x144_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("spmb_2048x144_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 144) $error("spmb_2048x144_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 144, DW);

			if (RWP != 1) $error("spmb_2048x144_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spmb_2048x144_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spmb_2048x144_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spmb_2048x144_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPMB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spmb_8192x36_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 8192) $error("spmb_8192x36_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 8192, R);

			if (DW != 36) $error("spmb_8192x36_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 36, DW);

			if (RWP != 1) $error("spmb_8192x36_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spmb_8192x36_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spmb_8192x36_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spmb_8192x36_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPMB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_1024x30_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("spsb_1024x30_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 30) $error("spsb_1024x30_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 30, DW);

			if (RWP != 1) $error("spsb_1024x30_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_1024x30_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_1024x30_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_1024x30_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_1024x56_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("spsb_1024x56_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 56) $error("spsb_1024x56_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("spsb_1024x56_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_1024x56_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_1024x56_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_1024x56_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_1024x78_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("spsb_1024x78_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 78) $error("spsb_1024x78_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("spsb_1024x78_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_1024x78_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_1024x78_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_1024x78_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_256x192_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("spsb_256x192_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 192) $error("spsb_256x192_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 192, DW);

			if (RWP != 1) $error("spsb_256x192_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_256x192_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_256x192_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_256x192_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_256x266_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("spsb_256x266_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 266) $error("spsb_256x266_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 266, DW);

			if (RWP != 1) $error("spsb_256x266_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_256x266_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_256x266_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_256x266_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_32x150_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 32) $error("spsb_32x150_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 32, R);

			if (DW != 150) $error("spsb_32x150_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 150, DW);

			if (RWP != 1) $error("spsb_32x150_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_32x150_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_32x150_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_32x150_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_32x204_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 32) $error("spsb_32x204_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 32, R);

			if (DW != 204) $error("spsb_32x204_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 204, DW);

			if (RWP != 1) $error("spsb_32x204_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_32x204_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_32x204_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_32x204_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_512x192_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("spsb_512x192_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 192) $error("spsb_512x192_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 192, DW);

			if (RWP != 1) $error("spsb_512x192_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_512x192_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_512x192_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_512x192_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_512x268_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("spsb_512x268_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 268) $error("spsb_512x268_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 268, DW);

			if (RWP != 1) $error("spsb_512x268_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_512x268_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_512x268_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_512x268_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_spsb_512x288_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("spsb_512x288_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 288) $error("spsb_512x288_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 288, DW);

			if (RWP != 1) $error("spsb_512x288_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("spsb_512x288_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("spsb_512x288_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_spsb_512x288_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_SPSB_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhd1prf_64x90_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("uhd1prf_64x90_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 90) $error("uhd1prf_64x90_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 90, DW);

			if (RWP != 1) $error("uhd1prf_64x90_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("uhd1prf_64x90_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("uhd1prf_64x90_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_uhd1prf_64x90_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHD1PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhd2prf_256x80_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("uhd2prf_256x80_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 80) $error("uhd2prf_256x80_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 80, DW);

			if (RWP != 0) $error("uhd2prf_256x80_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("uhd2prf_256x80_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("uhd2prf_256x80_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_uhd2prf_256x80_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHD2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhd2prf_256x84_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("uhd2prf_256x84_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 84) $error("uhd2prf_256x84_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 84, DW);

			if (RWP != 0) $error("uhd2prf_256x84_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("uhd2prf_256x84_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("uhd2prf_256x84_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_uhd2prf_256x84_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHD2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhd2prf_256x88_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("uhd2prf_256x88_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 88) $error("uhd2prf_256x88_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 88, DW);

			if (RWP != 0) $error("uhd2prf_256x88_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("uhd2prf_256x88_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("uhd2prf_256x88_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_uhd2prf_256x88_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHD2PRF_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhdsp_1024x144_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("uhdsp_1024x144_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 144) $error("uhdsp_1024x144_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 144, DW);

			if (RWP != 1) $error("uhdsp_1024x144_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("uhdsp_1024x144_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("uhdsp_1024x144_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_uhdsp_1024x144_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHDSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhdsp_1024x72_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("uhdsp_1024x72_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 72) $error("uhdsp_1024x72_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("uhdsp_1024x72_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("uhdsp_1024x72_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("uhdsp_1024x72_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_uhdsp_1024x72_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHDSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhdsp_2048x72_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("uhdsp_2048x72_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 72) $error("uhdsp_2048x72_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("uhdsp_2048x72_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("uhdsp_2048x72_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("uhdsp_2048x72_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_uhdsp_2048x72_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHDSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhdsp_512x192_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("uhdsp_512x192_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 192) $error("uhdsp_512x192_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 192, DW);

			if (RWP != 1) $error("uhdsp_512x192_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("uhdsp_512x192_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("uhdsp_512x192_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_uhdsp_512x192_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHDSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhdsp_512x288_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("uhdsp_512x288_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 288) $error("uhdsp_512x288_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 288, DW);

			if (RWP != 1) $error("uhdsp_512x288_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("uhdsp_512x288_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("uhdsp_512x288_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_uhdsp_512x288_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHDSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::TSMC7, mem_gen_pkg::mem_uhdsp_512x96_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("uhdsp_512x96_ulvt specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 96) $error("uhdsp_512x96_ulvt specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("uhdsp_512x96_ulvt specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("uhdsp_512x96_ulvt specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("uhdsp_512x96_ulvt specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_uhdsp_512x96_ulvt mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_shut_down_mode    (SHUTDOWN_SUPPORT    ? i_reg_mem_shut_down_mode    : '0),
				.i_reg_mem_deep_sleep_mode   (DPSLP_SUPPORT       ? i_reg_mem_deep_sleep_mode   : '0),
				.i_mem_dft_bypass_enable     (DFT_SUPPORT         ? i_mem_dft_bypass_enable     : '0),
				.i_mem_scan_enable           (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left          (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right         (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.o_mem_pudelay_shut_down,
				.o_mem_pudelay_deep_sleep,
				.i_reg_mem_diode_bypass_mode (BYPASS_MODE_SUPPORT ? i_reg_mem_diode_bypass_mode : '0),
				.i_reg_mem_faulty_io,
				.i_reg_mem_column_repair,
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_TSMC7_SETTINGS_UHDSP_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 137) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 137, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 72) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_uhdsp_2048x72_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 72) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 4096) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 4096, R);

			if (DW != 30) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 30, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 78) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_128x78_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 78) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_128x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_rf1rw_hsr_lvt_128x88m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 88) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 88, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_128x88m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 50) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x50_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 50) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_256x50m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 78) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x78_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 78) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_256x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_rf1rw_hsr_lvt_512x44m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 44) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 44, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_512x44m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_emc_rf1rw_hsr_lvt_512x64m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 64) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_emc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_emc_rf1rw_hsr_lvt_512x64m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_hsr_lvt_3072x137m4b4c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 3072) $error("ln04lpp_s00_mc_ra1rw_hsr_lvt_3072x137m4b4c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 3072, R);

			if (DW != 137) $error("ln04lpp_s00_mc_ra1rw_hsr_lvt_3072x137m4b4c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 137, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_hsr_lvt_3072x137m4b4c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_hsr_lvt_3072x137m4b4c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_hsr_lvt_3072x137m4b4c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_hsr_lvt_3072x137m4b4c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 137) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 137, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_1024x137m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x128m4b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x128m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 128) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x128m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x128m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x128m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x128m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x128m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x129m4b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x129m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 129) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x129m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 129, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x129m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x129m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x129m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x129m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x136m4b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x136m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 136) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x136m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 136, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x136m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x136m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x136m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x136m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x65m4b4c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x65m4b4c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 65) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x65m4b4c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 65, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x65m4b4c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x65m4b4c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x65m4b4c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x65m4b4c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2048) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2048, R);

			if (DW != 72) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_2048x72m4b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 4096) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 4096, R);

			if (DW != 30) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 30, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_ra1rw_uhdrw_lvt_4096x30m8b2c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RA1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rd2rw_hsr_lvt_256x128m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x128m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 128) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x128m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x128m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x128m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x128m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rd2rw_hsr_lvt_256x128m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RD2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RD2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_2prf_256x96_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rd2rw_hsr_lvt_256x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RD2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 128) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RD2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_2prf_512x128_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 128) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rd2rw_hsr_lvt_512x128m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RD2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rd2rw_hsr_lvt_512x64m4b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x64m4b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x64m4b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x64m4b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x64m4b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_512x64m4b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rd2rw_hsr_lvt_512x64m4b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RD2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rd2rw_hsr_lvt_64x104m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_64x104m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 104) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_64x104m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 104, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_64x104m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_64x104m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rd2rw_hsr_lvt_64x104m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rd2rw_hsr_lvt_64x104m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RD2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_1024x52m4b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 1024) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_1024x52m4b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 1024, R);

			if (DW != 52) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_1024x52m4b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 52, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_1024x52m4b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_1024x52m4b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_1024x52m4b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_1024x52m4b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_128x128_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x128m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 152) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 152, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_128x152_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 152) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 152, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 152) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 152, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x152m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x64m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 76) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 76, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 76) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 76, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x76m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 78) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 78) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x78m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 88) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 88, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 88) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 88, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x88m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x92m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x92m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 92) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x92m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 92, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x92m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x92m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_128x92m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_128x92m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x104m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x104m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 104) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x104m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 104, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x104m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x104m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x104m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x104m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 132) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 132, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x132_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 132) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 132, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x132m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 48) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 48, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x48_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 48) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 48, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 48) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 48, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x48m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 50) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 50) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x50m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x56_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x56m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x64m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 72) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x72_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 72) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 72) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x72m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 76) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 76, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 76) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 76, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x76m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 78) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 78) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x78m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 80) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 80, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x80_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 80) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 80, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x80m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 84) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 84, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x84_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 84) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 84, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x84m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 88) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 88, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x88_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 88) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 88, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x88m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_256x96_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_256x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 44) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 44, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 44) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 44, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x44m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x56m4b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x56m4b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x56m4b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x56m4b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x56m4b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x56m4b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x56m4b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x64m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x72m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x72m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 72) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x72m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x72m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x72m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_512x72m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_512x72m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x146m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x146m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 146) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x146m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 146, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x146m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x146m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x146m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x146m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 50) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_64x50_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 50) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 50) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 50, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x50m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_64x56_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x56m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 78) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_64x78_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 78) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 78) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 78, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x78m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 90) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 90, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_uhd1prf_64x90_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 90) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 90, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 90) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 90, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x90m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x92m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x92m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 92) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x92m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 92, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x92m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x92m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x92m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x92m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_1prf_64x96_lvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_hsr_lvt_64x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 16) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 16, R);

			if (DW != 92) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 92, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 16) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 16, R);

			if (DW != 92) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 92, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_16x92m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x64m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x64m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x64m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 64, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x64m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x64m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x64m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x64m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_hssp_256x96_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_256x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x112m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x112m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 112) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x112m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 112, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x112m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x112m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x112m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x112m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x56m4b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x56m4b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 56) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x56m4b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 56, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x56m4b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x56m4b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x56m4b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x56m4b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x72m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x72m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 72) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x72m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 72, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x72m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x72m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x72m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x72m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_uhdsp_512x96_ulvt}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_512x96m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 124) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 124, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 124) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 124, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x124m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 130) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 130, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 130) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 130, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x130m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x146m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x146m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 146) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x146m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 146, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x146m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x146m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x146m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x146m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x150m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x150m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 150) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x150m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 150, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x150m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x150m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x150m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_lvt_64x150m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 98) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 98, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 98) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 98, DW);

			if (RWP != 1) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 1, RWP);

			if (ROP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 0, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf1rw_uhdrw_rvt_64x98m2b1c1r2 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.i_mem_wr_enb,
				.i_mem_wr_data,
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF1RW_UHDRW_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_112x148m1b2c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 112) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_112x148m1b2c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 112, R);

			if (DW != 148) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_112x148m1b2c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 148, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_112x148m1b2c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_112x148m1b2c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_112x148m1b2c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_112x148m1b2c1 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 104) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 104, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 128) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 128, R);

			if (DW != 104) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 104, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_128x104m1b2c1r2 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_256x96m1b8c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 256) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_256x96m1b8c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 256, R);

			if (DW != 96) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_256x96m1b8c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 96, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_256x96m1b8c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_256x96m1b8c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_256x96m1b8c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_256x96m1b8c1r2 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_48x160m1b2c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 48) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_48x160m1b2c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 48, R);

			if (DW != 160) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_48x160m1b2c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 160, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_48x160m1b2c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_48x160m1b2c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_48x160m1b2c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_48x160m1b2c1 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_512x128m1b8c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 512) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_512x128m1b8c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 512, R);

			if (DW != 128) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_512x128m1b8c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 128, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_512x128m1b8c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_512x128m1b8c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_512x128m1b8c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_512x128m1b8c1r2 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_64x104m1b2c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x104m1b2c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 104) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x104m1b2c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 104, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x104m1b2c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x104m1b2c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x104m1b2c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_64x104m1b2c1 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 136) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 136, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1r2}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 64) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1r2 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 64, R);

			if (DW != 136) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1r2 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 136, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1r2 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1r2 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 1) $error("ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1r2 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 1, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_rf2rw_hsr_lvt_64x136m1b2c1r2 mem (

				.i_mem_rd_clk(i_clk),
				.i_mem_wr_clk(i_clk),
				.i_mem_wr_bit_enb(mem_wr_bit_enb_expanded),
				.i_mem_wr_enb,
				.i_mem_wr_addr,
				.i_mem_wr_data,
				.i_mem_rd_enb,
				.i_mem_rd_addr,
				.o_mem_rd_data,
				.i_reg_mem_retention_enable (SHUTDOWN_SUPPORT    ? i_reg_mem_deep_sleep_mode    : '0),
				.i_mem_dft_bypass_enable    (DFT_SUPPORT         ? i_mem_dft_bypass_enable      : '0),
				.i_mem_scan_enable          (DFT_SUPPORT         ? i_mem_scan_enable           : '0),
				.i_mem_scan_in_left         (DFT_SUPPORT         ? i_mem_scan_in_left          : '0),
				.i_mem_scan_in_right        (DFT_SUPPORT         ? i_mem_scan_in_right         : '0),
				.o_mem_scan_out_left,
				.o_mem_scan_out_right,
				.i_reg_mem_col_repair_addr1 ('0), // FIXME
				.i_reg_mem_col_repair_en1   ('0), // FIXME
				.i_reg_mem_col_repair_addr2 ('0), // FIXME
				.i_reg_mem_col_repair_en2   ('0), // FIXME
				.i_reg_mem_row_repair_addr1 ('0), // FIXME
				.i_reg_mem_row_repair_en1   ('0), // FIXME
				.i_reg_mem_row_repair_addr2 ('0), // FIXME
				.i_reg_mem_row_repair_en2   ('0), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_RF2RW_HSR_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_vromp_hd_lvt_16384x32m16b8c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 16384) $error("ln04lpp_s00_mc_vromp_hd_lvt_16384x32m16b8c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 16384, R);

			if (DW != 32) $error("ln04lpp_s00_mc_vromp_hd_lvt_16384x32m16b8c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 32, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_vromp_hd_lvt_16384x32m16b8c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_vromp_hd_lvt_16384x32m16b8c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_vromp_hd_lvt_16384x32m16b8c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_vromp_hd_lvt_16384x32m16b8c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.o_mem_rd_data,
				.i_reg_mem_power_down_enable ('0), // FIXME
				.o_mem_power_ready_enable    (  ), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_VROMP_HD_DEFAULT),
				.*
			);
		end
		{mem_gen_pkg::SF4, mem_gen_pkg::mem_ln04lpp_s00_mc_vromp_hd_lvt_2240x32m16b2c1}: begin : mem

		`ifndef FML_PARAM_CHECKS_DISABLE
			if (R != 2240) $error("ln04lpp_s00_mc_vromp_hd_lvt_2240x32m16b2c1 specified but does not have correct number of rows. Expected %0d, Actual %0d. Check your ADDR_WIDTH parameter", 2240, R);

			if (DW != 32) $error("ln04lpp_s00_mc_vromp_hd_lvt_2240x32m16b2c1 specified but does not have correct number of cols. Expected %0d, Actual %0d. Check your DATA_WIDTH parameter", 32, DW);

			if (RWP != 0) $error("ln04lpp_s00_mc_vromp_hd_lvt_2240x32m16b2c1 specified but does not have correct number of RW ports. Expected %0d, Actual %0d. Check your RW_PORTS parameter", 0, RWP);

			if (ROP != 1) $error("ln04lpp_s00_mc_vromp_hd_lvt_2240x32m16b2c1 specified but does not have correct number of RO ports. Expected %0d, Actual %0d. Check your RO_PORTS parameter", 1, ROP);

			if (WOP != 0) $error("ln04lpp_s00_mc_vromp_hd_lvt_2240x32m16b2c1 specified but does not have correct number of WO ports. Expected %0d, Actual %0d. Check your WO_PORTS parameter", 0, WOP);
		`endif

			tt_mem_wrapper_ln04lpp_s00_mc_vromp_hd_lvt_2240x32m16b2c1 mem (

				.i_mem_clk(i_clk),
				.i_mem_chip_enb,
				.i_mem_addr,
				.o_mem_rd_data,
				.i_reg_mem_power_down_enable ('0), // FIXME
				.o_mem_power_ready_enable    (  ), // FIXME
				.i_mem_tsel_settings         (TSEL_CONFIGURABLE   ? i_mem_tsel_settings : mem_gen_pkg::TSEL_SF4_SETTINGS_VROMP_HD_DEFAULT),
				.*
			);
		end
		default: begin
			$error("Unrecognized combination of technology (%s) and cell (%s)", TECHNOLOGY.name(), CELL.name());
		end
	endcase
endmodule
