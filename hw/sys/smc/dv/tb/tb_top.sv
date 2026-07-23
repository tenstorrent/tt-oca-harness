// SPDX-License-Identifier: Apache-2.0
//
// Minimal DUT-only top for the SMC Verilator / Xcelium acceptance compile and
// the OSS cocotb / PyUVM smokes.

`timescale 1ps/1fs

module smc_uvm_top
    import smc_pkg::*;
    import smc_efuse_pkg::*;
(
    input wire logic clk_smc_i /*verilator public_flat_rw*/,
    input wire logic clk_ref_i /*verilator public_flat_rw*/,
    input wire logic clk_periph_i /*verilator public_flat_rw*/,

    input wire logic powergood_i /*verilator public_flat_rw*/,
    input wire logic rst_cold_ni /*verilator public_flat_rw*/,
    input wire logic rst_cool_ni /*verilator public_flat_rw*/,

    output logic powergood_stable_o /*verilator public_flat_rw*/,
    output logic rst_cold_stable_ref_clk_no /*verilator public_flat_rw*/,
    output logic rst_primary_ref_clk_no /*verilator public_flat_rw*/,
    output logic rst_primary_smc_clk_no /*verilator public_flat_rw*/,
    output logic rst_wdt_smc_clk_no /*verilator public_flat_rw*/,

    output logic [3:0] tb_i2c_debug_lo /*verilator public_flat_rw*/,
    output logic       tb_i2c_cg_en /*verilator public_flat_rw*/,
    input  wire logic  tb_i2c0_scl_ext_low /*verilator public_flat_rw*/,
    input  wire logic  tb_i2c0_sda_ext_low /*verilator public_flat_rw*/,
    output logic       tb_i2c0_scl /*verilator public_flat_rw*/,
    output logic       tb_i2c0_sda /*verilator public_flat_rw*/,
    output logic       tb_i2c0_scl_dut_low /*verilator public_flat_rw*/,
    output logic       tb_i2c0_sda_dut_low /*verilator public_flat_rw*/,
    // I2C0 SMBALERT# (pad 39): active-low; pullup-high when DUT OE released.
    output logic       tb_i2c0_smbalert /*verilator public_flat_rw*/,
    input  wire logic  tb_i3c0_scl_ext_low /*verilator public_flat_rw*/,
    input  wire logic  tb_i3c0_sda_ext_low /*verilator public_flat_rw*/,
    output logic       tb_i3c0_scl /*verilator public_flat_rw*/,
    output logic       tb_i3c0_sda /*verilator public_flat_rw*/,
    output logic       tb_i3c0_scl_dut_low /*verilator public_flat_rw*/,
    output logic       tb_i3c0_sda_dut_low /*verilator public_flat_rw*/,
    input  wire logic  tb_cpu_jtag_tck /*verilator public_flat_rw*/,
    input  wire logic  tb_cpu_jtag_tms /*verilator public_flat_rw*/,
    input  wire logic  tb_cpu_jtag_tdi /*verilator public_flat_rw*/,
    input  wire logic  tb_cpu_jtag_reset /*verilator public_flat_rw*/,
    output logic       tb_cpu_jtag_tdo /*verilator public_flat_rw*/,

    // UART0 pad-level split-port for the P2 Phase A UART loopback:
    //   pad 11 = UART0 RX (external drive → DUT input)
    //   pad 12 = UART0 TX (DUT output → external observe)
    input  wire logic tb_uart0_rx_ext_drive /*verilator public_flat_rw*/,
    output logic      tb_uart0_tx_from_dut /*verilator public_flat_rw*/,

    // Telemetry ATB receiver 0 pad lift (U4-6). Cocotb drives beats into
    // telemetry_at*_i[0]; receivers 1/2 stay tied off.
    input  wire logic [7:0] tb_telemetry0_atdata /*verilator public_flat_rw*/,
    input  wire logic [6:0] tb_telemetry0_atid /*verilator public_flat_rw*/,
    input  wire logic       tb_telemetry0_atvalid /*verilator public_flat_rw*/,
    output logic            tb_telemetry0_atready /*verilator public_flat_rw*/,
    input  wire logic       tb_telemetry0_afready /*verilator public_flat_rw*/,
    output logic            tb_telemetry0_afvalid /*verilator public_flat_rw*/,

    // SPI octal-flash pad lift (U2-1/U2-2). Cocotb drives tb_spi_* as the
    // external SPI host into the padring mux; flash MISO returns via
    // tb_spi_miso_ext -> pad2core[0] -> spi_rxd_o[0].
    input  wire logic       tb_spi_enable /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_clk /*verilator public_flat_rw*/,
    input  wire logic [7:0] tb_spi_txd /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_cs_n /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_cs_oe_n /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_cs_ie_n /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_clk_ie_n /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_clk_oe_n /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_dqs_ie_n /*verilator public_flat_rw*/,
    input  wire logic       tb_spi_dqs_oe_n /*verilator public_flat_rw*/,
    input  wire logic [7:0] tb_spi_dq_ie_n /*verilator public_flat_rw*/,
    input  wire logic [7:0] tb_spi_dq_oe_n /*verilator public_flat_rw*/,
    // Flash-BFM MISO into pad 0 (DQ0). Driven by OcahSepSpiFlash / cocotb.
    input  wire logic       tb_spi_miso_ext /*verilator public_flat_rw*/,
    output logic [7:0]      tb_spi_rxd /*verilator public_flat_rw*/,
    output logic            tb_spi_rxds /*verilator public_flat_rw*/,
    output logic            tb_spi_mem_rebar_ipad /*verilator public_flat_rw*/,

    output logic tb_sync_irq /*verilator public_flat_rw*/,
    output logic tb_gpio_irq_any /*verilator public_flat_rw*/,
    output logic tb_uart_irq_any /*verilator public_flat_rw*/,
    output logic tb_mailbox_irq_any /*verilator public_flat_rw*/,
    output logic tb_avsbus_irq /*verilator public_flat_rw*/,
    output logic tb_telemetry_irq_any /*verilator public_flat_rw*/,
    output logic [16:0] tb_avsbus_cur_state_debug /*verilator public_flat_rw*/,
    // Sideband pad observe/drive (U4-4/5): AVS clk/mdata observe, sdata inject,
    // OCTS sync/credit observe + dual-chiplet secondary inject (U4-5).
    output logic tb_avs_clk_from_dut /*verilator public_flat_rw*/,
    output logic tb_avs_mdata_from_dut /*verilator public_flat_rw*/,
    input  wire logic tb_avs_sdata_ext /*verilator public_flat_rw*/,
    output logic tb_octs_sync_load_from_dut /*verilator public_flat_rw*/,
    output logic tb_octs_cnt_credit_from_dut /*verilator public_flat_rw*/,
    // Runtime primary/secondary strap (smc.chiplet_is_primary_i). Default 1.
    input  wire logic tb_chiplet_is_primary /*verilator public_flat_rw*/,
    // Secondary inject into pads 58/59 (padring enables pad2core only when
    // chiplet_is_primary_i==0). Idle low when unused.
    input  wire logic tb_octs_sync_load_ext /*verilator public_flat_rw*/,
    input  wire logic tb_octs_cnt_credit_ext /*verilator public_flat_rw*/,
    input  wire logic [7:0] tb_sep_mailbox_interrupts /*verilator public_flat_rw*/,
    input  wire logic [smc_pkg::NUM_GPIO_WRAPS-1:0] tb_gpio_ext_drive_en /*verilator public_flat_rw*/,
    input  wire logic [smc_pkg::NUM_GPIO_WRAPS-1:0] tb_gpio_ext_drive_value /*verilator public_flat_rw*/,

    output logic tb_gpio_core2pad_any /*verilator public_flat_rw*/,
    output logic tb_gpio_core2pad_en_any /*verilator public_flat_rw*/,
    output logic tb_gpio_pad2core_en_any /*verilator public_flat_rw*/,

    // Flat inbound AXI manager driven by cocotbext-axi (prefix s_axi).
    // Mirrors the legacy SMC DV inbound AXI path for real CSR/fabric traffic.
    input  wire logic [5:0]   s_axi_awid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  s_axi_awaddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   s_axi_awlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_awsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   s_axi_awburst /*verilator public_flat_rw*/,
    input  wire logic         s_axi_awlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_awcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_awprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_awqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_awregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  s_axi_awuser /*verilator public_flat_rw*/,
    input  wire logic         s_axi_awvalid /*verilator public_flat_rw*/,
    output logic              s_axi_awready /*verilator public_flat_rw*/,

    input  wire logic [63:0]  s_axi_wdata /*verilator public_flat_rw*/,
    input  wire logic [7:0]   s_axi_wstrb /*verilator public_flat_rw*/,
    input  wire logic         s_axi_wlast /*verilator public_flat_rw*/,
    input  wire logic [11:0]  s_axi_wuser /*verilator public_flat_rw*/,
    input  wire logic         s_axi_wvalid /*verilator public_flat_rw*/,
    output logic              s_axi_wready /*verilator public_flat_rw*/,

    output logic [5:0]        s_axi_bid /*verilator public_flat_rw*/,
    output logic [1:0]        s_axi_bresp /*verilator public_flat_rw*/,
    output logic [11:0]       s_axi_buser /*verilator public_flat_rw*/,
    output logic              s_axi_bvalid /*verilator public_flat_rw*/,
    input  wire logic         s_axi_bready /*verilator public_flat_rw*/,

    input  wire logic [5:0]   s_axi_arid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  s_axi_araddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   s_axi_arlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_arsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   s_axi_arburst /*verilator public_flat_rw*/,
    input  wire logic         s_axi_arlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_arcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   s_axi_arprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_arqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   s_axi_arregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  s_axi_aruser /*verilator public_flat_rw*/,
    input  wire logic         s_axi_arvalid /*verilator public_flat_rw*/,
    output logic              s_axi_arready /*verilator public_flat_rw*/,

    output logic [5:0]        s_axi_rid /*verilator public_flat_rw*/,
    output logic [63:0]       s_axi_rdata /*verilator public_flat_rw*/,
    output logic [1:0]        s_axi_rresp /*verilator public_flat_rw*/,
    output logic              s_axi_rlast /*verilator public_flat_rw*/,
    output logic [11:0]       s_axi_ruser /*verilator public_flat_rw*/,
    output logic              s_axi_rvalid /*verilator public_flat_rw*/,
    input  wire logic         s_axi_rready /*verilator public_flat_rw*/,

    // Flat SYS-input AXI manager. SYS_IN reaches the filtered local-fabric path;
    // it is kept as a public active bus for SYS_IN/local-fabric VIP promotion.
    input  wire logic [5:0]   sys_axi_awid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  sys_axi_awaddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   sys_axi_awlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   sys_axi_awsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   sys_axi_awburst /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_awlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   sys_axi_awcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   sys_axi_awprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   sys_axi_awqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   sys_axi_awregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  sys_axi_awuser /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_awvalid /*verilator public_flat_rw*/,
    output logic              sys_axi_awready /*verilator public_flat_rw*/,

    input  wire logic [63:0]  sys_axi_wdata /*verilator public_flat_rw*/,
    input  wire logic [7:0]   sys_axi_wstrb /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_wlast /*verilator public_flat_rw*/,
    input  wire logic [11:0]  sys_axi_wuser /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_wvalid /*verilator public_flat_rw*/,
    output logic              sys_axi_wready /*verilator public_flat_rw*/,

    output logic [5:0]        sys_axi_bid /*verilator public_flat_rw*/,
    output logic [1:0]        sys_axi_bresp /*verilator public_flat_rw*/,
    output logic [11:0]       sys_axi_buser /*verilator public_flat_rw*/,
    output logic              sys_axi_bvalid /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_bready /*verilator public_flat_rw*/,

    input  wire logic [5:0]   sys_axi_arid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  sys_axi_araddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   sys_axi_arlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   sys_axi_arsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   sys_axi_arburst /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_arlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   sys_axi_arcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   sys_axi_arprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   sys_axi_arqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   sys_axi_arregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  sys_axi_aruser /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_arvalid /*verilator public_flat_rw*/,
    output logic              sys_axi_arready /*verilator public_flat_rw*/,

    output logic [5:0]        sys_axi_rid /*verilator public_flat_rw*/,
    output logic [63:0]       sys_axi_rdata /*verilator public_flat_rw*/,
    output logic [1:0]        sys_axi_rresp /*verilator public_flat_rw*/,
    output logic              sys_axi_rlast /*verilator public_flat_rw*/,
    output logic [11:0]       sys_axi_ruser /*verilator public_flat_rw*/,
    output logic              sys_axi_rvalid /*verilator public_flat_rw*/,
    input  wire logic         sys_axi_rready /*verilator public_flat_rw*/,

    // Flat JTAG AXI manager used by output-fabric final VIP tests.
    input  wire logic [1:0]   jtag_axi_awid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  jtag_axi_awaddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   jtag_axi_awlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   jtag_axi_awsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   jtag_axi_awburst /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_awlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   jtag_axi_awcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   jtag_axi_awprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   jtag_axi_awqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   jtag_axi_awregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  jtag_axi_awuser /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_awvalid /*verilator public_flat_rw*/,
    output logic              jtag_axi_awready /*verilator public_flat_rw*/,

    input  wire logic [63:0]  jtag_axi_wdata /*verilator public_flat_rw*/,
    input  wire logic [7:0]   jtag_axi_wstrb /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_wlast /*verilator public_flat_rw*/,
    input  wire logic [11:0]  jtag_axi_wuser /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_wvalid /*verilator public_flat_rw*/,
    output logic              jtag_axi_wready /*verilator public_flat_rw*/,

    output logic [1:0]        jtag_axi_bid /*verilator public_flat_rw*/,
    output logic [1:0]        jtag_axi_bresp /*verilator public_flat_rw*/,
    output logic [11:0]       jtag_axi_buser /*verilator public_flat_rw*/,
    output logic              jtag_axi_bvalid /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_bready /*verilator public_flat_rw*/,

    input  wire logic [1:0]   jtag_axi_arid /*verilator public_flat_rw*/,
    input  wire logic [55:0]  jtag_axi_araddr /*verilator public_flat_rw*/,
    input  wire logic [7:0]   jtag_axi_arlen /*verilator public_flat_rw*/,
    input  wire logic [2:0]   jtag_axi_arsize /*verilator public_flat_rw*/,
    input  wire logic [1:0]   jtag_axi_arburst /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_arlock /*verilator public_flat_rw*/,
    input  wire logic [3:0]   jtag_axi_arcache /*verilator public_flat_rw*/,
    input  wire logic [2:0]   jtag_axi_arprot /*verilator public_flat_rw*/,
    input  wire logic [3:0]   jtag_axi_arqos /*verilator public_flat_rw*/,
    input  wire logic [3:0]   jtag_axi_arregion /*verilator public_flat_rw*/,
    input  wire logic [11:0]  jtag_axi_aruser /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_arvalid /*verilator public_flat_rw*/,
    output logic              jtag_axi_arready /*verilator public_flat_rw*/,

    output logic [1:0]        jtag_axi_rid /*verilator public_flat_rw*/,
    output logic [63:0]       jtag_axi_rdata /*verilator public_flat_rw*/,
    output logic [1:0]        jtag_axi_rresp /*verilator public_flat_rw*/,
    output logic              jtag_axi_rlast /*verilator public_flat_rw*/,
    output logic [11:0]       jtag_axi_ruser /*verilator public_flat_rw*/,
    output logic              jtag_axi_rvalid /*verilator public_flat_rw*/,
    input  wire logic         jtag_axi_rready /*verilator public_flat_rw*/,

    // Per-interface AXI-Lite idle observability (OR of aw_valid/w_valid/ar_valid
    // on each of the five SMC downstream AXI-Lite master interfaces).
    output logic tb_axil_dtp_csr_active /*verilator public_flat_rw*/,
    output logic tb_axil_pll_active /*verilator public_flat_rw*/,
    output logic tb_axil_pvt_active /*verilator public_flat_rw*/,
    output logic tb_axil_extension_active /*verilator public_flat_rw*/,
    output logic tb_axil_efuse_bank_active /*verilator public_flat_rw*/,
    output logic tb_axil_any_master_active /*verilator public_flat_rw*/,

    // Output-fabric responder observability + U1-2 SLVERR inject knob.
    output logic [31:0] tb_output_axi_write_count /*verilator public_flat_rw*/,
    output logic [31:0] tb_output_axi_read_count /*verilator public_flat_rw*/,
    output logic [55:0] tb_output_axi_last_addr /*verilator public_flat_rw*/,
    output logic [63:0] tb_output_axi_last_wdata /*verilator public_flat_rw*/,
    input  wire logic   tb_output_force_slverr /*verilator public_flat_rw*/,
    // U6-2: SYS_OUT AXI slave response handshake for SmcOutputAxiMonitor.
    output logic        tb_output_axi_bvalid /*verilator public_flat_rw*/,
    output logic        tb_output_axi_bready /*verilator public_flat_rw*/,
    output logic [1:0]  tb_output_axi_bresp /*verilator public_flat_rw*/,
    output logic        tb_output_axi_rvalid /*verilator public_flat_rw*/,
    output logic        tb_output_axi_rready /*verilator public_flat_rw*/,
    output logic [1:0]  tb_output_axi_rresp /*verilator public_flat_rw*/,
    output logic [55:0] tb_output_axi_awaddr /*verilator public_flat_rw*/,
    output logic        tb_output_axi_awvalid /*verilator public_flat_rw*/,
    output logic        tb_output_axi_awready /*verilator public_flat_rw*/,
    output logic [55:0] tb_output_axi_araddr /*verilator public_flat_rw*/,
    output logic        tb_output_axi_arvalid /*verilator public_flat_rw*/,
    output logic        tb_output_axi_arready /*verilator public_flat_rw*/,

    // CPU memory responder observability for firmware boot tests.
    output logic [31:0] tb_cpu_rom_read_count /*verilator public_flat_rw*/,
    output logic [31:0] tb_cpu_scratch_read_count /*verilator public_flat_rw*/,
    output logic [31:0] tb_cpu_scratch_write_count /*verilator public_flat_rw*/,
    output logic [31:0] tb_cpu_fw_mailbox /*verilator public_flat_rw*/,
    output logic        tb_cpu_fw_mailbox_valid /*verilator public_flat_rw*/,
    output logic [31:0] tb_cpu_dcache_write_count /*verilator public_flat_rw*/,
    output logic [57:0] tb_cpu_wb_pc0 /*verilator public_flat_rw*/,
    output logic        tb_cpu_cluster_isolate /*verilator public_flat_rw*/,
    // U7-3: Rocket DM active + ack after dmcontrol.dmactive write.
    output logic        tb_cpu_debug_dmactive /*verilator public_flat_rw*/,
    output logic        tb_cpu_debug_dmactive_ack /*verilator public_flat_rw*/,

    // U7-1: ECC SBE/DBE inject into scratch bank0 reads + fire count.
    // tb_cpu_ecc_inject_probe pulses a synthetic bank0 read so inject can be
    // scored without depending on live CPU fetch traffic.
    input  wire logic   tb_cpu_ecc_inject_sbe /*verilator public_flat_rw*/,
    input  wire logic   tb_cpu_ecc_inject_dbe /*verilator public_flat_rw*/,
    input  wire logic   tb_cpu_ecc_inject_probe /*verilator public_flat_rw*/,
    output logic [31:0] tb_cpu_ecc_inject_fire_count /*verilator public_flat_rw*/,

    // U7-2: DFD/DBS fault inject + debug-bus capture latch.
    input  wire logic   tb_dfd_fault_inject /*verilator public_flat_rw*/,
    output logic        tb_dbs_capture_valid /*verilator public_flat_rw*/,
    output logic [31:0] tb_dbs_capture_data /*verilator public_flat_rw*/,

    // U7-5: eFuse behavioral responder observability.
    output logic        tb_fuse_sense_done /*verilator public_flat_rw*/,
    output logic [31:0] tb_efuse_otp_word0 /*verilator public_flat_rw*/,
    output logic [31:0] tb_efuse_programmed_word0 /*verilator public_flat_rw*/,
    output logic [smc_efuse_pkg::NumEfuseBits-1:0] efuse_shadow_probe_o /*verilator public_flat_rw*/,

    // P2-15 lifecycle-gated eFuse JTAG access-control hooks.
    // lc_state drive: 4-bit raw state + force-sigint. tb_top builds the
    // differential pair {diff_n, diff_p} = {~raw, raw} (valid, sigint=0)
    // or {raw, raw} (equal => integrity error, sigint=1) for lc_state_i.
    input  wire logic [3:0] tb_lc_state_raw /*verilator public_flat_rw*/,
    input  wire logic       tb_lc_state_force_sigint /*verilator public_flat_rw*/,

    // JTAG-side eFuse AXI-Lite master (cocotbext-axi AxiLiteMaster, prefix ej_axi)
    // into smc.axil_smc_otp_jtag_req_i (SMC-OTP JTAG access-control path).
    input  wire logic [31:0] ej_axi_awaddr /*verilator public_flat_rw*/,
    input  wire logic [2:0]  ej_axi_awprot /*verilator public_flat_rw*/,
    input  wire logic        ej_axi_awvalid /*verilator public_flat_rw*/,
    output logic             ej_axi_awready /*verilator public_flat_rw*/,
    input  wire logic [31:0] ej_axi_wdata /*verilator public_flat_rw*/,
    input  wire logic [3:0]  ej_axi_wstrb /*verilator public_flat_rw*/,
    input  wire logic        ej_axi_wvalid /*verilator public_flat_rw*/,
    output logic             ej_axi_wready /*verilator public_flat_rw*/,
    output logic [1:0]       ej_axi_bresp /*verilator public_flat_rw*/,
    output logic             ej_axi_bvalid /*verilator public_flat_rw*/,
    input  wire logic        ej_axi_bready /*verilator public_flat_rw*/,
    input  wire logic [31:0] ej_axi_araddr /*verilator public_flat_rw*/,
    input  wire logic [2:0]  ej_axi_arprot /*verilator public_flat_rw*/,
    input  wire logic        ej_axi_arvalid /*verilator public_flat_rw*/,
    output logic             ej_axi_arready /*verilator public_flat_rw*/,
    output logic [31:0]      ej_axi_rdata /*verilator public_flat_rw*/,
    output logic [1:0]       ej_axi_rresp /*verilator public_flat_rw*/,
    output logic             ej_axi_rvalid /*verilator public_flat_rw*/,
    input  wire logic        ej_axi_rready /*verilator public_flat_rw*/
);

    /* verilator public_module */

    smc_sep_in_56_64_6_12_axi_req_t  sep_axi_in_req;
    smc_sep_in_56_64_6_12_axi_resp_t sep_axi_in_resp;
    smc_sys_in_56_64_6_12_axi_req_t  sys_axi_in_req;
    smc_sys_in_56_64_6_12_axi_resp_t sys_axi_in_resp;
    smc_jtag_56_64_2_12_axi_req_t    jtag_axi_in_req;
    smc_jtag_56_64_2_12_axi_resp_t   jtag_axi_in_resp;
    smc_sys_out_56_64_8_12_axi_req_t  output_axi_req;
    smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] tb_pad2core;

    // Telemetry ATB bundle (receiver 0 driven; 1/2 quiet).
    telemetry_receiver_pkg::telemetry_data_t
        [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atdata;
    telemetry_receiver_pkg::atb_id_t
        [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atid;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atvalid;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_atready;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_afvalid;
    logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0] tb_telemetry_afready;

    assign tb_telemetry_atdata[0] = tb_telemetry0_atdata;
    assign tb_telemetry_atid[0] = tb_telemetry0_atid;
    assign tb_telemetry_atvalid[0] = tb_telemetry0_atvalid;
    assign tb_telemetry0_atready = tb_telemetry_atready[0];
    assign tb_telemetry0_afvalid = tb_telemetry_afvalid[0];
    assign tb_telemetry_afready[0] = tb_telemetry0_afready;
    for (genvar tel_i = 1; tel_i < smc_config_pkg::NUM_TELEMETRY_RECEIVERS; tel_i++) begin : g_tel_tie
        assign tb_telemetry_atdata[tel_i] = '0;
        assign tb_telemetry_atid[tel_i] = '0;
        assign tb_telemetry_atvalid[tel_i] = 1'b0;
        assign tb_telemetry_afready[tel_i] = 1'b1;
    end

    // External peripheral-macro AXI-Lite master ports. smc routes CSR accesses
    // to hard macros (PLL, PVT, DTP CSR, peripheral extension) and to the
    // adopter padring GPIO control plane (GPIO_CTRL / GPIO_REFCLK_CTRL, i.e.
    // everything at/above GPIO_CTRL_0__REG_MAP_BASE_ADDR) out of these ports.
    // The OSS bench terminates each with a DECERR *boundary responder*
    // (a bus terminator, see prim_axi_lite_err_slv instances below). This does
    // NOT model any macro function; it only completes the AXI-Lite handshake so
    // the peripheral AXI-Lite xbar decode/route to every macro window is
    // positively observable through tb_axil_*_active, instead of hanging with
    // no responder. Macro-internal behaviour is out of SMC unit-verification
    // scope (owned by each macro's own IP-level DV).
    smc_axil_32_32_req_t  axil_pll_req;
    smc_axil_32_32_resp_t axil_pll_resp;
    smc_axil_32_32_req_t  axil_pvt_req;
    smc_axil_32_32_resp_t axil_pvt_resp;
    smc_axil_32_32_req_t  axil_dtp_csr_req;
    smc_axil_32_32_resp_t axil_dtp_csr_resp;
    smc_axil_32_32_req_t  axil_extension_req;
    smc_axil_32_32_resp_t axil_extension_resp;
    // Adopter padring GPIO control-plane external port (uses gpio_pkg AXI-Lite
    // struct types; 32b addr / 32b data, layout-identical to smc_axil_32_32).
    gpio_pkg::gpio_axil_req_t  axil_gpio_ctrl_req;
    gpio_pkg::gpio_axil_resp_t axil_gpio_ctrl_resp;
    // eFuse bank AXI-Lite master (macro) + fuse-command shim (analog model).
    smc_axil_32_32_req_t               axil_efuse_bank_req;
    smc_axil_32_32_resp_t              axil_efuse_bank_resp;
    smc_efuse_pkg::fuse_command_req_t  efuse_cmd_req;
    smc_efuse_pkg::fuse_command_resp_t efuse_cmd_resp;

    // I3C DAT/DCT/RLT memories (required under CONTROLLER_SUPPORT=1 / #3934).
    i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_src;
    i3c_pkg::dat_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dat_mem_sink;
    i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_src;
    i3c_pkg::dct_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_dct_mem_sink;
    i3c_pkg::rlt_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_src;
    i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NUM_I3C-1:0] i3c_rlt_mem_sink;

    chipyard_4core_mem_pkg::rom_req_t            smc_rom_req;
    chipyard_4core_mem_pkg::rom_rsp_t            smc_rom_rsp;
    chipyard_4core_mem_pkg::scratch_ram_req_t    smc_scratch_ram_req
        [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0];
    chipyard_4core_mem_pkg::scratch_ram_rsp_t    smc_scratch_ram_rsp
        [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_icache_tag_req_t  smc_l1_icache_tag_req
        [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_icache_tag_rsp_t  smc_l1_icache_tag_rsp
        [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_icache_data_req_t smc_l1_icache_data_req
        [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_icache_data_rsp_t smc_l1_icache_data_rsp
        [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_dcache_tag_req_t  smc_l1_dcache_tag_req
        [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t  smc_l1_dcache_tag_rsp
        [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_dcache_data_req_t smc_l1_dcache_data_req
        [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0];
    chipyard_4core_mem_pkg::l1_dcache_data_rsp_t smc_l1_dcache_data_rsp
        [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0];

    localparam int unsigned I2C0_SCL_PAD = 37;
    localparam int unsigned I2C0_SDA_PAD = 38;
    localparam int unsigned I2C0_SMBALERT_PAD = 39;
    localparam int unsigned I3C0_SCL_PAD = 27;
    localparam int unsigned I3C0_SDA_PAD = 28;
    // Per smc_padring.sv gen_uart_connections (base 11+4*u):
    //   pad 11 = UART0 RX (pad → core), pad 12 = UART0 TX (core → pad).
    localparam int unsigned UART0_RX_PAD = 11;
    localparam int unsigned UART0_TX_PAD = 12;
    // smc_padring.sv pad 60 = boot_stall (active-high). Default pad2core='1
    // would sticky-stall fuse_reset_n and keep the CPU in mem-init forever.
    // +smc_hold_cpu_boot keeps stall asserted from time-0 so FW-boot tests can
    // program RESET_VECTOR before the Rocket tiles ever fetch from ROM.
    localparam int unsigned BOOT_STALL_PAD = 60;
    bit tb_hold_cpu_boot;
    initial begin
        tb_hold_cpu_boot = 1'b0;
        if ($test$plusargs("smc_hold_cpu_boot")) begin
            tb_hold_cpu_boot = 1'b1;
            $display("[tb_top] +smc_hold_cpu_boot: pad60 boot_stall held until TB release");
        end
    end

    // Minimal LSIO open-drain resolver for I2C0. The SMC padring maps I2C0
    // SCL/SDA to GPIO pads 37/38. Released lines resolve high; either the DUT
    // or cocotb side may pull a line low.
    assign tb_i2c0_scl_dut_low = !u_dut.u_smc_peripherals.i2c_scl_o[0];
    assign tb_i2c0_sda_dut_low = !u_dut.u_smc_peripherals.i2c_sda_o[0];
    assign tb_i2c0_scl = !(tb_i2c0_scl_dut_low || tb_i2c0_scl_ext_low);
    assign tb_i2c0_sda = !(tb_i2c0_sda_dut_low || tb_i2c0_sda_ext_low);
    assign tb_i3c0_scl_dut_low = u_dut.u_smc_peripherals.i3c_scl_oe_to_pad[0] &&
                                  !u_dut.u_smc_peripherals.i3c_scl_to_pad[0];
    assign tb_i3c0_sda_dut_low = u_dut.u_smc_peripherals.i3c_sda_oe_to_pad[0] &&
                                  !u_dut.u_smc_peripherals.i3c_sda_to_pad[0];
    assign tb_i3c0_scl = !(tb_i3c0_scl_dut_low || tb_i3c0_scl_ext_low);
    assign tb_i3c0_sda = !(tb_i3c0_sda_dut_low || tb_i3c0_sda_ext_low);

    always_comb begin
        tb_pad2core = '1;
        for (int unsigned gpio_idx = 0; gpio_idx < smc_pkg::NUM_GPIO_WRAPS; gpio_idx++) begin
            if (tb_gpio_ext_drive_en[gpio_idx]) begin
                tb_pad2core[gpio_idx] = tb_gpio_ext_drive_value[gpio_idx];
            end
        end
        tb_pad2core[I2C0_SCL_PAD] = tb_i2c0_scl;
        tb_pad2core[I2C0_SDA_PAD] = tb_i2c0_sda;
        tb_pad2core[I3C0_SCL_PAD] = tb_i3c0_scl;
        tb_pad2core[I3C0_SDA_PAD] = tb_i3c0_sda;
        // UART0 RX: the external world drives one line into the DUT.
        tb_pad2core[UART0_RX_PAD] = tb_uart0_rx_ext_drive;
        // Boot stall: released by default; held when +smc_hold_cpu_boot is set
        // unless a test explicitly drives pad 60 via GPIO override.
        if (!tb_gpio_ext_drive_en[BOOT_STALL_PAD]) begin
            tb_pad2core[BOOT_STALL_PAD] = tb_hold_cpu_boot;
        end
        // SPI DQ0 MISO from flash BFM when SPI mux is enabled (pads 0-7).
        if (tb_spi_enable) begin
            tb_pad2core[0] = tb_spi_miso_ext;
        end
        // AVSBus sdata (pad 51): external slave ACK BFM into DUT.
        tb_pad2core[51] = tb_avs_sdata_ext;
        // OCTS dual-chiplet secondary inject (pads 58/59). Harmless when
        // primary (padring disables pad2core on these pads).
        tb_pad2core[58] = tb_octs_sync_load_ext;
        tb_pad2core[59] = tb_octs_cnt_credit_ext;
    end

    // UART0 TX: the DUT drives one line out to the external world.
    assign tb_uart0_tx_from_dut = u_dut.core2pad_o[UART0_TX_PAD];
    // I2C0 SMBALERT# (pad 39): OE-aware resolve (active-low when DUT drives).
    // core2pad_en_o is active-high (~lsio_core2pad_en_ni); data is 0 when OE.
    assign tb_i2c0_smbalert = u_dut.core2pad_en_o[I2C0_SMBALERT_PAD]
                              ? u_dut.core2pad_o[I2C0_SMBALERT_PAD]
                              : 1'b1;
    // AVSBus pads 49/50 (clk/mdata) and OCTS pads 58/59 (sync/credit) observe.
    assign tb_avs_clk_from_dut = u_dut.core2pad_o[49];
    assign tb_avs_mdata_from_dut = u_dut.core2pad_o[50];
    assign tb_octs_sync_load_from_dut = u_dut.core2pad_o[58];
    assign tb_octs_cnt_credit_from_dut = u_dut.core2pad_o[59];

    assign sep_axi_in_req.aw.id     = s_axi_awid;
    assign sep_axi_in_req.aw.addr   = s_axi_awaddr;
    assign sep_axi_in_req.aw.len    = s_axi_awlen;
    assign sep_axi_in_req.aw.size   = s_axi_awsize;
    assign sep_axi_in_req.aw.burst  = s_axi_awburst;
    assign sep_axi_in_req.aw.lock   = s_axi_awlock;
    assign sep_axi_in_req.aw.cache  = s_axi_awcache;
    assign sep_axi_in_req.aw.prot   = s_axi_awprot;
    assign sep_axi_in_req.aw.qos    = s_axi_awqos;
    assign sep_axi_in_req.aw.region = s_axi_awregion;
    assign sep_axi_in_req.aw.user   = s_axi_awuser;
    // Force ATOP=0 on all AXI ingresses; the outbound filter's err_slv is
    // built with `.ATOPs(1'b0)` and its `assume` on `atop == '0` fires a
    // fatal on Xcelium when the field is left X-propagating.
    assign sep_axi_in_req.aw.atop   = '0;
    assign sep_axi_in_req.aw_valid  = s_axi_awvalid;
    assign s_axi_awready            = sep_axi_in_resp.aw_ready;

    assign sep_axi_in_req.w.data    = s_axi_wdata;
    assign sep_axi_in_req.w.strb    = s_axi_wstrb;
    assign sep_axi_in_req.w.last    = s_axi_wlast;
    assign sep_axi_in_req.w.user    = s_axi_wuser;
    assign sep_axi_in_req.w_valid   = s_axi_wvalid;
    assign s_axi_wready             = sep_axi_in_resp.w_ready;

    assign s_axi_bid                = sep_axi_in_resp.b.id;
    assign s_axi_bresp              = sep_axi_in_resp.b.resp;
    assign s_axi_buser              = sep_axi_in_resp.b.user;
    assign s_axi_bvalid             = sep_axi_in_resp.b_valid;
    assign sep_axi_in_req.b_ready   = s_axi_bready;

    assign sep_axi_in_req.ar.id     = s_axi_arid;
    assign sep_axi_in_req.ar.addr   = s_axi_araddr;
    assign sep_axi_in_req.ar.len    = s_axi_arlen;
    assign sep_axi_in_req.ar.size   = s_axi_arsize;
    assign sep_axi_in_req.ar.burst  = s_axi_arburst;
    assign sep_axi_in_req.ar.lock   = s_axi_arlock;
    assign sep_axi_in_req.ar.cache  = s_axi_arcache;
    assign sep_axi_in_req.ar.prot   = s_axi_arprot;
    assign sep_axi_in_req.ar.qos    = s_axi_arqos;
    assign sep_axi_in_req.ar.region = s_axi_arregion;
    assign sep_axi_in_req.ar.user   = s_axi_aruser;
    assign sep_axi_in_req.ar_valid  = s_axi_arvalid;
    assign s_axi_arready            = sep_axi_in_resp.ar_ready;

    assign s_axi_rid                = sep_axi_in_resp.r.id;
    assign s_axi_rdata              = sep_axi_in_resp.r.data;
    assign s_axi_rresp              = sep_axi_in_resp.r.resp;
    assign s_axi_rlast              = sep_axi_in_resp.r.last;
    assign s_axi_ruser              = sep_axi_in_resp.r.user;
    assign s_axi_rvalid             = sep_axi_in_resp.r_valid;
    assign sep_axi_in_req.r_ready   = s_axi_rready;

    assign sys_axi_in_req.aw.id     = sys_axi_awid;
    assign sys_axi_in_req.aw.addr   = sys_axi_awaddr;
    assign sys_axi_in_req.aw.len    = sys_axi_awlen;
    assign sys_axi_in_req.aw.size   = sys_axi_awsize;
    assign sys_axi_in_req.aw.burst  = sys_axi_awburst;
    assign sys_axi_in_req.aw.lock   = sys_axi_awlock;
    assign sys_axi_in_req.aw.cache  = sys_axi_awcache;
    assign sys_axi_in_req.aw.prot   = sys_axi_awprot;
    assign sys_axi_in_req.aw.qos    = sys_axi_awqos;
    assign sys_axi_in_req.aw.region = sys_axi_awregion;
    assign sys_axi_in_req.aw.user   = sys_axi_awuser;
    assign sys_axi_in_req.aw.atop   = '0;
    assign sys_axi_in_req.aw_valid  = sys_axi_awvalid;
    assign sys_axi_awready          = sys_axi_in_resp.aw_ready;

    assign sys_axi_in_req.w.data    = sys_axi_wdata;
    assign sys_axi_in_req.w.strb    = sys_axi_wstrb;
    assign sys_axi_in_req.w.last    = sys_axi_wlast;
    assign sys_axi_in_req.w.user    = sys_axi_wuser;
    assign sys_axi_in_req.w_valid   = sys_axi_wvalid;
    assign sys_axi_wready           = sys_axi_in_resp.w_ready;

    assign sys_axi_bid              = sys_axi_in_resp.b.id;
    assign sys_axi_bresp            = sys_axi_in_resp.b.resp;
    assign sys_axi_buser            = sys_axi_in_resp.b.user;
    assign sys_axi_bvalid           = sys_axi_in_resp.b_valid;
    assign sys_axi_in_req.b_ready   = sys_axi_bready;

    assign sys_axi_in_req.ar.id     = sys_axi_arid;
    assign sys_axi_in_req.ar.addr   = sys_axi_araddr;
    assign sys_axi_in_req.ar.len    = sys_axi_arlen;
    assign sys_axi_in_req.ar.size   = sys_axi_arsize;
    assign sys_axi_in_req.ar.burst  = sys_axi_arburst;
    assign sys_axi_in_req.ar.lock   = sys_axi_arlock;
    assign sys_axi_in_req.ar.cache  = sys_axi_arcache;
    assign sys_axi_in_req.ar.prot   = sys_axi_arprot;
    assign sys_axi_in_req.ar.qos    = sys_axi_arqos;
    assign sys_axi_in_req.ar.region = sys_axi_arregion;
    assign sys_axi_in_req.ar.user   = sys_axi_aruser;
    assign sys_axi_in_req.ar_valid  = sys_axi_arvalid;
    assign sys_axi_arready          = sys_axi_in_resp.ar_ready;

    assign sys_axi_rid              = sys_axi_in_resp.r.id;
    assign sys_axi_rdata            = sys_axi_in_resp.r.data;
    assign sys_axi_rresp            = sys_axi_in_resp.r.resp;
    assign sys_axi_rlast            = sys_axi_in_resp.r.last;
    assign sys_axi_ruser            = sys_axi_in_resp.r.user;
    assign sys_axi_rvalid           = sys_axi_in_resp.r_valid;
    assign sys_axi_in_req.r_ready   = sys_axi_rready;

    assign jtag_axi_in_req.aw.id     = jtag_axi_awid;
    assign jtag_axi_in_req.aw.addr   = jtag_axi_awaddr;
    assign jtag_axi_in_req.aw.len    = jtag_axi_awlen;
    assign jtag_axi_in_req.aw.size   = jtag_axi_awsize;
    assign jtag_axi_in_req.aw.burst  = jtag_axi_awburst;
    assign jtag_axi_in_req.aw.lock   = jtag_axi_awlock;
    assign jtag_axi_in_req.aw.cache  = jtag_axi_awcache;
    assign jtag_axi_in_req.aw.prot   = jtag_axi_awprot;
    assign jtag_axi_in_req.aw.qos    = jtag_axi_awqos;
    assign jtag_axi_in_req.aw.region = jtag_axi_awregion;
    assign jtag_axi_in_req.aw.user   = jtag_axi_awuser;
    assign jtag_axi_in_req.aw.atop   = '0;
    assign jtag_axi_in_req.aw_valid  = jtag_axi_awvalid;
    assign jtag_axi_awready          = jtag_axi_in_resp.aw_ready;

    assign jtag_axi_in_req.w.data    = jtag_axi_wdata;
    assign jtag_axi_in_req.w.strb    = jtag_axi_wstrb;
    assign jtag_axi_in_req.w.last    = jtag_axi_wlast;
    assign jtag_axi_in_req.w.user    = jtag_axi_wuser;
    assign jtag_axi_in_req.w_valid   = jtag_axi_wvalid;
    assign jtag_axi_wready           = jtag_axi_in_resp.w_ready;

    assign jtag_axi_bid              = jtag_axi_in_resp.b.id;
    assign jtag_axi_bresp            = jtag_axi_in_resp.b.resp;
    assign jtag_axi_buser            = jtag_axi_in_resp.b.user;
    assign jtag_axi_bvalid           = jtag_axi_in_resp.b_valid;
    assign jtag_axi_in_req.b_ready   = jtag_axi_bready;

    assign jtag_axi_in_req.ar.id     = jtag_axi_arid;
    assign jtag_axi_in_req.ar.addr   = jtag_axi_araddr;
    assign jtag_axi_in_req.ar.len    = jtag_axi_arlen;
    assign jtag_axi_in_req.ar.size   = jtag_axi_arsize;
    assign jtag_axi_in_req.ar.burst  = jtag_axi_arburst;
    assign jtag_axi_in_req.ar.lock   = jtag_axi_arlock;
    assign jtag_axi_in_req.ar.cache  = jtag_axi_arcache;
    assign jtag_axi_in_req.ar.prot   = jtag_axi_arprot;
    assign jtag_axi_in_req.ar.qos    = jtag_axi_arqos;
    assign jtag_axi_in_req.ar.region = jtag_axi_arregion;
    assign jtag_axi_in_req.ar.user   = jtag_axi_aruser;
    assign jtag_axi_in_req.ar_valid  = jtag_axi_arvalid;
    assign jtag_axi_arready          = jtag_axi_in_resp.ar_ready;

    assign jtag_axi_rid              = jtag_axi_in_resp.r.id;
    assign jtag_axi_rdata            = jtag_axi_in_resp.r.data;
    assign jtag_axi_rresp            = jtag_axi_in_resp.r.resp;
    assign jtag_axi_rlast            = jtag_axi_in_resp.r.last;
    assign jtag_axi_ruser            = jtag_axi_in_resp.r.user;
    assign jtag_axi_rvalid           = jtag_axi_in_resp.r_valid;
    assign jtag_axi_in_req.r_ready   = jtag_axi_rready;

    // Output-fabric AXI memory responder (U1-1/U1-2): SEP-style shim with
    // optional +smc_output_hex preload and programmable SLVERR inject.
    tb_smc_output_mem_responder u_output_mem (
        .clk_i          (clk_smc_i),
        .rst_ni         (rst_cold_ni),
        .axi_req_i      (output_axi_req),
        .axi_resp_o     (output_axi_resp),
        .force_slverr_i (tb_output_force_slverr),
        .write_count_o  (tb_output_axi_write_count),
        .read_count_o   (tb_output_axi_read_count),
        .last_addr_o    (tb_output_axi_last_addr),
        .last_wdata_o   (tb_output_axi_last_wdata)
    );

    // U6-2: lift SYS_OUT AXI response / address handshakes for cocotb monitor.
    assign tb_output_axi_bvalid  = output_axi_resp.b_valid;
    assign tb_output_axi_bready  = output_axi_req.b_ready;
    assign tb_output_axi_bresp   = output_axi_resp.b.resp;
    assign tb_output_axi_rvalid  = output_axi_resp.r_valid;
    assign tb_output_axi_rready  = output_axi_req.r_ready;
    assign tb_output_axi_rresp   = output_axi_resp.r.resp;
    assign tb_output_axi_awaddr  = output_axi_req.aw.addr;
    assign tb_output_axi_awvalid = output_axi_req.aw_valid;
    assign tb_output_axi_awready = output_axi_resp.aw_ready;
    assign tb_output_axi_araddr  = output_axi_req.ar.addr;
    assign tb_output_axi_arvalid = output_axi_req.ar_valid;
    assign tb_output_axi_arready = output_axi_resp.ar_ready;

    // P2-15 lc_state differential drive. lc_state_i = {diff_n, diff_p}: the
    // decoder returns diff_p as the raw value and flags sigint when diff_n is
    // not the bitwise complement of diff_p. Default (raw=0, no force) yields
    // valid TEST_DEV so tests that do not touch this path are unaffected.
    logic [smc_pkg::LC_STATE_WIDTH-1:0]     lc_state_raw_drv;
    logic [2*smc_pkg::LC_STATE_WIDTH-1:0]   lc_state_drv;
    assign lc_state_raw_drv = tb_lc_state_raw[smc_pkg::LC_STATE_WIDTH-1:0];
    assign lc_state_drv     = tb_lc_state_force_sigint ?
                                {lc_state_raw_drv,  lc_state_raw_drv} :
                                {~lc_state_raw_drv, lc_state_raw_drv};

    // P2-15 JTAG-side eFuse AXI-Lite master pack/unpack.
    smc_axil_32_32_req_t  ej_axi_req;
    smc_axil_32_32_resp_t ej_axi_resp;
    assign ej_axi_req.aw.addr  = ej_axi_awaddr;
    assign ej_axi_req.aw.prot  = ej_axi_awprot;
    assign ej_axi_req.aw_valid = ej_axi_awvalid;
    assign ej_axi_awready      = ej_axi_resp.aw_ready;
    assign ej_axi_req.w.data   = ej_axi_wdata;
    assign ej_axi_req.w.strb   = ej_axi_wstrb;
    assign ej_axi_req.w_valid  = ej_axi_wvalid;
    assign ej_axi_wready       = ej_axi_resp.w_ready;
    assign ej_axi_bresp        = ej_axi_resp.b.resp;
    assign ej_axi_bvalid       = ej_axi_resp.b_valid;
    assign ej_axi_req.b_ready  = ej_axi_bready;
    assign ej_axi_req.ar.addr  = ej_axi_araddr;
    assign ej_axi_req.ar.prot  = ej_axi_arprot;
    assign ej_axi_req.ar_valid = ej_axi_arvalid;
    assign ej_axi_arready      = ej_axi_resp.ar_ready;
    assign ej_axi_rdata        = ej_axi_resp.r.data;
    assign ej_axi_rresp        = ej_axi_resp.r.resp;
    assign ej_axi_rvalid       = ej_axi_resp.r_valid;
    assign ej_axi_req.r_ready  = ej_axi_rready;

    // CPU ROM/scratch/cache memory responders. These are the SMC equivalent of
    // the OSS memory-shim style and keep the bare SMC CPU memory ports driven.
    tb_smc_cpu_mem_responder u_cpu_mem (
        .clk_i                 (clk_smc_i),
        .rst_ni                (rst_cold_ni),
        .rom_req_i             (smc_rom_req),
        .rom_rsp_o             (smc_rom_rsp),
        .scratch_ram_req_i     (smc_scratch_ram_req),
        .scratch_ram_rsp_o     (smc_scratch_ram_rsp),
        .l1_icache_tag_req_i   (smc_l1_icache_tag_req),
        .l1_icache_tag_rsp_o   (smc_l1_icache_tag_rsp),
        .l1_icache_data_req_i  (smc_l1_icache_data_req),
        .l1_icache_data_rsp_o  (smc_l1_icache_data_rsp),
        .l1_dcache_tag_req_i   (smc_l1_dcache_tag_req),
        .l1_dcache_tag_rsp_o   (smc_l1_dcache_tag_rsp),
        .l1_dcache_data_req_i  (smc_l1_dcache_data_req),
        .l1_dcache_data_rsp_o  (smc_l1_dcache_data_rsp),
        .rom_read_count_o          (tb_cpu_rom_read_count),
        .scratch_ram_read_count_o  (tb_cpu_scratch_read_count),
        .scratch_ram_write_count_o (tb_cpu_scratch_write_count),
        .fw_mailbox_o              (tb_cpu_fw_mailbox),
        .fw_mailbox_valid_o        (tb_cpu_fw_mailbox_valid),
        .dcache_data_write_count_o (tb_cpu_dcache_write_count),
        .ecc_inject_sbe_i          (tb_cpu_ecc_inject_sbe),
        .ecc_inject_dbe_i          (tb_cpu_ecc_inject_dbe),
        .ecc_inject_probe_i        (tb_cpu_ecc_inject_probe),
        .ecc_inject_fire_count_o   (tb_cpu_ecc_inject_fire_count)
    );

    smc u_dut (
        .clk_smc_i,
        .clk_ref_i,
        .clk_periph_i,
        .powergood_i,
        .powergood_stable_o,
        .rst_cold_ni,
        .rst_cold_stable_ref_clk_no,
        .rst_primary_ref_clk_no,
        .rst_primary_smc_clk_no,
        .rst_wdt_smc_clk_no,
        // DFT scan controls: match smc.sv port names (test_en_i / scan_rst_ni).
        // Functional mode (scan disabled) with scan reset deasserted.
        .test_en_i(1'b0),
        .scan_rst_ni(1'b1),
        .rst_cool_n_from_pin_i(rst_cool_ni),
        .sep_axi_in_req_i(sep_axi_in_req),
        .sep_axi_in_resp_o(sep_axi_in_resp),
        .sys_axi_in_req_i(sys_axi_in_req),
        .sys_axi_in_resp_o(sys_axi_in_resp),
        .jtag_axi_in_req_i(jtag_axi_in_req),
        .jtag_axi_in_resp_o(jtag_axi_in_resp),
        // P2-15 lifecycle-gated eFuse JTAG access-control path.
        .lc_state_i(lc_state_drv),
        .axil_smc_otp_jtag_req_i(ej_axi_req),
        .axil_smc_otp_jtag_resp_o(ej_axi_resp),
        // External peripheral-macro AXI-Lite master ports terminated by DECERR
        // boundary responders (instantiated after u_dut) for routing coverage.
        .axil_pll_req_o(axil_pll_req),
        .axil_pll_resp_i(axil_pll_resp),
        .axil_pvt_req_o(axil_pvt_req),
        .axil_pvt_resp_i(axil_pvt_resp),
        .axil_dtp_csr_req_o(axil_dtp_csr_req),
        .axil_dtp_csr_resp_i(axil_dtp_csr_resp),
        .axil_extension_req_o(axil_extension_req),
        .axil_extension_resp_i(axil_extension_resp),
        // Adopter padring GPIO control plane (GPIO_CTRL / GPIO_REFCLK_CTRL
        // windows) -- terminated by u_gpio_ctrl_rw_stub (U5 RW mirror).
        .axil_req_gpio_ctrl_o(axil_gpio_ctrl_req),
        .axil_resp_gpio_ctrl_i(axil_gpio_ctrl_resp),
        .pad2core_i(tb_pad2core),
        .smc_cpu_jtag_TCK_i(tb_cpu_jtag_tck),
        .smc_cpu_jtag_TMS_i(tb_cpu_jtag_tms),
        .smc_cpu_jtag_TDI_i(tb_cpu_jtag_tdi),
        .smc_cpu_jtag_TDO_data_o(tb_cpu_jtag_tdo),
        .smc_cpu_jtag_reset_i(tb_cpu_jtag_reset),
        .smc_cpu_jtag_mfr_id_i(11'h2AA),
        .smc_cpu_jtag_part_number_i(16'h0CA0),
        .smc_cpu_jtag_version_i(4'h1),
        .sep_mailbox_interrupts_i(tb_sep_mailbox_interrupts),
        // Preserve +smc_scratch_ram_hex / +smc_rom_hex preloads: the Chipyard
        // scratch auto-zero FSM would otherwise wipe the image before fetch.
        .disable_sram_auto_init_i(1'b1),
        // Boot / fuse sideband defaults (match legacy smc_chiplet_wrap ties).
        .ext_boot_seq_done_i(1'b1),
        .sep_wdt_reset_n_i(1'b1),
        .ss_reset_complete_i('1),
        .chiplet_is_primary_i(tb_chiplet_is_primary),
        .ndmreset_request_i('0),
        .boot_stall_jtag_ovrd_i(1'b0),
        .boot_stall_jtag_val_i(1'b0),
        .sep_security_disable_i(1'b0),
        .temp_interrupt_i(1'b0),
        .ext_interrupts_i('0),
        .cfg_flr_pf_active_i(1'b0),
        .jtag_reset_ctrl_i('0),
        .efuse_bank_ctrl_req_o(axil_efuse_bank_req),
        .efuse_bank_ctrl_resp_i(axil_efuse_bank_resp),
        .efuse_shim_command_req_o(efuse_cmd_req),
        .efuse_shim_command_resp_i(efuse_cmd_resp),
        .rom_intf_req_o(smc_rom_req),
        .rom_intf_rsp_i(smc_rom_rsp),
        .scratch_ram_intf_req_o(smc_scratch_ram_req),
        .scratch_ram_intf_rsp_i(smc_scratch_ram_rsp),
        .l1_icache_tag_intf_req_o(smc_l1_icache_tag_req),
        .l1_icache_tag_intf_rsp_i(smc_l1_icache_tag_rsp),
        .l1_icache_data_intf_req_o(smc_l1_icache_data_req),
        .l1_icache_data_intf_rsp_i(smc_l1_icache_data_rsp),
        .l1_dcache_tag_intf_req_o(smc_l1_dcache_tag_req),
        .l1_dcache_tag_intf_rsp_i(smc_l1_dcache_tag_rsp),
        .l1_dcache_data_intf_req_o(smc_l1_dcache_data_req),
        .l1_dcache_data_intf_rsp_i(smc_l1_dcache_data_rsp),
        // Telemetry ATB: clock/reset async write domain; receiver 0 driven by
        // tb_telemetry0_* (U4-6); receivers 1/2 remain quiet.
        .clk_telemetry_i(clk_smc_i),
        .rst_telemetry_ni(rst_cold_ni),
        .telemetry_atdata_i(tb_telemetry_atdata),
        .telemetry_atid_i(tb_telemetry_atid),
        .telemetry_atready_o(tb_telemetry_atready),
        .telemetry_atvalid_i(tb_telemetry_atvalid),
        .telemetry_afvalid_o(tb_telemetry_afvalid),
        .telemetry_afready_i(tb_telemetry_afready),
        // SPI octal-flash pads (U2-1). Cocotb drives tb_spi_*; idle default is
        // inactive CS/enable (tests that do not touch SPI leave them at 0).
        .spi_enable_i(tb_spi_enable),
        .spi_clk_i(tb_spi_clk),
        .spi_txd_i(tb_spi_txd),
        .spi_cs_n_i(tb_spi_cs_n),
        .spi_cs_oe_n_i(tb_spi_cs_oe_n),
        .spi_cs_ie_n_i(tb_spi_cs_ie_n),
        .spi_clk_ie_n_i(tb_spi_clk_ie_n),
        .spi_clk_oe_n_i(tb_spi_clk_oe_n),
        .spi_dqs_ie_n_i(tb_spi_dqs_ie_n),
        .spi_dqs_oe_n_i(tb_spi_dqs_oe_n),
        .spi_dq_ie_n_i(tb_spi_dq_ie_n),
        .spi_dq_oe_n_i(tb_spi_dq_oe_n),
        .spi_rxd_o(tb_spi_rxd),
        .spi_rxds_o(tb_spi_rxds),
        .spi_mem_rebar_oepad_i(1'b0),
        .spi_mem_rebar_opad_i(1'b0),
        .spi_mem_rebar_iepad_i(1'b0),
        .spi_mem_rebar_ipad_o(tb_spi_mem_rebar_ipad),
        .output_axi_req_o(output_axi_req),
        .output_axi_resp_i(output_axi_resp),
        // I3C controller memories (DAT/DCT/RLT) — see u_i3c_mem below.
        .i3c_dat_mem_src_i(i3c_dat_mem_src),
        .i3c_dat_mem_sink_o(i3c_dat_mem_sink),
        .i3c_dct_mem_src_i(i3c_dct_mem_src),
        .i3c_dct_mem_sink_o(i3c_dct_mem_sink),
        .i3c_rlt_mem_src_i(i3c_rlt_mem_src),
        .i3c_rlt_mem_sink_o(i3c_rlt_mem_sink)
    );

    // I3C DAT/DCT/RLT memories for the real open-source controller (#3934).
    tb_smc_i3c_mem_responder u_i3c_mem (
        .clk_i           (clk_periph_i),
        .rst_ni          (rst_cold_ni),
        .dat_mem_sink_i  (i3c_dat_mem_sink),
        .dat_mem_src_o   (i3c_dat_mem_src),
        .dct_mem_sink_i  (i3c_dct_mem_sink),
        .dct_mem_src_o   (i3c_dct_mem_src),
        .rlt_mem_sink_i  (i3c_rlt_mem_sink),
        .rlt_mem_src_o   (i3c_rlt_mem_src)
    );

    // ------------------------------------------------------------------
    // External peripheral-macro boundary responders (bus terminators).
    //
    // Each macro window in the peripheral AXI-Lite xbar (PLL, PVT, DTP CSR,
    // peripheral extension, adopter-padring GPIO control plane) drives a
    // dedicated smc master port. In real silicon these reach hard macros / the
    // adopter padring; for the OSS bench we terminate each with an AXI-Lite
    // DECERR error slave (returns 0xBADCAB1E).
    //
    // SCOPE: this ONLY completes the AXI-Lite handshake at the SMC boundary.
    // It does NOT reproduce any macro function (PLL locking, PVT sensing, DTP
    // trace, extension I3C, register storage/read-back). What it enables is
    // positive verification of SMC's own responsibility:
    //   * the periph xbar address decode/route is observable
    //     (tb_axil_<macro>_active pulses only for the matching window), and
    //   * a no-responder hang cannot stall the shared CSR master.
    // Macro-internal behaviour belongs to each macro's IP-level DV.
    // ------------------------------------------------------------------
    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH(32),
        .AXI_DATA_WIDTH(32),
        .axil_req_t (smc_axil_32_32_req_t),
        .axil_resp_t(smc_axil_32_32_resp_t)
    ) u_pll_macro_model (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_no),
        .axil_req_i (axil_pll_req),
        .axil_resp_o(axil_pll_resp)
    );

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH(32),
        .AXI_DATA_WIDTH(32),
        .axil_req_t (smc_axil_32_32_req_t),
        .axil_resp_t(smc_axil_32_32_resp_t)
    ) u_pvt_macro_model (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_no),
        .axil_req_i (axil_pvt_req),
        .axil_resp_o(axil_pvt_resp)
    );

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH(32),
        .AXI_DATA_WIDTH(32),
        .axil_req_t (smc_axil_32_32_req_t),
        .axil_resp_t(smc_axil_32_32_resp_t)
    ) u_dtp_csr_macro_model (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_no),
        .axil_req_i (axil_dtp_csr_req),
        .axil_resp_o(axil_dtp_csr_resp)
    );

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH(32),
        .AXI_DATA_WIDTH(32),
        .axil_req_t (smc_axil_32_32_req_t),
        .axil_resp_t(smc_axil_32_32_resp_t)
    ) u_extension_macro_model (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_no),
        .axil_req_i (axil_extension_req),
        .axil_resp_o(axil_extension_resp)
    );

    // Adopter padring GPIO control-plane RW stub (U5). Terminates the
    // smc_padring primary-demux "external" branch (GPIO_CTRL_* /
    // GPIO_REFCLK_CTRL @ 0xC000_4440+). Sparse OKAY storage only — not real
    // padring function. PLL/PVT/extension remain DECERR terminators.
    tb_smc_gpio_ctrl_rw_stub u_gpio_ctrl_rw_stub (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_no),
        .axil_req_i (axil_gpio_ctrl_req),
        .axil_resp_o(axil_gpio_ctrl_resp)
    );

    // U7-5: SEP-style eFuse/OTP behavioral responder (768x32 sticky-OR).
    // Replaces the DECERR bank terminator + combinational fuse-cmd ACK.
    logic [31:0] efuse_prog_fail_seed;
    tb_smc_efuse_responder u_efuse (
        .clk_i               (clk_smc_i),
        .rst_ni              (rst_cold_ni),
        .bank_ctrl_req_i     (axil_efuse_bank_req),
        .bank_ctrl_resp_o    (axil_efuse_bank_resp),
        .fuse_command_req_i  (efuse_cmd_req),
        .fuse_command_resp_o (efuse_cmd_resp),
        .prog_fail_seed_ext_i(efuse_prog_fail_seed),
        .otp_word0_o         (tb_efuse_otp_word0),
        .programmed_word0_o  (tb_efuse_programmed_word0)
    );
    assign efuse_prog_fail_seed = 32'h1bad_f00d;

    // Sense-done + sensed shadow probe (XMR into controller shadow regs).
    assign tb_fuse_sense_done = u_dut.fuse_sense_done_o;
    assign efuse_shadow_probe_o =
        u_dut.u_smc_peripherals.u_smc_efuse_wrapper.u_efuse_interface_controller
            .u_efuse_shadow_regs.shadow_efuse_o;

    assign tb_i2c_debug_lo  = u_dut.i2c_debug[0];
    assign tb_i2c_cg_en     = u_dut.cg_ctrl_i2c_cg_en;
    assign tb_sync_irq      = u_dut.sync_irq_o;
    assign tb_gpio_irq_any  = |u_dut.gpio_interrupt_o;
    assign tb_uart_irq_any  = |u_dut.uart_interrupt_o;
    assign tb_mailbox_irq_any = |u_dut.peripheral_interrupts[7:0];
    assign tb_avsbus_irq = u_dut.peripheral_interrupts[22];
    assign tb_telemetry_irq_any = |u_dut.peripheral_interrupts[10:8];
    assign tb_avsbus_cur_state_debug = u_dut.avsbus_cur_state_debug;

    assign tb_gpio_core2pad_any    = |u_dut.core2pad_o;
    assign tb_gpio_core2pad_en_any = |u_dut.core2pad_en_o;
    assign tb_gpio_pad2core_en_any = |u_dut.pad2core_en_o;

    // Per-interface idle observability — drives Batch B per-module sanity tests.
    assign tb_axil_dtp_csr_active    = axil_dtp_csr_req.aw_valid    | axil_dtp_csr_req.w_valid    | axil_dtp_csr_req.ar_valid;
    assign tb_axil_pll_active        = axil_pll_req.aw_valid        | axil_pll_req.w_valid        | axil_pll_req.ar_valid;
    assign tb_axil_pvt_active        = axil_pvt_req.aw_valid        | axil_pvt_req.w_valid        | axil_pvt_req.ar_valid;
    assign tb_axil_extension_active  = axil_extension_req.aw_valid  | axil_extension_req.w_valid  | axil_extension_req.ar_valid;
    assign tb_axil_efuse_bank_active = axil_efuse_bank_req.aw_valid | axil_efuse_bank_req.w_valid |
                                       axil_efuse_bank_req.ar_valid;
    assign tb_axil_any_master_active = tb_axil_dtp_csr_active | tb_axil_pll_active | tb_axil_pvt_active | tb_axil_extension_active | tb_axil_efuse_bank_active;

    // Hierarchical CPU debug (pre-isolate-clamp PC + boundary isolate).
    assign tb_cpu_wb_pc0 =
        u_dut.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.wb_reg_pc_raw[0];
    assign tb_cpu_cluster_isolate =
        u_dut.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.cluster_boundary_isolate;
    assign tb_cpu_debug_dmactive =
        u_dut.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.debug_dmactive;
    assign tb_cpu_debug_dmactive_ack =
        u_dut.u_smc_cpu_wrapper.gen_4core_cpu.u_smc_cpu.debug_dmactiveAck;

    // U7-2: DFD/DBS fault inject latches a deterministic capture token.
    // Hart0 PC can be X before CPU bring-up, so do not sample hierarchical PC
    // into the public capture port (cocotb cannot int() X).
    always_ff @(posedge clk_smc_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            tb_dbs_capture_valid <= 1'b0;
            tb_dbs_capture_data  <= '0;
        end else if (tb_dfd_fault_inject) begin
            tb_dbs_capture_valid <= 1'b1;
            tb_dbs_capture_data  <= 32'hDB5C_AFE1;
        end
    end

endmodule : smc_uvm_top
