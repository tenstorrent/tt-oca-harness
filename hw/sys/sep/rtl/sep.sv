// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Integrate the SEP security processor CPU, crypto, IO, SMN, and lifecycle boundaries.
//
// Exposes JTAG, DMI, memory-macro, SMN AXI, crypto SRAM, eFuse, SPI, lifecycle, mailbox,
// and Key Manager error interfaces to the integrator.
// sep_global_base_addr_o and sep_region_size_o publish the SEP aperture from sep_cpu_ctrl
// CSRs for the SMU AXI crossbar SEP-target rule.
// External-aperture requests inside the eFuse shim CSR window are diverted to the eFuse
// wrapper; the rest leave on sep_external_axi_req_o. PIC source i+1 is internal interrupt i
// for the NUM_INTERNAL_IRQS internal sources (mailbox, DMA, WDT, SPI, crypto, eFuse and
// bridge faults), followed by extintsrc_req_i. The WDT bark drives the CPU NMI, which jumps
// to SEP_NMI_VEC.
// When unused, tie test_en_i to 1'b0 and scan_rst_ni to 1'b1.

`include "axi/assign.svh"
`include "prim_assert.sv"

module sep #(
  parameter bit KM_LATCHED_MEM_RDATA = 1'b1,  // 1 if Key Manager ROM/SRAM latch read data for
                                              // look-ahead.
  parameter bit ABR_MASKING_EN = 1'b1,        // Enable Adams Bridge 2-share DOM masking.
  parameter int unsigned ABR_SRAM_LATENCY = 1,  // Adams Bridge SRAM read latency in cycles.
  parameter int unsigned EXT_TRNG_NUM_AXIS = 3,  // Number of external TRNG AXI-Stream ports; must
                                                 // be 3, one per entropy mux leg.
  parameter int unsigned EFUSE_SHIM_SIZE = 'h4,  // Size in bytes of the eFuse shim CSR window
                                                 // diverted from the external aperture to the eFuse
                                                 // wrapper.
  parameter bit [255:0] SEP_SEC_DISABLE_TOKEN = 256'b0  // Netlist-embedded secure-disable token
                                                        // digest; replace at synthesis.
) (
  input  logic clk_i,                         // System clock.
  input  logic clk_ref_i,                     // Free-running reference clock for REFERENCE_COUNTER.
  input  logic clk_wdt_i,                     // 200 kHz watchdog counter clock, asynchronous to
                                              // clk_i.
  input  logic rst_ni,                        // Active-low reset. Unless the JTAG override forces
                                              // it, the SEP reset derived from it is released only
                                              // after fuse sensing and ext_boot_seq_done_i.
  input  logic dbg_rstb_i,                    // EL2 debug-module reset, active-low.
  input  logic wdt_rst_ni,                    // Aggregated WDT resets from SMC and SEP, active-low;
                                              // resets only the CPU.

  output logic wdt_timer_rst_req_o,           // SEP WDT bite reset request, active-high, to the SMC
                                              // reset unit.

  input  logic jtag_tck_i,                    // JTAG clock.
  input  logic jtag_tms_i,                    // JTAG test mode select, sampled on jtag_tck_i.
  input  logic jtag_tdi_i,                    // JTAG test data input, sampled on jtag_tck_i.
  input  logic jtag_trst_ni,                  // JTAG reset, active-low.
  output logic jtag_tdo_o,                    // JTAG test data output; valid while jtag_tdoEn_o is
                                              // high.
  output logic jtag_tdoEn_o,                  // JTAG TDO output enable.

  input  sep_pkg::jtag_sep_reset_ctrl_t jtag_sep_reset_ctrl_i,  // JTAG IC_RESET override and value
                                                                // bits for the SEP reset and the
                                                                // per-engine crypto resets, in the
                                                                // TCK domain.

  input  sep_efuse_pkg::efuse_axil_req_t  axil_sep_otp_jtag_req_i,  // OTP debug AXI-Lite manager request to the eFuse wrapper; answered with DECERR in
                                                                    // restricted lifecycle states.
  output sep_efuse_pkg::efuse_axil_resp_t axil_sep_otp_jtag_resp_o,  // OTP debug AXI-Lite manager response.

  input  logic mpc_debug_halt_req_i,          // Async MPC debug halt request.
  input  logic mpc_debug_run_req_i,           // Async MPC debug run request.
  input  logic mpc_reset_run_req_i,           // 1 to run and 0 to halt in debug mode after reset.

  input  logic cpu_halt_req_i,                // Async halt request to the CPU.
  input  logic cpu_run_req_i,                 // Async restart request to the CPU.

  input  logic test_en_i,                     // DFT test-enable / scan-enable; tie 1'b0 when
                                              // unused.
  input  logic scan_rst_ni,                   // DFT scan reset, active-low, for reset synchronizer
                                              // bypass; tie 1'b1 when unused.

  input  logic ext_boot_seq_done_i,           // Integration boot-sequence completion (memory repair
                                              // and SMC straps); gates release of the SEP reset.

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

  output sep_pkg::sep_cpu_trace_t sep_cpu_trace_o,  // Core instruction trace: retired instruction,
                                                    // address, valid, exception, cause, interrupt,
                                                    // and tval.

  input  sep_pkg::sep_lockstep_ctrl_t   lockstep_ctrl_i,  // CPU lockstep control; inert unless
                                                          // built with RV_LOCKSTEP_ENABLE.
  output sep_pkg::sep_lockstep_status_t lockstep_status_o,  // CPU lockstep status; inert unless
                                                            // built with RV_LOCKSTEP_ENABLE.

  input logic [31:1] jtag_id_i,               // JTAG IDCODE bits [31:1] reported by the core debug
                                              // TAP; bit 0 is fixed at 1.

  input logic                      timer_int_i,  // Machine timer interrupt to the core.
  input logic                      soft_int_i,  // Machine software interrupt to the core.
  input logic [sep_pkg::NUM_EXTERNAL_IRQS-1:0] extintsrc_req_i,  // External interrupt requests; bit
                                                                 // i is PIC source
                                                                 // NUM_INTERNAL_IRQS + i + 1.

  output sep_pkg::sep_cpu_tcm_req_t sep_cpu_tcm_req_o,  // Per-bank ICCM and DCCM macro requests,
                                                        // with the macro clock, to sep_tcm_wrapper.
  input  sep_pkg::sep_cpu_tcm_rsp_t sep_cpu_tcm_rsp_i,  // Per-bank ICCM and DCCM read data and ECC
                                                        // from sep_tcm_wrapper.

  output sep_pkg::sep_sram_req_t    sep_sram_req_o,  // Request from the SEP SRAM memory interface
                                                     // to the SRAM macro.
  input  sep_pkg::sep_sram_rsp_t    sep_sram_rsp_i,  // Read data from the SEP SRAM macro.

  output sep_pkg::sep_sram_req_t    sep_boot_rom_req_o,  // Request from the boot ROM memory
                                                         // interface to the ROM macro.
  input  sep_pkg::sep_sram_rsp_t    sep_boot_rom_rsp_i,  // Read data from the boot ROM macro.

  output sep_pkg::sep_system_peripherals_outbound_axi_req_t  smn_outbound_axi_req_o,  // Outbound request to the SMN after the outbound filter.
  input  sep_pkg::sep_system_peripherals_outbound_axi_resp_t smn_outbound_axi_resp_i,  // Outbound response from the SMN.

  input  sep_pkg::sep_system_peripherals_internal_axi_req_t  smn_inbound_axi_req_i,  // SMN inbound request with a 56-bit global address, before the inbound filter.
  output sep_pkg::sep_system_peripherals_internal_axi_resp_t smn_inbound_axi_resp_o,  // SMN inbound response.

  output sep_pkg::sep_system_peripherals_internal_axi_req_t  sep_ext_to_smc_axi_req_o,  // SEP request in the SMC aperture, after the alias remap; not filtered.
  input  sep_pkg::sep_system_peripherals_internal_axi_resp_t sep_ext_to_smc_axi_resp_i,  // Response from the SMC to sep_ext_to_smc_axi_req_o.

  input logic entropy_rosc_sample_clk_i,      // Ring-oscillator sample clock for entropy_source;
                                              // async vs clk_i, ~100-400 MHz typical.

  output sep_crypto_pkg::sep_crypto_pka_imem_sram_req_t sep_crypto_pka_imem_sram_req_o,  // OTBN IMEM SRAM request from prim_ram_1p_scr_ext.
  input  sep_crypto_pkg::sep_crypto_pka_imem_sram_rsp_t sep_crypto_pka_imem_sram_rsp_i,  // OTBN IMEM SRAM response.

  output sep_crypto_pkg::sep_crypto_pka_dmem_sram_req_t sep_crypto_pka_dmem_sram_req_o,  // OTBN DMEM SRAM request from prim_ram_1p_scr_ext.
  input  sep_crypto_pkg::sep_crypto_pka_dmem_sram_rsp_t sep_crypto_pka_dmem_sram_rsp_i,  // OTBN DMEM SRAM response.

  output sep_crypto_pkg::abr_mem_req_t                  abr_mem_req_o,  // Adams Bridge external SRAM request; tech macros in sep_ip_integration.
  input  sep_crypto_pkg::abr_mem_rsp_t                  abr_mem_rsp_i,  // Adams Bridge external SRAM response.

  output sep_pkg::sep_32_32_axil_req_t  ext_trng_axil_req_o,  // External TRNG register request for
                                                              // 0x1091_7000-0x1091_7FFF, passed
                                                              // through to sep_ip_integration.
  input  sep_pkg::sep_32_32_axil_resp_t ext_trng_axil_resp_i,  // External TRNG AXI-Lite passthrough
                                                               // response.

  input  sep_crypto_pkg::ext_trng_axis_req_t ext_trng_axis_req_i [EXT_TRNG_NUM_AXIS-1:0],  // External TRNG streams from sep_ip_integration; stream i feeds entropy mux leg i
                                                                                           // (0 Key Manager, 1 AES/KMAC/OTBN, 2 entropy pool).
  output sep_crypto_pkg::ext_trng_axis_rsp_t ext_trng_axis_rsp_o [EXT_TRNG_NUM_AXIS-1:0],  // tready to each external TRNG stream: the consumer's tready when selected,
                                                                                           // held high to drain the stream when not.

  input logic ext_trng_irq_i,                 // External TRNG interrupt; PIC source 17.

  output km_intf_pkg::km_rom_mem_req_t   km_rom_mem_req_o,  // Key Manager request to its 16 KiB ROM
                                                            // hard macro.
  input  km_intf_pkg::km_rom_mem_rsp_t   km_rom_mem_rsp_i,  // Read data from the Key Manager ROM
                                                            // hard macro.
  output km_intf_pkg::km_sram_mem_req_t  km_sram_mem_req_o,  // Key Manager request to its 32 KiB
                                                             // SRAM hard macro.
  input  km_intf_pkg::km_sram_mem_rsp_t  km_sram_mem_rsp_i,  // Read data from the Key Manager SRAM
                                                             // hard macro.

  output sep_efuse_pkg::efuse_axil_req_t     efuse_bank_ctrl_req_o,  // eFuse bank control AXI-Lite request to the shim CSR.
  input  sep_efuse_pkg::efuse_axil_resp_t    efuse_bank_ctrl_resp_i,  // eFuse bank control AXI-Lite response.
  output sep_efuse_pkg::fuse_command_req_t   efuse_shim_command_req_o,  // eFuse read and program commands on the custom shim command interface.
  input  sep_efuse_pkg::fuse_command_resp_t  efuse_shim_command_resp_i,  // Shim response to the eFuse commands.

  output logic [1:0] lcc_demote_state_1_o,    // Differentially encoded DEMOTE_1.demote bit, which
                                              // re-opens debug feature bits [23:0] in TEST_DEV and
                                              // PROD; to the SMC.
  output logic [1:0] lcc_demote_state_2_o,    // Differentially encoded DEMOTE_2.demote bit, which
                                              // re-opens debug feature bits [47:24] in TEST_DEV and
                                              // PROD; to the SMC.

  output sep_io_pkg::sep_io_spi_req_t sep_io_spi_req_o,  // SPI pad outputs (clock, chip select, 4
                                                         // data lanes and their output enables),
                                                         // plus the SPI interrupt and DMA trigger.
  input  sep_io_pkg::sep_io_spi_rsp_t sep_io_spi_rsp_i,  // SPI data-lane inputs from the pads.

  output logic [2*sep_pkg::LcStateBitWidth-1:0] lc_state_o,     // Differentially encoded lifecycle
                                                                // state from the eFuse shadow
                                                                // registers.
  output sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable_o,  // Per-interface debug disables for
                                                               // the DTP, active-high (1 =
                                                               // disabled).
  output logic sep_fuse_dft_disable_o,        // Disables the SEP fuse DFT access path, active-high;
                                              // no functional consumer, provided for DFT insertion.
  output logic smc_fuse_dft_disable_o,        // Disables the SMC fuse DFT access path, active-high;
                                              // no functional consumer, provided for DFT insertion.
  output logic lc_sigint_err_o,               // Integrity error on the differentially encoded LC
                                              // state; forces every feature enable off unless
                                              // security is disabled.
  output logic security_disable_o,            // Security-disable status from eFuse token
                                              // processing, active-high.
  output logic secure_tm_o,                   // Latched secure test mode, active-high; captured on
                                              // the second clock edge after rst_ni release when
                                              // security is disabled, otherwise when fuse sensing
                                              // finishes.

  output logic [sep_pkg::NumMailboxes-1:0] smc_mailbox_interrupt_o,  // Per-mailbox outbound-data interrupts to the SMC.

  input  logic smc_fuse_sense_done_i,         // SMC fuse sense completion, reflected in
                                              // SMC_FUSE_SENSE_STATUS; requests to the SMC hang
                                              // while it is low.
  output logic sep_fuse_sense_done_o,         // High once the SEP eFuse shadow registers have been
                                              // loaded from the fuses.

  input logic secure_tm_req_i,                // Secure test mode request strap, latched into
                                              // secure_tm_o.

  output sep_pkg::sep_32_64_6_12_axi_req_t  sep_external_axi_req_o,  // Request for the external aperture 0x2000_0000-0x3FFF_FFFF outside the eFuse
                                                                     // shim window.
  input  sep_pkg::sep_32_64_6_12_axi_resp_t sep_external_axi_resp_i,  // Response to sep_external_axi_req_o.

  input  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0]        smc_global_base_addr_i,  // Base of the SMC aperture in the global address map; SEP requests inside it
                                                                                                   // leave on sep_ext_to_smc_axi_req_o.
  input  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0]        smc_region_size_i,  // Size in bytes of the SMC aperture at smc_global_base_addr_i.

  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0]        sep_global_base_addr_o,  // SEP global base address from sep_cpu_ctrl; SMU crossbar SEP-target rule.
  output logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0]        sep_region_size_o,  // SEP region size from sep_cpu_ctrl; SMU crossbar SEP-target rule.

  output logic km_unrecoverable_err_o,        // Key Manager unrecoverable fault, active-high: its
                                              // CPU is in the trap state and no longer executing;
                                              // also PIC source 31.
  output logic km_recoverable_err_o,          // Key Manager recoverable-fault indication; also PIC
                                              // source 32.

  output logic [383:0] ext_debug_bus_o        // 24 lanes of 16 bits: CPU trace and control status,
                                              // interrupts, reset and security status, eFuse, remap
                                              // and filter debug; bits [159:0] are 0.
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // Additional AXI interfaces for new crossbar wrapper
  // Masters: dma (unused/tied-off), ext (optional external master)

  logic cpu_iccm_ecc_single_error;
  logic cpu_iccm_ecc_double_error;
  logic cpu_dccm_ecc_single_error;
  logic cpu_dccm_ecc_double_error;

  logic cpu_dec_tlu_perfcnt0; // toggles when slot0 perf counter 0 has an event inc
  logic cpu_dec_tlu_perfcnt1;
  logic cpu_dec_tlu_perfcnt2;
  logic cpu_dec_tlu_perfcnt3;

  // Debug control signals (internal wires connected to sep_cpu outputs)
  logic mpc_debug_halt_ack;
  logic mpc_debug_run_ack;
  logic debug_brkpt_status;
  logic cpu_halt_ack_o;
  logic cpu_halt_status_o;
  logic debug_mode_status_o;
  logic cpu_run_ack_o;
  logic [9:0] sep_efuse_debug;
  logic [5:0] sep_efuse_token_match_sip_debug;
  logic [5:0] sep_efuse_token_match_chiplet_debug;

  sep_pkg::remap_debug_t         local_masters_remap_debug;
  logic [$clog2(sep_pkg::OutboundFilterNumFilters)-1:0]
      outbound_write_filter_hit_debug, outbound_read_filter_hit_debug;
  logic [$clog2(sep_pkg::InboundFilterNumFilters)-1:0]
      inbound_write_filter_hit_debug, inbound_read_filter_hit_debug;


  // Bridge structs for AXI4 wrappers (slaves)
  sep_pkg::sep_32_64_3_12_axi_req_t  smn_inbound_to_sep_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t smn_inbound_to_sep_axi_resp;

  sep_pkg::sep_32_64_3_12_axi_req_t  ifu_sram_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t ifu_sram_axi_resp;
  sep_pkg::sep_32_64_3_12_axi_req_t  dbg_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t dbg_axi_resp;

  sep_pkg::sep_32_64_3_12_axi_req_t  dma_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t dma_axi_resp;

  sep_pkg::sep_32_64_6_12_axi_req_t  dma_csr_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t dma_csr_rsp;
  sep_pkg::sep_32_64_6_12_axi_req_t  sram_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sram_rsp;
  sep_pkg::sep_32_64_3_12_axi_req_t  ifu_rom_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t ifu_rom_axi_resp;
  sep_pkg::sep_32_64_3_12_axi_req_t  lsu_rom_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t lsu_rom_axi_resp;
  sep_pkg::sep_32_64_3_12_axi_req_t  lsu_xbar_axi_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t lsu_xbar_axi_resp;

  sep_pkg::sep_32_64_3_12_axi_req_t  [sep_pkg::SEP_ROM_MUX_NUM_PORTS-1:0] rom_mux_req;
  sep_pkg::sep_32_64_3_12_axi_resp_t [sep_pkg::SEP_ROM_MUX_NUM_PORTS-1:0] rom_mux_resp;
  sep_pkg::sep_32_64_4_12_axi_req_t  rom_axi_req;
  sep_pkg::sep_32_64_4_12_axi_resp_t rom_axi_resp;

  sep_pkg::sep_32_64_6_12_axi_req_t  cpu_tcm_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t cpu_tcm_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  sep_crypto_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sep_crypto_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  sep_external_pre_demux_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sep_external_pre_demux_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  efuse_shim_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t efuse_shim_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  sep_io_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sep_io_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  entropy_fifo_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t entropy_fifo_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  sep_system_peripherals_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sep_system_peripherals_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  sep_wdt_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sep_wdt_axi_resp;
  sep_pkg::sep_32_64_6_12_axi_req_t  sep_reset_ctrl_axi_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t sep_reset_ctrl_axi_resp;

  logic [sep_pkg::SEP_CPU_IRQ_WIDTH-1:0] sep_interrupts;
  logic [sep_pkg::NUM_INTERNAL_IRQS-1:0] sep_internal_interrupts;
  logic intr_wdog_timer_bark;
  logic wdt_debug_sleep_mode;

  // WDT sleep mode - tie low for normal operation (watchdog always counts)
  assign wdt_debug_sleep_mode = 1'b0;

  logic [sep_pkg::NumMailboxes-1:0] sep_mailbox_interrupt;
  logic km_mbox_irq;
  logic entropy_source_irq;
  logic ext_trng_irq;
  logic locked_field_access_interrupt;
  logic token_match_fault;

  // DMA interrupt signals
  logic intr_dma_done;
  logic intr_dma_chunk_done;
  logic intr_dma_error;
  logic dma_alert;
  logic dma_reg_bus_err;
  logic dma_host_intg_err;
  logic dma_err_clr;

  // Peripheral register-bridge faults, one bit per block (sep_pkg::periph_bus_err_e
  // gives the bit order, shared with PERIPH_BUS_ERR_STATUS/_CLEAR).
  logic [sep_pkg::NUM_PERIPH_BUS_ERRS-1:0] periph_bus_err;
  logic [sep_pkg::NUM_PERIPH_BUS_ERRS-1:0] periph_bus_err_clr;
  logic wdt_alert;

  // Crypto subsystem interrupt signals (from sep_crypto)
  logic intr_hmac_done;
  logic intr_hmac_fifo_empty;
  logic intr_hmac_err;
  logic intr_kmac_done;
  logic intr_kmac_fifo_empty;
  logic intr_kmac_err;
  logic intr_cs_cmd_req_done;
  logic intr_cs_entropy_req;
  logic intr_cs_hw_inst_exc;
  logic intr_cs_fatal_err;
  logic intr_edn_cmd_req_done;
  logic intr_edn_fatal_err;
  logic intr_otbn_done;
  logic intr_abr_error;
  logic intr_abr_notif;
  logic km_unrecoverable_err;
  logic km_recoverable_err;
  logic crypto_alert;

  // Entropy-pool FIFO: native EDN fill bundle (out of sep_crypto) + status IRQs
  edn_pkg::edn_req_t entropy_pool_edn_req;
  edn_pkg::edn_rsp_t entropy_pool_edn_rsp;
  logic entropy_pool_low;
  logic entropy_pool_fill_stall;
  logic entropy_pool_err;
  logic trng_entropy_clear;

  logic [31:1] nmi_vec;

  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_local_base_addr;
  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_global_base_addr;
  logic [sep_pkg::SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH-1:0] sep_region_size;

  // Expose CSR-configured SEP aperture up to the SMU boundary for the
  // runtime SMU AXI crossbar address map.
  assign sep_global_base_addr_o = sep_global_base_addr;
  assign sep_region_size_o      = sep_region_size;

  logic security_disable;
  sep_efuse_pkg::sep_efuse_map_lc_disable_reg_t feat_ctrl;

  //////////////
  // SEP Resets
  //////////////

  logic sep_intermediate_reset_n; // Intermediate reset signal (before JTAG override) for efuse sensing being done
  logic sep_reset_n; // Efuse sensing done signal (after JTAG override)
  logic sep_cpu_reset_n; // This is the reset signal for the CPU
  logic wdt_timer_rst_req; // This is the reset signal for the WDT timer (actitve high)
  logic [2:0] ext_trng_src_sel; // External TRNG source selection from sep_cpu_ctrl
  logic km_wipe_state; // Key Manager emergency wipe control from sep_cpu_ctrl
  // Isolation handshake and sequenced resets between sep_reset_ctrl and sep_crypto
  sep_pkg::sep_crypto_isolate_t sep_crypto_isolate_req;
  sep_pkg::sep_crypto_isolate_t sep_crypto_isolated;
  sep_pkg::sep_sw_rst_t         sep_crypto_gated_rst_n;

  //////////////////
  // AXI Crossbar //
  //////////////////

  // Address width = 32 bits
  // Data width = 64 bits
  // Local generated crossbar wrapper (AXI only)
  sep_local_axi_xbar_wrapper u_sep_local_axi_xbar_wrapper (
    .clk_i                              (clk_i),
    .rst_ni                             (rst_ni),

    // AXI4 Slave Interfaces
    .ifu_sram_axi_req_i                 (ifu_sram_axi_req),
    .ifu_sram_axi_resp_o                (ifu_sram_axi_resp),

    .lsu_axi_req_i                      (lsu_xbar_axi_req),
    .lsu_axi_resp_o                     (lsu_xbar_axi_resp),

    .dbg_axi_req_i                      (dbg_axi_req),
    .dbg_axi_resp_o                     (dbg_axi_resp),

    .dma_axi_req_i                      (dma_axi_req),
    .dma_axi_resp_o                     (dma_axi_resp),

    .ext_axi_req_i                      (smn_inbound_to_sep_axi_req),
    .ext_axi_resp_o                     (smn_inbound_to_sep_axi_resp),

    // AXI4 Master Interfaces
    .cpu_tcm_axi_req_o                  (cpu_tcm_axi_req),
    .cpu_tcm_axi_resp_i                 (cpu_tcm_axi_resp),

    .dma_csr_axi_req_o                  (dma_csr_req),
    .dma_csr_axi_resp_i                 (dma_csr_rsp),

    .sram_axi_req_o                     (sram_req),
    .sram_axi_resp_i                    (sram_rsp),

    .sep_crypto_axi_req_o               (sep_crypto_axi_req),
    .sep_crypto_axi_resp_i              (sep_crypto_axi_resp),

    .sep_io_axi_req_o                   (sep_io_axi_req),
    .sep_io_axi_resp_i                  (sep_io_axi_resp),

    .entropy_fifo_axi_req_o             (entropy_fifo_axi_req),
    .entropy_fifo_axi_resp_i            (entropy_fifo_axi_resp),

    .sep_system_peripherals_axi_req_o   (sep_system_peripherals_axi_req),
    .sep_system_peripherals_axi_resp_i  (sep_system_peripherals_axi_resp),

    .sep_wdt_axi_req_o                  (sep_wdt_axi_req),
    .sep_wdt_axi_resp_i                 (sep_wdt_axi_resp),

    .sep_reset_ctrl_axi_req_o           (sep_reset_ctrl_axi_req),
    .sep_reset_ctrl_axi_resp_i          (sep_reset_ctrl_axi_resp),

    .sep_external_axi_req_o            (sep_external_pre_demux_req),
    .sep_external_axi_resp_i           (sep_external_pre_demux_resp)
  );

  ///////////////////////////
  // eFuse SHIM Routing    //
  ///////////////////////////

  // eFuse shim CSR lives in sep_external addr map but must pass through efuse controller before reaching ip_integration
  // Added demux to reroute eFuse shim traffic from xbar external to efuse_wrapper

  localparam logic [31:0] EfuseShimBase =
        32'(sep_top_addrmap_pkg::SEP_TOP_SEP_EXTERNAL_EFUSE_SHIM_CTRL_BASE_ADDR);

  localparam int unsigned NumExtDemuxPorts = 2;
  typedef enum logic [$clog2(
NumExtDemuxPorts
)-1:0] {
    EXT_DEMUX_EXTERNAL   = 1'd0,
    EXT_DEMUX_EFUSE_SHIM = 1'd1
  } ext_demux_target_e;

  sep_pkg::sep_32_64_6_12_axi_req_t  [NumExtDemuxPorts-1:0]    ext_demux_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t [NumExtDemuxPorts-1:0]    ext_demux_resp;
  ext_demux_target_e                                           ext_demux_aw_select;
  ext_demux_target_e                                           ext_demux_ar_select;

  function automatic ext_demux_target_e ext_demux_decode(
      input logic [sep_pkg::SEP_32_64_6_12_ADDR_WIDTH-1:0] addr);
    if (addr >= EfuseShimBase && addr < EfuseShimBase + EFUSE_SHIM_SIZE) begin
      return EXT_DEMUX_EFUSE_SHIM;
    end else begin
      return EXT_DEMUX_EXTERNAL;
    end
  endfunction

  always_comb begin
    ext_demux_aw_select = ext_demux_decode(sep_external_pre_demux_req.aw.addr);
    ext_demux_ar_select = ext_demux_decode(sep_external_pre_demux_req.ar.addr);
  end

  axi_demux #(
    .AxiIdWidth  (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .AtopSupport (1'b0),
    .aw_chan_t   (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t    (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_req_t   (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t  (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .NoMstPorts  (NumExtDemuxPorts),
    .MaxTrans    (4),
    .AxiLookBits (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .UniqueIds   (1'b0),
    .SpillAw     (1'b1),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b1),
    .SpillR      (1'b0)
  ) u_efuse_shim_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sep_external_pre_demux_req),
    .slv_resp_o      (sep_external_pre_demux_resp),
    .slv_aw_select_i (ext_demux_aw_select),
    .slv_ar_select_i (ext_demux_ar_select),
    .sel_hash_i      ('0),
    .mst_reqs_o      (ext_demux_req),
    .mst_resps_i     (ext_demux_resp)
  );

  assign sep_external_axi_req_o                = ext_demux_req [EXT_DEMUX_EXTERNAL];
  assign ext_demux_resp[EXT_DEMUX_EXTERNAL]    = sep_external_axi_resp_i;
  assign efuse_shim_axi_req                    = ext_demux_req [EXT_DEMUX_EFUSE_SHIM];
  assign ext_demux_resp[EXT_DEMUX_EFUSE_SHIM]  = efuse_shim_axi_resp;

  /////////////////////
  // Interrupt Logic //
  /////////////////////

  assign ext_trng_irq = ext_trng_irq_i;

  // External interrupt aggregation
  always_comb begin
    sep_internal_interrupts         = '0;
    sep_internal_interrupts[7:0]    = sep_mailbox_interrupt;
    sep_internal_interrupts[8]      = intr_dma_done;
    sep_internal_interrupts[9]      = intr_dma_chunk_done;
    sep_internal_interrupts[10]     = intr_dma_error;
    sep_internal_interrupts[11]     = dma_alert;
    sep_internal_interrupts[12]     = wdt_alert;
    sep_internal_interrupts[13]     = sep_io_spi_req_o.irq;
    sep_internal_interrupts[14]     = km_mbox_irq;
    sep_internal_interrupts[15]     = entropy_source_irq;
    sep_internal_interrupts[16]     = ext_trng_irq;
    sep_internal_interrupts[17]     = intr_hmac_done;
    sep_internal_interrupts[18]     = intr_hmac_fifo_empty;
    sep_internal_interrupts[19]     = intr_hmac_err;
    sep_internal_interrupts[20]     = intr_kmac_done;
    sep_internal_interrupts[21]     = intr_kmac_fifo_empty;
    sep_internal_interrupts[22]     = intr_kmac_err;
    sep_internal_interrupts[23]     = intr_cs_cmd_req_done;
    sep_internal_interrupts[24]     = intr_cs_entropy_req;
    sep_internal_interrupts[25]     = intr_cs_hw_inst_exc;
    sep_internal_interrupts[26]     = intr_cs_fatal_err;
    sep_internal_interrupts[27]     = intr_edn_cmd_req_done;
    sep_internal_interrupts[28]     = intr_edn_fatal_err;
    sep_internal_interrupts[29]     = intr_otbn_done;
    sep_internal_interrupts[30]     = km_unrecoverable_err;
    sep_internal_interrupts[31]     = km_recoverable_err;
    sep_internal_interrupts[32]     = crypto_alert;
    sep_internal_interrupts[33]     = locked_field_access_interrupt;
    sep_internal_interrupts[34]     = intr_abr_error;
    sep_internal_interrupts[35]     = intr_abr_notif;
    // Entropy-pool FIFO: separate PIC lines so firmware can distinguish a
    // transient low-water condition (informational, pool draining faster than
    // it fills) from a sustained EDN stall (fault, fill path not making progress).
    // Line 38 carries the pool pointer-integrity error, which is always 0 because
    // the pool FIFO is built without hardened pointers.
    sep_internal_interrupts[36]     = entropy_pool_low;
    sep_internal_interrupts[37]     = entropy_pool_fill_stall;
    sep_internal_interrupts[38]     = entropy_pool_err;
    sep_internal_interrupts[39]     = token_match_fault;
    // Secure DMA bridge faults. Level-sensitive: both sources are latched in the DMA
    // wrapper and held until firmware writes DMA_BUS_ERR_CLEAR. An edge-triggered
    // gateway would miss them after a WDT CPU reset, which resets the CPU but not the
    // DMA, leaving the source already high before the gateway is armed.
    sep_internal_interrupts[40]     = dma_reg_bus_err;
    sep_internal_interrupts[41]     = dma_host_intg_err;
    // Peripheral register-bridge faults share one source; firmware reads
    // PERIPH_BUS_ERR_STATUS to find which block faulted.
    sep_internal_interrupts[42]     = |periph_bus_err;
  end

  assign sep_interrupts = {extintsrc_req_i, sep_internal_interrupts};

  // Expose KM error signals as output ports
  assign km_unrecoverable_err_o = km_unrecoverable_err;
  assign km_recoverable_err_o   = km_recoverable_err;

  /////////////
  // SEP CPU //
  /////////////

  sep_cpu u_sep_cpu (
    .clk_i                          (clk_i),
    .rst_ni                         (sep_cpu_reset_n),
    .dbg_rstb_i                     (dbg_rstb_i),

    .jtag_tck_i                     (jtag_tck_i),   // JTAG clk
    .jtag_tms_i                     (jtag_tms_i),   // JTAG TMS
    .jtag_tdi_i                     (jtag_tdi_i),   // JTAG tdi
    .jtag_trst_ni                   (jtag_trst_ni), // JTAG Reset
    .jtag_tdo_o                     (jtag_tdo_o),   // JTAG TDO
    .jtag_tdoEn_o                   (jtag_tdoEn_o), // JTAG Test Data Output enable

    // external MPC halt/run interface
    .mpc_debug_halt_req_i           (mpc_debug_halt_req_i), // Async halt request
    .mpc_debug_run_req_i            (mpc_debug_run_req_i),  // Async run request
    .mpc_reset_run_req_i            (mpc_reset_run_req_i),  // Run/halt after reset
    .mpc_debug_halt_ack_o           (mpc_debug_halt_ack),   // Halt ack
    .mpc_debug_run_ack_o            (mpc_debug_run_ack),    // Run ack
    .debug_brkpt_status_o           (debug_brkpt_status),   // debug breakpoint

    .cpu_halt_req_i                 (cpu_halt_req_i),      // Async halt req to CPU
    .cpu_halt_ack_o                 (cpu_halt_ack_o),      // core response to halt
    .cpu_halt_status_o              (cpu_halt_status_o),   // 1'b1 indicates core is halted
    .debug_mode_status_o            (debug_mode_status_o), // Core to the PMU that core is in debug mode. When core is in debug mode, the PMU should refrain from sendng a halt or run request
    .cpu_run_req_i                  (cpu_run_req_i),       // Async restart req to CPU
    .cpu_run_ack_o                  (cpu_run_ack_o),       // Core response to run req

    .test_en_i                      (test_en_i),

    // DMI port for uncore
    .dmi_core_enable_i              (dmi_core_enable_i),
    .dmi_uncore_enable_i            (dmi_uncore_enable_i),
    .dmi_uncore_en_o                (dmi_uncore_en_o),
    .dmi_uncore_wr_en_o             (dmi_uncore_wr_en_o),
    .dmi_uncore_addr_o              (dmi_uncore_addr_o),
    .dmi_uncore_wdata_o             (dmi_uncore_wdata_o),
    .dmi_uncore_rdata_i             (dmi_uncore_rdata_i),
    .dmi_active_o                   (dmi_active_o),

    // jtag_id_i and nmi_vec_i should be tied to constant in the top level or sourced from a CSR
    .nmi_vec_i                      (nmi_vec),
    .jtag_id_i                      (jtag_id_i),

    // Non-maskable interrupt, should be asserted for at least 2 clock cycles
    //                             (Documentation section 3.16, https://chipsalliance.github.io/Cores-VeeR-EL2/html/main/docs_rendered/html/memory-map.html#non-maskable-interrupt-nmi-signal-and-vector)
    .nmi_int_i                      (intr_wdog_timer_bark),
    .timer_int_i                    (timer_int_i),
    .soft_int_i                     (soft_int_i),
    .extintsrc_req_i                (sep_interrupts),

    .sep_cpu_trace_o                (sep_cpu_trace_o),

    .iccm_ecc_single_error_o        (cpu_iccm_ecc_single_error),
    .iccm_ecc_double_error_o        (cpu_iccm_ecc_double_error),
    .dccm_ecc_single_error_o        (cpu_dccm_ecc_single_error),
    .dccm_ecc_double_error_o        (cpu_dccm_ecc_double_error),

    .dec_tlu_perfcnt0_o             (cpu_dec_tlu_perfcnt0), // toggles when slot0 perf counter 0 has an event inc
    .dec_tlu_perfcnt1_o             (cpu_dec_tlu_perfcnt1),
    .dec_tlu_perfcnt2_o             (cpu_dec_tlu_perfcnt2),
    .dec_tlu_perfcnt3_o             (cpu_dec_tlu_perfcnt3),

    .lockstep_ctrl_i                (lockstep_ctrl_i),
    .lockstep_status_o              (lockstep_status_o),

    // TCM interface ports (pass-through to sep_wrapper)
    .sep_cpu_tcm_req_o              (sep_cpu_tcm_req_o),
    .sep_cpu_tcm_rsp_i              (sep_cpu_tcm_rsp_i),

    // AXI interface ports
    .ifu_sram_axi_req_o             (ifu_sram_axi_req),
    .ifu_sram_axi_resp_i            (ifu_sram_axi_resp),

    .ifu_rom_axi_req_o              (ifu_rom_axi_req),
    .ifu_rom_axi_resp_i             (ifu_rom_axi_resp),

    .lsu_rom_axi_req_o              (lsu_rom_axi_req),
    .lsu_rom_axi_resp_i             (lsu_rom_axi_resp),

    .lsu_xbar_axi_req_o             (lsu_xbar_axi_req),
    .lsu_xbar_axi_resp_i            (lsu_xbar_axi_resp),

    .dbg_axi_req_o                  (dbg_axi_req),
    .dbg_axi_resp_i                 (dbg_axi_resp),

    .cpu_tcm_axi_req_i              (cpu_tcm_axi_req),
    .cpu_tcm_axi_resp_o             (cpu_tcm_axi_resp),

    .sep_local_base_addr_i          (sep_local_base_addr[31:0])
  );

  ///////////////////////////
  // SRAM Memory Interface //
  ///////////////////////////


  localparam int unsigned NumSramDemuxPorts = 2;
  typedef enum logic [$clog2(
NumSramDemuxPorts
)-1:0] {
    SRAM_DEMUX_MEM     = 1'd0,
    SRAM_DEMUX_ERR_SLV = 1'd1
  } sram_demux_target_e;

  sep_pkg::sep_32_64_6_12_axi_req_t  [NumSramDemuxPorts-1:0]     sram_demux_req;
  sep_pkg::sep_32_64_6_12_axi_resp_t [NumSramDemuxPorts-1:0]     sram_demux_resp;
  sram_demux_target_e                                            sram_demux_aw_select;
  sram_demux_target_e                                            sram_demux_ar_select;

  function automatic sram_demux_target_e sram_demux_decode(input axi_pkg::len_t len,
                                                           input axi_pkg::burst_t burst);
    if ((len != '0) && (burst != axi_pkg::BURST_INCR)) begin
      return SRAM_DEMUX_ERR_SLV;
    end else begin
      return SRAM_DEMUX_MEM;
    end
  endfunction

  always_comb begin
    sram_demux_aw_select = sram_demux_decode(sram_req.aw.len, sram_req.aw.burst);
    sram_demux_ar_select = sram_demux_decode(sram_req.ar.len, sram_req.ar.burst);
  end

  axi_demux #(
    .AxiIdWidth  (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .AtopSupport (1'b0),
    .aw_chan_t   (sep_pkg::sep_32_64_6_12_axi_aw_chan_t),
    .w_chan_t    (sep_pkg::sep_32_64_6_12_axi_w_chan_t),
    .b_chan_t    (sep_pkg::sep_32_64_6_12_axi_b_chan_t),
    .ar_chan_t   (sep_pkg::sep_32_64_6_12_axi_ar_chan_t),
    .r_chan_t    (sep_pkg::sep_32_64_6_12_axi_r_chan_t),
    .axi_req_t   (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t  (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .NoMstPorts  (NumSramDemuxPorts),
    .MaxTrans    (4),
    .AxiLookBits (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .UniqueIds   (1'b0),
    .SpillAw     (1'b0),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b0),
    .SpillR      (1'b0)
  ) u_sram_burst_demux (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .test_i          (test_en_i),
    .slv_req_i       (sram_req),
    .slv_resp_o      (sram_rsp),
    .slv_aw_select_i (sram_demux_aw_select),
    .slv_ar_select_i (sram_demux_ar_select),
    .sel_hash_i      ('0),
    .mst_reqs_o      (sram_demux_req),
    .mst_resps_i     (sram_demux_resp)
  );

  axi_err_slv #(
    .AxiIdWidth (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
    .axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .Resp       (axi_pkg::RESP_SLVERR),
    .ATOPs      (1'b0),
    .MaxTrans   (4)
  ) u_sram_burst_err_slv (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (test_en_i),
    .slv_req_i  (sram_demux_req[SRAM_DEMUX_ERR_SLV]),
    .slv_resp_o (sram_demux_resp[SRAM_DEMUX_ERR_SLV])
  );

  memory_interface #(
    .MEM_ADDR_WIDTH   (sep_pkg::SEP_MEM_ADDR_WIDTH),
    .MEM_DATA_WIDTH   (sep_pkg::SEP_MEM_DATA_WIDTH),
    .MEM_ID_WIDTH     (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
    .mem_req_t        (sep_pkg::sep_sram_req_t),
    .mem_rsp_t        (sep_pkg::sep_sram_rsp_t),
    .mem_axi_req_t    (sep_pkg::sep_32_64_6_12_axi_req_t),
    .mem_axi_resp_t   (sep_pkg::sep_32_64_6_12_axi_resp_t),
    .CSR_ADDR_WIDTH   (sep_pkg::SEP_32_64_6_12_ADDR_WIDTH),
    .CSR_DATA_WIDTH   (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
    .csr_axil_req_t   (sep_pkg::sep_axilite_xbar_req_t),
    .csr_axil_resp_t  (sep_pkg::sep_axilite_xbar_resp_t),
    .CSR_BASE_ADDR    (32'h0),
    .MEM_BASE_ADDR    (32'(sep_top_addrmap_pkg::SEP_TOP_SEP_SRAM_BASE_ADDR)),
    .NUM_BANKS        (1)
  ) u_sram_memory_interface (
    .clk_i                (clk_i),
    .rst_ni               (sep_reset_n),
    .mem_axi_req_i        (sram_demux_req[SRAM_DEMUX_MEM]),
    .mem_axi_resp_o       (sram_demux_resp[SRAM_DEMUX_MEM]),
    .csr_in_axil_req_i    ('0),
    .csr_in_axil_resp_o   (/* UNUSED */),
    .csr_out_axil_req_o   (/* UNUSED */),
    .csr_out_axil_resp_i  ('0),
    .mem_req_o            (sep_sram_req_o),
    .mem_rsp_i            (sep_sram_rsp_i),
    .busy_o               (/* UNUSED */)
  );

  //////////////////////////
  // ROM Memory Interface //
  //////////////////////////

  assign rom_mux_req[sep_pkg::SEP_ROM_MUX_PORT_IFU]  = ifu_rom_axi_req;
  assign ifu_rom_axi_resp                   = rom_mux_resp[sep_pkg::SEP_ROM_MUX_PORT_IFU];
  assign rom_mux_req[sep_pkg::SEP_ROM_MUX_PORT_LSU]  = lsu_rom_axi_req;
  assign lsu_rom_axi_resp                   = rom_mux_resp[sep_pkg::SEP_ROM_MUX_PORT_LSU];

  axi_mux #(
    .SlvAxiIDWidth (sep_pkg::SEP_32_64_3_12_ID_WIDTH),
    .slv_aw_chan_t (sep_pkg::sep_32_64_3_12_axi_aw_chan_t),
    .mst_aw_chan_t (sep_pkg::sep_32_64_4_12_axi_aw_chan_t),
    .w_chan_t      (sep_pkg::sep_32_64_3_12_axi_w_chan_t),
    .slv_b_chan_t  (sep_pkg::sep_32_64_3_12_axi_b_chan_t),
    .mst_b_chan_t  (sep_pkg::sep_32_64_4_12_axi_b_chan_t),
    .slv_ar_chan_t (sep_pkg::sep_32_64_3_12_axi_ar_chan_t),
    .mst_ar_chan_t (sep_pkg::sep_32_64_4_12_axi_ar_chan_t),
    .slv_r_chan_t  (sep_pkg::sep_32_64_3_12_axi_r_chan_t),
    .mst_r_chan_t  (sep_pkg::sep_32_64_4_12_axi_r_chan_t),
    .slv_req_t     (sep_pkg::sep_32_64_3_12_axi_req_t),
    .slv_resp_t    (sep_pkg::sep_32_64_3_12_axi_resp_t),
    .mst_req_t     (sep_pkg::sep_32_64_4_12_axi_req_t),
    .mst_resp_t    (sep_pkg::sep_32_64_4_12_axi_resp_t),
    .NoSlvPorts    (sep_pkg::SEP_ROM_MUX_NUM_PORTS),
    .MaxWTrans     (4),
    .FallThrough   (1'b0),
    .SpillAw       (1'b0),
    .SpillW        (1'b0),
    .SpillB        (1'b0),
    .SpillAr       (1'b0),
    .SpillR        (1'b0)
  ) u_boot_rom_axi_mux (
    .clk_i       (clk_i),
    .rst_ni      (sep_reset_n),
    .test_i      (test_en_i),
    .slv_reqs_i  (rom_mux_req),
    .slv_resps_o (rom_mux_resp),
    .mst_req_o   (rom_axi_req),
    .mst_resp_i  (rom_axi_resp)
  );

  memory_interface #(
    .MEM_ADDR_WIDTH   (sep_pkg::SEP_MEM_ADDR_WIDTH),
    .MEM_DATA_WIDTH   (sep_pkg::SEP_MEM_DATA_WIDTH),
    .MEM_ID_WIDTH     (sep_pkg::SEP_32_64_4_12_ID_WIDTH),
    .mem_req_t        (sep_pkg::sep_sram_req_t),
    .mem_rsp_t        (sep_pkg::sep_sram_rsp_t),
    .mem_axi_req_t    (sep_pkg::sep_32_64_4_12_axi_req_t),
    .mem_axi_resp_t   (sep_pkg::sep_32_64_4_12_axi_resp_t),
    .CSR_ADDR_WIDTH   (sep_pkg::SEP_32_64_4_12_ADDR_WIDTH),
    .CSR_DATA_WIDTH   (sep_pkg::SEP_32_64_4_12_DATA_WIDTH),
    .csr_axil_req_t   (sep_pkg::sep_axilite_xbar_req_t),
    .csr_axil_resp_t  (sep_pkg::sep_axilite_xbar_resp_t),
    .CSR_BASE_ADDR    (32'h0),
    .MEM_BASE_ADDR    (32'(sep_top_addrmap_pkg::SEP_TOP_SEP_BOOT_ROM_BASE_ADDR)),
    .NUM_BANKS        (1)
  ) u_boot_rom_memory_interface (
    .clk_i                (clk_i),
    .rst_ni               (sep_reset_n),
    .mem_axi_req_i        (rom_axi_req),
    .mem_axi_resp_o       (rom_axi_resp),
    .csr_in_axil_req_i    ('0),
    .csr_in_axil_resp_o   (/* UNUSED */),
    .csr_out_axil_req_o   (/* UNUSED */),
    .csr_out_axil_resp_i  ('0),
    .mem_req_o            (sep_boot_rom_req_o),
    .mem_rsp_i            (sep_boot_rom_rsp_i),
    .busy_o               (/* UNUSED */)
  );

  ///////////////////
  // Crypto Module //
  ///////////////////

  sep_crypto #(
    .LATCHED_MEM_RDATA (KM_LATCHED_MEM_RDATA),
    .MASKING_EN        (ABR_MASKING_EN),
    .SRAM_LATENCY      (ABR_SRAM_LATENCY),
    .EXT_TRNG_NUM_AXIS (EXT_TRNG_NUM_AXIS),
    .SEP_SEC_DISABLE_TOKEN (SEP_SEC_DISABLE_TOKEN)
  ) u_sep_crypto (
    .clk_i                        (clk_i),
    .rst_ni                       (rst_ni),

    .test_en_i                    (test_en_i),
    .scan_rst_ni                  (scan_rst_ni),

    .entropy_rosc_sample_clk_i              (entropy_rosc_sample_clk_i),

    // OTP debug AXI-Lite manager interface
    .axil_sep_otp_jtag_req_i                (axil_sep_otp_jtag_req_i),
    .axil_sep_otp_jtag_resp_o               (axil_sep_otp_jtag_resp_o),

    // Full AXI from local crossbar
    .sep_crypto_axi_req_i                   (sep_crypto_axi_req),
    .sep_crypto_axi_resp_o                  (sep_crypto_axi_resp),

    .efuse_shim_axi_req_i                   (efuse_shim_axi_req),
    .efuse_shim_axi_resp_o                  (efuse_shim_axi_resp),

    // Entropy source interrupt
    .entropy_source_irq_o                   (entropy_source_irq),

    // Native EDN endpoint routed to the fabric-level entropy-pool FIFO
    .entropy_pool_edn_req_i                 (entropy_pool_edn_req),
    .entropy_pool_edn_rsp_o                 (entropy_pool_edn_rsp),
    .trng_entropy_clear_o                   (trng_entropy_clear),

    // External TRNG AXI-Lite passthrough
    .ext_trng_axil_req_o                    (ext_trng_axil_req_o),
    .ext_trng_axil_resp_i                   (ext_trng_axil_resp_i),

    // External TRNG AXI-Stream
    .ext_trng_axis_req_i                    (ext_trng_axis_req_i),
    .ext_trng_axis_rsp_o                    (ext_trng_axis_rsp_o),

    // eFuse interface
    .efuse_bank_ctrl_req_o                  (efuse_bank_ctrl_req_o),
    .efuse_bank_ctrl_resp_i                 (efuse_bank_ctrl_resp_i),
    .efuse_shim_command_req_o               (efuse_shim_command_req_o),
    .efuse_shim_command_resp_i              (efuse_shim_command_resp_i),

    .sep_reset_ni                           (sep_reset_n),
    .sep_intermediate_reset_no              (sep_intermediate_reset_n),

    .secure_tm_req_i                        (secure_tm_req_i),
    .ext_boot_seq_done_i                    (ext_boot_seq_done_i),
    .security_disable_o                     (security_disable),
    .lc_state_o                             (lc_state_o),
    .feat_ctrl_o                            (feat_ctrl),
    .dbg_disable_o                          (dbg_disable_o),
    .sep_fuse_dft_disable_o                 (sep_fuse_dft_disable_o),
    .smc_fuse_dft_disable_o                 (smc_fuse_dft_disable_o),
    .lc_sigint_err_o                        (lc_sigint_err_o),
    .shadow_regs_o                          (),
    .fuse_sense_done_o                      (sep_fuse_sense_done_o),
    .secure_tm_o                            (secure_tm_o),

    // Key Manager interfaces
    .km_rom_mem_req_o                       (km_rom_mem_req_o),
    .km_rom_mem_rsp_i                       (km_rom_mem_rsp_i),
    .km_sram_mem_req_o                      (km_sram_mem_req_o),
    .km_sram_mem_rsp_i                      (km_sram_mem_rsp_i),
    .km_mbox_irq_to_sep_o                   (km_mbox_irq),
    .km_unrecoverable_err_o                 (km_unrecoverable_err),
    .km_recoverable_err_o                   (km_recoverable_err),

    .isolate_req_i                          (sep_crypto_isolate_req),
    .isolated_o                             (sep_crypto_isolated),
    .gated_rst_ni                           (sep_crypto_gated_rst_n),

    .lcc_demote_state_1_o                   (lcc_demote_state_1_o),
    .lcc_demote_state_2_o                   (lcc_demote_state_2_o),

    .ext_trng_src_sel_i                     (ext_trng_src_sel),
    .km_wipe_state_i                        (km_wipe_state),

    // Crypto subsystem interrupts
    .intr_hmac_done_o                       (intr_hmac_done),
    .intr_hmac_fifo_empty_o                 (intr_hmac_fifo_empty),
    .intr_hmac_err_o                        (intr_hmac_err),
    .intr_kmac_done_o                       (intr_kmac_done),
    .intr_kmac_fifo_empty_o                 (intr_kmac_fifo_empty),
    .intr_kmac_err_o                        (intr_kmac_err),
    .intr_cs_cmd_req_done_o                 (intr_cs_cmd_req_done),
    .intr_cs_entropy_req_o                  (intr_cs_entropy_req),
    .intr_cs_hw_inst_exc_o                  (intr_cs_hw_inst_exc),
    .intr_cs_fatal_err_o                    (intr_cs_fatal_err),
    .intr_edn_cmd_req_done_o                (intr_edn_cmd_req_done),
    .intr_edn_fatal_err_o                   (intr_edn_fatal_err),
    .intr_otbn_done_o                       (intr_otbn_done),
    .intr_abr_error_o                       (intr_abr_error),
    .intr_abr_notif_o                       (intr_abr_notif),

    .sep_crypto_pka_imem_sram_req_o         (sep_crypto_pka_imem_sram_req_o),
    .sep_crypto_pka_imem_sram_rsp_i         (sep_crypto_pka_imem_sram_rsp_i),
    .sep_crypto_pka_dmem_sram_req_o         (sep_crypto_pka_dmem_sram_req_o),
    .sep_crypto_pka_dmem_sram_rsp_i         (sep_crypto_pka_dmem_sram_rsp_i),

    .abr_mem_req_o                          (abr_mem_req_o),
    .abr_mem_rsp_i                          (abr_mem_rsp_i),

    .crypto_alert_o                         (crypto_alert),

    .sep_efuse_debug_o                      (sep_efuse_debug),
    .sep_efuse_token_match_sip_debug_o      (sep_efuse_token_match_sip_debug),
    .sep_efuse_token_match_chiplet_debug_o  (sep_efuse_token_match_chiplet_debug),

    .locked_field_access_interrupt_o        (locked_field_access_interrupt),

    .token_match_fault_o                    (token_match_fault),

    .aes_bus_err_o                          (periph_bus_err[sep_pkg::PERIPH_BUS_ERR_AES]),
    .hmac_bus_err_o                         (periph_bus_err[sep_pkg::PERIPH_BUS_ERR_HMAC]),
    .kmac_bus_err_o                         (periph_bus_err[sep_pkg::PERIPH_BUS_ERR_KMAC]),
    .otbn_bus_err_o                         (periph_bus_err[sep_pkg::PERIPH_BUS_ERR_OTBN]),
    .csrng_bus_err_o                        (periph_bus_err[sep_pkg::PERIPH_BUS_ERR_CSRNG]),
    .edn_bus_err_o                          (periph_bus_err[sep_pkg::PERIPH_BUS_ERR_EDN]),
    .aes_bus_err_clr_i                      (periph_bus_err_clr[sep_pkg::PERIPH_BUS_ERR_AES]),
    .hmac_bus_err_clr_i                     (periph_bus_err_clr[sep_pkg::PERIPH_BUS_ERR_HMAC]),
    .kmac_bus_err_clr_i                     (periph_bus_err_clr[sep_pkg::PERIPH_BUS_ERR_KMAC]),
    .otbn_bus_err_clr_i                     (periph_bus_err_clr[sep_pkg::PERIPH_BUS_ERR_OTBN]),
    .csrng_bus_err_clr_i                    (periph_bus_err_clr[sep_pkg::PERIPH_BUS_ERR_CSRNG]),
    .edn_bus_err_clr_i                      (periph_bus_err_clr[sep_pkg::PERIPH_BUS_ERR_EDN])
  );

  ///////////////
  // IO Module //
  ///////////////

  sep_io #(
    .NUM_COMPONENTS(1)
  ) u_sep_io (
    .clk_i             (clk_i),
    .rst_ni            (sep_reset_n),

    .test_en_i         (test_en_i),

    .sep_io_axi_req_i  (sep_io_axi_req),
    .sep_io_axi_resp_o (sep_io_axi_resp),

    .sep_io_spi_req_o  (sep_io_spi_req_o),
    .sep_io_spi_rsp_i  (sep_io_spi_rsp_i)
  );

  //////////////////////
  // Entropy-Pool FIFO //
  //////////////////////

  // Fabric-level entropy pool: filled by the native EDN endpoint routed out of
  // sep_crypto, drained read-only over a dedicated sep_local_axi_xbar output
  // (0x1095_0000). The aperture is read-only; writes return BRESP=SLVERR.
  sep_entropy_fifo u_entropy_fifo (
    .clk_i                    (clk_i),
    .rst_ni                   (rst_ni),
    .entropy_clear_i          (trng_entropy_clear),

    .test_en_i                (test_en_i),

    // Native EDN fill (HW pull from sep_crypto)
    .edn_req_o                (entropy_pool_edn_req),
    .edn_rsp_i                (entropy_pool_edn_rsp),

    // AXI-Lite read-only drain from the local xbar
    .entropy_fifo_axi_req_i   (entropy_fifo_axi_req),
    .entropy_fifo_axi_resp_o  (entropy_fifo_axi_resp),

    // Status / interrupts to the SEP PIC
    .pool_low_o               (entropy_pool_low),
    .fill_stall_o             (entropy_pool_fill_stall),
    .pool_err_o               (entropy_pool_err),
    .fifo_level_o             ()
  );

  ///////////////////////////////
  // System Peripherals Module //
  ///////////////////////////////

  sep_system_peripherals u_sep_system_peripherals (
    .clk_i                            (clk_i),
    .clk_ref_i                        (clk_ref_i),
    .rst_ni                           (sep_reset_n),
    .rst_warm_ni                      (sep_cpu_reset_n),

    .test_en_i                        (test_en_i),
    .scan_rst_ni                      (scan_rst_ni),
    .inbound_filter_skip_i            (feat_ctrl.sep_debug),    // 0: traverses inbound filter, 1: skips filter checking
    .outbound_filter_skip_i           (1'b0),                   // output filter is not affected by feature control

    // AXI4 Slave Interface
    .sep_system_peripheral_axi_req_i  (sep_system_peripherals_axi_req),
    .sep_system_peripheral_axi_resp_o (sep_system_peripherals_axi_resp),

    .smn_inbound_axi_req_i            (smn_inbound_axi_req_i),
    .smn_inbound_axi_resp_o           (smn_inbound_axi_resp_o),

    // AXI4 Master Interface
    .smn_inbound_to_sep_axi_req_o     (smn_inbound_to_sep_axi_req),
    .smn_inbound_to_sep_axi_resp_i    (smn_inbound_to_sep_axi_resp),

    .smn_outbound_axi_req_o           (smn_outbound_axi_req_o),
    .smn_outbound_axi_resp_i          (smn_outbound_axi_resp_i),

    .sep_ext_to_smc_axi_req_o         (sep_ext_to_smc_axi_req_o),
    .sep_ext_to_smc_axi_resp_i        (sep_ext_to_smc_axi_resp_i),

    // Address Remap Interface
    .local_masters_remap_debug_o      (local_masters_remap_debug),

    // Filter Interface
    .outbound_write_filter_hit_debug_o (outbound_write_filter_hit_debug),
    .outbound_read_filter_hit_debug_o  (outbound_read_filter_hit_debug),
    .inbound_write_filter_hit_debug_o  (inbound_write_filter_hit_debug),
    .inbound_read_filter_hit_debug_o   (inbound_read_filter_hit_debug),

    // Mailbox Interface
    .mailbox_inbound_interrupt_o      (sep_mailbox_interrupt),
    .mailbox_outbound_interrupt_o     (smc_mailbox_interrupt_o),

    // SEP System CSR Interface
    .smc_fuse_sense_done_i            (smc_fuse_sense_done_i),
    .sep_fuse_sense_done_i            (sep_fuse_sense_done_o),


    .nmi_vec_o                        (nmi_vec),

    .smc_global_base_addr_i           (smc_global_base_addr_i),
    .smc_region_size_i                (smc_region_size_i),

    .sep_local_base_addr_o            (sep_local_base_addr),
    .sep_global_base_addr_o           (sep_global_base_addr),
    .sep_region_size_o                (sep_region_size),

    .ext_trng_src_sel_o               (ext_trng_src_sel),
    .km_wipe_state_o                  (km_wipe_state),

    .dma_reg_bus_err_i                (dma_reg_bus_err),
    .dma_host_intg_err_i              (dma_host_intg_err),
    .dma_err_clr_o                    (dma_err_clr),

    .periph_bus_err_i                 (periph_bus_err),
    .periph_bus_err_clr_o             (periph_bus_err_clr)
  );

  /////////
  // WDT //
  /////////

  sep_wdt_wrap u_sep_wdt_wrap (
    .clk_i                   (clk_i),
    .clk_wdt_i               (clk_wdt_i),
    .rst_ni                  (rst_ni),
    .test_en_i               (test_en_i),
    .scan_rst_ni             (scan_rst_ni),
    .sep_wdt_axi_req_i       (sep_wdt_axi_req),
    .sep_wdt_axi_resp_o      (sep_wdt_axi_resp),
    .intr_wdog_timer_bark_o  (intr_wdog_timer_bark),
    .wdt_timer_rst_req_o     (wdt_timer_rst_req),
    .wdt_alert_o             (wdt_alert),
    .wdt_debug_sleep_mode_i  (wdt_debug_sleep_mode),
    .bus_err_o               (periph_bus_err[sep_pkg::PERIPH_BUS_ERR_WDT]),
    .bus_err_clr_i           (periph_bus_err_clr[sep_pkg::PERIPH_BUS_ERR_WDT])
  );

  //////////////////////
  // Reset Controller //
  //////////////////////

  sep_reset_ctrl u_sep_reset_ctrl (
    .clk_i                      (clk_i),
    .rst_ni                     (rst_ni),
    .wdt_rst_ni                 (wdt_rst_ni),
    .jtag_sep_reset_ctrl_i      (jtag_sep_reset_ctrl_i),
    .sep_intermediate_reset_ni  (sep_intermediate_reset_n),
    .sep_reset_no               (sep_reset_n),
    .sep_reset_ctrl_axi_req_i   (sep_reset_ctrl_axi_req),
    .sep_reset_ctrl_axi_resp_o  (sep_reset_ctrl_axi_resp),
    .test_en_i                  (test_en_i),
    .scan_rst_ni                (scan_rst_ni),
    .sep_cpu_reset_no           (sep_cpu_reset_n),
    .sep_crypto_isolate_req_o   (sep_crypto_isolate_req),
    .sep_crypto_isolated_i      (sep_crypto_isolated),
    .sep_crypto_gated_rst_no    (sep_crypto_gated_rst_n)
  );

  ////////////////
  // Secure DMA //
  ////////////////

  secure_dma_pkg::lsio_trigger_t lsio_trigger;
  assign lsio_trigger[0] = sep_io_spi_req_o.lsio_trigger;
  // Only the SPI LSIO trigger (bit 0) is currently used; tie off the remaining
  assign lsio_trigger[$bits(lsio_trigger)-1:1] = '0;

  sep_dma_wrap #(
    .SECURE_DMA_REG_MAP_BASE_ADDR (32'(sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_BASE_ADDR)),
    .ALERT_ASYNC_ON             ({secure_dma_reg_pkg::NumAlerts{1'b0}}),
    .ALERT_SKEW_CYCLES          (1'b0),
    .ENABLE_DATA_INTG_GEN       (1'b1),  // ENABLE integrity generation (was 1'b0)
    .ENABLE_RSP_DATA_INTG_CHECK (1'b1),  // ENABLE integrity checking (was 1'b0)
    .TL_USER_RSVD               ('0),
    .SYS_RACL_ROLE              ('0),
    .OT_AGENT_ID                ('0),
    .ENABLE_RACL                (1'b0),
    .RACL_ERROR_RSP             (1'b0),
    .RACL_POLICY_SEL_VEC        ('{secure_dma_reg_pkg::NumRegs{0}})
  ) u_sep_dma_wrap (
    .clk_i,
    .rst_ni                 (sep_reset_n),
    .test_en_i              (test_en_i),
    .lsio_trigger_i         (lsio_trigger),
    .intr_dma_done_o        (intr_dma_done),
    .intr_dma_chunk_done_o  (intr_dma_chunk_done),
    .intr_dma_error_o       (intr_dma_error),
    .dma_alert_o            (dma_alert),
    .dma_reg_bus_err_o      (dma_reg_bus_err),
    .dma_host_intg_err_o    (dma_host_intg_err),
    .dma_err_clr_i          (dma_err_clr),
    .reg_req_i              (dma_csr_req),
    .reg_resp_o             (dma_csr_rsp),
    .dma_req_o              (dma_axi_req),
    .dma_resp_i             (dma_axi_resp),
    .sep_local_base_addr_i  (sep_local_base_addr[31:0])
  );

  assign wdt_timer_rst_req_o  = wdt_timer_rst_req;
  assign security_disable_o   = security_disable;

  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(
      ExtDebugCpuStatusLaneWidth_A, $bits
      ({sep_cpu_trace_o.trace_rv_i_valid_ip, sep_cpu_trace_o.trace_rv_i_exception_ip, sep_cpu_trace_o.trace_rv_i_interrupt_ip, 13'b0}
          ) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(
      ExtDebugEccPerfLaneWidth_A, $bits
      ({cpu_iccm_ecc_single_error, cpu_iccm_ecc_double_error, cpu_dccm_ecc_single_error, cpu_dccm_ecc_double_error, cpu_dec_tlu_perfcnt0, cpu_dec_tlu_perfcnt1, cpu_dec_tlu_perfcnt2, cpu_dec_tlu_perfcnt3, 8'b0}
          ) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(
      ExtDebugInterruptLaneWidth_A, $bits
      ({intr_wdog_timer_bark, sep_mailbox_interrupt, km_mbox_irq, entropy_source_irq, ext_trng_irq, intr_dma_done, intr_dma_chunk_done, intr_dma_error, 1'b0}
          ) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugResetStatusLaneWidth_A, $bits
                                    ({sep_reset_n, wdt_timer_rst_req, security_disable, 13'b0})
                                    == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugTraceAddressLaneWidth_A, $bits
                                    (sep_cpu_trace_o.trace_rv_i_address_ip[15:0]) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugTraceInsnLaneWidth_A, $bits
                                    (sep_cpu_trace_o.trace_rv_i_insn_ip[15:0]) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(
      ExtDebugTraceExceptionLaneWidth_A, $bits
      ({sep_cpu_trace_o.trace_rv_i_ecause_ip[3:0], sep_cpu_trace_o.trace_rv_i_tval_ip[11:0]}) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(
      ExtDebugControlLaneWidth_A, $bits
      ({8'b0, cpu_run_ack_o, debug_mode_status_o, cpu_halt_status_o, cpu_halt_ack_o, 1'b0, debug_brkpt_status, mpc_debug_run_ack, mpc_debug_halt_ack}
          ) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugEfuseLaneWidth_A, $bits({6'b0, sep_efuse_debug}) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugSipTokenLaneWidth_A, $bits
                                    ({10'b0, sep_efuse_token_match_sip_debug}) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugChipletTokenLaneWidth_A, $bits
                                    ({10'b0, sep_efuse_token_match_chiplet_debug}) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugRemapLaneWidth_A, $bits
                                    ({8'b0, local_masters_remap_debug}) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(
      ExtDebugOutboundFilterLaneWidth_A, $bits
      ({{(16 - 2 * $clog2(sep_pkg::OutboundFilterNumFilters)
       ) {1'b0}}, outbound_write_filter_hit_debug, outbound_read_filter_hit_debug}) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(
      ExtDebugInboundFilterLaneWidth_A, $bits
      ({{(16 - 2 * $clog2(sep_pkg::InboundFilterNumFilters)
       ) {1'b0}}, inbound_write_filter_hit_debug, inbound_read_filter_hit_debug}) == 16)
  `OCAH_OT_ASSERT_STATIC_LINT_ERROR(ExtDebugReservedLanesWidth_A, $bits(160'b0) == 10 * 16)

  // External debug bus assignment (24 lanes, 16 bits per lane)
  assign ext_debug_bus_o = {
    // [383:368] CPU trace valid and exception
    sep_cpu_trace_o.trace_rv_i_valid_ip,
    sep_cpu_trace_o.trace_rv_i_exception_ip,
    sep_cpu_trace_o.trace_rv_i_interrupt_ip,
    13'b0,

    // [367:352] ECC errors and performance counters
    cpu_iccm_ecc_single_error,
    cpu_iccm_ecc_double_error,
    cpu_dccm_ecc_single_error,
    cpu_dccm_ecc_double_error,
    cpu_dec_tlu_perfcnt0,
    cpu_dec_tlu_perfcnt1,
    cpu_dec_tlu_perfcnt2,
    cpu_dec_tlu_perfcnt3,
    8'b0,

    // [351:336] Seven scalar interrupts, eight mailbox interrupts, one reserved bit
    intr_wdog_timer_bark,
    sep_mailbox_interrupt,
    km_mbox_irq,
    entropy_source_irq,
    ext_trng_irq,
    intr_dma_done,
    intr_dma_chunk_done,
    intr_dma_error,
    1'b0,  // [336] Reserved

    // [335:320] Reset and security status
    sep_reset_n,
    wdt_timer_rst_req,
    security_disable,
    13'b0,

    // [319:304] CPU trace instruction address [15:0]
    sep_cpu_trace_o.trace_rv_i_address_ip[15:0],

    // [303:288] CPU trace instruction [15:0]
    sep_cpu_trace_o.trace_rv_i_insn_ip[15:0],

    // [287:272] CPU trace ecause and tval [15:0]
    {
      sep_cpu_trace_o.trace_rv_i_ecause_ip[3:0], sep_cpu_trace_o.trace_rv_i_tval_ip[11:0]
    },

    // [271:256] Debug control signals
    8'b0,  // [271:264] Reserved padding
    cpu_run_ack_o,  // [263]
    debug_mode_status_o,  // [262]
    cpu_halt_status_o,  // [261]
    cpu_halt_ack_o,  // [260]
    1'b0,
    debug_brkpt_status,  // [258]
    mpc_debug_run_ack,  // [257]
    mpc_debug_halt_ack,  // [256]

    // [255:240] SEP eFuse debug
    6'b0,  // [255:250] Reserved padding
    sep_efuse_debug,  // [249:240]

    // [239:224] SEP eFuse RMA SiP token match debug
    10'b0,  // [239:230] Reserved padding
    sep_efuse_token_match_sip_debug,  // [229:224]

    // [223:208] SEP eFuse RMA chiplet token match debug
    10'b0,  // [223:214] Reserved padding
    sep_efuse_token_match_chiplet_debug,  // [213:208]

    // [207:192] Local masters address-remap hit debug
    8'b0,  // [207:200] Reserved padding
    local_masters_remap_debug,  // [199:192]

    // [191:176] Outbound filter hit debug
    {(16 - 2 * $clog2(
        sep_pkg::OutboundFilterNumFilters
    )) {1'b0}},
    outbound_write_filter_hit_debug,
    outbound_read_filter_hit_debug,

    // [175:160] Inbound filter hit debug
    {(16 - 2 * $clog2(
        sep_pkg::InboundFilterNumFilters
    )) {1'b0}},
    inbound_write_filter_hit_debug,
    inbound_read_filter_hit_debug,

    // [159:0] Reserved for future use
    160'b0
  };

endmodule
