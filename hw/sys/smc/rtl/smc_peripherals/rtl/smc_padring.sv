// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//----------------------------------------------------------
// SMC Padring
//
//----------------------------------------------------------


module smc_padring #(
	parameter int unsigned		MAX_TRANS			= 1,
	parameter bit [gpio_pkg::ADDR_WIDTH-1:0]	ADDRESS_MAP_SIZE_PER_GPIO = 32'h00000010,  // Size per GPIO instance (32 bytes)
	parameter bit [gpio_pkg::ADDR_WIDTH-1:0] GPIO_INTF_BASE_ADDR = 32'h00000000,      // Base address for all GPIO intfs
	parameter bit [gpio_pkg::ADDR_WIDTH-1:0] GPIO_CTRL_BASE_ADDR = GPIO_INTF_BASE_ADDR + (smc_pkg::NUM_GPIO_WRAPS * ADDRESS_MAP_SIZE_PER_GPIO) // Base address for all GPIO shims

)(
	input  logic								clk_i,
	input  logic								rst_primary_ni,
	input  logic								rst_cold_stable_smc_clk_ni,

	// Test Interface
	input  logic								test_en_i,
	input  logic								scan_rst_ni,

	// AXI-Lite Register Interface
	input  gpio_pkg::gpio_axil_req_t			axil_req_i,
	output gpio_pkg::gpio_axil_resp_t			axil_resp_o,

	// SPI
	input  logic								spi_enable_i,
	input  logic								spi_clk_i,					// Serial bir-rate clock
	input  logic [7:0]							spi_txd_i,					// Transmit Data Signal
	input  logic								spi_cs_n_i,					// Chip Select Signal
	input  logic								spi_cs_oe_n_i,				// chip select output enable
	input  logic								spi_cs_ie_n_i,
	input  logic								spi_clk_ie_n_i,
	input  logic								spi_clk_oe_n_i,
	input  logic								spi_dqs_ie_n_i,
	input  logic								spi_dqs_oe_n_i,
	input  logic [7:0]							spi_dq_ie_n_i,
	input  logic [7:0]							spi_dq_oe_n_i,
	output logic [7:0]							spi_rxd_o,					// Receive Data Signal
	output logic								spi_rxds_o,					// Read Data strobe in DDR mode of operation
	input  logic								spi_mem_rebar_oepad_i,
	input  logic								spi_mem_rebar_opad_i,
	input  logic								spi_mem_rebar_iepad_i,
	output logic								spi_mem_rebar_ipad_o,

	// UART
	input  logic [smc_config_pkg::NUM_UART-1:0]		uart_enable_i,
	output logic [smc_config_pkg::NUM_UART-1:0]		uart_rx_o,
	input  logic [smc_config_pkg::NUM_UART-1:0]		uart_tx_i,
	input  logic [smc_config_pkg::NUM_UART-1:0]		uart_rts_n_i,
	output logic [smc_config_pkg::NUM_UART-1:0]		uart_cts_n_o,

	// System Timer OCTS
	input  logic								chiplet_is_primary_i,
	input  logic								timer_sync_load_i,
	input  logic								timer_cnt_credit_i,
	output logic								timer_sync_load_o,
	output logic								timer_cnt_credit_o,
	input  logic								timer_gpio_enable_i,

	// Boot Stall
	output logic								boot_stall_o,

	// I3C
	input  logic [smc_config_pkg::NUM_I3C-1:0]			i3c_enable_i,
	output logic [smc_config_pkg::NUM_I3C-1:0]			i3c_scl_o,
	output logic [smc_config_pkg::NUM_I3C-1:0]			i3c_sda_o,
	input  logic [smc_config_pkg::NUM_I3C-1:0]			i3c_scl_i,
	input  logic [smc_config_pkg::NUM_I3C-1:0]			i3c_scl_oen_i,
	input  logic [smc_config_pkg::NUM_I3C-1:0]			i3c_sda_i,
	input  logic [smc_config_pkg::NUM_I3C-1:0]			i3c_sda_oen_i,				// Output enable for SDA IO pad (active low)
	input  logic [smc_config_pkg::NUM_I3C-1:0]			i3c_sda_pp_i,				// Push-pull - output enable for SDA IO pad

	// I2C
	input  logic [smc_config_pkg::NUM_I2C-1:0]			i2c_enable_i,
	input  logic [smc_config_pkg::NUM_I2C-1:0]			i2c_master_enable_i,
	output logic [smc_config_pkg::NUM_I2C-1:0]			i2c_scl_o,
	output logic [smc_config_pkg::NUM_I2C-1:0]			i2c_sda_o,
	output logic [smc_config_pkg::NUM_I2C-1:0]			i2c_smbus_n_o,
	output logic [smc_config_pkg::NUM_I2C-1:0]			i2c_smbus_alert_n_o,
	input  logic [smc_config_pkg::NUM_I2C-1:0]			i2c_scl_oen_i,
	input  logic [smc_config_pkg::NUM_I2C-1:0]			i2c_sda_oen_i,
	input  logic [smc_config_pkg::NUM_I2C-1:0]			i2c_smbus_n_i,
	input  logic [smc_config_pkg::NUM_I2C-1:0]			i2c_smbus_alert_oe_i,

	// AVS
	input  logic								avs_enable_i,
	input  logic								avs_clock_i,
	input  logic								avs_mdata_i,
	output logic								avs_sdata_o,

	// Reset Unit signals
	input  logic								rst_cool_ni,
	output logic								isolate_req_pin_o,

	// GPIO Control Interface (to external padring for ctrl/refclk/ext access)
	output gpio_pkg::gpio_axil_req_t            axil_req_gpio_ctrl_o,
	input  gpio_pkg::gpio_axil_resp_t           axil_resp_gpio_ctrl_i,

	// GPIO Data Signals (to external GPIO macros via gpio_shim instances)
	output	logic [smc_pkg::NUM_GPIO_WRAPS-1:0]       lsio_interface_select_o,
	output	logic [smc_pkg::NUM_GPIO_WRAPS-1:0]       core2pad_o,
	output	logic [smc_pkg::NUM_GPIO_WRAPS-1:0]       core2pad_en_o,
	input	logic [smc_pkg::NUM_GPIO_WRAPS-1:0]       pad2core_i,
	output	logic [smc_pkg::NUM_GPIO_WRAPS-1:0]       pad2core_en_o,

	// GPIO Interrupts - only bonded GPIOs can be used for interrupts
	output logic [smc_pkg::NUM_GPIO_WRAPS-1:0]		gpio_interrupt_o

);

	////////////////////
	// AXI-Lite Demux //
	////////////////////

	// Primary demux: gpio_intf vs gpio_ctrl/ext ranges
	gpio_pkg::gpio_axil_req_t  axil_req_gpio_intf;
	gpio_pkg::gpio_axil_resp_t axil_resp_gpio_intf;
	gpio_pkg::gpio_axil_req_t  axil_req_gpio_ctrl;
	gpio_pkg::gpio_axil_resp_t axil_resp_gpio_ctrl;

	logic primary_aw_select;  // 0=gpio_intf, 1=gpio_ctrl/ext
	logic primary_ar_select;  // 0=gpio_intf, 1=gpio_ctrl/ext

	always_comb begin
		// Primary decode: gpio_intf vs gpio_ctrl/ext ranges
		primary_aw_select = (axil_req_i.aw.addr >= GPIO_CTRL_BASE_ADDR);
		primary_ar_select = (axil_req_i.ar.addr >= GPIO_CTRL_BASE_ADDR);
	end

	axi_lite_demux #(
		.aw_chan_t			(gpio_pkg::gpio_axil_aw_chan_t),
		.w_chan_t			(gpio_pkg::gpio_axil_w_chan_t),
		.b_chan_t			(gpio_pkg::gpio_axil_b_chan_t),
		.ar_chan_t			(gpio_pkg::gpio_axil_ar_chan_t),
		.r_chan_t			(gpio_pkg::gpio_axil_r_chan_t),
		.axi_req_t			(gpio_pkg::gpio_axil_req_t),
		.axi_resp_t			(gpio_pkg::gpio_axil_resp_t),
		.NoMstPorts			(2),  // gpio_intf and gpio_ctrl/ext
		.MaxTrans			(MAX_TRANS),
		.FallThrough		(1'b0),
		.SpillAw			(1'b1),
		.SpillW				(1'b0),
		.SpillB				(1'b0),
		.SpillAr			(1'b1),
		.SpillR				(1'b0)
	) primary_axi_lite_demux (
		.clk_i				(clk_i),
		.rst_ni				(rst_primary_ni),
		.test_i				(test_en_i),
		.slv_req_i			(axil_req_i),
		.slv_resp_o			(axil_resp_o),
		.slv_aw_select_i	(primary_aw_select),
		.slv_ar_select_i	(primary_ar_select),
		.mst_reqs_o			({axil_req_gpio_ctrl_o, axil_req_gpio_intf}),
		.mst_resps_i		({axil_resp_gpio_ctrl_i, axil_resp_gpio_intf})
	);

	// Secondary demux for gpio_intf only
	gpio_pkg::gpio_axil_req_t  [smc_pkg::NUM_GPIO_WRAPS-1:0] axil_reqs_to_intf;
	gpio_pkg::gpio_axil_resp_t [smc_pkg::NUM_GPIO_WRAPS-1:0] axil_resps_from_intf;

	logic [$clog2(smc_pkg::NUM_GPIO_WRAPS)-1:0] gpio_intf_aw_select;
	logic [$clog2(smc_pkg::NUM_GPIO_WRAPS)-1:0] gpio_intf_ar_select;

	always_comb begin
		// Secondary decode for gpio_intf[71] - each is 0x10 bytes
		gpio_intf_aw_select = (axil_req_gpio_intf.aw.addr - GPIO_INTF_BASE_ADDR) >> 4;
		gpio_intf_ar_select = (axil_req_gpio_intf.ar.addr - GPIO_INTF_BASE_ADDR) >> 4;
	end

	axi_lite_demux #(
		.aw_chan_t			(gpio_pkg::gpio_axil_aw_chan_t),
		.w_chan_t			(gpio_pkg::gpio_axil_w_chan_t),
		.b_chan_t			(gpio_pkg::gpio_axil_b_chan_t),
		.ar_chan_t			(gpio_pkg::gpio_axil_ar_chan_t),
		.r_chan_t			(gpio_pkg::gpio_axil_r_chan_t),
		.axi_req_t			(gpio_pkg::gpio_axil_req_t),
		.axi_resp_t			(gpio_pkg::gpio_axil_resp_t),
		.NoMstPorts			(smc_pkg::NUM_GPIO_WRAPS),  // gpio_intf[71]
		.MaxTrans			(MAX_TRANS),
		.FallThrough		(1'b0),
		.SpillAw			(1'b1),
		.SpillW				(1'b0),
		.SpillB				(1'b0),
		.SpillAr			(1'b1),
		.SpillR				(1'b0)
	) secondary_axi_lite_demux (
		.clk_i				(clk_i),
		.rst_ni				(rst_primary_ni),
		.test_i				(test_en_i),
		.slv_req_i			(axil_req_gpio_intf),
		.slv_resp_o			(axil_resp_gpio_intf),
		.slv_aw_select_i	(gpio_intf_aw_select),
		.slv_ar_select_i	(gpio_intf_ar_select),
		.mst_reqs_o			(axil_reqs_to_intf),
		.mst_resps_i		(axil_resps_from_intf)
	);

	////////////////////
	// LSIO Interface //
	////////////////////

	logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_core2pad_en_n;
	logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_core2pad_data;
	logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_pad2core_en_n;
	logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_pad2core_data;

	always_comb begin
		// Disable all LSIO interface by default
		lsio_interface_select_o = '0;
		lsio_core2pad_en_n 		= {smc_pkg::NUM_GPIO_WRAPS{smc_padring_pkg::DISABLED}};
		lsio_core2pad_data 		= '0;
		lsio_pad2core_en_n 		= {smc_pkg::NUM_GPIO_WRAPS{smc_padring_pkg::DISABLED}};

		// SPI
		for (int s = 0; s < 8; s = s + 1) begin : gen_spi_connections
			lsio_interface_select_o[s] 	= spi_enable_i;
			lsio_core2pad_en_n[s]    	= spi_dq_oe_n_i[s];
			lsio_core2pad_data[s]    	= spi_txd_i[s];
			lsio_pad2core_en_n[s]    	= spi_dq_ie_n_i[s];
			spi_rxd_o[s]             	= lsio_pad2core_data[s];
		end

		lsio_interface_select_o[8]  = spi_enable_i;
		lsio_core2pad_en_n[8]      	= spi_cs_oe_n_i;
		lsio_core2pad_data[8]      	= spi_cs_n_i;
		lsio_pad2core_en_n[8]      	= spi_cs_ie_n_i;

		lsio_interface_select_o[9]  = spi_enable_i;
		lsio_core2pad_en_n[9]      	= spi_clk_oe_n_i;
		lsio_core2pad_data[9]      	= spi_clk_i;
		lsio_pad2core_en_n[9]      	= spi_clk_ie_n_i;

		lsio_interface_select_o[10] = spi_enable_i;
		lsio_core2pad_en_n[10]     	= spi_dqs_oe_n_i;
		lsio_core2pad_data[10]     	= 1'b0;
		lsio_pad2core_en_n[10]     	= spi_dqs_ie_n_i;
		spi_rxds_o                	= lsio_pad2core_data[10];

		// UART
		for (integer u = 0; u < smc_config_pkg::NUM_UART; u = u + 1) begin : gen_uart_connections
			lsio_interface_select_o[11+4*u] = uart_enable_i[u];
			lsio_core2pad_en_n[11+4*u]      = smc_padring_pkg::DISABLED;
			lsio_core2pad_data[11+4*u]      = 1'b0;
			lsio_pad2core_en_n[11+4*u]      = smc_padring_pkg::ENABLED;
			uart_rx_o[u]                    = lsio_pad2core_data[11+4*u];

			lsio_interface_select_o[12+4*u] = uart_enable_i[u];
			lsio_core2pad_en_n[12+4*u]      = smc_padring_pkg::ENABLED;
			lsio_core2pad_data[12+4*u]      = uart_tx_i[u];
			lsio_pad2core_en_n[12+4*u]      = smc_padring_pkg::DISABLED;

			lsio_interface_select_o[13+4*u] = uart_enable_i[u];
			lsio_core2pad_en_n[13+4*u]      = smc_padring_pkg::ENABLED;
			lsio_core2pad_data[13+4*u]      = uart_rts_n_i[u];
			lsio_pad2core_en_n[13+4*u]      = smc_padring_pkg::DISABLED;

			lsio_interface_select_o[14+4*u] = uart_enable_i[u];
			lsio_core2pad_en_n[14+4*u]      = smc_padring_pkg::DISABLED;
			lsio_core2pad_data[14+4*u]      = 1'b0;
			lsio_pad2core_en_n[14+4*u]      = smc_padring_pkg::ENABLED;
			uart_cts_n_o[u]                 = lsio_pad2core_data[14+4*u];
		end

		lsio_interface_select_o[27] = i3c_enable_i[0];
		lsio_core2pad_en_n[27]      = i3c_scl_oen_i[0];
		lsio_core2pad_data[27]      = i3c_scl_i[0];
		lsio_pad2core_en_n[27]      = smc_padring_pkg::ENABLED;
		i3c_scl_o[0]                = lsio_pad2core_data[27];

		lsio_interface_select_o[28] = i3c_enable_i[0];
		lsio_core2pad_en_n[28]      = ~(~i3c_sda_oen_i[0] | i3c_sda_pp_i[0]);
		lsio_core2pad_data[28]      = i3c_sda_i[0];
		lsio_pad2core_en_n[28]      = smc_padring_pkg::ENABLED;
		i3c_sda_o[0]                = lsio_pad2core_data[28];

		// I3C 2 - 5 (I3C[1] is fully unbonded at GPIO[66,67])
		for (integer i = 0; i < (smc_config_pkg::NUM_I3C - 2); i = i + 1) begin : gen_i3c_connections
			lsio_interface_select_o[29+(2*i)] = i3c_enable_i[2+i];
			lsio_core2pad_en_n[29+(2*i)]      = i3c_scl_oen_i[2+i];
			lsio_core2pad_data[29+(2*i)]      = i3c_scl_i[2+i];
			lsio_pad2core_en_n[29+(2*i)]      = smc_padring_pkg::ENABLED;
			i3c_scl_o[2+i]                    = lsio_pad2core_data[29+(2*i)];

			lsio_interface_select_o[30+(2*i)] = i3c_enable_i[2+i];
			lsio_core2pad_en_n[30+(2*i)]      = ~(~i3c_sda_oen_i[2+i] | i3c_sda_pp_i[2+i]);
			lsio_core2pad_data[30+(2*i)]      = i3c_sda_i[2+i];
			lsio_pad2core_en_n[30+(2*i)]      = smc_padring_pkg::ENABLED;
			i3c_sda_o[2+i]                    = lsio_pad2core_data[30+(2*i)];
		end

		// I3C[1] fully unbonded (both SCL and SDA)

		lsio_interface_select_o[66] = i3c_enable_i[1];
		lsio_core2pad_en_n[66]      = i3c_scl_oen_i[1];
		lsio_core2pad_data[66]      = i3c_scl_i[1];
		lsio_pad2core_en_n[66]      = smc_padring_pkg::ENABLED;
		i3c_scl_o[1]                = lsio_pad2core_data[66];

		lsio_interface_select_o[67] = i3c_enable_i[1];
		lsio_core2pad_en_n[67]      = ~(~i3c_sda_oen_i[1] | i3c_sda_pp_i[1]);
		lsio_core2pad_data[67]      = i3c_sda_i[1];
		lsio_pad2core_en_n[67]      = smc_padring_pkg::ENABLED;
		i3c_sda_o[1]                = lsio_pad2core_data[67];

		// I2C
		for (integer i = 0; i < smc_config_pkg::NUM_I2C; i = i + 1) begin : gen_i2c_connections
			// SCL
			lsio_interface_select_o[37+4*i] = i2c_enable_i[i];
			if (i2c_master_enable_i[i]) begin
				lsio_core2pad_en_n[37+4*i]  = i2c_scl_oen_i[i];
				lsio_core2pad_data[37+4*i]  = 1'b0;		// drive 0 because board will have pullups
				lsio_pad2core_en_n[37+4*i]  = ~i2c_scl_oen_i[i];
				i2c_scl_o[i]                = lsio_pad2core_data[37+4*i];
			end else begin
				lsio_core2pad_en_n[37+4*i]  = i2c_scl_oen_i[i];
				lsio_core2pad_data[37+4*i]  = 1'b0;		// drive 0 because board will have pullups
				lsio_pad2core_en_n[37+4*i]  = ~i2c_scl_oen_i[i];
				i2c_scl_o[i]                = lsio_pad2core_data[37+4*i];
			end
			// SDA
			lsio_interface_select_o[38+4*i] = i2c_enable_i[i];
			if (i2c_master_enable_i[i]) begin
				lsio_core2pad_en_n[38+4*i]  = i2c_sda_oen_i[i];
				lsio_core2pad_data[38+4*i]  = 1'b0;		// drive 0 because board will have pullups
				lsio_pad2core_en_n[38+4*i]  = ~i2c_sda_oen_i[i];
				i2c_sda_o[i]                = lsio_pad2core_data[38+4*i];
			end else begin
				lsio_core2pad_en_n[38+4*i]  = i2c_sda_oen_i[i];
				lsio_core2pad_data[38+4*i]  = 1'b0;		// drive 0 because board will have pullups
				lsio_pad2core_en_n[38+4*i]  = ~i2c_sda_oen_i[i];
				i2c_sda_o[i]                = lsio_pad2core_data[38+4*i];
			end
			// SMBUS ALERT [0]
			// active low, goes low when as a target device, it wants to talk to host
			lsio_interface_select_o[39+4*i] = i2c_enable_i[i];
			if (~i2c_master_enable_i[i]) begin
				lsio_core2pad_en_n[39+4*i]  = ~i2c_smbus_alert_oe_i[i];
				lsio_core2pad_data[39+4*i]  = 1'b0;
				lsio_pad2core_en_n[39+4*i]  = smc_padring_pkg::DISABLED;
				i2c_smbus_alert_n_o[i]      = 1'b0;
			end else begin
				lsio_core2pad_en_n[39+4*i]  = smc_padring_pkg::DISABLED;
				lsio_core2pad_data[39+4*i]  = 1'b0;
				lsio_pad2core_en_n[39+4*i]  = smc_padring_pkg::ENABLED;
				i2c_smbus_alert_n_o[i]      = lsio_pad2core_data[39+4*i];
			end
			// SMBUS SUSPEND
			// active low, goes low when want to suspend as a host
			lsio_interface_select_o[40+4*i] = i2c_enable_i[i];
			if (i2c_master_enable_i[i]) begin
				lsio_core2pad_en_n[40+4*i]  = i2c_smbus_n_i[i];
				lsio_core2pad_data[40+4*i]  = 1'b0;
				lsio_pad2core_en_n[40+4*i]  = smc_padring_pkg::DISABLED;
				i2c_smbus_n_o[i]            = 1'b0;
			end else begin
				lsio_core2pad_en_n[40+4*i]  = smc_padring_pkg::DISABLED;
				lsio_core2pad_data[40+4*i]  = 1'b0;
				lsio_pad2core_en_n[40+4*i]  = smc_padring_pkg::ENABLED;
				i2c_smbus_n_o[i]            = lsio_pad2core_data[40+4*i];
			end
		end

		// AVS
		lsio_interface_select_o[49] = avs_enable_i;
		lsio_core2pad_en_n[49]      = smc_padring_pkg::ENABLED;
		lsio_core2pad_data[49]      = avs_clock_i;
		lsio_pad2core_en_n[49]      = smc_padring_pkg::DISABLED;

		lsio_interface_select_o[50] = avs_enable_i;
		lsio_core2pad_en_n[50]      = smc_padring_pkg::ENABLED;
		lsio_core2pad_data[50]      = avs_mdata_i;
		lsio_pad2core_en_n[50]      = smc_padring_pkg::DISABLED;

		lsio_interface_select_o[51] = avs_enable_i;
		lsio_core2pad_en_n[51]      = smc_padring_pkg::DISABLED;
		lsio_core2pad_data[51]      = 1'b0;
		lsio_pad2core_en_n[51]      = smc_padring_pkg::ENABLED;
		avs_sdata_o                 = lsio_pad2core_data[51];

		// CAT THERM (GPIO 52) is driven via the smc_ip_integration 2nd HW
		// function override; primary path left at default.

		// Isolate Request Pin
		lsio_interface_select_o[53] = 1'b1;
		lsio_core2pad_en_n[53]      = smc_padring_pkg::DISABLED;
		lsio_core2pad_data[53]      = 1'b0;
		lsio_pad2core_en_n[53]      = smc_padring_pkg::ENABLED;
		isolate_req_pin_o           = lsio_pad2core_data[53];

		// SPI DQS Loopback
		lsio_interface_select_o[54] = spi_enable_i;
		lsio_core2pad_en_n[54]      = spi_mem_rebar_oepad_i;
		lsio_core2pad_data[54]      = spi_mem_rebar_opad_i;
		lsio_pad2core_en_n[54]      = spi_mem_rebar_iepad_i;
		spi_mem_rebar_ipad_o        = lsio_pad2core_data[54];

		// PLL Observation (GPIO 55) is driven via the smc_ip_integration 2nd HW
		// function override; primary path left at default.

		// Reserved
		lsio_interface_select_o[56] = '0;
		lsio_core2pad_en_n[56]      = smc_padring_pkg::DISABLED;
		lsio_core2pad_data[56]      = '0;
		lsio_pad2core_en_n[56]      = smc_padring_pkg::DISABLED;

		// PVT RO observation (GPIO 57) is driven via the smc_ip_integration 2nd HW
		// function override; primary path left at default.

		// System Timer OCTS
		// Primary: drive sync load and credit cnt signals to pad
		// Secondary: receive sync load and credit cnt signals from pad
		lsio_interface_select_o[58] = timer_gpio_enable_i;
		lsio_core2pad_en_n[58]      = chiplet_is_primary_i ? smc_padring_pkg::ENABLED : smc_padring_pkg::DISABLED;
		lsio_core2pad_data[58]      = chiplet_is_primary_i ? timer_sync_load_i : 1'b0;
		lsio_pad2core_en_n[58]      = chiplet_is_primary_i ? smc_padring_pkg::DISABLED : smc_padring_pkg::ENABLED;
		timer_sync_load_o           = lsio_pad2core_data[58];

		lsio_interface_select_o[59] = timer_gpio_enable_i;
		lsio_core2pad_en_n[59]      = chiplet_is_primary_i ? smc_padring_pkg::ENABLED : smc_padring_pkg::DISABLED;
		lsio_core2pad_data[59]      = chiplet_is_primary_i ? timer_cnt_credit_i : 1'b0;
		lsio_pad2core_en_n[59]      = chiplet_is_primary_i ? smc_padring_pkg::DISABLED : smc_padring_pkg::ENABLED;
		timer_cnt_credit_o          = lsio_pad2core_data[59];

		// Boot Stall
		lsio_interface_select_o[60]   = 1'b1;
		lsio_core2pad_en_n[60]        = smc_padring_pkg::DISABLED;
		lsio_core2pad_data[60]        = '0;
		lsio_pad2core_en_n[60]        = smc_padring_pkg::ENABLED;
		boot_stall_o				  = lsio_pad2core_data[60];

		// Reserved
		lsio_interface_select_o[61] = '0;
		lsio_core2pad_en_n[61]      = smc_padring_pkg::DISABLED;
		lsio_core2pad_data[61]      = '0;
		lsio_pad2core_en_n[61]      = smc_padring_pkg::DISABLED;

		// Cool Reset In (Dont drive here, just set pullup)
		lsio_interface_select_o[64] = '0;
		lsio_core2pad_en_n[64]      = smc_padring_pkg::DISABLED;
		lsio_core2pad_data[64]      = '0;
		lsio_pad2core_en_n[64]      = smc_padring_pkg::DISABLED;

		// Cool Reset Out
		lsio_interface_select_o[65] = 1'b1;
		lsio_core2pad_en_n[65]      = rst_cool_ni;
		lsio_core2pad_data[65]      = 1'b0;
		lsio_pad2core_en_n[65]      = smc_padring_pkg::DISABLED;

	end

	///////////
	// GPIOs //
	///////////

	// Generate GPIO interfaces
	for (genvar i = 0; i < smc_pkg::NUM_GPIO_WRAPS; i++) begin : gen_gpio_intf

		// Pad allocation settings
		localparam bit INPUT_BY_DEFAULT	= smc_padring_pkg::DefaultDirectionMap[i];

		// GPIO interface
		gpio #(
			.MAX_TRANS					(MAX_TRANS),
			.INPUT_BY_DEFAULT			(INPUT_BY_DEFAULT),

			.GPIO_INTF_REG_MAP_BASE_ADDR(GPIO_INTF_BASE_ADDR + (i * ADDRESS_MAP_SIZE_PER_GPIO)),
			.GPIO_INTF_REG_MAP_SIZE     (smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_SIZE),
			.ADDRESS_MAP_SIZE_PER_GPIO  (ADDRESS_MAP_SIZE_PER_GPIO)
		) u_gpio_interface (
			.clk_i					(clk_i),
			.rst_primary_ni			(rst_primary_ni),
			.rst_cold_ni			(rst_cold_stable_smc_clk_ni),
			.test_en_i				(test_en_i),

			// AXI-Lite Register Interface from secondary demux
			.axil_req_i				(axil_reqs_to_intf[i]),
			.axil_resp_o			(axil_resps_from_intf[i]),

			// LSIO Interface
			.lsio_interface_select_i(lsio_interface_select_o[i]),
			.lsio_core2pad_en_ni	(lsio_core2pad_en_n[i]),
			.lsio_core2pad_data_i	(lsio_core2pad_data[i]),
			.lsio_pad2core_en_ni	(lsio_pad2core_en_n[i]),
			.lsio_pad2core_data_o	(lsio_pad2core_data[i]),

			// GPIO Interrupts
			.interrupt_o			(gpio_interrupt_o[i]),

			.core2pad_o				(core2pad_o[i]),
			.core2pad_en_o			(core2pad_en_o[i]),
			.pad2core_i				(pad2core_i[i]),
			.pad2core_en_o			(pad2core_en_o[i])

		);
	end

endmodule