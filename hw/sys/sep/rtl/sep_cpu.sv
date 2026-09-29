// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the VeeR EL2 core complex behind a mostly core-agnostic SEP CPU boundary.
//
// Contains the RV32 core, PIC, and debug module with the ICCM and DCCM controllers; the TCM
// RAM macros sit outside, in sep_tcm_wrapper. The core boots from the boot ROM base and
// core_id is 0. The external
// interface is mostly not EL2-specific so another core can replace EL2 with limited churn
// above.
//
// VeeR reset bypass (scan_rst_n) is not exposed on the el2_veer_wrapper boundary. Lockstep
// ctrl/status ports stay present even when RV_LOCKSTEP_ENABLE is off so the hierarchy
// above keeps one footprint.
//
// The LSU, IFU and debug masters first pass through a window remap that rewrites addresses in
// [sep_local_base_addr_i, sep_local_base_addr_i + 0x3000_0000) to 0x1000_0000 plus the
// offset. An IFU demux then sends boot ROM addresses to the ROM port, SEP SRAM addresses to
// the SRAM port, and everything else to a DECERR slave; an LSU demux sends boot ROM addresses
// to the ROM port and everything else to the xbar port. Master AxUSER carries SEP_SOURCE_ID
// and AtoP is 0. The TCM structs connect to sep_tcm_wrapper, instantiated in
// sep_ip_integration.
//
// nmi_vec_i and jtag_id_i should be tied to constants or sourced from a CSR.

module sep_cpu (
  input logic clk_i,                          // System clock.
  input logic rst_ni,                         // Active-low reset.
  input logic dbg_rstb_i,                     // EL2 debug-module reset, active-low; also resets the
                                              // mpc_reset_run_req_i synchronizer.

  input  logic jtag_tck_i,                    // JTAG test clock of the core debug TAP.
  input  logic jtag_tms_i,                    // JTAG test mode select, sampled on jtag_tck_i.
  input  logic jtag_tdi_i,                    // JTAG test data input, sampled on jtag_tck_i.
  input  logic jtag_trst_ni,                  // JTAG TAP reset, active-low.
  output logic jtag_tdo_o,                    // JTAG test data output; valid while jtag_tdoEn_o is
                                              // high.
  output logic jtag_tdoEn_o,                  // JTAG Test Data Output enable.

  input  logic mpc_debug_halt_req_i,          // Asynchronous multi-processor-controller debug halt
                                              // request.
  input  logic mpc_debug_run_req_i,           // Asynchronous multi-processor-controller debug run
                                              // request.
  input  logic mpc_reset_run_req_i,           // 1 to run and 0 to halt in debug mode after reset;
                                              // synchronized to clk_i here.
  output logic mpc_debug_halt_ack_o,          // Acknowledge of mpc_debug_halt_req_i.
  output logic mpc_debug_run_ack_o,           // Acknowledge of mpc_debug_run_req_i.
  output logic debug_brkpt_status_o,          // Debug breakpoint status from the core.

  input  logic cpu_halt_req_i,                // Async halt req to CPU.
  output logic cpu_halt_ack_o,                // Core acknowledge of cpu_halt_req_i.
  output logic cpu_halt_status_o,             // High while the core is halted.
  output logic debug_mode_status_o,           // High while the core is in debug mode; the power
                                              // manager must not send a halt or run request then.
  input  logic cpu_run_req_i,                 // Async restart req to CPU.
  output logic cpu_run_ack_o,                 // Core response to run req.

  input logic test_en_i,                      // DFT test-enable (scan-enable) to the core scan_mode
                                              // and the demux test inputs.

  input  logic        dmi_core_enable_i,      // Enables DMI accesses to the core debug module
                                              // registers.
  input  logic        dmi_uncore_enable_i,    // Enables DMI accesses to the uncore aperture of the
                                              // DMI address space.
  output logic        dmi_uncore_en_o,        // DMI access strobe to the uncore aperture, gated by
                                              // dmi_uncore_enable_i.
  output logic        dmi_uncore_wr_en_o,     // Write qualifier for the uncore DMI access; low for
                                              // reads.
  output logic [6:0]  dmi_uncore_addr_o,      // DMI register address of the uncore access.
  output logic [31:0] dmi_uncore_wdata_o,     // Write data of the uncore DMI access.
  input  logic [31:0] dmi_uncore_rdata_i,     // Read data returned by the uncore for the addressed
                                              // DMI register.
  output logic        dmi_active_o,           // High while the debug transport drives a DMI access
                                              // to the core or uncore.

  input logic [31:1] nmi_vec_i,               // PC bits [31:1] the core jumps to on an NMI.
  input logic [31:1] jtag_id_i,               // JTAG IDCODE bits [31:1] reported by the core debug
                                              // TAP; bit 0 is fixed at 1.

  input logic                       nmi_int_i,  // Non-maskable interrupt to the core; hold for at
                                                // least two clk_i cycles.
  input logic                       timer_int_i,  // Machine timer interrupt to the core.
  input logic                       soft_int_i,  // Machine software interrupt to the core.
  input logic [sep_pkg::SEP_CPU_IRQ_WIDTH-1:0] extintsrc_req_i,  // External interrupt requests to
                                                                 // the core PIC; bit i is PIC
                                                                 // source i+1.

  output sep_pkg::sep_cpu_trace_t sep_cpu_trace_o,  // Core instruction trace: retired instruction,
                                                    // address, valid, exception, cause, interrupt,
                                                    // and tval.

  output logic iccm_ecc_single_error_o,       // ICCM single-bit (corrected) ECC error indication
                                              // from the core.
  output logic iccm_ecc_double_error_o,       // ICCM double-bit (uncorrectable) ECC error
                                              // indication from the core.
  output logic dccm_ecc_single_error_o,       // DCCM single-bit (corrected) ECC error indication
                                              // from the core.
  output logic dccm_ecc_double_error_o,       // DCCM double-bit (uncorrectable) ECC error
                                              // indication from the core.

  output logic dec_tlu_perfcnt0_o,            // Toggles when slot0 perf counter 0 has an event
                                              // increment.
  output logic dec_tlu_perfcnt1_o,            // Toggles when slot0 perf counter 1 has an event
                                              // increment.
  output logic dec_tlu_perfcnt2_o,            // Toggles when slot0 perf counter 2 has an event
                                              // increment.
  output logic dec_tlu_perfcnt3_o,            // Toggles when slot0 perf counter 3 has an event
                                              // increment.

  input  sep_pkg::sep_lockstep_ctrl_t   lockstep_ctrl_i,  // Lockstep corruption-detection disable
                                                          // and error-injection enable; ignored
                                                          // unless built with RV_LOCKSTEP_ENABLE.
  output sep_pkg::sep_lockstep_status_t lockstep_status_o,  // Lockstep corruption-detected status;
                                                            // held at zero unless built with
                                                            // RV_LOCKSTEP_ENABLE.

  output sep_pkg::sep_cpu_tcm_req_t sep_cpu_tcm_req_o,  // Per-bank ICCM and DCCM macro requests,
                                                        // with the macro clock, to sep_tcm_wrapper.
  input  sep_pkg::sep_cpu_tcm_rsp_t sep_cpu_tcm_rsp_i,  // Per-bank ICCM and DCCM read data and ECC
                                                        // from sep_tcm_wrapper.

  output sep_pkg::sep_32_64_3_12_axi_req_t      ifu_rom_axi_req_o,  // IFU fetch request for boot ROM addresses.
  input  sep_pkg::sep_32_64_3_12_axi_resp_t     ifu_rom_axi_resp_i,  // IFU fetch response from the boot ROM.
  output sep_pkg::sep_32_64_3_12_axi_req_t      ifu_sram_axi_req_o,  // IFU fetch request for SEP SRAM addresses.
  input  sep_pkg::sep_32_64_3_12_axi_resp_t     ifu_sram_axi_resp_i,  // IFU fetch response from the SEP SRAM.
  output sep_pkg::sep_32_64_3_12_axi_req_t      lsu_rom_axi_req_o,  // LSU request for boot ROM addresses.
  input  sep_pkg::sep_32_64_3_12_axi_resp_t     lsu_rom_axi_resp_i,  // LSU response from the boot ROM.
  output sep_pkg::sep_32_64_3_12_axi_req_t      lsu_xbar_axi_req_o,  // LSU request for every address outside the boot ROM, to the SEP local xbar.
  input  sep_pkg::sep_32_64_3_12_axi_resp_t     lsu_xbar_axi_resp_i,  // LSU response from the SEP local xbar.
  output sep_pkg::sep_32_64_3_12_axi_req_t      dbg_axi_req_o,  // Debug-module system-bus request,
                                                                // after the local alias remap.
  input  sep_pkg::sep_32_64_3_12_axi_resp_t     dbg_axi_resp_i,  // Debug-module system-bus
                                                                 // response.
  input  sep_pkg::sep_32_64_6_12_axi_req_t      cpu_tcm_axi_req_i,  // Request into the core DMA slave port for ICCM and DCCM access.
  output sep_pkg::sep_32_64_6_12_axi_resp_t     cpu_tcm_axi_resp_o,  // Response from the core DMA slave port; B and R USER carry SEP_SOURCE_ID.
  input  logic [31:0]                 sep_local_base_addr_i  // Base of the SEP local alias window;
                                                             // LSU, IFU, and debug addresses inside
                                                             // it are remapped to 0x1000_0000 plus
                                                             // the offset.
);

  import el2_pkg::el2_param_t;

  // el2_param.vh (generated) declares `parameter el2_param_t pt` with no terminator
  `include "el2_param.vh"
  ;

  // IFU intermediate signals (after local alias adjustment, before demux)
  sep_pkg::sep_32_64_3_12_axi_req_t  ifu_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t ifu_axi_resp;

  // Intermediate signals before local alias adjustment (raw from EL2)
  sep_pkg::sep_32_64_3_12_axi_req_t  lsu_axi_req_raw;
  sep_pkg::sep_32_64_3_12_axi_resp_t lsu_axi_resp_raw;
  sep_pkg::sep_32_64_3_12_axi_req_t  ifu_axi_req_raw;
  sep_pkg::sep_32_64_3_12_axi_resp_t ifu_axi_resp_raw;
  sep_pkg::sep_32_64_3_12_axi_req_t  dbg_axi_req_raw;
  sep_pkg::sep_32_64_3_12_axi_resp_t dbg_axi_resp_raw;

  // LSU intermediate signals (after local alias adjustment)
  sep_pkg::sep_32_64_3_12_axi_req_t  lsu_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t lsu_axi_resp;

  // SB/DBG AXI ID width conversion signals (pt.SB_BUS_TAG <-> SEP_32_64_3_12_ID_WIDTH)
  logic [pt.SB_BUS_TAG-1:0] sb_axi_awid_raw;
  logic [pt.SB_BUS_TAG-1:0] sb_axi_arid_raw;
  logic [pt.SB_BUS_TAG-1:0] sb_axi_bid_raw;
  logic [pt.SB_BUS_TAG-1:0] sb_axi_rid_raw;

  ////////////////////////////
  // CPU Core Instantiation //
  ////////////////////////////

  el2_mem_if el2_mem_if ();

  // Core has no internal synchronizer for mpc_reset_run_req_i; sync it here.
  // dbg_rstb_i deasserts well before rst_ni, so the value is stable when sampled.
  logic mpc_reset_run_req_sync;

  prim_flop_2sync #(
    .Width(1)
  ) u_mpc_reset_run_req_sync (
    .clk_i  (clk_i),
    .d_i    (mpc_reset_run_req_i),
    .rst_ni (dbg_rstb_i),
    .q_o    (mpc_reset_run_req_sync)
  );

  el2_veer_wrapper #(
    .RESET_VEC(sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR)
  ) u_el2_veer_wrapper (
    .clk       (clk_i),
    .rst_l     (rst_ni),
    .dbg_rst_l (dbg_rstb_i),

    .jtag_tck    (jtag_tck_i),   // JTAG clk
    .jtag_tms    (jtag_tms_i),   // JTAG TMS
    .jtag_tdi    (jtag_tdi_i),   // JTAG tdi
    .jtag_trst_n (jtag_trst_ni), // JTAG Reset
    .jtag_tdo    (jtag_tdo_o),   // JTAG TDO
    .jtag_tdoEn  (jtag_tdoEn_o), // JTAG Test Data Output enable

    // external MPC halt/run interface
    .mpc_debug_halt_req (mpc_debug_halt_req_i),   // Async halt request
    .mpc_debug_run_req  (mpc_debug_run_req_i),    // Async run request
    .mpc_reset_run_req  (mpc_reset_run_req_sync), // Run/halt after reset
    .mpc_debug_halt_ack (mpc_debug_halt_ack_o),   // Halt ack
    .mpc_debug_run_ack  (mpc_debug_run_ack_o),    // Run ack
    .debug_brkpt_status (debug_brkpt_status_o),   // debug breakpoint

    .i_cpu_halt_req      (cpu_halt_req_i),      // Async halt req to CPU
    .o_cpu_halt_ack      (cpu_halt_ack_o),      // core response to halt
    .o_cpu_halt_status   (cpu_halt_status_o),   // 1'b1 indicates core is halted
    .o_debug_mode_status (debug_mode_status_o), // Core to the PMU that core is in debug mode. When core is in debug mode, the PMU should refrain from sendng a halt or run request
    .i_cpu_run_req       (cpu_run_req_i), // Async restart req to CPU
    .o_cpu_run_ack       (cpu_run_ack_o), // Core response to run req

    .scan_mode  (test_en_i), // DFT test-enable
    .mbist_mode (1'b0),    // This is unused in the EL2, tie down

    // DMI port for uncore
    .dmi_core_enable   (dmi_core_enable_i),
    .dmi_uncore_enable (dmi_uncore_enable_i),
    .dmi_uncore_en     (dmi_uncore_en_o),
    .dmi_uncore_wr_en  (dmi_uncore_wr_en_o),
    .dmi_uncore_addr   (dmi_uncore_addr_o),
    .dmi_uncore_wdata  (dmi_uncore_wdata_o),
    .dmi_uncore_rdata  (dmi_uncore_rdata_i),
    .dmi_active        (dmi_active_o),

    // jtag_id and nmi_vec should be tied to constant in the top level or sourced from a CSR
    .nmi_vec (nmi_vec_i),
    .jtag_id (jtag_id_i),
    .core_id ('0),      // drives register that controls mhartid, a single core el2 can safely tie this to 0

    // Non-maskable interrupt, should be asserted for at least 2 clock cycles
    //(Documentation section 3.16, https://chipsalliance.github.io/Cores-VeeR-EL2/html/main/docs_rendered/html/memory-map.html#non-maskable-interrupt-nmi-signal-and-vector)
    .nmi_int       (nmi_int_i),
    .timer_int     (timer_int_i),
    .soft_int      (soft_int_i),
    .extintsrc_req (extintsrc_req_i),

    // Trace interface
    .trace_rv_i_insn_ip      (sep_cpu_trace_o.trace_rv_i_insn_ip),
    .trace_rv_i_address_ip   (sep_cpu_trace_o.trace_rv_i_address_ip),
    .trace_rv_i_valid_ip     (sep_cpu_trace_o.trace_rv_i_valid_ip),
    .trace_rv_i_exception_ip (sep_cpu_trace_o.trace_rv_i_exception_ip),
    .trace_rv_i_ecause_ip    (sep_cpu_trace_o.trace_rv_i_ecause_ip),
    .trace_rv_i_interrupt_ip (sep_cpu_trace_o.trace_rv_i_interrupt_ip),
    .trace_rv_i_tval_ip      (sep_cpu_trace_o.trace_rv_i_tval_ip),

    .lsu_bus_clk_en (1'b1), // Clock ratio b/w cpu core clk & AHB master interface
    .ifu_bus_clk_en (1'b1), // Clock ratio b/w cpu core clk & AHB master interface
    .dbg_bus_clk_en (1'b1), // Clock ratio b/w cpu core clk & AHB master interface
    .dma_bus_clk_en (1'b1), // Clock ratio b/w cpu core clk & AHB slave interface

    .iccm_ecc_single_error (iccm_ecc_single_error_o),
    .iccm_ecc_double_error (iccm_ecc_double_error_o),
    .dccm_ecc_single_error (dccm_ecc_single_error_o),
    .dccm_ecc_double_error (dccm_ecc_double_error_o),

    .dec_tlu_perfcnt0 (dec_tlu_perfcnt0_o), // toggles when slot0 perf counter 0 has an event inc
    .dec_tlu_perfcnt1 (dec_tlu_perfcnt1_o),
    .dec_tlu_perfcnt2 (dec_tlu_perfcnt2_o),
    .dec_tlu_perfcnt3 (dec_tlu_perfcnt3_o),

`ifdef RV_LOCKSTEP_ENABLE
    .disable_corruption_detection_i (lockstep_ctrl_i.disable_corruption_detection),
    .lockstep_err_injection_en_i    (lockstep_ctrl_i.err_injection_en),
    .corruption_detected_o          (lockstep_status_o.corruption_detected),
`endif

    // Memory macro interfaces
    .el2_icache_export (el2_mem_if.veer_icache_src),
    .el2_mem_export    (el2_mem_if.veer_sram_src),

    // LSU AXI (master) - raw signals before local alias remap
    .lsu_axi_awvalid (lsu_axi_req_raw.aw_valid),
    .lsu_axi_awready (lsu_axi_resp_raw.aw_ready),
    .lsu_axi_awid    (lsu_axi_req_raw.aw.id),
    .lsu_axi_awaddr  (lsu_axi_req_raw.aw.addr),
    .lsu_axi_awregion(lsu_axi_req_raw.aw.region),
    .lsu_axi_awlen   (lsu_axi_req_raw.aw.len),
    .lsu_axi_awsize  (lsu_axi_req_raw.aw.size),
    .lsu_axi_awburst (lsu_axi_req_raw.aw.burst),
    .lsu_axi_awlock  (lsu_axi_req_raw.aw.lock),
    .lsu_axi_awcache (lsu_axi_req_raw.aw.cache),
    .lsu_axi_awprot  (lsu_axi_req_raw.aw.prot),
    .lsu_axi_awqos   (lsu_axi_req_raw.aw.qos),
    .lsu_axi_wvalid  (lsu_axi_req_raw.w_valid),
    .lsu_axi_wready  (lsu_axi_resp_raw.w_ready),
    .lsu_axi_wdata   (lsu_axi_req_raw.w.data),
    .lsu_axi_wstrb   (lsu_axi_req_raw.w.strb),
    .lsu_axi_wlast   (lsu_axi_req_raw.w.last),
    .lsu_axi_bvalid  (lsu_axi_resp_raw.b_valid),
    .lsu_axi_bready  (lsu_axi_req_raw.b_ready),
    .lsu_axi_bresp   (lsu_axi_resp_raw.b.resp),
    .lsu_axi_bid     (lsu_axi_resp_raw.b.id),
    .lsu_axi_arvalid (lsu_axi_req_raw.ar_valid),
    .lsu_axi_arready (lsu_axi_resp_raw.ar_ready),
    .lsu_axi_arid    (lsu_axi_req_raw.ar.id),
    .lsu_axi_araddr  (lsu_axi_req_raw.ar.addr),
    .lsu_axi_arregion(lsu_axi_req_raw.ar.region),
    .lsu_axi_arlen   (lsu_axi_req_raw.ar.len),
    .lsu_axi_arsize  (lsu_axi_req_raw.ar.size),
    .lsu_axi_arburst (lsu_axi_req_raw.ar.burst),
    .lsu_axi_arlock  (lsu_axi_req_raw.ar.lock),
    .lsu_axi_arcache (lsu_axi_req_raw.ar.cache),
    .lsu_axi_arprot  (lsu_axi_req_raw.ar.prot),
    .lsu_axi_arqos   (lsu_axi_req_raw.ar.qos),
    .lsu_axi_rvalid  (lsu_axi_resp_raw.r_valid),
    .lsu_axi_rready  (lsu_axi_req_raw.r_ready),
    .lsu_axi_rid     (lsu_axi_resp_raw.r.id),
    .lsu_axi_rdata   (lsu_axi_resp_raw.r.data),
    .lsu_axi_rresp   (lsu_axi_resp_raw.r.resp),
    .lsu_axi_rlast   (lsu_axi_resp_raw.r.last),

    // IFU AXI (master) - raw signals before local alias remap
    .ifu_axi_awvalid  (ifu_axi_req_raw.aw_valid),
    .ifu_axi_awready  (ifu_axi_resp_raw.aw_ready),
    .ifu_axi_awid     (ifu_axi_req_raw.aw.id),
    .ifu_axi_awaddr   (ifu_axi_req_raw.aw.addr),
    .ifu_axi_awregion (ifu_axi_req_raw.aw.region),
    .ifu_axi_awlen    (ifu_axi_req_raw.aw.len),
    .ifu_axi_awsize   (ifu_axi_req_raw.aw.size),
    .ifu_axi_awburst  (ifu_axi_req_raw.aw.burst),
    .ifu_axi_awlock   (ifu_axi_req_raw.aw.lock),
    .ifu_axi_awcache  (ifu_axi_req_raw.aw.cache),
    .ifu_axi_awprot   (ifu_axi_req_raw.aw.prot),
    .ifu_axi_awqos    (ifu_axi_req_raw.aw.qos),
    .ifu_axi_wvalid   (ifu_axi_req_raw.w_valid),
    .ifu_axi_wready   (ifu_axi_resp_raw.w_ready),
    .ifu_axi_wdata    (ifu_axi_req_raw.w.data),
    .ifu_axi_wstrb    (ifu_axi_req_raw.w.strb),
    .ifu_axi_wlast    (ifu_axi_req_raw.w.last),
    .ifu_axi_bvalid   (ifu_axi_resp_raw.b_valid),
    .ifu_axi_bready   (ifu_axi_req_raw.b_ready),
    .ifu_axi_bresp    (ifu_axi_resp_raw.b.resp),
    .ifu_axi_bid      (ifu_axi_resp_raw.b.id),
    .ifu_axi_arvalid  (ifu_axi_req_raw.ar_valid),
    .ifu_axi_arready  (ifu_axi_resp_raw.ar_ready),
    .ifu_axi_arid     (ifu_axi_req_raw.ar.id),
    .ifu_axi_araddr   (ifu_axi_req_raw.ar.addr),
    .ifu_axi_arregion (ifu_axi_req_raw.ar.region),
    .ifu_axi_arlen    (ifu_axi_req_raw.ar.len),
    .ifu_axi_arsize   (ifu_axi_req_raw.ar.size),
    .ifu_axi_arburst  (ifu_axi_req_raw.ar.burst),
    .ifu_axi_arlock   (ifu_axi_req_raw.ar.lock),
    .ifu_axi_arcache  (ifu_axi_req_raw.ar.cache),
    .ifu_axi_arprot   (ifu_axi_req_raw.ar.prot),
    .ifu_axi_arqos    (ifu_axi_req_raw.ar.qos),
    .ifu_axi_rvalid   (ifu_axi_resp_raw.r_valid),
    .ifu_axi_rready   (ifu_axi_req_raw.r_ready),
    .ifu_axi_rid      (ifu_axi_resp_raw.r.id),
    .ifu_axi_rdata    (ifu_axi_resp_raw.r.data),
    .ifu_axi_rresp    (ifu_axi_resp_raw.r.resp),
    .ifu_axi_rlast    (ifu_axi_resp_raw.r.last),

    // SB/DBG AXI (master) - raw signals before local alias remap
    .sb_axi_awvalid  (dbg_axi_req_raw.aw_valid),
    .sb_axi_awready  (dbg_axi_resp_raw.aw_ready),
    .sb_axi_awid     (sb_axi_awid_raw),
    .sb_axi_awaddr   (dbg_axi_req_raw.aw.addr),
    .sb_axi_awregion (dbg_axi_req_raw.aw.region),
    .sb_axi_awlen    (dbg_axi_req_raw.aw.len),
    .sb_axi_awsize   (dbg_axi_req_raw.aw.size),
    .sb_axi_awburst  (dbg_axi_req_raw.aw.burst),
    .sb_axi_awlock   (dbg_axi_req_raw.aw.lock),
    .sb_axi_awcache  (dbg_axi_req_raw.aw.cache),
    .sb_axi_awprot   (dbg_axi_req_raw.aw.prot),
    .sb_axi_awqos    (dbg_axi_req_raw.aw.qos),
    .sb_axi_wvalid   (dbg_axi_req_raw.w_valid),
    .sb_axi_wready   (dbg_axi_resp_raw.w_ready),
    .sb_axi_wdata    (dbg_axi_req_raw.w.data),
    .sb_axi_wstrb    (dbg_axi_req_raw.w.strb),
    .sb_axi_wlast    (dbg_axi_req_raw.w.last),
    .sb_axi_bvalid   (dbg_axi_resp_raw.b_valid),
    .sb_axi_bready   (dbg_axi_req_raw.b_ready),
    .sb_axi_bresp    (dbg_axi_resp_raw.b.resp),
    .sb_axi_bid      (sb_axi_bid_raw),
    .sb_axi_arvalid  (dbg_axi_req_raw.ar_valid),
    .sb_axi_arready  (dbg_axi_resp_raw.ar_ready),
    .sb_axi_arid     (sb_axi_arid_raw),
    .sb_axi_araddr   (dbg_axi_req_raw.ar.addr),
    .sb_axi_arregion (dbg_axi_req_raw.ar.region),
    .sb_axi_arlen    (dbg_axi_req_raw.ar.len),
    .sb_axi_arsize   (dbg_axi_req_raw.ar.size),
    .sb_axi_arburst  (dbg_axi_req_raw.ar.burst),
    .sb_axi_arlock   (dbg_axi_req_raw.ar.lock),
    .sb_axi_arcache  (dbg_axi_req_raw.ar.cache),
    .sb_axi_arprot   (dbg_axi_req_raw.ar.prot),
    .sb_axi_arqos    (dbg_axi_req_raw.ar.qos),
    .sb_axi_rvalid   (dbg_axi_resp_raw.r_valid),
    .sb_axi_rready   (dbg_axi_req_raw.r_ready),
    .sb_axi_rid      (sb_axi_rid_raw),
    .sb_axi_rdata    (dbg_axi_resp_raw.r.data),
    .sb_axi_rresp    (dbg_axi_resp_raw.r.resp),
    .sb_axi_rlast    (dbg_axi_resp_raw.r.last),

    // DMA/TCM AXI (slave)
    .dma_axi_awvalid (cpu_tcm_axi_req_i.aw_valid),
    .dma_axi_awready (cpu_tcm_axi_resp_o.aw_ready),
    .dma_axi_awid    (cpu_tcm_axi_req_i.aw.id),
    .dma_axi_awaddr  (cpu_tcm_axi_req_i.aw.addr),
    .dma_axi_awsize  (cpu_tcm_axi_req_i.aw.size),
    .dma_axi_awprot  (cpu_tcm_axi_req_i.aw.prot),
    .dma_axi_awlen   (cpu_tcm_axi_req_i.aw.len),
    .dma_axi_awburst (cpu_tcm_axi_req_i.aw.burst),
    .dma_axi_wvalid  (cpu_tcm_axi_req_i.w_valid),
    .dma_axi_wready  (cpu_tcm_axi_resp_o.w_ready),
    .dma_axi_wdata   (cpu_tcm_axi_req_i.w.data),
    .dma_axi_wstrb   (cpu_tcm_axi_req_i.w.strb),
    .dma_axi_wlast   (cpu_tcm_axi_req_i.w.last),
    .dma_axi_bvalid  (cpu_tcm_axi_resp_o.b_valid),
    .dma_axi_bready  (cpu_tcm_axi_req_i.b_ready),
    .dma_axi_bresp   (cpu_tcm_axi_resp_o.b.resp),
    .dma_axi_bid     (cpu_tcm_axi_resp_o.b.id),
    .dma_axi_arvalid (cpu_tcm_axi_req_i.ar_valid),
    .dma_axi_arready (cpu_tcm_axi_resp_o.ar_ready),
    .dma_axi_arid    (cpu_tcm_axi_req_i.ar.id),
    .dma_axi_araddr  (cpu_tcm_axi_req_i.ar.addr),
    .dma_axi_arsize  (cpu_tcm_axi_req_i.ar.size),
    .dma_axi_arprot  (cpu_tcm_axi_req_i.ar.prot),
    .dma_axi_arlen   (cpu_tcm_axi_req_i.ar.len),
    .dma_axi_arburst (cpu_tcm_axi_req_i.ar.burst),
    .dma_axi_rvalid  (cpu_tcm_axi_resp_o.r_valid),
    .dma_axi_rready  (cpu_tcm_axi_req_i.r_ready),
    .dma_axi_rid     (cpu_tcm_axi_resp_o.r.id),
    .dma_axi_rdata   (cpu_tcm_axi_resp_o.r.data),
    .dma_axi_rresp   (cpu_tcm_axi_resp_o.r.resp),
    .dma_axi_rlast   (cpu_tcm_axi_resp_o.r.last)
  );

  //////////////////////////////
  // Lockstep (when not built) //
  //////////////////////////////

`ifndef RV_LOCKSTEP_ENABLE
  // No VeeR lockstep ports to bind to; keep this module's own ports well-defined.
  assign lockstep_status_o = '0;

  logic unused_lockstep_ctrl;
  assign unused_lockstep_ctrl = |lockstep_ctrl_i;
`endif

  ///////////////////////////////////////////
  // SB/DBG AXI ID Width Conversion Logic //
  ///////////////////////////////////////////

  // Convert EL2 SB ID width to AXI struct ID width
  // If pt.SB_BUS_TAG < SEP_32_64_3_12_ID_WIDTH: zero-pad MSBs
  // If pt.SB_BUS_TAG > SEP_32_64_3_12_ID_WIDTH: truncate MSBs (should not happen in practice)
  // If pt.SB_BUS_TAG == SEP_32_64_3_12_ID_WIDTH: direct assignment

  assign dbg_axi_req_raw.aw.id = sep_pkg::SEP_32_64_3_12_ID_WIDTH'(sb_axi_awid_raw);
  assign dbg_axi_req_raw.ar.id = sep_pkg::SEP_32_64_3_12_ID_WIDTH'(sb_axi_arid_raw);

  // Convert AXI struct ID width to EL2 SB ID width
  assign sb_axi_bid_raw = pt.SB_BUS_TAG'(dbg_axi_resp_raw.b.id);
  assign sb_axi_rid_raw = pt.SB_BUS_TAG'(dbg_axi_resp_raw.r.id);

  ////////////////////
  // Struct Mapping //
  ////////////////////

  // Map el2_mem_if signals to output struct (req: CPU -> TCM macros)
  assign sep_cpu_tcm_req_o.clk               = el2_mem_if.clk;
  assign sep_cpu_tcm_req_o.iccm_clken        = el2_mem_if.iccm_clken;
  assign sep_cpu_tcm_req_o.iccm_wren_bank    = el2_mem_if.iccm_wren_bank;
  assign sep_cpu_tcm_req_o.iccm_addr_bank    = el2_mem_if.iccm_addr_bank;
  assign sep_cpu_tcm_req_o.iccm_bank_wr_data = el2_mem_if.iccm_bank_wr_data;
  assign sep_cpu_tcm_req_o.iccm_bank_wr_ecc  = el2_mem_if.iccm_bank_wr_ecc;
  assign sep_cpu_tcm_req_o.dccm_clken        = el2_mem_if.dccm_clken;
  assign sep_cpu_tcm_req_o.dccm_wren_bank    = el2_mem_if.dccm_wren_bank;
  assign sep_cpu_tcm_req_o.dccm_addr_bank    = el2_mem_if.dccm_addr_bank;
  assign sep_cpu_tcm_req_o.dccm_wr_data_bank = el2_mem_if.dccm_wr_data_bank;
  assign sep_cpu_tcm_req_o.dccm_wr_ecc_bank  = el2_mem_if.dccm_wr_ecc_bank;

  // Map input struct to el2_mem_if signals (rsp: TCM macros -> CPU)
  assign el2_mem_if.iccm_bank_dout = sep_cpu_tcm_rsp_i.iccm_bank_dout;
  assign el2_mem_if.iccm_bank_ecc  = sep_cpu_tcm_rsp_i.iccm_bank_ecc;
  assign el2_mem_if.dccm_bank_dout = sep_cpu_tcm_rsp_i.dccm_bank_dout;
  assign el2_mem_if.dccm_bank_ecc  = sep_cpu_tcm_rsp_i.dccm_bank_ecc;

  // ICache (Tie off - no ICache)
  assign el2_mem_if.wb_packeddout_pre          = '0;
  assign el2_mem_if.wb_dout_pre_up             = '0;
  assign el2_mem_if.ic_tag_data_raw_packed_pre = '0;
  assign el2_mem_if.ic_tag_data_raw_pre        = '0;

  // Tie off missing AXI user fields in EL2 wrapper connections (raw signals)
  // Masters: drive req user fields to 0, and ignore resp user by tying to 0
  assign ifu_axi_req_raw.aw.user = sep_pkg::SEP_SOURCE_ID;
  assign ifu_axi_req_raw.w.user  = sep_pkg::SEP_SOURCE_ID;
  assign ifu_axi_req_raw.ar.user = sep_pkg::SEP_SOURCE_ID;

  assign lsu_axi_req_raw.aw.user = sep_pkg::SEP_SOURCE_ID;
  assign lsu_axi_req_raw.w.user  = sep_pkg::SEP_SOURCE_ID;
  assign lsu_axi_req_raw.ar.user = sep_pkg::SEP_SOURCE_ID;

  assign dbg_axi_req_raw.aw.user = sep_pkg::SEP_SOURCE_ID;
  assign dbg_axi_req_raw.w.user  = sep_pkg::SEP_SOURCE_ID;
  assign dbg_axi_req_raw.ar.user = sep_pkg::SEP_SOURCE_ID;

  // Tie off ATOP (atomic operation) fields - not supported by EL2
  assign ifu_axi_req_raw.aw.atop = '0;
  assign lsu_axi_req_raw.aw.atop = '0;
  assign dbg_axi_req_raw.aw.atop = '0;

  // Slave: EL2 wrapper doesn't produce user on responses
  assign cpu_tcm_axi_resp_o.b.user = sep_pkg::SEP_SOURCE_ID;
  assign cpu_tcm_axi_resp_o.r.user = sep_pkg::SEP_SOURCE_ID;

  //////////////////////////////////
  // Local Alias Address Remapper //
  //////////////////////////////////

  // LSU Bus Remap
  axi_window_remap #(
    .axi_req_t      (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_resp_t     (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .AXI_ADDR_WIDTH (sep_pkg::SEP_32_64_3_12_ADDR_WIDTH)
  ) u_lsu_local_alias_remap (
    .slv_req_i          (lsu_axi_req_raw),
    .slv_resp_o         (lsu_axi_resp_raw),
    .mst_req_o          (lsu_axi_req),
    .mst_resp_i         (lsu_axi_resp),
    .local_alias_base_i (sep_local_base_addr_i),
    .region_size_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_SIZE[31:0]),
    .target_base_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_BASE[31:0])
  );

  // IFU Bus Remap
  axi_window_remap #(
    .axi_req_t      (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_resp_t     (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .AXI_ADDR_WIDTH (sep_pkg::SEP_32_64_3_12_ADDR_WIDTH)
  ) u_ifu_local_alias_remap (
    .slv_req_i          (ifu_axi_req_raw),
    .slv_resp_o         (ifu_axi_resp_raw),
    .mst_req_o          (ifu_axi_req),
    .mst_resp_i         (ifu_axi_resp),
    .local_alias_base_i (sep_local_base_addr_i),
    .region_size_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_SIZE[31:0]),
    .target_base_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_BASE[31:0])
  );

  // DBG Bus Remap
  axi_window_remap #(
    .axi_req_t      (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_resp_t     (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .AXI_ADDR_WIDTH (sep_pkg::SEP_32_64_3_12_ADDR_WIDTH)
  ) u_dbg_local_alias_remap (
    .slv_req_i          (dbg_axi_req_raw),
    .slv_resp_o         (dbg_axi_resp_raw),
    .mst_req_o          (dbg_axi_req_o),
    .mst_resp_i         (dbg_axi_resp_i),
    .local_alias_base_i (sep_local_base_addr_i),
    .region_size_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_SIZE[31:0]),
    .target_base_i      (sep_pkg::SEP_LOCAL_ALIAS_REGION_BASE[31:0])
  );

  ///////////////////
  // IFU AXI Demux //
  ///////////////////

  sep_pkg::sep_32_64_3_12_axi_req_t  [sep_pkg::SEP_IFU_DEMUX_NUM_PORTS-1:0] ifu_demux_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t [sep_pkg::SEP_IFU_DEMUX_NUM_PORTS-1:0] ifu_demux_resp;
  sep_pkg::sep_ifu_demux_port_t ifu_aw_select, ifu_ar_select;

  always_comb begin
    if ((ifu_axi_req.aw.addr >= sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR) && (ifu_axi_req.aw.addr < sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_SIZE)) begin
      ifu_aw_select = sep_pkg::SEP_IFU_DEMUX_PORT_ROM;
    end else if ((ifu_axi_req.aw.addr >= sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR) && (ifu_axi_req.aw.addr < sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_SIZE)) begin
      ifu_aw_select = sep_pkg::SEP_IFU_DEMUX_PORT_SRAM;
    end else begin
      ifu_aw_select = sep_pkg::SEP_IFU_DEMUX_PORT_ERR_SLV;
    end

    if ((ifu_axi_req.ar.addr >= sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR) && (ifu_axi_req.ar.addr < sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_SIZE)) begin
      ifu_ar_select = sep_pkg::SEP_IFU_DEMUX_PORT_ROM;
    end else if ((ifu_axi_req.ar.addr >= sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR) && (ifu_axi_req.ar.addr < sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_SIZE)) begin
      ifu_ar_select = sep_pkg::SEP_IFU_DEMUX_PORT_SRAM;
    end else begin
      ifu_ar_select = sep_pkg::SEP_IFU_DEMUX_PORT_ERR_SLV;
    end
  end

  axi_demux #(
    .AxiIdWidth  (sep_pkg::SEP_32_64_3_12_ID_WIDTH),
    .AtopSupport (1'b0),
    .aw_chan_t   (sep_pkg::sep_32_64_3_12_axi_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_32_64_3_12_axi_w_chan_t),
    .b_chan_t    (sep_pkg::sep_32_64_3_12_axi_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_32_64_3_12_axi_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_32_64_3_12_axi_r_chan_t),
    .axi_req_t   (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_resp_t  (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .NoMstPorts  (sep_pkg::SEP_IFU_DEMUX_NUM_PORTS),
    .MaxTrans    (4),
    .AxiLookBits (sep_pkg::SEP_32_64_3_12_ID_WIDTH),
    .UniqueIds   (1'b0),
    .SpillAw     (1'b0),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b0),
    .SpillR      (1'b0),
    .SelHashIds  (1'b0)
  ) u_ifu_axi_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (ifu_axi_req),
    .slv_aw_select_i (ifu_aw_select),
    .slv_ar_select_i (ifu_ar_select),
    .sel_hash_i      ('0),
    .slv_resp_o      (ifu_axi_resp),
    .mst_reqs_o      (ifu_demux_req),
    .mst_resps_i     (ifu_demux_resp)
  );

  // Connect demux outputs to module ports
  assign ifu_rom_axi_req_o                     = ifu_demux_req[sep_pkg::SEP_IFU_DEMUX_PORT_ROM];
  assign ifu_demux_resp[sep_pkg::SEP_IFU_DEMUX_PORT_ROM] = ifu_rom_axi_resp_i;

  assign ifu_sram_axi_req_o                      = ifu_demux_req[sep_pkg::SEP_IFU_DEMUX_PORT_SRAM];
  assign ifu_demux_resp[sep_pkg::SEP_IFU_DEMUX_PORT_SRAM] = ifu_sram_axi_resp_i;

  // Error slave for invalid address decodes
  axi_err_slv #(
    .AxiIdWidth (sep_pkg::SEP_32_64_3_12_ID_WIDTH),
    .axi_req_t  (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_resp_t (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .Resp       (axi_pkg::RESP_DECERR),
    .ATOPs      (1'b0),
    .MaxTrans   (4)
  ) u_ifu_axi_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (ifu_demux_req[sep_pkg::SEP_IFU_DEMUX_PORT_ERR_SLV]),
    .slv_resp_o (ifu_demux_resp[sep_pkg::SEP_IFU_DEMUX_PORT_ERR_SLV])
  );

  ///////////////////
  // LSU AXI Demux //
  ///////////////////

  sep_pkg::sep_32_64_3_12_axi_req_t  [sep_pkg::SEP_LSU_DEMUX_NUM_PORTS-1:0] lsu_demux_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t [sep_pkg::SEP_LSU_DEMUX_NUM_PORTS-1:0] lsu_demux_resp;
  sep_pkg::sep_lsu_demux_port_t lsu_aw_select, lsu_ar_select;

  always_comb begin
    if ((lsu_axi_req.aw.addr >= sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR) && (lsu_axi_req.aw.addr < sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_SIZE)) begin
      lsu_aw_select = sep_pkg::SEP_LSU_DEMUX_PORT_ROM;
    end else begin
      lsu_aw_select = sep_pkg::SEP_LSU_DEMUX_PORT_XBAR;
    end

    if ((lsu_axi_req.ar.addr >= sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR) && (lsu_axi_req.ar.addr < sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_SIZE)) begin
      lsu_ar_select = sep_pkg::SEP_LSU_DEMUX_PORT_ROM;
    end else begin
      lsu_ar_select = sep_pkg::SEP_LSU_DEMUX_PORT_XBAR;
    end
  end

  axi_demux #(
    .AxiIdWidth  (sep_pkg::SEP_32_64_3_12_ID_WIDTH),
    .AtopSupport (1'b0),
    .aw_chan_t   (sep_pkg::sep_32_64_3_12_axi_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_32_64_3_12_axi_w_chan_t),
    .b_chan_t    (sep_pkg::sep_32_64_3_12_axi_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_32_64_3_12_axi_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_32_64_3_12_axi_r_chan_t),
    .axi_req_t   (sep_pkg::sep_32_64_3_12_axi_req_t),
    .axi_resp_t  (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .NoMstPorts  (sep_pkg::SEP_LSU_DEMUX_NUM_PORTS),
    .MaxTrans    (4),
    .AxiLookBits (sep_pkg::SEP_32_64_3_12_ID_WIDTH),
    .UniqueIds   (1'b0),
    .SpillAw     (1'b0),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b0),
    .SpillR      (1'b0),
    .SelHashIds  (1'b0)
  ) u_lsu_axi_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (lsu_axi_req),
    .slv_aw_select_i (lsu_aw_select),
    .slv_ar_select_i (lsu_ar_select),
    .sel_hash_i      ('0),
    .slv_resp_o      (lsu_axi_resp),
    .mst_reqs_o      (lsu_demux_req),
    .mst_resps_i     (lsu_demux_resp)
  );

  // Connect demux outputs to module ports
  assign lsu_rom_axi_req_o                      = lsu_demux_req[sep_pkg::SEP_LSU_DEMUX_PORT_ROM];
  assign lsu_demux_resp[sep_pkg::SEP_LSU_DEMUX_PORT_ROM] = lsu_rom_axi_resp_i;

  assign lsu_xbar_axi_req_o                      = lsu_demux_req[sep_pkg::SEP_LSU_DEMUX_PORT_XBAR];
  assign lsu_demux_resp[sep_pkg::SEP_LSU_DEMUX_PORT_XBAR] = lsu_xbar_axi_resp_i;

endmodule
