// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Single source of truth for the sep_uvm_top TB signals, shared by the
// cocotb and SV-UVM shapes of tb_top.sv. Each signal is declared exactly
// once here and expanded by tb_top.sv into the shape the compile selects:
//
//   * cocotb (default): the ANSI port list -- `SEP_TB_IN*` become
//     `input wire <type>` ports, `SEP_TB_OUT` becomes `output <type>`, each
//     carrying the Verilator public metacomment.
//   * SV-UVM (`UVM` defined): internal TB signals -- every entry becomes a
//     plain `<type> <name>;` declaration, driven/observed by the harness
//     block at the end of tb_top.sv.
//
// Macro grammar (defined and undefined by tb_top.sv, nowhere else):
//   `SEP_TB_IN_FIRST(type, name) -- first list entry only (no leading
//                                   comma in the port-list expansion)
//   `SEP_TB_IN(type, name)       -- TB -> DUT stimulus
//   `SEP_TB_OUT(type, name)      -- DUT -> TB observable
//
// The comments name the cocotb driver of each pin; in the SV-UVM shape the
// harness drives the same pin from sep_tb_if or a quiescent tie-off.
//
// This file is NOT standalone-compilable; it exists only for inclusion
// inside the sep_uvm_top module header.

// Clocks (driven by cocotb)
`SEP_TB_IN_FIRST(logic, clk_i)
`SEP_TB_IN(logic, clk_wdt_i)
`SEP_TB_IN(logic, entropy_rosc_sample_clk_i)
// Free-running reference clock for the SEP_CPU_CTRL REFERENCE_COUNTER. It is a
// genuinely separate clock: prim_refclk_count_w_cdc counts on this edge and
// resynchronises the value onto clk_i, so leaving it undriven freezes the
// counter and its CDC.
`SEP_TB_IN(logic, clk_ref_i)

// Reset (driven by cocotb, active-low)
`SEP_TB_IN(logic, rst_ni)

// Boot/run controls (driven by cocotb)
`SEP_TB_IN(logic, ext_boot_seq_done_i)
`SEP_TB_IN(logic, mpc_reset_run_req)
// TEST_EN strap (frontdoor DUT input). Latched into secure_tm on fuse-sense-done
// (or on cold-reset release when security_disable is set). Default 0 = functional
// mode; drive 1 before sense to latch secure_tm. SECURE_TM does not qualify
// feature control.
`SEP_TB_IN(logic, test_en_strap_i)
// JTAG SW-reset hold (frontdoor DUT input jtag_sep_reset_ctrl_i). When 1,
// that engine is held in SW reset regardless of SW_RESET_N, so it never
// asserts crypto edn_req across rst_ni. Default 0 = CSR owns the bit.
`SEP_TB_IN(logic, jtag_otbn_rst_hold_i)
`SEP_TB_IN(logic, jtag_aes_rst_hold_i)
`SEP_TB_IN(logic, jtag_hmac_rst_hold_i)
`SEP_TB_IN(logic, jtag_kmac_rst_hold_i)
`SEP_TB_IN(logic, jtag_trng_rst_hold_i)
`SEP_TB_IN(logic, jtag_abr_rst_hold_i)
// JTAG sep_reset_n override (frontdoor jtag_sep_reset_ctrl_i). ovrd=0 selects
// sep_intermediate_reset_n, which stays low until fuse sense completes. ovrd=1
// selects val. Default 0 on both, so every other leaf keeps the sense-gated reset.
`SEP_TB_IN(logic, jtag_sep_reset_n_ovrd_i)
`SEP_TB_IN(logic, jtag_sep_reset_n_val_i)
// IC_RESET TDR for the SEP slice. tdr_en=0 keeps the per-port pins above.
// tdr_en=1 selects jtag_ic_reset_reg, sized to jtag_sep_reset_ctrl_t and
// packed the way jtag_ptap packs the SEP slice. Scan controls idle, and
// rst_n/trst_n stay released, so the register holds override-off.
`SEP_TB_IN(logic, jtag_ic_reset_tdr_en_i)
`SEP_TB_IN(logic, jtag_ic_reset_tck_i)
`SEP_TB_IN(logic, jtag_ic_reset_select_i)
`SEP_TB_IN(logic, jtag_ic_reset_capture_en_i)
`SEP_TB_IN(logic, jtag_ic_reset_shift_en_i)
`SEP_TB_IN(logic, jtag_ic_reset_update_en_i)
`SEP_TB_IN(logic, jtag_ic_reset_rst_n_i)
`SEP_TB_IN(logic, jtag_ic_reset_trst_n_i)
`SEP_TB_IN(logic, jtag_ic_reset_tdi_i)
`SEP_TB_OUT(logic, jtag_ic_reset_tdo_o)
// LC differential-integrity error inject. Default 0. When 1, tb forces a broken
// pair onto the LCC decoder input (no legal OTP image can present one). See
// the force block in tb_top.sv.
`SEP_TB_IN(logic, lc_sigint_inject_i)
// Token-comparator redundancy fault inject. Default 0. Encoding:
//   3'b000 off
//   3'b001 collapse instance 0 of the selected comparator (both rails 0).
//          This also makes instance 0 disagree with 1 and 2, and the fault
//          output is the OR of the collapse and disagree terms, so this
//          mode does not prove the collapse detector exists. Isolating it
//          needs all three pairs alike and compute_comparison_vld_i=1.
//          SEC_DISABLE's valid is the sticky digest valid, not the RMA
//          digest_vld && fuse_sense_done term, so an all-alike force with
//          that valid still 0 is expected not to raise the SEC rail.
//   3'b010 disagree: instance 0 drives a legal mismatch pair while 1/2 match.
//          Every pair stays legal, so this isolates the disagree term.
//   3'b011 unanimous legal mismatch pair on all three instances
//   3'b100 unanimous legal match pair on all three instances
//          The two unanimous modes overwrite the gated comparator outputs,
//          so the presented token does not reach the result: they show that
//          a unanimous legal pair raises no fault, not that any particular
//          token compares a particular way.
// No legal token/OTP image can break the three identical compare cones. See
// the force block in tb_top.sv.
`SEP_TB_IN(logic [2:0], token_cmp_fault_inject_i)
// Which token comparator the inject hits. Default 0.
//   2'b00 RMA_SIP  2'b01 RMA_CHIPLET  2'b10 SEC_DISABLE
`SEP_TB_IN(logic [1:0], token_cmp_fault_sel_i)
// RMA_SIP digest test-enable inject. The production test input is tied
// low in this testbench, so the latch-freeze path has no frontdoor.
`SEP_TB_IN(logic, token_digest_test_en_inject_i)
// DMA host-path command-integrity inject. Default 0. When 1, tb forces a
// broken codeword onto the host-adapter command-integrity decoder input
// (software cannot emit a bad TL-UL user code). The checker
// still gates on a_valid, so a DMA-issued command is required. See the
// force block in tb_top.sv.
`SEP_TB_IN(logic, dma_host_intg_inject_i)
// HMAC message-FIFO drain stall. Default 0. When 1, tb holds the FIFO's read
// side idle so the hash engine stops consuming and the FIFO fills. A port rather
// than a plusarg so a test can raise it after the ROM's short self-test hash.
// See the force block in tb_top.sv.
`SEP_TB_IN(logic, hmac_fifo_drain_stall_i)

// ------------------------------------------------------------------
// Flat CPU-LSU AXI manager (cocotbext-axi AxiMaster, prefix s_axi)
// sep_cpu.lsu_axi_* = sep_32_64_3_12 (addr32/data64/id3/user12)
// ------------------------------------------------------------------
// Write address channel
`SEP_TB_IN(logic [2:0], s_axi_awid)
`SEP_TB_IN(logic [31:0], s_axi_awaddr)
`SEP_TB_IN(logic [7:0], s_axi_awlen)
`SEP_TB_IN(logic [2:0], s_axi_awsize)
`SEP_TB_IN(logic [1:0], s_axi_awburst)
`SEP_TB_IN(logic, s_axi_awlock)
`SEP_TB_IN(logic [3:0], s_axi_awcache)
`SEP_TB_IN(logic [2:0], s_axi_awprot)
`SEP_TB_IN(logic [3:0], s_axi_awqos)
`SEP_TB_IN(logic [3:0], s_axi_awregion)
`SEP_TB_IN(logic [11:0], s_axi_awuser)
`SEP_TB_IN(logic, s_axi_awvalid)
`SEP_TB_OUT(logic, s_axi_awready)
// Write data channel
`SEP_TB_IN(logic [63:0], s_axi_wdata)
`SEP_TB_IN(logic [7:0], s_axi_wstrb)
`SEP_TB_IN(logic, s_axi_wlast)
`SEP_TB_IN(logic [11:0], s_axi_wuser)
`SEP_TB_IN(logic, s_axi_wvalid)
`SEP_TB_OUT(logic, s_axi_wready)
// Write response channel
`SEP_TB_OUT(logic [2:0], s_axi_bid)
`SEP_TB_OUT(logic [1:0], s_axi_bresp)
`SEP_TB_OUT(logic [11:0], s_axi_buser)
`SEP_TB_OUT(logic, s_axi_bvalid)
`SEP_TB_IN(logic, s_axi_bready)
// Read address channel
`SEP_TB_IN(logic [2:0], s_axi_arid)
`SEP_TB_IN(logic [31:0], s_axi_araddr)
`SEP_TB_IN(logic [7:0], s_axi_arlen)
`SEP_TB_IN(logic [2:0], s_axi_arsize)
`SEP_TB_IN(logic [1:0], s_axi_arburst)
`SEP_TB_IN(logic, s_axi_arlock)
`SEP_TB_IN(logic [3:0], s_axi_arcache)
`SEP_TB_IN(logic [2:0], s_axi_arprot)
`SEP_TB_IN(logic [3:0], s_axi_arqos)
`SEP_TB_IN(logic [3:0], s_axi_arregion)
`SEP_TB_IN(logic [11:0], s_axi_aruser)
`SEP_TB_IN(logic, s_axi_arvalid)
`SEP_TB_OUT(logic, s_axi_arready)
// Read data channel
`SEP_TB_OUT(logic [2:0], s_axi_rid)
`SEP_TB_OUT(logic [63:0], s_axi_rdata)
`SEP_TB_OUT(logic [1:0], s_axi_rresp)
`SEP_TB_OUT(logic, s_axi_rlast)
`SEP_TB_OUT(logic [11:0], s_axi_ruser)
`SEP_TB_OUT(logic, s_axi_rvalid)
`SEP_TB_IN(logic, s_axi_rready)

// ------------------------------------------------------------------
// Flat SMN-inbound external AXI manager (cocotbext-axi AxiMaster, prefix
// m_axi). This is the DUT's REAL external inbound port (smn_inbound_axi_*,
// sep_56_64_6_12: addr56/data64/id6/user12) -- a true frontdoor master on a
// real DUT port. Unlike the CPU-LSU splice (s_axi), which attaches to the
// internal LSU bus, this path traverses the SEP inbound filter
// (u_inbound_filter), which is block-by-default and is skipped
// only when feat_ctrl.sep_debug=1. `sep_lcc_uvm_inbound_filter_gating_test` drives
// it to prove external AXI is blocked (PROD) / allowed (PROD_DBG_1). Idle for
// every other test (the agent drives these to a clean idle from t=0).
// ------------------------------------------------------------------
// Write address channel
`SEP_TB_IN(logic [5:0], m_axi_awid)
`SEP_TB_IN(logic [55:0], m_axi_awaddr)
`SEP_TB_IN(logic [7:0], m_axi_awlen)
`SEP_TB_IN(logic [2:0], m_axi_awsize)
`SEP_TB_IN(logic [1:0], m_axi_awburst)
`SEP_TB_IN(logic, m_axi_awlock)
`SEP_TB_IN(logic [3:0], m_axi_awcache)
`SEP_TB_IN(logic [2:0], m_axi_awprot)
`SEP_TB_IN(logic [3:0], m_axi_awqos)
`SEP_TB_IN(logic [3:0], m_axi_awregion)
`SEP_TB_IN(logic [11:0], m_axi_awuser)
`SEP_TB_IN(logic, m_axi_awvalid)
`SEP_TB_OUT(logic, m_axi_awready)
// Write data channel
`SEP_TB_IN(logic [63:0], m_axi_wdata)
`SEP_TB_IN(logic [7:0], m_axi_wstrb)
`SEP_TB_IN(logic, m_axi_wlast)
`SEP_TB_IN(logic [11:0], m_axi_wuser)
`SEP_TB_IN(logic, m_axi_wvalid)
`SEP_TB_OUT(logic, m_axi_wready)
// Write response channel
`SEP_TB_OUT(logic [5:0], m_axi_bid)
`SEP_TB_OUT(logic [1:0], m_axi_bresp)
`SEP_TB_OUT(logic [11:0], m_axi_buser)
`SEP_TB_OUT(logic, m_axi_bvalid)
`SEP_TB_IN(logic, m_axi_bready)
// Read address channel
`SEP_TB_IN(logic [5:0], m_axi_arid)
`SEP_TB_IN(logic [55:0], m_axi_araddr)
`SEP_TB_IN(logic [7:0], m_axi_arlen)
`SEP_TB_IN(logic [2:0], m_axi_arsize)
`SEP_TB_IN(logic [1:0], m_axi_arburst)
`SEP_TB_IN(logic, m_axi_arlock)
`SEP_TB_IN(logic [3:0], m_axi_arcache)
`SEP_TB_IN(logic [2:0], m_axi_arprot)
`SEP_TB_IN(logic [3:0], m_axi_arqos)
`SEP_TB_IN(logic [3:0], m_axi_arregion)
`SEP_TB_IN(logic [11:0], m_axi_aruser)
`SEP_TB_IN(logic, m_axi_arvalid)
`SEP_TB_OUT(logic, m_axi_arready)
// Read data channel
`SEP_TB_OUT(logic [5:0], m_axi_rid)
`SEP_TB_OUT(logic [63:0], m_axi_rdata)
`SEP_TB_OUT(logic [1:0], m_axi_rresp)
`SEP_TB_OUT(logic, m_axi_rlast)
`SEP_TB_OUT(logic [11:0], m_axi_ruser)
`SEP_TB_OUT(logic, m_axi_rvalid)
`SEP_TB_IN(logic, m_axi_rready)

// ------------------------------------------------------------------
// Flat SEP-OTP JTAG AXI-Lite manager (cocotbext-axi AxiLiteMaster, prefix
// j_axi). This is the DUT's real `axil_sep_otp_jtag_*` port (efuse_axil:
// addr32/data32) -- the debug/JTAG path into the eFuse interface controller,
// which arbitrates with the CPU's eFuse-MMR path at the eFuse AXI-Lite mux and
// is LC-state-gated (in PROD/RMA_SIP the JTAG path may read/write only the MMR
// token region; a shadow/CSR access is routed to an error slave -> 0xbadcab1e).
// Used by `sep_efuse_jtag_axil_el2_cpu_mux_test`. Idle for every other test.
// ------------------------------------------------------------------
`SEP_TB_IN(logic [31:0], j_axi_awaddr)
`SEP_TB_IN(logic [2:0], j_axi_awprot)
`SEP_TB_IN(logic, j_axi_awvalid)
`SEP_TB_OUT(logic, j_axi_awready)
`SEP_TB_IN(logic [31:0], j_axi_wdata)
`SEP_TB_IN(logic [3:0], j_axi_wstrb)
`SEP_TB_IN(logic, j_axi_wvalid)
`SEP_TB_OUT(logic, j_axi_wready)
`SEP_TB_OUT(logic [1:0], j_axi_bresp)
`SEP_TB_OUT(logic, j_axi_bvalid)
`SEP_TB_IN(logic, j_axi_bready)
`SEP_TB_IN(logic [31:0], j_axi_araddr)
`SEP_TB_IN(logic [2:0], j_axi_arprot)
`SEP_TB_IN(logic, j_axi_arvalid)
`SEP_TB_OUT(logic, j_axi_arready)
`SEP_TB_OUT(logic [31:0], j_axi_rdata)
`SEP_TB_OUT(logic [1:0], j_axi_rresp)
`SEP_TB_OUT(logic, j_axi_rvalid)
`SEP_TB_IN(logic, j_axi_rready)

// ------------------------------------------------------------------
// CPU firmware-boot controls/observables (driven/read by cocotb in the
// `+cpu_boot` run mode; left at 0 by the no-CPU smoke tests).
// ------------------------------------------------------------------
// Desired reset PC[31:1], driven to the wrapper's rst_vec input.
`SEP_TB_IN(logic [31:1], rst_vec_i)
`SEP_TB_IN(logic, i_cpu_run_req_i)  // async run request to the core
`SEP_TB_IN(logic, tcm_load_i)  // strobe: backdoor-load TCM image
// WDT reset INPUT to the DUT (a real sep primary input). Default-driven 1
// (deasserted) by sep_base_test for every test; the wdt-reset-path test
// pulses it to 0 to exercise wdt_rst_ni -> sep_cpu_reset_n.
`SEP_TB_IN(logic, wdt_rst_ni_i)
// EL2 debugger reset INPUT to the DUT (sep.sv dbg_rstb_i, a real sep primary
// input). Default-driven 1 (deasserted) by sep_base_test; the CPU debug-reset
// isolation test pulses it to 0 to prove it does NOT disturb the system/CPU
// reset domain.
`SEP_TB_IN(logic, dbg_rstb_i)
`SEP_TB_OUT(logic, o_cpu_run_ack_o)  // core run acknowledge (XMR-tapped)
`SEP_TB_OUT(logic, cpu_trace_valid_o)  // retired-instruction valid
`SEP_TB_OUT(logic [31:0], cpu_trace_addr_o)  // retired-instruction PC
`SEP_TB_OUT(logic [31:0], cpu_trace_insn_o)  // retired instruction encoding
`SEP_TB_OUT(logic [4:0], cpu_trace_ecause_o)  // exception cause (with dbg_cpu_trace_exc_o)
`SEP_TB_OUT(logic, cpu_trace_interrupt_o)  // exception was an interrupt
`SEP_TB_OUT(logic [31:0], cpu_trace_tval_o)  // trap value (faulting addr/insn)
`SEP_TB_OUT(logic, fw_done_o)  // firmware signaled completion
`SEP_TB_OUT(logic, fw_pass_o)  // completion was PASS
`SEP_TB_OUT(logic [7:0], fw_char_o)  // firmware console byte
`SEP_TB_OUT(logic, fw_char_valid_o)  // console byte strobe
// Boot bring-up debug observables (cheap XMR/struct taps).
`SEP_TB_OUT(logic, dbg_iccm_active_o)  // core asserting any ICCM bank clken (fetching)
`SEP_TB_OUT(logic [13:0], dbg_iccm_addr_o)  // ICCM bank-0 row address being fetched
`SEP_TB_OUT(logic, dbg_dccm_active_o)  // core asserting any DCCM bank clken
`SEP_TB_OUT(logic, dbg_sep_reset_n_o)  // SEP internal reset released
// CPU warm reset (sep_cpu_reset_n = sep_reset_n & wdt_rst_ni).
`SEP_TB_OUT(logic, sep_cpu_reset_n_o)
`SEP_TB_OUT(logic, dbg_cpu_trace_exc_o)  // retired-instruction exception flag
`SEP_TB_OUT(logic, sep_fuse_sense_done_o)  // SEP fuse sense completed
// Sensed eFuse shadow-register array, flattened to a top-level OUTPUT PORT
// (not an internal signal) so cocotb reads it reliably -- same access
// pattern as every other observable above. Default backdoor data-compare
// path; one eFuse test uses the AXI front door instead.
`SEP_TB_OUT(logic [sep_efuse_pkg::NumEfuseBits-1:0], efuse_shadow_probe_o)
// The three public-ID fields of the Key Manager's OTP input, taken at the KM
// instance's otp_data_i port. Each is the 512-bit dual-rail word {~id, id}.
`SEP_TB_OUT(logic [511:0], km_otp_sep_chiplet_id_o)
`SEP_TB_OUT(logic [511:0], km_otp_sep_sip_id_o)
`SEP_TB_OUT(logic [511:0], km_otp_sep_sys_id_o)
// SEP scratch-cold CSR array (8 words x 32b), surfaced as a top-level probe so
// the dual-CPU eFuse-mux coexistence test can read the EL2 firmware's measured
// summary (host loop count + KM-contention error counters) with no AXI master
// -- the EL2 owns the LSU bus under +cpu_boot. The cold block survives the KM
// warm reset.
`SEP_TB_OUT(logic [255:0], scratch_cold_probe_o)
// Read-only XMRs observe the loaded manifest header and three decrypted AES
// payload blocks. The CPU owns the SRAM frontdoor during firmware boot, so
// the testbench has no independent read path. The memory arrays sit outside
// the AXI ready/valid combinational cones.
`SEP_TB_OUT(logic [63:0], sram_word0_probe_o)
`SEP_TB_OUT(logic [383:0], sram_payload_probe_o)
// The ML-KEM seed Z words inside the Adams Bridge engine (the scratch copy the
// ML-KEM KEYGEN reads). Software cannot read Z back, and after a KV seed read
// the decapsulation key reads as zero, so this read-only XMR is the only view of
// the Z a KV read delivered. Word i occupies bits [32*i +: 32]. Zero in a build
// without Adams Bridge. Owners: sep_km_sideload_share_walk_test,
// sep_km_abr_mlkem_sideload_test.
`SEP_TB_OUT(logic [255:0], abr_mlkem_seed_z_probe_o)
// Count of SEP->SMC accesses that landed outside every register window the
// generated SMC map declares. Non-zero means the ROM used an offset this
// design does not implement -- see the SMC address decode check in tb_top.
// Any test may assert this is 0; the SMC responder is a flat memory that
// answers every address, so nothing else catches it. The words the ROM
// publishes into that memory (SMC scratch[10], DFX_CTRL_STATUS_SMU) are read
// through the responder's backdoor, not through a probe port.
`SEP_TB_OUT(logic [31:0], smc_addr_violations_o)
`SEP_TB_OUT(logic [31:0], km_rom_req_count_o)
`SEP_TB_OUT(logic [31:0], km_sram_req_count_o)
`SEP_TB_OUT(logic [31:0], km_sram_write_count_o)
`SEP_TB_OUT(logic [31:0], km_sram_word0_o)
// KM SRAM words 0..97 from the real macro array, word i at [32*i +: 32]. Sized
// for km_rom_otp_id.S, which writes its results to those words.
`SEP_TB_OUT(logic [98*32-1:0], km_sram_probe_o)
// KM SRAM read-response timing counters at the wrapper port; see the monitor
// in tb_top. Observation-only.
`SEP_TB_OUT(logic [31:0], km_sram_rd_accept_count_o)
`SEP_TB_OUT(logic [31:0], km_sram_rd_lat1_count_o)
`SEP_TB_OUT(logic [31:0], km_sram_rd_lat_err_count_o)
`SEP_TB_OUT(logic [31:0], km_sram_rd_b2b_diff_count_o)
`SEP_TB_OUT(logic [31:0], km_sram_scr_rd_count_o)
// KM SRAM writes accepted while the KM scrambler is enabled, at the wrapper
// port: count, and the physical word address and data of the first four, with
// the macro array word at each of those addresses. Observation-only.
`SEP_TB_OUT(logic [31:0], km_sram_scr_wr_count_o)
`SEP_TB_OUT(logic [4*13-1:0], km_sram_scr_wr_addr_o)
`SEP_TB_OUT(logic [4*32-1:0], km_sram_scr_wr_data_o)
`SEP_TB_OUT(logic [4*32-1:0], km_sram_scr_wr_cell_o)
// SEP-side KM mailbox regblock address-decode write refusals: count and the
// block offset of the last one. Observation-only.
`SEP_TB_OUT(logic [31:0], km_mbox_sep_wr_err_count_o)
`SEP_TB_OUT(logic [4:0], km_mbox_sep_wr_err_addr_o)
`SEP_TB_OUT(logic [31:0], otbn_imem_req_count_o)
`SEP_TB_OUT(logic [31:0], otbn_imem_write_count_o)
`SEP_TB_OUT(logic [31:0], otbn_dmem_req_count_o)
`SEP_TB_OUT(logic [31:0], otbn_dmem_write_count_o)
// ESRC -> DRBG -> CSRNG -> EDN -> KM entropy datapath probes. The driven noise
// (esrc_noise_o) is the deterministic stimulus; the rest are DUT observation
// points for the alive smoke and CHK1-CHK5 golden-vs-probe scoreboard.
// Cocotb-driven 12-lane raw noise: lets a Python noise generator feed the DUT
// and a golden the SAME deterministic sequence, so the decorrelator golden
// aligns by construction.
`SEP_TB_IN(logic [11:0], esrc_noise_ext_i)
`SEP_TB_OUT(logic [11:0], esrc_noise_o)  // driven 12-lane raw noise (golden input)
`SEP_TB_OUT(logic, esrc_noise_active_o)  // lane-0 actual DUT dcor.noise_i (force-took proof)
`SEP_TB_OUT(logic [11:0], esrc_ro_enable_o)  // CHK1/CHK2 per-lane generator enable (sync)
`SEP_TB_OUT(logic [95:0], esrc_decor_bytes_o)  // CHK1: 12x8 decorrelator sampled output
`SEP_TB_OUT(logic [347:0], esrc_decor_sr_o)  // CHK1 sync: 12x29 raw decorrelator ff_stage
`SEP_TB_OUT(logic, esrc_decor_valid_o)  // CHK2 chain: per-sample BIW/decor valid strobe
`SEP_TB_OUT(logic, esrc_whiten_push_o)  // CHK2 chain: SHA-whitener accepted-word strobe
`SEP_TB_OUT(logic, esrc_compress_vld_o)  // CHK2: compressor output valid
`SEP_TB_OUT(logic [31:0], esrc_compress_data_o)  // CHK2: compressor output word
`SEP_TB_OUT(logic, drbg_seed_valid_o)  // seed accumulated/presented to CSRNG
`SEP_TB_OUT(logic, drbg_es_ack_o)  // CSRNG seed-handshake ack
`SEP_TB_OUT(logic [383:0], drbg_es_bits_o)  // CHK4: 384-bit hardware seed
`SEP_TB_OUT(logic, drbg_genbits_vld_o)  // CHK4: CTR_DRBG genbits valid
`SEP_TB_OUT(logic [127:0], drbg_genbits_data_o)  // CHK4: CTR_DRBG genbits block
`SEP_TB_OUT(logic, drbg_genbits_fips_o)  // CHK4: genbits fips flag
`SEP_TB_OUT(logic, drbg_gen_last_o)  // CHK4: last genbits of a Generate

// drbg_axil64_lane_adapter channel-arbitration probes, one 6-bit vector per
// lane, at the adapter's own AXI-Lite-64 port. The crossbar and
// axi_to_axi_lite sit between the TB master and this port, so a same-cycle
// AW/W/AR presentation at s_axi/m_axi is not evidence of a same-cycle
// presentation HERE, which is where the arbitration decision is made. Bit
// order: {ar_ready, w_ready, aw_ready, ar_valid, w_valid, aw_valid}.
// All three ready bits low while their valid bits are held is the stall
// signature: the adapter has accepted nothing and no channel can retire.
`SEP_TB_OUT(logic [5:0], drbg_csrng_axil_chan_o)  // CSRNG lane adapter port
`SEP_TB_OUT(logic [5:0], drbg_edn_axil_chan_o)  // EDN lane adapter port
// {ar_valid, aw_valid | w_valid} on each DUT lane adapter's AXI-Lite-32 side:
// the adapter presents a request to its TL-UL bridge.
`SEP_TB_OUT(logic [1:0], drbg_csrng_fwd_o)
`SEP_TB_OUT(logic [1:0], drbg_edn_fwd_o)

// Port-level arbitration vehicle for drbg_axil64_lane_adapter.
//
// The crossbar between a SEP master and the DUT's own lane adapters delivers
// W one cycle after AW and re-serializes to that order whatever the master
// presents (CHK-CONCURRENT-CAL logs the two gaps), so a same-cycle AW/W/AR
// presentation and a W-before-AW presentation cannot be produced at the DUT
// adapter port from the fabric side. This is a SECOND, TB-OWNED instance of
// the same module with its own reset, driven straight from cocotb, so every
// legal channel ordering is presentable and a wedged cell can be cleared
// without resetting the DUT.
//
// It proves the MODULE's arbitration contract, not the SEP integration. The
// fabric-driven leaves keep that half: `drbg_{csrng,edn}_axil_chan_o` above
// observe the real DUT adapters.
`SEP_TB_IN(logic, tbadp_rst_ni_i)  // vehicle reset, independent of rst_ni
`SEP_TB_IN(logic, tbadp_aw_valid_i)
`SEP_TB_IN(logic [31:0], tbadp_aw_addr_i)
`SEP_TB_IN(logic, tbadp_w_valid_i)
`SEP_TB_IN(logic [63:0], tbadp_w_data_i)
`SEP_TB_IN(logic [7:0], tbadp_w_strb_i)
`SEP_TB_IN(logic, tbadp_b_ready_i)
`SEP_TB_IN(logic, tbadp_ar_valid_i)
`SEP_TB_IN(logic [31:0], tbadp_ar_addr_i)
`SEP_TB_IN(logic, tbadp_r_ready_i)
// {ar_ready, w_ready, aw_ready, ar_valid, w_valid, aw_valid} at the vehicle
// port, the same bit order as the DUT-side probes.
`SEP_TB_OUT(logic [5:0], tbadp_chan_o)
`SEP_TB_OUT(logic, tbadp_b_valid_o)
`SEP_TB_OUT(logic, tbadp_r_valid_o)
`SEP_TB_OUT(logic [63:0], tbadp_r_data_o)
`SEP_TB_OUT(logic [1:0], tbadp_b_resp_o)  // BRESP: OKAY vs the unsupported-access SLVERR
`SEP_TB_OUT(logic [1:0], tbadp_r_resp_o)  // RRESP: same, for the read leg
// {ar_valid, aw_valid | w_valid} on the vehicle's AXI-Lite-32 side: the
// adapter presents a downstream request. An unsupported access must leave both
// bits low, because the adapter answers it itself and forwards nothing.
`SEP_TB_OUT(logic [1:0], tbadp_fwd_o)
`SEP_TB_OUT(logic, km_entropy_tvalid_o)  // CHK5: post-mux EDN->KM tvalid (entropy_muxed_req[0])
`SEP_TB_OUT(logic [31:0], km_entropy_tdata_o)  // CHK5: post-mux EDN->KM tdata word
`SEP_TB_OUT(logic, km_entropy_tready_o)  // CHK5: KM tready (entropy_muxed_rsp[0]) -> real handshake
// CHK5 crypto EDN sinks: the SEP EDN's crypto leg (entropy_muxed_req[1]) fans
// out through drbg_axis_edn_adapter to native EDN clients crypto_edn[0]=AES,
// [1]=KMAC, [2]=OTBN-RND, [3]=OTBN-URND. A delivered word to sink i is the cycle
// crypto_edn_req[i].edn_req && crypto_edn_rsp[i].edn_ack. Packed per-client so a
// multi-sink CHK5 can score each endpoint off these vectors.
`SEP_TB_OUT(logic [3:0], crypto_edn_req_o)  // bit i = crypto_edn_req[i].edn_req
`SEP_TB_OUT(logic [3:0], crypto_edn_ack_o)  // bit i = crypto_edn_rsp[i].edn_ack
`SEP_TB_OUT(logic [127:0], crypto_edn_bus_o)  // word i = crypto_edn_rsp[i].edn_bus ([32*i +: 32])
`SEP_TB_OUT(logic [3:0], crypto_edn_fips_o)  // bit i = crypto_edn_rsp[i].edn_fips
// CHK5 per-sink ROUTING golden tap (AXIS1): the crypto-leg EDN word stream
// POST the KM/crypto mux but PRE the drbg_axis_edn_adapter fan-out
// (sep_crypto.entropy_muxed_req[1]). This is the authoritative ordered word
// sequence the adapter hands to the crypto endpoints; with a single active
// crypto sink the adapter is in-order so AES's post-adapter beats equal this
// stream 1:1, and each word is also chained to the CHK4 genbits golden.
// Read-only XMR, no force.
`SEP_TB_OUT(logic, axis1_tvalid_o)  // entropy_muxed_req[1].tvalid
`SEP_TB_OUT(logic, axis1_tready_o)  // entropy_muxed_rsp[1].tready
`SEP_TB_OUT(logic [31:0], axis1_tdata_o)  // entropy_muxed_req[1].tdata (32b word)
// CHK5 entropy-pool sink (EDN endpoint [2]): AXIS2 is the pre-adapter mux-leg
// stream (entropy_muxed_req[2]); pool_edn_* is the post-adapter native EDN
// handshake into sep_entropy_fifo (one client, so AXIS2==pool beats in order).
// Observation-only XMR, no force. No frontdoor equivalent of the 32-bit EDN
// beat -- the 0x1095 aperture is a packed 64-bit FIFO drain.
`SEP_TB_OUT(logic, axis2_tvalid_o)  // entropy_muxed_req[2].tvalid
`SEP_TB_OUT(logic, axis2_tready_o)  // entropy_muxed_rsp[2].tready
`SEP_TB_OUT(logic [31:0], axis2_tdata_o)  // entropy_muxed_req[2].tdata (32b word)
`SEP_TB_OUT(logic, pool_edn_req_o)  // entropy_pool_edn_req_i.edn_req
`SEP_TB_OUT(logic, pool_edn_ack_o)  // entropy_pool_edn_rsp_o.edn_ack
`SEP_TB_OUT(logic [31:0], pool_edn_bus_o)  // entropy_pool_edn_rsp_o.edn_bus
`SEP_TB_OUT(logic, pool_edn_fips_o)  // entropy_pool_edn_rsp_o.edn_fips
// Observation-only depth of the fabric pool's 32->64 packer. Used to
// trigger a TRNG reset with exactly one pre-reset 32-bit half-word cached.
`SEP_TB_OUT(logic [1:0], entropy_pool_packer_depth_o)
// Coordinated-reset observation: shared reset plus ESRC/CSRNG/EDN isolate
// completion bits, used to prove reset cannot precede the slowest drain.
`SEP_TB_OUT(logic, trng_gated_rst_n_probe_o)
`SEP_TB_OUT(logic, trng_reset_active_probe_o)
`SEP_TB_OUT(logic [2:0], trng_axi_isolated_probe_o)
// Same observation for the HMAC accelerator domain. An accelerator reset
// depends on BOTH its host path and its Key Manager path, so both isolate
// completion bits are exposed. Each bit is named here rather than exposing the
// packed sep_crypto_isolate_t vector, so no test has to hand-derive a field
// position from the struct declaration.
`SEP_TB_OUT(logic, hmac_gated_rst_n_probe_o)
`SEP_TB_OUT(logic, hmac_host_isolated_probe_o)
`SEP_TB_OUT(logic, hmac_km_isolated_probe_o)
// Host-path isolate request, high from the software reset request until
// release. See "Crypto reset-sequencer probes" in
// hw/sys/sep/dv/docs/SEP_TB_ARCH.adoc.
`SEP_TB_OUT(logic, hmac_host_isolate_req_probe_o)
`SEP_TB_OUT(logic, kmac_gated_rst_n_probe_o)
`SEP_TB_OUT(logic, kmac_host_isolated_probe_o)
`SEP_TB_OUT(logic, kmac_km_isolated_probe_o)
`SEP_TB_OUT(logic, kmac_host_isolate_req_probe_o)
`SEP_TB_OUT(logic, abr_gated_rst_n_probe_o)
`SEP_TB_OUT(logic, abr_host_isolated_probe_o)
`SEP_TB_OUT(logic, abr_km_isolated_probe_o)
`SEP_TB_OUT(logic, abr_host_isolate_req_probe_o)
// AES and OTBN gated resets, for timing the crypto EDN endpoint cancel against
// the reset it precedes.
`SEP_TB_OUT(logic, aes_gated_rst_n_probe_o)
`SEP_TB_OUT(logic, otbn_gated_rst_n_probe_o)
// IP-interrupt aggregator: observation-only mirror of the NUM_INTERNAL_IRQS-bit
// sep_internal_interrupts vector that sep.sv assembles and feeds to the VeeR
// PIC. The IP->aggregator test injects each CSRNG/EDN INTR_TEST and watches the
// mapped bit here. Read-only XMR, no force (same class as the probes above).
`SEP_TB_OUT(logic [sep_pkg::NUM_INTERNAL_IRQS-1:0], sep_internal_interrupts_probe_o)
// Saturating count of cycles where CPU-LSU and DMA simultaneously present an
// SRAM request on the same local-crossbar address channel.
`SEP_TB_OUT(logic [31:0], dma_cpu_sram_overlap_count_o)
// SPI-to-DMA transmit pacing, observation-only: the OpenTitan SPI host
// transmit-FIFO depth, the SPI trigger bit at the secure DMA input, and the
// DMA STATUS.busy flop. No CSR shows the trigger or the FIFO depth while the
// DMA moves data, so the DMA-TX test reads them here to grade the refill
// pacing (owner `sep_spi_ot_dma_tx_test`).
`SEP_TB_OUT(logic [7:0], spi_tx_qd_probe_o)
`SEP_TB_OUT(logic, spi_lsio_trigger_probe_o)
`SEP_TB_OUT(logic, dma_busy_probe_o)
// W handshakes at the AXI-Lite port of each fabric remap/filter slot register
// block in sep_system_csr: saturating count of all beats, saturating count of
// beats with non-zero data on a byte lane whose WSTRB bit is 0, and one sticky
// bit per slot for the second kind. Slot order: alias [15:0], AP [31:16],
// STEE [47:32], outbound filter [79:48], inbound filter [95:80].
`SEP_TB_OUT(logic [31:0], fabric_slot_w_beats_o)
`SEP_TB_OUT(logic [31:0], fabric_slot_w_fill_beats_o)
`SEP_TB_OUT(logic [95:0], fabric_slot_w_fill_seen_o)
// The production SEP debug-bus output, exposed read-only for lane-packing checks.
`SEP_TB_OUT(logic [383:0], ext_debug_bus_o)
`SEP_TB_OUT(logic [15:0], efuse_debug_bus_o)
// System-CSR AXI4-Lite AR/AW handshakes after axi_to_axi_lite
// (sep_system_peripherals_xbar u_system_csr_a2l_1). Observation-only.
// fabric.adoc "convert burst to single" is this bridge. The external master
// sees AxLEN=1; Lite has no AxLEN, so the split is not a frontdoor CSR. Addr
// is the local 32 bits (scratch is in the 32-bit map). Outside the tb s_axi /
// m_axi ready/valid cones.
`SEP_TB_OUT(logic, sys_csr_axil_arvalid_o)
`SEP_TB_OUT(logic, sys_csr_axil_arready_o)
`SEP_TB_OUT(logic [31:0], sys_csr_axil_araddr_o)
`SEP_TB_OUT(logic, sys_csr_axil_awvalid_o)
`SEP_TB_OUT(logic, sys_csr_axil_awready_o)
`SEP_TB_OUT(logic [31:0], sys_csr_axil_awaddr_o)
// AR/AW handshakes at the local crossbar's `ext` initiator: the requests
// sep_system_peripherals forwards into the local crossbar (SMN inbound traffic,
// and local-master traffic that the peripheral crossbar does not decode).
// Observation-only, outside the tb s_axi / m_axi ready/valid cones.
`SEP_TB_OUT(logic, xbar_ext_in_arvalid_o)
`SEP_TB_OUT(logic, xbar_ext_in_arready_o)
`SEP_TB_OUT(logic [31:0], xbar_ext_in_araddr_o)
`SEP_TB_OUT(logic, xbar_ext_in_awvalid_o)
`SEP_TB_OUT(logic, xbar_ext_in_awready_o)
`SEP_TB_OUT(logic [31:0], xbar_ext_in_awaddr_o)
// Fabric observation taps (docs/SEP_TB_ARCH.adoc, observation-probe list).
// Read-only copies of DUT nets: each AXI tap carries the AW and AR VALID,
// READY and request fields, and the W beat where named. A handshake is
// VALID and READY high on one clk_i edge. Outside every tb ready/valid cone.
// PR-OUT: smn_outbound_axi_req_o (the net smn_outbound_req_w).
`SEP_TB_OUT(logic, pr_out_awvalid_o)
`SEP_TB_OUT(logic, pr_out_awready_o)
`SEP_TB_OUT(logic [55:0], pr_out_awaddr_o)
`SEP_TB_OUT(logic [7:0], pr_out_awid_o)
`SEP_TB_OUT(logic [11:0], pr_out_awuser_o)
`SEP_TB_OUT(logic [3:0], pr_out_awcache_o)
`SEP_TB_OUT(logic [2:0], pr_out_awprot_o)
`SEP_TB_OUT(logic [7:0], pr_out_awlen_o)
`SEP_TB_OUT(logic [2:0], pr_out_awsize_o)
`SEP_TB_OUT(logic [1:0], pr_out_awburst_o)
`SEP_TB_OUT(logic, pr_out_arvalid_o)
`SEP_TB_OUT(logic, pr_out_arready_o)
`SEP_TB_OUT(logic [55:0], pr_out_araddr_o)
`SEP_TB_OUT(logic [7:0], pr_out_arid_o)
`SEP_TB_OUT(logic [11:0], pr_out_aruser_o)
`SEP_TB_OUT(logic [3:0], pr_out_arcache_o)
`SEP_TB_OUT(logic [2:0], pr_out_arprot_o)
`SEP_TB_OUT(logic [7:0], pr_out_arlen_o)
`SEP_TB_OUT(logic [2:0], pr_out_arsize_o)
`SEP_TB_OUT(logic [1:0], pr_out_arburst_o)
`SEP_TB_OUT(logic, pr_out_wvalid_o)
`SEP_TB_OUT(logic, pr_out_wready_o)
`SEP_TB_OUT(logic [63:0], pr_out_wdata_o)
`SEP_TB_OUT(logic [7:0], pr_out_wstrb_o)
`SEP_TB_OUT(logic, pr_out_wlast_o)
// PR-SMC: sep_ext_to_smc_axi_req_o (the net ext_to_smc_req_w).
`SEP_TB_OUT(logic, pr_smc_awvalid_o)
`SEP_TB_OUT(logic, pr_smc_awready_o)
`SEP_TB_OUT(logic [55:0], pr_smc_awaddr_o)
`SEP_TB_OUT(logic [5:0], pr_smc_awid_o)
`SEP_TB_OUT(logic [11:0], pr_smc_awuser_o)
`SEP_TB_OUT(logic [3:0], pr_smc_awcache_o)
`SEP_TB_OUT(logic [2:0], pr_smc_awprot_o)
`SEP_TB_OUT(logic [7:0], pr_smc_awlen_o)
`SEP_TB_OUT(logic [2:0], pr_smc_awsize_o)
`SEP_TB_OUT(logic [1:0], pr_smc_awburst_o)
`SEP_TB_OUT(logic, pr_smc_arvalid_o)
`SEP_TB_OUT(logic, pr_smc_arready_o)
`SEP_TB_OUT(logic [55:0], pr_smc_araddr_o)
`SEP_TB_OUT(logic [5:0], pr_smc_arid_o)
`SEP_TB_OUT(logic [11:0], pr_smc_aruser_o)
`SEP_TB_OUT(logic [3:0], pr_smc_arcache_o)
`SEP_TB_OUT(logic [2:0], pr_smc_arprot_o)
`SEP_TB_OUT(logic [7:0], pr_smc_arlen_o)
`SEP_TB_OUT(logic [2:0], pr_smc_arsize_o)
`SEP_TB_OUT(logic [1:0], pr_smc_arburst_o)
`SEP_TB_OUT(logic, pr_smc_wvalid_o)
`SEP_TB_OUT(logic, pr_smc_wready_o)
`SEP_TB_OUT(logic [63:0], pr_smc_wdata_o)
`SEP_TB_OUT(logic [7:0], pr_smc_wstrb_o)
`SEP_TB_OUT(logic, pr_smc_wlast_o)
// PR-EXT: the AXI Extension port, wrapper net u_dut.axi_extension_axi_req.
`SEP_TB_OUT(logic, pr_ext_awvalid_o)
`SEP_TB_OUT(logic, pr_ext_awready_o)
`SEP_TB_OUT(logic [31:0], pr_ext_awaddr_o)
`SEP_TB_OUT(logic [5:0], pr_ext_awid_o)
`SEP_TB_OUT(logic [11:0], pr_ext_awuser_o)
`SEP_TB_OUT(logic [3:0], pr_ext_awcache_o)
`SEP_TB_OUT(logic [2:0], pr_ext_awprot_o)
`SEP_TB_OUT(logic [7:0], pr_ext_awlen_o)
`SEP_TB_OUT(logic [2:0], pr_ext_awsize_o)
`SEP_TB_OUT(logic [1:0], pr_ext_awburst_o)
`SEP_TB_OUT(logic, pr_ext_arvalid_o)
`SEP_TB_OUT(logic, pr_ext_arready_o)
`SEP_TB_OUT(logic [31:0], pr_ext_araddr_o)
`SEP_TB_OUT(logic [5:0], pr_ext_arid_o)
`SEP_TB_OUT(logic [11:0], pr_ext_aruser_o)
`SEP_TB_OUT(logic [3:0], pr_ext_arcache_o)
`SEP_TB_OUT(logic [2:0], pr_ext_arprot_o)
`SEP_TB_OUT(logic [7:0], pr_ext_arlen_o)
`SEP_TB_OUT(logic [2:0], pr_ext_arsize_o)
`SEP_TB_OUT(logic [1:0], pr_ext_arburst_o)
`SEP_TB_OUT(logic, pr_ext_wvalid_o)
`SEP_TB_OUT(logic, pr_ext_wready_o)
`SEP_TB_OUT(logic [63:0], pr_ext_wdata_o)
`SEP_TB_OUT(logic [7:0], pr_ext_wstrb_o)
`SEP_TB_OUT(logic, pr_ext_wlast_o)
// PR-DMACSR: the request at the DMA CSR target port (sep.sv dma_csr_req).
`SEP_TB_OUT(logic, pr_dmacsr_awvalid_o)
`SEP_TB_OUT(logic, pr_dmacsr_awready_o)
`SEP_TB_OUT(logic [31:0], pr_dmacsr_awaddr_o)
`SEP_TB_OUT(logic, pr_dmacsr_arvalid_o)
`SEP_TB_OUT(logic, pr_dmacsr_arready_o)
`SEP_TB_OUT(logic [31:0], pr_dmacsr_araddr_o)
// PR-INFLT: the request out of the inbound filter (u_inbound_filter), before
// the global-to-local remap; it carries the global address.
`SEP_TB_OUT(logic, pr_inflt_awvalid_o)
`SEP_TB_OUT(logic, pr_inflt_awready_o)
`SEP_TB_OUT(logic [55:0], pr_inflt_awaddr_o)
`SEP_TB_OUT(logic, pr_inflt_arvalid_o)
`SEP_TB_OUT(logic, pr_inflt_arready_o)
`SEP_TB_OUT(logic [55:0], pr_inflt_araddr_o)
// PR-ALIAS input: the request into u_local_master_remap_wrap.
`SEP_TB_OUT(logic, pr_alias_in_awvalid_o)
`SEP_TB_OUT(logic, pr_alias_in_awready_o)
`SEP_TB_OUT(logic [55:0], pr_alias_in_awaddr_o)
`SEP_TB_OUT(logic [3:0], pr_alias_in_awcache_o)
`SEP_TB_OUT(logic [2:0], pr_alias_in_awprot_o)
`SEP_TB_OUT(logic, pr_alias_in_arvalid_o)
`SEP_TB_OUT(logic, pr_alias_in_arready_o)
`SEP_TB_OUT(logic [55:0], pr_alias_in_araddr_o)
`SEP_TB_OUT(logic [3:0], pr_alias_in_arcache_o)
`SEP_TB_OUT(logic [2:0], pr_alias_in_arprot_o)
// PR-ALIAS output: the request out of u_local_master_remap_wrap.
`SEP_TB_OUT(logic, pr_alias_out_awvalid_o)
`SEP_TB_OUT(logic, pr_alias_out_awready_o)
`SEP_TB_OUT(logic [55:0], pr_alias_out_awaddr_o)
`SEP_TB_OUT(logic [3:0], pr_alias_out_awcache_o)
`SEP_TB_OUT(logic [2:0], pr_alias_out_awprot_o)
`SEP_TB_OUT(logic, pr_alias_out_arvalid_o)
`SEP_TB_OUT(logic, pr_alias_out_arready_o)
`SEP_TB_OUT(logic [55:0], pr_alias_out_araddr_o)
`SEP_TB_OUT(logic [3:0], pr_alias_out_arcache_o)
`SEP_TB_OUT(logic [2:0], pr_alias_out_arprot_o)
// PR-SRAM: the SRAM macro request (wrapper net u_dut.sep_sram_req) and response.
`SEP_TB_OUT(logic, pr_sram_req_o)
`SEP_TB_OUT(logic, pr_sram_gnt_o)
`SEP_TB_OUT(logic [31:0], pr_sram_addr_o)
`SEP_TB_OUT(logic, pr_sram_we_o)
`SEP_TB_OUT(logic [63:0], pr_sram_wdata_o)
`SEP_TB_OUT(logic [7:0], pr_sram_strb_o)
`SEP_TB_OUT(logic, pr_sram_rvalid_o)
`SEP_TB_OUT(logic [63:0], pr_sram_rdata_o)
// PR-ROM: the boot ROM macro request (wrapper net u_dut.sep_boot_rom_req) and response.
`SEP_TB_OUT(logic, pr_rom_req_o)
`SEP_TB_OUT(logic, pr_rom_gnt_o)
`SEP_TB_OUT(logic [31:0], pr_rom_addr_o)
`SEP_TB_OUT(logic, pr_rom_we_o)
`SEP_TB_OUT(logic [63:0], pr_rom_wdata_o)
`SEP_TB_OUT(logic [7:0], pr_rom_strb_o)
`SEP_TB_OUT(logic, pr_rom_rvalid_o)
`SEP_TB_OUT(logic [63:0], pr_rom_rdata_o)
// BH-SMC (docs/SEP_TB_ARCH.adoc, HDL Top port table). A leaf drives these
// before it releases reset; bh_smc_en_i other than 1 leaves the hook off.
`SEP_TB_IN(logic, bh_smc_en_i)
`SEP_TB_IN(logic [55:0], bh_smc_base_i)
`SEP_TB_IN(logic [55:0], bh_smc_size_i)
// Lifecycle status observability. security_disable and lc_sigint_err are DUT
// outputs (frontdoor). secure_tm_o is also a real DUT output -- the latched
// TEST_EN strap -- so a strap test can observe the latch rather than assume it.
`SEP_TB_OUT(logic, lcc_security_disable_probe_o)
`SEP_TB_OUT(logic, lcc_sigint_err_probe_o)
`SEP_TB_OUT(logic, secure_tm_o)
// RMA_SIP digest-latch scan-freeze observability: the retained-digest sticky
// latch and its enable/valid chain, tapped so a fault-injection test can
// watch capture, hold, and DFT-freeze behavior without a force.
`SEP_TB_OUT(logic [255:0], token_digest_sticky_o)
`SEP_TB_OUT(logic, token_digest_valid_o)
`SEP_TB_OUT(logic, token_digest_test_en_o)
`SEP_TB_OUT(logic, token_digest_latch_en_pre_o)
`SEP_TB_OUT(logic, token_digest_valid_en_pre_o)
`SEP_TB_OUT(logic, token_digest_latch_en_o)
`SEP_TB_OUT(logic, token_digest_valid_en_o)

// eFuse read/program FSM fail-closed observability and fault injection.
// `efuse_read_interface` and `efuse_program_interface` each hold a two-bit
// state whose only legal encodings are 2'b01 and 2'b10; 2'b00 and 2'b11 are
// unreachable by any frontdoor stimulus, so the fail-closed behaviour the
// design asserts on them has no other way to be provoked. The inject inputs
// drive one illegal encoding for one cycle; the probes are read-only taps on
// the state and on the error/data outputs the contract names.
`SEP_TB_IN(logic [1:0], efuse_read_state_inject_i)
`SEP_TB_IN(logic, efuse_read_state_inject_en_i)
`SEP_TB_IN(logic [1:0], efuse_program_state_inject_i)
`SEP_TB_IN(logic, efuse_program_state_inject_en_i)
`SEP_TB_OUT(logic [1:0], efuse_read_state_o)
`SEP_TB_OUT(logic [1:0], efuse_program_state_o)
`SEP_TB_OUT(logic, efuse_read_error_o)
`SEP_TB_OUT(logic, efuse_read_done_o)
`SEP_TB_OUT(logic, efuse_read_busy_o)
`SEP_TB_OUT(logic [31:0], efuse_read_back_data_o)
// One per interface: each drives its own command request, and checking the
// program machine against the read machine's request would hold on any RTL.
`SEP_TB_OUT(logic, efuse_read_cmd_req_valid_o)
`SEP_TB_OUT(logic, efuse_program_cmd_req_valid_o)
// The program interface's retirement outputs, so its fail-closed leg grades the
// same contract the read leg does rather than only the absence of a command.
`SEP_TB_OUT(logic, efuse_program_error_o)
`SEP_TB_OUT(logic, efuse_program_done_o)
`SEP_TB_OUT(logic, efuse_program_busy_o)
`SEP_TB_OUT(logic [31:0], efuse_program_read_back_data_o)
// Demotion state outputs expose the differential {~demote, demote} encoding;
// 2'b10 is clear, 2'b01 is set, and other values are invalid. The lock bits
// have no DUT output, and the CPU owns their AXI frontdoor during firmware
// boot, so read-only XMRs observe the register storage. The leaf register
// storage sits outside the AXI ready/valid combinational cones.
`SEP_TB_OUT(logic [1:0], lcc_demote_state_1_probe_o)
`SEP_TB_OUT(logic [1:0], lcc_demote_state_2_probe_o)
`SEP_TB_OUT(logic, lcc_demote_lock_1_probe_o)
`SEP_TB_OUT(logic, lcc_demote_lock_2_probe_o)
// The packed 64-bit sep_efuse_map_lc_disable_reg_t feature-control vector,
// read-only XMR.
`SEP_TB_OUT(logic [63:0], lcc_feat_ctrl_probe_o)
// Each dbg_disable_o bit as its own DUT-output port (frontdoor). Checkers
// read these by name so a packed-struct reorder cannot swap two same-case
// bits past the golden. The flattened vector stays for a width self-test.
`SEP_TB_OUT(logic, dbg_disable_stap_io_o)
`SEP_TB_OUT(logic, dbg_disable_stap_smc_o)
`SEP_TB_OUT(logic, dbg_disable_stap_sep_o)
`SEP_TB_OUT(logic, dbg_disable_stap_extra_o)
`SEP_TB_OUT(logic, dbg_disable_stap_host_o)
`SEP_TB_OUT(logic, dbg_disable_dft_secure_o)
`SEP_TB_OUT(logic, dbg_disable_dft_nonsecure_o)
`SEP_TB_OUT(logic, dbg_disable_dfd_o)
`SEP_TB_OUT(logic, dbg_disable_smc_jtag2axi_o)
`SEP_TB_OUT(logic, dbg_disable_smc_otp_jtag2axi_o)
`SEP_TB_OUT(logic, dbg_disable_sep_otp_jtag2axi_o)
`SEP_TB_OUT(logic [$bits(sep_lifecycle_ctrl_pkg::dbg_disable_t)-1:0], dbg_disable_all_o)
// DFT-inserted fuse-path disables. Real DUT outputs (sep_wrapper), not
// internal probes: no functional consumer and no CSR mirror. Disable
// polarity: SEP is Case 3 AND sep_fuse_dbg (bit 2), inverted; SMC is
// Case 2 AND smc_fuse_dbg (bit 3), inverted.
`SEP_TB_OUT(logic, sep_fuse_dft_disable_o)
`SEP_TB_OUT(logic, smc_fuse_dft_disable_o)
// WDT bite reset request: a REAL `sep` output port (sep.sv wdt_timer_rst_req_o,
// asserted when the WDT count reaches BITE_THOLD). Brought out so the
// reset/WDT sanity test (`sep_reset_wdt_sanity_test`) can observe the bite ->
// reset-request edge. This is a DUT output (frontdoor), not an
// internal-signal probe.
`SEP_TB_OUT(logic, wdt_timer_rst_req_o)
// SMC-facing mailbox interrupt: a REAL `sep` output port
// (sep.sv smc_mailbox_interrupt_o, fed by the mailbox block's
// outbound_interrupt_o). It leaves the block instead of reaching the SEP CPU
// PIC, so nothing inside sep observes it. Brought out so the mailbox delivery
// test can prove the direction: a push at the inbound aperture raises the CPU
// PIC source and leaves this line low; a push at the outbound aperture raises
// this line and no PIC source. One bit per mailbox channel.
`SEP_TB_OUT(logic [sep_pkg::NumMailboxes-1:0], smc_mailbox_interrupt_o)
`SEP_TB_OUT(logic, spi_cs_n_o)
`SEP_TB_OUT(logic, spi_sck_o)
`SEP_TB_OUT(logic, spi_mosi_o)
`SEP_TB_IN(logic, spi_miso_i)
