// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

/**
 * @file km_csr.sv
 * @brief Key Manager Control/Status Register (KMCSR) wrapper.
 *
 * @details Wraps the PeakRDL-generated km_csr_reg block and adds custom
 *          hardware logic:
 *          - IRQ aggregation: combines the sticky interrupt sources (parity
 *            errors, bus errors, DRBG error, wipe, execute and ROM access
 *            violations) with per-source enable masking into a single CPU
 *            interrupt output.
 *          - Scrambler lock: implements write-once lock for SCRAMBLER_KEY and
 *            SCRAMBLER_CTRL registers (reads return zero when locked).
 *          - OTP data capture and read-through: OTP register values reflect
 *            captured differential values, with UID/CLASS_KEY isolation in
 *            secure test mode.
 *          - Soft reset: magic-code-guarded reset generation.
 *          - Virtual UART and test protocol register plumbing.
 *
 * @details Reset domains:
 *          - cold_rst_ni (AASD): resets the SRAM scrambler lock/key/enable
 *            (SCRAMBLER_CTRL.lock, SCRAMBLER_KEY), VUART edge detect, and the
 *            entire regblock via arst_n. Cold reset always implies warm reset.
 *          - warm_rst_ni (synchronous): resets soft_rst_q and the regblock CPUIF
 *            plus all warm-tagged fields via WARM_RST_N. Warm-tagged fields include
 *            IRQ_STATUS/IRQ_ENABLE/IRQ_SET, SOFT_RST_CODE, RECOVERABLE_ERR,
 *            SRAM_LOCK (write-lock bits), SRAM_LOCK violation bits,
 *            SRAM_EXEC_MODE (execute-permission whitelist mode),
 *            IRQ_ENTRY_ADDR/IRQ_ENTRY_LOCK, and the firmware test-bench registers.
 *            Warm reset breaks the soft reset trigger loop and quiesces the AXI
 *            CPUIF state machine.
 *
 * @param axil_req_t   AXI-Lite request struct type.
 * @param axil_resp_t  AXI-Lite response struct type.
 */

module km_csr
  import km_intf_pkg::*;
  import km_csr_reg_pkg::*;
  import axi_pkg::*;
#(
  // AXI-Lite interface types
  parameter type axil_req_t  = km_axil_req_t,
  parameter type axil_resp_t = km_axil_resp_t
) (
  // Clock and Reset
  input  logic clk_i,
  input  logic cold_rst_ni,   // Cold reset: async-assert/sync-deassert (AASD)
  input  logic warm_rst_ni,   // Warm reset: fully synchronous (from km_reset_conditioner)

  // AXI4-Lite Slave Interface (from crossbar)
  input  axil_req_t axil_req_i,
  output axil_resp_t axil_resp_o,

  // IRQ Event Inputs
  input  logic   rom_parity_err_i,    // ROM parity error (pulse)
  input  logic   sram_parity_err_i,   // SRAM parity error (pulse)
  input  logic   rom_write_err_i,     // ROM write attempt detected (pulse)
  input  logic   axi_slverr_i,        // AXI SLVERR error (pulse)
  input  logic   axi_decerr_i,        // AXI DECERR error (pulse)
  input  logic   drbg_err_i,         // DRBG Sampler error (pulse)
  input  logic   wipe_state_i,      // Wipe state event (rising edge sets IRQ)

  // Scrambler Control Outputs
  output logic [31:0] scrambler_key_o,      // Scrambler key (0 when locked)
  output logic        scrambler_enable_o,   // Scrambler enable
  output logic        scrambler_lock_o,     // Scrambler lock status

  // SRAM write-lock (to SRAM interface): bit[i]=1 locks region i. Write-1-only.
  output logic [31:0] sram_lock_bits_o,
  // SRAM write-lock violation (from SRAM interface): one-hot region that had attempted write while locked
  input  logic [31:0] sram_write_lock_violation_region_i,

  // SRAM execute-permission mode (to CPU wrapper): 0=ROM-only whitelist, 1=write-locked-SRAM whitelist
  output logic        sram_exec_mode_o,
  // Execute-permission whitelist violation (from CPU wrapper): pulse when fetch is outside whitelist
  input  logic   exec_violation_i,
  // ROM lockout violation (from CPU wrapper): pulse on ROM fetch or read after lockout engages
  input  logic   rom_access_violation_i,

  // Aggregated IRQ Output (to CPU)
  output logic        km_irq_o,

  // Programmable IRQ entry address (to CPU wrapper / PicoRV32)
  output logic [31:0] irq_entry_addr_o,

  // Soft Reset Output
  output logic        soft_rst_o,

  // Error condition output: recoverable error event
  output logic        recoverable_err_o,

  // Virtual UART Interface (for testbench communication)
  // TX: Firmware writes byte, testbench captures
  output logic [7:0]  vuart_tx_data_o,       // TX byte data
  output logic        vuart_tx_valid_o,      // TX data valid strobe (pulse)
  // RX: Testbench writes byte, firmware reads
  input  logic [7:0] vuart_rx_data_i,       // RX byte from testbench
  input  logic   vuart_rx_valid_i,      // RX data valid

  // Test Protocol Interface (for firmware-testbench communication)
  // Firmware writes these, testbench reads
  output logic [31:0] tb_result_o,           // Test result (0=fail, 1=pass)
  output logic [31:0] tb_signature_o,        // Test completion signature
  output logic [31:0] tb_errcode_o,          // Error code
  output logic [31:0] tb_subtest_o,          // Current subtest number
  output logic [31:0] tb_cmd_o,              // Command from firmware
  output logic [31:0] tb_cmd_arg_o,          // Command argument
  // Testbench writes these, firmware reads
  input  logic [31:0] tb_cmd_next_i,         // Testbench can write to clear command
  input  logic [31:0] tb_cmd_status_i,       // Command status from testbench
  input  logic [31:0] tb_cmd_result_i,       // Command result from testbench

  // SEP OTP Data Interface
  input  km_otp_data_t otp_data_i            // Differentially encoded OTP data
);

  `include "ocah_assert.svh"

  // =========================================================================
  // Local Parameters
  // =========================================================================

  /** @brief Bit positions within the SCRAMBLER_CTRL register (per RDL). */
  localparam int unsigned SCRAMBLER_CTRL_ENABLE_BIT_POS = 0;
  localparam int unsigned SCRAMBLER_CTRL_LOCK_BIT_POS = 1;

  /** @brief Bit positions for the internal IRQ aggregation vector (excludes mailbox). */
  localparam int unsigned IRQ_AGG_ROM_PARITY_ERR_BIT = 0;
  localparam int unsigned IRQ_AGG_SRAM_PARITY_ERR_BIT = 1;
  localparam int unsigned IRQ_AGG_ROM_WRITE_ERR_BIT = 2;
  localparam int unsigned IRQ_AGG_SRAM_WRITE_LOCK_ERR_BIT = 3;
  localparam int unsigned IRQ_AGG_AXI_SLVERR_BIT = 4;
  localparam int unsigned IRQ_AGG_AXI_DECERR_BIT = 5;
  localparam int unsigned IRQ_AGG_DRBG_ERR_BIT = 6;
  localparam int unsigned IRQ_AGG_WIPE_STATE_BIT = 7;
  localparam int unsigned IRQ_AGG_OTP_CHANGE_BIT = 8;
  localparam int unsigned IRQ_AGG_OTP_SIGINT_BIT = 9;
  localparam int unsigned IRQ_AGG_EXEC_VIOLATION_BIT = 10;
  localparam int unsigned IRQ_AGG_ROM_ACCESS_VIOLATION_BIT = 11;

  /** @brief Total number of IRQ sources aggregated into km_irq_o. */
  localparam int unsigned NUM_IRQ_SOURCES = 12;

  //=========================================================================
  // AXI4-Lite Interface Conversion
  //=========================================================================
  // Convert struct-based km_axil_req_t/km_axil_resp_t to individual ports
  // (axi4-lite-flat format, matching SEP/SMC style)


  // Individual AXI port signals for register block (axi4-lite-flat format)
  logic reg_awready, reg_awvalid;
  logic [km_csr_reg_pkg::KM_CSR_REG_MIN_ADDR_WIDTH-1:0] reg_awaddr;
  logic [2:0] reg_awprot;
  logic reg_wready, reg_wvalid;
  logic [31:0] reg_wdata;
  logic [3:0] reg_wstrb;
  logic reg_bready, reg_bvalid;
  logic [1:0] reg_bresp;
  logic reg_arready, reg_arvalid;
  logic [km_csr_reg_pkg::KM_CSR_REG_MIN_ADDR_WIDTH-1:0] reg_araddr;
  logic [2:0] reg_arprot;
  logic reg_rready, reg_rvalid;
  logic [31:0] reg_rdata;
  logic [1:0] reg_rresp;

  // Write address channel
  assign reg_awvalid = axil_req_i.aw_valid;
  assign reg_awaddr  = axil_req_i.aw.addr[km_csr_reg_pkg::KM_CSR_REG_MIN_ADDR_WIDTH-1:0];
  assign reg_awprot  = axil_req_i.aw.prot;
  assign axil_resp_o.aw_ready = reg_awready;

  // Write data channel
  assign reg_wvalid = axil_req_i.w_valid;
  assign reg_wdata  = axil_req_i.w.data;
  assign reg_wstrb  = axil_req_i.w.strb;
  assign axil_resp_o.w_ready = reg_wready;

  // Write response channel
  assign axil_resp_o.b.resp   = reg_bresp;
  assign axil_resp_o.b_valid  = reg_bvalid;
  assign reg_bready = axil_req_i.b_ready;

  // Read address channel
  assign reg_arvalid = axil_req_i.ar_valid;
  assign reg_araddr  = axil_req_i.ar.addr[km_csr_reg_pkg::KM_CSR_REG_MIN_ADDR_WIDTH-1:0];
  assign reg_arprot  = axil_req_i.ar.prot;
  assign axil_resp_o.ar_ready = reg_arready;

  // Read data channel
  assign axil_resp_o.r.data  = reg_rdata;
  assign axil_resp_o.r.resp = reg_rresp;
  assign axil_resp_o.r_valid = reg_rvalid;
  assign reg_rready = axil_req_i.r_ready;

  //=========================================================================
  // Register Module Interface Signals
  //=========================================================================

  km_csr__in_t  hwif_in;
  km_csr__out_t hwif_out;

  //=========================================================================
  // IRQ Status Register Logic
  //=========================================================================
  // All IRQ_STATUS fields are sticky (set on pulse via hwset, cleared by W1C).
  // The generated module handles stickybit behavior: hwset sets the bit,
  // software writes 1 to clear.

  assign hwif_in.IRQ_STATUS.rom_parity_err.next      = 1'b0;      // Tie off (using hwset instead)
  assign hwif_in.IRQ_STATUS.sram_parity_err.next     = 1'b0;      // Tie off (using hwset instead)
  assign hwif_in.IRQ_STATUS.rom_write_err.next       = 1'b0;      // Tie off (using hwset instead)
  assign hwif_in.IRQ_STATUS.sram_write_lock_err.next = 1'b0;      // Tie off (using hwset instead)
  assign hwif_in.IRQ_STATUS.axi_slverr.next          = 1'b0;      // Tie off (using hwset instead)
  assign hwif_in.IRQ_STATUS.axi_decerr.next          = 1'b0;      // Tie off (using hwset instead)
  assign hwif_in.IRQ_STATUS.drbg_err.next            = 1'b0;      // Tie off (using hwset instead)

  // Sticky IRQ bits can be set by either:
  // 1. Hardware error pulse (normal operation)
  // 2. Software write to IRQ_SET register (ISR testing)
  // Both sources are OR'd together to form the hwset signal.
  assign hwif_in.IRQ_STATUS.rom_parity_err.hwset  = rom_parity_err_i |
                                                      hwif_out.IRQ_SET.rom_parity_err_set.value;
  assign hwif_in.IRQ_STATUS.sram_parity_err.hwset = sram_parity_err_i |
                                                      hwif_out.IRQ_SET.sram_parity_err_set.value;
  assign hwif_in.IRQ_STATUS.rom_write_err.hwset   = rom_write_err_i |
                                                      hwif_out.IRQ_SET.rom_write_err_set.value;
  assign hwif_in.IRQ_STATUS.sram_write_lock_err.hwset = (|sram_write_lock_violation_region_i) |
                                                      hwif_out.IRQ_SET.sram_write_lock_err_set.value;
  assign hwif_in.IRQ_STATUS.axi_slverr.hwset      = axi_slverr_i |
                                                      hwif_out.IRQ_SET.axi_slverr_set.value;
  assign hwif_in.IRQ_STATUS.axi_decerr.hwset     = axi_decerr_i |
                                                      hwif_out.IRQ_SET.axi_decerr_set.value;
  assign hwif_in.IRQ_STATUS.drbg_err.hwset       = drbg_err_i |
                                                      hwif_out.IRQ_SET.drbg_err_set.value;
  assign hwif_in.IRQ_STATUS.wipe_state.next      = 1'b0;  // Tie off (using hwset instead)
  assign hwif_in.IRQ_STATUS.wipe_state.hwset     = wipe_state_i |
                                                      hwif_out.IRQ_SET.wipe_state_set.value;

  // OTP change and sigint IRQs are driven from otp_change_any / otp_sigint_any
  // computed in the OTP section below.
  assign hwif_in.IRQ_STATUS.otp_change.next  = 1'b0;
  assign hwif_in.IRQ_STATUS.otp_sigint.next  = 1'b0;

  // Execute-permission whitelist violation: set by pulse from CPU wrapper or by IRQ_SET (test)
  assign hwif_in.IRQ_STATUS.exec_violation.next  = 1'b0;
  assign hwif_in.IRQ_STATUS.exec_violation.hwset = exec_violation_i |
                                                     hwif_out.IRQ_SET.exec_violation_set.value;

  // ROM lockout violation: set by pulse from CPU wrapper or by IRQ_SET (test)
  assign hwif_in.IRQ_STATUS.rom_access_violation.next  = 1'b0;
  assign hwif_in.IRQ_STATUS.rom_access_violation.hwset =
        rom_access_violation_i | hwif_out.IRQ_SET.rom_access_violation_set.value;

  //=========================================================================
  // IRQ Aggregation
  //=========================================================================

  logic [NUM_IRQ_SOURCES-1:0] irq_status;
  logic [NUM_IRQ_SOURCES-1:0] irq_enable;
  logic [NUM_IRQ_SOURCES-1:0] irq_masked;

  assign irq_status[IRQ_AGG_ROM_PARITY_ERR_BIT]      = hwif_out.IRQ_STATUS.rom_parity_err.value;
  assign irq_status[IRQ_AGG_SRAM_PARITY_ERR_BIT]     = hwif_out.IRQ_STATUS.sram_parity_err.value;
  assign irq_status[IRQ_AGG_ROM_WRITE_ERR_BIT]        = hwif_out.IRQ_STATUS.rom_write_err.value;
  assign irq_status[IRQ_AGG_SRAM_WRITE_LOCK_ERR_BIT] = hwif_out.IRQ_STATUS.sram_write_lock_err.value;
  assign irq_status[IRQ_AGG_AXI_SLVERR_BIT]          = hwif_out.IRQ_STATUS.axi_slverr.value;
  assign irq_status[IRQ_AGG_AXI_DECERR_BIT]          = hwif_out.IRQ_STATUS.axi_decerr.value;
  assign irq_status[IRQ_AGG_DRBG_ERR_BIT]            = hwif_out.IRQ_STATUS.drbg_err.value;
  assign irq_status[IRQ_AGG_WIPE_STATE_BIT]           = hwif_out.IRQ_STATUS.wipe_state.value;
  assign irq_status[IRQ_AGG_OTP_CHANGE_BIT]           = hwif_out.IRQ_STATUS.otp_change.value;
  assign irq_status[IRQ_AGG_OTP_SIGINT_BIT]           = hwif_out.IRQ_STATUS.otp_sigint.value;
  assign irq_status[IRQ_AGG_EXEC_VIOLATION_BIT]       = hwif_out.IRQ_STATUS.exec_violation.value;
  assign irq_status[IRQ_AGG_ROM_ACCESS_VIOLATION_BIT] = hwif_out.IRQ_STATUS.rom_access_violation.value;

  assign irq_enable[IRQ_AGG_ROM_PARITY_ERR_BIT]      = hwif_out.IRQ_ENABLE.rom_parity_en.value;
  assign irq_enable[IRQ_AGG_SRAM_PARITY_ERR_BIT]     = hwif_out.IRQ_ENABLE.sram_parity_en.value;
  assign irq_enable[IRQ_AGG_ROM_WRITE_ERR_BIT]        = hwif_out.IRQ_ENABLE.rom_write_en.value;
  assign irq_enable[IRQ_AGG_SRAM_WRITE_LOCK_ERR_BIT] = hwif_out.IRQ_ENABLE.sram_write_lock_en.value;
  assign irq_enable[IRQ_AGG_AXI_SLVERR_BIT]          = hwif_out.IRQ_ENABLE.axi_slverr_en.value;
  assign irq_enable[IRQ_AGG_AXI_DECERR_BIT]          = hwif_out.IRQ_ENABLE.axi_decerr_en.value;
  assign irq_enable[IRQ_AGG_DRBG_ERR_BIT]            = hwif_out.IRQ_ENABLE.drbg_err_en.value;
  assign irq_enable[IRQ_AGG_WIPE_STATE_BIT]           = hwif_out.IRQ_ENABLE.wipe_state_en.value;
  assign irq_enable[IRQ_AGG_OTP_CHANGE_BIT]           = hwif_out.IRQ_ENABLE.otp_change_en.value;
  assign irq_enable[IRQ_AGG_OTP_SIGINT_BIT]           = hwif_out.IRQ_ENABLE.otp_sigint_en.value;
  assign irq_enable[IRQ_AGG_EXEC_VIOLATION_BIT]       = hwif_out.IRQ_ENABLE.exec_violation_en.value;
  assign irq_enable[IRQ_AGG_ROM_ACCESS_VIOLATION_BIT] = hwif_out.IRQ_ENABLE.rom_access_violation_en.value;

  assign irq_masked = irq_status & irq_enable;
  assign km_irq_o = |irq_masked;

  //=========================================================================
  // IRQ entry address (programmable via KMCSR; block SW writes when locked)
  //=========================================================================

  assign hwif_in.IRQ_ENTRY_ADDR.addr.swwel = hwif_out.IRQ_ENTRY_LOCK.lock.value;
  assign irq_entry_addr_o                  = hwif_out.IRQ_ENTRY_ADDR.addr.value;

  //=========================================================================
  // Scrambler Lock Logic
  //=========================================================================
  // When SCRAMBLER_CTRL.LOCK = 1:
  // - SCRAMBLER_KEY writes are ignored (register value overridden via hwif_in)
  // - SCRAMBLER_KEY reads return 0x0000_0000 (register value overridden via hwif_in)
  // - SCRAMBLER_CTRL.LOCK can only be set (0→1), never cleared (register value overridden)
  // - SCRAMBLER_CTRL.ENABLE is locked and forced to 1 (cannot be modified, always enabled)

  // Lock state tracking (write-once: can only transition 0→1)
  logic scrambler_lock_q;
  logic [31:0] scrambler_key_stored;
  logic scrambler_enable_stored;

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      scrambler_lock_q <= 1'b0;
      scrambler_key_stored <= 32'h0;
      scrambler_enable_stored <= 1'b0;
    end else begin
      // Track lock state - only allow 0→1 transition (write-once)
      if (hwif_out.SCRAMBLER_CTRL.lock.value && !scrambler_lock_q) begin
        scrambler_lock_q <= 1'b1;
        // When locked, scrambler must also be enabled
        scrambler_enable_stored <= 1'b1;
      end

      // Store scrambler key while unlocked; freeze on lock (write-once).
      if (!scrambler_lock_q) begin
        scrambler_key_stored <= hwif_out.SCRAMBLER_KEY.key.value;
      end
    end
  end

  // Register-level lock behavior: override register values via hwif_in
  // When locked, continuously drive register inputs to locked values
  // This prevents software writes from taking effect and makes reads return locked values
  // When not locked, maintain current register value (allow software writes to take effect)

  // SCRAMBLER_KEY: When locked, override to 0 (reads return 0, writes are ignored)
  // When not locked, maintain current value (software can write)
  assign hwif_in.SCRAMBLER_KEY.key.next = scrambler_lock_q ? 32'h0 : hwif_out.SCRAMBLER_KEY.key.value;

  // SCRAMBLER_CTRL: When locked, override lock and enable bits to locked values
  // Lock bit: preserve if set (write-once behavior - once set, always set)
  // Enable bit: always 1 when locked
  assign hwif_in.SCRAMBLER_CTRL.lock.next = scrambler_lock_q ? 1'b1 : hwif_out.SCRAMBLER_CTRL.lock.value;
  assign hwif_in.SCRAMBLER_CTRL.enable.next = scrambler_lock_q ? 1'b1 : hwif_out.SCRAMBLER_CTRL.enable.value;

  // Scrambler outputs to hardware
  // Always send stored key to hardware (lock only affects software access, not hardware operation)
  // When locked, scrambler must always be enabled
  assign scrambler_key_o = scrambler_key_stored;
  assign scrambler_enable_o = scrambler_lock_q ? 1'b1 : hwif_out.SCRAMBLER_CTRL.enable.value;
  assign scrambler_lock_o = scrambler_lock_q;

  //=========================================================================
  // SRAM Write-Lock: Write-1-only, output to SRAM interface
  //=========================================================================
  // RDL uses onwrite=woset; generated block implements write-1-only. No wrapper logic.
  assign sram_lock_bits_o = hwif_out.SRAM_LOCK.lock_bits.value;

  //=========================================================================
  // SRAM Execute-Permission Mode
  //=========================================================================
  // Write-1-only (woset), warm-reset domain. Drives the whitelist selector in
  // picorv32_wrapper: 0=ROM-only, 1=ROM+write-locked-SRAM.
  assign sram_exec_mode_o = hwif_out.SRAM_EXEC_MODE.enable.value;

  //=========================================================================
  // SRAM Write-Lock Violation Status
  //=========================================================================
  // Violation one-hot from SRAM interface: OR into sticky status register.
  assign hwif_in.SRAM_WRITE_LOCK_VIOLATION.violation_bits.next  = sram_write_lock_violation_region_i;
  assign hwif_in.SRAM_WRITE_LOCK_VIOLATION.violation_bits.hwset  = |sram_write_lock_violation_region_i;

  //=========================================================================
  // OTP Data Read-Through with Dual-Rail Decode, Read-Lock, and Change-Detect
  //=========================================================================
  // 1. Decode each dual-rail field with prim_diff_decode_multi (unmasked).
  // 2. Detect changes vs. previous cycle; aggregate into OTP_CHANGE_STATUS.
  // 3. Apply read-lock masking before writing register .next values.
  // 4. Drive IRQ_STATUS.OTP_CHANGE and OTP_SIGINT from aggregated signals.

  // ---- Effective read-lock: OR of warm-domain (OTP_READ_LOCK) and
  //      cold-domain (OTP_READ_LOCK_COLD) bits for each OTP field.
  //      Either register alone is sufficient to suppress CSR readback. ----
  logic otp_lock_life_cycle, otp_lock_demotion, otp_lock_chiplet;
  logic otp_lock_sip, otp_lock_sys, otp_lock_class_key;
  logic otp_lock_chip_id, otp_lock_sip_id, otp_lock_sys_id;

  assign otp_lock_life_cycle  = hwif_out.OTP_READ_LOCK.life_cycle.value
                                | hwif_out.OTP_READ_LOCK_COLD.life_cycle.value;
  assign otp_lock_demotion    = hwif_out.OTP_READ_LOCK.demotion.value
                                | hwif_out.OTP_READ_LOCK_COLD.demotion.value;
  assign otp_lock_chiplet     = hwif_out.OTP_READ_LOCK.chiplet_uid.value
                                | hwif_out.OTP_READ_LOCK_COLD.chiplet_uid.value;
  assign otp_lock_sip         = hwif_out.OTP_READ_LOCK.sip_uid.value
                                | hwif_out.OTP_READ_LOCK_COLD.sip_uid.value;
  assign otp_lock_sys         = hwif_out.OTP_READ_LOCK.sys_uid.value
                                | hwif_out.OTP_READ_LOCK_COLD.sys_uid.value;
  assign otp_lock_class_key   = hwif_out.OTP_READ_LOCK.class_key.value
                                | hwif_out.OTP_READ_LOCK_COLD.class_key.value;
  assign otp_lock_chip_id     = hwif_out.OTP_READ_LOCK.sep_chiplet_id.value
                                | hwif_out.OTP_READ_LOCK_COLD.sep_chiplet_id.value;
  assign otp_lock_sip_id      = hwif_out.OTP_READ_LOCK.sep_sip_id.value
                                | hwif_out.OTP_READ_LOCK_COLD.sep_sip_id.value;
  assign otp_lock_sys_id      = hwif_out.OTP_READ_LOCK.sep_sys_id.value
                                | hwif_out.OTP_READ_LOCK_COLD.sep_sys_id.value;

  // ---- Registered encoded OTP captures ----
  // The raw encoded signals from otp_data_i are registered here.  All
  // downstream logic (decoders, CSR word assignments, change detection)
  // operates on these stable registered versions rather than the raw input,
  // giving clean timing and a single authority for all OTP-derived state.
  //
  // otp_prev_valid suppresses a spurious change pulse on the first cycle
  // after reset before any valid OTP data has been captured.  Lifecycle and
  // demotion captures persist across warm resets.  The secret and public
  // identity captures are additionally cleared by warm reset (which also
  // carries the soft reset) and reload from otp_data_i on the first cycle
  // after release.
  logic         otp_prev_valid;
  logic [7:0]   lc_enc_r;
  logic [1:0] dem1_enc_r, dem2_enc_r;
  logic [511:0] chiplet_enc_r, sip_enc_r, sys_enc_r;
  logic [511:0] class_key_enc_r;
  logic [511:0] chip_id_enc_r, sip_id_enc_r, sys_id_enc_r;

  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      otp_prev_valid  <= 1'b0;
      lc_enc_r        <= '0;
      dem1_enc_r      <= '0;
      dem2_enc_r      <= '0;
      chiplet_enc_r   <= '0;
      sip_enc_r       <= '0;
      sys_enc_r       <= '0;
      class_key_enc_r <= '0;
      chip_id_enc_r   <= '0;
      sip_id_enc_r    <= '0;
      sys_id_enc_r    <= '0;
    end else if (!warm_rst_ni) begin
      otp_prev_valid  <= 1'b0;
      chiplet_enc_r   <= '0;
      sip_enc_r       <= '0;
      sys_enc_r       <= '0;
      class_key_enc_r <= '0;
      chip_id_enc_r   <= '0;
      sip_id_enc_r    <= '0;
      sys_id_enc_r    <= '0;
    end else begin
      otp_prev_valid  <= 1'b1;
      lc_enc_r        <= otp_data_i.life_cycle;
      dem1_enc_r      <= otp_data_i.demotion_state_1;
      dem2_enc_r      <= otp_data_i.demotion_state_2;
      chiplet_enc_r   <= otp_data_i.chiplet_uid;
      sip_enc_r       <= otp_data_i.sip_uid;
      sys_enc_r       <= otp_data_i.sys_uid;
      class_key_enc_r <= otp_data_i.class_key;
      chip_id_enc_r   <= otp_data_i.sep_chiplet_id;
      sip_id_enc_r    <= otp_data_i.sep_sip_id;
      sys_id_enc_r    <= otp_data_i.sep_sys_id;
    end
  end

  // ---- Dual-rail decoders (operate on the registered captures) ----
  // Decoders for LC (Width=4) and demotion (Width=1) fields.
  // Decoders for 256-bit fields (Width=256): chiplet_uid, sip_uid, sys_uid,
  // class_key, sep_chiplet_id, sep_sip_id, sep_sys_id.

  logic [3:0]   lc_decoded;
  logic         lc_sigint;

  prim_diff_decode_multi #(
    .Width(4),
    .AsyncOn(1'b0)
  ) u_lc_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (lc_enc_r),
    .data_o  (lc_decoded),
    .sigint_o(lc_sigint)
  );

  logic dem1_decoded, dem1_sigint;
  prim_diff_decode_multi #(
    .Width(1),
    .AsyncOn(1'b0)
  ) u_dem1_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (dem1_enc_r),
    .data_o  (dem1_decoded),
    .sigint_o(dem1_sigint)
  );

  logic dem2_decoded, dem2_sigint;
  prim_diff_decode_multi #(
    .Width(1),
    .AsyncOn(1'b0)
  ) u_dem2_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (dem2_enc_r),
    .data_o  (dem2_decoded),
    .sigint_o(dem2_sigint)
  );

  logic [255:0] chiplet_decoded;
  logic         chiplet_sigint;
  prim_diff_decode_multi #(
    .Width(256),
    .AsyncOn(1'b0)
  ) u_chiplet_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (chiplet_enc_r),
    .data_o  (chiplet_decoded),
    .sigint_o(chiplet_sigint)
  );

  logic [255:0] sip_decoded;
  logic         sip_sigint;
  prim_diff_decode_multi #(
    .Width(256),
    .AsyncOn(1'b0)
  ) u_sip_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (sip_enc_r),
    .data_o  (sip_decoded),
    .sigint_o(sip_sigint)
  );

  logic [255:0] sys_decoded;
  logic         sys_sigint;
  prim_diff_decode_multi #(
    .Width(256),
    .AsyncOn(1'b0)
  ) u_sys_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (sys_enc_r),
    .data_o  (sys_decoded),
    .sigint_o(sys_sigint)
  );

  logic [255:0] class_key_decoded;
  logic         class_key_sigint;
  prim_diff_decode_multi #(
    .Width(256),
    .AsyncOn(1'b0)
  ) u_class_key_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (class_key_enc_r),
    .data_o  (class_key_decoded),
    .sigint_o(class_key_sigint)
  );

  logic [255:0] chip_id_decoded;
  logic         chip_id_sigint;
  prim_diff_decode_multi #(
    .Width(256),
    .AsyncOn(1'b0)
  ) u_chip_id_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (chip_id_enc_r),
    .data_o  (chip_id_decoded),
    .sigint_o(chip_id_sigint)
  );

  logic [255:0] sip_id_decoded;
  logic         sip_id_sigint;
  prim_diff_decode_multi #(
    .Width(256),
    .AsyncOn(1'b0)
  ) u_sip_id_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (sip_id_enc_r),
    .data_o  (sip_id_decoded),
    .sigint_o(sip_id_sigint)
  );

  logic [255:0] sys_id_decoded;
  logic         sys_id_sigint;
  prim_diff_decode_multi #(
    .Width(256),
    .AsyncOn(1'b0)
  ) u_sys_id_dec (
    .clk_i,
    .rst_ni  (cold_rst_ni),
    .data_i  (sys_id_enc_r),
    .data_o  (sys_id_decoded),
    .sigint_o(sys_id_sigint)
  );

  // ---- Change detection ----
  // A change pulse fires when the incoming otp_data_i differs from the
  // registered capture of the previous cycle (encoded comparison).  This is
  // correct because the encoding is injective: identical encoded words always
  // decode to the same value.  The pulse fires one cycle before the new
  // decoded value appears in the CSR, but OTP_CHANGE_STATUS is sticky, so
  // firmware always sees the new CSR value when it reads the status.
  logic lc_change_pulse, dem_change_pulse, chiplet_change_pulse;
  logic sip_change_pulse, sys_change_pulse, class_key_change_pulse;
  logic chip_id_change_pulse, sip_id_change_pulse, sys_id_change_pulse;
  logic otp_change_any, otp_sigint_any;

  assign lc_change_pulse        = otp_prev_valid && (otp_data_i.life_cycle       != lc_enc_r);
  assign dem_change_pulse       = otp_prev_valid && ((otp_data_i.demotion_state_1 != dem1_enc_r) ||
                                                       (otp_data_i.demotion_state_2 != dem2_enc_r));
  assign chiplet_change_pulse   = otp_prev_valid &&
                                    (otp_data_i.chiplet_uid != chiplet_enc_r);
  assign sip_change_pulse       = otp_prev_valid &&
                                    (otp_data_i.sip_uid != sip_enc_r);
  assign sys_change_pulse       = otp_prev_valid &&
                                    (otp_data_i.sys_uid != sys_enc_r);
  assign class_key_change_pulse = otp_prev_valid &&
                                    (otp_data_i.class_key != class_key_enc_r);
  assign chip_id_change_pulse   = otp_prev_valid &&
                                    (otp_data_i.sep_chiplet_id != chip_id_enc_r);
  assign sip_id_change_pulse    = otp_prev_valid &&
                                    (otp_data_i.sep_sip_id != sip_id_enc_r);
  assign sys_id_change_pulse    = otp_prev_valid &&
                                    (otp_data_i.sep_sys_id != sys_id_enc_r);

  assign otp_change_any = lc_change_pulse | dem_change_pulse | chiplet_change_pulse |
                            sip_change_pulse | sys_change_pulse | class_key_change_pulse |
                            chip_id_change_pulse | sip_id_change_pulse | sys_id_change_pulse;
  assign otp_sigint_any = lc_sigint | dem1_sigint | dem2_sigint |
                            chiplet_sigint | sip_sigint | sys_sigint | class_key_sigint |
                            chip_id_sigint | sip_id_sigint | sys_id_sigint;

  // ---- OTP_CHANGE_STATUS register drives ----
  assign hwif_in.OTP_CHANGE_STATUS.life_cycle.next    = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.life_cycle.hwset   = lc_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.demotion.next      = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.demotion.hwset     = dem_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.chiplet_uid.next   = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.chiplet_uid.hwset  = chiplet_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.sip_uid.next       = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.sip_uid.hwset      = sip_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.sys_uid.next       = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.sys_uid.hwset      = sys_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.class_key.next     = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.class_key.hwset    = class_key_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.sep_chiplet_id.next  = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.sep_chiplet_id.hwset = chip_id_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.sep_sip_id.next      = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.sep_sip_id.hwset     = sip_id_change_pulse;
  assign hwif_in.OTP_CHANGE_STATUS.sep_sys_id.next      = 1'b0;
  assign hwif_in.OTP_CHANGE_STATUS.sep_sys_id.hwset     = sys_id_change_pulse;

  // ---- IRQ_STATUS OTP_CHANGE and OTP_SIGINT hwset drives ----
  // (next fields were tied off above; here we provide the hwset side)
  assign hwif_in.IRQ_STATUS.otp_change.hwset = otp_change_any |
                                                  hwif_out.IRQ_SET.otp_change_set.value;
  assign hwif_in.IRQ_STATUS.otp_sigint.hwset = otp_sigint_any |
                                                  hwif_out.IRQ_SET.otp_sigint_set.value;

  // ---- OTP_LIFE_CYCLE and OTP_DEMOTION_STATE read-through (with lock masking) ----
  assign hwif_in.OTP_LIFE_CYCLE.value.next              = otp_lock_life_cycle ? '0 : lc_enc_r;
  assign hwif_in.OTP_DEMOTION_STATE.demote_1_value.next = otp_lock_demotion   ? '0 : dem1_enc_r;
  assign hwif_in.OTP_DEMOTION_STATE.demote_2_value.next = otp_lock_demotion   ? '0 : dem2_enc_r;

  // ---- Dual-rail word register read-through (with lock masking) ----
  // All word assignments use the registered captures, not raw otp_data_i.
  // VAL word n = <field>_enc_r[32n+31:32n] (lower 256 bits = value)
  // CPL word n = <field>_enc_r[256+32n+31:256+32n] (upper 256 bits = ~value)

  // CHIPLET_UID (otp_lock_chiplet gates all 16 words)
  assign hwif_in.OTP_CHIPLET_UID_VAL_0.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[31:0];
  assign hwif_in.OTP_CHIPLET_UID_VAL_1.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[63:32];
  assign hwif_in.OTP_CHIPLET_UID_VAL_2.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[95:64];
  assign hwif_in.OTP_CHIPLET_UID_VAL_3.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[127:96];
  assign hwif_in.OTP_CHIPLET_UID_VAL_4.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[159:128];
  assign hwif_in.OTP_CHIPLET_UID_VAL_5.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[191:160];
  assign hwif_in.OTP_CHIPLET_UID_VAL_6.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[223:192];
  assign hwif_in.OTP_CHIPLET_UID_VAL_7.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[255:224];
  assign hwif_in.OTP_CHIPLET_UID_CPL_0.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[287:256];
  assign hwif_in.OTP_CHIPLET_UID_CPL_1.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[319:288];
  assign hwif_in.OTP_CHIPLET_UID_CPL_2.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[351:320];
  assign hwif_in.OTP_CHIPLET_UID_CPL_3.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[383:352];
  assign hwif_in.OTP_CHIPLET_UID_CPL_4.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[415:384];
  assign hwif_in.OTP_CHIPLET_UID_CPL_5.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[447:416];
  assign hwif_in.OTP_CHIPLET_UID_CPL_6.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[479:448];
  assign hwif_in.OTP_CHIPLET_UID_CPL_7.value.next = otp_lock_chiplet ? '0 : chiplet_enc_r[511:480];

  // SIP_UID
  assign hwif_in.OTP_SIP_UID_VAL_0.value.next = otp_lock_sip ? '0 : sip_enc_r[31:0];
  assign hwif_in.OTP_SIP_UID_VAL_1.value.next = otp_lock_sip ? '0 : sip_enc_r[63:32];
  assign hwif_in.OTP_SIP_UID_VAL_2.value.next = otp_lock_sip ? '0 : sip_enc_r[95:64];
  assign hwif_in.OTP_SIP_UID_VAL_3.value.next = otp_lock_sip ? '0 : sip_enc_r[127:96];
  assign hwif_in.OTP_SIP_UID_VAL_4.value.next = otp_lock_sip ? '0 : sip_enc_r[159:128];
  assign hwif_in.OTP_SIP_UID_VAL_5.value.next = otp_lock_sip ? '0 : sip_enc_r[191:160];
  assign hwif_in.OTP_SIP_UID_VAL_6.value.next = otp_lock_sip ? '0 : sip_enc_r[223:192];
  assign hwif_in.OTP_SIP_UID_VAL_7.value.next = otp_lock_sip ? '0 : sip_enc_r[255:224];
  assign hwif_in.OTP_SIP_UID_CPL_0.value.next = otp_lock_sip ? '0 : sip_enc_r[287:256];
  assign hwif_in.OTP_SIP_UID_CPL_1.value.next = otp_lock_sip ? '0 : sip_enc_r[319:288];
  assign hwif_in.OTP_SIP_UID_CPL_2.value.next = otp_lock_sip ? '0 : sip_enc_r[351:320];
  assign hwif_in.OTP_SIP_UID_CPL_3.value.next = otp_lock_sip ? '0 : sip_enc_r[383:352];
  assign hwif_in.OTP_SIP_UID_CPL_4.value.next = otp_lock_sip ? '0 : sip_enc_r[415:384];
  assign hwif_in.OTP_SIP_UID_CPL_5.value.next = otp_lock_sip ? '0 : sip_enc_r[447:416];
  assign hwif_in.OTP_SIP_UID_CPL_6.value.next = otp_lock_sip ? '0 : sip_enc_r[479:448];
  assign hwif_in.OTP_SIP_UID_CPL_7.value.next = otp_lock_sip ? '0 : sip_enc_r[511:480];

  // SYS_UID
  assign hwif_in.OTP_SYS_UID_VAL_0.value.next = otp_lock_sys ? '0 : sys_enc_r[31:0];
  assign hwif_in.OTP_SYS_UID_VAL_1.value.next = otp_lock_sys ? '0 : sys_enc_r[63:32];
  assign hwif_in.OTP_SYS_UID_VAL_2.value.next = otp_lock_sys ? '0 : sys_enc_r[95:64];
  assign hwif_in.OTP_SYS_UID_VAL_3.value.next = otp_lock_sys ? '0 : sys_enc_r[127:96];
  assign hwif_in.OTP_SYS_UID_VAL_4.value.next = otp_lock_sys ? '0 : sys_enc_r[159:128];
  assign hwif_in.OTP_SYS_UID_VAL_5.value.next = otp_lock_sys ? '0 : sys_enc_r[191:160];
  assign hwif_in.OTP_SYS_UID_VAL_6.value.next = otp_lock_sys ? '0 : sys_enc_r[223:192];
  assign hwif_in.OTP_SYS_UID_VAL_7.value.next = otp_lock_sys ? '0 : sys_enc_r[255:224];
  assign hwif_in.OTP_SYS_UID_CPL_0.value.next = otp_lock_sys ? '0 : sys_enc_r[287:256];
  assign hwif_in.OTP_SYS_UID_CPL_1.value.next = otp_lock_sys ? '0 : sys_enc_r[319:288];
  assign hwif_in.OTP_SYS_UID_CPL_2.value.next = otp_lock_sys ? '0 : sys_enc_r[351:320];
  assign hwif_in.OTP_SYS_UID_CPL_3.value.next = otp_lock_sys ? '0 : sys_enc_r[383:352];
  assign hwif_in.OTP_SYS_UID_CPL_4.value.next = otp_lock_sys ? '0 : sys_enc_r[415:384];
  assign hwif_in.OTP_SYS_UID_CPL_5.value.next = otp_lock_sys ? '0 : sys_enc_r[447:416];
  assign hwif_in.OTP_SYS_UID_CPL_6.value.next = otp_lock_sys ? '0 : sys_enc_r[479:448];
  assign hwif_in.OTP_SYS_UID_CPL_7.value.next = otp_lock_sys ? '0 : sys_enc_r[511:480];

  // CLASS_KEY
  assign hwif_in.OTP_CLASS_KEY_VAL_0.value.next = otp_lock_class_key ? '0 : class_key_enc_r[31:0];
  assign hwif_in.OTP_CLASS_KEY_VAL_1.value.next = otp_lock_class_key ? '0 : class_key_enc_r[63:32];
  assign hwif_in.OTP_CLASS_KEY_VAL_2.value.next = otp_lock_class_key ? '0 : class_key_enc_r[95:64];
  assign hwif_in.OTP_CLASS_KEY_VAL_3.value.next = otp_lock_class_key ? '0 : class_key_enc_r[127:96];
  assign hwif_in.OTP_CLASS_KEY_VAL_4.value.next = otp_lock_class_key ? '0 : class_key_enc_r[159:128];
  assign hwif_in.OTP_CLASS_KEY_VAL_5.value.next = otp_lock_class_key ? '0 : class_key_enc_r[191:160];
  assign hwif_in.OTP_CLASS_KEY_VAL_6.value.next = otp_lock_class_key ? '0 : class_key_enc_r[223:192];
  assign hwif_in.OTP_CLASS_KEY_VAL_7.value.next = otp_lock_class_key ? '0 : class_key_enc_r[255:224];
  assign hwif_in.OTP_CLASS_KEY_CPL_0.value.next = otp_lock_class_key ? '0 : class_key_enc_r[287:256];
  assign hwif_in.OTP_CLASS_KEY_CPL_1.value.next = otp_lock_class_key ? '0 : class_key_enc_r[319:288];
  assign hwif_in.OTP_CLASS_KEY_CPL_2.value.next = otp_lock_class_key ? '0 : class_key_enc_r[351:320];
  assign hwif_in.OTP_CLASS_KEY_CPL_3.value.next = otp_lock_class_key ? '0 : class_key_enc_r[383:352];
  assign hwif_in.OTP_CLASS_KEY_CPL_4.value.next = otp_lock_class_key ? '0 : class_key_enc_r[415:384];
  assign hwif_in.OTP_CLASS_KEY_CPL_5.value.next = otp_lock_class_key ? '0 : class_key_enc_r[447:416];
  assign hwif_in.OTP_CLASS_KEY_CPL_6.value.next = otp_lock_class_key ? '0 : class_key_enc_r[479:448];
  assign hwif_in.OTP_CLASS_KEY_CPL_7.value.next = otp_lock_class_key ? '0 : class_key_enc_r[511:480];

  // SEP_CHIPLET_ID
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_0.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[31:0];
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_1.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[63:32];
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_2.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[95:64];
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_3.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[127:96];
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_4.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[159:128];
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_5.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[191:160];
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_6.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[223:192];
  assign hwif_in.OTP_SEP_CHIPLET_ID_VAL_7.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[255:224];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_0.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[287:256];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_1.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[319:288];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_2.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[351:320];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_3.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[383:352];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_4.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[415:384];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_5.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[447:416];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_6.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[479:448];
  assign hwif_in.OTP_SEP_CHIPLET_ID_CPL_7.value.next = otp_lock_chip_id ? '0 : chip_id_enc_r[511:480];

  // SEP_SIP_ID
  assign hwif_in.OTP_SEP_SIP_ID_VAL_0.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[31:0];
  assign hwif_in.OTP_SEP_SIP_ID_VAL_1.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[63:32];
  assign hwif_in.OTP_SEP_SIP_ID_VAL_2.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[95:64];
  assign hwif_in.OTP_SEP_SIP_ID_VAL_3.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[127:96];
  assign hwif_in.OTP_SEP_SIP_ID_VAL_4.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[159:128];
  assign hwif_in.OTP_SEP_SIP_ID_VAL_5.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[191:160];
  assign hwif_in.OTP_SEP_SIP_ID_VAL_6.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[223:192];
  assign hwif_in.OTP_SEP_SIP_ID_VAL_7.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[255:224];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_0.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[287:256];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_1.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[319:288];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_2.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[351:320];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_3.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[383:352];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_4.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[415:384];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_5.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[447:416];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_6.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[479:448];
  assign hwif_in.OTP_SEP_SIP_ID_CPL_7.value.next = otp_lock_sip_id ? '0 : sip_id_enc_r[511:480];

  // SEP_SYS_ID
  assign hwif_in.OTP_SEP_SYS_ID_VAL_0.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[31:0];
  assign hwif_in.OTP_SEP_SYS_ID_VAL_1.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[63:32];
  assign hwif_in.OTP_SEP_SYS_ID_VAL_2.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[95:64];
  assign hwif_in.OTP_SEP_SYS_ID_VAL_3.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[127:96];
  assign hwif_in.OTP_SEP_SYS_ID_VAL_4.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[159:128];
  assign hwif_in.OTP_SEP_SYS_ID_VAL_5.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[191:160];
  assign hwif_in.OTP_SEP_SYS_ID_VAL_6.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[223:192];
  assign hwif_in.OTP_SEP_SYS_ID_VAL_7.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[255:224];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_0.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[287:256];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_1.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[319:288];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_2.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[351:320];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_3.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[383:352];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_4.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[415:384];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_5.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[447:416];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_6.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[479:448];
  assign hwif_in.OTP_SEP_SYS_ID_CPL_7.value.next = otp_lock_sys_id ? '0 : sys_id_enc_r[511:480];

  //=========================================================================
  // Soft Reset Output
  //=========================================================================
  // Soft reset requires code match
  // - SOFT_RST_CODE register must be written with 0x53525354 ("SRST")
  // - Code match generates registered soft reset signal
  // - Soft reset forces async reset input low (active-low: 0 = reset)
  // - Soft reset is cleared by full reset sequence

  /** @brief Magic code that triggers a soft reset when written to SOFT_RST_CODE. */
  localparam logic [31:0] SOFT_RST_CODE_MAGIC = 32'h53525354;  // ASCII "SRST"

  // Detect when SOFT_RST_CODE register contains the magic code
  // Use register block interface (hwif_out) to check register value
  // Register resets to 0, so this will only be true after firmware writes the magic code
  logic soft_rst_code_match;
  assign soft_rst_code_match = (hwif_out.SOFT_RST_CODE.code.value == SOFT_RST_CODE_MAGIC);

  // Register soft reset signal to prevent glitches
  // Active-low: 0 = reset asserted, 1 = normal operation.
  // When write with magic code detected, soft_rst_q = 0 (reset asserted).
  // warm_rst_ni (which is asserted both on cold and warm reset)
  // deasserts soft_rst_q, breaking the trigger loop. The SOFT_RST_CODE register
  // itself is also warm-resettable (resetsignal=WARM_RST_N in RDL), so the magic
  // code clears during the warm cycle, preventing re-trigger after release.
  logic soft_rst_q;
  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      soft_rst_q <= 1'b1;  // Cold AASD path: normal operation
    end else if (!warm_rst_ni) begin
      // Synchronous warm reset release: clear the soft-reset assertion.
      // warm_rst_ni is asserted by the conditioner on any warm (or cold) event.
      soft_rst_q <= 1'b1;
    end else begin
      if (soft_rst_code_match) begin
        soft_rst_q <= 1'b0;  // Assert reset (active-low)
      end
    end
  end

  // Output active-low soft reset signal
  // 0 = reset asserted, 1 = normal operation
  assign soft_rst_o = soft_rst_q;

  //=========================================================================
  // Recoverable Error Output
  //=========================================================================
  // Driven by RECOVERABLE_ERR register. Firmware sets when ISR recovers;
  // SEP requests clear via firmware command (KM firmware writes 0).
  assign recoverable_err_o = hwif_out.RECOVERABLE_ERR.recoverable_err.value;

  //=========================================================================
  // Virtual UART Logic
  //=========================================================================
  // VUART provides a simple byte-oriented interface for firmware-testbench
  // communication. This is used for printf/putc in firmware tests.
  //
  // TX path: Firmware writes to VUART_TX, DATA_VALID pulses for one cycle
  // RX path: Testbench provides data via input ports, firmware reads VUART_RX

  // TX: Output the TX byte from the register
  assign vuart_tx_data_o = hwif_out.VUART_TX.tx_byte.value;

  // TX Valid: Detect when firmware sets the DATA_VALID bit in VUART_TX
  // The DATA_VALID bit is in hwif_out.VUART_TX.data_valid.value
  // We detect when it goes from 0 to 1 (rising edge) to generate a pulse
  logic vuart_tx_data_valid_prev;
  logic vuart_tx_valid_pulse;

  // Sample DATA_VALID bit to detect rising edge
  always_ff @(posedge clk_i or negedge cold_rst_ni) begin
    if (!cold_rst_ni) begin
      vuart_tx_data_valid_prev <= 1'b0;
    end else begin
      vuart_tx_data_valid_prev <= hwif_out.VUART_TX.data_valid.value;
    end
  end

  // Rising edge detection: was 0, now 1
  assign vuart_tx_valid_pulse = hwif_out.VUART_TX.data_valid.value && !vuart_tx_data_valid_prev;
  assign vuart_tx_valid_o = vuart_tx_valid_pulse;

  // TX DATA_VALID clearing: Tell hardware to clear the DATA_VALID bit after one cycle
  assign hwif_in.VUART_TX.data_valid.next = 1'b0;  // Always clear (self-clearing)

  // RX: Hardware provides data from testbench
  assign hwif_in.VUART_RX.rx_byte.next = vuart_rx_data_i;
  assign hwif_in.VUART_RX.data_valid.next = vuart_rx_valid_i;

  // RX Status: Mirror the RX valid signal
  assign hwif_in.VUART_STATUS.tx_ready.next = 1'b1;  // TX is always ready (instant)
  assign hwif_in.VUART_STATUS.rx_valid.next = vuart_rx_valid_i;
  // PRINT_ENABLE: sim-only printf gate - TB backdoor-writes .next (+VUART_PRINT); FW reads via CSR.
  //               Intentionally no RTL driver (RDL sw=r; hw=w).
  // Default is 0 (disabled) to save simulation time

  //=========================================================================
  // Test Protocol Register Logic
  //=========================================================================
  // These registers provide a standardized interface for firmware tests to
  // communicate with the testbench. Firmware writes results/commands, and
  // testbench reads them. Testbench writes status/results that firmware reads.

  // Firmware writes these, testbench reads via output ports
  assign tb_result_o    = hwif_out.TB_RESULT.result.value;
  assign tb_signature_o = hwif_out.TB_SIGNATURE.signature.value;
  assign tb_errcode_o   = hwif_out.TB_ERRCODE.errcode.value;
  assign tb_subtest_o   = hwif_out.TB_SUBTEST.subtest.value;
  assign tb_cmd_o       = hwif_out.TB_CMD.cmd.value;
  assign tb_cmd_arg_o   = hwif_out.TB_CMD_ARG.arg.value;

  // Testbench writes these via input ports, firmware reads
  assign hwif_in.TB_CMD.cmd.next          = tb_cmd_next_i;
  assign hwif_in.TB_CMD_STATUS.status.next = tb_cmd_status_i;
  assign hwif_in.TB_CMD_RESULT.result.next = tb_cmd_result_i;

  //=========================================================================
  // Generated Register Module Instantiation
  //=========================================================================

  // Drive warm reset into the regblock via hwif_in struct field
  assign hwif_in.WARM_RST_N = warm_rst_ni;

  km_csr_reg u_km_csr_reg (
    .clk            (clk_i),
    .arst_n         (cold_rst_ni),
    .s_axil_awready (reg_awready),
    .s_axil_awvalid (reg_awvalid),
    .s_axil_awaddr  (reg_awaddr),
    .s_axil_awprot  (reg_awprot),
    .s_axil_wready  (reg_wready),
    .s_axil_wvalid  (reg_wvalid),
    .s_axil_wdata   (reg_wdata),
    .s_axil_wstrb   (reg_wstrb),
    .s_axil_bready  (reg_bready),
    .s_axil_bvalid  (reg_bvalid),
    .s_axil_bresp   (reg_bresp),
    .s_axil_arready (reg_arready),
    .s_axil_arvalid (reg_arvalid),
    .s_axil_araddr  (reg_araddr),
    .s_axil_arprot  (reg_arprot),
    .s_axil_rready  (reg_rready),
    .s_axil_rvalid  (reg_rvalid),
    .s_axil_rdata   (reg_rdata),
    .s_axil_rresp   (reg_rresp),
    .hwif_in        (hwif_in),
    .hwif_out       (hwif_out)
  );

  //=========================================================================
  // Assertions
  //=========================================================================

  `OCAH_ASSERT_KNOWN(ScramblerLockKnown_A, scrambler_lock_q, clk_i, !cold_rst_ni)
  `OCAH_ASSERT_KNOWN(IrqKnown_A, km_irq_o, clk_i, !cold_rst_ni)
  `OCAH_ASSERT_KNOWN(IrqEntryAddrKnown_A, irq_entry_addr_o, clk_i, !cold_rst_ni)

endmodule : km_csr
