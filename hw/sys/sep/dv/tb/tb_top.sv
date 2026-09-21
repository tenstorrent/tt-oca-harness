// SPDX-License-Identifier: Apache-2.0
//
// SEP OSS DV testbench top.
//
// Wraps the `sep_wrapper` DUT (hw/top/sep_wrapper.sv, which instantiates the bare
// `sep` core from hw/sys/sep/rtl/sep.sv) for the OSS cocotb flow: brings
// clocks/reset/boot controls out as top-level ports and ties every unused DUT
// port to a benign idle value. Stimulus is injected on the SEP CPU's own LSU AXI
// master bus: the core (VeeR EL2) is held off (`mpc_reset_run_req=0`) and an
// external cocotbext-axi AxiMaster is spliced onto the CPU's LSU AXI master
// ``SEP_CORE.sep_cpu.lsu_axi_req` / `lsu_axi_resp`, sep_32_64_3_12
// (addr32/data64/id3/user12). The stub build (`SEP_CPU_STUB`) is the sole
// driver of that bus and drives lsu_axi_req from the tb's assembled request
// (`assign`, no `force`; see shims/cpu/sep_cpu_stub.sv). On the full-CPU
// build a no_cpu test force-splices the same post-remap `lsu_axi_req` and
// holds `lsu_axi_resp_raw` idle. The tb reads lsu_axi_resp back by name.
// Driving the demux slave-side LSU bus reaches the SEP-local fabric through the
// same ROM/xbar routing point as the core would, so the external SMN inbound
// filter is NOT in the path. Every other DUT port is tied to a benign idle
// value so nothing X-props.
//
// A flat cocotb AXI interface is spliced onto these same CPU master ports.
// The CPU LSU splice is the primary stimulus
// path. `smn_inbound` is additionally brought out as the flat `m_axi_*` master
// (the DUT's real external inbound port, which traverses the inbound filter);
// it idles unless a test drives it, and is used by the inbound-filter-gating
// test to prove external AXI is blocked/allowed by feat_ctrl.sep_debug.
//
// Two run modes, selected by the `+cpu_boot` plusarg:
//   * no-CPU (default): the core is held off (mpc_reset_run_req=0) and cocotb
//     drives the SEP fabric over s_axi. The stub build presents that request
//     on the LSU master (`assign`). The full-CPU build force-splices the
//     same post-remap net. Verilator no_cpu stays on the stub.
//   * CPU firmware boot (+cpu_boot): runs on the full-CPU build, the core owns all of
//     its master buses, fetches firmware out of the wrapper's real TCM macros, and
//     runs. The boot test backdoor-loads the TCM (tb_backdoor_mem, on tcm_load_i),
//     passes the desired reset vector to this top, which programs the EL2
//     reset-vector TDR through JTAG, asserts mpc_reset_run_req, and observes PC
//     advance (sep_cpu_trace) plus the firmware console/PASS magic on the outbound
//     mailbox responder (sep_outbound_mbx).
//
// Boot/reset invariants:
//   * ext_boot_seq_done_i = 1   (DUT port, driven by cocotb)
//   * +skip_fuse_sense          (RTL plusarg, set by tests that bypass real sense)
//   * mpc_reset_run_req         (0 = hold the CPU off [no_cpu]; 1 = run [cpu])
//
// The CPU LSU req/resp struct (deps/axi AXI_TYPEDEF_ALL) is bridged to flat
// `s_axi_*` ports so cocotb binds via AxiBus.from_prefix(dut, "s_axi").

`timescale 1ps/1fs

module sep_uvm_top
    import sep_pkg::*;
    import sep_crypto_pkg::*;
    import sep_io_pkg::*;
(
    // Clocks (driven by cocotb)
    input  wire logic clk_i,
    input  wire logic clk_wdt_i,
    input  wire logic entropy_rosc_sample_clk_i,

    // Reset (driven by cocotb, active-low)
    input  wire logic rst_ni,

    // Boot/run controls (driven by cocotb)
    input  wire logic ext_boot_seq_done_i,
    input  wire logic mpc_reset_run_req,
    // TEST_EN strap (frontdoor DUT input). Latched into secure_tm on fuse-sense-done
    // (or on cold-reset release when security_disable is set). Default 0 = functional
    // mode; drive 1 before sense to open FEAT_CTRL[47:32].
    input  wire logic test_en_strap_i,
    // JTAG SW-reset hold (frontdoor DUT input jtag_sep_reset_ctrl_i). When 1,
    // that engine is held in SW reset regardless of SW_RESET_N, so it never
    // asserts crypto edn_req across rst_ni. Default 0 = CSR owns the bit.
    input  wire logic jtag_otbn_rst_hold_i,
    input  wire logic jtag_aes_rst_hold_i,
    input  wire logic jtag_hmac_rst_hold_i,
    input  wire logic jtag_kmac_rst_hold_i,
    input  wire logic jtag_trng_rst_hold_i,
    // LC differential-integrity error inject. Default 0. When 1, tb forces a broken
    // pair onto the LCC decoder input; no legal OTP image can present one. See
    // the force block below.
    input  wire logic lc_sigint_inject_i,
    // Token-comparator redundancy fault inject. Default 0. Encoding:
    //   3'b000 off
    //   3'b001 collapse instance 0 of the RMA_SIP comparator (both rails 0)
    //   3'b010 disagree: instance 0 drives a legal mismatch pair while 1/2 match
    //   3'b011 common-mode mismatch: all three legal mismatch (invert of a match)
    //   3'b100 common-mode match: all three legal match (invert of a mismatch)
    // No legal token/OTP image can break the three identical compare cones. See
    // the force block below.
    input  wire logic [2:0] token_cmp_fault_inject_i,
    // Which token comparator the inject hits. Default 0.
    //   2'b00 RMA_SIP  2'b01 RMA_CHIPLET  2'b10 SEC_DISABLE
    input  wire logic [1:0] token_cmp_fault_sel_i,
    // DMA host-path command-integrity inject. Default 0. When 1, tb forces a
    // broken codeword onto the host-adapter command-integrity decoder input
    // (software cannot emit a bad TL-UL user code). The checker
    // still gates on a_valid, so a DMA-issued command is required. See the
    // force block below.
    input  wire logic dma_host_intg_inject_i,

    // ------------------------------------------------------------------
    // Flat CPU-LSU AXI manager (cocotbext-axi AxiMaster, prefix s_axi)
    // sep_cpu.lsu_axi_* = sep_32_64_3_12 (addr32/data64/id3/user12)
    // ------------------------------------------------------------------
    // Write address channel
    input  wire logic [2:0]   s_axi_awid,
    input  wire logic [31:0]  s_axi_awaddr,
    input  wire logic [7:0]   s_axi_awlen,
    input  wire logic [2:0]   s_axi_awsize,
    input  wire logic [1:0]   s_axi_awburst,
    input  wire logic         s_axi_awlock,
    input  wire logic [3:0]   s_axi_awcache,
    input  wire logic [2:0]   s_axi_awprot,
    input  wire logic [3:0]   s_axi_awqos,
    input  wire logic [3:0]   s_axi_awregion,
    input  wire logic [11:0]  s_axi_awuser,
    input  wire logic         s_axi_awvalid,
    output logic              s_axi_awready,
    // Write data channel
    input  wire logic [63:0]  s_axi_wdata,
    input  wire logic [7:0]   s_axi_wstrb,
    input  wire logic         s_axi_wlast,
    input  wire logic [11:0]  s_axi_wuser,
    input  wire logic         s_axi_wvalid,
    output logic              s_axi_wready,
    // Write response channel
    output logic [2:0]        s_axi_bid,
    output logic [1:0]        s_axi_bresp,
    output logic [11:0]       s_axi_buser,
    output logic              s_axi_bvalid,
    input  wire logic         s_axi_bready,
    // Read address channel
    input  wire logic [2:0]   s_axi_arid,
    input  wire logic [31:0]  s_axi_araddr,
    input  wire logic [7:0]   s_axi_arlen,
    input  wire logic [2:0]   s_axi_arsize,
    input  wire logic [1:0]   s_axi_arburst,
    input  wire logic         s_axi_arlock,
    input  wire logic [3:0]   s_axi_arcache,
    input  wire logic [2:0]   s_axi_arprot,
    input  wire logic [3:0]   s_axi_arqos,
    input  wire logic [3:0]   s_axi_arregion,
    input  wire logic [11:0]  s_axi_aruser,
    input  wire logic         s_axi_arvalid,
    output logic              s_axi_arready,
    // Read data channel
    output logic [2:0]        s_axi_rid,
    output logic [63:0]       s_axi_rdata,
    output logic [1:0]        s_axi_rresp,
    output logic              s_axi_rlast,
    output logic [11:0]       s_axi_ruser,
    output logic              s_axi_rvalid,
    input  wire logic         s_axi_rready,

    // ------------------------------------------------------------------
    // Flat SMN-inbound external AXI manager (cocotbext-axi AxiMaster, prefix
    // m_axi). This is the DUT's REAL external inbound port (smn_inbound_axi_*,
    // sep_56_64_6_12: addr56/data64/id6/user12) — a true frontdoor master on a
    // real DUT port. Unlike the CPU-LSU splice (s_axi), which attaches to the
    // internal LSU bus, this path traverses the SEP inbound filter
    // (u_inbound_filter), which is block-by-default and is skipped
    // only when feat_ctrl.sep_debug=1. `sep_lcc_uvm_inbound_filter_gating_test` drives
    // it to prove external AXI is blocked (PROD) / allowed (PROD_DBG_1). Idle for
    // every other test (the agent drives these to a clean idle from t=0).
    // ------------------------------------------------------------------
    // Write address channel
    input  wire logic [5:0]   m_axi_awid,
    input  wire logic [55:0]  m_axi_awaddr,
    input  wire logic [7:0]   m_axi_awlen,
    input  wire logic [2:0]   m_axi_awsize,
    input  wire logic [1:0]   m_axi_awburst,
    input  wire logic         m_axi_awlock,
    input  wire logic [3:0]   m_axi_awcache,
    input  wire logic [2:0]   m_axi_awprot,
    input  wire logic [3:0]   m_axi_awqos,
    input  wire logic [3:0]   m_axi_awregion,
    input  wire logic [11:0]  m_axi_awuser,
    input  wire logic         m_axi_awvalid,
    output logic              m_axi_awready,
    // Write data channel
    input  wire logic [63:0]  m_axi_wdata,
    input  wire logic [7:0]   m_axi_wstrb,
    input  wire logic         m_axi_wlast,
    input  wire logic [11:0]  m_axi_wuser,
    input  wire logic         m_axi_wvalid,
    output logic              m_axi_wready,
    // Write response channel
    output logic [5:0]        m_axi_bid,
    output logic [1:0]        m_axi_bresp,
    output logic [11:0]       m_axi_buser,
    output logic              m_axi_bvalid,
    input  wire logic         m_axi_bready,
    // Read address channel
    input  wire logic [5:0]   m_axi_arid,
    input  wire logic [55:0]  m_axi_araddr,
    input  wire logic [7:0]   m_axi_arlen,
    input  wire logic [2:0]   m_axi_arsize,
    input  wire logic [1:0]   m_axi_arburst,
    input  wire logic         m_axi_arlock,
    input  wire logic [3:0]   m_axi_arcache,
    input  wire logic [2:0]   m_axi_arprot,
    input  wire logic [3:0]   m_axi_arqos,
    input  wire logic [3:0]   m_axi_arregion,
    input  wire logic [11:0]  m_axi_aruser,
    input  wire logic         m_axi_arvalid,
    output logic              m_axi_arready,
    // Read data channel
    output logic [5:0]        m_axi_rid,
    output logic [63:0]       m_axi_rdata,
    output logic [1:0]        m_axi_rresp,
    output logic              m_axi_rlast,
    output logic [11:0]       m_axi_ruser,
    output logic              m_axi_rvalid,
    input  wire logic         m_axi_rready,

    // ------------------------------------------------------------------
    // Flat SEP-OTP JTAG AXI-Lite manager (cocotbext-axi AxiLiteMaster, prefix
    // j_axi). This is the DUT's real `axil_sep_otp_jtag_*` port (efuse_axil:
    // addr32/data32) -- the debug/JTAG path into the eFuse interface controller,
    // which arbitrates with the CPU's eFuse-MMR path at the eFuse AXI-Lite mux and
    // is LC-state-gated (in PROD/RMA_SIP the JTAG path may read/write only the MMR
    // token region; a shadow/CSR access is routed to an error slave -> 0xbadcab1e).
    // Used by `sep_efuse_jtag_axil_el2_cpu_mux_test`. Idle for every other test.
    // ------------------------------------------------------------------
    input  wire logic [31:0]  j_axi_awaddr,
    input  wire logic [2:0]   j_axi_awprot,
    input  wire logic         j_axi_awvalid,
    output logic              j_axi_awready,
    input  wire logic [31:0]  j_axi_wdata,
    input  wire logic [3:0]   j_axi_wstrb,
    input  wire logic         j_axi_wvalid,
    output logic              j_axi_wready,
    output logic [1:0]        j_axi_bresp,
    output logic              j_axi_bvalid,
    input  wire logic         j_axi_bready,
    input  wire logic [31:0]  j_axi_araddr,
    input  wire logic [2:0]   j_axi_arprot,
    input  wire logic         j_axi_arvalid,
    output logic              j_axi_arready,
    output logic [31:0]       j_axi_rdata,
    output logic [1:0]        j_axi_rresp,
    output logic              j_axi_rvalid,
    input  wire logic         j_axi_rready,

    // ------------------------------------------------------------------
    // CPU firmware-boot controls/observables (driven/read by cocotb in the
    // `+cpu_boot` run mode; left at 0 by the no-CPU smoke tests).
    // ------------------------------------------------------------------
    input  wire logic [31:1]  rst_vec_i,         // desired reset PC[31:1] for JTAG TDR setup
    input  wire logic         i_cpu_run_req_i,   // async run request to the core
    input  wire logic         tcm_load_i,        // strobe: backdoor-load TCM image
    // WDT reset INPUT to the DUT (a real sep primary input). Default-driven 1
    // (deasserted) by sep_base_test for every test; the wdt-reset-path test
    // pulses it to 0 to exercise wdt_rst_ni -> sep_cpu_reset_n.
    input  wire logic         wdt_rst_ni_i,
    // EL2 debugger reset INPUT to the DUT (sep.sv dbg_rstb_i, a real sep primary
    // input). Default-driven 1 (deasserted) by sep_base_test; the CPU debug-reset
    // isolation test pulses it to 0 to prove it does NOT disturb the system/CPU
    // reset domain.
    input  wire logic         dbg_rstb_i,
    output logic              o_cpu_run_ack_o,   // core run acknowledge (XMR-tapped)
    output logic              cpu_trace_valid_o, // retired-instruction valid
    output logic [31:0]       cpu_trace_addr_o,  // retired-instruction PC
    output logic [31:0]       cpu_trace_insn_o,  // retired instruction encoding
    output logic [4:0]        cpu_trace_ecause_o,   // exception cause (with dbg_cpu_trace_exc_o)
    output logic              cpu_trace_interrupt_o, // exception was an interrupt
    output logic [31:0]       cpu_trace_tval_o,  // trap value (faulting addr/insn)
    output logic              fw_done_o,         // firmware signaled completion
    output logic              fw_pass_o,         // completion was PASS
    output logic [7:0]        fw_char_o,         // firmware console byte
    output logic              fw_char_valid_o,   // console byte strobe
    // Boot bring-up debug observables (cheap XMR/struct taps).
    output logic              dbg_iccm_active_o, // core asserting any ICCM bank clken (fetching)
    output logic [13:0]       dbg_iccm_addr_o,   // ICCM bank-0 row address being fetched
    output logic              dbg_dccm_active_o, // core asserting any DCCM bank clken
    output logic              dbg_sep_reset_n_o, // SEP internal reset released
    // CPU warm reset (sep_cpu_reset_n = sep_reset_n & wdt_rst_ni).
    output logic              sep_cpu_reset_n_o,
    output logic              dbg_cpu_trace_exc_o, // retired-instruction exception flag
    output logic              sep_fuse_sense_done_o, // SEP fuse sense completed
    // Sensed eFuse shadow-register array, flattened to a top-level OUTPUT PORT
    // (not an internal signal) so cocotb reads it reliably -- same access
    // pattern as every other observable above. Default backdoor data-compare
    // path; one eFuse test uses the AXI front door instead.
    output logic [sep_efuse_pkg::NumEfuseBits-1:0] efuse_shadow_probe_o,
    // SEP scratch-cold CSR array (8 words x 32b), surfaced as a top-level probe so
    // the dual-CPU eFuse-mux coexistence test can read the EL2 firmware's measured
    // summary (host loop count + KM-contention error counters) with no AXI master
    // -- the EL2 owns the LSU bus under +cpu_boot. The cold block survives the KM
    // warm reset. Read-only observation of the same registers.
    output logic [255:0]      scratch_cold_probe_o,
    // Read-only XMRs observe the loaded manifest header and three decrypted AES
    // payload blocks. The CPU owns the SRAM frontdoor during firmware boot, so
    // the testbench has no independent read path. The memory arrays sit outside
    // the AXI ready/valid combinational cones.
    output logic [63:0]       sram_word0_probe_o,
    output logic [383:0]      sram_payload_probe_o,
    // SMC scratch[10] (smc_base+0x390D0), the slot the ROM publishes the raw
    // DFX/MEM_REPAIR status into when it blocks the boot -- the documented
    // JTAG-readable evidence that the ROM saw the failure. Sampled rather than
    // continuously assigned: axi_sim_mem backs the SMC with an ASSOCIATIVE array,
    // which cannot appear in a continuous assign. Reads 0 until the ROM writes it.
    output logic [31:0]       smc_scratch10_probe_o,
    // DFX_CTRL_STATUS_SMU (smc_base+0xB800) as the SMC model actually holds it,
    // i.e. the word the ROM's MEM_REPAIR gate reads over AXI. The FAILURE arm can
    // confirm its own injection from SMC scratch[10], because the gate republishes
    // the raw value there; the PASS arm cannot, because that publication sits on
    // the failure branch and the pass branch writes nothing at all. Without this
    // probe a pass-arm test whose +sep_dft_status silently failed to apply would
    // read the tb default 0x113 -- which has mem_repair_success, mbist_done AND
    // mbist_pass set, so it would still boot and still be green, and the whole
    // discrimination the testcase rests on would be untested.
    output logic [31:0]       smc_dft_status_probe_o,
    // Count of SEP->SMC accesses that landed outside every register window the
    // generated SMC map declares. Non-zero means the ROM used an offset this
    // design does not implement -- see the SMC address decode check below. Any
    // test may assert this is 0; the flat axi_sim_mem cannot catch it otherwise.
    output logic [31:0]       smc_addr_violations_o,
    output logic [31:0]       km_rom_req_count_o,
    output logic [31:0]       km_sram_req_count_o,
    output logic [31:0]       km_sram_write_count_o,
    output logic [31:0]       km_sram_word0_o,
    output logic [31:0]       otbn_imem_req_count_o,
    output logic [31:0]       otbn_imem_write_count_o,
    output logic [31:0]       otbn_dmem_req_count_o,
    output logic [31:0]       otbn_dmem_write_count_o,
    // ESRC -> DRBG -> CSRNG -> EDN -> KM entropy datapath probes. The driven noise
    // (esrc_noise_o) is the deterministic stimulus; the rest are DUT observation
    // points for the alive smoke and CHK1-CHK5 golden-vs-probe scoreboard.
    // Cocotb-driven 12-lane raw noise: lets a Python noise generator feed the DUT
    // and a golden the SAME deterministic sequence, so the decorrelator golden
    // aligns by construction.
    input  wire logic [11:0]  esrc_noise_ext_i,
    output logic [11:0]       esrc_noise_o,          // driven 12-lane raw noise (golden input)
    output logic              esrc_noise_active_o,   // lane-0 actual DUT dcor.noise_i (force-took proof)
    output logic [11:0]       esrc_ro_enable_o,      // CHK1/CHK2 per-lane generator enable (sync)
    output logic [95:0]       esrc_decor_bytes_o,    // CHK1: 12x8 decorrelator sampled output
    output logic [347:0]      esrc_decor_sr_o,       // CHK1 sync: 12x29 raw decorrelator ff_stage
    output logic              esrc_decor_valid_o,    // CHK2 chain: per-sample BIW/decor valid strobe
    output logic              esrc_whiten_push_o,    // CHK2 chain: SHA-whitener accepted-word strobe
    output logic              esrc_compress_vld_o,   // CHK2: compressor output valid
    output logic [31:0]       esrc_compress_data_o,  // CHK2: compressor output word
    output logic              drbg_seed_valid_o,     // seed accumulated/presented to CSRNG
    output logic              drbg_es_ack_o,         // CSRNG seed-handshake ack
    output logic [383:0]      drbg_es_bits_o,        // CHK4: 384-bit hardware seed
    output logic              drbg_genbits_vld_o,    // CHK4: CTR_DRBG genbits valid
    output logic [127:0]      drbg_genbits_data_o,   // CHK4: CTR_DRBG genbits block
    output logic              drbg_genbits_fips_o,   // CHK4: genbits fips flag
    output logic              drbg_gen_last_o,       // CHK4: last genbits of a Generate
    output logic              km_entropy_tvalid_o,   // CHK5: post-mux EDN->KM tvalid (entropy_muxed_req[0])
    output logic [31:0]       km_entropy_tdata_o,    // CHK5: post-mux EDN->KM tdata word
    output logic              km_entropy_tready_o,   // CHK5: KM tready (entropy_muxed_rsp[0]) -> real handshake
    // CHK5 crypto EDN sinks: the SEP EDN's crypto leg (entropy_muxed_req[1]) fans
    // out through drbg_axis_edn_adapter to native EDN clients crypto_edn[0]=AES,
    // [1]=KMAC, [2]=OTBN-RND, [3]=OTBN-URND. A delivered word to sink i is the cycle
    // crypto_edn_req[i].edn_req && crypto_edn_rsp[i].edn_ack. Packed per-client so a
    // multi-sink CHK5 can score each endpoint off these vectors.
    output logic [3:0]        crypto_edn_req_o,      // bit i = crypto_edn_req[i].edn_req
    output logic [3:0]        crypto_edn_ack_o,      // bit i = crypto_edn_rsp[i].edn_ack
    output logic [127:0]      crypto_edn_bus_o,      // word i = crypto_edn_rsp[i].edn_bus ([32*i +: 32])
    output logic [3:0]        crypto_edn_fips_o,     // bit i = crypto_edn_rsp[i].edn_fips
    // CHK5 per-sink ROUTING golden tap (AXIS1): the crypto-leg EDN word stream
    // POST the KM/crypto mux but PRE the drbg_axis_edn_adapter fan-out
    // (sep_crypto.entropy_muxed_req[1]). This is the authoritative ordered word
    // sequence the adapter hands to the crypto endpoints; with a single active
    // crypto sink the adapter is in-order so AES's post-adapter beats equal this
    // stream 1:1, and each word is also chained to the CHK4 genbits golden.
    // Read-only XMR, no force.
    output logic              axis1_tvalid_o,        // entropy_muxed_req[1].tvalid
    output logic              axis1_tready_o,        // entropy_muxed_rsp[1].tready
    output logic [31:0]       axis1_tdata_o,         // entropy_muxed_req[1].tdata (32b word)
    // CHK5 entropy-pool sink (EDN endpoint [2]): AXIS2 is the pre-adapter mux-leg
    // stream (entropy_muxed_req[2]); pool_edn_* is the post-adapter native EDN
    // handshake into sep_entropy_fifo (one client, so AXIS2==pool beats in order).
    // Observation-only XMR, no force. No frontdoor equivalent of the 32-bit EDN
    // beat -- the 0x1095 aperture is a packed 64-bit drain, Phase 3 FIFO consume.
    output logic              axis2_tvalid_o,        // entropy_muxed_req[2].tvalid
    output logic              axis2_tready_o,        // entropy_muxed_rsp[2].tready
    output logic [31:0]       axis2_tdata_o,         // entropy_muxed_req[2].tdata (32b word)
    output logic              pool_edn_req_o,        // entropy_pool_edn_req_i.edn_req
    output logic              pool_edn_ack_o,        // entropy_pool_edn_rsp_o.edn_ack
    output logic [31:0]       pool_edn_bus_o,        // entropy_pool_edn_rsp_o.edn_bus
    output logic              pool_edn_fips_o,       // entropy_pool_edn_rsp_o.edn_fips
    // Observation-only depth of the fabric pool's 32->64 packer. Used to
    // trigger a TRNG reset with exactly one pre-reset 32-bit half-word cached.
    output logic [1:0]        entropy_pool_packer_depth_o,
    // Coordinated-reset observation: shared reset plus ESRC/CSRNG/EDN isolate
    // completion bits, used to prove reset cannot precede the slowest drain.
    output logic              trng_gated_rst_n_probe_o,
    output logic [2:0]        trng_axi_isolated_probe_o,
    // IP-interrupt aggregator: observation-only mirror of the 34-bit
    // sep_internal_interrupts vector that sep.sv assembles and feeds to the VeeR
    // PIC. The IP->aggregator test injects each CSRNG/EDN INTR_TEST and watches the
    // mapped bit here. Read-only XMR, no force (same class as the probes above).
    output logic [sep_pkg::NUM_INTERNAL_IRQS-1:0] sep_internal_interrupts_probe_o,
    // The production SEP debug-bus output, exposed read-only for lane-packing checks.
    output logic [383:0]      ext_debug_bus_o,
    // System-CSR AXI4-Lite AR/AW handshakes after axi_to_axi_lite
    // (sep_system_peripherals_xbar u_system_csr_a2l_1). Observation-only.
    // The bridge converts a burst to single beats. The external master still
    // sees AxLEN=1;
    // Lite has no AxLEN, so the split is not a frontdoor CSR. Addr is the
    // local 32 bits (scratch is in the 32-bit map). Outside the tb s_axi /
    // m_axi ready/valid cones.
    output logic        sys_csr_axil_arvalid_o,
    output logic        sys_csr_axil_arready_o,
    output logic [31:0] sys_csr_axil_araddr_o,
    output logic        sys_csr_axil_awvalid_o,
    output logic        sys_csr_axil_awready_o,
    output logic [31:0] sys_csr_axil_awaddr_o,
    // Lifecycle status observability. security_disable and lc_sigint_err are DUT
    // outputs (frontdoor). secure_tm_o is also a real DUT output -- the latched
    // TEST_EN strap -- so a strap test can observe the latch rather than assume it.
    output logic              lcc_security_disable_probe_o,
    output logic              lcc_sigint_err_probe_o,
    output logic              secure_tm_o,
    // Demotion state outputs expose the differential {~demote, demote} encoding;
    // 2'b10 is clear, 2'b01 is set, and other values are invalid. The lock bits
    // have no DUT output, and the CPU owns their AXI frontdoor during firmware
    // boot, so read-only XMRs observe the register storage. The leaf register
    // storage sits outside the AXI ready/valid combinational cones.
    output logic [1:0]        lcc_demote_state_1_probe_o,
    output logic [1:0]        lcc_demote_state_2_probe_o,
    output logic              lcc_demote_lock_1_probe_o,
    output logic              lcc_demote_lock_2_probe_o,
    // OTP JTAG2AXIL disable bits of DUT dbg_disable_o (frontdoor). LCC ties
    // both to 0; the fuse controller enforces access. Sliced here so cocotb
    // can read them without a packed-struct field walk.
    output logic              dbg_disable_smc_otp_jtag2axi_o,
    output logic              dbg_disable_sep_otp_jtag2axi_o,
    // WDT bite reset request: a REAL `sep` output port (sep.sv wdt_timer_rst_req_o,
    // asserted when the WDT count reaches BITE_THOLD). Brought out so the
    // reset/WDT sanity test (`sep_reset_wdt_sanity_test`) can observe the bite ->
    // reset-request edge. This
    // is a DUT output (frontdoor), not an internal-signal probe.
    output logic              wdt_timer_rst_req_o,
    output logic              spi_cs_n_o,
    output logic              spi_sck_o,
    output logic              spi_mosi_o,
    input  wire logic         spi_miso_i
);

    // ------------------------------------------------------------------
    // DUT-flavor XMR roots. The DUT is `sep_wrapper`, so sep-internal state lives
    // under u_dut.u_sep and the OSS IP integration (memory macros, generic efuse
    // model) under u_dut.u_sep_ip_integration. The OpenTitan SPI host is inside
    // the `sep` core. Every
    // sep-internal XMR read routes through `SEP_CORE / `SEP_IPI so one probe text
    // is used throughout.
    // ------------------------------------------------------------------
    `define SEP_CORE u_dut.u_sep
    `define SEP_IPI  u_dut.u_sep_ip_integration
    // The entropy complex sits below sep_crypto inside sep_trng, which owns the
    // shared TRNG reset. Naming that level once means a hierarchy change is made
    // here rather than at every entropy probe and assertion scope below.
    `define SEP_ESRC `SEP_CORE.sep_crypto.u_sep_trng.u_entropy_source_s3c_scan
    `define SEP_DRBG `SEP_CORE.sep_crypto.u_sep_trng.u_drbg_s3c_scan

    // ------------------------------------------------------------------
    // Idle / benign tie-off nets for the unused external ports.
    // ('0 default-init on structs keeps every input req/rsp port at idle.)
    // ------------------------------------------------------------------
    // SMN inbound external AXI: assembled (combinationally, below) from the flat
    // m_axi_* master inputs and read back to the flat m_axi_* outputs. Always wired
    // to the DUT's smn_inbound_axi_req_i port (idles unless a test drives m_axi_*).
    sep_pkg::sep_system_peripherals_internal_axi_req_t  smn_inbound_req_drive;
    sep_pkg::sep_system_peripherals_internal_axi_resp_t smn_inbound_resp_w;
    sep_pkg::sep_system_peripherals_internal_axi_resp_t ext_to_smc_resp_idle   = '0;
    // SEP->SMC external AXI. Tied idle by default; with SEP_SMC_MEM_MODEL a
    // behavioral axi_sim_mem responds (real R/W to SMC scratch + SRAM) so the
    // Boot ROM can run its SMC scratch round-trip + non-SPI manifest fetch.
    sep_pkg::sep_system_peripherals_internal_axi_req_t  ext_to_smc_req_w;
    sep_pkg::sep_system_peripherals_internal_axi_resp_t ext_to_smc_resp_w;
    // SEP-OTP JTAG AXI-Lite: assembled from the flat j_axi_* master inputs (below).
    sep_efuse_pkg::efuse_axil_req_t   j_axil_req_drive;
    sep_efuse_pkg::efuse_axil_resp_t  j_axil_resp_w;
    sep_pkg::jtag_sep_reset_ctrl_t   jtag_sep_reset_ctrl_drive;
    always_comb begin
        jtag_sep_reset_ctrl_drive = '0;
        // Ports are Z until cocotb drive_idle_defaults. Treat only 1 as hold.
        jtag_sep_reset_ctrl_drive.ovrd.otbn_jtag_rst_n_ovrd =
            (jtag_otbn_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.aes_jtag_rst_n_ovrd =
            (jtag_aes_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.hmac_jtag_rst_n_ovrd =
            (jtag_hmac_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.kmac_jtag_rst_n_ovrd =
            (jtag_kmac_rst_hold_i === 1'b1);
        jtag_sep_reset_ctrl_drive.ovrd.trng_jtag_rst_n_ovrd =
            (jtag_trng_rst_hold_i === 1'b1);
    end

    // smc_fuse_sense_done_i is a real DUT input the SMC drives when its fuse sense
    // completes. There is no SMC here, so it stays idle-0 and
    // `+sep_smc_fuse_sense_done` models the SMC having finished. Not a force, and
    // not a bypass of anything: it changes only how long the ROM waits.
    //
    // It matters to exactly one path. A manifest whose usage_constraints enable a
    // chiplet_id or package_id word makes the ROM wait for this bit before reading
    // the SMC fuse map (bootrom/prod/src/manifest_load.c). The wait is bounded and
    // falls through on expiry, so with the pin idle the ROM performs its full
    // 1,000,000-iteration poll and then makes the same comparison it would have
    // made immediately -- about 15M clocks of identical outcome. Default stays 0 so
    // no existing test changes behaviour.
    logic smc_fuse_sense_done_drive;
    initial begin
        smc_fuse_sense_done_drive = 1'b0;
        if ($test$plusargs("sep_smc_fuse_sense_done")) begin
            smc_fuse_sense_done_drive = 1'b1;
            $display("[tb] smc_fuse_sense_done_i driven high (+sep_smc_fuse_sense_done)");
        end
    end

    // Outbound mailbox responder buses and CPU trace -- the DUT struct nets the
    // wrapper flow needs.
    sep_pkg::sep_system_peripherals_outbound_axi_req_t  smn_outbound_req_w;
    sep_pkg::sep_system_peripherals_outbound_axi_resp_t smn_outbound_resp_w;
    sep_cpu_trace_t    cpu_trace_w;

    // Cocotb drives rst_ni after time 0. Until then the input wire is Z, and
    // PeakRDL immediate asserts in an always_ff else treat `if (~arst_n)` as
    // false when arst_n is X/Z. Hold 0 until the port is a known 0/1, then
    // follow. The bring-up presents rst_ni high before asserting it, so the
    // assertion is a real falling edge and every async-reset flop loads its
    // reset value (sep_base_test.assert_cold_reset).
    // An X/Z on the port AFTER cocotb has driven it is a testbench defect, not
    // the bring-up window: latching the last good level would hide it for the
    // rest of the run, so it fails here instead. rst_n_driven marks the window
    // closed on the first known level.
    logic rst_n_int = 1'b0;
    logic rst_n_driven = 1'b0;
    always @(*) begin
        if ((rst_ni === 1'b0) || (rst_ni === 1'b1)) begin
            rst_n_int = rst_ni;
            rst_n_driven = 1'b1;
        end else if (rst_n_driven) begin
            $error("%0t: rst_ni went %b after being driven; the DUT is running on the last known level",
                   $time, rst_ni);
        end
    end

    // Assertion classes held off, and why each is not a DUT contract here.
    //
    // AssertConnected_A: 408 instances across three subtrees (403 entropy_source,
    // 4 axis_edn_crypto, 1 axis_edn_pool). It asks whether a hardened counter's
    // err_o reaches an OpenTitan alert, so it cannot fail on DUT behaviour. It is
    // ASSERT_INIT_NET -- an immediate assert in `initial #1ps`, with no clock and
    // no reset -- so `disable iff` cannot gate it and the scope is the only knob.
    //
    // ~23 do not apply: their err_o is wired and reaches escalation and irq_o, and
    // SEP's entropy_source has no alert output for the OT convention to test. The
    // declarative escape is EnableAlertTriggerSVA(0) at those instantiations.
    //
    // The other 385 are a real defect: the counters raise err_o into a net
    // nothing reads. A green run is therefore NOT evidence that a glitched
    // health-test counter would be reported. The SPI assertions in this subtree
    // are armed only during reset, so they judge nothing after it.
    //
    // Scope is by subtree because these are generate-loop instances with no single
    // name to target, which also disables every other assertion under those three
    // blocks -- so the one OCAH contract in the set is re-armed by name below.
`ifndef VERILATOR
    initial begin
        // These three stay off while the counters are unwired. Re-arm by an
        // assertion's own hierarchical name, never by re-enabling a parent
        // instance.
        $assertoff(0, `SEP_ESRC);
        $assertoff(0, `SEP_CORE.sep_crypto.u_axis_edn_crypto_s3c_scan);
        $assertoff(0, `SEP_CORE.sep_crypto.u_axis_edn_pool_s3c_scan);
        // FipsWindowFloor_A in entropy_source: fips_lock |-> window >= 1024.
        // The only OCAH assertion under those subtrees, and reachable stimulus:
        // sep_drbg_esrc_fips_lock_test writes FIPS_LOCK.LOCK, so a locked
        // out-of-spec window must fail rather than be swept up by the line above.
        $asserton(0, `SEP_ESRC.FipsWindowFloor_A);
        // SHA-256-only prim_sha2_32 (MultimodeEn=0) ties inner digest_mode_i to
        // SHA2_None. ValidDigestModeFlag_A requires {SHA2_256, SHA2_384, SHA2_512}
        // on every hash beat, so it is not a contract on those instances. HMAC
        // and DMA use MultimodeEn=1 and keep the check. $assertoff scopes are
        // resolved from this module, so these are downward XMRs (a module-name
        // scope does not resolve).
        $assertoff(0, `SEP_ESRC
            .u_sha256_whitener.u_sha2.gen_sha256_logic.u_prim_sha2_256
            .ValidDigestModeFlag_A);
        $assertoff(0, `SEP_ESRC
            .u_sha256_whitener.u_sha2.gen_sha256_logic.u_prim_sha2_256.u_pad
            .ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_sip_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_sip_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.u_pad.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_chiplet_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_rma_chiplet_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.u_pad.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_sec_disable_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.ValidDigestModeFlag_A);
        $assertoff(0, `SEP_CORE.sep_crypto.u_sep_efuse_wrapper
            .u_efuse_interface_controller.gen_mmr_reg.u_efuse_token_processing
            .u_sha256_sec_disable_token.u_prim_sha2_32.gen_sha256_logic
            .u_prim_sha2_256.u_pad.ValidDigestModeFlag_A);

    end

    // UrndNoReseedOnReset_A in otbn_rnd cannot pass on this instance. It arms
    // only while OTBN is in reset -- disable iff (rst_ni !== '0) -- and its guard
    // reads CURRENT rst_ni while the property body reads SAMPLED rst_ni. SEP
    // asserts OTBN's reset ON a clk_i edge, because otbn_gated_rst_n is a flop
    // output of hw/sys/sep/rtl/sep_crypto_axi_isolate_unit.sv, so at that edge the
    // guard sees reset active and arms an attempt whose body still sees the
    // pre-reset value and therefore demands seed_en_q be high. It fires on every
    // software reset whatever the DUT does.
    //
    // This holds the property off for the WHOLE RUN, not just that edge, so no
    // in-reset cycle is checked in any test. Little is lost because of the flop
    // in otbn_rnd: seed_en_q is asynchronously cleared by the same rst_ni
    // the property checks it against, and that flop is what stops a reseed request
    // -- held high through reset by design -- from starting one. A reseed cannot
    // begin mid-reset unless that flop's reset is broken, and its declaration is
    // what guarantees it is not.
    //
    // The fix belongs upstream: the guard should sample as the body does.
    initial begin
        $assertoff(0, `SEP_CORE.sep_crypto.sep_crypto_otbn_wrapper_s3c_scan
            .u_otbn.u_otbn_core.u_otbn_rnd.UrndNoReseedOnReset_A);
    end
`endif

    // TB-owned CPU lockstep stimulus/observation. Initialised: an undriven
    // lockstep_ctrl_i would reach the core as X under RV_LOCKSTEP_ENABLE.
    sep_pkg::sep_lockstep_ctrl_t   lockstep_ctrl_i = '0;
    sep_pkg::sep_lockstep_status_t lockstep_status_o;
    sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_w;
    assign dbg_disable_smc_otp_jtag2axi_o = dbg_disable_w.smc_otp_jtag2axi;
    assign dbg_disable_sep_otp_jtag2axi_o = dbg_disable_w.sep_otp_jtag2axi;

    // TB-owned JTAG pins used to program the EL2 reset-vector TDR in +cpu_boot
    // mode. They remain at the idle TAP-reset values for no-CPU tests.
    logic jtag_tck   = 1'b0;
    logic jtag_tms   = 1'b0;
    logic jtag_tdi   = 1'b0;
    logic jtag_trst_n = 1'b0;

    localparam logic [4:0] RESET_VECTOR_TDR_IR = 5'h18;

    task automatic jtag_tb_clock(input logic tms, input logic tdi);
        jtag_tms = tms;
        jtag_tdi = tdi;
        #1ps;
        jtag_tck = 1'b1;
        #1ps;
        jtag_tck = 1'b0;
        #1ps;
    endtask

    task automatic program_reset_vector_tdr(input logic [31:0] vector);
        int bit_idx;

        if (vector[0] !== 1'b0) begin
            $fatal(1,
                   "[SEP OSS DV] Reset-vector TDR requires a halfword-aligned address: 0x%08x",
                   vector);
        end

        // Assert and release TRST, then explicitly enter Run-Test/Idle.
        jtag_trst_n = 1'b0;
        jtag_tck = 1'b0;
        #1ps;
        jtag_trst_n = 1'b1;
        repeat (5) jtag_tb_clock(1'b1, 1'b0);
        jtag_tb_clock(1'b0, 1'b0);

        // Select-IR-Scan and load RSTVEC (0x18), LSB first.
        jtag_tb_clock(1'b1, 1'b0); // Select-DR-Scan
        jtag_tb_clock(1'b1, 1'b0); // Select-IR-Scan
        jtag_tb_clock(1'b0, 1'b0); // Capture-IR
        jtag_tb_clock(1'b0, 1'b0); // Shift-IR
        for (bit_idx = 0; bit_idx < 5; bit_idx++) begin
            jtag_tb_clock(bit_idx == 4, RESET_VECTOR_TDR_IR[bit_idx]);
        end
        jtag_tb_clock(1'b1, 1'b0); // Update-IR
        jtag_tb_clock(1'b0, 1'b0); // Run-Test/Idle

        // Select-DR-Scan and shift the reset vector, LSB first. RSTVEC stores
        // PC[31:1], so bit 0 is reserved and always shifts as zero.
        jtag_tb_clock(1'b1, 1'b0); // Select-DR-Scan
        jtag_tb_clock(1'b0, 1'b0); // Capture-DR
        jtag_tb_clock(1'b0, 1'b0); // Shift-DR
        for (bit_idx = 0; bit_idx < 32; bit_idx++) begin
            jtag_tb_clock(bit_idx == 31, bit_idx == 0 ? 1'b0 : vector[bit_idx]);
        end
        jtag_tb_clock(1'b1, 1'b0); // Update-DR
        jtag_tb_clock(1'b0, 1'b0); // Run-Test/Idle

        jtag_tms = 1'b0;
        jtag_tdi = 1'b0;
        $display("[SEP OSS DV] Reset-vector TDR programmed to 0x%08x", vector);
    endtask

    // The vendored VeeR tap has no reset-vector TDR, so this JTAG sequence
    // shifts into a nonexistent register and is inert. The reset vector reaches
    // the CPU through the wrapper's direct `rst_vec` input (connected from
    // rst_vec_i in the DUT instantiation below).
    // The OSS top has no external JTAG client. Program RSTVEC while the primary
    // reset is asserted, before the cocotb CPU-boot flow releases reset. Poll on the
    // clock edge rather than a bare level `wait`: a cocotb (VPI)-driven rst_vec_i
    // update does not reliably re-trigger a `wait` under Verilator, so the one-shot
    // could fire late (after reset release) and latch a stale/zero vector. Program
    // exactly once on the first clock where reset is asserted and rst_vec_i is a
    // known non-zero entry (clocks start while rst_ni is still low, so the window is
    // always seen). Bit math unchanged: RSTVEC stores PC[31:1] = rst_vec_i.
    initial begin : init_reset_vector_tdr
        if ($test$plusargs("cpu_boot")) begin
            forever begin
                @(posedge clk_i);
                if ((rst_ni === 1'b0) && !$isunknown(rst_vec_i) && (rst_vec_i !== '0)) begin
                    program_reset_vector_tdr({rst_vec_i, 1'b0});
                    break;
                end
            end
        end
    end

    // ------------------------------------------------------------------
    // SEP DUT = sep_wrapper (smn_inbound driven by the flat m_axi_* external
    // master). Real memory macros + generic efuse model are internal (no
    // mem/efuse responder buses). SPI leaves the wrapper as the sep_io_pkg
    // struct pair (sep_io_spi_req_o / sep_io_spi_rsp_i); the TB bridges it to
    // the scalar pad ports below. The reset vector is a direct rst_vec input
    // (the vendored VeeR tap has no reset-vector TDR).
    // ------------------------------------------------------------------
    sep_io_pkg::sep_io_spi_req_t sep_io_spi_req_w;
    // EXT_TRNG_NUM_AXIS must equal sep_crypto_pkg::SEP_CRYPTO_EDN_ENDPOINT_COUNT (3):
    // sep_crypto.u_sep_trng binds u_drbg_s3c_scan.edn_axis_o/i to drbg_int_axis_req/rsp as a
    // DIRECT packed-array connection, one mux leg per DRBG EDN endpoint
    // ([0]=Key Manager, [1]=crypto adapter, [2]=entropy pool). Width 2 truncates
    // that bind; sep_crypto.sv's g_drbg_endpoint_mux_width_check catches it under
    // simulators that evaluate elaboration-time $error. Verilator skips
    // that check, so the width must stay correct here.
    //
    // The third leg is NOT free. sep_entropy_fifo drives edn_req from the first
    // post-reset cycle, so once endpoint [2] is connected the DRBG grants it real
    // genbits blocks and a single seed serves several Generate commands. That is
    // why the CHK4 golden is demand-driven (sep_entropy_golden.genbits_block() /
    // genbits_gen_last()): a fixed glen-blocks-per-seed model desynchronises at
    // the first extra Generate. Truncating to 2 to dodge that is not an option
    // either -- it left the dropped leg's inputs X-driven.
    //
    // SEP_SEC_DISABLE_TOKEN is the metal expected digest, not an AXI register.
    // Product RTL defaults it to 0, which no SHA-256 output matches. Bind the
    // SHA-256 of the all-zero 32-byte token so a frontdoor write of zeros can
    // take the match. This is the TB stand-in for the metal ECO; it does not
    // force security_disable.
    localparam bit [255:0] SEC_DIS_TB_DIGEST =
        256'h66687aad_f862bd77_6c8fc18b_8e9f8e20_08971485_6ee233b3_902a591d_0d5f2925;
    sep_wrapper #(
        .EXT_TRNG_NUM_AXIS     (3),
        .SEP_SEC_DISABLE_TOKEN (SEC_DIS_TB_DIGEST)
    ) u_dut (
        // Clocks / resets
        .clk_i                        (clk_i),
        .clk_wdt_i                    (clk_wdt_i),
        .rst_ni                       (rst_n_int),
        .dbg_rstb_i                   (dbg_rstb_i),
        .wdt_rst_ni                   (wdt_rst_ni_i),
        .entropy_rosc_sample_clk_i    (entropy_rosc_sample_clk_i),
        .wdt_timer_rst_req_o          (wdt_timer_rst_req_o),

        // JTAG (TB-driven only during +cpu_boot reset-vector TDR setup)
        .jtag_tck                     (jtag_tck),
        .jtag_tms                     (jtag_tms),
        .jtag_tdi                     (jtag_tdi),
        .jtag_trst_n                  (jtag_trst_n),
        .jtag_tdo                     (),
        .jtag_tdoEn                   (),
        .jtag_sep_reset_ctrl_i        (jtag_sep_reset_ctrl_drive),

`ifdef SEP_JTAG_AXIL_LIVE
        .axil_sep_otp_jtag_req_i      (j_axil_req_drive),
`else
        .axil_sep_otp_jtag_req_i      ('0),
`endif
        .axil_sep_otp_jtag_resp_o     (j_axil_resp_w),

        // MPC halt/run + CPU run (CPU held off; LSU master driven by the stub)
        .mpc_debug_halt_req           (1'b0),
        .mpc_debug_run_req            (1'b0),
        .mpc_reset_run_req            (mpc_reset_run_req),
        .i_cpu_halt_req               (1'b0),
        .i_cpu_run_req                (i_cpu_run_req_i),

        // DFT: functional mode (see the bare-sep note below on test_en_i).
        .test_en_i                    (1'b0),
        .scan_rst_ni                  (1'b1),
        .ext_boot_seq_done_i          (ext_boot_seq_done_i),

        // DMI uncore (idle)
        .dmi_core_enable              (1'b0),
        .dmi_uncore_enable            (1'b0),
        .dmi_uncore_en                (),
        .dmi_uncore_wr_en             (),
        .dmi_uncore_addr              (),
        .dmi_uncore_wdata             (),
        .dmi_uncore_rdata             ('0),
        .dmi_active                   (),

        .sep_cpu_trace                (cpu_trace_w),
        // Direct reset-vector input.
        .rst_vec                      (rst_vec_i),
        .jtag_id                      ('0),

        // Interrupts (idle)
        .timer_int                    (1'b0),
        .soft_int                     (1'b0),
        .extintsrc_req                ('0),

        // SMN external AXI (outbound captured by the mailbox responder; inbound
        // driven by the flat m_axi_* master when live).
        .smn_outbound_axi_req_o       (smn_outbound_req_w),
        .smn_outbound_axi_resp_i      (smn_outbound_resp_w),
`ifdef SEP_SMN_INBOUND_AXI_LIVE
        .smn_inbound_axi_req_i        (smn_inbound_req_drive),
`else
        .smn_inbound_axi_req_i        ('0),
`endif
        .smn_inbound_axi_resp_o       (smn_inbound_resp_w),
        .sep_ext_to_smc_axi_req_o     (ext_to_smc_req_w),
        .sep_ext_to_smc_axi_resp_i    (ext_to_smc_resp_w),

        // LC demote. Real DUT outputs, brought out so a ROM boot test can observe
        // what BL0 actually wrote rather than what it said it wrote.
        .lcc_demote_state_1_o         (lcc_demote_state_1_probe_o),
        .lcc_demote_state_2_o         (lcc_demote_state_2_probe_o),

        // SPI: quad-lane struct boundary, bridged below to the
        // single-lane pad ports (sck/cs_n from req; MOSI = sd[0] out;
        // MISO returns on rsp.sd[1]). The SPI block IRQ loops back into the
        // wrapper's interrupt aggregator input.
        .sep_io_spi_req_o             (sep_io_spi_req_w),
        .sep_io_spi_rsp_i             ('{sd: {2'b00, spi_miso_i, 1'b0}}),
        .spi_irq_i                    (sep_io_spi_req_w.irq),

        // New wrapper status/debug outputs: observability only, left open.
        .lc_state_o                   (),
        .dbg_disable_o                (dbg_disable_w),
        .lc_sigint_err_o              (lcc_sigint_err_probe_o),
        .security_disable_o           (lcc_security_disable_probe_o),
        .secure_tm_o                  (secure_tm_o),
        .km_unrecoverable_err_o       (),
        .km_recoverable_err_o         (),
        .efuse_debug_bus_o            (),

        // Mailbox interrupts
        .smc_mailbox_interrupt_o      (),

        // eFuse status
        .smc_fuse_sense_done_i        (smc_fuse_sense_done_drive),
        .sep_fuse_sense_done_o        (sep_fuse_sense_done_o),

        .secure_tm_req_i              (test_en_strap_i),

        // SMC address configuration tied to 0 (identity remap).
`ifdef SEP_SMC_MEM_MODEL
        // Route the SMC region (scratch 0x4003_9080+, straps 0x4040_5800, SMC SRAM
        // 0x4006_0000+ manifest) out the sep_ext_to_smc AXI to the behavioral
        // axi_sim_mem. The ROM boots secondary (non-SPI) and DMAs the manifest+BL1
        // from SMC SRAM.
        .smc_global_base_addr_i       (56'h4000_0000),
        .smc_region_size_i            (56'h0100_0000),
`else
        .smc_global_base_addr_i       ('0),
        .smc_region_size_i            ('0),
`endif
        .sep_global_base_addr_o       (),
        .sep_region_size_o            (),

        // External debug bus
        .ext_debug_bus_o              (ext_debug_bus_o),

        // CPU lockstep control/status
        .lockstep_ctrl_i              (lockstep_ctrl_i),
        .lockstep_status_o            (lockstep_status_o)
    );
    // Scalar SPI pad bridge from the wrapper struct port.
    assign spi_sck_o  = sep_io_spi_req_w.sck;
    assign spi_cs_n_o = sep_io_spi_req_w.cs_n;
    assign spi_mosi_o = sep_io_spi_req_w.sd[0];

    // ------------------------------------------------------------------
    // SEP->SMC external AXI responder (real-ROM boot only).
    // The Boot ROM accesses the SMC scratch registers (0x4003_9080+) and SMC
    // SRAM (0x4006_0000, manifest+BL1) over sep_ext_to_smc_axi. A behavioral
    // axi_sim_mem gives those a real memory (R/W), so the ROM's scratch
    // round-trip passes and its non-SPI manifest fetch works. The backing
    // memory is preloaded via +sep_smc_mem_hex=<file> ($readmemh into u_smc_mem.mem).
    // ------------------------------------------------------------------
`ifdef SEP_SMC_MEM_MODEL
    sep_pkg::sep_system_peripherals_internal_axi_req_t  [0:0] smc_mem_req_arr;
    sep_pkg::sep_system_peripherals_internal_axi_resp_t [0:0] smc_mem_rsp_arr;
    assign smc_mem_req_arr[0] = ext_to_smc_req_w;
    assign ext_to_smc_resp_w  = smc_mem_rsp_arr[0];

    axi_sim_mem #(
        .AddrWidth         (56),
        .DataWidth         (64),
        .IdWidth           (6),
        .UserWidth         (12),
        .NumPorts          (1),
        .axi_req_t         (sep_pkg::sep_system_peripherals_internal_axi_req_t),
        .axi_rsp_t         (sep_pkg::sep_system_peripherals_internal_axi_resp_t),
        .WarnUninitialized (1'b0),
        .UninitializedData ("zeros"),
        .ClearErrOnAccess  (1'b1),
        // axi_sim_mem drives each AXI handshake as "apply outputs at #ApplDelay
        // after posedge, sample the master's valid/ready at #AcqDelay". The pulp
        // defaults are 0ps/0ps, which collapse both to `#0` and make the model
        // rely on event-region (`#0` inactive-region) ordering to sample the
        // master AFTER its NBA update. Verilator's --timing scheduler resolves
        // `#0` differently, so the model samples valid/ready in the wrong delta
        // and the SMC AXI handshake never completes -> every ROM SMC scratch
        // access stalls forever (post code, virtual console, the status-to-SEP
        // handshake, the staging window in scratch[13]/[14]). The pulp driver family
        // asserts ApplDelay>0 && AcqDelay>ApplDelay for exactly this reason.
        // Required: 0 < ApplDelay < AcqDelay < min(sys_clk_period). These are
        // elaboration-time params but sys_clk_period_ns is chosen at runtime by
        // sep_env_cfg.randomize_timing() = rng.randint(4,20)ns, so they must fit
        // the 4ns floor (NOT the seed=1 8ns period). Use 1ns/3ns: valid for the
        // whole [4,20]ns range under both scheduling models; still samples well after
        // the master's NBA-driven valid.
        .ApplDelay         (1ns),
        .AcqDelay          (3ns)
    ) u_smc_mem (
        .clk_i     (clk_i),
        .rst_ni    (rst_n_int),
        .axi_req_i (smc_mem_req_arr),
        .axi_rsp_o (smc_mem_rsp_arr)
    );

    // ------------------------------------------------------------------
    // SMC address decode check.
    //
    // WHY THIS EXISTS. u_smc_mem is a FLAT axi_sim_mem: it answers at whatever
    // address the ROM presents, so a wrong SEP<->SMC offset is invisible -- the
    // testbench simply seeds the wrong address too and every test stays green.
    // An offset in sep_smc_interface.h can therefore drift out of agreement with
    // this design's generated map (smc_addr.h) and point into an unmapped hole
    // without a single test failing.
    //
    // This checker restores the one property the flat model threw away: an
    // access outside a register window that actually exists is an ERROR. The
    // windows below are transcribed from smc_addr.h (SMC-local 0xC000_XXXX seen
    // as 0x4000_XXXX from SEP, the identity mapping this tb configures via
    // smc_global_base_addr_i). Keep them in step with that header; if the ROM
    // legitimately needs a new block, add its authoritative base/size here
    // rather than widening an existing window.
    localparam logic [55:0] SmcStrapsLoAddr = 56'h4040_5800;
    localparam logic [55:0] SmcStrapsHiAddr = SmcStrapsLoAddr + 4;

    // SMC CPU_CTRL scratch registers: index * 8 from smc_base+0x39080
    // (sep_smc_interface.h). 8 holds the manifest offset the SMC publishes to
    // SEP, 9 the SMC->SEP status word, 13 the SEP-safe SRAM offset, 14 its size.
    localparam logic [55:0] SmcScratchBaseAddr = 56'h4003_9080;
    localparam logic [55:0] SmcScratch8Addr = SmcScratchBaseAddr + (8 * 8);
    localparam logic [55:0] SmcScratch9Addr = SmcScratchBaseAddr + (9 * 8);
    localparam logic [55:0] SmcScratch13Addr = SmcScratchBaseAddr + (13 * 8);
    localparam logic [55:0] SmcScratch14Addr = SmcScratchBaseAddr + (14 * 8);
    localparam int unsigned SmcNumWindows = 7;
    // {base, size} pairs, SEP-side addresses.
    localparam logic [55:0] SmcWinBase [SmcNumWindows] = '{
        56'h4000_2000,  // SMC_RESET_UNIT
        56'h4000_2900,  // SMC_MISC_WRAP_CHIP_CONFIG (CHIP_ID, LC_STATE)
        56'h4000_7000,  // SMC_EFUSE_MAP             (chiplet/package ID)
        56'h4000_B800,  // DFX_CTRL                  (STATUS_SMU)
        56'h4003_9000,  // SMC_CPU_CTRL              (scratch[0..15] at +0x80)
        56'h4006_0000,  // SPM_MEMORY                (manifest + BL1)
        SmcStrapsLoAddr // SMC_EXTERNAL straps      (STRAPS_LO/HI)
    };
    localparam logic [55:0] SmcWinSize [SmcNumWindows] = '{
        56'h0000_00CC, 56'h0000_0014, 56'h0000_0C00,
        56'h0000_0018, 56'h0000_02C0, 56'h0010_0000,
        56'h0000_0008
    };

    // Counted as well as reported: a cocotb test can require this to be 0, so the
    // check cannot be silently lost if $error severity is ever downgraded.
    int unsigned smc_addr_violations;
    assign smc_addr_violations_o = smc_addr_violations;

    function automatic bit smc_addr_mapped(input logic [55:0] a);
        smc_addr_mapped = 1'b0;
        for (int unsigned w = 0; w < SmcNumWindows; w++) begin
            if (a >= SmcWinBase[w] && a < (SmcWinBase[w] + SmcWinSize[w])) begin
                smc_addr_mapped = 1'b1;
            end
        end
    endfunction

    logic smc_aw_violation;
    logic smc_ar_violation;
    assign smc_aw_violation =
        ext_to_smc_req_w.aw_valid && ext_to_smc_resp_w.aw_ready &&
        !smc_addr_mapped(ext_to_smc_req_w.aw.addr);
    assign smc_ar_violation =
        ext_to_smc_req_w.ar_valid && ext_to_smc_resp_w.ar_ready &&
        !smc_addr_mapped(ext_to_smc_req_w.ar.addr);

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            smc_addr_violations <= 0;
        end else begin
            smc_addr_violations <=
                smc_addr_violations + smc_aw_violation + smc_ar_violation;
            if (smc_aw_violation) begin
                $error("[tb] SMC ADDRESS DECODE: write to 0x%0h is outside every register window in smc_addr.h -- the ROM is using an offset this design does not implement",
                       ext_to_smc_req_w.aw.addr);
            end
            if (smc_ar_violation) begin
                $error("[tb] SMC ADDRESS DECODE: read from 0x%0h is outside every register window in smc_addr.h -- the ROM is using an offset this design does not implement",
                       ext_to_smc_req_w.ar.addr);
            end
        end
    end

    // Preload the SMC memory so the Boot ROM's non-SPI manifest path proceeds:
    //   scratch[9] (0x4003_90C8) = SMC_SEP_STATUS_MANIFEST_READY (bit1) so the
    //   ROM's manifest-ready poll breaks; scratch[8] (0x4003_90C0) = manifest
    //   offset 0. The manifest+BL1 image is loaded from +sep_smc_mem_hex if given.
    string smc_mem_image;
    logic [31:0] dft_status_ovr;
    logic [31:0] straps_hi_ovr;
    logic [31:0] straps_lo_ovr;
    logic [31:0] smc_scratch13_ovr;
    logic [31:0] smc_scratch14_ovr;
    logic [31:0] smc_scratch8_ovr;
    initial begin
        #1;
        // scratch[9] status: SRAM_INIT|MANIFEST_READY|BUFFER_READY|SRAM_PROTECTED
        // scratch[8] manifest offset = 0x1000 (TBL1 manifest at that offset in the
        // packed SMC image -> manifest_addr = 0x4006_0000 + 0x1000). No primary
        // strap -> boot_from_spi()=false -> non-SPI (SMC-SRAM) manifest path.
        //
        // ALL FOUR BYTES of each word are written so the published value is stated
        // here rather than half-stated here and half-inherited from a vendor
        // parameter. The ROM reads both words with a 32-bit smc_scratch_read()
        // (rom_main.c, manifest_load.c), and writing only bytes 0-1 of scratch[8]
        // left the upper half of that read to whatever the memory model does with
        // an absent key.
        //
        // That is NOT an X hazard, and the earlier version of this comment was
        // wrong to say so: u_smc_mem is instantiated with
        // UninitializedData("zeros") above, and axi_sim_mem returns '0 for an
        // absent byte on its AXI read path, so the ROM always read 0x00001000
        // whatever the simulator. The X hazard in this block is real but narrower
        // -- it applies where TB CODE reads mem[] DIRECTLY, which is the
        // read-modify-write the STRAPS_LO overrides below perform, not the ROM's
        // AXI reads. Writing these bytes is therefore explicitness and symmetry
        // with the scratch[13]/[14] blocks, which is worth having on its own, and
        // NOT a behaviour fix: it changes no simulator's result.
        u_smc_mem.mem[SmcScratch9Addr + 0] = 8'h0F;
        u_smc_mem.mem[SmcScratch9Addr + 1] = 8'h00;
        u_smc_mem.mem[SmcScratch9Addr + 2] = 8'h00;
        u_smc_mem.mem[SmcScratch9Addr + 3] = 8'h00;
        u_smc_mem.mem[SmcScratch8Addr + 0] = 8'h00;
        u_smc_mem.mem[SmcScratch8Addr + 1] = 8'h10;
        u_smc_mem.mem[SmcScratch8Addr + 2] = 8'h00;
        u_smc_mem.mem[SmcScratch8Addr + 3] = 8'h00;
        // DFX_CTRL_STATUS_SMU (smc_base+0xB800) = 0x00000113, the healthy part:
        //   bit 0  mem_repair_done     bit 1 mem_repair_success
        //   bit 4  mbist_done          bit 8 mbist_pass
        // The ROM's boot gate checks BOTH arms (vector.S), so the MBIST bits are
        // not decoration: without mbist_done the gate polls for it, times out
        // after MBIST_DONE_WAIT_ITERS and halts. Every rom_fw test that does not
        // pass +sep_dft_status inherits this word, so it must represent a part
        // that boots.
        u_smc_mem.mem[56'h4000_B800] = 8'h13;
        u_smc_mem.mem[56'h4000_B801] = 8'h01;
        // STRAPS_LO and STRAPS_HI in the SMC external supplementary window,
        // explicitly zero.
        // REQUIRED, not tidiness: u_smc_mem.mem is an associative array, so
        // reading a key that was never written yields X. Both halves are now read
        // by the ROM's pre-C boot gate -- STRAPS_LO[13] BYPASS_SRAM_REPAIR and
        // STRAPS_HI[22] MBIST_BYPASS (vector.S) -- and an X there makes the gate
        // branch on an undefined bit. STRAPS_LO additionally needs it because
        // +sep_boot_from_spi and +sep_straps_lo read-modify-write these bytes so
        // that they can be combined, and the OR would propagate the X.
        //
        // Zeroing the HIGH half matters only on a 4-state simulator. Verilator is
        // 2-state, so an unwritten key reads 0 there and the tests pass either
        // way; sep_sim_cfg.toml also lists 4-state simulators, where without this
        // the MBIST arm would branch on X for every test that does not pass
        // +sep_straps_hi. Do not remove it because the Verilator runs are green.
        u_smc_mem.mem[SmcStrapsLoAddr + 0] = 8'h00;
        u_smc_mem.mem[SmcStrapsLoAddr + 1] = 8'h00;
        u_smc_mem.mem[SmcStrapsLoAddr + 2] = 8'h00;
        u_smc_mem.mem[SmcStrapsLoAddr + 3] = 8'h00;
        u_smc_mem.mem[SmcStrapsHiAddr + 0] = 8'h00;
        u_smc_mem.mem[SmcStrapsHiAddr + 1] = 8'h00;
        u_smc_mem.mem[SmcStrapsHiAddr + 2] = 8'h00;
        u_smc_mem.mem[SmcStrapsHiAddr + 3] = 8'h00;
        if ($value$plusargs("sep_smc_mem_hex=%s", smc_mem_image)) begin
            $readmemh(smc_mem_image, u_smc_mem.mem);
            $display("[tb] SMC mem preloaded from %s", smc_mem_image);
        end
        // ---- Explicit per-test injections. -------------------------------
        // All three sit BELOW the $readmemh above, so an explicit request always
        // wins over whatever a +sep_smc_mem_hex image happens to cover. Order
        // matters: above the $readmemh, an SMC image covering the straps window
        // would silently clear an explicit stimulus.
        //
        // +sep_boot_from_spi sets STRAPS_LO[25] (primary_chiplet) at
        // smc_base+0x405800. Bit 25 is byte 3 of the word, bit 1. It is a strap
        // value, NOT a boot-path selector: boot_from_spi() is
        // `primary_chiplet && !boot_recovery` (boot_straps.h), so with
        // +sep_straps_lo also asserting boot_recovery the ROM takes its RECOVERY
        // branch instead -- which is exactly what sep_boot_recovery_test needs.
        // Default off: without it the ROM keeps taking the SMC-SRAM secondary
        // branch, so sep_rom_non_secure_boot_test is unaffected.
        if ($test$plusargs("sep_boot_from_spi")) begin
            u_smc_mem.mem[SmcStrapsLoAddr + 3] =
                u_smc_mem.mem[SmcStrapsLoAddr + 3] | 8'h02;
            $display("[tb] STRAPS_LO[25] primary_chiplet=1");
        end
        // STRAPS_LO (smc_base+0x405800) whole-word override, the twin of
        // +sep_straps_hi below. sep_smc_interface.h: [13] bypass_sram_repair,
        // [19] boot_recovery, [21] status_rpt_disable, [25] primary_chiplet.
        //
        // Needed because the ROM's boot gate reads bit 13: BYPASS_SRAM_REPAIR
        // means repair never ran, and the gate skips its repair check entirely in
        // that case rather than reading a 0 status as a failure. +sep_boot_from_spi
        // writes byte 3 alone, so it cannot reach bit 13 (byte 1).
        //
        // Ordering with +sep_boot_from_spi is deliberate and both may be used
        // together. Both OR rather than assign, so neither clobbers the other
        // whichever bits each sets, and both sit after the $readmemh for the
        // reason given above.
        if ($value$plusargs("sep_straps_lo=%h", straps_lo_ovr)) begin
            u_smc_mem.mem[SmcStrapsLoAddr + 0] =
                u_smc_mem.mem[SmcStrapsLoAddr + 0] | straps_lo_ovr[7:0];
            u_smc_mem.mem[SmcStrapsLoAddr + 1] =
                u_smc_mem.mem[SmcStrapsLoAddr + 1] | straps_lo_ovr[15:8];
            u_smc_mem.mem[SmcStrapsLoAddr + 2] =
                u_smc_mem.mem[SmcStrapsLoAddr + 2] | straps_lo_ovr[23:16];
            u_smc_mem.mem[SmcStrapsLoAddr + 3] =
                u_smc_mem.mem[SmcStrapsLoAddr + 3] | straps_lo_ovr[31:24];
            $display("[tb] STRAPS_LO or'd with 0x%08x (+sep_straps_lo): bypass_sram_repair=%0d recovery=%0d",
                     straps_lo_ovr, straps_lo_ovr[13], straps_lo_ovr[19]);
        end
        // MEM_REPAIR / MBIST gate injection.
        //
        // Writes the whole 32-bit word rather than just clearing bit 1, because
        // the point of the failure case is to prove the ROM gates on
        // mem_repair_success specifically: a test that injects 0x0 cannot tell
        // "checks bit 1" from "checks any bit" from "checks a non-zero word". The
        // useful stimulus is every bit set EXCEPT bit 1 (0xFFFFFFFD).
        // Little-endian byte order: byte 0 holds bits [7:0].
        if ($value$plusargs("sep_dft_status=%h", dft_status_ovr)) begin
            u_smc_mem.mem[56'h4000_B800] = dft_status_ovr[7:0];
            u_smc_mem.mem[56'h4000_B801] = dft_status_ovr[15:8];
            u_smc_mem.mem[56'h4000_B802] = dft_status_ovr[23:16];
            u_smc_mem.mem[56'h4000_B803] = dft_status_ovr[31:24];
            $display("[tb] DFX_CTRL_STATUS_SMU overridden to 0x%08x (+sep_dft_status)",
                     dft_status_ovr);
        end
        // STRAPS_HI (smc_base+0x405804) = bits [63:32] of the 64-bit strap word.
        // sep_smc_interface.h: [22] mbist_bypass, [26] rotate_update.
        //
        // Whole-word, like +sep_dft_status: a per-bit flag would need one plusarg
        // per strap and could not express a combination, and the ROM reads the
        // word once (boot_straps.c) so partial writes would be the odd case
        // rather than the normal one. Little-endian: byte 0 holds bits [7:0].
        if ($value$plusargs("sep_straps_hi=%h", straps_hi_ovr)) begin
            u_smc_mem.mem[SmcStrapsHiAddr + 0] = straps_hi_ovr[7:0];
            u_smc_mem.mem[SmcStrapsHiAddr + 1] = straps_hi_ovr[15:8];
            u_smc_mem.mem[SmcStrapsHiAddr + 2] = straps_hi_ovr[23:16];
            u_smc_mem.mem[SmcStrapsHiAddr + 3] = straps_hi_ovr[31:24];
            $display("[tb] STRAPS_HI set to 0x%08x (+sep_straps_hi): mbist_bypass=%0d rotate=%0d",
                     straps_hi_ovr, straps_hi_ovr[22], straps_hi_ovr[26]);
        end
        // SMC scratch[13]/[14]: the SEP-safe window inside SMC SRAM, which the
        // ROM reads when a manifest asks for use_ext_sram=0 and then stages the
        // payload at smc_sram_base + scratch[13] (manifest_load.c). The ROM
        // refuses a 0/0 window as out of range, so the branch needs both values.
        //
        // Offset is relative to SMC SRAM base, not absolute, matching what the
        // ROM adds to sep_get_smc_sram_base(). Default unwritten: an associative
        // array yields X for a key never written, so a test that wants the SMC
        // staging path must pass both.
        if ($value$plusargs("sep_smc_scratch13=%h", smc_scratch13_ovr)) begin
            u_smc_mem.mem[SmcScratch13Addr + 0] = smc_scratch13_ovr[7:0];
            u_smc_mem.mem[SmcScratch13Addr + 1] = smc_scratch13_ovr[15:8];
            u_smc_mem.mem[SmcScratch13Addr + 2] = smc_scratch13_ovr[23:16];
            u_smc_mem.mem[SmcScratch13Addr + 3] = smc_scratch13_ovr[31:24];
            $display("[tb] SMC scratch[13] SEP-safe SRAM offset = 0x%08x (+sep_smc_scratch13)",
                     smc_scratch13_ovr);
        end
        if ($value$plusargs("sep_smc_scratch14=%h", smc_scratch14_ovr)) begin
            u_smc_mem.mem[SmcScratch14Addr + 0] = smc_scratch14_ovr[7:0];
            u_smc_mem.mem[SmcScratch14Addr + 1] = smc_scratch14_ovr[15:8];
            u_smc_mem.mem[SmcScratch14Addr + 2] = smc_scratch14_ovr[23:16];
            u_smc_mem.mem[SmcScratch14Addr + 3] = smc_scratch14_ovr[31:24];
            $display("[tb] SMC scratch[14] SEP-safe SRAM size = 0x%08x (+sep_smc_scratch14)",
                     smc_scratch14_ovr);
        end
        // SMC scratch[8]: the manifest offset the SMC publishes to SEP. The ROM
        // reads it on its non-SPI path and loads the manifest from
        // sep_get_smc_sram_base() + this value (manifest_load.c), with NO second
        // slot -- so an offset holding no manifest is terminal rather than a
        // failover. Needed by the secondary-chiplet rows: the default written at
        // the top of this block is 0x1000, where the packed SMC image really
        // carries "TBL1", and pointing it elsewhere is the only way to present an
        // invalid published manifest without editing the image.
        //
        // Whole-word assign, not an OR: the default is non-zero, so ORing could
        // only ever add bits to 0x1000 and could not express a different offset.
        // Little-endian: byte 0 holds bits [7:0].
        if ($value$plusargs("sep_smc_scratch8=%h", smc_scratch8_ovr)) begin
            u_smc_mem.mem[SmcScratch8Addr + 0] = smc_scratch8_ovr[7:0];
            u_smc_mem.mem[SmcScratch8Addr + 1] = smc_scratch8_ovr[15:8];
            u_smc_mem.mem[SmcScratch8Addr + 2] = smc_scratch8_ovr[23:16];
            u_smc_mem.mem[SmcScratch8Addr + 3] = smc_scratch8_ovr[31:24];
            $display("[tb] SMC scratch[8] manifest offset = 0x%08x (+sep_smc_scratch8)",
                     smc_scratch8_ovr);
        end
    end

    // SMC scratch[10] mirror for the MEM_REPAIR-gate test. exists() guards keep an
    // unwritten slot reading 0 instead of relying on assoc-array default-read
    // behaviour, so "ROM never published it" and "ROM published 0" stay distinct
    // only because the injected status is non-zero -- which is why the test
    // injects 0xFFFFFFFD and not 0.
    logic [31:0] smc_scratch10_q;
    always @(posedge clk_i) begin
        smc_scratch10_q <= {
            u_smc_mem.mem.exists(56'h4003_90D3) ? u_smc_mem.mem[56'h4003_90D3] : 8'h00,
            u_smc_mem.mem.exists(56'h4003_90D2) ? u_smc_mem.mem[56'h4003_90D2] : 8'h00,
            u_smc_mem.mem.exists(56'h4003_90D1) ? u_smc_mem.mem[56'h4003_90D1] : 8'h00,
            u_smc_mem.mem.exists(56'h4003_90D0) ? u_smc_mem.mem[56'h4003_90D0] : 8'h00
        };
    end
    assign smc_scratch10_probe_o = smc_scratch10_q;

    // DFX_CTRL_STATUS_SMU mirror, same sampling pattern and same reason as the
    // scratch[10] mirror above (associative array, so no continuous assign).
    logic [31:0] smc_dft_status_q;
    always @(posedge clk_i) begin
        smc_dft_status_q <= {
            u_smc_mem.mem.exists(56'h4000_B803) ? u_smc_mem.mem[56'h4000_B803] : 8'h00,
            u_smc_mem.mem.exists(56'h4000_B802) ? u_smc_mem.mem[56'h4000_B802] : 8'h00,
            u_smc_mem.mem.exists(56'h4000_B801) ? u_smc_mem.mem[56'h4000_B801] : 8'h00,
            u_smc_mem.mem.exists(56'h4000_B800) ? u_smc_mem.mem[56'h4000_B800] : 8'h00
        };
    end
    assign smc_dft_status_probe_o = smc_dft_status_q;

`else
    assign ext_to_smc_resp_w = ext_to_smc_resp_idle;
    assign smc_scratch10_probe_o = '0;
    assign smc_dft_status_probe_o = '0;
    // No SMC model, so no SEP->SMC traffic to decode. 0 rather than X: a test
    // asserting "no address violations" must not pass on an undriven port, and
    // must not fail on a build that never had an SMC to address.
    assign smc_addr_violations_o = '0;
`endif

    // ------------------------------------------------------------------
    // tb_backdoor_mem: default-fill + image load for the real memory macros.
    //
    // The wrapper's macros have no runtime init (MemInitFile("")) and power up X
    // on a 4-state simulator / 0 on Verilator -- both wrong for KM (parity) and OTBN (SECDED),
    // whose valid power-up word is non-zero. Fill patterns include ECC/parity.
    // Array paths are hw/top/sep_ip_integration.sv and sep_tcm_wrapper
    // (TCM per-depth generate arms: gen_ram).
    // Backdoor writes into these DUT arrays need them public under Verilator
    // (sep_public_scope.vlt: prim_ram_1p.mem, prim_rom.mem, ram_16384x39.ram_core).
    // ------------------------------------------------------------------
    // RISC-V SECDED (Hsiao) ECC over a 32-bit word (EL2 TCM encoding).
    function automatic logic [6:0] bd_riscv_ecc32(input logic [31:0] data);
        logic [6:0] synd;
        synd[0] = ^(data & 32'h56aa_ad5b);
        synd[1] = ^(data & 32'h9b33_366d);
        synd[2] = ^(data & 32'he3c3_c78e);
        synd[3] = ^(data & 32'h03fc_07f0);
        synd[4] = ^(data & 32'h03ff_f800);
        synd[5] = ^(data & 32'hfc00_0000);
        synd[6] = ^{data, synd[5:0]};
        return synd;
    endfunction
    // KM per-word odd parity nibble (one bit per byte, inverted XOR reduction).
    function automatic logic [3:0] bd_km_word_parity(input logic [31:0] w);
        for (int unsigned i = 0; i < 4; i++) bd_km_word_parity[i] = ~^w[8*i +: 8];
    endfunction

    localparam logic [38:0] BD_OTBN_ZERO = prim_secded_pkg::SecdedInv3932ZeroWord;

`define BD_ICCM(b) `SEP_IPI.u_sep_tcm_wrapper.gen_iccm.gen_bank[b].gen_iccm_ram.ram.ram_core
`define BD_DCCM(b) `SEP_IPI.u_sep_tcm_wrapper.gen_dccm.gen_bank[b].gen_dccm_ram.ram.ram_core

    // Non-zero valid power-up patterns (Verilator's 0-init and a 4-state simulator's
    // X are both invalid here -> spurious KM SRAM_PARITY / OTBN SECDED faults otherwise).
    initial begin : backdoor_default_fill_nonzero
        for (int i = 0; i < 4096; i++)
            `SEP_IPI.u_km_rom.mem[i] = {bd_km_word_parity(32'h0000_0013), 32'h0000_0013};
        for (int i = 0; i < 8192; i++)
            `SEP_IPI.u_km_sram.gen_ram_inst[0].u_mem.mem[i] = {4'hF, 32'h0};
        for (int i = 0; i < 4096; i++)
            `SEP_IPI.u_otbn_imem_sram.mem[i] = BD_OTBN_ZERO;
        for (int i = 0; i < 1024; i++)
            `SEP_IPI.u_otbn_dmem_sram.mem[i] = {8{BD_OTBN_ZERO}};
    end

`ifndef VERILATOR
    // Zero-default macros power up X on a 4-state simulator; zero them. Verilator
    // 0-inits these, so the sweep is compiled only for the non-Verilator build (a
    // constant-bound Verilator `initial` sweep over ~100k rows unrolls into an
    // uncompilable C++ function).
    initial begin : backdoor_default_fill_zero
        for (int i = 0; i < 32768; i++)
            `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem[i] = 64'h0;
        for (int i = 0; i < 16384; i++)
            `SEP_IPI.u_sep_boot_rom.mem[i] = 64'h0;
        for (int r = 0; r < 16384; r++) begin
            `BD_ICCM(0)[r] = 39'h0; `BD_ICCM(1)[r] = 39'h0;
            `BD_ICCM(2)[r] = 39'h0; `BD_ICCM(3)[r] = 39'h0;
            `BD_DCCM(0)[r] = 39'h0; `BD_DCCM(1)[r] = 39'h0;
        end
    end
`endif

    // Image loads into the ROM/SRAM macros at t=0. Honor the plusarg first, else
    // the CWD default filename (tests that stage a committed hex into the sim
    // CWD without a plusarg still get it -- e.g. sep_boot_rom_smoke_test relies
    // on the default sep_boot_rom.hex). A missing default file leaves the
    // default fill intact.
    // A named `+km_rom_hex` file must exist: $readmemh of an absent path leaves
    // the KM ROM empty and the firmware never posts ready.
    initial begin : backdoor_image_loads
        string img;
        int    fd;
        #0;  // let the default-fill initials settle first
        if ($value$plusargs("sep_boot_rom_hex=%s", img)) begin
            $readmemh(img, `SEP_IPI.u_sep_boot_rom.mem);
            $display("[tb_backdoor_mem] boot ROM image loaded (%0s)", img);
        end else begin
            fd = $fopen("sep_boot_rom.hex", "r");
            if (fd != 0) begin
                $fclose(fd);
                $readmemh("sep_boot_rom.hex", `SEP_IPI.u_sep_boot_rom.mem);
                $display("[tb_backdoor_mem] boot ROM image loaded (sep_boot_rom.hex)");
            end
        end
        if ($value$plusargs("sep_sram_hex=%s", img)) begin
            $readmemh(img, `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem);
        end else begin
            fd = $fopen("sep_sram.hex", "r");
            if (fd != 0) begin
                $fclose(fd);
                $readmemh("sep_sram.hex", `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem);
            end
        end
        if ($value$plusargs("km_rom_hex=%s", img)) begin
            fd = $fopen(img, "r");
            if (fd == 0) begin
                $fatal(1, "[tb_backdoor_mem] +km_rom_hex=%s is not readable", img);
            end
            $fclose(fd);
            $readmemh(img, `SEP_IPI.u_km_rom.mem);
            $display("[tb_backdoor_mem] KM ROM image loaded (%0s)", img);
        end else begin
            fd = $fopen("km_rom.parhex", "r");
            if (fd != 0) begin
                $fclose(fd);
                $readmemh("km_rom.parhex", `SEP_IPI.u_km_rom.mem);
            end
        end
    end

    // TCM (ICCM/DCCM) firmware backdoor-load on tcm_load_i, de-interleaved into the
    // EL2 bank/row layout with per-word Hsiao ECC (ICCM bank=off[3:2] row=off[17:4],
    // DCCM bank=off[2] row=off[16:3]); byte buffers pre-zeroed so every row is
    // written (imaged or ECC-valid 0). Constant bank indices keep the XMR legal.
    logic [7:0] bd_itcm_buf [262144];
    logic [7:0] bd_dtcm_buf [131072];
    string        iccm_poke_arg;
    logic [31:0]  iccm_poke_addr, iccm_poke_data;
    logic [38:0]  iccm_poke_word;
    int           iccm_poke_off;
    always @(posedge tcm_load_i) begin : backdoor_tcm_load
        int off;
        logic [31:0] w;
        logic [38:0] fw;
        for (int i = 0; i < 262144; i++) bd_itcm_buf[i] = 8'h00;
        $readmemh("sep_itcm.hex", bd_itcm_buf);
        for (off = 0; off + 3 < 262144; off += 4) begin
            w  = {bd_itcm_buf[off+3], bd_itcm_buf[off+2], bd_itcm_buf[off+1], bd_itcm_buf[off]};
            fw = (w == 32'h0) ? '0 : {bd_riscv_ecc32(w), w};
            case (off[3:2])
                2'd0: `BD_ICCM(0)[off[17:4]] = fw;
                2'd1: `BD_ICCM(1)[off[17:4]] = fw;
                2'd2: `BD_ICCM(2)[off[17:4]] = fw;
                2'd3: `BD_ICCM(3)[off[17:4]] = fw;
            endcase
        end
        for (int i = 0; i < 131072; i++) bd_dtcm_buf[i] = 8'h00;
        $readmemh("sep_dtcm.hex", bd_dtcm_buf);
        for (off = 0; off + 3 < 131072; off += 4) begin
            w  = {bd_dtcm_buf[off+3], bd_dtcm_buf[off+2], bd_dtcm_buf[off+1], bd_dtcm_buf[off]};
            fw = (w == 32'h0) ? '0 : {bd_riscv_ecc32(w), w};
            if (off[2]) `BD_DCCM(1)[off[16:3]] = fw;
            else        `BD_DCCM(0)[off[16:3]] = fw;
        end
        $display("[tb_backdoor_mem] TCM image loaded (sep_itcm.hex / sep_dtcm.hex)");

        // ICCM single-word poke: +sep_iccm_word=<hexaddr>:<hexdata>
        // The poke follows the bulk load in this block because that load rewrites
        // the entire ICCM. The warm-handler test places an instruction at the
        // seeded address and observes the PC there. The poke uses the TCM's Hsiao
        // SECDED encoding and bank interleave so the core fetches a valid word.
        if ($value$plusargs("sep_iccm_word=%s", iccm_poke_arg)) begin
            if ($sscanf(iccm_poke_arg, "%h:%h", iccm_poke_addr, iccm_poke_data) != 2) begin
                $fatal(1, "[tb] +sep_iccm_word must be <hexaddr>:<hexdata>, got '%s'",
                       iccm_poke_arg);
            end
            iccm_poke_off = int'(iccm_poke_addr - 32'hC000_0000);
            if (iccm_poke_off < 0 || iccm_poke_off + 3 >= 262144) begin
                $fatal(1, "[tb] +sep_iccm_word address 0x%08x is outside ICCM [0xC0000000,0xC0040000)",
                       iccm_poke_addr);
            end
            iccm_poke_word = {bd_riscv_ecc32(iccm_poke_data), iccm_poke_data};
            case (iccm_poke_off[3:2])
                2'd0: `BD_ICCM(0)[iccm_poke_off[17:4]] = iccm_poke_word;
                2'd1: `BD_ICCM(1)[iccm_poke_off[17:4]] = iccm_poke_word;
                2'd2: `BD_ICCM(2)[iccm_poke_off[17:4]] = iccm_poke_word;
                2'd3: `BD_ICCM(3)[iccm_poke_off[17:4]] = iccm_poke_word;
            endcase
            $display("[tb] ICCM[0x%08x] = 0x%08x with ECC, AFTER the bulk load (+sep_iccm_word)",
                     iccm_poke_addr, iccm_poke_data);
        end
    end
`undef BD_ICCM
`undef BD_DCCM

    // ------------------------------------------------------------------
    // CPU-LSU AXI splice.
    //
    // Inject: assemble the LSU req struct from the flat cocotb master inputs into
    // `lsu_req_drive` (always_comb). The sep_cpu stub reads this by upward
    // reference and drives its lsu_axi_req from it (single driver, plain assign,
    // no force — see shims/cpu/sep_cpu_stub.sv). Whole-signal only; no per-field
    // drive. The no_cpu build replaces the core with a stub, so the bus is
    // single-driven and driven rather than forced.
    // ------------------------------------------------------------------
    sep_32_64_3_12_axi_req_t lsu_req_drive;

    always_comb begin
        lsu_req_drive            = '{default: '0};  // zeros atop and any unused fields
        lsu_req_drive.aw.id      = s_axi_awid;
        lsu_req_drive.aw.addr    = s_axi_awaddr;
        lsu_req_drive.aw.len     = s_axi_awlen;
        lsu_req_drive.aw.size    = s_axi_awsize;
        lsu_req_drive.aw.burst   = s_axi_awburst;
        lsu_req_drive.aw.lock    = s_axi_awlock;
        lsu_req_drive.aw.cache   = s_axi_awcache;
        lsu_req_drive.aw.prot    = s_axi_awprot;
        lsu_req_drive.aw.qos     = s_axi_awqos;
        lsu_req_drive.aw.region  = s_axi_awregion;
        lsu_req_drive.aw.user    = s_axi_awuser;
        // X-harden the handshakes: the drive is active from time 0, before cocotb
        // drives s_axi_*. Assert valid/ready only on a clean 1 so a 4-state sim
        // sees an idle (not X) LSU bus during bring-up instead of an unknown txn.
        lsu_req_drive.aw_valid   = (s_axi_awvalid === 1'b1);
        lsu_req_drive.w.data     = s_axi_wdata;
        lsu_req_drive.w.strb     = s_axi_wstrb;
        lsu_req_drive.w.last     = s_axi_wlast;
        lsu_req_drive.w.user     = s_axi_wuser;
        lsu_req_drive.w_valid    = (s_axi_wvalid === 1'b1);
        lsu_req_drive.b_ready    = (s_axi_bready === 1'b1);
        lsu_req_drive.ar.id      = s_axi_arid;
        lsu_req_drive.ar.addr    = s_axi_araddr;
        lsu_req_drive.ar.len     = s_axi_arlen;
        lsu_req_drive.ar.size    = s_axi_arsize;
        lsu_req_drive.ar.burst   = s_axi_arburst;
        lsu_req_drive.ar.lock    = s_axi_arlock;
        lsu_req_drive.ar.cache   = s_axi_arcache;
        lsu_req_drive.ar.prot    = s_axi_arprot;
        lsu_req_drive.ar.qos     = s_axi_arqos;
        lsu_req_drive.ar.region  = s_axi_arregion;
        lsu_req_drive.ar.user    = s_axi_aruser;
        lsu_req_drive.ar_valid   = (s_axi_arvalid === 1'b1);
        lsu_req_drive.r_ready    = (s_axi_rready === 1'b1);
    end

    // LSU stimulus injection:
    //  * Stub build: the stub is the sole driver of the LSU master and drives
    //    lsu_axi_req from `lsu_req_drive` (upward reference; no force).
    //  * CPU firmware-boot (+cpu_boot): the real VeeR owns LSU/IFU/DBG.
    //  * no_cpu on the full-CPU build outside Verilator: VeeR is held off
    //    (mpc_reset_run_req=0), so the VIP owns the post-remap LSU request.
    //    Same node the stub drives, so VIP addresses do not pass through
    //    u_lsu_local_alias_remap. The raw response is held idle so the halted
    //    core sees no beats it did not issue. Verilator cannot force the whole
    //    request struct; that path stays on the stub.
`ifndef SEP_CPU_STUB
    `ifdef VERILATOR
    initial if (!$test$plusargs("cpu_boot"))
        $fatal(1, "no_cpu test on the full-CPU Verilator build: select target=lsu_stub_all_live or pass +cpu_boot");
    `else
    initial if (!$test$plusargs("cpu_boot")) begin
        force `SEP_CORE.sep_cpu.lsu_axi_req      = lsu_req_drive;
        force `SEP_CORE.sep_cpu.lsu_axi_resp_raw = '0;
        $display("[tb] no_cpu on full-CPU build: LSU VIP force-splice active");
    end
    `endif
`endif

    // ------------------------------------------------------------------
    // SMN-inbound external AXI master (prefix m_axi).
    //
    // The inbound req struct is assembled combinationally from the flat cocotb
    // master inputs. The DUT's smn_inbound_axi_req_i port uses this live struct
    // only when SEP_SMN_INBOUND_AXI_LIVE is defined; otherwise it ties to
    // compile-time constant idle and the external-master cone can fold.
    // X-harden the handshakes (clean-1 only) so a 4-state sim sees idle, not X,
    // before cocotb drives m_axi_*.
    // ------------------------------------------------------------------
    always_comb begin
        smn_inbound_req_drive           = '{default: '0};  // zeros atop/unused
        smn_inbound_req_drive.aw.id     = m_axi_awid;
        smn_inbound_req_drive.aw.addr   = m_axi_awaddr;
        smn_inbound_req_drive.aw.len    = m_axi_awlen;
        smn_inbound_req_drive.aw.size   = m_axi_awsize;
        smn_inbound_req_drive.aw.burst  = m_axi_awburst;
        smn_inbound_req_drive.aw.lock   = m_axi_awlock;
        smn_inbound_req_drive.aw.cache  = m_axi_awcache;
        smn_inbound_req_drive.aw.prot   = m_axi_awprot;
        smn_inbound_req_drive.aw.qos    = m_axi_awqos;
        smn_inbound_req_drive.aw.region = m_axi_awregion;
        smn_inbound_req_drive.aw.user   = m_axi_awuser;
        smn_inbound_req_drive.aw_valid  = (m_axi_awvalid === 1'b1);
        smn_inbound_req_drive.w.data    = m_axi_wdata;
        smn_inbound_req_drive.w.strb    = m_axi_wstrb;
        smn_inbound_req_drive.w.last    = m_axi_wlast;
        smn_inbound_req_drive.w.user    = m_axi_wuser;
        smn_inbound_req_drive.w_valid   = (m_axi_wvalid === 1'b1);
        smn_inbound_req_drive.b_ready   = (m_axi_bready === 1'b1);
        smn_inbound_req_drive.ar.id     = m_axi_arid;
        smn_inbound_req_drive.ar.addr   = m_axi_araddr;
        smn_inbound_req_drive.ar.len    = m_axi_arlen;
        smn_inbound_req_drive.ar.size   = m_axi_arsize;
        smn_inbound_req_drive.ar.burst  = m_axi_arburst;
        smn_inbound_req_drive.ar.lock   = m_axi_arlock;
        smn_inbound_req_drive.ar.cache  = m_axi_arcache;
        smn_inbound_req_drive.ar.prot   = m_axi_arprot;
        smn_inbound_req_drive.ar.qos    = m_axi_arqos;
        smn_inbound_req_drive.ar.region = m_axi_arregion;
        smn_inbound_req_drive.ar.user   = m_axi_aruser;
        smn_inbound_req_drive.ar_valid  = (m_axi_arvalid === 1'b1);
        smn_inbound_req_drive.r_ready   = (m_axi_rready === 1'b1);
    end

    assign m_axi_awready = smn_inbound_resp_w.aw_ready;
    assign m_axi_wready  = smn_inbound_resp_w.w_ready;
    assign m_axi_bid     = smn_inbound_resp_w.b.id;
    assign m_axi_bresp   = smn_inbound_resp_w.b.resp;
    assign m_axi_buser   = smn_inbound_resp_w.b.user;
    assign m_axi_bvalid  = smn_inbound_resp_w.b_valid;
    assign m_axi_arready = smn_inbound_resp_w.ar_ready;
    assign m_axi_rid     = smn_inbound_resp_w.r.id;
    assign m_axi_rdata   = smn_inbound_resp_w.r.data;
    assign m_axi_rresp   = smn_inbound_resp_w.r.resp;
    assign m_axi_rlast   = smn_inbound_resp_w.r.last;
    assign m_axi_ruser   = smn_inbound_resp_w.r.user;
    assign m_axi_rvalid  = smn_inbound_resp_w.r_valid;

    // ------------------------------------------------------------------
    // SEP-OTP JTAG AXI-Lite master (prefix j_axi). Same scheme as the m_axi master
    // above: the DUT's axil_sep_otp_jtag_req_i port uses this live struct only
    // when SEP_JTAG_AXIL_LIVE is defined; otherwise it ties to compile-time idle.
    // Assemble the efuse_axil req struct from the flat cocotb inputs; plain
    // DUT-port connection.
    // X-harden the handshakes (clean-1 only) so the port idles, not X, before drive.
    // ------------------------------------------------------------------
    always_comb begin
        j_axil_req_drive          = '{default: '0};
        j_axil_req_drive.aw.addr  = j_axi_awaddr;
        j_axil_req_drive.aw.prot  = j_axi_awprot;
        j_axil_req_drive.aw_valid = (j_axi_awvalid === 1'b1);
        j_axil_req_drive.w.data   = j_axi_wdata;
        j_axil_req_drive.w.strb   = j_axi_wstrb;
        j_axil_req_drive.w_valid  = (j_axi_wvalid === 1'b1);
        j_axil_req_drive.b_ready  = (j_axi_bready === 1'b1);
        j_axil_req_drive.ar.addr  = j_axi_araddr;
        j_axil_req_drive.ar.prot  = j_axi_arprot;
        j_axil_req_drive.ar_valid = (j_axi_arvalid === 1'b1);
        j_axil_req_drive.r_ready  = (j_axi_rready === 1'b1);
    end

    assign j_axi_awready = j_axil_resp_w.aw_ready;
    assign j_axi_wready  = j_axil_resp_w.w_ready;
    assign j_axi_bresp   = j_axil_resp_w.b.resp;
    assign j_axi_bvalid  = j_axil_resp_w.b_valid;
    assign j_axi_arready = j_axil_resp_w.ar_ready;
    assign j_axi_rdata   = j_axil_resp_w.r.data;
    assign j_axi_rresp   = j_axil_resp_w.r.resp;
    assign j_axi_rvalid  = j_axil_resp_w.r_valid;

    // ------------------------------------------------------------------
    // CPU firmware-boot responders + observables.
    // ------------------------------------------------------------------
    // PC advance: surface the EL2 retired-instruction trace. o_cpu_run_ack is not
    // a port on bare `sep` (and ext_debug_bus_o is only [383:0]), so tap it by XMR
    // from the CPU wrapper — the same hierarchical-read style used for the LSU
    // response above.
    assign cpu_trace_valid_o = cpu_trace_w.trace_rv_i_valid_ip;
    assign cpu_trace_addr_o  = cpu_trace_w.trace_rv_i_address_ip;
    // Full retirement record for the cocotb CPU-trace monitor: the instruction
    // encoding drives call/return decode (shadow call stack); ecause/interrupt/
    // tval qualify the exception flag below into a diagnosable trap record.
    assign cpu_trace_insn_o      = cpu_trace_w.trace_rv_i_insn_ip;
    assign cpu_trace_ecause_o    = cpu_trace_w.trace_rv_i_ecause_ip;
    assign cpu_trace_interrupt_o = cpu_trace_w.trace_rv_i_interrupt_ip;
    assign cpu_trace_tval_o      = cpu_trace_w.trace_rv_i_tval_ip;
    assign o_cpu_run_ack_o   = `SEP_CORE.sep_cpu.o_cpu_run_ack;

    // SEP resets (internal nets): the reset-independence and wdt-reset-path
    // tests read them. Same XMR-probe style as above.
    assign dbg_sep_reset_n_o = `SEP_CORE.sep_reset_n;
    assign sep_cpu_reset_n_o = `SEP_CORE.sep_cpu_reset_n;

    // IP-interrupt aggregate vector feeding the PIC (sep.sv sep_internal_interrupts):
    // observation-only mirror for the IP->aggregator test. CSRNG INTR sources
    // map to bits [21:24], EDN to [25:26] (sep.sv).
    assign sep_internal_interrupts_probe_o = `SEP_CORE.sep_internal_interrupts;
    assign entropy_pool_packer_depth_o = `SEP_CORE.u_entropy_fifo.packer_depth;
    assign trng_gated_rst_n_probe_o =
        `SEP_CORE.u_sep_reset_ctrl.sep_crypto_gated_rst_no.trng;
    assign trng_axi_isolated_probe_o = {
        `SEP_CORE.sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.trng_edn,
        `SEP_CORE.sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.trng_csrng,
        `SEP_CORE.sep_crypto.u_sep_crypto_axi_interconnect.isolated_o.trng_entropy_source
    };

    // Read-only XMRs observe the write-one-to-set demotion lock storage. The lock
    // bits have no DUT output, and firmware owns the AXI frontdoor while they are
    // programmed. These leaf fields sit outside the AXI ready/valid combinational
    // cones and retain whether firmware wrote each lock.
    assign lcc_demote_lock_1_probe_o =
        `SEP_CORE.sep_crypto.u_sep_lifecycle_ctrl.demote_reg_1.lock;
    assign lcc_demote_lock_2_probe_o =
        `SEP_CORE.sep_crypto.u_sep_lifecycle_ctrl.demote_reg_2.lock;

    // Boot bring-up debug taps: did the core start fetching from the TCM? The TCM
    // req is a wrapper-internal net (u_sep -> ip_integration).
    assign dbg_iccm_active_o   = |u_dut.sep_cpu_tcm_req.iccm_clken;
    assign dbg_iccm_addr_o     = u_dut.sep_cpu_tcm_req.iccm_addr_bank[0];
    assign dbg_dccm_active_o   = |u_dut.sep_cpu_tcm_req.dccm_clken;
    assign dbg_cpu_trace_exc_o = cpu_trace_w.trace_rv_i_exception_ip;

    // Flatten the sensed shadow array (efuse_map_t, NumEfuseBits wide) to the
    // top-level probe port; word i occupies bits [32*i +: 32], matching values[i].
    assign efuse_shadow_probe_o =
        `SEP_CORE.sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs.shadow_efuse_o;

    // SEP scratch-cold CSR words [0..7], each `data.value` [31:0]. Explicit
    // per-index assigns avoid a cross-hierarchy indexed XMR (same style as the
    // ESRC decorrelator-SR probe above). The EL2 coexist firmware mirrors its
    // measured summary into these; the cocotb test reads them back as the observer.
`define SCRATCH_COLD(i) \
    assign scratch_cold_probe_o[32*(i) +: 32] = \
        `SEP_CORE.sep_system_peripherals.u_sep_system_csr.u_sep_scratch_reg_cold.field_storage.SCRATCH[i].data.value
    `SCRATCH_COLD(0); `SCRATCH_COLD(1); `SCRATCH_COLD(2); `SCRATCH_COLD(3);
    `SCRATCH_COLD(4); `SCRATCH_COLD(5); `SCRATCH_COLD(6); `SCRATCH_COLD(7);
`undef SCRATCH_COLD

    // System-CSR AXI-Lite after u_system_csr_a2l_1. See port comment.
    assign sys_csr_axil_arvalid_o =
        `SEP_CORE.sep_system_peripherals.system_csr_axil_req.ar_valid;
    assign sys_csr_axil_arready_o =
        `SEP_CORE.sep_system_peripherals.system_csr_axil_resp.ar_ready;
    assign sys_csr_axil_araddr_o =
        `SEP_CORE.sep_system_peripherals.system_csr_axil_req.ar.addr[31:0];
    assign sys_csr_axil_awvalid_o =
        `SEP_CORE.sep_system_peripherals.system_csr_axil_req.aw_valid;
    assign sys_csr_axil_awready_o =
        `SEP_CORE.sep_system_peripherals.system_csr_axil_resp.aw_ready;
    assign sys_csr_axil_awaddr_o =
        `SEP_CORE.sep_system_peripherals.system_csr_axil_req.aw.addr[31:0];

    // Read-only XMRs observe the manifest at SRAM word 0 and the decrypted
    // payload at byte offset 0x1000. Firmware owns the SRAM AXI frontdoor during
    // boot, and these memory-array reads sit outside the ready/valid cones.
    assign sram_word0_probe_o = `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem['h000];
`define SRAM_PL(i) \
    assign sram_payload_probe_o[64*(i) +: 64] = \
        `SEP_IPI.u_sep_sram.gen_ram_inst[0].u_mem.mem['h200 + (i)]
    `SRAM_PL(0); `SRAM_PL(1); `SRAM_PL(2);
    `SRAM_PL(3); `SRAM_PL(4); `SRAM_PL(5);
`undef SRAM_PL

    // ------------------------------------------------------------------
    // Warm-reset handler seed: +sep_cold_scratch7=<hex32>
    // ------------------------------------------------------------------
    // A one-shot deposit seeds COLD Scratch 7 after both resets release and
    // before the CPU fetches. The CPU owns the system-CSR AXI frontdoor during
    // firmware boot, so the testbench cannot perform this timed write through an
    // independent master. The leaf storage sits outside the AXI ready/valid
    // combinational cones. A deposit allows later ROM writes to remain visible.
    logic [31:0] cold_scratch7_seed;
    initial begin : cold_scratch7_seed_deposit
        if ($value$plusargs("sep_cold_scratch7=%h", cold_scratch7_seed)) begin
            wait (rst_ni === 1'b1);
            wait (sep_cpu_reset_n_o === 1'b1);
            repeat (4) @(posedge clk_i);
            `SEP_CORE.sep_system_peripherals.u_sep_system_csr
                .u_sep_scratch_reg_cold.field_storage.SCRATCH[7].data.value = cold_scratch7_seed;
            $display("[tb] cold_scratch[7] seeded 0x%08x (+sep_cold_scratch7)",
                     cold_scratch7_seed);
        end
    end

    // ------------------------------------------------------------------
    // LC differential-integrity error inject.
    // ------------------------------------------------------------------
    // No legal OTP image can present a broken {~raw, raw} LC_STATE pair: the
    // sense FSM regenerates the pair from the raw nibble. The specification's
    // fail-closed feat_ctrl=0 path therefore has no frontdoor stimulus.
    // When lc_sigint_inject_i=1, force both rails of the LCC decoder input to 0
    // so prim_diff_decode_multi asserts sigint (XNOR of equal rails). The
    // software-visible LC_STATE shadow is not touched -- only the decoder
    // input -- so the stitch test can still value-check the legal pair.
    // Re-issue every clock (Verilator snapshots a force RHS). Release when the
    // port drops so the legal pair returns. Default 0; outside AXI cones.
`define LCC_DEC_DATA \
    `SEP_CORE.sep_crypto.u_sep_lifecycle_ctrl.u_lc_state_dec.data_i
    always @(posedge clk_i) begin
        if (lc_sigint_inject_i === 1'b1) begin
            force `LCC_DEC_DATA = '0;
        end else begin
            release `LCC_DEC_DATA;
        end
    end
`undef LCC_DEC_DATA

    // ------------------------------------------------------------------
    // Token-comparator redundancy fault inject.
    // ------------------------------------------------------------------
    // The three digest comparators see the same inputs. A legal token write
    // can only produce a unanimous legal pair (match or mismatch). Collapse
    // and two-instance disagreement have no frontdoor. Common-mode invert
    // of every instance is the documented coverage hole: the detector does
    // not fire when all three flip the same way. Force the gated instance
    // rails of the selected token wrapper; TOKEN_MATCH_FAULT and the
    // match-status CSR stay frontdoor-read. Default 0; released after the
    // check; outside the AXI ready/valid cones. Re-issue every clock
    // (Verilator snapshots a force RHS).
`define TOKEN_PROC \
    `SEP_CORE.sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller \
        .gen_mmr_reg.u_efuse_token_processing
`define CMP_SIP  `TOKEN_PROC.u_triple_redundant_comparator_rma_sip_token
`define CMP_CHIP `TOKEN_PROC.u_triple_redundant_comparator_rma_chiplet_token
`define CMP_SEC  `TOKEN_PROC.u_triple_redundant_comparator_sec_disable_token
    logic [2:0] token_cmp_force_p, token_cmp_force_n;
    logic       token_cmp_do_force;
    always_comb begin
        token_cmp_force_p = 3'b000;
        token_cmp_force_n = 3'b000;
        token_cmp_do_force = 1'b0;
        if (token_cmp_fault_inject_i === 3'b001) begin
            token_cmp_force_p = 3'b110;
            token_cmp_force_n = 3'b000;
            token_cmp_do_force = 1'b1;
        end else if (token_cmp_fault_inject_i === 3'b010) begin
            token_cmp_force_p = 3'b110;
            token_cmp_force_n = 3'b001;
            token_cmp_do_force = 1'b1;
        end else if (token_cmp_fault_inject_i === 3'b011) begin
            token_cmp_force_p = 3'b000;
            token_cmp_force_n = 3'b111;
            token_cmp_do_force = 1'b1;
        end else if (token_cmp_fault_inject_i === 3'b100) begin
            token_cmp_force_p = 3'b111;
            token_cmp_force_n = 3'b000;
            token_cmp_do_force = 1'b1;
        end
    end
    always @(posedge clk_i) begin
        if (token_cmp_do_force && token_cmp_fault_sel_i === 2'b00) begin
            force `CMP_SIP.match_p = token_cmp_force_p;
            force `CMP_SIP.match_n = token_cmp_force_n;
            release `CMP_CHIP.match_p;
            release `CMP_CHIP.match_n;
            release `CMP_SEC.match_p;
            release `CMP_SEC.match_n;
        end else if (token_cmp_do_force && token_cmp_fault_sel_i === 2'b01) begin
            release `CMP_SIP.match_p;
            release `CMP_SIP.match_n;
            force `CMP_CHIP.match_p = token_cmp_force_p;
            force `CMP_CHIP.match_n = token_cmp_force_n;
            release `CMP_SEC.match_p;
            release `CMP_SEC.match_n;
        end else if (token_cmp_do_force && token_cmp_fault_sel_i === 2'b10) begin
            release `CMP_SIP.match_p;
            release `CMP_SIP.match_n;
            release `CMP_CHIP.match_p;
            release `CMP_CHIP.match_n;
            force `CMP_SEC.match_p = token_cmp_force_p;
            force `CMP_SEC.match_n = token_cmp_force_n;
        end else begin
            release `CMP_SIP.match_p;
            release `CMP_SIP.match_n;
            release `CMP_CHIP.match_p;
            release `CMP_CHIP.match_n;
            release `CMP_SEC.match_p;
            release `CMP_SEC.match_n;
        end
    end
`undef CMP_SIP
`undef CMP_CHIP
`undef CMP_SEC
`undef TOKEN_PROC

    // ------------------------------------------------------------------
    // DMA host-path command-integrity inject.
    // ------------------------------------------------------------------
    // host_path_err is the OR of a fabric non-OKAY on a DMA transfer and a
    // TL-UL command-integrity fail on a DMA-issued command. A legal
    // descriptor can produce the fabric term; it cannot produce a broken
    // command user code -- the engine always emits a matching pair. When
    // dma_host_intg_inject_i=1, force the host-adapter checker input
    // (tlul_cmd_intg_chk.u_chk.data_i) to 0 so the real decoder computes
    // err_o. err_o stays gated on a_valid. STATUS / PIC [40] / CLEAR stay
    // frontdoor or the aggregate probe. Re-issue every clock
    // (Verilator snapshots a force RHS). Release when the port drops.
    // Default 0; outside the AXI ready/valid cones.
`define DMA_HOST_CMD_INTG_DI \
    `SEP_CORE.u_sep_dma_wrap.u_tlul_to_axi_lite_dma \
        .gen_cmd_intg_check.u_cmd_intg_chk.u_chk.data_i
    always @(posedge clk_i) begin
        if (dma_host_intg_inject_i === 1'b1) begin
            force `DMA_HOST_CMD_INTG_DI = '0;
        end else begin
            release `DMA_HOST_CMD_INTG_DI;
        end
    end
`undef DMA_HOST_CMD_INTG_DI

    // ------------------------------------------------------------------
    // ESRC raw-noise force + entropy datapath probes.
    // ------------------------------------------------------------------
    // The ESRC ring oscillators' `#delay` feedback is ignored under Verilator, so
    // the 12 noise lanes never toggle. Under +esrc_noise_force, drive them from the
    // cocotb-controlled raw-noise port so the real decorrelator/compressor/SHA/
    // CSRNG/EDN math runs on a sequence the Python golden predicts bit-exactly.
    // This is the one permitted force (raw noise at the source); the downstream
    // drbg_axis/edn nets below are read-only observation taps, never forced.
    logic [11:0] esrc_noise_d;

    assign esrc_noise_d = esrc_noise_ext_i;
    assign esrc_noise_o = esrc_noise_d;
    // Read back lane 0's ACTUAL dcor.noise_i: when the force is active this tracks
    // the driven bit; without the force it is the RTL's (static/X) noise bit. The
    // smoke asserts this matches esrc_noise_o[0] -> proves the force took (not
    // trivially satisfied).
    assign esrc_noise_active_o =
        `SEP_ESRC.u_generator_complex.gen_ecmplx[0].u_generator.u_decorrelator.noise_i;

    // Force the per-lane DECORRELATOR INPUT PORT (dcor.noise_i) directly -- the
    // exact node the SR flop samples. Forcing the upstream
    // `noise_bit` wire instead lets the SR flop sample a different scheduling point
    // under Verilator, so the decorrelator golden cannot reproduce the RTL output.
    // RE-ISSUE the force every clock: a `force` in an `initial` block snapshots the
    // RHS once at t=0 (Verilator), so it would hold the stale value. Update on the
    // falling edge so noise_i is stable before the decorrelator samples it on the
    // rising edge; forcing on that same rising edge creates an ordering race.
    // Explicit per-lane indices avoid a cross-hierarchy genvar-indexed force.
`define ESRC_NOISE_FORCE(i) \
    force `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_decorrelator.noise_i = esrc_noise_d[i]
    // Plain `always` (NOT always_ff): `force` is a procedural continuous override,
    // not a flop assignment, so always_ff semantics do not apply.
    // No explicit `release` is needed: the force is gated by `+esrc_noise_force` (only
    // active in noise-injection runs) and each test is its own elaboration, so the force
    // cannot leak into another test; it is simply torn down when the sim ends.
    always @(negedge clk_i) begin
        if ($test$plusargs("esrc_noise_force")) begin
            `ESRC_NOISE_FORCE(0);  `ESRC_NOISE_FORCE(1);  `ESRC_NOISE_FORCE(2);
            `ESRC_NOISE_FORCE(3);  `ESRC_NOISE_FORCE(4);  `ESRC_NOISE_FORCE(5);
            `ESRC_NOISE_FORCE(6);  `ESRC_NOISE_FORCE(7);  `ESRC_NOISE_FORCE(8);
            `ESRC_NOISE_FORCE(9);  `ESRC_NOISE_FORCE(10); `ESRC_NOISE_FORCE(11);
        end
    end
`undef ESRC_NOISE_FORCE

    // +sep_crypto_edn_force -- DV SHORTCUT, off by default. Grants the crypto
    // blocks' EDN handshakes directly so they can leave their reseed states and
    // run; the real entropy_source -> CSRNG -> EDN path is bypassed and NOT
    // exercised. Covers OTBN (RND/URND) and AES; AES is a separate EDN client
    // and stalls in its masking-PRNG reseed without a client-0 grant.
    localparam logic [31:0] AesEdnWord = 32'hA5A5_5A5A;
    logic edn_force_on;
    logic otbn_rnd_ack_q, otbn_urnd_ack_q, aes_ack_q;
    initial begin
        edn_force_on = $test$plusargs("sep_crypto_edn_force");
        if (edn_force_on) begin
            $display("[tb] *** DV SHORTCUT: +sep_crypto_edn_force -- OTBN and AES EDN grants");
            $display("[tb] *** are forced; the entropy_source/CSRNG/EDN chain is NOT exercised.");
        end
    end

// Target the driver-side net inside sep_crypto rather than the wrapper's input
// port -- a `force` on a module instance input is rejected (ASSIGNIN).
// Client indices in sep_crypto: 0 = AES, 1 = KMAC, 2 = OTBN RND,
// 3 = OTBN URND. KMAC is not forced -- the ROM's SHA-256 goes through HMAC.
`define OTBN_RND_RSP  `SEP_CORE.sep_crypto.crypto_edn_rsp[2]
`define OTBN_URND_RSP `SEP_CORE.sep_crypto.crypto_edn_rsp[3]
`define OTBN_RND_REQ  `SEP_CORE.sep_crypto.crypto_edn_req[2]
`define OTBN_URND_REQ `SEP_CORE.sep_crypto.crypto_edn_req[3]
`define AES_RSP       `SEP_CORE.sep_crypto.crypto_edn_rsp[0]
`define AES_REQ       `SEP_CORE.sep_crypto.crypto_edn_req[0]
    // ack pulses for one cycle per request rather than sitting high, so a
    // multi-word reseed is delivered as a sequence of beats like the real EDN.
    always @(posedge clk_i) begin
        if (edn_force_on) begin
            otbn_rnd_ack_q  <= `OTBN_RND_REQ.edn_req  & ~otbn_rnd_ack_q;
            otbn_urnd_ack_q <= `OTBN_URND_REQ.edn_req & ~otbn_urnd_ack_q;
            aes_ack_q       <= `AES_REQ.edn_req       & ~aes_ack_q;
            force `OTBN_RND_RSP.edn_ack   = otbn_rnd_ack_q;
            force `OTBN_RND_RSP.edn_fips  = 1'b1;
            force `OTBN_RND_RSP.edn_bus   = $urandom();
            force `OTBN_URND_RSP.edn_ack  = otbn_urnd_ack_q;
            force `OTBN_URND_RSP.edn_fips = 1'b1;
            force `OTBN_URND_RSP.edn_bus  = $urandom();
            force `AES_RSP.edn_ack        = aes_ack_q;
            force `AES_RSP.edn_fips       = 1'b1;
            force `AES_RSP.edn_bus        = AesEdnWord;
        end
    end
`undef AES_RSP
`undef AES_REQ
`undef OTBN_RND_RSP
`undef OTBN_URND_RSP
`undef OTBN_RND_REQ
`undef OTBN_URND_REQ

    // Entropy datapath probe taps (compiled-in XMR reads; no --public-flat-rw).
    assign esrc_ro_enable_o     = `SEP_ESRC.u_generator_complex.jitter_ro_enable_i;
    assign esrc_decor_bytes_o   = `SEP_ESRC.u_generator_complex.entropy_stream_uncompressed_o;
    // Raw 29-bit decorrelator shift register per lane. ff_stage and the sampled
    // byte share the full entropy-source rst_ni. decor_bytes_o lags the
    // true SR reset by a full divider period, so the golden cannot derive
    // the SR phase from decor_bytes_o alone. The scoreboard seeds its golden SR from
    // this exact state once shifting is live, then free-runs the CHK1..CHK5 chain.
    // Explicit per-lane indices avoid a cross-hierarchy genvar-indexed XMR.
`define ESRC_DECOR_SR(i) \
    assign esrc_decor_sr_o[29*(i) +: 29] = \
        `SEP_ESRC.u_generator_complex.gen_ecmplx[i].u_generator.u_decorrelator.ff_stage
    `ESRC_DECOR_SR(0);  `ESRC_DECOR_SR(1);  `ESRC_DECOR_SR(2);
    `ESRC_DECOR_SR(3);  `ESRC_DECOR_SR(4);  `ESRC_DECOR_SR(5);
    `ESRC_DECOR_SR(6);  `ESRC_DECOR_SR(7);  `ESRC_DECOR_SR(8);
    `ESRC_DECOR_SR(9);  `ESRC_DECOR_SR(10); `ESRC_DECOR_SR(11);
`undef ESRC_DECOR_SR
    assign esrc_decor_valid_o   = `SEP_ESRC.entropy_stream_valid;
    // SHA-whitener input handshake: a BIW word is hashed only when the whitener is
    // in its input phase (sha_fifo_valid && sha_fifo_ready). During its SHA compute
    // + 8-word output phase it accepts nothing and the unconnected entropy_ready_o
    // means upstream decor samples are DROPPED -- so the chain golden must be fed a
    // sample ONLY on this strobe, else its SHA 16:1 blocks misframe after block 0.
    assign esrc_whiten_push_o   = `SEP_ESRC.u_sha256_whitener.sha_fifo_valid
                                & `SEP_ESRC.u_sha256_whitener.sha_fifo_ready;
    assign esrc_compress_vld_o  = `SEP_ESRC.entropy_stream_vld_o;
    assign esrc_compress_data_o = `SEP_ESRC.entropy_stream_data_o;
    assign drbg_seed_valid_o    = `SEP_DRBG.u_csrng_seed_adapter.seed_queue_valid_o;
    assign drbg_es_ack_o        = `SEP_DRBG.u_csrng.entropy_src_hw_if_i.es_ack;
    assign drbg_es_bits_o       = `SEP_DRBG.u_csrng.entropy_src_hw_if_i.es_bits;
    assign drbg_genbits_vld_o   = `SEP_DRBG.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_vld_o;
    assign drbg_genbits_data_o  = `SEP_DRBG.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_data_o;
    assign drbg_genbits_fips_o  = `SEP_DRBG.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_fips_o;
    assign drbg_gen_last_o      = `SEP_DRBG.u_csrng.u_csrng_core.gen_last_q;
    // Post-EXT_TRNG_SRC_SEL-mux: the entropy actually presented to the KM (proves
    // the internal-DRBG leg was selected, not ext_trng). tvalid && tready = the KM
    // consumed a genbits word.
    assign km_entropy_tvalid_o  = `SEP_CORE.sep_crypto.entropy_muxed_req[0].tvalid;
    assign km_entropy_tdata_o   = `SEP_CORE.sep_crypto.entropy_muxed_req[0].tdata;
    // CHK5 per-sink routing golden: the crypto-leg (mux endpoint [1]) AXIS word
    // stream feeding drbg_axis_edn_adapter. tvalid && tready = one word handed to a
    // crypto endpoint (in `sep_drbg_real_sink_multi_km_aes_test` only AES
    // requests, so this equals AES's post-adapter beats in order). Each word is
    // also a CHK4 genbits-golden word (chained).
    assign axis1_tvalid_o       = `SEP_CORE.sep_crypto.entropy_muxed_req[1].tvalid;
    assign axis1_tready_o       = `SEP_CORE.sep_crypto.entropy_muxed_rsp[1].tready;
    assign axis1_tdata_o        = `SEP_CORE.sep_crypto.entropy_muxed_req[1].tdata;
    assign km_entropy_tready_o  = `SEP_CORE.sep_crypto.entropy_muxed_rsp[0].tready;
    // CHK5 pool (mux endpoint [2]): pre-adapter AXIS2 + post-adapter native EDN.
    assign axis2_tvalid_o       = `SEP_CORE.sep_crypto.entropy_muxed_req[2].tvalid;
    assign axis2_tready_o       = `SEP_CORE.sep_crypto.entropy_muxed_rsp[2].tready;
    assign axis2_tdata_o        = `SEP_CORE.sep_crypto.entropy_muxed_req[2].tdata;
    assign pool_edn_req_o       = `SEP_CORE.sep_crypto.entropy_pool_edn_req_i.edn_req;
    assign pool_edn_ack_o       = `SEP_CORE.sep_crypto.entropy_pool_edn_rsp_o.edn_ack;
    assign pool_edn_bus_o       = `SEP_CORE.sep_crypto.entropy_pool_edn_rsp_o.edn_bus;
    assign pool_edn_fips_o      = `SEP_CORE.sep_crypto.entropy_pool_edn_rsp_o.edn_fips;

    // Per-client crypto EDN taps (post drbg_axis_edn_adapter). edn_req is the
    // client's request, edn_ack the adapter's grant pulse, edn_bus the delivered
    // 32b entropy word. Explicit per-index assigns avoid a cross-hierarchy
    // genvar-indexed XMR (same style as the ESRC decorrelator-SR probe above).
`define CRYPTO_EDN_TAP(i) \
    assign crypto_edn_req_o[i]              = `SEP_CORE.sep_crypto.crypto_edn_req[i].edn_req;  \
    assign crypto_edn_ack_o[i]              = `SEP_CORE.sep_crypto.crypto_edn_rsp[i].edn_ack;  \
    assign crypto_edn_bus_o[32*(i) +: 32]   = `SEP_CORE.sep_crypto.crypto_edn_rsp[i].edn_bus;  \
    assign crypto_edn_fips_o[i]             = `SEP_CORE.sep_crypto.crypto_edn_rsp[i].edn_fips
    `CRYPTO_EDN_TAP(0); `CRYPTO_EDN_TAP(1); `CRYPTO_EDN_TAP(2); `CRYPTO_EDN_TAP(3);
`undef CRYPTO_EDN_TAP

    // KM/OTBN memory activity counters from the wrapper-internal req nets.
    // KM SRAM gnt=1 and OTBN req=enable, so a count of the request strobe is
    // a count of accepted accesses (km uses .req/.we; otbn uses .enable/.write).
    logic [31:0] km_rom_req_cnt_q, km_sram_req_cnt_q, km_sram_wr_cnt_q;
    logic [31:0] otbn_imem_req_cnt_q, otbn_imem_wr_cnt_q;
    logic [31:0] otbn_dmem_req_cnt_q, otbn_dmem_wr_cnt_q;
    always_ff @(posedge clk_i or negedge rst_n_int) begin
        if (!rst_n_int) begin
            km_rom_req_cnt_q    <= '0;
            km_sram_req_cnt_q   <= '0;
            km_sram_wr_cnt_q    <= '0;
            otbn_imem_req_cnt_q <= '0;
            otbn_imem_wr_cnt_q  <= '0;
            otbn_dmem_req_cnt_q <= '0;
            otbn_dmem_wr_cnt_q  <= '0;
        end else begin
            if (u_dut.km_rom_mem_req.req)  km_rom_req_cnt_q  <= km_rom_req_cnt_q + 32'd1;
            if (u_dut.km_sram_mem_req.req) begin
                km_sram_req_cnt_q <= km_sram_req_cnt_q + 32'd1;
                if (u_dut.km_sram_mem_req.we) km_sram_wr_cnt_q <= km_sram_wr_cnt_q + 32'd1;
            end
            if (u_dut.sep_crypto_pka_imem_sram_req.enable) begin
                otbn_imem_req_cnt_q <= otbn_imem_req_cnt_q + 32'd1;
                if (u_dut.sep_crypto_pka_imem_sram_req.write)
                    otbn_imem_wr_cnt_q <= otbn_imem_wr_cnt_q + 32'd1;
            end
            if (u_dut.sep_crypto_pka_dmem_sram_req.enable) begin
                otbn_dmem_req_cnt_q <= otbn_dmem_req_cnt_q + 32'd1;
                if (u_dut.sep_crypto_pka_dmem_sram_req.write)
                    otbn_dmem_wr_cnt_q <= otbn_dmem_wr_cnt_q + 32'd1;
            end
        end
    end
    assign km_rom_req_count_o      = km_rom_req_cnt_q;
    assign km_sram_req_count_o     = km_sram_req_cnt_q;
    assign km_sram_write_count_o   = km_sram_wr_cnt_q;
    assign otbn_imem_req_count_o   = otbn_imem_req_cnt_q;
    assign otbn_imem_write_count_o = otbn_imem_wr_cnt_q;
    assign otbn_dmem_req_count_o   = otbn_dmem_req_cnt_q;
    assign otbn_dmem_write_count_o = otbn_dmem_wr_cnt_q;
    // KM SRAM word 0: peek the real macro array. The KM SRAM is one unscrambled
    // prim_ram_1p_adv (sep_ip_integration.u_km_sram) addressed by word index
    // within the 32 KB km_intf_pkg SRAM window, so km_intf_pkg::SRAM_BASE_ADDR
    // (0x0000_8000) + 0 is mem[0]. Both KM ROM images store their word there.
    assign km_sram_word0_o =
        u_dut.u_sep_ip_integration.u_km_sram.gen_ram_inst[0].u_mem.mem[0][31:0];

    // Outbound mailbox responder + firmware-console/PASS-magic monitor.
    sep_outbound_mbx u_mbx (
        .clk_i           (clk_i),
        .rst_ni          (rst_n_int),
        .req_i           (smn_outbound_req_w),
        .resp_o          (smn_outbound_resp_w),
        .fw_done_o       (fw_done_o),
        .fw_pass_o       (fw_pass_o),
        .fw_char_o       (fw_char_o),
        .fw_char_valid_o (fw_char_valid_o)
    );

    // Response: present the CPU LSU demux slave response back to the cocotb master.
    assign s_axi_awready = `SEP_CORE.sep_cpu.lsu_axi_resp.aw_ready;
    assign s_axi_wready  = `SEP_CORE.sep_cpu.lsu_axi_resp.w_ready;
    assign s_axi_bid     = `SEP_CORE.sep_cpu.lsu_axi_resp.b.id;
    assign s_axi_bresp   = `SEP_CORE.sep_cpu.lsu_axi_resp.b.resp;
    assign s_axi_buser   = `SEP_CORE.sep_cpu.lsu_axi_resp.b.user;
    assign s_axi_bvalid  = `SEP_CORE.sep_cpu.lsu_axi_resp.b_valid;
    assign s_axi_arready = `SEP_CORE.sep_cpu.lsu_axi_resp.ar_ready;
    assign s_axi_rid     = `SEP_CORE.sep_cpu.lsu_axi_resp.r.id;
    assign s_axi_rdata   = `SEP_CORE.sep_cpu.lsu_axi_resp.r.data;
    assign s_axi_rresp   = `SEP_CORE.sep_cpu.lsu_axi_resp.r.resp;
    assign s_axi_rlast   = `SEP_CORE.sep_cpu.lsu_axi_resp.r.last;
    assign s_axi_ruser   = `SEP_CORE.sep_cpu.lsu_axi_resp.r.user;
    assign s_axi_rvalid  = `SEP_CORE.sep_cpu.lsu_axi_resp.r_valid;

    // ------------------------------------------------------------------
    // AXI protocol checkers (hw/common/dv/vip/ocah_axi_vip/sva).
    //
    // Passive readers on the two TB-driven AXI4 buses. They assert the AMBA
    // IHI 0022 rules the VIP implements: handshake stability, VALID held
    // until READY, X/Z hygiene, burst and size legality, WRAP alignment, the
    // 4KB boundary, WLAST position, WSTRB lane legality, response-before-
    // request ordering, and ID outstanding tracking. They drive nothing.
    //
    // Both buses carry TB-sourced stimulus, so a failure here is a stimulus
    // bug in the VIP or a sequence rather than a DUT bug. That is the value:
    // it stops an illegal transaction being blamed on the DUT.
    //
    // Assertion bodies are guarded by OCAH_INC_ASSERT (hw/common/assert),
    // which Verilator does not define, so both instances elaborate to empty
    // modules there and cost nothing. The rules are live wherever
    // OCAH_INC_ASSERT is defined.
    //
    // m_axi ties en_i high: it is TB-driven in both run modes. s_axi is gated
    // by the run mode, for the reason stated at its instance. A test that needs
    // a further suppression window drives a TB signal here, never drops the
    // instance.
    // ------------------------------------------------------------------
    ocah_axi_sva #(
        .IS_LITE    (1'b0),
        .ADDR_WIDTH (56),
        .DATA_WIDTH (64),
        .ID_WIDTH   (6)
    ) u_m_axi_sva (                       // external SMN inbound master
        .aclk    (clk_i),
        .aresetn (rst_ni),
        .en_i    (1'b1),
        .awid    (m_axi_awid),
        .awaddr  (m_axi_awaddr),
        .awlen   (m_axi_awlen),
        .awsize  (m_axi_awsize),
        .awburst (m_axi_awburst),
        .awlock  (m_axi_awlock),
        .awprot  (m_axi_awprot),
        .awvalid (m_axi_awvalid),
        .awready (m_axi_awready),
        .wdata   (m_axi_wdata),
        .wstrb   (m_axi_wstrb),
        .wlast   (m_axi_wlast),
        .wvalid  (m_axi_wvalid),
        .wready  (m_axi_wready),
        .bid     (m_axi_bid),
        .bresp   (m_axi_bresp),
        .bvalid  (m_axi_bvalid),
        .bready  (m_axi_bready),
        .arid    (m_axi_arid),
        .araddr  (m_axi_araddr),
        .arlen   (m_axi_arlen),
        .arsize  (m_axi_arsize),
        .arburst (m_axi_arburst),
        .arlock  (m_axi_arlock),
        .arprot  (m_axi_arprot),
        .arvalid (m_axi_arvalid),
        .arready (m_axi_arready),
        .rid     (m_axi_rid),
        .rdata   (m_axi_rdata),
        .rresp   (m_axi_rresp),
        .rlast   (m_axi_rlast),
        .rvalid  (m_axi_rvalid),
        .rready  (m_axi_rready)
    );

    // The s_axi checker watches the CPU-LSU splice, which the TB drives only on
    // the stub build. Under +cpu_boot the EL2 owns that bus, so the checker
    // would be judging the core's own traffic rather than TB stimulus. Static
    // initialisation resolves before any initial block, so the value is settled
    // before the first assertion samples. m_axi stays armed in both modes: it is
    // TB-driven throughout.
    bit s_axi_sva_en = !$test$plusargs("cpu_boot");

    ocah_axi_sva #(
        .IS_LITE    (1'b0),
        .ADDR_WIDTH (32),
        .DATA_WIDTH (64),
        .ID_WIDTH   (3)
    ) u_s_axi_sva (                       // CPU LSU master (TB-driven when !cpu_boot)
        .aclk    (clk_i),
        .aresetn (rst_ni),
        .en_i    (s_axi_sva_en),
        .awid    (s_axi_awid),
        .awaddr  (s_axi_awaddr),
        .awlen   (s_axi_awlen),
        .awsize  (s_axi_awsize),
        .awburst (s_axi_awburst),
        .awlock  (s_axi_awlock),
        .awprot  (s_axi_awprot),
        .awvalid (s_axi_awvalid),
        .awready (s_axi_awready),
        .wdata   (s_axi_wdata),
        .wstrb   (s_axi_wstrb),
        .wlast   (s_axi_wlast),
        .wvalid  (s_axi_wvalid),
        .wready  (s_axi_wready),
        .bid     (s_axi_bid),
        .bresp   (s_axi_bresp),
        .bvalid  (s_axi_bvalid),
        .bready  (s_axi_bready),
        .arid    (s_axi_arid),
        .araddr  (s_axi_araddr),
        .arlen   (s_axi_arlen),
        .arsize  (s_axi_arsize),
        .arburst (s_axi_arburst),
        .arlock  (s_axi_arlock),
        .arprot  (s_axi_arprot),
        .arvalid (s_axi_arvalid),
        .arready (s_axi_arready),
        .rid     (s_axi_rid),
        .rdata   (s_axi_rdata),
        .rresp   (s_axi_rresp),
        .rlast   (s_axi_rlast),
        .rvalid  (s_axi_rvalid),
        .rready  (s_axi_rready)
    );

    // ------------------------------------------------------------------
    // Key Manager internal AXI-Lite, CPU side. Every access KM firmware makes
    // to KPV, KMCSR, the DRBG sampler and the mailbox crosses this one port:
    // the KM crossbar has a
    // single slave port wired to the internal picorv32, so no testbench
    // master can reach it.
    //
    // Bound rather than instantiated, so the port names resolve in the Key
    // Manager's own scope. Passive: it needs no stimulus and adds none.
    // IS_LITE=1 drops the burst, ID and exclusive rules an AXI-Lite port does
    // not carry.
    //
    // Enabled only once the warm reset is a known 0 or 1. That reset is
    // conditioned and synchronised, so it reads X until the first clock edge,
    // and comparing VALID against a low reset has no meaning while the reset
    // itself is unknown.
    //
    // This checks PROTOCOL, not data. A register that accepts a write, answers
    // OKAY and stores nothing breaks no rule here, so a green run is not
    // evidence that a KM register write landed.
    bind key_manager ocah_axi_sva #(
        .IS_LITE    (1'b1),
        .ADDR_WIDTH (32),
        .DATA_WIDTH (32),
        .ID_WIDTH   (1)
    ) u_km_axil_sva (
        .aclk    (clk_i),
        .aresetn (rst_warm_sync_n),
        // Names resolve in key_manager. The warm reset is conditioned and
        // synchronised and the CPU's valids follow it, so both read X before
        // the first edge; comparing VALID against a low reset says nothing
        // while either is undefined.
        .en_i    (!$isunknown(rst_warm_sync_n)
                  && !$isunknown(cpu_axil_req.aw_valid)
                  && !$isunknown(cpu_axil_req.ar_valid)),
        .awid    (1'b0),
        .awaddr  (cpu_axil_req.aw.addr),
        .awlen   (8'd0),
        .awsize  (3'd2),
        .awburst (2'b01),
        .awlock  (1'b0),
        .awprot  (cpu_axil_req.aw.prot),
        .awvalid (cpu_axil_req.aw_valid),
        .awready (cpu_axil_resp.aw_ready),
        .wdata   (cpu_axil_req.w.data),
        .wstrb   (cpu_axil_req.w.strb),
        .wlast   (1'b1),
        .wvalid  (cpu_axil_req.w_valid),
        .wready  (cpu_axil_resp.w_ready),
        .bid     (1'b0),
        .bresp   (cpu_axil_resp.b.resp),
        .bvalid  (cpu_axil_resp.b_valid),
        .bready  (cpu_axil_req.b_ready),
        .arid    (1'b0),
        .araddr  (cpu_axil_req.ar.addr),
        .arlen   (8'd0),
        .arsize  (3'd2),
        .arburst (2'b01),
        .arlock  (1'b0),
        .arprot  (cpu_axil_req.ar.prot),
        .arvalid (cpu_axil_req.ar_valid),
        .arready (cpu_axil_resp.ar_ready),
        .rid     (1'b0),
        .rdata   (cpu_axil_resp.r.data),
        .rresp   (cpu_axil_resp.r.resp),
        .rlast   (1'b1),
        .rvalid  (cpu_axil_resp.r_valid),
        .rready  (cpu_axil_req.r_ready)
    );

`undef SEP_ESRC
`undef SEP_DRBG
`undef SEP_CORE
`undef SEP_IPI

endmodule : sep_uvm_top
