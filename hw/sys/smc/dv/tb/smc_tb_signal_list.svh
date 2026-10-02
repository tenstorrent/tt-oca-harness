// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Single source of truth for the smc_uvm_top TB signals, shared by the
// cocotb and SV-UVM shapes of tb_top.sv. Each signal is declared exactly
// once here and expanded by tb_top.sv into the shape the compile selects:
//
//   * cocotb (default): the ANSI port list -- `SMC_TB_IN*` become
//     `input wire <type>` ports, `SMC_TB_OUT` becomes `output <type>`, each
//     carrying the Verilator public metacomment.
//   * SV-UVM (`UVM` defined): internal TB signals -- every entry becomes a
//     plain `<type> <name>;` declaration, driven/observed by the harness
//     block at the end of tb_top.sv.
//
// Macro grammar (defined and undefined by tb_top.sv, nowhere else):
//   `SMC_TB_IN_FIRST(type, name) -- first list entry only (no leading
//                                   comma in the port-list expansion)
//   `SMC_TB_IN(type, name)       -- TB -> DUT stimulus
//   `SMC_TB_OUT(type, name)      -- DUT -> TB observable
//
// This file is NOT standalone-compilable; it exists only for inclusion
// inside the smc_uvm_top module header.
`SMC_TB_IN_FIRST(logic, clk_smc_i)
`SMC_TB_IN(logic, clk_ref_i)
`SMC_TB_IN(logic, clk_periph_i)

`SMC_TB_IN(logic, powergood_i)
`SMC_TB_IN(logic, rst_cold_ni)
`SMC_TB_IN(logic, rst_cool_ni)

`SMC_TB_OUT(logic, clk_smc_o)
`SMC_TB_OUT(logic, clk_ref_o)
`SMC_TB_OUT(logic, clk_periph_o)

`SMC_TB_OUT(logic, powergood_stable_o)
`SMC_TB_OUT(logic, rst_cold_stable_ref_clk_no)
`SMC_TB_OUT(logic, rst_primary_ref_clk_no)
`SMC_TB_OUT(logic, rst_primary_smc_clk_no)
`SMC_TB_OUT(logic, rst_wdt_smc_clk_no)

`SMC_TB_OUT(logic [3:0], tb_i2c_debug_lo)
`SMC_TB_OUT(logic, tb_i2c_cg_en)
// DMA clock-gating LIVE observability (SMC_DMA_CG_ACTIVITY_TEST).
// Lifted to TB top because smc_public_scope.vlt only publishes smc_uvm_top.
`SMC_TB_OUT(logic, tb_dma_cg_en)
`SMC_TB_OUT(logic, tb_dma_gated_clk)
`SMC_TB_OUT(logic, tb_dma_busy)
`SMC_TB_OUT(logic, tb_dma_frontend_busy)
`SMC_TB_OUT(logic, tb_dma_backend_busy)
// Gater busy_i (frontend_wakeup | backend_busy) — T0 for hyst measure.
`SMC_TB_OUT(logic, tb_dma_gater_busy)
// Zeroer clock-gating LIVE observability + DFT test_en drive.
`SMC_TB_OUT(logic, tb_zeroer_cg_en)
`SMC_TB_OUT(logic, tb_zeroer_gated_axi_clk)
`SMC_TB_OUT(logic, tb_zeroer_gated_reg_clk)
`SMC_TB_OUT(logic, tb_zeroer_busy)
// Zeroer AXI-Lite snoop bus_active — T0 for reg_clk resume / access window.
`SMC_TB_OUT(logic, tb_zeroer_bus_active)
// State-corruption fault injection and fail-closed observability.
`SMC_TB_IN(logic, tb_zeroer_state_inject_en)
`SMC_TB_IN(logic [2:0], tb_zeroer_state_inject)
`SMC_TB_OUT(logic [2:0], tb_zeroer_state)
`SMC_TB_OUT(logic, tb_zeroer_intp)
`SMC_TB_OUT(logic, tb_zeroer_awvalid)
`SMC_TB_OUT(logic, tb_zeroer_wvalid)
`SMC_TB_IN(logic, tb_test_en_i)
`SMC_TB_IN(logic, tb_i2c0_scl_ext_low)
`SMC_TB_IN(logic, tb_i2c0_sda_ext_low)
`SMC_TB_OUT(logic, tb_i2c0_scl)
`SMC_TB_OUT(logic, tb_i2c0_sda)
`SMC_TB_OUT(logic, tb_i2c0_scl_dut_low)
`SMC_TB_OUT(logic, tb_i2c0_sda_dut_low)
// I2C0 SMBALERT#: active-low; pullup-high when DUT OE released.
`SMC_TB_OUT(logic, tb_i2c0_smbalert)
// LSIO enable + controller-side sense (CDC'd). Host traffic must wait until
// enable=1 and scl_i tracks the OD bus, else FMT sits unconsumed.
`SMC_TB_OUT(logic, tb_i2c0_enable)
`SMC_TB_OUT(logic, tb_i2c0_scl_i)
`SMC_TB_OUT(logic, tb_i2c0_sda_i)
`SMC_TB_IN(logic, tb_i3c0_scl_ext_low)
`SMC_TB_IN(logic, tb_i3c0_sda_ext_low)
`SMC_TB_OUT(logic, tb_i3c0_scl)
`SMC_TB_OUT(logic, tb_i3c0_sda)
`SMC_TB_OUT(logic, tb_i3c0_scl_dut_low)
`SMC_TB_OUT(logic, tb_i3c0_sda_dut_low)
`SMC_TB_IN(logic, tb_cpu_jtag_tck)
`SMC_TB_IN(logic, tb_cpu_jtag_tms)
`SMC_TB_IN(logic, tb_cpu_jtag_tdi)
`SMC_TB_IN(logic, tb_cpu_jtag_reset)
`SMC_TB_OUT(logic, tb_cpu_jtag_tdo)

// UART0 pad-level split-port for the P2 Phase A UART loopback:
//   Uart0RxPad (external drive -> DUT input)
//   Uart0TxPad (DUT output -> external observe)
`SMC_TB_IN(logic, tb_uart0_rx_ext_drive)
`SMC_TB_OUT(logic, tb_uart0_tx_from_dut)
// UART0 transmit-FIFO ready as the wrap-0 log engine sees it (low while the
// TX FIFO is full), and the cycles on which that engine holds a fetched byte
// it cannot write because of it: the backpressure the firmware log-write
// scenario claims to run against.
`SMC_TB_OUT(logic, tb_uart0_tx_ready)
`SMC_TB_OUT(logic, tb_uart0_log_write_stalled)

// Telemetry ATB pad lift (U4-6). Cocotb drives beats into telemetry_at*_i per
// receiver. Every stimulus entry here idles at the value the tie-off it
// replaced presented (atdata/atid 0, atvalid 0, afready 1), so a test that
// touches none of them sees the bench it saw before the lift. AFVALID/AFREADY
// stay lifted for receiver 0 only: the flush handshake is not part of what the
// per-receiver decode legs drive.
`SMC_TB_IN(logic [7:0], tb_telemetry0_atdata)
`SMC_TB_IN(logic [6:0], tb_telemetry0_atid)
`SMC_TB_IN(logic, tb_telemetry0_atvalid)
`SMC_TB_OUT(logic, tb_telemetry0_atready)
`SMC_TB_IN(logic, tb_telemetry0_afready)
`SMC_TB_OUT(logic, tb_telemetry0_afvalid)
`SMC_TB_IN(logic [7:0], tb_telemetry1_atdata)
`SMC_TB_IN(logic [6:0], tb_telemetry1_atid)
`SMC_TB_IN(logic, tb_telemetry1_atvalid)
`SMC_TB_OUT(logic, tb_telemetry1_atready)
`SMC_TB_IN(logic [7:0], tb_telemetry2_atdata)
`SMC_TB_IN(logic [6:0], tb_telemetry2_atid)
`SMC_TB_IN(logic, tb_telemetry2_atvalid)
`SMC_TB_OUT(logic, tb_telemetry2_atready)

// SPI octal-flash pad lift (U2-1/U2-2). Cocotb drives tb_spi_* as the
// external SPI host into the padring mux; flash MISO returns via
// tb_spi_miso_ext -> pad2core[0] -> spi_rxd_o[0].
`SMC_TB_IN(logic, tb_spi_enable)
`SMC_TB_IN(logic, tb_spi_clk)
`SMC_TB_IN(logic [7:0], tb_spi_txd)
`SMC_TB_IN(logic, tb_spi_cs_n)
`SMC_TB_IN(logic, tb_spi_cs_oe_n)
`SMC_TB_IN(logic, tb_spi_cs_ie_n)
`SMC_TB_IN(logic, tb_spi_clk_ie_n)
`SMC_TB_IN(logic, tb_spi_clk_oe_n)
`SMC_TB_IN(logic, tb_spi_dqs_ie_n)
`SMC_TB_IN(logic, tb_spi_dqs_oe_n)
`SMC_TB_IN(logic [7:0], tb_spi_dq_ie_n)
`SMC_TB_IN(logic [7:0], tb_spi_dq_oe_n)
// Flash-BFM MISO into pad 0 (DQ0). Driven by OcahSepSpiFlash / cocotb.
`SMC_TB_IN(logic, tb_spi_miso_ext)
`SMC_TB_OUT(logic [7:0], tb_spi_rxd)
`SMC_TB_OUT(logic, tb_spi_rxds)
`SMC_TB_OUT(logic, tb_spi_mem_rebar_ipad)

`SMC_TB_OUT(logic, tb_sync_irq)
`SMC_TB_OUT(logic, tb_gpio_irq_any)
// AXI hang-detector irqs (smc_base combinational OR + per-master).
// Lifted so cocotb can observe irq_test / independence without Force.
`SMC_TB_OUT(logic, tb_axi_hang_irq)
`SMC_TB_OUT(logic, tb_axi_hang_irq_sys)
`SMC_TB_OUT(logic, tb_axi_hang_irq_sep)
`SMC_TB_OUT(logic, tb_axi_hang_irq_data)
// Hang IRQ on its way to the PLIC: the peripheral_interrupts[30] slot in
// smc_peripherals, and the cpu_interrupts bit that is the PLIC source pin
// on u_smc_cpu_wrapper.interrupts_i. PLIC source ID is that bit index + 1.
`SMC_TB_OUT(logic, tb_axi_hang_irq_periph30)
`SMC_TB_OUT(logic, tb_axi_hang_irq_plic_src)
// Boot-stall product pins: pad vs JTAG override mux, sticky processed out.
`SMC_TB_OUT(logic, tb_boot_stall_combined_o)
`SMC_TB_IN(logic, tb_boot_stall_jtag_ovrd_i)
`SMC_TB_IN(logic, tb_boot_stall_jtag_val_i)
// DUT-side BootStallPad sample via smc.pad2core_i (post pad-shim), not
// gpio_pad_io / tb_pad_drive_* echo. Do not XMR-drive pad2core_i — it is
// already driven by smc_ip_integration; this is observe-only.
`SMC_TB_OUT(logic, tb_gpio_pad57)
// SEP WDT reset into SMC (smc_wrapper.sep_wdt_reset_n_i). Idle 1.
`SMC_TB_IN(logic, tb_sep_wdt_reset_n)
// PCIe FLR PF-active (smc_wrapper.cfg_flr_pf_active_i). Idle 0.
// Unique vs rst_cool_ni / smc_flr_sanity cool-reset proxy.
`SMC_TB_IN(logic, tb_cfg_flr_pf_active)
`SMC_TB_OUT(logic [31:0], tb_isolate_req_o)
`SMC_TB_OUT(logic, tb_skip_mem_repair_o)
// Cool-reset output generated by the FLR FSM (reset_unit.rst_cool_no).
`SMC_TB_OUT(logic, tb_rst_cool_from_flr)
// NDM reset handshake (smc_wrapper.ndmreset_*). Width = CPU_CLUSTER_COUNT.
// NDM request lines. Width follows the DV-owned NDM_CLUSTER_COUNT table value
// in cocotb/seq_lib/smc_ndm_reset_test_seq.py, which the test compares the
// DUT's NDMRESET_CLUSTER_COUNT against.
`SMC_TB_IN(logic [3:0], tb_ndmreset_request)
`SMC_TB_OUT(logic [3:0], tb_ndmreset_process)
`SMC_TB_OUT(logic, tb_ndmreset_irq)
`SMC_TB_OUT(logic, tb_uart_irq_any)
// The UART line the PLIC actually sees: smc_peripherals_cdc.sv:309 ORs the
// 16550 IRQ, the UART error line and the log-engine IRQ into one bit per
// instance, and smc_peripherals.sv:1159 routes them to
// peripheral_interrupts[21:18]. `tb_uart_irq_any` above is the 16550 half
// only, so the log engine is not observable through it.
`SMC_TB_OUT(logic [3:0], tb_uart_irq_combined)
// The three I2C instances' PLIC lines (smc_peripherals.sv:1161,
// peripheral_interrupts[25:23]). tb_i2c_cg_en is the clock gate, not the IRQ.
`SMC_TB_OUT(logic [2:0], tb_i2c_irq)
`SMC_TB_OUT(logic, tb_mailbox_irq_any)
`SMC_TB_OUT(logic, tb_avsbus_irq)
`SMC_TB_OUT(logic, tb_telemetry_irq_any)
// eFuse locked-shadow access (smc_peripherals peripheral_interrupts[27]).
`SMC_TB_OUT(logic, tb_efuse_locked_access_irq)
// PVT temperature interrupt. Enters through smc_ext_interrupts_i bus (TB uses bit 1).
// Synced observe is smc_base.ext_interrupts_smc_clk[1]. Idle 0.
`SMC_TB_IN(logic, tb_temp_interrupt_i)
`SMC_TB_OUT(logic, tb_temp_interrupt_irq)
// One bit of product smc_ext_interrupts_i (wrapper width 256). Idle 0.
// Synced observe is smc_base.ext_interrupts_smc_clk[0], not GPIO.
`SMC_TB_IN(logic, tb_ext_interrupt_0_i)
`SMC_TB_OUT(logic, tb_ext_interrupt_0_sync)
// Reset-unit captured GPIO straps (wrapper [63:0]; STRAPS_LO/HI use [60:0]).
// Unique vs GPIO0 IRQ pads (`smc_gpio_irq_active_test`); this pin is strap capture.
`SMC_TB_IN(logic [63:0], tb_captured_straps)
// Subsystem reset-complete pin (prim_sync3 → SS_RESET_COMPLETE CSR). Idle 1.
`SMC_TB_IN(logic [31:0], tb_ss_reset_complete)
// SS0 warm_reset_n from ss_reset_ctrl_o[0] (SW SS_WARM_RESET_N bit 0).
`SMC_TB_OUT(logic, tb_ss0_warm_reset_n)
// Packed jtag_smc_reset_ctrl_t (ovrd[135:68]|val[67:0]). Idle 0.
// Unique vs boot-stall JTAG ovrd and vs rst_cool_ni / cfg_flr_pf_active_i.
`SMC_TB_IN(logic [$bits(jtag_smc_reset_ctrl_t)-1:0], tb_jtag_reset_ctrl)
// DFX STATUS_SMU sticky abort pins. done/success/pass stay tied 1 for
// boot. Idle 0; unique vs ecc_dfd DEBUG_CTRL/BUS_MUX reset reads.
`SMC_TB_IN(logic, tb_mem_repair_abort)
`SMC_TB_IN(logic, tb_mbist_abort)
`SMC_TB_OUT(logic [16:0], tb_avsbus_cur_state_debug)
// Sideband pad observe/drive (U4-4/5): AVS clk/mdata observe, sdata inject,
// OCTS sync/credit observe + dual-chiplet secondary inject (U4-5).
`SMC_TB_OUT(logic, tb_avs_clk_from_dut)
`SMC_TB_OUT(logic, tb_avs_mdata_from_dut)
`SMC_TB_IN(logic, tb_avs_sdata_ext)
`SMC_TB_OUT(logic, tb_octs_sync_load_from_dut)
`SMC_TB_OUT(logic, tb_octs_cnt_credit_from_dut)
// Runtime primary/secondary strap (smc.chiplet_is_primary_i). Default 1.
`SMC_TB_IN(logic, tb_chiplet_is_primary)
// Secondary inject into pads 55/56 (smc_padring OCTS). pad2core enabled
// only when
// chiplet_is_primary_i==0. Idle low when unused.
`SMC_TB_IN(logic, tb_octs_sync_load_ext)
`SMC_TB_IN(logic, tb_octs_cnt_credit_ext)
`SMC_TB_IN(logic [7:0], tb_sep_mailbox_interrupts)
`SMC_TB_IN(logic [smc_pkg::NumGpioWraps-1:0], tb_gpio_ext_drive_en)
`SMC_TB_IN(logic [smc_pkg::NumGpioWraps-1:0], tb_gpio_ext_drive_value)

`SMC_TB_OUT(logic, tb_gpio_core2pad_any)
`SMC_TB_OUT(logic, tb_gpio_core2pad_en_any)
`SMC_TB_OUT(logic, tb_gpio_pad2core_en_any)
// Full pad buses from real smc RTL (smc_wrapper.u_smc). Cocotb cannot XMR
// into u_dut.u_smc under smc_public_scope.vlt (TB-top public only).
`SMC_TB_OUT(logic [smc_pkg::NumGpioWraps-1:0], tb_core2pad_o)
`SMC_TB_OUT(logic [smc_pkg::NumGpioWraps-1:0], tb_core2pad_en_o)
// Per-pad LSIO ownership: a pad an LSIO function selects takes that function's
// direction instead of its INPUT_BY_DEFAULT.
`SMC_TB_OUT(logic [smc_pkg::NumGpioWraps-1:0], tb_lsio_interface_select)
// Per-pad input-buffer enable. gpio.sv drives core2pad_en from the CSRs only
// (its default branch is 1'b0 for every instance) and carries
// INPUT_BY_DEFAULT on pad2core_en, so this is the bus on which the padring's
// default direction map is visible.
`SMC_TB_OUT(logic [smc_pkg::NumGpioWraps-1:0], tb_pad2core_en_o)

// Flat inbound AXI manager driven by cocotbext-axi (prefix s_axi).
// Inbound AXI path for real CSR/fabric traffic.
`SMC_TB_IN(logic [5:0], s_axi_awid)
`SMC_TB_IN(logic [55:0], s_axi_awaddr)
`SMC_TB_IN(logic [7:0], s_axi_awlen)
`SMC_TB_IN(logic [2:0], s_axi_awsize)
`SMC_TB_IN(logic [1:0], s_axi_awburst)
`SMC_TB_IN(logic, s_axi_awlock)
`SMC_TB_IN(logic [3:0], s_axi_awcache)
`SMC_TB_IN(logic [2:0], s_axi_awprot)
`SMC_TB_IN(logic [3:0], s_axi_awqos)
`SMC_TB_IN(logic [3:0], s_axi_awregion)
`SMC_TB_IN(logic [11:0], s_axi_awuser)
`SMC_TB_IN(logic, s_axi_awvalid)
`SMC_TB_OUT(logic, s_axi_awready)

`SMC_TB_IN(logic [63:0], s_axi_wdata)
`SMC_TB_IN(logic [7:0], s_axi_wstrb)
`SMC_TB_IN(logic, s_axi_wlast)
`SMC_TB_IN(logic [11:0], s_axi_wuser)
`SMC_TB_IN(logic, s_axi_wvalid)
`SMC_TB_OUT(logic, s_axi_wready)

`SMC_TB_OUT(logic [5:0], s_axi_bid)
`SMC_TB_OUT(logic [1:0], s_axi_bresp)
`SMC_TB_OUT(logic [11:0], s_axi_buser)
`SMC_TB_OUT(logic, s_axi_bvalid)
`SMC_TB_IN(logic, s_axi_bready)
// TB-owned SEP_IN B-channel hold. It keeps an accepted write response
// outstanding while later AW/W traffic remains available.
`SMC_TB_IN(logic, tb_sep_axi_b_hold)

`SMC_TB_IN(logic [5:0], s_axi_arid)
`SMC_TB_IN(logic [55:0], s_axi_araddr)
`SMC_TB_IN(logic [7:0], s_axi_arlen)
`SMC_TB_IN(logic [2:0], s_axi_arsize)
`SMC_TB_IN(logic [1:0], s_axi_arburst)
`SMC_TB_IN(logic, s_axi_arlock)
`SMC_TB_IN(logic [3:0], s_axi_arcache)
`SMC_TB_IN(logic [2:0], s_axi_arprot)
`SMC_TB_IN(logic [3:0], s_axi_arqos)
`SMC_TB_IN(logic [3:0], s_axi_arregion)
`SMC_TB_IN(logic [11:0], s_axi_aruser)
`SMC_TB_IN(logic, s_axi_arvalid)
`SMC_TB_OUT(logic, s_axi_arready)

`SMC_TB_OUT(logic [5:0], s_axi_rid)
`SMC_TB_OUT(logic [63:0], s_axi_rdata)
`SMC_TB_OUT(logic [1:0], s_axi_rresp)
`SMC_TB_OUT(logic, s_axi_rlast)
`SMC_TB_OUT(logic [11:0], s_axi_ruser)
`SMC_TB_OUT(logic, s_axi_rvalid)
`SMC_TB_IN(logic, s_axi_rready)
// TB-owned SEP_IN R-channel hold. After AR accept, gates DUT-facing
// r_ready and hides r_valid from the VIP so the beat stays outstanding.
// Hang detector snoops the gated handshake (not irq_test). Idle 0.
`SMC_TB_IN(logic, tb_sep_axi_r_hold)
// Consume stale R beats without presenting them to the AXI VIP.
`SMC_TB_IN(logic, tb_sep_axi_r_drop)
`SMC_TB_OUT(logic, tb_sep_axi_r_raw_valid)

// Flat SYS-input AXI manager: SYS_IN reaches the filtered local-fabric path.
`SMC_TB_IN(logic [5:0], sys_axi_awid)
`SMC_TB_IN(logic [55:0], sys_axi_awaddr)
`SMC_TB_IN(logic [7:0], sys_axi_awlen)
`SMC_TB_IN(logic [2:0], sys_axi_awsize)
`SMC_TB_IN(logic [1:0], sys_axi_awburst)
`SMC_TB_IN(logic, sys_axi_awlock)
`SMC_TB_IN(logic [3:0], sys_axi_awcache)
`SMC_TB_IN(logic [2:0], sys_axi_awprot)
`SMC_TB_IN(logic [3:0], sys_axi_awqos)
`SMC_TB_IN(logic [3:0], sys_axi_awregion)
`SMC_TB_IN(logic [11:0], sys_axi_awuser)
`SMC_TB_IN(logic, sys_axi_awvalid)
`SMC_TB_OUT(logic, sys_axi_awready)

`SMC_TB_IN(logic [63:0], sys_axi_wdata)
`SMC_TB_IN(logic [7:0], sys_axi_wstrb)
`SMC_TB_IN(logic, sys_axi_wlast)
`SMC_TB_IN(logic [11:0], sys_axi_wuser)
`SMC_TB_IN(logic, sys_axi_wvalid)
`SMC_TB_OUT(logic, sys_axi_wready)

`SMC_TB_OUT(logic [5:0], sys_axi_bid)
`SMC_TB_OUT(logic [1:0], sys_axi_bresp)
`SMC_TB_OUT(logic [11:0], sys_axi_buser)
`SMC_TB_OUT(logic, sys_axi_bvalid)
`SMC_TB_IN(logic, sys_axi_bready)

`SMC_TB_IN(logic [5:0], sys_axi_arid)
`SMC_TB_IN(logic [55:0], sys_axi_araddr)
`SMC_TB_IN(logic [7:0], sys_axi_arlen)
`SMC_TB_IN(logic [2:0], sys_axi_arsize)
`SMC_TB_IN(logic [1:0], sys_axi_arburst)
`SMC_TB_IN(logic, sys_axi_arlock)
`SMC_TB_IN(logic [3:0], sys_axi_arcache)
`SMC_TB_IN(logic [2:0], sys_axi_arprot)
`SMC_TB_IN(logic [3:0], sys_axi_arqos)
`SMC_TB_IN(logic [3:0], sys_axi_arregion)
`SMC_TB_IN(logic [11:0], sys_axi_aruser)
`SMC_TB_IN(logic, sys_axi_arvalid)
`SMC_TB_OUT(logic, sys_axi_arready)

`SMC_TB_OUT(logic [5:0], sys_axi_rid)
`SMC_TB_OUT(logic [63:0], sys_axi_rdata)
`SMC_TB_OUT(logic [1:0], sys_axi_rresp)
`SMC_TB_OUT(logic, sys_axi_rlast)
`SMC_TB_OUT(logic [11:0], sys_axi_ruser)
`SMC_TB_OUT(logic, sys_axi_rvalid)
`SMC_TB_IN(logic, sys_axi_rready)
// TB-owned SYS_IN R-channel hold. Same product handshake as
// tb_sep_axi_r_hold, on the SYS hang-detector snoop. Idle 0.
`SMC_TB_IN(logic, tb_sys_axi_r_hold)
`SMC_TB_IN(logic, tb_sys_axi_r_drop)
`SMC_TB_OUT(logic, tb_sys_axi_r_raw_valid)

// Flat JTAG AXI manager used by output-fabric final VIP tests.
`SMC_TB_IN(logic [1:0], jtag_axi_awid)
`SMC_TB_IN(logic [55:0], jtag_axi_awaddr)
`SMC_TB_IN(logic [7:0], jtag_axi_awlen)
`SMC_TB_IN(logic [2:0], jtag_axi_awsize)
`SMC_TB_IN(logic [1:0], jtag_axi_awburst)
`SMC_TB_IN(logic, jtag_axi_awlock)
`SMC_TB_IN(logic [3:0], jtag_axi_awcache)
`SMC_TB_IN(logic [2:0], jtag_axi_awprot)
`SMC_TB_IN(logic [3:0], jtag_axi_awqos)
`SMC_TB_IN(logic [3:0], jtag_axi_awregion)
`SMC_TB_IN(logic [11:0], jtag_axi_awuser)
`SMC_TB_IN(logic, jtag_axi_awvalid)
`SMC_TB_OUT(logic, jtag_axi_awready)

`SMC_TB_IN(logic [63:0], jtag_axi_wdata)
`SMC_TB_IN(logic [7:0], jtag_axi_wstrb)
`SMC_TB_IN(logic, jtag_axi_wlast)
`SMC_TB_IN(logic [11:0], jtag_axi_wuser)
`SMC_TB_IN(logic, jtag_axi_wvalid)
`SMC_TB_OUT(logic, jtag_axi_wready)

`SMC_TB_OUT(logic [1:0], jtag_axi_bid)
`SMC_TB_OUT(logic [1:0], jtag_axi_bresp)
`SMC_TB_OUT(logic [11:0], jtag_axi_buser)
`SMC_TB_OUT(logic, jtag_axi_bvalid)
`SMC_TB_IN(logic, jtag_axi_bready)

`SMC_TB_IN(logic [1:0], jtag_axi_arid)
`SMC_TB_IN(logic [55:0], jtag_axi_araddr)
`SMC_TB_IN(logic [7:0], jtag_axi_arlen)
`SMC_TB_IN(logic [2:0], jtag_axi_arsize)
`SMC_TB_IN(logic [1:0], jtag_axi_arburst)
`SMC_TB_IN(logic, jtag_axi_arlock)
`SMC_TB_IN(logic [3:0], jtag_axi_arcache)
`SMC_TB_IN(logic [2:0], jtag_axi_arprot)
`SMC_TB_IN(logic [3:0], jtag_axi_arqos)
`SMC_TB_IN(logic [3:0], jtag_axi_arregion)
`SMC_TB_IN(logic [11:0], jtag_axi_aruser)
`SMC_TB_IN(logic, jtag_axi_arvalid)
`SMC_TB_OUT(logic, jtag_axi_arready)

`SMC_TB_OUT(logic [1:0], jtag_axi_rid)
`SMC_TB_OUT(logic [63:0], jtag_axi_rdata)
`SMC_TB_OUT(logic [1:0], jtag_axi_rresp)
`SMC_TB_OUT(logic, jtag_axi_rlast)
`SMC_TB_OUT(logic [11:0], jtag_axi_ruser)
`SMC_TB_OUT(logic, jtag_axi_rvalid)
`SMC_TB_IN(logic, jtag_axi_rready)

// Per-interface AXI-Lite idle observability (OR of aw_valid/w_valid/ar_valid
// on each of the SMC downstream AXI-Lite master interfaces).
`SMC_TB_OUT(logic, tb_axil_dtp_csr_active)
`SMC_TB_OUT(logic, tb_axil_external_active)
// The adopter external port's request addresses with their valids, so a probe
// can tie the port activity it sees to the address it issued.
`SMC_TB_OUT(logic, tb_axil_external_arvalid)
`SMC_TB_OUT(logic [smc_pkg::SmcLocalAddrWidth-1:0], tb_axil_external_araddr)
`SMC_TB_OUT(logic, tb_axil_external_awvalid)
`SMC_TB_OUT(logic [smc_pkg::SmcLocalAddrWidth-1:0], tb_axil_external_awaddr)
`SMC_TB_OUT(logic, tb_axil_efuse_bank_active)
`SMC_TB_OUT(logic, tb_axil_any_master_active)

// Output-fabric observability (U6-2). SLVERR on this boundary comes from
// the SYS_OUT slave agent's fault programming, not a DUT Force / starve knob.
`SMC_TB_OUT(logic [31:0], tb_output_axi_write_count)
`SMC_TB_OUT(logic [31:0], tb_output_axi_read_count)
`SMC_TB_OUT(logic [55:0], tb_output_axi_last_addr)
`SMC_TB_OUT(logic [63:0], tb_output_axi_last_wdata)
// U6-2: SYS_OUT AXI slave response handshake for SmcOutputAxiMonitor.
`SMC_TB_OUT(logic, tb_output_axi_bvalid)
`SMC_TB_OUT(logic, tb_output_axi_bready)
`SMC_TB_OUT(logic [1:0], tb_output_axi_bresp)
`SMC_TB_OUT(logic, tb_output_axi_rvalid)
`SMC_TB_OUT(logic, tb_output_axi_rready)
`SMC_TB_OUT(logic [1:0], tb_output_axi_rresp)
`SMC_TB_OUT(logic [55:0], tb_output_axi_awaddr)
`SMC_TB_OUT(logic, tb_output_axi_awvalid)
`SMC_TB_OUT(logic, tb_output_axi_awready)
`SMC_TB_OUT(logic [55:0], tb_output_axi_araddr)
`SMC_TB_OUT(logic, tb_output_axi_arvalid)
`SMC_TB_OUT(logic, tb_output_axi_arready)
`SMC_TB_OUT(logic [63:0], tb_output_axi_wdata)
`SMC_TB_OUT(logic, tb_output_axi_wvalid)
`SMC_TB_OUT(logic, tb_output_axi_wready)
// TB-owned SYS_OUT R/B hold. After AW/AR accept, hides r_valid/b_valid
// from the DUT and hides r_ready/b_ready from the responder so the beat
// stays outstanding. DATA hang detector snoops data_accel (DMA/zeroer
// master), which stalls when SYS_OUT never completes. Idle 0.
`SMC_TB_IN(logic, tb_output_axi_resp_hold)

// CPU memory responder observability for firmware boot tests.
`SMC_TB_OUT(logic [31:0], tb_cpu_rom_read_count)
`SMC_TB_OUT(logic [31:0], tb_cpu_scratch_read_count)
`SMC_TB_OUT(logic [chipyard_4core_mem_pkg::NumSramBanks*32-1:0], tb_cpu_scratch_bank_read_count)
`SMC_TB_OUT(logic [31:0], tb_cpu_scratch_write_count)
`SMC_TB_OUT(logic [31:0], tb_cpu_fw_mailbox)
`SMC_TB_OUT(logic, tb_cpu_fw_mailbox_valid)
`SMC_TB_OUT(logic [31:0], tb_cpu_dcache_write_count)
`SMC_TB_OUT(logic [57:0], tb_cpu_wb_pc0)
// The other three harts' retired PCs. crt0 calls __metal_synchronize_harts
// before main() on every sram image, so hart 0 stalling in that barrier and
// hart 0 never being released look identical through tb_cpu_wb_pc0 alone.
`SMC_TB_OUT(logic [57:0], tb_cpu_wb_pc1)
`SMC_TB_OUT(logic [57:0], tb_cpu_wb_pc2)
`SMC_TB_OUT(logic [57:0], tb_cpu_wb_pc3)
// Per-core trap cause and trapped PC, straight off each Rocket CSR file. The
// retired PC alone cannot tell a trap from a stall: a firmware image parked in
// crt0's fault loop and one that simply stopped fetching look the same.
// mcause[63] is the interrupt bit, the low bits the exception code.
`SMC_TB_OUT(logic [63:0], tb_cpu_mcause0)
`SMC_TB_OUT(logic [63:0], tb_cpu_mcause1)
`SMC_TB_OUT(logic [63:0], tb_cpu_mcause2)
`SMC_TB_OUT(logic [63:0], tb_cpu_mcause3)
`SMC_TB_OUT(logic [57:0], tb_cpu_mepc0)
`SMC_TB_OUT(logic [57:0], tb_cpu_mepc1)
`SMC_TB_OUT(logic [57:0], tb_cpu_mepc2)
`SMC_TB_OUT(logic [57:0], tb_cpu_mepc3)
`SMC_TB_OUT(logic, tb_cpu_cluster_isolate)
// CPU timeout-reset / AXI-isolate recovery observability. These are passive
// lifts only; tests create stalls with the existing public hold controls.
`SMC_TB_OUT(logic, tb_cpu_isolate_req)
`SMC_TB_OUT(logic, tb_cpu_drained)
`SMC_TB_OUT(logic, tb_cpu_reset_timeout)
`SMC_TB_OUT(logic, tb_cpu_reset_applied)
`SMC_TB_OUT(logic, tb_cpu_uncore_reset_n)
`SMC_TB_OUT(logic, tb_cpu_l2_isolated)
`SMC_TB_OUT(logic [3:0], tb_cpu_l2_pending_aw)
`SMC_TB_OUT(logic [3:0], tb_cpu_l2_pending_w)
`SMC_TB_OUT(logic [3:0], tb_cpu_l2_pending_ar)
`SMC_TB_OUT(logic, tb_cpu_l2_flush_active)
`SMC_TB_OUT(logic, tb_cpu_mmio_isolated)
`SMC_TB_OUT(logic [3:0], tb_cpu_mmio_pending_aw)
`SMC_TB_OUT(logic [3:0], tb_cpu_mmio_pending_w)
`SMC_TB_OUT(logic [3:0], tb_cpu_mmio_pending_ar)
`SMC_TB_OUT(logic, tb_cpu_mmio_flush_active)
// U7-3: Rocket DM active + ack after dmcontrol.dmactive write.
`SMC_TB_OUT(logic, tb_cpu_debug_dmactive)
`SMC_TB_OUT(logic, tb_cpu_debug_dmactive_ack)
// Hart 0 retirement record from the Rocket CSR trace bundle, and the core
// reset that masks it: the writeback registers behind the bundle have no
// reset, so the fields hold X in a four-state simulator until the core runs.
// Consumer: cocotb/env/smc_cpu_trace_monitor.py.
`SMC_TB_OUT(logic, tb_cpu_core_reset_n)
`SMC_TB_OUT(logic, tb_cpu_trace_valid)
// The same retire valid and PC without the core-reset mask, for the leaf that
// orders the first retire against the core reset release: a retire the mask
// would hide is exactly what that leaf has to be able to see.
`SMC_TB_OUT(logic, tb_cpu_trace_valid_unmasked)
`SMC_TB_OUT(logic [57:0], tb_cpu_trace_pc_unmasked)
`SMC_TB_OUT(logic [57:0], tb_cpu_trace_pc)
`SMC_TB_OUT(logic [31:0], tb_cpu_trace_insn)
`SMC_TB_OUT(logic, tb_cpu_trace_exc)
`SMC_TB_OUT(logic [63:0], tb_cpu_trace_cause)
`SMC_TB_OUT(logic [57:0], tb_cpu_trace_tval)
// Scratch 2 is the firmware virtual console (smc_scratchpad.h
// SMC_SCRATCH_SIM_VIRT_CONSOLE); cocotb/env/smc_virt_console.py decodes it.
`SMC_TB_OUT(logic [31:0], tb_cpu_scratch2)

// U7-1: ECC SBE/DBE inject into scratch bank0 reads + fire count.
// fire_count tracks DUT cpu_scratch0_inject_fire only (real bank0 reads
// with inject armed). tb_cpu_ecc_inject_probe is part of the cocotb pin
// surface and is not scored.
`SMC_TB_IN(logic, tb_cpu_ecc_inject_sbe)
`SMC_TB_IN(logic, tb_cpu_ecc_inject_dbe)
`SMC_TB_IN(logic, tb_cpu_ecc_inject_probe)
// Scratch codeword poke: XOR mask into bank0 entry on a rising poke_en.
// One bit is a correctable error, two are not.
`SMC_TB_IN(logic, tb_cpu_ecc_poke_en)
`SMC_TB_IN(logic [31:0], tb_cpu_ecc_poke_entry)
`SMC_TB_IN(logic [1:0], tb_cpu_ecc_poke_mask)
// CPU cluster double-error detect (live + sticky).
`SMC_TB_OUT(logic, tb_cluster_ded)
`SMC_TB_OUT(logic, tb_cluster_ded_seen)
// Cluster WDT first / second timeout pins (live + sticky).
`SMC_TB_OUT(logic, tb_wdt_first_timeout)
`SMC_TB_OUT(logic, tb_wdt_first_timeout_seen)
`SMC_TB_OUT(logic, tb_wdt_second_timeout)
`SMC_TB_OUT(logic, tb_wdt_second_timeout_seen)
`SMC_TB_OUT(logic [31:0], tb_cpu_ecc_inject_fire_count)
`SMC_TB_OUT(logic, tb_cpu_scratch0_inject_fire)

// U7-2: DFD/DBS fault inject + debug-bus capture latch.
`SMC_TB_IN(logic, tb_dfd_fault_inject)
`SMC_TB_OUT(logic, tb_dbs_capture_valid)
`SMC_TB_OUT(logic [31:0], tb_dbs_capture_data)

// U7-5: eFuse behavioral responder observability.
`SMC_TB_OUT(logic, tb_fuse_sense_done)
// Warm-reset domain release (feeds SCRATCH_COLD_WARM etc.). Wait on this —
// not only tb_fuse_sense_done — before warm-domain CSR traffic.
`SMC_TB_OUT(logic, tb_fuse_reset_n)
`SMC_TB_OUT(logic, tb_rst_warm_smc_clk_n)
`SMC_TB_OUT(logic [31:0], tb_efuse_otp_word0)
`SMC_TB_OUT(logic [31:0], tb_efuse_programmed_word0)
`SMC_TB_IN(logic, tb_efuse_program_state_inject_en)
`SMC_TB_IN(logic [1:0], tb_efuse_program_state_inject)
`SMC_TB_OUT(logic [1:0], tb_efuse_program_state)
`SMC_TB_OUT(logic, tb_efuse_program_req_valid)
`SMC_TB_OUT(logic, tb_efuse_program_busy)
`SMC_TB_OUT(logic, tb_efuse_program_done)
`SMC_TB_OUT(logic, tb_efuse_program_error)
`SMC_TB_OUT(logic [31:0], tb_efuse_program_readback)
`SMC_TB_IN(logic, tb_efuse_read_state_inject_en)
`SMC_TB_IN(logic [1:0], tb_efuse_read_state_inject)
`SMC_TB_IN(logic [1:0], tb_efuse_read_error_inject)
`SMC_TB_OUT(logic [1:0], tb_efuse_read_state)
`SMC_TB_OUT(logic, tb_efuse_read_req_valid)
`SMC_TB_OUT(logic, tb_efuse_read_busy)
`SMC_TB_OUT(logic, tb_efuse_read_done)
`SMC_TB_OUT(logic, tb_efuse_read_error)
`SMC_TB_OUT(logic [31:0], tb_efuse_readback)
`SMC_TB_OUT(logic [15:0], tb_efuse_read_addr)
`SMC_TB_OUT(logic [15:0], tb_efuse_program_addr)
`SMC_TB_OUT(logic [smc_efuse_pkg::NumEfuseBits-1:0], efuse_shadow_probe_o)

// P2-15: drive product lc_state_i directly (diff {n,p}). No Force /
// no TB encode helper — tests pack complementary or illegal encodings.
`SMC_TB_IN(logic [2*smc_pkg::LcStateWidth-1:0], tb_lc_state)

// JTAG-side eFuse AXI-Lite master (cocotbext-axi AxiLiteMaster, prefix ej_axi)
// into smc.axil_smc_otp_jtag_req_i (SMC-OTP JTAG access-control path).
`SMC_TB_IN(logic [31:0], ej_axi_awaddr)
`SMC_TB_IN(logic [2:0], ej_axi_awprot)
`SMC_TB_IN(logic, ej_axi_awvalid)
`SMC_TB_OUT(logic, ej_axi_awready)
`SMC_TB_IN(logic [31:0], ej_axi_wdata)
`SMC_TB_IN(logic [3:0], ej_axi_wstrb)
`SMC_TB_IN(logic, ej_axi_wvalid)
`SMC_TB_OUT(logic, ej_axi_wready)
`SMC_TB_OUT(logic [1:0], ej_axi_bresp)
`SMC_TB_OUT(logic, ej_axi_bvalid)
`SMC_TB_IN(logic, ej_axi_bready)
`SMC_TB_IN(logic [31:0], ej_axi_araddr)
`SMC_TB_IN(logic [2:0], ej_axi_arprot)
`SMC_TB_IN(logic, ej_axi_arvalid)
`SMC_TB_OUT(logic, ej_axi_arready)
`SMC_TB_OUT(logic [31:0], ej_axi_rdata)
`SMC_TB_OUT(logic [1:0], ej_axi_rresp)
`SMC_TB_OUT(logic, ej_axi_rvalid)
`SMC_TB_IN(logic, ej_axi_rready)

// ------------------------------------------------------------------
// P1 interrupt-vector observability. The interrupt chapters name a bit index
// per source, and nothing published the vectors those indices live in: the
// per-source scalars above are hand-picked slices. These are the whole buses.
// ------------------------------------------------------------------
`SMC_TB_OUT(logic [smc_4core_cpu_pkg::NumCpuInterrupts-1:0], tb_cpu_interrupts)
`SMC_TB_OUT(logic [31:0], tb_peripheral_interrupts)
`SMC_TB_OUT(logic [31:0], tb_mailbox_interrupts)
`SMC_TB_OUT(logic [31:0], tb_ext_mailbox_interrupts)
`SMC_TB_OUT(logic [smc_pkg::NumGpioWraps-1:0], tb_gpio_interrupt)
`SMC_TB_OUT(logic [3:0], tb_ndmreset_request_sync)
// The three contributors the combined UART bit ORs together, before the OR.
`SMC_TB_OUT(logic [3:0], tb_uart_irq_raw)
`SMC_TB_OUT(logic [3:0], tb_uart_err_raw)
`SMC_TB_OUT(logic [3:0], tb_logengine_irq_raw)
`SMC_TB_OUT(logic [2:0], tb_telemetry_irq)
`SMC_TB_OUT(logic, tb_sep_wdt_irq_sync)
`SMC_TB_OUT(logic, tb_cla_interrupt)
// The CLA clock-stop status and the term behind it. The status output is
// ANDed with tdr_dbg_ctrl_clock_stop_en_i, which this tb ties low.
`SMC_TB_OUT(logic, tb_cla_clock_stop)
`SMC_TB_OUT(logic, tb_cla_halt_clock_global)
`SMC_TB_OUT(logic, tb_dma_intp)

// PLIC state. Context 2N is hart N machine-mode, 2N+1 supervisor-mode.
`SMC_TB_OUT(logic [3:0], tb_plic_meip)
`SMC_TB_OUT(logic [3:0], tb_plic_seip)
`SMC_TB_OUT(logic [2:0], tb_plic_threshold0)
`SMC_TB_OUT(logic [8:0], tb_plic_maxdev0)
`SMC_TB_OUT(logic [6:0], tb_plic_enables0_w0)
`SMC_TB_OUT(logic, tb_plic_claim0)
`SMC_TB_OUT(logic, tb_plic_complete0)
`SMC_TB_OUT(logic [8:0], tb_plic_completer_dev)
`SMC_TB_OUT(logic [2:0], tb_plic_pending_low)
`SMC_TB_OUT(logic [2:0], tb_plic_priority_low)
// Source index 331 is the fourth cluster-internal watchdog: a PLIC source
// with no cpu_interrupts bit behind it.
`SMC_TB_OUT(logic, tb_plic_pending_331)
// Source 324 is the zeroer completion bit (cpu_interrupts[323]) at the PLIC.
`SMC_TB_OUT(logic, tb_plic_pending_324)

// CLINT. MTIMECMP is `pad`/`pad_N` in the generated cluster.
`SMC_TB_OUT(logic [63:0], tb_clint_mtime)
`SMC_TB_OUT(logic [63:0], tb_clint_mtimecmp0)
`SMC_TB_OUT(logic [63:0], tb_clint_mtimecmp1)
`SMC_TB_OUT(logic [3:0], tb_clint_msip)
`SMC_TB_OUT(logic [3:0], tb_clint_mtip)
// Per-core direct pins, read at the core boundary rather than at the CLINT.
`SMC_TB_OUT(logic [3:0], tb_core_mtip)
`SMC_TB_OUT(logic [3:0], tb_core_msip)
`SMC_TB_OUT(logic [3:0], tb_core_meip)
`SMC_TB_OUT(logic [3:0], tb_core_buserror)

// ------------------------------------------------------------------
// P1 DMA stream-0 command registers and the master port a transfer moves on.
// ------------------------------------------------------------------
`SMC_TB_OUT(logic, tb_dma_next_id_re)
`SMC_TB_OUT(logic [31:0], tb_dma_next_id)
`SMC_TB_OUT(logic [9:0], tb_dma_status0)
`SMC_TB_OUT(logic [31:0], tb_dma_done_id)
`SMC_TB_OUT(logic [63:0], tb_dma_src_addr)
`SMC_TB_OUT(logic [63:0], tb_dma_dst_addr)
`SMC_TB_OUT(logic [63:0], tb_dma_length)
`SMC_TB_OUT(logic [63:0], tb_dma_reps)
`SMC_TB_OUT(logic, tb_dma_done_id_re)
`SMC_TB_OUT(logic, tb_dma_fe_req_valid)
`SMC_TB_OUT(logic, tb_dma_fe_req_ready)
`SMC_TB_OUT(logic, tb_dma_trans_complete)
`SMC_TB_OUT(logic, tb_dma_frontend_wakeup)
`SMC_TB_OUT(logic, tb_dma_frontend_gated_clk)
`SMC_TB_OUT(logic, tb_dma_mst_awvalid)
`SMC_TB_OUT(logic, tb_dma_mst_awready)
`SMC_TB_OUT(logic [55:0], tb_dma_mst_awaddr)
`SMC_TB_OUT(logic [7:0], tb_dma_mst_awlen)
`SMC_TB_OUT(logic, tb_dma_mst_wvalid)
`SMC_TB_OUT(logic, tb_dma_mst_wready)
`SMC_TB_OUT(logic, tb_dma_mst_wlast)
`SMC_TB_OUT(logic [7:0], tb_dma_mst_wstrb)
`SMC_TB_OUT(logic [63:0], tb_dma_mst_wdata)
`SMC_TB_OUT(logic, tb_dma_mst_bvalid)

// Zeroer master port, outstanding counter and command registers.
`SMC_TB_OUT(logic, tb_zeroer_awready)
`SMC_TB_OUT(logic [55:0], tb_zeroer_awaddr)
`SMC_TB_OUT(logic [7:0], tb_zeroer_awlen)
`SMC_TB_OUT(logic, tb_zeroer_wready)
`SMC_TB_OUT(logic, tb_zeroer_wlast)
`SMC_TB_OUT(logic [7:0], tb_zeroer_wstrb)
`SMC_TB_OUT(logic [63:0], tb_zeroer_wdata)
`SMC_TB_OUT(logic, tb_zeroer_bvalid)
`SMC_TB_OUT(logic [31:0], tb_zeroer_outstanding)
`SMC_TB_OUT(logic [63:0], tb_zeroer_dest_addr)
`SMC_TB_OUT(logic [63:0], tb_zeroer_size)
`SMC_TB_OUT(logic, tb_zeroer_trigger)
`SMC_TB_OUT(logic, tb_zeroer_status_read)
`SMC_TB_OUT(logic, tb_zeroer_strb_dest)
`SMC_TB_OUT(logic, tb_zeroer_strb_size)
`SMC_TB_OUT(logic, tb_zeroer_req_is_wr)
`SMC_TB_OUT(logic, tb_zeroer_disable_cg)
`SMC_TB_OUT(logic, tb_zeroer_axi_clk_enable)

// GPIO wrap 0 AXI-Lite protection filter: the requirement, the enables and
// the prot the request actually carried.
`SMC_TB_OUT(logic, tb_gpio0_awvalid)
`SMC_TB_OUT(logic, tb_gpio0_arvalid)
`SMC_TB_OUT(logic [2:0], tb_gpio0_awprot)
`SMC_TB_OUT(logic [2:0], tb_gpio0_arprot)
`SMC_TB_OUT(logic [2:0], tb_gpio0_awprot_req)
`SMC_TB_OUT(logic [2:0], tb_gpio0_arprot_req)
`SMC_TB_OUT(logic, tb_gpio0_wr_filter_en)
`SMC_TB_OUT(logic, tb_gpio0_rd_filter_en)

// Inbound fabric filter decisions and the JTAG alias-remap hit debug.
`SMC_TB_OUT(logic [15:0], tb_inb_write_hit)
`SMC_TB_OUT(logic [15:0], tb_inb_read_hit)
`SMC_TB_OUT(logic, tb_inb_isolate_write)
`SMC_TB_OUT(logic, tb_inb_isolate_read)
`SMC_TB_OUT(logic [2:0], tb_remap_jtag_aw_hit)
`SMC_TB_OUT(logic [2:0], tb_remap_jtag_ar_hit)

// Isolation / FLR sequencing state.
`SMC_TB_OUT(logic [31:0], tb_isolate_req_reg)
`SMC_TB_OUT(logic [31:0], tb_isolate_req_smcen_reg)
`SMC_TB_OUT(logic, tb_isolate_req_smc_reg)
`SMC_TB_OUT(logic, tb_flr_sync_ref)
`SMC_TB_OUT(logic, tb_flr_posedge_ref)
`SMC_TB_OUT(logic [1:0], tb_flr_counter_state)

// Peripherals: ATB per receiver, I2C mode enables, mailbox 0 FIFO levels,
// the UART TX lines and one AXI-Lite CDC bridge on its peripheral-clock side.
`SMC_TB_OUT(logic [2:0], tb_telem_atvalid)
`SMC_TB_OUT(logic [2:0], tb_telem_atready)
`SMC_TB_OUT(logic [6:0], tb_telem_atid0)
`SMC_TB_OUT(logic [6:0], tb_telem_atid1)
`SMC_TB_OUT(logic [6:0], tb_telem_atid2)
`SMC_TB_OUT(logic [2:0], tb_i2c_host_enable)
`SMC_TB_OUT(logic [2:0], tb_i2c_target_enable)
`SMC_TB_OUT(logic [1:0], tb_mbx0_full)
`SMC_TB_OUT(logic [1:0], tb_mbx0_empty)
`SMC_TB_OUT(logic [3:0], tb_uart_tx)
`SMC_TB_OUT(logic, tb_periph_cdc_awvalid)
`SMC_TB_OUT(logic, tb_periph_cdc_awready)
`SMC_TB_OUT(logic, tb_periph_cdc_wvalid)
`SMC_TB_OUT(logic, tb_periph_cdc_bvalid)
`SMC_TB_OUT(logic, tb_periph_cdc_arvalid)
`SMC_TB_OUT(logic, tb_periph_cdc_arready)
`SMC_TB_OUT(logic, tb_periph_cdc_rvalid)

// eFuse bank-control AXI-Lite port and the SHIM command handshake.
`SMC_TB_OUT(logic, tb_efuse_bank_awvalid)
`SMC_TB_OUT(logic, tb_efuse_bank_wvalid)
`SMC_TB_OUT(logic, tb_efuse_bank_arvalid)
`SMC_TB_OUT(logic, tb_efuse_bank_bvalid)
`SMC_TB_OUT(logic, tb_efuse_bank_rvalid)
`SMC_TB_OUT(logic, tb_efuse_shim_cmd_valid)
`SMC_TB_OUT(logic, tb_efuse_shim_resp_valid)
`SMC_TB_OUT(logic, tb_efuse_shim_resp_status)
`SMC_TB_OUT(logic [63:0], tb_efuse_locks)

// ------------------------------------------------------------------
// Elaboration aliases: optional observe ports for the bring-up smoke
// (SmcWrapperElaborationSeq). Bare SmcEnv tests never touch these.
// ------------------------------------------------------------------
`SMC_TB_OUT(logic, dut_present_o)
`SMC_TB_OUT(logic, powergood_o)
`SMC_TB_OUT(logic, rst_cold_n_o)
`SMC_TB_OUT(logic, smc_reset_n_o)
`SMC_TB_OUT(logic, smc_fuse_sense_done_o)
`SMC_TB_OUT(logic, smc_init_mem_done_o)
`SMC_TB_OUT(logic [31:0], smc_scratch_0_o)
`SMC_TB_OUT(logic, smc_test_pass_o)
`SMC_TB_OUT(logic, smc_test_fail_o)
`SMC_TB_OUT(logic [31:0], output_axi_write_count_o)
`SMC_TB_OUT(logic [31:0], output_axi_read_count_o)
