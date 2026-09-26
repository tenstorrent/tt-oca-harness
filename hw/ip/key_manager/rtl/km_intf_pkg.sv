// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Shared Key Manager interface types and address-map constants.
//
// Defines the 32-bit AXI4-Lite channel/request/response types, ROM and SRAM
// memory req/rsp structs, DRBG AXI-Stream structs, IRQ event and SEP OTP data
// bundles, and the CPU address-map bases/ends used by the crossbar and CPU
// router. Each register-block port spans exactly 2^MIN_ADDR_WIDTH bytes from
// its generated package so registers are not aliased under a second address.
// The OTP window is a full 4 KB page remapped by key_manager onto the system
// eFuse controller (MAP/CTRL/MMR sub-regions keep addr[11:0]).

package km_intf_pkg;

  `include "axi/typedef.svh"

  import axi_pkg::*;

  // =========================================================================
  // AXI4-Lite Type Definitions (32-bit)
  // =========================================================================

  localparam int unsigned KM_AXI_ADDR_WIDTH = 32;  // AXI4-Lite address width
  localparam int unsigned KM_AXI_DATA_WIDTH = 32;  // AXI4-Lite data width
  localparam int unsigned KM_AXI_STRB_WIDTH = KM_AXI_DATA_WIDTH / 8;  // AXI4-Lite write-strobe width

  // 32-bit AXI address type for the Key Manager subsystem.
  typedef logic [KM_AXI_ADDR_WIDTH-1:0] km_addr_t;
  // 32-bit AXI data type for the Key Manager subsystem.
  typedef logic [KM_AXI_DATA_WIDTH-1:0] km_data_t;
  // 4-bit AXI write-strobe type (one bit per data byte).
  typedef logic [KM_AXI_STRB_WIDTH-1:0] km_strb_t;

  //=========================================================================
  // AXI4-Lite Channel and Request/Response Types
  //=========================================================================

  // AXI-Lite channel, request, and response types (macro-generated:
  // km_axil_aw/w/b/ar/r_chan_t, km_axil_req_t, km_axil_resp_t).
  `AXI_LITE_TYPEDEF_ALL(km_axil, km_addr_t, km_data_t, km_strb_t)

  //=========================================================================
  // Memory Interface Types
  //=========================================================================

  parameter int unsigned KM_MEM_ADDR_WIDTH = 32;  // Memory byte-address width
  parameter int unsigned KM_MEM_DATA_WIDTH = 32;  // Memory data width
  parameter int unsigned KM_MEM_STRB_WIDTH = KM_MEM_DATA_WIDTH / 8;  // Memory byte-enable width

  parameter int unsigned KM_ROM_MEM_ADDR_WIDTH = 12;  // ROM word-address width (4K words = 16 KB)

  parameter int unsigned KM_SRAM_MEM_ADDR_WIDTH = 13;  // SRAM word-address width (8K words = 32 KB)

  // ROM memory request (CPU -> ROM hard macro).
  typedef struct packed {
    logic                             req;         // Request valid
    logic [KM_ROM_MEM_ADDR_WIDTH-1:0] addr;        // Word address
  } km_rom_mem_req_t;

  // ROM memory response (ROM hard macro -> CPU).
  typedef struct packed {
    logic                           gnt;           // Grant/ready
    logic                           rvalid;        // Read data valid
    logic [KM_MEM_DATA_WIDTH-1:0]   rdata;         // Read data
    logic [KM_MEM_STRB_WIDTH-1:0]   parity;        // Byte parity bits
  } km_rom_mem_rsp_t;

  // SRAM memory request (CPU -> SRAM hard macro).
  typedef struct packed {
    logic                              req;           // Request valid
    logic                              we;            // Write enable
    logic [KM_MEM_STRB_WIDTH-1:0]      be;            // Byte enables
    logic [KM_SRAM_MEM_ADDR_WIDTH-1:0] addr;          // Word address
    logic [KM_MEM_DATA_WIDTH-1:0]      wdata;         // Write data
    logic [KM_MEM_STRB_WIDTH-1:0]      wparity;       // Write parity bits
  } km_sram_mem_req_t;

  // SRAM memory response (SRAM hard macro -> CPU).
  typedef struct packed {
    logic                           gnt;           // Grant/ready
    logic                           rvalid;        // Read data valid
    logic [KM_MEM_DATA_WIDTH-1:0]   rdata;         // Read data
    logic [KM_MEM_STRB_WIDTH-1:0]   rparity;       // Read parity bits
  } km_sram_mem_rsp_t;

  //=========================================================================
  // IRQ Types
  //=========================================================================

  // Packed IRQ event flags for the Key Manager subsystem.
  typedef struct packed {
    logic rom_parity_err;       // ROM parity error event
    logic sram_parity_err;      // SRAM parity error event
  } km_irq_events_t;

  // Key Manager CPU address map: each register-block port spans exactly the
  // window its block decodes (2^MIN_ADDR_WIDTH). Addresses between one port's
  // end and the next base get DECERR from the crossbar; unmapped offsets
  // inside a port window get SLVERR from --err-if-bad-addr register blocks.
  //
  //  | Region | Base        | End         | Size  | Notes                                   |
  //  |--------|-------------|-------------|-------|-----------------------------------------|
  //  | ROM    | 0x0000_0000 | 0x0000_3FFF | 16 KB |                                         |
  //  | ---    | 0x0000_4000 | 0x0000_7FFF | 16 KB | Unmapped (DECERR); reserved for a       |
  //  |        |             |             |       | future ROM expansion to 32 KB           |
  //  | SRAM   | 0x0000_8000 | 0x0000_FFFF | 32 KB |                                         |
  //  | MBOX   | 0x0001_0000 | 0x0001_001F |  32 B |                                         |
  //  | OTP    | 0x0001_1000 | 0x0001_1FFF |  4 KB | External pass-through; HW remaps to     |
  //  |        |             |             |       | OTP_EFUSE_REMAP_BASE (MAP/CTRL/MMR),    |
  //  |        |             |             |       | which needs the whole page              |
  //  | KPV    | 0x0001_2000 | 0x0001_3FFF |  8 KB | 64 slots; 8 KB-aligned                  |
  //  | KMCSR  | 0x0001_4000 | 0x0001_47FF |  2 KB |                                         |
  //  | DRBG   | 0x0001_5000 | 0x0001_500F |  16 B |                                         |
  //  | OTBN   | 0x0001_8000 | 0x0001_807F | 128 B |                                         |
  //  | AES    | 0x0001_9000 | 0x0001_907F | 128 B |                                         |
  //  | KMAC   | 0x0001_A000 | 0x0001_A07F | 128 B |                                         |
  //  | HMAC   | 0x0001_B000 | 0x0001_B07F | 128 B |                                         |
  //  | ABR    | 0x0001_C000 | 0x0001_C7FF |  2 KB |                                         |
  //  | VROM   | 0x1000_0000 | 0x1000_FFFF | 64 KB |                                         |

  localparam km_addr_t ROM_BASE_ADDR = 32'h0000_0000;   // ROM window base
  localparam km_addr_t ROM_END_ADDR = 32'h0000_3FFF;    // ROM window end (inclusive)
  localparam km_addr_t SRAM_BASE_ADDR = 32'h0000_8000;  // SRAM window base
  localparam km_addr_t SRAM_END_ADDR = 32'h0000_FFFF;   // SRAM window end (inclusive)

  // Last inclusive address of a register-block decode window of width addr_width.
  function automatic km_addr_t km_window_end(km_addr_t base, int unsigned addr_width);
    return base + km_addr_t'((32'd1 << addr_width) - 1);
  endfunction

  localparam km_addr_t MBOX_BASE_ADDR = 32'h0001_0000;  // Mailbox register window base
  localparam km_addr_t MBOX_END_ADDR = km_window_end(
      MBOX_BASE_ADDR, km_mailbox_km_reg_pkg::KM_MAILBOX_KM_REG_MIN_ADDR_WIDTH
  );  // Mailbox register window end
  localparam km_addr_t KPV_BASE_ADDR = 32'h0001_2000;  // KPV register window base
  localparam km_addr_t KPV_END_ADDR = km_window_end(
      KPV_BASE_ADDR, km_kpv_reg_pkg::KM_KPV_REG_MIN_ADDR_WIDTH
  );  // KPV register window end
  localparam km_addr_t KMCSR_BASE_ADDR = 32'h0001_4000;  // KMCSR register window base
  localparam km_addr_t KMCSR_END_ADDR = km_window_end(
      KMCSR_BASE_ADDR, km_csr_reg_pkg::KM_CSR_REG_MIN_ADDR_WIDTH
  );  // KMCSR register window end
  localparam km_addr_t DRBG_SAMPLER_BASE_ADDR = 32'h0001_5000;  // DRBG sampler window base
  localparam km_addr_t DRBG_SAMPLER_END_ADDR = km_window_end(
      DRBG_SAMPLER_BASE_ADDR, km_drbg_sampler_reg_pkg::KM_DRBG_SAMPLER_REG_MIN_ADDR_WIDTH
  );  // DRBG sampler window end

  localparam km_addr_t OTP_BASE_ADDR = 32'h0001_1000;  // OTP/eFuse KM-local window base
  localparam km_addr_t OTP_END_ADDR = 32'h0001_1FFF;   // OTP/eFuse KM-local window end

  localparam km_addr_t OTBN_BASE_ADDR = 32'h0001_8000;  // OTBN window base
  localparam km_addr_t OTBN_END_ADDR = km_window_end(
      OTBN_BASE_ADDR, otbn_wrapper_key_reg_pkg::OTBN_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // OTBN window end
  localparam km_addr_t AES_BASE_ADDR = 32'h0001_9000;  // AES window base
  localparam km_addr_t AES_END_ADDR = km_window_end(
      AES_BASE_ADDR, aes_wrapper_key_reg_pkg::AES_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // AES window end
  localparam km_addr_t KMAC_BASE_ADDR = 32'h0001_A000;  // KMAC window base
  localparam km_addr_t KMAC_END_ADDR = km_window_end(
      KMAC_BASE_ADDR, kmac_wrapper_key_reg_pkg::KMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // KMAC window end
  localparam km_addr_t HMAC_BASE_ADDR = 32'h0001_B000;  // HMAC window base
  localparam km_addr_t HMAC_END_ADDR = km_window_end(
      HMAC_BASE_ADDR, hmac_wrapper_key_reg_pkg::HMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // HMAC window end
  localparam km_addr_t ABR_BASE_ADDR = 32'h0001_C000;  // Adams Bridge window base
  localparam km_addr_t ABR_END_ADDR = km_window_end(
      ABR_BASE_ADDR, abr_wrapper_key_reg_pkg::ABR_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // Adams Bridge window end

  localparam km_addr_t VROM_BASE_ADDR = 32'h1000_0000;  // Virtual ROM window base
  localparam km_addr_t VROM_END_ADDR = 32'h1000_FFFF;   // Virtual ROM window end

  localparam int unsigned ROM_SIZE_BYTES = ROM_END_ADDR - ROM_BASE_ADDR + 1;  // ROM size in bytes
  localparam int unsigned SRAM_SIZE_BYTES = SRAM_END_ADDR - SRAM_BASE_ADDR + 1;  // SRAM size in bytes
  localparam int unsigned VROM_SIZE_BYTES = VROM_END_ADDR - VROM_BASE_ADDR + 1;  // VROM size in bytes

  localparam int unsigned SRAM_LOCK_REGION_BYTES = 1024;  // Bytes per write-lock region
  localparam int unsigned SRAM_NUM_LOCK_REGIONS = SRAM_SIZE_BYTES / SRAM_LOCK_REGION_BYTES;  // Lock region count

  localparam int unsigned KM_DRBG_AXIS_DATA_WIDTH = 32;  // DRBG AXI-Stream data width
  localparam int unsigned KM_DRBG_AXIS_STRB_WIDTH = KM_DRBG_AXIS_DATA_WIDTH / 8;  // DRBG AXI-Stream strobe width

  // DRBG AXI-Stream request (DRBG→KM); tuser mirrors drbg_pkg for width-matched bind.
  typedef struct packed {
    logic                               tvalid;
    logic [KM_DRBG_AXIS_DATA_WIDTH-1:0] tdata;
    logic [KM_DRBG_AXIS_STRB_WIDTH-1:0] tstrb;
    logic                               tuser;
  } km_drbg_axis_req_t;

  // DRBG AXI-Stream response (KM sampler slave -> DRBG master).
  typedef struct packed {logic tready;} km_drbg_axis_resp_t;

  //=========================================================================
  // SEP OTP Data Interface
  //=========================================================================
  // SEP OTP bundle for KMCSR: differential life-cycle/demotion; dual-rail 256-bit IDs.
  typedef struct packed {
    logic [7:0]   life_cycle;           // 4-bit value differentially encoded into 8-bit
    logic [1:0]   demotion_state_1;     // 1-bit value differentially encoded into 2-bit
    logic [1:0]   demotion_state_2;     // 1-bit value differentially encoded into 2-bit
    logic [511:0] chiplet_uid;          // 256-bit UID, dual-rail: {~uid, uid}
    logic [511:0] class_key;            // 256-bit class key, dual-rail: {~key, key}
    logic [511:0] sip_uid;              // 256-bit SIP UID, dual-rail: {~uid, uid}
    logic [511:0] sys_uid;              // 256-bit system UID, dual-rail: {~uid, uid}
    logic [511:0] sep_chiplet_id;       // 256-bit chiplet public ID, dual-rail: {~id, id}
    logic [511:0] sep_sip_id;           // 256-bit SiP public ID, dual-rail: {~id, id}
    logic [511:0] sep_sys_id;           // 256-bit system public ID, dual-rail: {~id, id}
  } km_otp_data_t;

endpackage : km_intf_pkg
