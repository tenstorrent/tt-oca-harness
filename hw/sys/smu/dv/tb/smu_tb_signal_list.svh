// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Single source of truth for the smu_uvm_top TB signals, shared by the
// cocotb and SV-UVM shapes of tb_top.sv. Each signal is declared exactly
// once here and expanded by tb_top.sv into the shape the compile selects:
//
//   * cocotb (default): the ANSI port list -- `SMU_TB_IN*` become
//     `input wire <type>` ports, `SMU_TB_OUT` becomes `output <type>`, each
//     carrying the Verilator public metacomment.
//   * SV-UVM (`UVM` defined): internal TB signals -- every entry becomes a
//     plain `<type> <name>;` declaration, driven/observed by the harness
//     block at the end of tb_top.sv.
//
// Macro grammar (defined and undefined by tb_top.sv, nowhere else):
//   `SMU_TB_IN_FIRST(type, name) -- first list entry only (no leading
//                                   comma in the port-list expansion)
//   `SMU_TB_IN(type, name)       -- TB -> DUT stimulus
//   `SMU_TB_OUT(type, name)      -- DUT -> TB observable
//
// This file is NOT standalone-compilable; it exists only for inclusion
// inside the smu_uvm_top module header. The cocotb catalog (cocotb/) drives
// and samples these names; keep them stable.
`SMU_TB_IN_FIRST(logic, clk_smu_i)
`SMU_TB_IN(logic, clk_ref_i)
`SMU_TB_IN(logic, clk_periph_i)
`SMU_TB_IN(logic, rst_cold_ni)
`SMU_TB_IN(logic, powergood_i)
// External boot-sequence done gate (SMU_006); default-drive 1'b1 in base bring-up
`SMU_TB_IN(logic, ext_boot_seq_done_i)

// Primary JTAG TAP (cocotb OcahJtagMasterDriver / SV-UVM ocah_jtag_if)
`SMU_TB_IN(logic, jtag_tck)
`SMU_TB_IN(logic, jtag_tms)
`SMU_TB_IN(logic, jtag_trst)  // active-low
`SMU_TB_IN(logic, jtag_tdi)
`SMU_TB_OUT(logic, jtag_tdo)
`SMU_TB_OUT(logic, jtag_tdo_oen)

// Reset / SEP=0 observables (real checkers)
`SMU_TB_OUT(logic, rst_cold_stable_ref_clk_no)
`SMU_TB_OUT(logic, rst_primary_ref_clk_no)
`SMU_TB_OUT(logic, rst_primary_smc_clk_no)
`SMU_TB_OUT(logic, rst_primary_periph_clk_no)
`SMU_TB_OUT(logic [55:0], sep_global_base_o)
`SMU_TB_OUT(logic [55:0], sep_region_size_o)
`SMU_TB_OUT(logic [55:0], smc_global_base_o)
`SMU_TB_OUT(logic [31:0], smc_region_size_o)
`SMU_TB_OUT(logic, smc_init_mem_done_o)
`SMU_TB_OUT(logic, smc_fuse_sense_done_o)
`SMU_TB_OUT(logic, smc_fuse_reset_n_delayed_o)
// DTP DEBUG_CONTROL -> SMC boot-stall (hierarchical observe)
`SMU_TB_OUT(logic, jtag_boot_stall_ovrd)
`SMU_TB_OUT(logic, jtag_boot_stall)
// IC_RESET observables (DTP override)
`SMU_TB_OUT(logic, jtag_ic_reset_ext_ovrd)
`SMU_TB_OUT(logic, jtag_ic_reset_ext_ctrl_n)
`SMU_TB_OUT(logic, jtag_ic_reset_smc_ovrd)
`SMU_TB_OUT(logic, jtag_ic_reset_smc_ctrl_n)
// Cross-trigger CTM loopback ports (cocotb drives dst_req)
`SMU_TB_IN(logic [7:0], xtrig_ctm_dst_req)
`SMU_TB_OUT(logic [7:0], xtrig_ctm_dst_ack)
`SMU_TB_OUT(logic [7:0], xtrig_ctm_src_req)
`SMU_TB_IN(logic [7:0], xtrig_ctm_src_ack)
// Clock-stop coordination
`SMU_TB_IN(logic [7:0], xtrig_clk_stop_req)
`SMU_TB_OUT(logic, dtp_stop_clks_o)
`SMU_TB_OUT(logic, dtp_cla_clock_stop_en)
// Lifecycle / demote (SEP=0 defaults)
`SMU_TB_OUT(logic [7:0], lc_state_o)
`SMU_TB_OUT(logic, lc_sigint_err_o)
`SMU_TB_OUT(logic [1:0], lcc_demote_state_1_o)
`SMU_TB_OUT(logic [1:0], lcc_demote_state_2_o)
// GPIO boot-stall pad bit[57] drive (OR'd into pad2core; Verilator-safe)
`SMU_TB_IN(logic, gpio_boot_stall_drive_i)
// Width tracks the DUT port (smu.sv smc_ext_mailbox_interrupts_o) and mbx_irqs.
`SMU_TB_OUT(logic [smc_pkg::NUM_MAILBOXES-1:0], ext_mailbox_interrupts)
`SMU_TB_OUT(logic [31:0], jtag_ptap_state)
`SMU_TB_OUT(logic [31:0], jtag_ptap_inst_decoded)

// Macro AXI-Lite activity (OR of aw/w/ar valid on the boundary master).
// PLL, PVT and the extension slot share the single smc_external window.
`SMU_TB_OUT(logic, tb_axil_external_active)

// WDT first-timeout pin observe (ChipYard rst export; clamped under isolate)
`SMU_TB_OUT(logic, tb_wdt_first_timeout)
// Pre-clamp observe only (no TB Force inject -- policy: real RTL / fail test)
`SMU_TB_OUT(logic, tb_wdt_reset_raw)
`SMU_TB_OUT(logic, tb_cluster_boundary_isolate)

// OCTS timer count pin observe
`SMU_TB_OUT(logic [63:0], tb_timer_count)
// IO STAP host TCK observe (DTP-IO-STAP; chiplet-to-chiplet TAP fanout)
`SMU_TB_OUT(logic, tb_stap_io_tck)
// SMC STAP host observe (internal DTP->SMC CPU JTAG; not a top-level SMU port)
`SMU_TB_OUT(logic, tb_stap_smc_tck)
`SMU_TB_OUT(logic, tb_stap_smc_trst_n)
`SMU_TB_OUT(logic, tb_stap_smc_tdi)
`SMU_TB_OUT(logic, tb_stap_smc_tms)
// Select-gated: host_tdo_oen = stap_sel && shift_en (observe DTP port; SMU wire is unused)
`SMU_TB_OUT(logic, tb_stap_smc_tdo_oen)
// BSR scan_ctrl.select (instruction-gated; TCK fans out on any DR)
`SMU_TB_OUT(logic, tb_bsr_select)
// SMC OTP JTAG2AXI gate (feat_ctrl fuse_test && soc && ap; SEP=0 ties open)
`SMU_TB_OUT(logic, tb_otp_jtag2axi_security_disable)
// SMC fabric JTAG2AXI gate (feat_ctrl soc && ap; SEP=0 ties open)
`SMU_TB_OUT(logic, tb_smc_jtag2axi_security_disable)

// Telemetry ATB channel-0 drive / observe (receivers 1..N stay idle)
`SMU_TB_IN(logic [7:0], tb_tel_atdata)
`SMU_TB_IN(logic [6:0], tb_tel_atid)
`SMU_TB_IN(logic, tb_tel_atvalid)
`SMU_TB_IN(logic, tb_tel_afready)
`SMU_TB_OUT(logic, tb_tel_atready)
`SMU_TB_OUT(logic, tb_tel_afvalid)

// Flat external SMN AXI subordinate (the shared ocah_axi_vip master drives this)
`SMU_TB_IN(logic [7:0], s_axi_awid)
`SMU_TB_IN(logic [55:0], s_axi_awaddr)
`SMU_TB_IN(logic [7:0], s_axi_awlen)
`SMU_TB_IN(logic [2:0], s_axi_awsize)
`SMU_TB_IN(logic [1:0], s_axi_awburst)
`SMU_TB_IN(logic, s_axi_awlock)
`SMU_TB_IN(logic [3:0], s_axi_awcache)
`SMU_TB_IN(logic [2:0], s_axi_awprot)
`SMU_TB_IN(logic [3:0], s_axi_awqos)
`SMU_TB_IN(logic [3:0], s_axi_awregion)
`SMU_TB_IN(logic [11:0], s_axi_awuser)
`SMU_TB_IN(logic, s_axi_awvalid)
`SMU_TB_OUT(logic, s_axi_awready)
`SMU_TB_IN(logic [63:0], s_axi_wdata)
`SMU_TB_IN(logic [7:0], s_axi_wstrb)
`SMU_TB_IN(logic, s_axi_wlast)
`SMU_TB_IN(logic [11:0], s_axi_wuser)
`SMU_TB_IN(logic, s_axi_wvalid)
`SMU_TB_OUT(logic, s_axi_wready)
`SMU_TB_OUT(logic [7:0], s_axi_bid)
`SMU_TB_OUT(logic [1:0], s_axi_bresp)
`SMU_TB_OUT(logic [11:0], s_axi_buser)
`SMU_TB_OUT(logic, s_axi_bvalid)
`SMU_TB_IN(logic, s_axi_bready)
`SMU_TB_IN(logic [7:0], s_axi_arid)
`SMU_TB_IN(logic [55:0], s_axi_araddr)
`SMU_TB_IN(logic [7:0], s_axi_arlen)
`SMU_TB_IN(logic [2:0], s_axi_arsize)
`SMU_TB_IN(logic [1:0], s_axi_arburst)
`SMU_TB_IN(logic, s_axi_arlock)
`SMU_TB_IN(logic [3:0], s_axi_arcache)
`SMU_TB_IN(logic [2:0], s_axi_arprot)
`SMU_TB_IN(logic [3:0], s_axi_arqos)
`SMU_TB_IN(logic [3:0], s_axi_arregion)
`SMU_TB_IN(logic [11:0], s_axi_aruser)
`SMU_TB_IN(logic, s_axi_arvalid)
`SMU_TB_OUT(logic, s_axi_arready)
`SMU_TB_OUT(logic [7:0], s_axi_rid)
`SMU_TB_OUT(logic [63:0], s_axi_rdata)
`SMU_TB_OUT(logic [1:0], s_axi_rresp)
`SMU_TB_OUT(logic, s_axi_rlast)
`SMU_TB_OUT(logic [11:0], s_axi_ruser)
`SMU_TB_OUT(logic, s_axi_rvalid)
`SMU_TB_IN(logic, s_axi_rready)

// Activity counters for connectivity checks
`SMU_TB_OUT(logic [31:0], smu_axi_in_awvalid_count)
`SMU_TB_OUT(logic [31:0], smu_axi_out_awvalid_count)
