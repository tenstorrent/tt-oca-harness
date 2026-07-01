// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SEP Crypto submodule typedefs and parameters
//
//-----------------------------------------------------------------------------

package sep_crypto_pkg;

    import sep_pkg::*;

    // import otbn_pkg::*;
    import lc_ctrl_pkg::*;
    import edn_pkg::*;
    import otp_ctrl_pkg::*;
    import keymgr_pkg::*;
    import prim_ram_1p_pkg::*;


    parameter axi_pkg::xbar_rule_32_t otbn_rule = '{
        idx:        0,
        start_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_OTBN_BASE_ADDR,
        end_addr:   och_sep_top_addrmap_pkg::OCH_SEP_TOP_OTBN_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_OTBN_SIZE
    };

    parameter axi_pkg::xbar_rule_32_t hmac_rule = '{
        idx:        1,
        start_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_HMAC_BASE_ADDR,
        end_addr:   och_sep_top_addrmap_pkg::OCH_SEP_TOP_HMAC_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_HMAC_SIZE
    };

    parameter axi_pkg::xbar_rule_32_t aes_rule = '{
        idx:        2,
        start_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_AES_BASE_ADDR,
        end_addr:   och_sep_top_addrmap_pkg::OCH_SEP_TOP_AES_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_AES_SIZE   // 256 bytes for AES
    };

    parameter axi_pkg::xbar_rule_32_t kmac_rule = '{
        idx:        3,
        start_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_KMAC_BASE_ADDR,
        end_addr:   och_sep_top_addrmap_pkg::OCH_SEP_TOP_KMAC_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_KMAC_SIZE
    };

    parameter axi_pkg::xbar_rule_32_t fuse_rule = '{
        idx:        4,
        start_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR,
        end_addr:   och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_SHIM_CTRL_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_EFUSE_SHIM_CTRL_SIZE  // 1 KB for Fuse +
    };

    parameter axi_pkg::xbar_rule_32_t lifecycle_rule = '{
        idx:        5,
        start_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_BASE_ADDR,
        end_addr:   och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_BASE_ADDR + och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_LIFECYCLE_CTRL_SIZE
    };

    parameter axi_pkg::xbar_rule_32_t km_rule = '{
        idx:        6,
        start_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_KM_MAILBOX_SEP_BASE_ADDR,
        end_addr:   och_sep_top_addrmap_pkg::OCH_SEP_TOP_KM_MAILBOX_SEP_BASE_ADDR + 32'h0000_1000  // 4KB decode window
    };

    // DRBG: spec allocates 0x1091_5000-0x1091_5FFF (4KB), split into CSRNG + EDN
    localparam logic [31:0] DRBG_CSRNG_BASE_ADDR = 32'h1091_5000;
    localparam logic [31:0] DRBG_EDN_BASE_ADDR   = 32'h1091_5800;

    parameter axi_pkg::xbar_rule_32_t csrng_rule = '{
        idx:        7,
        start_addr: DRBG_CSRNG_BASE_ADDR,
        end_addr:   DRBG_EDN_BASE_ADDR
    };

    parameter axi_pkg::xbar_rule_32_t edn_rule = '{
        idx:        8,
        start_addr: DRBG_EDN_BASE_ADDR,
        end_addr:   32'h1091_6000
    };

    // ESRC: OCH spec 0x1091_6000–0x1091_6FFF (4 kB)
    localparam logic [31:0] ENTROPY_SOURCE_BASE_ADDR = 32'h1091_6000;
    localparam logic [31:0] ENTROPY_SOURCE_END_ADDR  = 32'h1091_7000;

    parameter axi_pkg::xbar_rule_32_t entropy_source_rule = '{
        idx:        9,
        start_addr: ENTROPY_SOURCE_BASE_ADDR,
        end_addr:   ENTROPY_SOURCE_END_ADDR
    };

    // TRNG: OCH spec 0x1091_7000–0x1091_7FFF (4 kB) — passthrough to sep_ip_integration
    localparam logic [31:0] TRNG_BASE_ADDR = 32'h1091_7000;
    localparam logic [31:0] TRNG_END_ADDR  = 32'h1091_8000;

    parameter axi_pkg::xbar_rule_32_t trng_rule = '{
        idx:        10,
        start_addr: TRNG_BASE_ADDR,
        end_addr:   TRNG_END_ADDR
    };

    // AXI demux port indices (must match axi_demux master port order in sep_crypto.sv).
    // Highest enum value must equal SEP_CRYPTO_NUM_AXI_MST - 1.
    typedef enum int unsigned {
        SepCryptoAxiErrSlv       = 0,
        SepCryptoAxiOtbn         = 1,
        SepCryptoAxiHmac         = 2,
        SepCryptoAxiAes          = 3,
        SepCryptoAxiKmac         = 4,
        SepCryptoAxiFuse         = 5,
        SepCryptoAxiLifecycle    = 6,
        SepCryptoAxiKm           = 7,
        SepCryptoAxiCsrng        = 8,
        SepCryptoAxiEdn          = 9,
        SepCryptoAxiEntropySrc   = 10,
        SepCryptoAxiTrng         = 11
    } sep_crypto_axi_port_e;

    localparam int unsigned SEP_CRYPTO_NUM_AXI_MST     = 12;
    localparam int unsigned SEP_CRYPTO_NUM_AXI_MST_SEL = $clog2(SEP_CRYPTO_NUM_AXI_MST);

    /** @brief AXI-Stream endpoints on u_drbg edn_axis_o: [0]=Key Manager (via mux0), [1]=crypto adapter (via mux1) */
    localparam int unsigned SEP_CRYPTO_EDN_ENDPOINT_COUNT = 2;
    /** @brief Native EDN clients downstream of u_axis_edn_crypto: AES, KMAC, OTBN RND, OTBN URND */
    localparam int unsigned SEP_CRYPTO_AXIS_EDN_CLIENT_COUNT = 4;
    /** @brief Native EDN ports on u_drbg (bypass AXI-Stream adapter); 0 — crypto use u_axis_edn_crypto only */
    localparam int unsigned SEP_CRYPTO_DRBG_NATIVE_CLIENT_COUNT = 0;

    //////////
    // AXI4-Lite 32-bit typedefs for OTBN data width conversion
    //////////

    `include "axi/typedef.svh"


    //////////
    // OTBN PKA memory interface definitions (following sep_sram pattern)
    //////////

    // OTBN IMEM: 16 KB instruction memory with 39-bit words (32-bit data + 7-bit ECC)
    parameter int unsigned SEP_CRYPTO_PKA_IMEM_ADDR_WIDTH = 12;  // 4096 words (16KB)
    parameter int unsigned SEP_CRYPTO_PKA_IMEM_WORD_WIDTH = 39;

    typedef struct packed {
        logic         clk;      // Clock for external RAM
        logic         enable;   // RAM request enable
        logic         write;    // Write enable
        logic [SEP_CRYPTO_PKA_IMEM_ADDR_WIDTH-1:0]  addr;     // Address (32-bit default, parameterizable)
        logic [SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0]  wdata;    // Write data (32-bit default, parameterizable)
        logic [SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0]  wmask;    // Write mask (32-bit default, parameterizable)
    } sep_crypto_pka_imem_sram_req_t;

    typedef struct packed {
        logic[SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0] rdata;
        logic q_valid;
    } sep_crypto_pka_imem_sram_rsp_t;

    // OTBN DMEM: 32 KB data memory with 312-bit words (32-bit data + 7-bit ECC) * 8
    // Total = OTBN_DMEM_SIZE (16KB bus-accessible) + DmemScratchSizeByte (16KB scratch)
    parameter int unsigned SEP_CRYPTO_PKA_DMEM_ADDR_WIDTH = 10;  // 1024 words (32KB)
    parameter int unsigned SEP_CRYPTO_PKA_DMEM_WORD_WIDTH = 39*8;

    typedef struct packed {
        logic         clk;      // Clock for external RAM
        logic         enable;   // RAM request enable
        logic         write;    // Write enable
        logic [SEP_CRYPTO_PKA_DMEM_ADDR_WIDTH-1:0]  addr;     // Address
        logic [SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0]  wdata;    // Write data
        logic [SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0]  wmask;    // Write mask
    } sep_crypto_pka_dmem_sram_req_t;

    typedef struct packed {
        logic[SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0] rdata;
    } sep_crypto_pka_dmem_sram_rsp_t;

    typedef logic sep_crypto_fuse_req_t;
    typedef logic sep_crypto_fuse_rsp_t;

    //////////
    // External TRNG AXI-Stream interface (from sep_ip_integration → sep_crypto)
    //////////

    localparam int unsigned EXT_TRNG_AXIS_DATA_WIDTH = 32;
    localparam int unsigned EXT_TRNG_AXIS_STRB_WIDTH = EXT_TRNG_AXIS_DATA_WIDTH / 8;

    typedef struct packed {
        logic                                    tvalid;
        logic [EXT_TRNG_AXIS_DATA_WIDTH-1:0]     tdata;
        logic [EXT_TRNG_AXIS_STRB_WIDTH-1:0]     tstrb;
    } ext_trng_axis_req_t;

    typedef struct packed {
        logic tready;
    } ext_trng_axis_rsp_t;

    // TODO: Config struct enabling/disabling the instantiation of specific sub-modules

endpackage
