/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_defs.h
 * @brief Global definitions for Key Manager ROM firmware
 *
 * Memory map, firmware version, shred parameters, KPV constants,
 * message buffer sizes, key handle limits, and all command/response/
 * return-code/fault-code enumerations.
 */

#ifndef ROM_DEFS_H
#define ROM_DEFS_H

#ifndef __ASSEMBLER__
#include <stdint.h>
#endif /* !__ASSEMBLER__ */

/*===========================================================================
 * Memory Map
 *===========================================================================*/

/** @brief ROM base address. */
#define ROM_KM_ROM_BASE 0x00000000
/** @brief ROM size in bytes (16 KB). */
#define ROM_KM_ROM_SIZE 0x00004000
/** @brief SRAM base address. */
#define ROM_KM_SRAM_BASE 0x00004000
/** @brief SRAM size in bytes (16 KB). */
#define ROM_KM_SRAM_SIZE 0x00004000
/** @brief First address past the end of SRAM. */
#define ROM_KM_SRAM_END (ROM_KM_SRAM_BASE + ROM_KM_SRAM_SIZE)

/** @brief ROM warm-persist region base address (highest 512 B of SRAM, region 31). */
#define ROM_KM_PERSIST_BASE (ROM_KM_SRAM_END - ROM_KM_PERSIST_SIZE)
/* ROM-owned warm-persist region: the highest 512 B of SRAM, reserved for ROM
 * firmware state that must survive warm reset. It is NOT for mutable
 * (SRAM-loaded) firmware, which ROM write-locks out of it before handoff. */
/** @brief ROM warm-persist region size in bytes (512 B = one SRAM write-lock region). */
#define ROM_KM_PERSIST_SIZE 0x00000200
/** @brief SRAM write-lock region index covering the warm-persist region (top region). */
#define ROM_KM_PERSIST_LOCK_REGION 31u
/** @brief SRAM_LOCK bitmask for the warm-persist region (bit 31). */
#define ROM_KM_PERSIST_LOCK_MASK (1u << ROM_KM_PERSIST_LOCK_REGION)

/**
 * @brief Granularity of one SRAM write-lock region in bytes.
 *
 * The 16 KB SRAM is divided into 32 regions of 512 B each.  The SRAM_LOCK
 * register has one bit per region.  Used by the mutable-firmware bounds check
 * and the firmware-region lock-mask computation.
 */
#define SRAM_LOCK_REGION_BYTES 0x00000200u

/**
 * @brief Exclusive upper bound (CPU address) of the mutable-firmware load area.
 *
 * Defined by the linker (km_sram_layout.ld) as STACK - __rom_max_stack, rounded
 * DOWN to a SRAM_LOCK_REGION_BYTES boundary, where __rom_max_stack is the
 * worst-case ROM main-stack budget validated against the production ELF by
 * scripts/km_stack_analyze.py.  Because it is a build-time constant rather than a
 * function of the live stack pointer, a warm-reset CMD_SRAM_EXEC restart can
 * never let the deeper-running ROM stack overwrite the loaded image, and the
 * image and ROM stack always occupy disjoint SRAM write-lock regions.
 *
 * Use its address, not its value: `(uint32_t)(uintptr_t)__km_fw_load_limit`.
 */
#ifndef __ASSEMBLER__
extern const uint8_t __km_fw_load_limit[];
#endif /* !__ASSEMBLER__ */

/**
 * @brief ROM IRQ vector address (`irq_vec` in crt0.s, at absolute 0x10).
 *
 * This is the reset value of KMCSR IRQ_ENTRY_ADDR. Because IRQ_ENTRY_ADDR is a
 * warm-reset-domain register, every reset that re-enters ROM (cold, external
 * async, and KM soft reset) restores it to this value and clears
 * IRQ_ENTRY_LOCK. ROM re-asserts it explicitly at boot before enabling IRQs so
 * correctness does not depend solely on the reset value.
 */
#define ROM_KM_ROM_IRQ_ENTRY 0x10u

/** @brief Key Provisioning Vault register base address. */
#define ROM_KM_KPV_BASE 0x0000D000
/** @brief Key Manager CSR register base address. */
#define ROM_KM_KMCSR_BASE 0x0000E000
/** @brief DRBG sampler register base address. */
#define ROM_KM_DRBG_BASE 0x0000F000
/** @brief Mailbox register base address. */
#define ROM_KM_MAILBOX_BASE 0x00010000

/** @brief Words per mailbox FIFO (matches RTL MAILBOX_DEPTH default) */
#define ROM_KM_MAILBOX_FIFO_DEPTH 16

/**
 * @brief OTP/eFuse AXI-Lite window base address (KM CPU view).
 *
 * Crossbar master port 8 decodes this 4 KB window. key_manager.sv replaces
 * addr[31:12] with OTP_EFUSE_REMAP_BASE[31:12] before driving efuse_req_o, so the shared SEP
 * efuse_interface_controller (at OTP_EFUSE_REMAP_BASE) is reached.
 * Generated key_manager_addr.h also provides per-sub-region constants:
 *   KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR  (0x00011000) — MAP / OTP shadow
 *   KEY_MANAGER_OTP_EFUSE_CTRL_BASE_ADDR (0x00011400) — eFuse Interface CTRL
 *   KEY_MANAGER_OTP_EFUSE_MMR_BASE_ADDR  (0x00011500) — eFuse MMR
 *
 * Prefer KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR from PeakRDL; define only if absent.
 */
#ifndef ROM_KM_OTP_BASE
#define ROM_KM_OTP_BASE 0x00011000
#endif

/*===========================================================================
 * Firmware Version
 *===========================================================================*/

/** @brief ROM firmware major version. */
#define ROM_KM_ROM_VERSION_MAJOR 1
/** @brief ROM firmware minor version. */
#define ROM_KM_ROM_VERSION_MINOR 1
/** @brief ROM firmware patch version. */
#define ROM_KM_ROM_VERSION_PATCH 0

/*===========================================================================
 * Shred Parameters
 *===========================================================================*/

/** @brief Number of additional shred passes (total = SHRED_ITER + 1 = 3) */
#define ROM_KM_SHRED_ITER 2

/*===========================================================================
 * KPV Parameters
 *===========================================================================*/

/** @brief Number of slots in the Key Provisioning Vault. */
#define ROM_KM_KPV_NUM_SLOTS 32
/** @brief 32-bit words per KPV slot. */
#define ROM_KM_KPV_WORDS_PER_SLOT 16
/** @brief Total 32-bit words across the entire KPV (largest shred region). */
#define ROM_KM_KPV_TOTAL_WORDS ((uint16_t)(ROM_KM_KPV_NUM_SLOTS * ROM_KM_KPV_WORDS_PER_SLOT))

/*===========================================================================
 * Message Buffer Parameters
 *===========================================================================*/

/** @brief Maximum message payload length in 32-bit words */
#define ROM_KM_MAX_PAYLOAD_LEN 255

/** @brief Message buffer size in 32-bit words (header + max payload + CRC) */
#define ROM_KM_MSGBUF_SIZE (1 + ROM_KM_MAX_PAYLOAD_LEN + 1)

/*===========================================================================
 * Key Handle Parameters
 *===========================================================================*/

/** @brief Maximum simultaneous key handles (0x01-0xFF) */
#define ROM_KM_MAX_KEY_HANDLES 255

/** @brief Null key handle (reserved, never assigned) */
#define ROM_KM_KEY_HANDLE_NULL 0x00

/**
 * @brief Maximum key length in 32-bit words.
 *
 * The wire-encoded key size is `actual word count - 1` and is bounded to 127
 * (see rom_load_key / CMD_KEY_LOAD), so the largest key occupies 128 words.
 */
#define ROM_KM_MAX_KEY_WORDS 128

/*===========================================================================
 * Crypto Engine Share Sizes (words per share)
 *===========================================================================*/

/** @brief HMAC key share size in 32-bit words (256-bit). */
#define ROM_KM_HMAC_WORDS_PER_SHARE 8
/** @brief KMAC key share size in 32-bit words (256-bit). */
#define ROM_KM_KMAC_WORDS_PER_SHARE 8
/** @brief AES key share size in 32-bit words (256-bit). */
#define ROM_KM_AES_WORDS_PER_SHARE 8
/** @brief OTBN key share size in 32-bit words (384-bit). */
#define ROM_KM_OTBN_WORDS_PER_SHARE 12
/** @brief Adams Bridge seed share size in 32-bit words (256-bit). */
#define ROM_KM_ABR_WORDS_PER_SHARE 8

/** @brief Largest crypto-engine key share width in words (OTBN = 12). */
#define ROM_KM_MAX_WORDS_PER_SHARE ROM_KM_OTBN_WORDS_PER_SHARE

/*===========================================================================
 * Crypto Engine Register Layout (common across all wrappers)
 *===========================================================================*/

/** @brief Byte offset of SHARE0 from wrapper base. */
#define ROM_KM_ENGINE_KEY_SHARE0_OFFSET 0x000
/** @brief Byte offset of SHARE1 from wrapper base; (words) is words per share. */
#define ROM_KM_ENGINE_KEY_SHARE1_OFFSET(words) ((words)*4)

/*===========================================================================
 * IRQ Bit Positions
 *===========================================================================*/

/** @brief PicoRV32 IRQ bitmask for the mailbox interrupt (bit 4). */
#define ROM_KM_IRQ_MBOX_BIT (1 << 4)
/** @brief PicoRV32 IRQ bitmask for the ABR ML-KEM shared-key pulse (bit 5). */
#define ROM_KM_IRQ_ABR_SHAREDKEY_BIT (1 << 5)

#ifndef __ASSEMBLER__
/*===========================================================================
 * Command IDs
 *===========================================================================*/

/** @brief Command identifiers (sparse: 0x00-0x04, 0x10-0x12, and 0x22-0x28). */
typedef enum {
    ROM_KM_CMD_HW_VER = 0x00,    /**< Query hardware version */
    ROM_KM_CMD_ROM_VER = 0x01,   /**< Query ROM firmware version */
    ROM_KM_CMD_SRAM_VER = 0x02,  /**< Query SRAM firmware version */
    ROM_KM_CMD_STAT = 0x03,      /**< Query recoverable-error status */
    ROM_KM_CMD_RECOV_ACK = 0x04, /**< Acknowledge recoverable error */
    ROM_KM_CMD_EXEC_ROM = 0x10,  /**< Continue executing ROM; ignore subsequent handover commands */
    ROM_KM_CMD_SRAM_LOAD_EXEC =
        0x11, /**< Accept firmware image via mailbox, load to SRAM, and execute */
    ROM_KM_CMD_SRAM_EXEC = 0x12,         /**< Jump to pre-loaded mutable firmware in SRAM */
    ROM_KM_CMD_KEY_GENERATE = 0x22,      /**< Generate a random key */
    ROM_KM_CMD_KEY_REVOKE = 0x23,        /**< Revoke a key by handle */
    ROM_KM_CMD_KEY_TRANSFER = 0x24,      /**< Transfer a key to crypto engines */
    ROM_KM_CMD_ENGINE_SHRED = 0x25,      /**< Shred crypto engine sideload keys */
    ROM_KM_CMD_KEY_LOAD = 0x26,          /**< Load SEP-supplied key material via mailbox */
    ROM_KM_CMD_ABR_SK_TRANSFER = 0x27,   /**< Capture ML-KEM shared key from ABR into KPV */
    ROM_KM_CMD_OTP_READ_LOCK_COLD = 0x28 /**< Set cold-reset-domain OTP read-lock bits */
} rom_km_cmd_id_t;

/** @brief Evaluate to non-zero if @p id is a valid command ID. */
#define ROM_KM_CMD_IS_VALID(id) \
    ((id) <= 0x04 || ((id) >= 0x10 && (id) <= 0x12) || ((id) >= 0x22 && (id) <= 0x28))

/*===========================================================================
 * Response IDs
 *===========================================================================*/

/** @brief Response identifiers sent from KM to SEP. */
typedef enum {
    ROM_KM_RESP_CMD = 0x00,                  /**< Command response */
    ROM_KM_RESP_KM_READY = 0x55,             /**< Boot-complete announcement */
    ROM_KM_RESP_ABR_SHARED_KEY_READY = 0x56, /**< ML-KEM shared key available */
    ROM_KM_RESP_RECOVERABLE_FAULT = 0xFE,    /**< Recoverable fault notification */
    ROM_KM_RESP_UNRECOVERABLE_FAULT = 0xFF   /**< Unrecoverable fault notification */
} rom_km_resp_id_t;

/*===========================================================================
 * Return Codes (signed 8-bit, for RESP_CMD)
 *===========================================================================*/

/** @brief Command return codes (signed 8-bit, carried in RESP_CMD). */
typedef enum {
    ROM_KM_RC_SUCCESS = 0,      /**< Command completed successfully */
    ROM_KM_RC_FAILURE = -1,     /**< Generic failure */
    ROM_KM_RC_HEADER_CRC = -2,  /**< Header CRC-8 mismatch */
    ROM_KM_RC_CMD_NOSEQ = -3,   /**< Sequence number mismatch */
    ROM_KM_RC_INVALID_CMD = -4, /**< Unknown command ID */
    ROM_KM_RC_INVALID_LEN = -5, /**< Payload length mismatch */
    ROM_KM_RC_PAYLOAD_CRC = -6, /**< Payload CRC-32C mismatch */
    ROM_KM_RC_INVALID_ARG = -7  /**< Invalid argument value */
} rom_km_return_code_t;

/*===========================================================================
 * Recoverable Fault Codes (signed 8-bit)
 *===========================================================================*/

/** @brief Recoverable fault codes (signed 8-bit). */
typedef enum {
    ROM_KM_RFAULT_KEY_SLOT_CRC = -1,   /**< Key slot CRC integrity failure */
    ROM_KM_RFAULT_RX_BUFF_OFLOW = -2,  /**< RX buffer overflow (unterminated msg) */
    ROM_KM_RFAULT_MBOX_OVERFLOW = -3,  /**< Outbound mailbox FIFO overflow */
    ROM_KM_RFAULT_MBOX_UNDERFLOW = -4, /**< Inbound mailbox FIFO underflow */
    ROM_KM_RFAULT_FLUSHED_BY_SEP = -5  /**< Mailbox flushed by SEP */
} rom_km_recov_fault_code_t;

/*===========================================================================
 * Unrecoverable Fault Codes (signed 8-bit)
 *===========================================================================*/

/** @brief Unrecoverable fault codes (signed 8-bit). */
typedef enum {
    ROM_KM_UFAULT_WIPE_STATE = -1,      /**< WIPE_STATE asserted */
    ROM_KM_UFAULT_ROM_PARITY = -2,      /**< ROM parity error */
    ROM_KM_UFAULT_SRAM_PARITY = -3,     /**< SRAM parity error */
    ROM_KM_UFAULT_ROM_WRITE = -4,       /**< Illegal write to ROM */
    ROM_KM_UFAULT_SRAM_WRITE_LOCK = -5, /**< Write to locked SRAM region */
    ROM_KM_UFAULT_AXI_DECERR = -6,      /**< AXI decode error */
    ROM_KM_UFAULT_AXI_SLVERR = -7,      /**< AXI slave error */
    ROM_KM_UFAULT_DRBG_ERR = -8,        /**< DRBG hardware error */
    ROM_KM_UFAULT_ILLEGAL_INSN = -9,    /**< Illegal instruction trap */
    ROM_KM_UFAULT_BUS_ERROR = -10,      /**< AXI bus-error trap */
    ROM_KM_UFAULT_EBREAK = -11,         /**< EBREAK instruction trap */
    ROM_KM_UFAULT_SPURIOUS_IRQ = -12,   /**< Unrecognised IRQ source */
    ROM_KM_UFAULT_OTP_SIGINT = -13,     /**< OTP dual-rail integrity violation */
    ROM_KM_UFAULT_FW_CRC = -14,         /**< Mutable firmware image CRC-32C mismatch */
    ROM_KM_UFAULT_FW_STACK_OVF = -15,   /**< Firmware load destination exceeded stack guard */
    ROM_KM_UFAULT_SHRED_RANGE = -16,    /**< Shred word count exceeded the shred-order buffer */
    ROM_KM_UFAULT_EXEC =
        -17 /**< Instruction fetch from non-whitelisted (non-executable) memory region */
} rom_km_unrecov_fault_code_t;

/*===========================================================================
 * OTP Read-Lock / Change-Status Aggregate Masks
 *
 * Per-field single-bit masks are generated by PeakRDL as
 * KM_CSR__OTP_READ_LOCK_REG__<FIELD>_bm in km_csr.h.
 * Only the multi-field aggregates below need to be maintained here.
 *
 * POLICY: LIFE_CYCLE and DEMOTION are non-secret status and must NOT be
 * read-locked by firmware (they stay software-readable). They are therefore
 * deliberately excluded from the read-lock aggregate below, and there is no
 * "lock all" read-lock mask. Firmware that read-locks OTP fields before
 * handing control to mutable (SRAM-loaded) firmware should use
 * ROM_KM_OTP_LOCK_SECRET_MASK.
 *===========================================================================*/

/**
 * @brief Read-lock mask for the secret OTP fields ROM may lock. This is the only OTP read-lock
 * aggregate.
 */
#define ROM_KM_OTP_LOCK_SECRET_MASK \
    (KM_CSR__OTP_READ_LOCK_REG__CHIPLET_UID_bm | KM_CSR__OTP_READ_LOCK_REG__SIP_UID_bm | \
     KM_CSR__OTP_READ_LOCK_REG__SYS_UID_bm | KM_CSR__OTP_READ_LOCK_REG__CLASS_KEY_bm)

/**
 * @brief OTP_CHANGE_STATUS aggregate covering all six monitored fields. Used
 *        to verify/clear change status.
 */
#define ROM_KM_OTP_CHANGE_ALL_MASK \
    (KM_CSR__OTP_CHANGE_STATUS_REG__LIFE_CYCLE_bm | KM_CSR__OTP_CHANGE_STATUS_REG__DEMOTION_bm | \
     KM_CSR__OTP_CHANGE_STATUS_REG__CHIPLET_UID_bm | KM_CSR__OTP_CHANGE_STATUS_REG__SIP_UID_bm | \
     KM_CSR__OTP_CHANGE_STATUS_REG__SYS_UID_bm | KM_CSR__OTP_CHANGE_STATUS_REG__CLASS_KEY_bm)

/*===========================================================================
 * Message Header Layout
 *===========================================================================*/

/** @brief Command/response message header (32-bit packed word) */
typedef union {
    uint32_t raw;
    struct {
        uint8_t seq_num;     /**< [7:0]   Sequence number */
        uint8_t id;          /**< [15:8]  Command or response ID */
        uint8_t payload_len; /**< [23:16] Payload length in words */
        uint8_t header_crc8; /**< [31:24] CRC-8/ROHC of lower 24 bits */
    } __attribute__((packed));
} rom_km_msg_header_t;

/*===========================================================================
 * Command Handler Result
 *===========================================================================*/

/** @brief Result returned by every command handler. */
typedef struct {
    int8_t return_code;  /**< Return code from rom_km_return_code_t */
    uint8_t has_arg;     /**< 1 if return_arg is valid */
    uint32_t return_arg; /**< Optional packed 32-bit return argument */
} rom_km_cmd_result_t;

/*===========================================================================
 * Command Payload Argument Structs
 *===========================================================================*/

/** @brief Payload for CMD_KEY_GENERATE (0x22): 2 words. */
typedef struct {
    uint32_t req_size;   /**< [6:0] requested key size in words minus 1 */
    uint32_t dest_valid; /**< [7:0] destination engine bitmask */
} rom_km_cmd_key_generate_args_t;

/** @brief Payload for CMD_KEY_REVOKE (0x23): 1 word. */
typedef struct {
    uint32_t handle; /**< [7:0] key handle to revoke */
} rom_km_cmd_key_revoke_args_t;

/** @brief Payload for CMD_KEY_TRANSFER (0x24): 2 words. */
typedef struct {
    uint32_t handle;       /**< [7:0] key handle to transfer */
    uint32_t dest_engines; /**< [7:0] destination engine bitmask */
} rom_km_cmd_key_transfer_args_t;

/** @brief Payload for CMD_ENGINE_SHRED (0x25): 1 word. */
typedef struct {
    uint32_t dest; /**< [7:0] engine bitmask to shred */
} rom_km_cmd_engine_shred_args_t;

/** @brief Payload for CMD_KEY_LOAD (0x26): variable length (KEY_SIZE+3 words).
 *
 * word 0: KEY_SIZE[6:0]    RESERVED[31:7]=0  — number of KEY_DATA words minus 1
 * word 1: DEST_VALID[7:0]  RESERVED[31:8]=0  — destination engine bitmask
 * words 2..(2+KEY_SIZE): KEY_DATA[0..KEY_SIZE] — cleartext key material
 *
 * Total payload length = KEY_SIZE + 3 32-bit words (not counting PAYLOAD_CRC32).
 */
typedef struct {
    uint32_t key_size;   /**< [6:0] key word count minus 1; RESERVED[31:7] must be 0 */
    uint32_t dest_valid; /**< [7:0] destination engine bitmask; RESERVED[31:8] must be 0 */
    uint32_t key_data[]; /**< KEY_SIZE+1 key words (flexible array member) */
} rom_km_cmd_key_load_args_t;

/** @brief Payload for CMD_ABR_SK_TRANSFER (0x27): 1 word.
 *
 * word 0: DEST_VALID[7:0]  RESERVED[31:8]=0  — destination engine bitmask for
 *   the captured key.  Must be non-zero with no bits above [7] set.
 */
typedef struct {
    uint32_t dest_valid; /**< [7:0] destination engine bitmask; RESERVED[31:8] must be 0 */
} rom_km_cmd_abr_sk_transfer_args_t;

/** @brief Payload for CMD_OTP_READ_LOCK_COLD (0x28): 1 word.
 *
 * word 0: LOCK_BITS[5:0]  RESERVED[31:6]=0  — OTP field read-lock bitmask
 *   applied to the cold-reset-domain OTP_READ_LOCK_COLD register (woset).
 * RESERVED[31:6] must be zero; non-zero reserved bits return INVALID_ARG.
 * Bits can only be set, not cleared.  Already-set bits are unaffected (woset).
 * The return argument echoes the resulting OTP_READ_LOCK_COLD register value.
 */
typedef struct {
    uint32_t lock_bits; /**< [5:0] OTP field bitmask; RESERVED[31:6] must be 0 */
} rom_km_cmd_otp_read_lock_cold_args_t;

/** @brief Valid (non-reserved) bit mask for CMD_OTP_READ_LOCK_COLD lock_bits. */
#define ROM_KM_OTP_READ_LOCK_COLD_VALID_MASK 0x3Fu

/**
 * @brief Payload for CMD_SRAM_LOAD_EXEC (0x11): 1 word.
 *
 * word 0: FW_WORDS[15:0]   RESERVED[31:16]=0  — firmware image size in 32-bit words.
 *   Does not include the trailing CRC-32C word appended by SEP in the image frame.
 *   Must be non-zero and fit within the mutable-load area (ROM checks statically
 *   against __km_fw_load_limit, the worst-case-stack-aligned load ceiling).
 */
typedef struct {
    uint32_t fw_words; /**< [15:0] firmware image word count; RESERVED[31:16] must be 0 */
} rom_km_cmd_sram_load_exec_args_t;

/*===========================================================================
 * Crypto Engine Destination Bitfield (shared by DEST_VALID / DEST_ENGINE)
 *===========================================================================*/

/** @brief Crypto engine destination bitmask (shared by DEST_VALID / DEST_ENGINE). */
typedef union {
    uint8_t raw; /**< Raw 8-bit value */
    struct {
        uint8_t hmac_sha2 : 1;        /**< bit 0: HMAC-SHA2 engine */
        uint8_t kmac_sha3 : 1;        /**< bit 1: KMAC-SHA3 engine */
        uint8_t aes : 1;              /**< bit 2: AES engine */
        uint8_t otbn : 1;             /**< bit 3: OTBN engine */
        uint8_t abr_mldsa_seed : 1;   /**< bit 4: Adams Bridge ML-DSA seed */
        uint8_t abr_mlkem_seed_d : 1; /**< bit 5: Adams Bridge ML-KEM seed D */
        uint8_t abr_mlkem_seed_z : 1; /**< bit 6: Adams Bridge ML-KEM seed Z */
        uint8_t abr_mlkem_msg : 1;    /**< bit 7: Adams Bridge ML-KEM message */
    };
} rom_km_dest_bits_t;

/** @brief All valid destination bits (bits [7:0]). */
#define ROM_KM_DEST_VALID_MASK 0xFFu

/*===========================================================================
 * Command Return Argument Structs
 *===========================================================================*/

/** @brief Return argument for CMD_HW_VER(0x00), CMD_ROM_VER(0x01), CMD_SRAM_VER(0x02). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t patch : 8; /* [7:0]   */
        uint32_t minor : 8; /* [15:8]  */
        uint32_t major : 8; /* [23:16] */
        uint32_t _rsvd : 8; /* [31:24] */
    };
} rom_km_version_ret_t;

/** @brief Return argument for CMD_STAT(0x03): {rsvd[31:1], RECOVERABLE_ERR[0]}. */
typedef union {
    uint32_t raw;
    struct {
        uint32_t recoverable_err : 1; /* [0]    */
        uint32_t _rsvd : 31;          /* [31:1] */
    };
} rom_km_stat_ret_t;

/** @brief Return argument for CMD_KEY_REVOKE(0x23) and CMD_KEY_LOAD(0x26). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t key_handle : 8; /* [7:0]  */
        uint32_t _rsvd : 24;     /* [31:8] */
    };
} rom_km_handle_ret_t;

/** @brief Return argument for CMD_KEY_GENERATE(0x22). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t key_handle : 8; /* [7:0]   */
        uint32_t req_size : 7;   /* [14:8]  */
        uint32_t _rsvd0 : 1;     /* [15]    */
        uint32_t dest_valid : 8; /* [23:16] */
        uint32_t _rsvd1 : 8;     /* [31:24] */
    };
} rom_km_key_generate_ret_t;

/** @brief Return argument for CMD_KEY_TRANSFER(0x24). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t key_handle : 8;  /* [7:0]   */
        uint32_t dest_engine : 8; /* [15:8]  */
        uint32_t _rsvd : 16;      /* [31:16] */
    };
} rom_km_key_transfer_ret_t;

/** @brief Return argument for CMD_ENGINE_SHRED(0x25). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t dest_engine : 8; /* [7:0]  */
        uint32_t _rsvd : 24;      /* [31:8] */
    };
} rom_km_engine_shred_ret_t;

#endif /* !__ASSEMBLER__ */

/*===========================================================================
 * EBREAK Opcode (for ISR disambiguation)
 *===========================================================================*/

/** @brief RISC-V EBREAK instruction encoding (used by ISR to distinguish deliberate halt). */
#define ROM_KM_EBREAK_OPCODE 0x00100073

/** @brief RISC-V C.EBREAK (compressed) instruction encoding.
 *  With -march=rv32emc the compiler/assembler may emit the 2-byte form.
 *  A 32-bit load at the ebreak PC will place c.ebreak in the lower half-word. */
#define ROM_KM_C_EBREAK_OPCODE 0x9002

#endif /* ROM_DEFS_H */
