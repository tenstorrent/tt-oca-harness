// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Integrate the Key Manager CPU, memories, peripherals and crypto master ports into one
// hierarchical block.
//
// Components:
//
// - PicoRV32 CPU with direct ROM/SRAM memory interfaces
// - AXI-Lite crossbar for internal peripheral access
// - KMCSR (control/status registers) with IRQ aggregation
// - Mailbox for bidirectional SEP-KM communication
// - DRBG sampler for random number acquisition
// - KPV (Key and Policy Vault) for key storage
// - External crypto engine master ports (OTBN, AES, KMAC, HMAC, Adams Bridge) and the
//   OTP/eFuse master
//
// km_reset_conditioner conditions reset internally and produces two clean resets:
//
// - Cold (AASD, rst_cold_aasd_no): resets all KM components; source is cold_rst_ni.
// - Warm (synchronous, rst_warm_sync_no): resets the CPU, the internal AXI fabric and the
//   warm KMCSR/KPV/DRBG/mailbox fields; sources are warm_rst_ni, soft_rst_n from KMCSR
//   and cold reset.
//
// LATCHED_MEM_RDATA is 1 when ROM/SRAM latch read data, so it stays valid after the
// request deasserts, and 0 when read data is valid only while rvalid is asserted. Setting
// it lets the CPU use look-ahead optimization when the memory supports it.
//
// OTP_EFUSE_REMAP_BASE is the absolute address of the eFuse controller as seen on
// efuse_req_o. Transactions from the internal OTP crossbar port (xbar port 8, KM-local
// 0x0001_1xxx) have their upper 20 bits replaced with OTP_EFUSE_REMAP_BASE[31:12] before
// being driven onto efuse_req_o; the lower 12 bits (register offset) are preserved. The
// integrator sets it to the system-level address of the eFuse controller and must connect
// efuse_req_o/efuse_resp_i to that controller.
//
// The ROM and SRAM hard macros are instantiated at integration level and connect through
// the exposed memory ports.

module key_manager
  import km_intf_pkg::*;
  import axi_pkg::*;
  import prim_mubi_pkg::*;
#(
  parameter int unsigned ROM_SIZE_BYTES   = 16384,          // ROM size in bytes (16 KB).
  parameter int unsigned SRAM_SIZE_BYTES  = 32768,          // SRAM size in bytes (32 KB).
  parameter int unsigned MAILBOX_DEPTH    = 16,             // Words per mailbox FIFO
                                                            // direction.
  parameter bit          LATCHED_MEM_RDATA = 1'b0,          // 1 if ROM/SRAM latch read data;
                                                            // enables look-ahead.
  parameter km_addr_t OTP_EFUSE_REMAP_BASE = 32'h1093_0000  // Absolute eFuse controller
                                                            // address on efuse_req_o;
                                                            // replaces addr[31:12].
) (
  input  logic   clk_i,        // System clock.
  input  logic   cold_rst_ni,  // Cold reset, asynchronous active-low.
  input  logic   warm_rst_ni,  // Warm reset, synchronous active-low.

  input  km_axil_req_t mbox_sep_req_i,    // Mailbox AXI4-Lite slave request from the SEP
                                          // host, which sends and receives messages to and
                                          // from KM here.
  output km_axil_resp_t mbox_sep_resp_o,  // Mailbox AXI4-Lite slave response to the SEP host.

  output logic        mbox_irq_to_sep_o,  // Mailbox interrupt: outbound data available
                                          // (KM→SEP).

  output logic        unrecoverable_err_o,  // Active-high: KM is in trap state (no longer
                                            // executing).
  output logic        recoverable_err_o,    // Recoverable fault occurred (KMCSR register bit).

  output km_axil_req_t  otbn_req_o,   // External crypto AXI4-Lite master to OTBN (Big Number
                                      // Accelerator).
  input  km_axil_resp_t otbn_resp_i,  // AXI4-Lite response from OTBN.

  output km_axil_req_t  aes_req_o,   // External crypto AXI4-Lite master to the AES
                                     // accelerator.
  input  km_axil_resp_t aes_resp_i,  // AXI4-Lite response from the AES accelerator.

  output km_axil_req_t  kmac_req_o,   // External crypto AXI4-Lite master to the KMAC
                                      // accelerator.
  input  km_axil_resp_t kmac_resp_i,  // AXI4-Lite response from the KMAC accelerator.

  output km_axil_req_t  hmac_req_o,   // External crypto AXI4-Lite master to the HMAC
                                      // accelerator.
  input  km_axil_resp_t hmac_resp_i,  // AXI4-Lite response from the HMAC accelerator.

  output km_axil_req_t  abr_req_o,   // External crypto AXI4-Lite master to the Adams Bridge
                                     // accelerator.
  input  km_axil_resp_t abr_resp_i,  // AXI4-Lite response from the Adams Bridge accelerator.

  input  logic abr_mlkem_sharedkey_irq_i,  // Adams Bridge ML-KEM shared-key valid IRQ
                                           // (level-sensitive, active-high).

  output km_axil_req_t  efuse_req_o,   // OTP/eFuse AXI-Lite master from xbar port 8, remapped
                                       // to OTP_EFUSE_REMAP_BASE.
  input  km_axil_resp_t efuse_resp_i,  // AXI-Lite response from the system eFuse controller.

  output km_rom_mem_req_t  rom_mem_req_o,  // Request to the ROM hard macro.
  input  km_rom_mem_rsp_t rom_mem_rsp_i,   // Response from the ROM hard macro.

  output km_sram_mem_req_t sram_mem_req_o,  // Request to the SRAM hard macro.
  input  km_sram_mem_rsp_t sram_mem_rsp_i,  // Response from the SRAM hard macro.

  input  km_drbg_axis_req_t drbg_axis_req_i,    // DRBG AXI-Stream request (KM is slave, DRBG
                                                // is master).
  output km_drbg_axis_resp_t drbg_axis_resp_o,  // DRBG AXI-Stream response.

  input  km_otp_data_t otp_data_i,  // Differentially encoded SEP OTP data.

  input  logic    wipe_state_i,  // Wipe state. A rising edge sets IRQ_STATUS.WIPE_STATE and
                                 // zeros the entire KPV on the next cycle.

  input  logic   test_en_i,   // DFT test-enable.
  input  logic   scan_rst_ni  // Scan reset, active-low; bypasses the reset synchronizer.
);

  `include "prim_assert.sv"

  //=========================================================================
  // Parameter Validation
  //=========================================================================
  // Validate parameters at elaboration.

  // Pinned against the address map rather than a literal: the memory sizes and
  // the decode ranges have to agree, and the map is the one that also feeds the
  // write-lock and exec region indices.
  `OCAH_OT_ASSERT_INIT(RomSizeValid_A, ROM_SIZE_BYTES == km_intf_pkg::ROM_SIZE_BYTES)
  `OCAH_OT_ASSERT_INIT(SramSizeValid_A, SRAM_SIZE_BYTES == km_intf_pkg::SRAM_SIZE_BYTES)
  `OCAH_OT_ASSERT_INIT(MailboxDepthMin_A, MAILBOX_DEPTH >= 16)
  `OCAH_OT_ASSERT_INIT(MailboxDepthPow2_A, (MAILBOX_DEPTH & (MAILBOX_DEPTH - 1)) == 0)

  //=========================================================================
  // Internal Signals
  //=========================================================================

  // Reset signals
  logic soft_rst_n;       // Soft reset from KMCSR (active-low, asserted on code match)
  logic rst_cold_aasd_n;  // Cold reset output from conditioner (AASD, for all-KM reset)
  logic rst_warm_sync_n;  // Warm reset output from conditioner (synchronous, for CPU + fabric)

  // CPU AXI-Lite master interface (for peripherals via crossbar)
  km_axil_req_t  cpu_axil_req;
  km_axil_resp_t cpu_axil_resp;

  // CPU IRQ inputs
  logic cpu_irq;       // KMCSR aggregated (sticky error sources)
  logic cpu_mbox_irq;  // Mailbox inbound (direct level)

  // ROM/SRAM parity errors (from CPU wrapper)
  logic cpu_rom_parity_err;
  logic cpu_sram_parity_err;
  logic cpu_rom_write_err;  // ROM write attempt detected

  // Scrambler control (from KMCSR to SRAM interface)
  logic [31:0] scrambler_key;
  logic        scrambler_enable;
  logic        scrambler_lock;

  // SRAM write-lock (from KMCSR to CPU/SRAM) and violation (from CPU to KMCSR)
  logic [31:0] sram_lock_bits;
  logic [31:0] sram_write_lock_violation_region;

  // Execute-permission whitelist mode (from KMCSR to CPU) and violation (from CPU to KMCSR)
  logic        sram_exec_mode;
  logic        exec_violation;

  // ROM lockout violation (from CPU to KMCSR)
  logic        rom_access_violation;

  // Crossbar slave port (from CPU)
  km_axil_req_t  xbar_slv_req;
  km_axil_resp_t xbar_slv_resp;

  // Crossbar master ports (to peripherals)
  km_axil_req_t  kpv_req;
  km_axil_resp_t kpv_resp;
  km_axil_req_t  kmcsr_req;
  km_axil_resp_t kmcsr_resp;
  km_axil_req_t  mbox_req;
  km_axil_resp_t mbox_resp;
  km_axil_req_t  drbg_req;
  km_axil_resp_t drbg_resp;
  // OTP/eFuse crossbar master port (index 8); wired to efuse_req_o with remap
  km_axil_req_t  otp_axil_req;
  km_axil_resp_t otp_axil_resp;


  // KMCSR hardware inputs
  logic        mbox_irq_to_km;
  logic        drbg_error;

  // Wipe: rising-edge detect to one-cycle pulse
  logic        wipe_event_d;
  logic        wipe_event;
  logic        wipe_pulse;

  // CPU trap output (unrecoverable: KM no longer executing)
  logic cpu_trap;

  // KMCSR IRQ aggregation output
  logic km_irq;

  // KMCSR → CPU: runtime IRQ vector (reset default 0x10 via register reset)
  logic [31:0] irq_entry_addr;

  //=========================================================================
  // Reset Conditioning
  //=========================================================================
  // Dual reset generation.
  //   Cold path (rst_cold_aasd_no): AASD, all KM components.
  //   Warm path (rst_warm_sync_no): synchronous, CPU + internal AXI fabric.
  //   Warm sources: cold reset deasserted, warm_rst_ni, or soft_rst_n from KMCSR.

  km_reset_conditioner #(
    .MIN_RESET_CYCLES(10)
  ) u_reset_conditioner (
    .clk_i          (clk_i),
    .cold_rst_ni    (cold_rst_ni),    // Async cold reset (AASD source)
    .soft_rst_ni    (soft_rst_n),     // Soft reset (from KMCSR; sync to clk_i)
    .warm_rst_ni    (warm_rst_ni),    // Warm reset (synchronous, active-low)
    .scan_rst_ni    (scan_rst_ni),
    .scanmode_i     (prim_mubi_pkg::mubi4_bool_to_mubi(test_en_i)),
    .rst_cold_aasd_no(rst_cold_aasd_n),
    .rst_warm_sync_no(rst_warm_sync_n)
  );

  // Wipe KPV on either external wipe_state_i or CPU trap.
  // Pulse once on rising edge to avoid repeated full-regfile clears.
  assign wipe_event = wipe_state_i | cpu_trap;
  always_ff @(posedge clk_i or negedge rst_cold_aasd_n) begin
    if (!rst_cold_aasd_n) wipe_event_d <= 1'b0;
    else wipe_event_d <= wipe_event;
  end
  assign wipe_pulse = wipe_event & ~wipe_event_d;

  //=========================================================================
  // CPU Wrapper Instance
  //=========================================================================

  // AXI bus error outputs from CPU wrapper
  logic cpu_axi_slverr;
  logic cpu_axi_decerr;

  picorv32_wrapper #(
    .axil_req_t (km_axil_req_t),
    .axil_resp_t(km_axil_resp_t),
    .LATCHED_MEM_RDATA(LATCHED_MEM_RDATA)
  ) u_cpu (
    .clk_i              (clk_i),
    .rst_ni             (rst_cold_aasd_n),  // AASD cold reset (memory interfaces, parity)
    .rst_sync_ni        (rst_warm_sync_n),  // Synchronous warm reset (PicoRV32 CPU core)
    // ROM interface (exposed at top level, with parity checking)
    // The CPU wrapper internally instantiates km_rom_interface
    .rom_mem_req_o      (rom_mem_req_o),
    .rom_mem_rsp_i      (rom_mem_rsp_i),
    .rom_parity_err_o   (cpu_rom_parity_err),
    .rom_write_err_o    (cpu_rom_write_err),
    // SRAM interface (exposed at top level, with scrambling and parity checking)
    // The CPU wrapper internally instantiates km_sram_interface
    .sram_mem_req_o     (sram_mem_req_o),
    .sram_mem_rsp_i     (sram_mem_rsp_i),
    .sram_parity_err_o  (cpu_sram_parity_err),
    // Scrambler control (from KMCSR)
    .scrambler_key_i    (scrambler_key),
    .scrambler_en_i     (scrambler_enable),
    // SRAM write-lock (from KMCSR)
    .sram_lock_bits_i   (sram_lock_bits),
    .sram_write_lock_violation_region_o (sram_write_lock_violation_region),
    // Execute-permission whitelist (from/to KMCSR)
    .sram_exec_mode_i   (sram_exec_mode),
    .exec_violation_o   (exec_violation),
    .rom_access_violation_o (rom_access_violation),
    // AXI interface for peripherals only
    .axi_mst_req_o      (cpu_axil_req),
    .axi_mst_resp_i     (cpu_axil_resp),
    .irq_i              (cpu_irq),
    .mbox_irq_i         (cpu_mbox_irq),
    .abr_sharedkey_irq_i (abr_mlkem_sharedkey_irq_i),
    .irq_entry_addr_i   (irq_entry_addr),
    .trap_o             (cpu_trap),
    // AXI bus error outputs
    .axi_slverr_o       (cpu_axi_slverr),
    .axi_decerr_o       (cpu_axi_decerr)
  );

  // Connect CPU AXI master to crossbar slave port
  assign xbar_slv_req = cpu_axil_req;
  assign cpu_axil_resp = xbar_slv_resp;

  // Connect CPU IRQs: KMCSR aggregated errors + direct mailbox level
  assign cpu_irq     = km_irq;
  assign cpu_mbox_irq = mbox_irq_to_km;

  // Error condition outputs: unrecoverable = CPU trap; recoverable = KMCSR register
  assign unrecoverable_err_o = cpu_trap;

  // Remap xbar OTP port (index 8) to the integrator-supplied base address.
  // The crossbar delivers KM-local offsets (0x0001_1xxx); replace addr[31:12]
  // with OTP_EFUSE_REMAP_BASE[31:12] so the eFuse controller receives the
  // absolute address it was instantiated at.
  always_comb begin
    efuse_req_o         = otp_axil_req;
    efuse_req_o.aw.addr = {OTP_EFUSE_REMAP_BASE[31:12], otp_axil_req.aw.addr[11:0]};
    efuse_req_o.ar.addr = {OTP_EFUSE_REMAP_BASE[31:12], otp_axil_req.ar.addr[11:0]};
  end
  assign otp_axil_resp = efuse_resp_i;


  //=========================================================================
  // AXI-Lite Crossbar Instance
  //=========================================================================

  km_axi_lite_xbar #(
    .axil_req_t (km_axil_req_t),
    .axil_resp_t(km_axil_resp_t)
  ) u_xbar (
    .clk_i          (clk_i),
    .rst_ni          (rst_warm_sync_n),  // Warm reset to quiesce internal AXI fabric
    .test_i          (test_en_i),
    // Slave port: from CPU
    .slv_req_i       (xbar_slv_req),
    .slv_resp_o      (xbar_slv_resp),
    // Master ports: to peripherals
    .kpv_req_o       (kpv_req),
    .kpv_resp_i      (kpv_resp),
    .kmcsr_req_o     (kmcsr_req),
    .kmcsr_resp_i    (kmcsr_resp),
    .drbg_req_o      (drbg_req),
    .drbg_resp_i     (drbg_resp),
    .mbox_req_o      (mbox_req),
    .mbox_resp_i     (mbox_resp),
    // External crypto engine ports
    .otbn_req_o      (otbn_req_o),
    .otbn_resp_i     (otbn_resp_i),
    .aes_req_o       (aes_req_o),
    .aes_resp_i      (aes_resp_i),
    .kmac_req_o      (kmac_req_o),
    .kmac_resp_i     (kmac_resp_i),
    .hmac_req_o      (hmac_req_o),
    .hmac_resp_i     (hmac_resp_i),
    .abr_req_o       (abr_req_o),
    .abr_resp_i      (abr_resp_i),
    // OTP/eFuse pass-through (index 8); addr remap applied before efuse_req_o
    .otp_req_o       (otp_axil_req),
    .otp_resp_i      (otp_axil_resp)
  );

  //=========================================================================
  // DRBG Sampler Instance
  //=========================================================================

  km_drbg_sampler #(
    .axil_req_t (km_axil_req_t),
    .axil_resp_t(km_axil_resp_t)
  ) u_drbg_sampler (
    .clk_i           (clk_i),
    .cold_rst_ni     (rst_cold_aasd_n),
    .warm_rst_ni     (rst_warm_sync_n),
    .axil_req_i      (drbg_req),
    .axil_resp_o     (drbg_resp),
    .drbg_axis_req_i (drbg_axis_req_i),
    .drbg_axis_resp_o(drbg_axis_resp_o),
    .drbg_error_o    (drbg_error)
  );

  //=========================================================================
  // KPV Instance (Key and Policy Vault)
  //=========================================================================

  km_kpv #(
    .axil_req_t  (km_axil_req_t),
    .axil_resp_t (km_axil_resp_t)
  ) u_kpv (
    .clk_i          (clk_i),
    .cold_rst_ni    (rst_cold_aasd_n),
    .warm_rst_ni    (rst_warm_sync_n),
    .km_axil_req_i  (kpv_req),
    .km_axil_resp_o (kpv_resp),
    .wipe_pulse_i   (wipe_pulse)
  );

  //=========================================================================
  // Mailbox Instance
  //=========================================================================

  km_mailbox #(
    .MAILBOX_DEPTH(MAILBOX_DEPTH),
    .km_axil_req_t (km_axil_req_t),
    .km_axil_resp_t(km_axil_resp_t),
    .sep_axil_req_t (km_axil_req_t),  // SEP side uses the KM types
    .sep_axil_resp_t(km_axil_resp_t)
  ) u_mailbox (
    .clk_i              (clk_i),
    .cold_rst_ni        (rst_cold_aasd_n),
    .warm_rst_ni        (rst_warm_sync_n),
    .test_en_i          (test_en_i),
    // KM CPU AXI4-Lite Slave Interface (from crossbar)
    .km_axil_req_i      (mbox_req),
    .km_axil_resp_o     (mbox_resp),
    // SEP Host AXI4-Lite Slave Interface (from top level)
    .sep_axil_req_i     (mbox_sep_req_i),
    .sep_axil_resp_o    (mbox_sep_resp_o),
    // Interrupt Outputs
    .mbox_irq_to_km_o   (mbox_irq_to_km),
    .mbox_irq_to_sep_o  (mbox_irq_to_sep_o)
  );

  //=========================================================================
  // KMCSR Instance
  //=========================================================================

  km_csr #(
    .axil_req_t (km_axil_req_t),
    .axil_resp_t(km_axil_resp_t)
  ) u_kmcsr (
    .clk_i              (clk_i),
    .cold_rst_ni        (rst_cold_aasd_n),
    .warm_rst_ni        (rst_warm_sync_n),
    // AXI4-Lite Slave Interface (from crossbar)
    .axil_req_i         (kmcsr_req),
    .axil_resp_o         (kmcsr_resp),
    // IRQ Event Inputs
    .rom_parity_err_i   (cpu_rom_parity_err),
    .sram_parity_err_i  (cpu_sram_parity_err),
    .rom_write_err_i    (cpu_rom_write_err),
    .axi_slverr_i       (cpu_axi_slverr),
    .axi_decerr_i       (cpu_axi_decerr),
    .drbg_err_i         (drbg_error),
    .wipe_state_i       (wipe_pulse),
    // Scrambler Control Outputs
    .scrambler_key_o    (scrambler_key),
    .scrambler_enable_o (scrambler_enable),
    .scrambler_lock_o   (scrambler_lock),
    // SRAM write-lock outputs and violation input
    .sram_lock_bits_o   (sram_lock_bits),
    .sram_write_lock_violation_region_i(sram_write_lock_violation_region),
    // Execute-permission whitelist mode output and violation input
    .sram_exec_mode_o   (sram_exec_mode),
    .exec_violation_i   (exec_violation),
    .rom_access_violation_i (rom_access_violation),
    // Aggregated IRQ Output (to CPU)
    .km_irq_o           (km_irq),
    .irq_entry_addr_o   (irq_entry_addr),
    // Soft Reset Output (active-low: 0 = reset, 1 = normal)
    .soft_rst_o         (soft_rst_n),
    // Recoverable error event output
    .recoverable_err_o  (recoverable_err_o),
    // Virtual UART Interface (directly probed by testbench)
    // Outputs are unconnected (testbench probes register values)
    // Inputs tied off (testbench can force values if needed)
    .vuart_tx_data_o    (),
    .vuart_tx_valid_o   (),
    .vuart_rx_data_i    (8'h00),
    .vuart_rx_valid_i   (1'b0),
    // Test Protocol Interface (directly probed by testbench)
    // Outputs are unconnected (testbench probes register values)
    // Inputs tied off (testbench writes via interface)
    .tb_result_o        (),
    .tb_signature_o     (),
    .tb_errcode_o       (),
    .tb_subtest_o       (),
    .tb_cmd_o           (),
    .tb_cmd_arg_o       (),
    .tb_cmd_next_i      (32'h0),
    .tb_cmd_status_i    (32'h0),
    .tb_cmd_result_i    (32'h0),
    // SEP OTP Data Interface
    .otp_data_i         (otp_data_i)
  );

endmodule : key_manager

