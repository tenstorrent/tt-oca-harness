// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Define the Key Manager interface types and address-map constants.
//
// Shared by every Key Manager subsystem component:
//
// - AXI4-Lite channel, request and response types (32-bit)
// - ROM and SRAM memory interface structs (req/rsp)
// - DRBG AXI-Stream interface structs
// - IRQ event type, which no module uses
// - SEP OTP data interface struct
// - Full CPU address map constants for internal and external peripherals, used by the
//   crossbar and the CPU router

package km_intf_pkg;

  `include "axi/typedef.svh"

  import axi_pkg::*;

  // =========================================================================
  // AXI4-Lite Type Definitions (32-bit)
  // =========================================================================

  localparam int unsigned KmAxiAddrWidth = 32;  // AXI4-Lite address width.
  localparam int unsigned KmAxiDataWidth = 32;  // AXI4-Lite data width.
  localparam int unsigned KmAxiStrbWidth = KmAxiDataWidth / 8;  // AXI4-Lite write-strobe width.

  // 32-bit AXI address type for the Key Manager subsystem.
  typedef logic [KmAxiAddrWidth-1:0] km_addr_t;
  // 32-bit AXI data type for the Key Manager subsystem.
  typedef logic [KmAxiDataWidth-1:0] km_data_t;
  // 4-bit AXI write-strobe type (one bit per data byte).
  typedef logic [KmAxiStrbWidth-1:0] km_strb_t;

  //=========================================================================
  // AXI4-Lite Channel and Request/Response Types
  //=========================================================================

  // AXI-Lite channel, request, and response types (macro-generated). Expands to
  // km_axil_aw_chan_t, km_axil_w_chan_t, km_axil_b_chan_t, km_axil_ar_chan_t,
  // km_axil_r_chan_t, km_axil_req_t and km_axil_resp_t.
  `AXI_LITE_TYPEDEF_ALL(km_axil, km_addr_t, km_data_t, km_strb_t)

  //=========================================================================
  // Memory Interface Types
  //=========================================================================

  // Memory interface common widths (byte address, data, byte-enables).
  parameter int unsigned KM_MEM_ADDR_WIDTH = 32;  // Byte address width; not used by any module.
  parameter int unsigned KM_MEM_DATA_WIDTH = 32;  // Memory data width.
  parameter int unsigned KM_MEM_STRB_WIDTH = KM_MEM_DATA_WIDTH / 8;  // Memory byte-enable width.

  parameter int unsigned KM_ROM_MEM_ADDR_WIDTH = 12;  // ROM word-address width (12 bits = 4K words = 16 KB).

  parameter int unsigned KM_SRAM_MEM_ADDR_WIDTH = 13;  // SRAM word-address width (13 bits = 8K words = 32 KB).

  // ROM memory request (CPU -> ROM hard macro).
  typedef struct packed {
    logic                             req;           // Request valid.
    logic [KM_ROM_MEM_ADDR_WIDTH-1:0] addr;        // Word address.
  } km_rom_mem_req_t;

  // ROM memory response (ROM hard macro -> CPU).
  typedef struct packed {
    logic                           gnt;           // Grant/ready.
    logic                           rvalid;        // Read data valid.
    logic [KM_MEM_DATA_WIDTH-1:0]   rdata;         // Read data.
    logic [KM_MEM_STRB_WIDTH-1:0]   parity;        // Byte parity bits.
  } km_rom_mem_rsp_t;

  // SRAM memory request (CPU -> SRAM hard macro).
  typedef struct packed {
    logic                              req;           // Request valid.
    logic                              we;            // Write enable.
    logic [KM_MEM_STRB_WIDTH-1:0]      be;            // Byte enables.
    logic [KM_SRAM_MEM_ADDR_WIDTH-1:0] addr;          // Word address.
    logic [KM_MEM_DATA_WIDTH-1:0]      wdata;         // Write data.
    logic [KM_MEM_STRB_WIDTH-1:0]      wparity;       // Write parity bits.
  } km_sram_mem_req_t;

  // SRAM memory response (SRAM hard macro -> CPU).
  typedef struct packed {
    logic                           gnt;           // Grant/ready.
    logic                           rvalid;        // Read data valid.
    logic [KM_MEM_DATA_WIDTH-1:0]   rdata;         // Read data.
    logic [KM_MEM_STRB_WIDTH-1:0]   rparity;       // Read parity bits.
  } km_sram_mem_rsp_t;

  //=========================================================================
  // IRQ Types
  //=========================================================================

  // Packed IRQ event flags for the Key Manager subsystem.
  typedef struct packed {
    logic rom_parity_err;       // ROM parity error event.
    logic sram_parity_err;      // SRAM parity error event.
  } km_irq_events_t;

  // Key Manager CPU address map.
  //
  // Every register-block port spans exactly the window its block decodes, 2^MIN_ADDR_WIDTH
  // bytes taken from the generated register package, so no register is reachable from more
  // than one address. The table sizes are what those widths yield.
  //
  //  | Region | Base        | End         | Size  | Notes                                   |
  //  |--------|-------------|-------------|-------|-----------------------------------------|
  //  | ROM    | 0x0000_0000 | 0x0000_3FFF | 16 KB |                                         |
  //  | ---    | 0x0000_4000 | 0x0000_7FFF | 16 KB | Unmapped (DECERR); reserved for a       |
  //  |        |             |             |       | future ROM expansion to 32 KB           |
  //  | SRAM   | 0x0000_8000 | 0x0000_FFFF | 32 KB |                                         |
  //  | MBOX   | 0x0001_0000 | 0x0001_001F |  32 B |                                         |
  //  | OTP    | 0x0001_1000 | 0x0001_1FFF |  4 KB | External pass-through of MAP/CTRL/MMR;  |
  //  |        |             |             |       | HW remaps to OTP_EFUSE_REMAP_BASE and   |
  //  |        |             |             |       | answers other offsets with SLVERR       |
  //  | KPV    | 0x0001_2000 | 0x0001_3FFF |  8 KB | 64 slots; 8 KB-aligned                  |
  //  | KMCSR  | 0x0001_4000 | 0x0001_47FF |  2 KB |                                         |
  //  | DRBG   | 0x0001_5000 | 0x0001_500F |  16 B |                                         |
  //  | OTBN   | 0x0001_8000 | 0x0001_807F | 128 B |                                         |
  //  | AES    | 0x0001_9000 | 0x0001_907F | 128 B |                                         |
  //  | KMAC   | 0x0001_A000 | 0x0001_A07F | 128 B |                                         |
  //  | HMAC   | 0x0001_B000 | 0x0001_B07F | 128 B |                                         |
  //  | ABR    | 0x0001_C000 | 0x0001_C7FF |  2 KB |                                         |
  //  | VROM   | 0x1000_0000 | 0x1000_FFFF | 64 KB | Simulation-only; decoded only under     |
  //  |        |             |             |       | OCAH_KM_VROM, otherwise DECERR          |
  //
  // Addresses between one port's end and the next port's base are outside every crossbar
  // rule, so the crossbar answers DECERR; unmapped offsets inside a port's window reach its
  // register block, which is generated with --err-if-bad-addr and answers SLVERR. On the OTP
  // port, key_manager answers SLVERR itself for every offset outside the MAP, CTRL and MMR
  // register maps, so only those reach the eFuse controller.

  // Internal memory
  localparam km_addr_t RomBaseAddr = 32'h0000_0000;  // ROM window base.
  localparam km_addr_t RomEndAddr = 32'h0000_3FFF;  // ROM window end (inclusive).
  localparam km_addr_t SramBaseAddr = 32'h0000_8000;  // SRAM window base.
  localparam km_addr_t SramEndAddr = 32'h0000_FFFF;  // SRAM window end (inclusive).

  // Last address of a rule that spans one register block's decode window. A block keeps
  // only `addr_width` low address bits, so a rule any wider than its window would let the
  // block's registers repeat through the rest of the rule under a second set of addresses.
  function automatic km_addr_t km_window_end(km_addr_t base, int unsigned addr_width);
    return base + km_addr_t'((32'd1 << addr_width) - 1);
  endfunction

  // Internal peripherals
  localparam km_addr_t MboxBaseAddr = 32'h0001_0000;  // Mailbox register window base.
  localparam km_addr_t MboxEndAddr = km_window_end(
      MboxBaseAddr, km_mailbox_km_reg_pkg::KM_MAILBOX_KM_REG_MIN_ADDR_WIDTH
  );  // Mailbox register window end
  localparam km_addr_t KpvBaseAddr = 32'h0001_2000;  // KPV register window base
  localparam km_addr_t KpvEndAddr = km_window_end(
      KpvBaseAddr, km_kpv_reg_pkg::KM_KPV_REG_MIN_ADDR_WIDTH
  );  // KPV register window end
  localparam km_addr_t KmcsrBaseAddr = 32'h0001_4000;  // KMCSR register window base
  localparam km_addr_t KmcsrEndAddr = km_window_end(
      KmcsrBaseAddr, km_csr_reg_pkg::KM_CSR_REG_MIN_ADDR_WIDTH
  );  // KMCSR register window end
  localparam km_addr_t DrbgSamplerBaseAddr = 32'h0001_5000;  // DRBG sampler window base
  localparam km_addr_t DrbgSamplerEndAddr = km_window_end(
      DrbgSamplerBaseAddr, km_drbg_sampler_reg_pkg::KM_DRBG_SAMPLER_REG_MIN_ADDR_WIDTH
  );  // DRBG sampler window end

  // OTP / eFuse access port. The crossbar routes the OTP page to xbar master port 8.
  // key_manager.sv forwards only the MAP, CTRL and MMR register maps to efuse_req_o, with
  // addr[KmAxiAddrWidth-1:OtpRemapAddrWidth] replaced by OTP_EFUSE_REMAP_BASE, so the
  // shared SEP efuse_interface_controller is reached at the same offsets. The register maps
  // come from the generated KM address map and must lie inside the page.
  localparam int unsigned OtpRemapAddrWidth = 12;  // Offset bits the OTP remap keeps.
  localparam km_addr_t OtpPageMask = km_addr_t'(
      (32'd1 << OtpRemapAddrWidth) - 1
  );  // OTP page offset bits
  localparam km_addr_t OtpMapBaseAddr = km_addr_t'(
      key_manager_addrmap_pkg::KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR
  );  // eFuse shadow map base
  localparam km_addr_t OtpMapEndAddr = OtpMapBaseAddr + km_addr_t'(
      key_manager_addrmap_pkg::KEY_MANAGER_OTP_EFUSE_MAP_SIZE - 1
  );  // eFuse shadow map end
  localparam km_addr_t OtpCtrlBaseAddr = km_addr_t'(
      key_manager_addrmap_pkg::KEY_MANAGER_OTP_EFUSE_CTRL_BASE_ADDR
  );  // eFuse interface control base
  localparam km_addr_t OtpCtrlEndAddr = OtpCtrlBaseAddr + km_addr_t'(
      key_manager_addrmap_pkg::KEY_MANAGER_OTP_EFUSE_CTRL_SIZE - 1
  );  // eFuse interface control end
  localparam km_addr_t OtpMmrBaseAddr = km_addr_t'(
      key_manager_addrmap_pkg::KEY_MANAGER_OTP_EFUSE_MMR_BASE_ADDR
  );  // eFuse token MMR base
  localparam km_addr_t OtpMmrEndAddr = OtpMmrBaseAddr + km_addr_t'(
      key_manager_addrmap_pkg::KEY_MANAGER_OTP_EFUSE_MMR_SIZE - 1
  );  // eFuse token MMR end
  localparam km_addr_t OtpBaseAddr = OtpMapBaseAddr & ~OtpPageMask;  // OTP page base
  localparam km_addr_t OtpEndAddr = km_window_end(OtpBaseAddr, OtpRemapAddrWidth);  // OTP page end

  // True when addr falls in the MAP, CTRL or MMR register map of the OTP page.
  function automatic logic otp_addr_decoded(km_addr_t addr);
    return (addr >= OtpMapBaseAddr && addr <= OtpMapEndAddr) ||
           (addr >= OtpCtrlBaseAddr && addr <= OtpCtrlEndAddr) ||
           (addr >= OtpMmrBaseAddr && addr <= OtpMmrEndAddr);
  endfunction

  // External crypto engine ports
  localparam km_addr_t OtbnBaseAddr = 32'h0001_8000;  // OTBN window base
  localparam km_addr_t OtbnEndAddr = km_window_end(
      OtbnBaseAddr, otbn_wrapper_key_reg_pkg::OTBN_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // OTBN window end
  localparam km_addr_t AesBaseAddr = 32'h0001_9000;  // AES window base
  localparam km_addr_t AesEndAddr = km_window_end(
      AesBaseAddr, aes_wrapper_key_reg_pkg::AES_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // AES window end
  localparam km_addr_t KmacBaseAddr = 32'h0001_A000;  // KMAC window base
  localparam km_addr_t KmacEndAddr = km_window_end(
      KmacBaseAddr, kmac_wrapper_key_reg_pkg::KMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // KMAC window end
  localparam km_addr_t HmacBaseAddr = 32'h0001_B000;  // HMAC window base
  localparam km_addr_t HmacEndAddr = km_window_end(
      HmacBaseAddr, hmac_wrapper_key_reg_pkg::HMAC_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // HMAC window end
  localparam km_addr_t AbrBaseAddr = 32'h0001_C000;  // Adams Bridge window base
  localparam km_addr_t AbrEndAddr = km_window_end(
      AbrBaseAddr, abr_wrapper_key_reg_pkg::ABR_WRAPPER_KEY_REG_MIN_ADDR_WIDTH
  );  // Adams Bridge window end

  // Virtual ROM, decoded by picorv32_wrapper only under OCAH_KM_VROM
  localparam km_addr_t VromBaseAddr = 32'h1000_0000;  // Virtual ROM window base
  localparam km_addr_t VromEndAddr = 32'h1000_FFFF;  // Virtual ROM window end

  // Region sizes derived from the address ranges above.
  localparam int unsigned RomSizeBytes = RomEndAddr - RomBaseAddr + 1;  // 16 KB
  localparam int unsigned SramSizeBytes = SramEndAddr - SramBaseAddr + 1;  // 32 KB
  localparam int unsigned VromSizeBytes = VromEndAddr - VromBaseAddr + 1;  // 64 KB

  // SRAM write-lock granularity: 1 KB per lockable region.
  localparam int unsigned SramLockRegionBytes = 1024;  // Bytes per write-lock region
  localparam int unsigned SramNumLockRegions = SramSizeBytes / SramLockRegionBytes;  // Lock region count

  // =========================================================================
  // DRBG AXI-Stream Interface (KM is slave, DRBG is master)
  // =========================================================================

  // DRBG AXI-Stream bus widths (32-bit data, 4-bit strobe).
  localparam int unsigned KmDrbgAxisDataWidth = 32;
  localparam int unsigned KmDrbgAxisStrbWidth = KmDrbgAxisDataWidth / 8;

  // DRBG AXI-Stream request (DRBG master -> KM sampler slave).
  //
  // `tuser` is the per-beat sideband carried on drbg_pkg::drbg_axis_req_t (FIPS provenance
  // for post-CSRNG DRBG output). KM does not consume `tuser` but must mirror the producer
  // struct layout so the port connection at
  // sep_crypto.u_key_manager_s3c_scan.drbg_axis_req_i is not a width-mismatched (and thus
  // bit-shifted) bind.
  typedef struct packed {
    logic                               tvalid;
    logic [KmDrbgAxisDataWidth-1:0]     tdata;
    logic [KmDrbgAxisStrbWidth-1:0]     tstrb;
    logic                               tuser;
  } km_drbg_axis_req_t;

  // DRBG AXI-Stream response (KM sampler slave -> DRBG master).
  typedef struct packed {logic tready;} km_drbg_axis_resp_t;

  //=========================================================================
  // SEP OTP Data Interface
  //=========================================================================
  // SEP OTP data bundle read directly from port signals by KMCSR.
  //
  // The life-cycle field is differentially encoded (4-bit value in 8 bits); the demotion
  // state fields are 1-bit values encoded into 2 bits each. The four 256-bit secret fields
  // (chiplet_uid, class_key, sip_uid, sys_uid) and the three 256-bit public identity fields
  // (sep_chiplet_id, sep_sip_id, sep_sys_id) are dual-rail encoded by
  // prim_diff_encode_multi in sep_crypto.sv: the 512-bit wire carries
  // {~value[255:0], value[255:0]}, so [511:256] is the complement (~value) and [255:0] is
  // the value.
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
