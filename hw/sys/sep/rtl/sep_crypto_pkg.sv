// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define typedefs and parameters for the SEP cryptographic subsystem.
//
// Covers the sep_crypto_axi_interconnect address rules and port enum, ABR memory structs,
// external TRNG AXI-Stream types, OTBN IMEM and DMEM structs, and EDN endpoint and client
// counts.

package sep_crypto_pkg;

  import sep_pkg::*;

  // import otbn_pkg::*;
  import lc_ctrl_pkg::*;
  import edn_pkg::*;
  import otp_ctrl_pkg::*;
  import keymgr_pkg::*;
  import prim_ram_1p_pkg::*;


  parameter axi_pkg::xbar_rule_32_t OTBN_RULE = '{
      idx: 0,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_OTBN_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_OTBN_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_OTBN_SIZE
  };

  parameter axi_pkg::xbar_rule_32_t HMAC_RULE = '{
      idx: 1,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_HMAC_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_HMAC_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_HMAC_SIZE
  };

  parameter axi_pkg::xbar_rule_32_t AES_RULE = '{
      idx: 2,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_AES_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_AES_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_AES_SIZE  // 256 bytes for AES.
  };

  parameter axi_pkg::xbar_rule_32_t KMAC_RULE = '{
      idx: 3,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_KMAC_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_KMAC_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_KMAC_SIZE
  };

  // Contiguous eFuse block: MAP -> INTERFACE CSR -> MMR.
  parameter axi_pkg::xbar_rule_32_t FUSE_RULE = '{
      idx: 4,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_EFUSE_MMR_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_EFUSE_MMR_SIZE
  };

  parameter axi_pkg::xbar_rule_32_t LIFECYCLE_RULE = '{
      idx: 5,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_SEP_LIFECYCLE_CTRL_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_SEP_LIFECYCLE_CTRL_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_SEP_LIFECYCLE_CTRL_SIZE
  };

  parameter axi_pkg::xbar_rule_32_t KM_RULE = '{
      idx: 6,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_KM_MAILBOX_SEP_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_KM_MAILBOX_SEP_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_KM_MAILBOX_SEP_SIZE
  };

  parameter axi_pkg::xbar_rule_32_t CSRNG_RULE = '{
      idx: 7,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_CSRNG_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_CSRNG_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_CSRNG_SIZE
  };

  parameter axi_pkg::xbar_rule_32_t EDN_RULE = '{
      idx: 8,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_EDN_BASE_ADDR,
      end_addr: sep_top_addrmap_pkg::SEP_TOP_EDN_BASE_ADDR + sep_top_addrmap_pkg::SEP_TOP_EDN_SIZE
  };

  parameter axi_pkg::xbar_rule_32_t ENTROPY_SOURCE_RULE = '{
      idx: 9,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_ENTROPY_SOURCE_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_ENTROPY_SOURCE_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_ENTROPY_SOURCE_SIZE
  };

  // TRNG: OCH spec 0x1091_7000–0x1091_7FFF (4 kB) — passthrough to an external TRNG
  localparam logic [31:0] TRNG_BASE_ADDR = 32'h1091_7000;
  localparam logic [31:0] TRNG_END_ADDR = 32'h1091_8000;

  parameter axi_pkg::xbar_rule_32_t TRNG_RULE = '{
      idx: 10,
      start_addr: TRNG_BASE_ADDR,
      end_addr: TRNG_END_ADDR
  };

  parameter axi_pkg::xbar_rule_32_t ABR_RULE = '{
      idx: 11,
      start_addr: sep_top_addrmap_pkg::SEP_TOP_ABR_BASE_ADDR,
      end_addr:
      sep_top_addrmap_pkg::SEP_TOP_ABR_BASE_ADDR
      +
      sep_top_addrmap_pkg::SEP_TOP_ABR_SIZE
  };

  // AXI demux port indices (must match axi_demux master port order in sep_crypto.sv).
  // Highest enum value must equal SEP_CRYPTO_NUM_AXI_MST - 1.
  typedef enum int unsigned {
    SEP_CRYPTO_AXI_ERR_SLV       = 0,
    SEP_CRYPTO_AXI_OTBN          = 1,
    SEP_CRYPTO_AXI_HMAC          = 2,
    SEP_CRYPTO_AXI_AES           = 3,
    SEP_CRYPTO_AXI_KMAC          = 4,
    SEP_CRYPTO_AXI_FUSE          = 5,
    SEP_CRYPTO_AXI_LIFECYCLE     = 6,
    SEP_CRYPTO_AXI_KM            = 7,
    SEP_CRYPTO_AXI_CSRNG         = 8,
    SEP_CRYPTO_AXI_EDN           = 9,
    SEP_CRYPTO_AXI_ENTROPY_SRC   = 10,
    SEP_CRYPTO_AXI_TRNG          = 11,
    SEP_CRYPTO_AXI_ABR           = 12
  } sep_crypto_axi_port_e;

  localparam int unsigned SEP_CRYPTO_NUM_AXI_MST = 13;
  localparam int unsigned SEP_CRYPTO_NUM_AXI_MST_SEL = $clog2(SEP_CRYPTO_NUM_AXI_MST);

  // AXI-Stream endpoints on u_drbg_s3c_scan edn_axis_o, one per ext-TRNG mux leg:
  // [0]=Key Manager (mux0), [1]=crypto adapter (mux1), [2]=entropy-pool adapter (mux2)
  localparam int unsigned SEP_CRYPTO_EDN_ENDPOINT_COUNT = 3;
  // Native EDN clients downstream of u_axis_edn_crypto_s3c_scan:
  // AES, KMAC, OTBN RND, OTBN URND
  localparam int unsigned SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT = 4;
  // Native EDN client downstream of u_axis_edn_pool_s3c_scan: the SEP entropy-pool FIFO
  localparam int unsigned SEP_CRYPTO_POOL_EDN_CLIENT_COUNT = 1;

  //////////
  // AXI4-Lite 32-bit typedefs for OTBN data width conversion
  //////////

  `include "axi/typedef.svh"


  //////////
  // OTBN PKA memory interface definitions (following sep_sram pattern)
  //////////

  // OTBN IMEM: 16 KB instruction memory with 39-bit words (32-bit data + 7-bit ECC)
  parameter int unsigned SEP_CRYPTO_PKA_IMEM_ADDR_WIDTH = 12;  // 4096 words (16KB).
  parameter int unsigned SEP_CRYPTO_PKA_IMEM_WORD_WIDTH = 39;

  typedef struct packed {
    logic         clk;      // Clock for external RAM.
    logic         enable;   // RAM request enable.
    logic         write;    // Write enable.
    logic [SEP_CRYPTO_PKA_IMEM_ADDR_WIDTH-1:0]  addr;     // Address (32-bit default, parameterizable).
    logic [SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0]  wdata;    // Write data (32-bit default, parameterizable).
    logic [SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0]  wmask;    // Write mask (32-bit default, parameterizable).
  } sep_crypto_pka_imem_sram_req_t;

  typedef struct packed {
    logic[SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0] rdata;
    logic q_valid;
  } sep_crypto_pka_imem_sram_rsp_t;

  // OTBN DMEM: 32 KB data memory with 312-bit words (32-bit data + 7-bit ECC) * 8
  // Total = OTBN_DMEM_SIZE (16KB bus-accessible) + DmemScratchSizeByte (16KB scratch)
  parameter int unsigned SEP_CRYPTO_PKA_DMEM_ADDR_WIDTH = 10;  // 1024 words (32KB).
  parameter int unsigned SEP_CRYPTO_PKA_DMEM_WORD_WIDTH = 39 * 8;

  typedef struct packed {
    logic         clk;      // Clock for external RAM.
    logic         enable;   // RAM request enable.
    logic         write;    // Write enable.
    logic [SEP_CRYPTO_PKA_DMEM_ADDR_WIDTH-1:0]  addr;     // Address.
    logic [SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0]  wdata;    // Write data.
    logic [SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0]  wmask;    // Write mask.
  } sep_crypto_pka_dmem_sram_req_t;

  typedef struct packed {
    logic [SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0] rdata;
  } sep_crypto_pka_dmem_sram_rsp_t;

  //////////
  // Adams Bridge (ABR) memory interface definitions
  //
  // These packed req/rsp structs mirror the `abr_mem_if` signal set (13 channels)
  // so the ABR SRAM can be threaded up out of sep as structs (OTBN convention
  // above), instead of a virtual interface crossing the sibling-module boundary
  // that the SRAM macros live behind.
  //
  // Widths are HARDCODED here (mirroring the OTBN geometry above) because this
  // package is compiled BEFORE the vendored abr_params_pkg / abr_ctrl_pkg in the
  // Bender source order, so it cannot import them. They are not optional at
  // elaboration though, so the mirror is pinned to the vendor source from both
  // ends: the g_abr_mem_* checks in sep_crypto_abr_wrapper.sv compare it against
  // the vendor parameters, and g_abr_mem_depth_check compares it against the
  // depths the SRAMs are actually built with. A vendor bump that changes any
  // depth/width fails the build instead of silently truncating. Update together.
  // Values derived from vendor/adams_bridge/src/abr_top/rtl/abr_params_pkg.sv and
  // abr_ctrl_pkg.sv:
  //   ABR_MEM_DATA_WIDTH  = COEFF_PER_CLK*MLDSA_Q_WIDTH = 4*24 = 96
  //   ABR_MEM_W1    : DEPTH=512  -> ADDR_W=9 ; DATA_W=4
  //   ABR_MEM_INST0 : DEPTH=832  -> ADDR_W=10; DATA_W=96
  //   ABR_MEM_INST1 : DEPTH=64   -> ADDR_W=6 ; DATA_W=96
  //   ABR_MEM_INST2 : DEPTH=1536 -> ADDR_W=11; DATA_W=96
  //   SK_MEM_BANK   : DEPTH=596  -> ADDR_W=10; DATA_W=ABR_REG_WIDTH=32
  //   SIG_Z_MEM     : DEPTH=224  -> ADDR_W=8 ; DATA_W=160; WSTROBE_W=20
  //   PK_MEM        : DEPTH=64   -> ADDR_W=6 ; DATA_W=320; WSTROBE_W=40
  //////////

  // Adams Bridge SRAM configuration
  parameter bit SEP_CRYPTO_ABR_MASKING_EN = 1'b1;
  parameter int unsigned SEP_CRYPTO_ABR_SRAM_LATENCY = 1;

  parameter int unsigned SEP_CRYPTO_ABR_MEM_DATA_W = 96;
  parameter int unsigned SEP_CRYPTO_ABR_W1_ADDR_W = 9;
  parameter int unsigned SEP_CRYPTO_ABR_W1_DATA_W = 4;
  parameter int unsigned SEP_CRYPTO_ABR_INST0_ADDR_W = 10;
  parameter int unsigned SEP_CRYPTO_ABR_INST1_ADDR_W = 6;
  parameter int unsigned SEP_CRYPTO_ABR_INST2_ADDR_W = 11;
  parameter int unsigned SEP_CRYPTO_ABR_SK_ADDR_W = 10;
  parameter int unsigned SEP_CRYPTO_ABR_SK_DATA_W = 32;
  parameter int unsigned SEP_CRYPTO_ABR_SIGZ_ADDR_W = 8;
  parameter int unsigned SEP_CRYPTO_ABR_SIGZ_DATA_W = 160;
  parameter int unsigned SEP_CRYPTO_ABR_SIGZ_WSTRB_W = 20;
  parameter int unsigned SEP_CRYPTO_ABR_PK_ADDR_W = 6;
  parameter int unsigned SEP_CRYPTO_ABR_PK_DATA_W = 320;
  parameter int unsigned SEP_CRYPTO_ABR_PK_WSTRB_W = 40;

  // Plain (no byte-enable) 96-bit memory request channel. Shared by mem_inst0
  // (10b addr), mem_inst1 (6b addr) and mem_inst2 (11b addr, the widest) + their
  // masked twins, so the addr fields are sized to the WIDEST (INST2=11b); the
  // narrower channels use the low bits and the unused MSBs stay zero.
  typedef struct packed {
    logic                                     we;
    logic [SEP_CRYPTO_ABR_INST2_ADDR_W-1:0]   waddr;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]     wdata;
    logic                                     re;
    logic [SEP_CRYPTO_ABR_INST2_ADDR_W-1:0]   raddr;
  } abr_mem_ch_req_t;

  // Byte-enabled memory request channel -- used for pk_mem (320b data, 6b addr,
  // 40b strobe). sig_z_mem (160b/8b/20b) differs in width so it has dedicated
  // fields in abr_mem_req_t below rather than reusing this type.
  typedef struct packed {
    logic                                     we;
    logic [SEP_CRYPTO_ABR_PK_ADDR_W-1:0]      waddr;
    logic [SEP_CRYPTO_ABR_PK_DATA_W-1:0]      wdata;
    logic [SEP_CRYPTO_ABR_PK_WSTRB_W-1:0]     wstrobe;
    logic                                     re;
    logic [SEP_CRYPTO_ABR_PK_ADDR_W-1:0]      raddr;
  } abr_mem_be_ch_req_t;

  // ABR memory request struct -- one field per `abr_mem_if` channel, req direction.
  typedef struct packed {
    // Clock carried alongside the request (OTBN convention) so the external
    // SRAM macros are clocked identically to abr_top regardless of any
    // crypto-clock gating between here and the wrapper.
    logic                                   clk;
    // w1_mem uses its own narrow addr/data; kept in dedicated fields.
    logic                                   w1_we;
    logic [SEP_CRYPTO_ABR_W1_ADDR_W-1:0]    w1_waddr;
    logic [SEP_CRYPTO_ABR_W1_DATA_W-1:0]    w1_wdata;
    logic                                   w1_re;
    logic [SEP_CRYPTO_ABR_W1_ADDR_W-1:0]    w1_raddr;
    // sk banks use narrow 32-bit data.
    logic                                   sk_bank0_we;
    logic [SEP_CRYPTO_ABR_SK_ADDR_W-1:0]    sk_bank0_waddr;
    logic [SEP_CRYPTO_ABR_SK_DATA_W-1:0]    sk_bank0_wdata;
    logic                                   sk_bank0_re;
    logic [SEP_CRYPTO_ABR_SK_ADDR_W-1:0]    sk_bank0_raddr;
    logic                                   sk_bank1_we;
    logic [SEP_CRYPTO_ABR_SK_ADDR_W-1:0]    sk_bank1_waddr;
    logic [SEP_CRYPTO_ABR_SK_DATA_W-1:0]    sk_bank1_wdata;
    logic                                   sk_bank1_re;
    logic [SEP_CRYPTO_ABR_SK_ADDR_W-1:0]    sk_bank1_raddr;
    // 96-bit coefficient memories (share abr_mem_ch_req_t geometry).
    abr_mem_ch_req_t                        mem_inst0_bank0;
    abr_mem_ch_req_t                        mem_inst0_bank1;
    abr_mem_ch_req_t                        mem_inst1;
    abr_mem_ch_req_t                        mem_inst2;
    abr_mem_ch_req_t                        mem_inst0_bank0_masked;
    abr_mem_ch_req_t                        mem_inst0_bank1_masked;
    abr_mem_ch_req_t                        mem_inst1_masked;
    abr_mem_ch_req_t                        mem_inst2_masked;
    // Byte-enabled memories.
    logic                                   sig_z_we;
    logic [SEP_CRYPTO_ABR_SIGZ_ADDR_W-1:0]  sig_z_waddr;
    logic [SEP_CRYPTO_ABR_SIGZ_DATA_W-1:0]  sig_z_wdata;
    logic [SEP_CRYPTO_ABR_SIGZ_WSTRB_W-1:0] sig_z_wstrobe;
    logic                                   sig_z_re;
    logic [SEP_CRYPTO_ABR_SIGZ_ADDR_W-1:0]  sig_z_raddr;
    abr_mem_be_ch_req_t                     pk_mem;
  } abr_mem_req_t;

  // ABR memory response struct -- one rdata field per `abr_mem_if` channel.
  typedef struct packed {
    logic [SEP_CRYPTO_ABR_W1_DATA_W-1:0]    w1_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst0_bank0_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst0_bank1_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst1_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst2_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst0_bank0_masked_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst0_bank1_masked_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst1_masked_rdata;
    logic [SEP_CRYPTO_ABR_MEM_DATA_W-1:0]   mem_inst2_masked_rdata;
    logic [SEP_CRYPTO_ABR_SK_DATA_W-1:0]    sk_bank0_rdata;
    logic [SEP_CRYPTO_ABR_SK_DATA_W-1:0]    sk_bank1_rdata;
    logic [SEP_CRYPTO_ABR_SIGZ_DATA_W-1:0]  sig_z_rdata;
    logic [SEP_CRYPTO_ABR_PK_DATA_W-1:0]    pk_rdata;
  } abr_mem_rsp_t;

  typedef logic sep_crypto_fuse_req_t;
  typedef logic sep_crypto_fuse_rsp_t;

  //////////
  // External TRNG AXI-Stream interface (from outside sep → sep_crypto)
  //////////

  localparam int unsigned EXT_TRNG_AXIS_DATA_WIDTH = 32;
  localparam int unsigned EXT_TRNG_AXIS_STRB_WIDTH = EXT_TRNG_AXIS_DATA_WIDTH / 8;

  typedef struct packed {
    logic                                    tvalid;
    logic [EXT_TRNG_AXIS_DATA_WIDTH-1:0]     tdata;
    logic [EXT_TRNG_AXIS_STRB_WIDTH-1:0]     tstrb;
  } ext_trng_axis_req_t;

  typedef struct packed {logic tready;} ext_trng_axis_rsp_t;

endpackage
