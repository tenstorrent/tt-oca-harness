// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Single source of truth for the smu_wrapper_uvm_top TB signals, shared by
// the cocotb and SV-UVM shapes of tb_wrapper_top.sv. Each signal is declared
// exactly once here and expanded by tb_wrapper_top.sv into the shape the
// compile selects:
//
//   * cocotb (default): the ANSI port list -- `SMU_TB_IN*` become
//     `input wire <type>` ports, `SMU_TB_OUT` becomes `output <type>`.
//   * SV-UVM (`UVM` defined): internal TB signals -- every entry becomes a
//     plain `<type> <name>;` declaration, driven/observed by the harness
//     block at the end of tb_wrapper_top.sv.
//
// Macro grammar (defined and undefined by tb_wrapper_top.sv, nowhere else):
//   `SMU_TB_IN_FIRST(type, name) -- first list entry only (no leading
//                                   comma in the port-list expansion)
//   `SMU_TB_IN(type, name)       -- TB -> DUT stimulus
//   `SMU_TB_OUT(type, name)      -- DUT -> TB observable
//
// The comments name what each pin carries and, for the stimulus pins, which
// cocotb driver owns it; in the SV-UVM shape the harness drives the same pin
// from smu_tb_if, a VIP interface, or a quiescent tie-off.
//
// This file is NOT standalone-compilable; it exists only for inclusion
// inside the smu_wrapper_uvm_top module header. The cocotb catalog
// (cocotb_wrapper/) drives and samples these names; keep them stable.
`SMU_TB_IN_FIRST(logic, clk_smu_i)
// Primary JTAG TAP, driven from cocotb through the pad-level TCK/TMS/TDI/TDO.
`SMU_TB_IN(logic, jtag_tck)
`SMU_TB_IN(logic, jtag_tms)
`SMU_TB_IN(logic, jtag_trst)  // active-low
`SMU_TB_IN(logic, jtag_tdi)
// ESRC raw noise, driven from cocotb. Mirrors hw/sys/sep/dv/tb/tb_top.sv.
`SMU_TB_IN(logic [11:0], esrc_noise_ext_i)
`SMU_TB_OUT(logic [11:0], esrc_noise_o)  // the driven 12-lane stimulus
`SMU_TB_OUT(logic, esrc_noise_active_o)  // lane-0 actual dcor.noise_i
// Entropy datapath observation taps. Read-only, never driven -- the same
// nets hw/sys/sep/dv/tb/tb_top.sv watches. These are how a test tells
// "the stack was programmed" from "entropy actually flowed".
`SMU_TB_OUT(logic, drbg_seed_valid_o)
`SMU_TB_OUT(logic, drbg_es_ack_o)
`SMU_TB_OUT(logic, drbg_genbits_vld_o)
// Sticky versions. These are pulses; latching them in hardware means a test
// can poll every few thousand cycles instead of sampling every edge from
// Python, which is both far faster and cannot miss a one-cycle event.
`SMU_TB_OUT(logic, drbg_seed_valid_seen_o)
`SMU_TB_OUT(logic, drbg_es_ack_seen_o)
`SMU_TB_OUT(logic, drbg_genbits_seen_o)
`SMU_TB_OUT(logic, esrc_noise_took_o)
`SMU_TB_OUT(logic, jtag_tdo)
`SMU_TB_OUT(logic, jtag_tdo_oen)
// IC_RESET override bits as the SMC and SEP reset controllers see them.
// Every wrapper test depends on these being clear: an asserted override
// holds cold/fuse reset and the SEP never fetches.
`SMU_TB_OUT(logic [67:0], ic_reset_smc_ovrd_o)
`SMU_TB_OUT(logic, ic_reset_sep_ovrd_any_o)
// SEP lifecycle-controller fan-out. The LCC decides the chiplet's posture
// and three consumers act on it; lc_state_o alone shows the SMU boundary.
// These expose the DTP and SMC legs so a test can prove the posture reaches
// them rather than merely existing on a port.
`SMU_TB_OUT(logic [1:0], lcc_demote_state_1_o)
`SMU_TB_OUT(logic [1:0], lcc_demote_state_2_o)
`SMU_TB_OUT(logic [63:0], lcc_feat_ctrl_o)
`SMU_TB_OUT(logic [15:0], lcc_dbg_disable_o)  // to DTP
// The one dbg_disable path field the DTP specification ties to the SMC
// fabric JTAG2AXI bridge, read by its spec name rather than by bit position.
`SMU_TB_OUT(logic, lcc_dbg_disable_smc_jtag2axi_o)
`SMU_TB_OUT(logic [7:0], smc_lc_state_in_o)  // as SMC receives it
// DTP JTAG2AXI traffic into the SMC. dbg_disable.smc_jtag2axi stops the
// bridge from launching a transaction at all (jtag2axi.sv: the update is
// gated by `!security_disable_i`), so counting AW/AR here is how a test
// tells "debug is gated" from "the signal merely says so".
`SMU_TB_OUT(logic [31:0], dtp_smc_dbg_aw_count_o)
`SMU_TB_OUT(logic [31:0], dtp_smc_dbg_ar_count_o)
`SMU_TB_OUT(logic [31:0], dtp_smc_dbg_b_count_o)
`SMU_TB_IN(logic, clk_ref_i)
`SMU_TB_IN(logic, clk_periph_i)
`SMU_TB_IN(logic, clk_sep_wdt_i)
// ESRC ring-oscillator sample clock. A separate, faster clock than clk_smu:
// the entropy source samples its noise lanes on this one, so with it static
// the ESRC produces nothing no matter how the stack is programmed. The SEP
// DV testbench drives it at 3 ns.
`SMU_TB_IN(logic, entropy_rosc_sample_clk_i)
`SMU_TB_IN(logic, rst_cold_ni)
`SMU_TB_IN(logic, powergood_i)
`SMU_TB_OUT(logic, dut_present_o)
`SMU_TB_OUT(logic, sep_enabled_o)
`SMU_TB_OUT(logic, rst_cold_n_o)
`SMU_TB_OUT(logic, powergood_o)
`SMU_TB_OUT(logic, smc_fuse_sense_done_o)
`SMU_TB_OUT(logic, smc_fuse_reset_n_delayed_o)
`SMU_TB_OUT(logic, rst_primary_smc_clk_n_o)
`SMU_TB_OUT(logic, smc_init_mem_done_o)
`SMU_TB_OUT(logic, sep_fuse_sense_done_o)
// State of the SEP efuse shadow-register sim_skip_fuse_sense flag, i.e.
// whether the SEP fuse-sense sequence is replaced by the shadow preload in
// this run. A checker that reads fuse-sense completion needs this to know
// whether the completion is DUT-earned.
`SMU_TB_OUT(logic, sep_fuse_sense_skipped_o)
`SMU_TB_OUT(logic, sep_reset_n_o)
`SMU_TB_OUT(logic [31:0], smc_scratch_0_o)
`SMU_TB_OUT(logic, smc_test_pass_o)
`SMU_TB_OUT(logic, smc_test_fail_o)
`SMU_TB_OUT(logic [31:0], smc_rom_read_count_o)
// From the bound smc_cpu_mem_dv: whether the SMC core is actually fetching
// and writing scratch RAM. Separates "the ROM never handed over" from
// "control reached the scratch image and it faulted".
// SMC CPU_CTRL scratch6/7/10: the ext_axi protocol's SMC-side READY, GO and
// PASS. Reading them here is diagnosis only -- the master reads the same
// registers through the aperture, which is the path under test.
`SMU_TB_OUT(logic [31:0], smc_scratch_6_o)
`SMU_TB_OUT(logic [31:0], smc_scratch_7_o)
`SMU_TB_OUT(logic [31:0], smc_scratch_10_o)
`SMU_TB_OUT(logic [31:0], smc_scratch_read_count_o)
`SMU_TB_OUT(logic [31:0], smc_scratch_write_count_dv_o)
`SMU_TB_OUT(logic [31:0], smc_scratch_write_count_o)
`SMU_TB_OUT(logic, sep_trace_valid_o)
`SMU_TB_OUT(logic [31:0], sep_pc_o)
// Remaining fields of the EL2 retirement record (el2_trace_pkt_t), for the
// cocotb processor-state monitor.
`SMU_TB_OUT(logic [31:0], sep_trace_insn_o)
`SMU_TB_OUT(logic, sep_trace_exc_o)
`SMU_TB_OUT(logic [4:0], sep_trace_ecause_o)
`SMU_TB_OUT(logic, sep_trace_interrupt_o)
`SMU_TB_OUT(logic [31:0], sep_trace_tval_o)
`SMU_TB_OUT(logic [31:0], sep_inst_count_o)
`SMU_TB_OUT(logic [31:0], sep_iccm_write_count_o)
`SMU_TB_OUT(logic [31:0], sep_dccm_write_count_o)
`SMU_TB_OUT(logic, sep_boot_rom_fetch_seen_o)
`SMU_TB_OUT(logic, sep_iccm_fetch_seen_o)
`SMU_TB_OUT(logic, sep_first_pc_valid_o)
`SMU_TB_OUT(logic [31:0], sep_first_pc_o)
`SMU_TB_OUT(logic, fw_done_o)
`SMU_TB_OUT(logic, fw_pass_o)
`SMU_TB_OUT(logic [7:0], fw_char_o)
`SMU_TB_OUT(logic, fw_char_valid_o)
// Sticky per-stage bitmap of the SEP DV firmware STAGE_BEACON words
// (0xB1B0B0B_<stage>) seen on the STDOUT mailbox. Bit N = stage N reached.
`SMU_TB_OUT(logic [15:0], fw_beacon_mask_o)
`SMU_TB_OUT(logic [31:0], fw_last_word_o)
// SEP outbound (SMN) path observation. Separates "the SEP never issued the
// write" from "the SMU crossbar did not route it to ext_out", which are the
// two ways a firmware mailbox handshake goes silent.
`SMU_TB_OUT(logic [31:0], sep_smn_out_aw_count_o)
`SMU_TB_OUT(logic [55:0], sep_xbar_global_base_o)
`SMU_TB_OUT(logic [31:0], sep_xbar_region_size_o)
// Crossbar -> SEP inbound AW. Separates "the crossbar never routed the
// transaction to the SEP" from "it arrived and the SEP inbound filter
// dropped it", which look identical from the firmware's side.
`SMU_TB_OUT(logic [31:0], sep_xbar_in_aw_count_o)
// AWUSER of the last crossbar->SEP write. The SEP inbound filter matches
// src_id/group_id out of this field (axi_filter_wrap.sv:159), so a window
// that looks correctly programmed still drops traffic whose user field
// carries a different source id.
`SMU_TB_OUT(logic [11:0], sep_xbar_in_aw_user_o)
`SMU_TB_OUT(logic [55:0], sep_xbar_in_aw_addr_o)
// Crossbar -> SMC inbound AR and AW. A DECERR on ext_in comes either from
// the crossbar's decode miss or from the SMC inbound filter; only the first
// leaves these counts where they were.
`SMU_TB_OUT(logic [31:0], smc_xbar_in_ar_count_o)
`SMU_TB_OUT(logic [31:0], smc_xbar_in_aw_count_o)
// SEP AP / STEE output-remap region-0 offsets, as the remap datapath sees
// them. sep_smu_remap programs these write-only and cannot read them back,
// so the golden comparison has to happen here.
`SMU_TB_OUT(logic [55:0], sep_ap_remap_offset0_o)
`SMU_TB_OUT(logic [55:0], sep_stee_remap_offset0_o)
// AP output-remap CSR path, split at the two stages unique to this branch:
// the second-level 16-way demux inside sep_system_csr, and the generated
// register block behind it. Everything upstream is shared with the filter
// and scratch CSRs, which are known good.
`SMU_TB_OUT(logic [31:0], sep_ap_csr_aw_count_o)  // reaches the AP_OUTPUT_REMAP demux
`SMU_TB_OUT(logic [31:0], sep_ap_reg0_aw_count_o)  // reaches region 0's register block
`SMU_TB_OUT(logic [31:0], sep_csr_aw_count_o)  // reaches sep_system_csr at all
`SMU_TB_OUT(logic [55:0], sep_csr_last_aw_addr_o)  // ...and with what address
`SMU_TB_OUT(logic [31:0], sep_csr_errslv_aw_count_o)  // ...or was classified ERR_SLV
`SMU_TB_OUT(logic [31:0], smu_axi_out_write_count_o)
`SMU_TB_OUT(logic [31:0], smu_axi_out_read_count_o)
// Outbound-boundary handshake split: write_count only moves on B, so it
// cannot separate a stalled write from one the crossbar never routed here.
// aw_valid says the beat was presented at the boundary; aw_ready says the
// boundary slave accepted it.
// ext_in AXI master pins, named for cocotbext.axi AxiBus.from_prefix
// (prefix "ext_in"). Driven by the cocotb master; see the assigns below.
`SMU_TB_IN(logic, ext_in_awvalid)
`SMU_TB_OUT(logic, ext_in_awready)
`SMU_TB_IN(logic [7:0], ext_in_awid)
`SMU_TB_IN(logic [55:0], ext_in_awaddr)
`SMU_TB_IN(logic [7:0], ext_in_awlen)
`SMU_TB_IN(logic [2:0], ext_in_awsize)
`SMU_TB_IN(logic [1:0], ext_in_awburst)
`SMU_TB_IN(logic [11:0], ext_in_awuser)
// AXI4 qualifiers. axi_56_64_aw_chan_t carries all of these; they are real
// ports so the wrapper can verify AxPROT and the other qualifiers.
`SMU_TB_IN(logic, ext_in_awlock)
`SMU_TB_IN(logic [3:0], ext_in_awcache)
`SMU_TB_IN(logic [2:0], ext_in_awprot)
`SMU_TB_IN(logic [3:0], ext_in_awqos)
`SMU_TB_IN(logic [3:0], ext_in_awregion)
`SMU_TB_IN(logic [11:0], ext_in_wuser)
`SMU_TB_OUT(logic [11:0], ext_in_buser)
`SMU_TB_IN(logic, ext_in_wvalid)
`SMU_TB_OUT(logic, ext_in_wready)
`SMU_TB_IN(logic [63:0], ext_in_wdata)
`SMU_TB_IN(logic [7:0], ext_in_wstrb)
`SMU_TB_IN(logic, ext_in_wlast)
`SMU_TB_OUT(logic, ext_in_bvalid)
`SMU_TB_IN(logic, ext_in_bready)
`SMU_TB_OUT(logic [7:0], ext_in_bid)
`SMU_TB_OUT(logic [1:0], ext_in_bresp)
`SMU_TB_IN(logic, ext_in_arvalid)
`SMU_TB_OUT(logic, ext_in_arready)
`SMU_TB_IN(logic [7:0], ext_in_arid)
`SMU_TB_IN(logic [55:0], ext_in_araddr)
`SMU_TB_IN(logic [7:0], ext_in_arlen)
`SMU_TB_IN(logic [2:0], ext_in_arsize)
`SMU_TB_IN(logic [1:0], ext_in_arburst)
`SMU_TB_IN(logic [11:0], ext_in_aruser)
`SMU_TB_IN(logic, ext_in_arlock)
`SMU_TB_IN(logic [3:0], ext_in_arcache)
`SMU_TB_IN(logic [2:0], ext_in_arprot)
`SMU_TB_IN(logic [3:0], ext_in_arqos)
`SMU_TB_IN(logic [3:0], ext_in_arregion)
`SMU_TB_OUT(logic [11:0], ext_in_ruser)
// Observables the shared seq_lib reads by name, matching tb/tb_top.sv.
`SMU_TB_OUT(jtag_tap_pkg::tap_state_e, jtag_ptap_state)
`SMU_TB_OUT(jtag_inst_reg_pkg::jtag_instruction_decoded_e, jtag_ptap_inst_decoded)
// The decoded instruction as a plain vector: VCS hands an enum-typed port
// to cocotb as a 32-bit integer.
`SMU_TB_OUT(logic [jtag_inst_reg_pkg::DECODED_IR_WIDTH-1:0], tb_ptap_inst_decoded)
`SMU_TB_OUT(logic [55:0], sep_global_base_o)
`SMU_TB_OUT(logic [55:0], sep_region_size_o)
`SMU_TB_OUT(logic [55:0], smc_global_base_o)
`SMU_TB_OUT(logic [31:0], smc_region_size_o)
`SMU_TB_OUT(logic, rst_primary_ref_clk_no)
`SMU_TB_OUT(logic, rst_primary_periph_clk_no)
`SMU_TB_OUT(logic, rst_cold_stable_ref_clk_no)
`SMU_TB_OUT(logic, lc_sigint_err_o)
// PTAP security-disable taps, reached hierarchically exactly as the bare TB
// does -- one level deeper here, since u_dut is the wrapper.
`SMU_TB_OUT(logic, tb_smc_jtag2axi_security_disable)
`SMU_TB_OUT(logic, tb_otp_jtag2axi_security_disable)
`SMU_TB_IN(logic, ext_boot_seq_done_i)
`SMU_TB_OUT(logic [63:0], tb_timer_count)
`SMU_TB_OUT(logic, tb_bsr_select)
// DTP boot-stall / IC-reset / cross-trigger surface, matching tb_top.sv.
`SMU_TB_OUT(logic, jtag_boot_stall)
`SMU_TB_OUT(logic, jtag_boot_stall_ovrd)
`SMU_TB_OUT(logic, jtag_ic_reset_ext_ovrd)
`SMU_TB_OUT(logic, jtag_ic_reset_ext_ctrl_n)
`SMU_TB_OUT(logic, jtag_ic_reset_smc_ovrd)
`SMU_TB_OUT(logic, jtag_ic_reset_smc_ctrl_n)
`SMU_TB_IN(logic, gpio_boot_stall_drive_i)
`SMU_TB_IN(logic [dtp_pkg::DEFAULT_NUM_INT_CT-3:0], xtrig_ctm_dst_req)
`SMU_TB_IN(logic [dtp_pkg::DEFAULT_NUM_INT_CT-3:0], xtrig_ctm_src_ack)
`SMU_TB_IN(logic, xtrig_clk_stop_req)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_INT_CT-3:0], xtrig_ctm_dst_ack)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_INT_CT-3:0], xtrig_ctm_src_req)
// DTP clock-stop grant, as tb/tb_top.sv exposes it. Sampled by
// smu_clock_stop_coordination_test.
`SMU_TB_OUT(logic, dtp_stop_clks_o)
// The CLA's own clock-stop enable, one level inside smu. Paired with
// dtp_stop_clks_o above: the test proves the aggregate grant follows the
// per-source enable, so both have to be visible.
`SMU_TB_OUT(logic, dtp_cla_clock_stop_en)
// SMC eFuse shadow map. seq_lib.smu_jtag_helpers.shadow_map_word32 reads
// this by name to cross-check an OTP write against the shadow copy the SMC
// actually sees; the OTP leaves cannot score without it.
`SMU_TB_OUT(smc_efuse_pkg::efuse_map_t, smc_shadow_regs)
`SMU_TB_OUT(logic, tb_stap_io_tck)
`SMU_TB_OUT(logic, tb_stap_smc_tck)
`SMU_TB_OUT(logic, tb_stap_smc_tms)
`SMU_TB_OUT(logic, tb_stap_smc_trst_n)
`SMU_TB_OUT(logic, tb_stap_smc_tdi)
`SMU_TB_OUT(logic, tb_stap_smc_tdo_oen)
// SEP STAP host TCK/TMS as the DTP drives them.
`SMU_TB_OUT(logic, tb_stap_sep_tck)
`SMU_TB_OUT(logic, tb_stap_sep_tms)
`SMU_TB_OUT(logic, ext_in_rvalid)
`SMU_TB_IN(logic, ext_in_rready)
`SMU_TB_OUT(logic [7:0], ext_in_rid)
`SMU_TB_OUT(logic [63:0], ext_in_rdata)
`SMU_TB_OUT(logic [1:0], ext_in_rresp)
`SMU_TB_OUT(logic, ext_in_rlast)
`SMU_TB_OUT(logic, smu_axi_out_aw_valid_seen_o)
`SMU_TB_OUT(logic, smu_axi_out_aw_fired_seen_o)
`SMU_TB_OUT(logic [55:0], smu_axi_out_first_aw_addr_o)
`SMU_TB_OUT(logic, smu_axi_out_w_valid_seen_o)
`SMU_TB_OUT(logic, smu_axi_out_w_fired_seen_o)
`SMU_TB_OUT(logic, smu_axi_out_w_last_seen_o)
`SMU_TB_OUT(logic, smu_axi_out_b_valid_seen_o)
// First AW's control fields, latched. A beat whose length or size is X is
// accepted on the address channel and then stalls, which the B counter
// alone cannot tell apart from a beat that never arrived.
`SMU_TB_OUT(logic [7:0], smu_axi_out_first_aw_len_o)
`SMU_TB_OUT(logic [2:0], smu_axi_out_first_aw_size_o)
`SMU_TB_OUT(logic [1:0], smu_axi_out_first_aw_burst_o)
`SMU_TB_OUT(logic [9:0], smu_axi_out_first_aw_id_o)
`SMU_TB_OUT(logic, smu_axi_out_first_aw_ctrl_x_o)
`SMU_TB_OUT(logic [15:0], smu_axi_out_aw_valid_cycles_o)
`SMU_TB_OUT(logic [15:0], smu_axi_out_aw_ready_cycles_o)
`SMU_TB_OUT(logic [15:0], smu_axi_out_w_valid_cycles_o)
`SMU_TB_OUT(logic [15:0], smu_axi_out_w_ready_cycles_o)
`SMU_TB_OUT(logic [smc_pkg::NUM_MAILBOXES-1:0], ext_mailbox_interrupts_o)
// SEP run-gate / IFU bring-up probes (keep nets visible under VCS)
`SMU_TB_OUT(logic [15:0], sep_cla_custom_o)
`SMU_TB_OUT(logic, sep_mpc_reset_run_o)
`SMU_TB_OUT(logic, sep_mpc_debug_run_o)
`SMU_TB_OUT(logic, sep_cpu_run_req_o)
`SMU_TB_OUT(logic, sep_halt_status_o)
`SMU_TB_OUT(logic, sep_debug_mode_o)
`SMU_TB_OUT(logic [31:0], sep_boot_rom_req_count_o)
`SMU_TB_OUT(logic, sep_cpu_rst_ni_o)
`SMU_TB_OUT(logic, sep_dbg_rstb_o)
`SMU_TB_OUT(logic, sep_mod_rst_ni_o)
`SMU_TB_OUT(logic [31:0], sep_cpu_clk_count_o)
`SMU_TB_OUT(logic, sep_rungate_at_release_valid_o)
`SMU_TB_OUT(logic, sep_mpc_reset_run_at_release_o)
`SMU_TB_OUT(logic, sep_mpc_xz_at_release_o)
`SMU_TB_OUT(logic [15:0], sep_cla_at_release_o)
// SMU_ALL_001 compose / clk-domain / lifecycle observe surface
`SMU_TB_OUT(logic [7:0], lc_state_o)
// Hierarchical SEP lifecycle source (for lc_state=from_sep identity). This
// bench elaborates SEP, so the tap is live. No target of this package
// elaborates SEP=0.
`SMU_TB_OUT(logic [7:0], obs_sep_lc_state_o)
// Compile-time present flags, diagnostic only: SMU_ALL_001 proves presence
// from the hierarchical clk/rst identity observes below.
`SMU_TB_OUT(logic, obs_compose_smc_present_o)
`SMU_TB_OUT(logic, obs_compose_sep_present_o)
`SMU_TB_OUT(logic, obs_compose_dtp_present_o)
`SMU_TB_OUT(logic, obs_compose_xbar_present_o)
`SMU_TB_OUT(logic, obs_dtp_clk_o)
`SMU_TB_OUT(logic, obs_smc_clk_o)
`SMU_TB_OUT(logic, obs_sep_clk_o)
`SMU_TB_OUT(logic, obs_xbar_clk_o)
`SMU_TB_OUT(logic, obs_dtp_rst_n_o)
`SMU_TB_OUT(logic, obs_smc_rst_n_o)
`SMU_TB_OUT(logic, obs_sep_rst_n_o)
`SMU_TB_OUT(logic, obs_xbar_rst_n_o)
`SMU_TB_OUT(logic, obs_smc_tel_clk_o)
`SMU_TB_OUT(logic, obs_sep_wdt_clk_o)
// SMC reset-controller power-good synchronizer output, and a sticky record of
// it having been observed deasserted. Both come from inside u_dut; powergood_o
// below is the input pin echoed back.
`SMU_TB_OUT(logic, obs_powergood_stable_o)
`SMU_TB_OUT(logic, obs_powergood_stable_low_seen_o)
`SMU_TB_OUT(logic, obs_jtag_tdo_o)
`SMU_TB_OUT(logic, obs_smu_axi_awready_o)
`SMU_TB_OUT(logic, obs_xtrig_src_req0_o)
// Secondary-TAP and iJTAG scan-chain hosts. smu_wrapper is the scan master
// on all of them, so the bench has to supply the client side; tb_top.sv
// closes each chain with scan_in <- scan_out and this does the same, so a
// shift through the primary TAP leaves the wrapper at its boundary pins and
// re-enters there. The select and TDO-enable taps are what separates
// "the chain shifted" from "the host was never selected".
`SMU_TB_OUT(logic, tb_dfd_select)
`SMU_TB_OUT(logic, tb_dft_select)
`SMU_TB_OUT(logic, tb_dft_secure_select)
`SMU_TB_OUT(logic, tb_stap_host_select)
`SMU_TB_OUT(logic, tb_stap_io_tms)
`SMU_TB_OUT(logic, tb_stap_io_tdo)
`SMU_TB_OUT(logic, tb_stap_io_tdo_oen)
`SMU_TB_OUT(logic, tb_stap_extra0_tms)
`SMU_TB_OUT(logic, tb_stap_extra0_tdo)
`SMU_TB_OUT(logic, tb_stap_extra0_tdo_oen)
// ATB telemetry sources, one lane per receiver; lane 0 is the low bits.
`SMU_TB_IN(logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0][7:0], tb_telemetry_atdata)
`SMU_TB_IN(logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0][6:0], tb_telemetry_atid)
`SMU_TB_IN(logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0], tb_telemetry_atvalid)
`SMU_TB_IN(logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0], tb_telemetry_afready)
`SMU_TB_OUT(logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0], tb_telemetry_atready)
`SMU_TB_OUT(logic [smc_config_pkg::NUM_TELEMETRY_RECEIVERS-1:0], tb_telemetry_afvalid)
// SMC boundary inputs, and the outputs they and the SMC CSRs drive.
`SMU_TB_IN(logic [smc_4core_cpu_pkg::NUM_EXT_INTERRUPTS-1:0], tb_smc_ext_interrupts)
`SMU_TB_IN(logic [3:0], tb_smc_ndmreset_request)
`SMU_TB_IN(logic, tb_cfg_flr_pf_active)
`SMU_TB_IN(logic, tb_mem_repair_abort)
`SMU_TB_IN(logic, tb_mbist_abort)
// Active-high holds on the boundary straps the wrapper otherwise sees
// asserted: each drives the DUT input low while it is 1, so an undriven
// pin leaves the strap at its boot value.
`SMU_TB_IN(logic, tb_mem_repair_hold)
`SMU_TB_IN(logic, tb_mbist_hold)
`SMU_TB_IN(logic [31:0], tb_ss_reset_incomplete)
`SMU_TB_IN(logic, tb_chiplet_secondary)
`SMU_TB_IN(logic, tb_cool_reset_pin)
`SMU_TB_OUT(logic [3:0], tb_smc_ndmreset_process)
`SMU_TB_OUT(logic [31:0], tb_isolate_req)
`SMU_TB_OUT(logic [31:0], tb_ss_config)
// One 32-bit word per `reset_ctrl_t` field of `ss_reset_ctrl_o`. Lane i of
// each word is subsystem i's field, so a word lines up with the reset-unit
// register that owns the field.
`SMU_TB_OUT(logic [31:0], tb_ss_cold_reset_n)
`SMU_TB_OUT(logic [31:0], tb_ss_warm_reset_n)
`SMU_TB_OUT(logic [31:0], tb_ss_config_state_hold)
`SMU_TB_OUT(logic [31:0], tb_ss_sram_hold)
`SMU_TB_OUT(logic [31:0], tb_ss_critical_signal_hold)
`SMU_TB_OUT(logic [31:0], tb_ss_debug_hold)
`SMU_TB_OUT(logic [31:0], tb_ss_force_to_ref_clk_n)
`SMU_TB_OUT(logic, tb_sync_irq)
`SMU_TB_OUT(logic, tb_skip_mem_repair)
`SMU_TB_OUT(logic, tb_smc_cluster_ded)
`SMU_TB_OUT(logic, tb_smc_wdt_first_timeout)
`SMU_TB_OUT(logic, tb_smc_wdt_second_timeout)
`SMU_TB_OUT(logic [smc_pkg::NUM_GPIO_WRAPS-1:0], tb_gpio_interrupt)
`SMU_TB_OUT(logic [smc_config_pkg::NUM_UART-1:0], tb_uart_interrupt)
// GPIO pin 0 pad drive, weak so a core output still wins, matching the
// boot-stall strap drive on pin 57 below.
`SMU_TB_IN(logic, tb_gpio0_drive_en)
`SMU_TB_IN(logic, tb_gpio0_drive_val)
// Per-pad drive for the whole GPIO bus, on the same weak terms as pin 0.
`SMU_TB_IN(logic [smc_pkg::NUM_GPIO_WRAPS-1:0], tb_gpio_drive_en)
`SMU_TB_IN(logic [smc_pkg::NUM_GPIO_WRAPS-1:0], tb_gpio_drive_val)
// SEP secure test-mode request strap. The SEP eFuse wrapper samples it on
// the rising edge of its fuse-sense-done, so a leaf drives it across a cold
// reset rather than at an arbitrary time.
`SMU_TB_IN(logic, tb_secure_tm_req)
// Clears the SRAM auto-initialisation strap the scratch-RAM preload raises.
`SMU_TB_IN(logic, tb_smc_sram_auto_init_restore)
`SMU_TB_OUT(logic, tb_secure_tm)
// Cross-trigger port pads. The DTP is the pad controller on all four
// groups. CT_Req_out sits on an ocah_open_drain_bus shared wire, a private
// wire per pad or the group wire the pads in tb_xtrig_ctp_wire_group
// share, resting at the board pull for the port's INVERT sense; the bench
// pulls the wire from a chiplet driver instead of driving the pad. The
// other three pad groups keep the direct data-input drive.
`SMU_TB_IN(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_wire_pull)
`SMU_TB_IN(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_wire_ext_assert)
`SMU_TB_IN(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_wire_group)
`SMU_TB_IN(logic, tb_xtrig_ctp_wire_group_pull)
`SMU_TB_IN(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_in_din)
`SMU_TB_IN(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ack_in_din)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_out_dout)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_out_dout_en)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_out_din_en)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_out_din)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_wire_mismatch)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ct_dst)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_in_dout)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_in_dout_en)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_req_in_din_en)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ack_in_dout)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ack_in_dout_en)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ack_in_din_en)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ack_out_dout)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ack_out_dout_en)
`SMU_TB_OUT(logic [dtp_pkg::DEFAULT_NUM_CTP-1:0], tb_xtrig_ctp_ack_out_din_en)
