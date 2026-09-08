// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

package sep_efuse_pkg;
  import och_sep_top_addrmap_pkg::*;

  function automatic int unsigned efuse_offset(input longint unsigned addr);
    return int'(addr - och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BASE_ADDR);
  endfunction

  // -------------------------------------------------------------------------
  // Per-register shadow typedefs.
  // Field order: MSB first (packed struct convention).
  // -------------------------------------------------------------------------

  // LOCKS — 64-bit register (regwidth=64; accesswidth=64), slots 0-31.
  // Each field n owns write-lock at bit 2n, read-lock at bit 2n+1.
  //   Slots  0-28 : original fields (LC_STATE through SIP_PUBK_PQC_HASH1) — bits [0:57]
  //   Slots 29-31 : v0.5.22 identity fuses (SEP_CHIPLET_ID / SIP / SYS)  — bits [58:63]
  // Slots 32-39 (spare0-spare7) and unassigned slots 40-47 live in LOCKS_SPARE.
  typedef struct packed {
    logic [0:0]   sep_sys_id_read_lock ;                // [63]     slot 31
    logic [0:0]   sep_sys_id_write_lock ;               // [62]     slot 31
    logic [0:0]   sep_sip_id_read_lock ;                // [61]     slot 30
    logic [0:0]   sep_sip_id_write_lock ;               // [60]     slot 30
    logic [0:0]   sep_chiplet_id_read_lock ;            // [59]     slot 29
    logic [0:0]   sep_chiplet_id_write_lock ;           // [58]     slot 29
    logic [0:0]   sip_pubk_pqc_hash1_read_lock ;       // [57]     slot 28
    logic [0:0]   sip_pubk_pqc_hash1_write_lock ;      // [56]     slot 28
    logic [0:0]   sip_pubk_hash1_read_lock ;            // [55]     slot 27
    logic [0:0]   sip_pubk_hash1_write_lock ;           // [54]     slot 27
    logic [0:0]   sys_pubk_pqc_hash_read_lock ;        // [53]     slot 26
    logic [0:0]   sys_pubk_pqc_hash_write_lock ;       // [52]     slot 26
    logic [0:0]   sip_pubk_pqc_hash0_read_lock ;       // [51]     slot 25
    logic [0:0]   sip_pubk_pqc_hash0_write_lock ;      // [50]     slot 25
    logic [0:0]   chiplet_pubk_pqc_hash1_read_lock ;   // [49]     slot 24
    logic [0:0]   chiplet_pubk_pqc_hash1_write_lock ;  // [48]     slot 24
    logic [0:0]   chiplet_pubk_pqc_hash0_read_lock ;   // [47]     slot 23
    logic [0:0]   chiplet_pubk_pqc_hash0_write_lock ;  // [46]     slot 23
    logic [0:0]   required_algs_read_lock ;             // [45]     slot 22
    logic [0:0]   required_algs_write_lock ;            // [44]     slot 22
    logic [0:0]   required_signers_read_lock ;          // [43]     slot 21
    logic [0:0]   required_signers_write_lock ;         // [42]     slot 21
    logic [0:0]   chiplet_pubk_hash1_read_lock ;        // [41]     slot 20
    logic [0:0]   chiplet_pubk_hash1_write_lock ;       // [40]     slot 20
    logic [0:0]   chiplet_pubk_hash0_read_lock ;        // [39]     slot 19
    logic [0:0]   chiplet_pubk_hash0_write_lock ;       // [38]     slot 19
    logic [0:0]   spi_config_en_read_lock ;             // [37]     slot 18
    logic [0:0]   spi_config_en_write_lock ;            // [36]     slot 18
    logic [0:0]   rom_ctl_read_lock ;                   // [35]     slot 17
    logic [0:0]   rom_ctl_write_lock ;                  // [34]     slot 17
    logic [0:0]   status_rpt_read_lock ;                // [33]     slot 16
    logic [0:0]   status_rpt_write_lock ;               // [32]     slot 16
    logic [0:0]   sys_uid_read_lock ;                   // [31]     slot 15
    logic [0:0]   sys_uid_write_lock ;                  // [30]     slot 15
    logic [0:0]   sys_pubk_hash_read_lock ;             // [29]     slot 14
    logic [0:0]   sys_pubk_hash_write_lock ;            // [28]     slot 14
    logic [0:0]   sip_uid_read_lock ;                   // [27]     slot 13
    logic [0:0]   sip_uid_write_lock ;                  // [26]     slot 13
    logic [0:0]   sip_pubk_hash0_read_lock ;            // [25]     slot 12
    logic [0:0]   sip_pubk_hash0_write_lock ;           // [24]     slot 12
    logic [0:0]   chiplet_uid_read_lock ;               // [23]     slot 11
    logic [0:0]   chiplet_uid_write_lock ;              // [22]     slot 11
    logic [0:0]   bl2_version_read_lock ;               // [21]     slot 10
    logic [0:0]   bl2_version_write_lock ;              // [20]     slot 10
    logic [0:0]   bl1_version_read_lock ;               // [19]     slot  9
    logic [0:0]   bl1_version_write_lock ;              // [18]     slot  9
    logic [0:0]   chiplet_pubk_revoke_read_lock ;       // [17]     slot  8
    logic [0:0]   chiplet_pubk_revoke_write_lock ;      // [16]     slot  8
    logic [0:0]   class_key_read_lock ;                 // [15]     slot  7
    logic [0:0]   class_key_write_lock ;                // [14]     slot  7
    logic [0:0]   rma_chiplet_token_digest_read_lock ;  // [13]     slot  6
    logic [0:0]   rma_chiplet_token_digest_write_lock ; // [12]     slot  6
    logic [0:0]   rma_sip_token_digest_read_lock ;      // [11]     slot  5
    logic [0:0]   rma_sip_token_digest_write_lock ;     // [10]     slot  5
    logic [0:0]   sys_dis_read_lock ;                   // [9]      slot  4
    logic [0:0]   sys_dis_write_lock ;                  // [8]      slot  4
    logic [0:0]   sip_dis_read_lock ;                   // [7]      slot  3
    logic [0:0]   sip_dis_write_lock ;                  // [6]      slot  3
    logic [0:0]   transient_rma_en_read_lock ;          // [5]      slot  2
    logic [0:0]   transient_rma_en_write_lock ;         // [4]      slot  2
    logic [0:0]   sboot_dis_read_lock ;                 // [3]      slot  1
    logic [0:0]   sboot_dis_write_lock ;                // [2]      slot  1
    logic [0:0]   lc_state_read_lock ;                  // [1]      slot  0
    logic [0:0]   lc_state_write_lock ;                 // [0]      slot  0
  } sep_efuse_map_locks_reg_t;

  // LOCKS_SPARE — 32-bit register (regwidth=32; accesswidth=32), slots 32-47.
  //   [15:0]  slots 32-39: spare0-spare7 write/read lock pairs
  //   [31:16] slots 40-47: unassigned, reserved for future lock slots
  typedef struct packed {
    logic [15:0]  spare_lock_rsvd ;      // [31:16] slots 40-47, unassigned
    logic [0:0]   spare7_read_lock ;     // [15]    slot 39
    logic [0:0]   spare7_write_lock ;    // [14]    slot 39
    logic [0:0]   spare6_read_lock ;     // [13]    slot 38
    logic [0:0]   spare6_write_lock ;    // [12]    slot 38
    logic [0:0]   spare5_read_lock ;     // [11]    slot 37
    logic [0:0]   spare5_write_lock ;    // [10]    slot 37
    logic [0:0]   spare4_read_lock ;     // [9]     slot 36
    logic [0:0]   spare4_write_lock ;    // [8]     slot 36
    logic [0:0]   spare3_read_lock ;     // [7]     slot 35
    logic [0:0]   spare3_write_lock ;    // [6]     slot 35
    logic [0:0]   spare2_read_lock ;     // [5]     slot 34
    logic [0:0]   spare2_write_lock ;    // [4]     slot 34
    logic [0:0]   spare1_read_lock ;     // [3]     slot 33
    logic [0:0]   spare1_write_lock ;    // [2]     slot 33
    logic [0:0]   spare0_read_lock ;     // [1]     slot 32
    logic [0:0]   spare0_write_lock ;    // [0]     slot 32
  } sep_efuse_map_locks_spare_reg_t;

  typedef struct packed {
    logic [23:0]   rsvd ;
    logic [7:0]   lc_state ;
  } sep_efuse_map_lc_state_reg_t;



  typedef struct packed {
    logic [30:0]   rsvd ;
    logic [0:0]   disable_secure_boot ;
  } sep_efuse_map_sboot_dis_reg_t;



  typedef struct packed {
    logic [30:0]   rsvd ;
    logic [0:0]   transient_rma_en ;
  } sep_efuse_map_transient_rma_en_reg_t;



  // LC_DISABLE / feature-control disable vector.
  // Spec: the Disable Vector Format section of lifecycle_controller.adoc.
  // 1'b1 = feature disabled; feat_ctrl_o is inverted (enable polarity).
  // Groups:
  //   DBG_1 [23:0]  — gated by DEMOTE_1 (local debug)
  //   DBG_2 [47:24] — gated by DEMOTE_2 (inter-chiplet debug bypass)
  //   Func  [63:48] — always gated by SIP_DIS/SYS_DIS per LC state
  typedef struct packed {
    logic [15:0]  func_reserved ;         // [63:48] Function group
    logic [22:0]  debug_reserved_dbg2 ;   // [47:25] DBG_2 reserved
    logic [0:0]   sip_debug ;             // [24]    SIP_DBG (DBG_2)
    logic [19:0]  debug_reserved_dbg1 ;   // [23:4]  DBG_1 reserved
    logic [0:0]   smc_fuse_dbg ;          // [3]     SMC_FUSE_DBG (DBG_1)
    logic [0:0]   sep_fuse_dbg ;          // [2]     SEP_FUSE_DBG (DBG_1)
    logic [0:0]   chiplet_dbg ;           // [1]     CHIPLET_DBG (DBG_1)
    logic [0:0]   sep_debug ;             // [0]     SEP_DBG (DBG_1)
  } sep_efuse_map_lc_disable_reg_t;



  typedef struct packed {logic [255:0] token_digest;} sep_efuse_map_rma_sip_token_digest_reg_t;



  typedef struct packed {logic [255:0] token_digest;} sep_efuse_map_rma_chiplet_token_digest_reg_t;



  typedef struct packed {logic [255:0] key;} sep_efuse_map_class_key_reg_t;



  typedef struct packed {logic [31:0] select;} sep_efuse_map_chiplet_pubk_revoke_reg_t;



  typedef struct packed {logic [255:0] version;} sep_efuse_map_bl1_version_reg_t;



  typedef struct packed {logic [255:0] version;} sep_efuse_map_bl2_version_reg_t;



  typedef struct packed {logic [255:0] uid;} sep_efuse_map_chiplet_uid_reg_t;



  typedef struct packed {logic [255:0] key_hash;} sep_efuse_map_sip_pubk_hash_reg_t;



  typedef struct packed {logic [255:0] uid;} sep_efuse_map_sip_uid_reg_t;



  typedef struct packed {logic [255:0] key_hash;} sep_efuse_map_sys_pubk_hash_reg_t;



  typedef struct packed {logic [255:0] uid;} sep_efuse_map_sys_uid_reg_t;



  typedef struct packed {
    logic [29:0]   reserved ;
    logic [1:0]   rpt ;
  } sep_efuse_map_status_rpt_reg_t;



  typedef struct packed {
    logic [25:0]   reserved ;
    logic [4:0]    rom_swap_ctrl ;
    logic [0:0]    rom_endianness_ctrl ;
  } sep_efuse_map_rom_ctl_reg_t;



  typedef struct packed {
    logic [12:0]   spi_control_field_en_rsvd ;
    logic [10:0]   smu_pll_sysclk ;
    logic [7:0]    spi_control_field_en ;
  } sep_efuse_map_sep_spi_ctrl_field_en_reg_t;



  typedef struct packed {logic [31:0] discovery;} sep_efuse_map_spi_discovery_ctrl_reg_t;



  typedef struct packed {logic [31:0] dq_timing;} sep_efuse_map_spi_phy_dq_timing_reg_t;



  typedef struct packed {logic [31:0] dqs_timing;} sep_efuse_map_spi_phy_dqs_timing_reg_t;



  typedef struct packed {logic [31:0] gate_lpbk;} sep_efuse_map_spi_phy_gate_lpbk_reg_t;



  typedef struct packed {logic [31:0] dll_slave;} sep_efuse_map_spi_phy_dll_slave_reg_t;



  typedef struct packed {logic [31:0] dll_master;} sep_efuse_map_spi_phy_dll_master_reg_t;



  typedef struct packed {logic [31:0] misc;} sep_efuse_map_spi_phy_misc_reg_t;



  typedef struct packed {logic [31:0] rb_valid_time;} sep_efuse_map_spi_rb_valid_time_reg_t;



  // Signing-model key hashes (256-bit, field name: key_hash)
  typedef struct packed {logic [255:0] key_hash;} sep_efuse_map_chiplet_pubk_hash_reg_t;



  typedef struct packed {
    logic [29:0]   reserved ;
    logic [1:0]    required_signers ;
  } sep_efuse_map_required_signers_v_t;



  typedef struct packed {
    logic [19:0]   reserved ;
    logic [3:0]    sys_algs ;
    logic [3:0]    sip_algs ;
    logic [3:0]    chiplet_algs ;
  } sep_efuse_map_required_algs_reg_t;



  typedef struct packed {logic [255:0] key_hash;} sep_efuse_map_pqc_hash_reg_t;



  // v0.5.22 public identity fuses (SEP_CHIPLET_ID / SEP_SIP_ID / SEP_SYS_ID)
  typedef struct packed {logic [255:0] id;} sep_efuse_map_sep_id_reg_t;



  // v0.5.22 individually-lockable 256-bit spare fields
  typedef struct packed {logic [255:0] rsvd;} sep_efuse_map_spare_256_reg_t;



  // -------------------------------------------------------------------------
  // Full shadow-register map (packed, MSB = highest address).
  // Total size must equal NumEfuseBits = 8192.
  // -------------------------------------------------------------------------
  typedef struct packed {
    // 0x3e0: spare7 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare7 ;
    // 0x3c0: spare6 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare6 ;
    // 0x3a0: spare5 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare5 ;
    // 0x380: spare4 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare4 ;
    // 0x360: spare3 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare3 ;
    // 0x340: spare2 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare2 ;
    // 0x320: spare1 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare1 ;
    // 0x300: spare0 (256 bits)
    sep_efuse_map_spare_256_reg_t              spare0 ;
    // 0x2e0: SEP_SYS_ID (256 bits)
    sep_efuse_map_sep_id_reg_t                 sep_sys_id ;
    // 0x2c0: SEP_SIP_ID (256 bits)
    sep_efuse_map_sep_id_reg_t                 sep_sip_id ;
    // 0x2a0: SEP_CHIPLET_ID (256 bits)
    sep_efuse_map_sep_id_reg_t                 sep_chiplet_id ;
    // 0x280: SIP_PUBK_PQC_HASH1 (256 bits)
    sep_efuse_map_pqc_hash_reg_t               sip_pubk_pqc_hash1 ;
    // 0x260: SIP_PUBK_HASH1 (256 bits)
    sep_efuse_map_sip_pubk_hash_reg_t          sip_pubk_hash1 ;
    // 0x240: SYS_PUBK_PQC_HASH (256 bits)
    sep_efuse_map_pqc_hash_reg_t               sys_pubk_pqc_hash ;
    // 0x220: SIP_PUBK_PQC_HASH0 (256 bits)
    sep_efuse_map_pqc_hash_reg_t               sip_pubk_pqc_hash0 ;
    // 0x200: CHIPLET_PUBK_PQC_HASH1 (256 bits)
    sep_efuse_map_pqc_hash_reg_t               chiplet_pubk_pqc_hash1 ;
    // 0x1e0: CHIPLET_PUBK_PQC_HASH0 (256 bits)
    sep_efuse_map_pqc_hash_reg_t               chiplet_pubk_pqc_hash0 ;
    // 0x1dc: REQUIRED_ALGS (32 bits)
    sep_efuse_map_required_algs_reg_t          required_algs ;
    // 0x1d8: REQUIRED_SIGNERS (32 bits)
    sep_efuse_map_required_signers_v_t         required_signers ;
    // 0x1b8: CHIPLET_PUBK_HASH1 (256 bits)
    sep_efuse_map_chiplet_pubk_hash_reg_t      chiplet_pubk_hash1 ;
    // 0x198: CHIPLET_PUBK_HASH0 (256 bits)
    sep_efuse_map_chiplet_pubk_hash_reg_t      chiplet_pubk_hash0 ;
    // 0x194: SPI_RB_VALID_TIME (32 bits)
    sep_efuse_map_spi_rb_valid_time_reg_t      spi_rb_valid_time ;
    // 0x190: SPI_PHY_MISC (32 bits)
    sep_efuse_map_spi_phy_misc_reg_t           spi_phy_misc ;
    // 0x18c: SPI_PHY_DLL_MASTER (32 bits)
    sep_efuse_map_spi_phy_dll_master_reg_t     spi_phy_dll_master ;
    // 0x188: SPI_PHY_DLL_SLAVE (32 bits)
    sep_efuse_map_spi_phy_dll_slave_reg_t      spi_phy_dll_slave ;
    // 0x184: SPI_PHY_GATE_LPBK (32 bits)
    sep_efuse_map_spi_phy_gate_lpbk_reg_t      spi_phy_gate_lpbk ;
    // 0x180: SPI_PHY_DQS_TIMING (32 bits)
    sep_efuse_map_spi_phy_dqs_timing_reg_t     spi_phy_dqs_timing ;
    // 0x17c: SPI_PHY_DQ_TIMING (32 bits)
    sep_efuse_map_spi_phy_dq_timing_reg_t      spi_phy_dq_timing ;
    // 0x178: SPI_DISCOVERY_CTRL (32 bits)
    sep_efuse_map_spi_discovery_ctrl_reg_t     spi_discovery_ctrl ;
    // 0x174: SEP_SPI_CTRL_FIELD_EN (32 bits)
    sep_efuse_map_sep_spi_ctrl_field_en_reg_t  sep_spi_ctrl_field_en ;
    // 0x170: ROM_CTL (32 bits)
    sep_efuse_map_rom_ctl_reg_t                rom_ctl ;
    // 0x16c: STATUS_RPT (32 bits)
    sep_efuse_map_status_rpt_reg_t             status_rpt ;
    // 0x14c: SYS_UID (256 bits)
    sep_efuse_map_sys_uid_reg_t                sys_uid ;
    // 0x12c: SYS_PUBK_HASH (256 bits)
    sep_efuse_map_sys_pubk_hash_reg_t          sys_pubk_hash ;
    // 0x10c: SIP_UID (256 bits)
    sep_efuse_map_sip_uid_reg_t                sip_uid ;
    // 0xec: SIP_PUBK_HASH0 (256 bits)
    sep_efuse_map_sip_pubk_hash_reg_t          sip_pubk_hash0 ;
    // 0xcc: CHIPLET_UID (256 bits)
    sep_efuse_map_chiplet_uid_reg_t            chiplet_uid ;
    // 0xac: BL2_VERSION (256 bits)
    sep_efuse_map_bl2_version_reg_t            bl2_version ;
    // 0x8c: BL1_VERSION (256 bits)
    sep_efuse_map_bl1_version_reg_t            bl1_version ;
    // 0x88: CHIPLET_PUBK_REVOKE (32 bits)
    sep_efuse_map_chiplet_pubk_revoke_reg_t    chiplet_pubk_revoke ;
    // 0x68: CLASS_KEY (256 bits)
    sep_efuse_map_class_key_reg_t              class_key ;
    // 0x48: RMA_CHIPLET_TOKEN_DIGEST (256 bits)
    sep_efuse_map_rma_chiplet_token_digest_reg_t rma_chiplet_token_digest ;
    // 0x28: RMA_SIP_TOKEN_DIGEST (256 bits)
    sep_efuse_map_rma_sip_token_digest_reg_t   rma_sip_token_digest ;
    // 0x20: SYS_DIS (64 bits)
    sep_efuse_map_lc_disable_reg_t             sys_dis ;
    // 0x18: SIP_DIS (64 bits)
    sep_efuse_map_lc_disable_reg_t             sip_dis ;
    // 0x14: TRANSIENT_RMA_EN (32 bits)
    sep_efuse_map_transient_rma_en_reg_t       transient_rma_en ;
    // 0x10: SBOOT_DIS (32 bits)
    sep_efuse_map_sboot_dis_reg_t              sboot_dis ;
    // 0x0c: LC_STATE (32 bits)
    sep_efuse_map_lc_state_reg_t               lc_state ;
    // 0x08: LOCKS_SPARE (32 bits)
    sep_efuse_map_locks_spare_reg_t            locks_spare ;
    // 0x00: LOCKS (64 bits)
    sep_efuse_map_locks_reg_t                  locks ;
  } sep_efuse_map_regmap_t;
  `include "apb/typedef.svh"
  `include "axi/typedef.svh"
  `include "efuse_typedef.svh"

  // Physical fuse array size: 8192 bits = 1024 bytes = 256 × 32-bit words.
  // Map spans 0x0 (LOCKS) through 0x3FF (end of spare7), ending at 0x400.
  localparam int unsigned NumEfuseBits = 8 * 1024;  // 8192
  localparam int unsigned NumFuseWordWidth = 32;

  localparam int unsigned NumFuseWords = NumEfuseBits / NumFuseWordWidth;  // 256
  localparam int unsigned NumFuseWordBytes = NumFuseWordWidth / 8;
  localparam int unsigned NumFuseBytes = NumFuseWords * NumFuseWordBytes;  // 1024

  localparam int unsigned NumFuseBitsWidth = $clog2(NumEfuseBits);
  localparam int unsigned NumFuseByteWidth = $clog2(NumFuseBytes);
  // NOTE: $clog2(256)=8 can only represent 0-255, but we need to represent 256 words
  // Add 1 to ensure we can hold NumFuseWords itself (not just NumFuseWords-1)
  localparam int unsigned NumFuseWordsWidth = $clog2(NumFuseWords + 1);
  localparam int unsigned SHADOW_REG_BITS = NumEfuseBits;

  typedef logic [NumFuseBitsWidth-1:0] efuse_addr_bit_t;
  typedef logic [NumFuseByteWidth-1:0] efuse_addr_byte_t;
  typedef logic [NumFuseWordWidth-1:0] efuse_data_t;
  typedef logic [NumFuseWordsWidth-1:0] efuse_word_counter_t;

  // Common interface types for efuse commands and responses
  `EFUSE_COMMAND_REQ_T(fuse_command_req_t, efuse_addr_bit_t, efuse_data_t, efuse_word_counter_t,
                       efuse_pkg::fuse_command_e)
  `EFUSE_COMMAND_RESP_T(fuse_command_resp_t, efuse_data_t)

  // AXILite interface types
  localparam int unsigned ADDR_WIDTH = 32;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;
  typedef logic [ADDR_WIDTH    -1:0] addr_t;
  typedef logic [DATA_WIDTH    -1:0] data_t;
  typedef logic [STRB_WIDTH    -1:0] strb_t;
  `AXI_LITE_TYPEDEF_ALL(efuse_axil, addr_t, data_t, strb_t)
  `APB_TYPEDEF_ALL(efuse_apb, addr_t, data_t, strb_t)

  // 40 real lockable fields (idx 0-39) + LOCKS meta-field (idx 6'h3F).
  //   Slots  0-28 : original fields (LC_STATE through SIP_PUBK_PQC_HASH1)
  //   Slots 29-31 : v0.5.22 identity fuses (SEP_CHIPLET_ID, SEP_SIP_ID, SEP_SYS_ID)
  //   Slots 32-39 : v0.5.22 spare fields (spare0-spare7)
  //   LOCKS_META_IDX (6'h3F): fixed sentinel for the LOCKS/LOCKS_SPARE meta-entry.
  //                 Hardware never applies lock bits to this entry. The idx is the
  //                 max 6-bit value so it cannot collide with a real field slot,
  //                 regardless of how many real fields are added in future.
  //                 Unassigned lock slots 40-47 live in LOCKS_SPARE[31:16].
  localparam int unsigned NUM_EFUSE_FIELDS = 41;
  localparam logic [efuse_pkg::EFUSE_FIELD_MAP_IDX_WIDTH-1:0] LOCKS_META_IDX = '1;
  localparam logic [1:0] WRITE_LOCK = 2'b11;
  localparam logic [1:0] WRITE_UNLOCK = 2'b00;
  localparam logic [1:0] WRITE_SET_ONLY = 2'b10;
  localparam logic READ_LOCK = 1'b1;
  localparam logic READ_UNLOCK = 1'b0;
  localparam logic SECURE_TM_LOCK = 1'b1;
  localparam logic SECURE_TM_UNLOCK = 1'b0;

  // Physical OTP bits covered by LOCKS + LOCKS_SPARE (the 96-bit lock field).
  // LOCKS (64-bit) occupies OTP words 0-1, LOCKS_SPARE (32-bit) occupies word 2.
  // Class1ShadowRanges uses LOCKS_BASE_ADDR with LockFieldBits to cover all three
  // words, keeping the physical OTP ↔ APB word index 1-to-1.
  localparam int unsigned LockFieldBits = $bits(
      sep_efuse_map_locks_reg_t
  ) + $bits(
      sep_efuse_map_locks_spare_reg_t
  );  // 96

  // efuse_lock_view_t presents the efuse_map_t union with the full 96-bit
  // lock field at the LSB end, mirroring where LOCKS/LOCKS_SPARE sit in the
  // packed struct. locks[79:0] holds the 80 meaningful lock-pair bits (slots 0-39);
  // locks[95:80] are LOCKS_SPARE[31:16] (unassigned slots 40-47).
  typedef struct packed {
    logic [NumEfuseBits-LockFieldBits-1:0] reserved;
    logic [LockFieldBits-1:0]              locks;
  } efuse_lock_view_t;

  typedef union packed {
    sep_efuse_map_regmap_t                         fields;
    efuse_lock_view_t                              locks;
    logic [NumFuseWords-1:0][NumFuseWordWidth-1:0] values;
  } efuse_map_t;

  // Class 1 storage is selected by field identity; all locations and widths
  // are derived directly from the generated RDL metadata.
  // LockFieldBits == 96: LOCKS (words 0-1) + LOCKS_SPARE (word 2) are all sensed.

  // TODO: Why is NumFuseWordWidth passed in?
  localparam efuse_pkg::shadow_word_range_map_t Class1ShadowRanges = '{
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset(OCH_SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR), LockFieldBits, NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_lc_state_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_lc_disable_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_lc_disable_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_rma_sip_token_digest_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_rma_chiplet_token_digest_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_class_key_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_chiplet_uid_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_UID_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_sip_uid_reg_t
          ),
          NumFuseWordWidth
      ),
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_UID_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_sys_uid_reg_t
          ),
          NumFuseWordWidth
      )
  };

  // Class 1a device secrets. These are disconnected from the shadow register
  // hardware output while secure_tm is asserted so no real secret reaches a
  // scannable consumer. Register reads keep their normal access controls.
  localparam efuse_pkg::shadow_word_range_map_t SecretShadowRanges = '{
      0:
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_chiplet_uid_reg_t
          ),
          NumFuseWordWidth
      ),
      1:
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_UID_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_sip_uid_reg_t
          ),
          NumFuseWordWidth
      ),
      2:
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_UID_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_sys_uid_reg_t
          ),
          NumFuseWordWidth
      ),
      3:
      efuse_pkg::make_shadow_word_range
      (
          efuse_offset
          (
              OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR
          ),
          $bits(
              sep_efuse_map_class_key_reg_t
          ),
          NumFuseWordWidth
      ),
      default: '0
  };


  // lock field
  // lock[3]   secure_tm: 0 -> secure_tm unlock; 1 -> secure_tm lock
  // lock[2:1] write: 00 -> unlock;11 -> lock ;10 -> set only;
  // lock[0]   read: 0 -> readable; 1 -> read locked
  localparam efuse_pkg::rule_t [NUM_EFUSE_FIELDS-1:0] EfuseFieldMap = '{
      // idx 39: spare7 — lock slot 39 (LOCKS_SPARE[14:15])
      '{
          idx: 6'd39,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE7_BASE_ADDR
          ),
          end_addr: och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIZE - 1
      },
      // idx 38: spare6 — lock slot 38 (LOCKS_SPARE[12:13])
      '{
          idx: 6'd38,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE6_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE7_BASE_ADDR
          ) - 1
      },
      // idx 37: spare5 — lock slot 37 (LOCKS_SPARE[10:11])
      '{
          idx: 6'd37,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE5_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE6_BASE_ADDR
          ) - 1
      },
      // idx 36: spare4 — lock slot 36 (LOCKS_SPARE[8:9])
      '{
          idx: 6'd36,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE4_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE5_BASE_ADDR
          ) - 1
      },
      // idx 35: spare3 — lock slot 35 (LOCKS_SPARE[6:7])
      '{
          idx: 6'd35,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE3_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE4_BASE_ADDR
          ) - 1
      },
      // idx 34: spare2 — lock slot 34 (LOCKS_SPARE[4:5])
      '{
          idx: 6'd34,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE2_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE3_BASE_ADDR
          ) - 1
      },
      // idx 33: spare1 — lock slot 33 (LOCKS_SPARE[2:3])
      '{
          idx: 6'd33,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE1_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE2_BASE_ADDR
          ) - 1
      },
      // idx 32: spare0 — lock slot 32 (LOCKS_SPARE[0:1])
      '{
          idx: 6'd32,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE0_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE1_BASE_ADDR
          ) - 1
      },
      // idx 31: SEP_SYS_ID — lock slot 31 (LOCKS[62:63])
      '{
          idx: 6'd31,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SYS_ID_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SPARE0_BASE_ADDR
          ) - 1
      },
      // idx 30: SEP_SIP_ID — lock slot 30 (LOCKS[60:61])
      '{
          idx: 6'd30,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SIP_ID_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SYS_ID_BASE_ADDR
          ) - 1
      },
      // idx 29: SEP_CHIPLET_ID — lock slot 29 (LOCKS[58:59])
      '{
          idx: 6'd29,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_CHIPLET_ID_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SIP_ID_BASE_ADDR
          ) - 1
      },
      '{  // SIP_PUBK_PQC_HASH1 (idx 28)
          idx: 6'd28,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_PQC_HASH1_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_CHIPLET_ID_BASE_ADDR
          ) - 1
      },
      '{  // SIP_PUBK_HASH1 (idx 27)
          idx: 6'd27,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_HASH1_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_PQC_HASH1_BASE_ADDR
          ) - 1
      },
      '{  // SYS_PUBK_PQC_HASH (idx 26)
          idx: 6'd26,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_PQC_HASH_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_HASH1_BASE_ADDR
          ) - 1
      },
      '{  // SIP_PUBK_PQC_HASH0 (idx 25)
          idx: 6'd25,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_PQC_HASH0_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_PQC_HASH_BASE_ADDR
          ) - 1
      },
      '{  // CHIPLET_PUBK_PQC_HASH1 (idx 24)
          idx: 6'd24,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_PQC_HASH1_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_PQC_HASH0_BASE_ADDR
          ) - 1
      },
      '{  // CHIPLET_PUBK_PQC_HASH0 (idx 23)
          idx: 6'd23,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_PQC_HASH0_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_PQC_HASH1_BASE_ADDR
          ) - 1
      },
      '{  // REQUIRED_ALGS (idx 22)
          idx: 6'd22,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_REQUIRED_ALGS_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_PQC_HASH0_BASE_ADDR
          ) - 1
      },
      '{  // REQUIRED_SIGNERS (idx 21)
          idx: 6'd21,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_REQUIRED_SIGNERS_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_REQUIRED_ALGS_BASE_ADDR
          ) - 1
      },
      '{  // CHIPLET_PUBK_HASH1 (idx 20)
          idx: 6'd20,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH1_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_REQUIRED_SIGNERS_BASE_ADDR
          ) - 1
      },
      '{  // CHIPLET_PUBK_HASH0 (idx 19)
          idx: 6'd19,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH0_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH1_BASE_ADDR
          ) - 1
      },
      '{  // SPI_CONFIG / SEP_SPI_CTRL_FIELD_EN through SPI_RB_VALID_TIME (idx 18)
          idx: 6'd18,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_HASH0_BASE_ADDR
          ) - 1
      },
      '{  // ROM_CTL (idx 17)
          idx: 6'd17,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_ROM_CTL_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SEP_SPI_CTRL_FIELD_EN_BASE_ADDR
          ) - 1
      },
      '{  // STATUS_RPT (idx 16)
          idx: 6'd16,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_STATUS_RPT_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_ROM_CTL_BASE_ADDR
          ) - 1
      },
      '{  // SYS_UID (idx 15)
          idx: 6'd15,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_UID_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_STATUS_RPT_BASE_ADDR
          ) - 1
      },
      '{  // SYS_PUBK_HASH (idx 14)
          idx: 6'd14,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_HASH_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_UID_BASE_ADDR
          ) - 1
      },
      '{  // SIP_UID (idx 13)
          idx: 6'd13,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_UID_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_PUBK_HASH_BASE_ADDR
          ) - 1
      },
      '{  // SIP_PUBK_HASH0 (idx 12)
          idx: 6'd12,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_HASH0_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_UID_BASE_ADDR
          ) - 1
      },
      '{  // CHIPLET_UID (idx 11)
          idx: 6'd11,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_PUBK_HASH0_BASE_ADDR
          ) - 1
      },
      '{  // BL2_VERSION (idx 10)
          idx: 6'd10,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL2_VERSION_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR
          ) - 1
      },
      '{  // BL1_VERSION (idx 9)
          idx: 6'd9,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL1_VERSION_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL2_VERSION_BASE_ADDR
          ) - 1
      },
      '{  // CHIPLET_PUBK_REVOKE (idx 8)
          idx: 6'd08,
          lock: {SECURE_TM_UNLOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_REVOKE_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_BL1_VERSION_BASE_ADDR
          ) - 1
      },
      '{  // CLASS_KEY (idx 7)
          idx: 6'd07,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CHIPLET_PUBK_REVOKE_BASE_ADDR
          ) - 1
      },
      // TODO: should this have SECURE_TM_LOCK? Not in hw/sys/sep/doc/lifecycle_controller.adoc list
      '{  // RMA_CHIPLET_TOKEN_DIGEST (idx 6)
          idx: 6'd06,
          lock: {SECURE_TM_LOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR
          ) - 1
      },
      // TODO: should this have SECURE_TM_LOCK? Not in hw/sys/sep/doc/lifecycle_controller.adoc list
      '{  // RMA_SIP_TOKEN_DIGEST (idx 5)
          idx: 6'd05,
          lock: {SECURE_TM_LOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_BASE_ADDR
          ) - 1
      },
      '{  // SYS_DIS (idx 4)
          idx: 6'd04,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR
          ) - 1
      },
      '{  // SIP_DIS (idx 3)
          idx: 6'd03,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SYS_DIS_BASE_ADDR
          ) - 1
      },
      '{  // TRANSIENT_RMA_EN (idx 2)
          idx: 6'd02,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_TRANSIENT_RMA_EN_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SIP_DIS_BASE_ADDR
          ) - 1
      },
      '{  // SBOOT_DIS (idx 1)
          idx: 6'd01,
          lock: {SECURE_TM_UNLOCK, WRITE_UNLOCK, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_TRANSIENT_RMA_EN_BASE_ADDR
          ) - 1
      },
      '{  // LC_STATE (idx 0)
          idx: 6'd00,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_SBOOT_DIS_BASE_ADDR
          ) - 1
      },
      '{  // LOCKS meta-field (idx LOCKS_META_IDX = 6'h3F); hardware never applies lock
          // bits to this entry. Covers both LOCKS (64-bit) and LOCKS_SPARE (32-bit).
          idx:
          LOCKS_META_IDX,
          lock: {SECURE_TM_LOCK, WRITE_SET_ONLY, READ_UNLOCK},
          start_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR
          ),
          end_addr:
          efuse_offset
          (
              och_sep_top_addrmap_pkg::OCH_SEP_TOP_SEP_EFUSE_MAP_LC_STATE_BASE_ADDR
          ) - 1
      }
  };

endpackage
