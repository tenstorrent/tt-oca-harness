// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Single source of truth for the dtp_uvm_top TB signals, shared by the
// cocotb and SV-UVM shapes of tb_top.sv. Each signal is
// declared exactly once here and expanded by tb_top.sv into the shape the
// compile selects:
//
//   * cocotb (default): the ANSI port list -- `DTP_TB_IN*` become
//     `input wire <type>` ports, `DTP_TB_OUT` becomes `output <type>`.
//   * SV-UVM (`UVM` defined): internal TB signals -- every entry becomes a
//     plain `<type> <name>;` declaration, driven/observed by the harness
//     block at the end of tb_top.sv.
//
// Macro grammar (defined and undefined by tb_top.sv, nowhere else):
//   `DTP_TB_IN_FIRST(type, name)  -- first list entry only (no leading
//                                    comma in the port-list expansion)
//   `DTP_TB_IN(type, name)        -- TB -> DUT stimulus
//   `DTP_TB_OUT(type, name)       -- DUT -> TB observable
//   `DTP_TB_IN_COCOTB(type, name) -- cocotb-shape-only stimulus: expands to
//                                    nothing under `UVM` (the UVM harness
//                                    drives the typed struct directly)
//
// This file is NOT standalone-compilable; it exists only for inclusion
// inside the dtp_uvm_top module header.

// System clock and reset (cocotb drives them; the UVM harness generates the
// clock and sequences the resets through dtp_tb_if)
`DTP_TB_IN_FIRST(logic, clk_i)
`DTP_TB_IN(logic, rst_n_i)
`DTP_TB_IN(logic, pwr_on_rst_ni)

// Primary JTAG TAP pins (cocotb drives them raw; UVM via ocah_jtag_if)
`DTP_TB_IN(logic, jtag_tck)
`DTP_TB_IN(logic, jtag_tms)
`DTP_TB_IN(logic, jtag_trst)  // active-low TAP reset
`DTP_TB_IN(logic, jtag_tdi)
`DTP_TB_OUT(logic, jtag_tdo)
`DTP_TB_OUT(logic, jtag_tdo_oen)

// TAP state observation for IEEE 1149.1 FSM checks (UVM: via dtp_tb_if)
`DTP_TB_OUT(tap_state_e, jtag_ptap_state)
`DTP_TB_OUT(jtag_instruction_decoded_e, jtag_ptap_inst_decoded)

// Flattened scan-control observables for DTP-local scan models/checkers.
`DTP_TB_OUT(logic, jtag_bsr_select)
`DTP_TB_OUT(logic, jtag_bsr_shift_en)
`DTP_TB_OUT(logic, jtag_bsr_capture_en)
`DTP_TB_OUT(logic, jtag_bsr_update_en)
`DTP_TB_OUT(logic, jtag_ijtag_select)
`DTP_TB_OUT(logic, jtag_ijtag_shift_en)
`DTP_TB_OUT(logic, jtag_ijtag_capture_en)
`DTP_TB_OUT(logic, jtag_ijtag_update_en)
`DTP_TB_OUT(logic, jtag_dft_secure_select)
`DTP_TB_OUT(logic, jtag_dft_secure_shift_en)
`DTP_TB_OUT(logic, jtag_dft_secure_capture_en)
`DTP_TB_OUT(logic, jtag_dft_secure_update_en)
`DTP_TB_OUT(logic, jtag_dft_select)
`DTP_TB_OUT(logic, jtag_dft_shift_en)
`DTP_TB_OUT(logic, jtag_dft_capture_en)
`DTP_TB_OUT(logic, jtag_dft_update_en)
`DTP_TB_OUT(logic, jtag_dfd_select)
`DTP_TB_OUT(logic, jtag_dfd_shift_en)
`DTP_TB_OUT(logic, jtag_dfd_capture_en)
`DTP_TB_OUT(logic, jtag_dfd_update_en)
`DTP_TB_OUT(logic, jtag_stap_host_select)
`DTP_TB_OUT(logic, jtag_stap_host_shift_en)
`DTP_TB_OUT(logic, jtag_stap_host_capture_en)
`DTP_TB_OUT(logic, jtag_stap_host_update_en)
`DTP_TB_OUT(logic, jtag_stap_io_tms)
`DTP_TB_OUT(logic, jtag_stap_io_tck)
`DTP_TB_OUT(logic, jtag_stap_io_trst_n)
`DTP_TB_OUT(logic, jtag_stap_io_tdo_oen)
`DTP_TB_OUT(logic, jtag_stap_smc_tms)
`DTP_TB_OUT(logic, jtag_stap_smc_tck)
`DTP_TB_OUT(logic, jtag_stap_smc_trst_n)
`DTP_TB_OUT(logic, jtag_stap_smc_tdo_oen)
`DTP_TB_OUT(logic, jtag_stap_sep_tms)
`DTP_TB_OUT(logic, jtag_stap_sep_tck)
`DTP_TB_OUT(logic, jtag_stap_sep_trst_n)
`DTP_TB_OUT(logic, jtag_stap_sep_tdo_oen)
`DTP_TB_OUT(logic, jtag_stap_extra0_tms)
`DTP_TB_OUT(logic, jtag_stap_extra0_tck)
`DTP_TB_OUT(logic, jtag_stap_extra0_trst_n)
`DTP_TB_OUT(logic, jtag_stap_extra0_tdo_oen)

// Downstream STAP TAP attachment. Per STAP host port: the
// host TDO (the downstream TAP's TDI), the downstream TAP's TDO back into
// the host TDI, and the attach enable. With ds_en=0 the host TDI is the
// port's own TDO (wire loopback, the default); with ds_en=1 a reactive
// ocah_jtag_vip slave device answers behind the port.
`DTP_TB_OUT(logic, jtag_stap_io_tdo)
`DTP_TB_IN(logic, jtag_stap_io_tdi)
`DTP_TB_IN(logic, jtag_stap_io_ds_en)
`DTP_TB_OUT(logic, jtag_stap_smc_tdo)
`DTP_TB_IN(logic, jtag_stap_smc_tdi)
`DTP_TB_IN(logic, jtag_stap_smc_ds_en)
`DTP_TB_OUT(logic, jtag_stap_sep_tdo)
`DTP_TB_IN(logic, jtag_stap_sep_tdi)
`DTP_TB_IN(logic, jtag_stap_sep_ds_en)
`DTP_TB_OUT(logic, jtag_stap_extra0_tdo)
`DTP_TB_IN(logic, jtag_stap_extra0_tdi)
`DTP_TB_IN(logic, jtag_stap_extra0_ds_en)

// DEBUG_CONTROL / IC_RESET observables and CLA clock-stop stimulus.
`DTP_TB_IN(logic [DEFAULT_NUM_CLK_STOP_REQ-1:0], xtrig_clk_stop_req)
`DTP_TB_OUT(logic, stop_clks)
`DTP_TB_OUT(logic, cla_clock_stop_en)
`DTP_TB_OUT(logic, jtag_boot_stall_ovrd)
`DTP_TB_OUT(logic, jtag_boot_stall)
`DTP_TB_OUT(logic, jtag_ic_reset_smc_ovrd)
`DTP_TB_OUT(logic, jtag_ic_reset_smc_ctrl_n)
`DTP_TB_OUT(logic, jtag_ic_reset_sep_ovrd)
`DTP_TB_OUT(logic, jtag_ic_reset_sep_ctrl_n)
`DTP_TB_OUT(logic, jtag_ic_reset_ext_ovrd)
`DTP_TB_OUT(logic, jtag_ic_reset_ext_ctrl_n)

// Lifecycle debug-disable stimulus: the eleven pre-resolved active-high
// disables of sep_lifecycle_ctrl_pkg::dbg_disable_t, one scalar per field
// (1 = interface disabled). Packed unchanged into DTP's dbg_disable_i.
// cocotb shape only: the UVM harness connects the typed
// dtp_tb_if.dbg_disable struct straight to the DUT, so the per-field
// scalars have no UVM-shape counterparts.
`DTP_TB_IN_COCOTB(logic, dbg_disable_stap_io)
`DTP_TB_IN_COCOTB(logic, dbg_disable_stap_smc)
`DTP_TB_IN_COCOTB(logic, dbg_disable_stap_sep)
`DTP_TB_IN_COCOTB(logic, dbg_disable_stap_extra)
`DTP_TB_IN_COCOTB(logic, dbg_disable_stap_host)
`DTP_TB_IN_COCOTB(logic, dbg_disable_dft_secure)
`DTP_TB_IN_COCOTB(logic, dbg_disable_dft_nonsecure)
`DTP_TB_IN_COCOTB(logic, dbg_disable_dfd)
`DTP_TB_IN_COCOTB(logic, dbg_disable_smc_jtag2axi)
`DTP_TB_IN_COCOTB(logic, dbg_disable_smc_otp_jtag2axi)
`DTP_TB_IN_COCOTB(logic, dbg_disable_sep_otp_jtag2axi)

// SMC AXI request-valid pulse counters for no-activity security checks.
`DTP_TB_OUT(logic [31:0], smc_axi_awvalid_count)
`DTP_TB_OUT(logic [31:0], smc_axi_wvalid_count)
`DTP_TB_OUT(logic [31:0], smc_axi_arvalid_count)

// OTP AXI-Lite request-valid pulse counters for no-activity checks.
`DTP_TB_OUT(logic [31:0], smc_otp_axil_awvalid_count)
`DTP_TB_OUT(logic [31:0], smc_otp_axil_wvalid_count)
`DTP_TB_OUT(logic [31:0], smc_otp_axil_arvalid_count)
`DTP_TB_OUT(logic [31:0], sep_otp_axil_awvalid_count)
`DTP_TB_OUT(logic [31:0], sep_otp_axil_wvalid_count)
`DTP_TB_OUT(logic [31:0], sep_otp_axil_arvalid_count)

// SMC OTP AXI-Lite manager flattened for the TB responder (cocotb
// AxiLiteRam; UVM ocah_axi_vip slave agent).
`DTP_TB_OUT(logic [31:0], smc_otp_axil_awaddr)
`DTP_TB_OUT(logic [2:0], smc_otp_axil_awprot)
`DTP_TB_OUT(logic, smc_otp_axil_awvalid)
`DTP_TB_IN(logic, smc_otp_axil_awready)
`DTP_TB_OUT(logic [31:0], smc_otp_axil_wdata)
`DTP_TB_OUT(logic [3:0], smc_otp_axil_wstrb)
`DTP_TB_OUT(logic, smc_otp_axil_wvalid)
`DTP_TB_IN(logic, smc_otp_axil_wready)
`DTP_TB_IN(logic [1:0], smc_otp_axil_bresp)
`DTP_TB_IN(logic, smc_otp_axil_bvalid)
`DTP_TB_OUT(logic, smc_otp_axil_bready)
`DTP_TB_OUT(logic [31:0], smc_otp_axil_araddr)
`DTP_TB_OUT(logic [2:0], smc_otp_axil_arprot)
`DTP_TB_OUT(logic, smc_otp_axil_arvalid)
`DTP_TB_IN(logic, smc_otp_axil_arready)
`DTP_TB_IN(logic [31:0], smc_otp_axil_rdata)
`DTP_TB_IN(logic [1:0], smc_otp_axil_rresp)
`DTP_TB_IN(logic, smc_otp_axil_rvalid)
`DTP_TB_OUT(logic, smc_otp_axil_rready)

// SEP OTP AXI-Lite manager flattened for the TB responder.
`DTP_TB_OUT(logic [31:0], sep_otp_axil_awaddr)
`DTP_TB_OUT(logic [2:0], sep_otp_axil_awprot)
`DTP_TB_OUT(logic, sep_otp_axil_awvalid)
`DTP_TB_IN(logic, sep_otp_axil_awready)
`DTP_TB_OUT(logic [31:0], sep_otp_axil_wdata)
`DTP_TB_OUT(logic [3:0], sep_otp_axil_wstrb)
`DTP_TB_OUT(logic, sep_otp_axil_wvalid)
`DTP_TB_IN(logic, sep_otp_axil_wready)
`DTP_TB_IN(logic [1:0], sep_otp_axil_bresp)
`DTP_TB_IN(logic, sep_otp_axil_bvalid)
`DTP_TB_OUT(logic, sep_otp_axil_bready)
`DTP_TB_OUT(logic [31:0], sep_otp_axil_araddr)
`DTP_TB_OUT(logic [2:0], sep_otp_axil_arprot)
`DTP_TB_OUT(logic, sep_otp_axil_arvalid)
`DTP_TB_IN(logic, sep_otp_axil_arready)
`DTP_TB_IN(logic [31:0], sep_otp_axil_rdata)
`DTP_TB_IN(logic [1:0], sep_otp_axil_rresp)
`DTP_TB_IN(logic, sep_otp_axil_rvalid)
`DTP_TB_OUT(logic, sep_otp_axil_rready)

// XTRIG AXI-Lite subordinate flattened for TB-driven CSR access (the UVM
// shape ties the request side off quiescent).
`DTP_TB_IN(logic [31:0], xtrig_axil_awaddr)
`DTP_TB_IN(logic [2:0], xtrig_axil_awprot)
`DTP_TB_IN(logic, xtrig_axil_awvalid)
`DTP_TB_OUT(logic, xtrig_axil_awready)
`DTP_TB_IN(logic [31:0], xtrig_axil_wdata)
`DTP_TB_IN(logic [3:0], xtrig_axil_wstrb)
`DTP_TB_IN(logic, xtrig_axil_wvalid)
`DTP_TB_OUT(logic, xtrig_axil_wready)
`DTP_TB_OUT(logic [1:0], xtrig_axil_bresp)
`DTP_TB_OUT(logic, xtrig_axil_bvalid)
`DTP_TB_IN(logic, xtrig_axil_bready)
`DTP_TB_IN(logic [31:0], xtrig_axil_araddr)
`DTP_TB_IN(logic [2:0], xtrig_axil_arprot)
`DTP_TB_IN(logic, xtrig_axil_arvalid)
`DTP_TB_OUT(logic, xtrig_axil_arready)
`DTP_TB_OUT(logic [31:0], xtrig_axil_rdata)
`DTP_TB_OUT(logic [1:0], xtrig_axil_rresp)
`DTP_TB_OUT(logic, xtrig_axil_rvalid)
`DTP_TB_IN(logic, xtrig_axil_rready)
`DTP_TB_OUT(logic [31:0], xtrig_axil_awvalid_count)
`DTP_TB_OUT(logic [31:0], xtrig_axil_wvalid_count)
`DTP_TB_OUT(logic [31:0], xtrig_axil_arvalid_count)

// XTRIG CTM and CTP GPIO stimulus/observables (the UVM shape ties the
// stimulus inputs off quiescent).
`DTP_TB_OUT(logic [DEFAULT_NUM_INT_CT-1:0], xtrig_ctm_src_req)
`DTP_TB_IN(logic [DEFAULT_NUM_INT_CT-1:0], xtrig_ctm_src_ack)
`DTP_TB_IN(logic [DEFAULT_NUM_INT_CT-1:0], xtrig_ctm_dst_req)
`DTP_TB_OUT(logic [DEFAULT_NUM_INT_CT-1:0], xtrig_ctm_dst_ack)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_out_dout)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_out_dout_en)
`DTP_TB_IN(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_out_din)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_out_din_en)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_in_dout)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_in_dout_en)
`DTP_TB_IN(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_in_din)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_req_in_din_en)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_in_dout)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_in_dout_en)
`DTP_TB_IN(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_in_din)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_in_din_en)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_out_dout)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_out_dout_en)
`DTP_TB_IN(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_out_din)
`DTP_TB_OUT(logic [DEFAULT_NUM_CTP-1:0], xtrig_ctp_ack_out_din_en)
