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
#define ROM_KM_ROM_BASE             0x00000000
/** @brief ROM size in bytes (8 KB). */
#define ROM_KM_ROM_SIZE             0x00002000
/** @brief SRAM base address. */
#define ROM_KM_SRAM_BASE            0x00004000
/** @brief SRAM size in bytes (16 KB). */
#define ROM_KM_SRAM_SIZE            0x00004000
/** @brief First address past the end of SRAM. */
#define ROM_KM_SRAM_END             (ROM_KM_SRAM_BASE + ROM_KM_SRAM_SIZE)

/** @brief Key Provisioning Vault register base address. */
#define ROM_KM_KPV_BASE             0x0000D000
/** @brief Key Manager CSR register base address. */
#define ROM_KM_KMCSR_BASE           0x0000E000
/** @brief DRBG sampler register base address. */
#define ROM_KM_DRBG_BASE            0x0000F000
/** @brief Mailbox register base address. */
#define ROM_KM_MAILBOX_BASE         0x00010000

/** @brief Words per mailbox FIFO (matches RTL MAILBOX_DEPTH default) */
#define ROM_KM_MAILBOX_FIFO_DEPTH   16

/** @brief OTBN crypto engine wrapper base address. */
#define ROM_KM_OTBN_WRAPPER_BASE    0x00018000
/** @brief AES crypto engine wrapper base address. */
#define ROM_KM_AES_WRAPPER_BASE     0x00019000
/** @brief KMAC crypto engine wrapper base address. */
#define ROM_KM_KMAC_WRAPPER_BASE    0x0001A000
/** @brief HMAC crypto engine wrapper base address. */
#define ROM_KM_HMAC_WRAPPER_BASE    0x0001B000

/*===========================================================================
 * Firmware Version
 *===========================================================================*/

/** @brief ROM firmware major version. */
#define ROM_KM_ROM_VERSION_MAJOR    1
/** @brief ROM firmware minor version. */
#define ROM_KM_ROM_VERSION_MINOR    1
/** @brief ROM firmware patch version. */
#define ROM_KM_ROM_VERSION_PATCH    0

/*===========================================================================
 * Shred Parameters
 *===========================================================================*/

/** @brief Number of additional shred passes (total = SHRED_ITER + 1 = 3) */
#define ROM_KM_SHRED_ITER           2

/*===========================================================================
 * KPV Parameters
 *===========================================================================*/

/** @brief Number of slots in the Key Provisioning Vault. */
#define ROM_KM_KPV_NUM_SLOTS        32
/** @brief 32-bit words per KPV slot. */
#define ROM_KM_KPV_WORDS_PER_SLOT   16

/*===========================================================================
 * Message Buffer Parameters
 *===========================================================================*/

/** @brief Maximum message payload length in 32-bit words */
#define ROM_KM_MAX_PAYLOAD_LEN      255

/** @brief Message buffer size in 32-bit words (header + max payload + CRC) */
#define ROM_KM_MSGBUF_SIZE          (1 + ROM_KM_MAX_PAYLOAD_LEN + 1)

/*===========================================================================
 * Key Handle Parameters
 *===========================================================================*/

/** @brief Maximum simultaneous key handles (0x01-0xFF) */
#define ROM_KM_MAX_KEY_HANDLES      255

/** @brief Null key handle (reserved, never assigned) */
#define ROM_KM_KEY_HANDLE_NULL      0x00

/*===========================================================================
 * Crypto Engine Share Sizes (words per share)
 *===========================================================================*/

/** @brief HMAC key share size in 32-bit words (256-bit). */
#define ROM_KM_HMAC_WORDS_PER_SHARE  8
/** @brief KMAC key share size in 32-bit words (256-bit). */
#define ROM_KM_KMAC_WORDS_PER_SHARE  8
/** @brief AES key share size in 32-bit words (256-bit). */
#define ROM_KM_AES_WORDS_PER_SHARE   8
/** @brief OTBN key share size in 32-bit words (384-bit). */
#define ROM_KM_OTBN_WORDS_PER_SHARE  12

/*===========================================================================
 * Crypto Engine Register Layout (common across all wrappers)
 *===========================================================================*/

/** @brief Byte offset of SHARE0 from wrapper base. */
#define ROM_KM_ENGINE_KEY_SHARE0_OFFSET          0x000
/** @brief Byte offset of SHARE1 from wrapper base; (words) is words per share. */
#define ROM_KM_ENGINE_KEY_SHARE1_OFFSET(words)   ((words) * 4)

/*===========================================================================
 * IRQ Bit Positions
 *===========================================================================*/

/** @brief PicoRV32 IRQ bitmask for the mailbox interrupt (bit 4). */
#define ROM_KM_IRQ_MBOX_BIT         (1 << 4)

#ifndef __ASSEMBLER__
/*===========================================================================
 * Command IDs
 *===========================================================================*/

/** @brief Command identifiers (sparse: 0x00-0x04, 0x10-0x12, and 0x20-0x26). */
typedef enum {
    ROM_KM_CMD_HW_VER              = 0x00, /**< Query hardware version */
    ROM_KM_CMD_ROM_VER             = 0x01, /**< Query ROM firmware version */
    ROM_KM_CMD_SRAM_VER            = 0x02, /**< Query SRAM firmware version (reserved) */
    ROM_KM_CMD_STAT                = 0x03, /**< Query recoverable-error status */
    ROM_KM_CMD_RECOV_ACK           = 0x04, /**< Acknowledge recoverable error */
    ROM_KM_CMD_EXEC_ROM            = 0x10, /**< Continue executing ROM; ignore subsequent handover commands */
    ROM_KM_CMD_SRAM_LOAD_EXEC      = 0x11, /**< Accept firmware image via mailbox, load to SRAM, and execute */
    ROM_KM_CMD_SRAM_EXEC           = 0x12, /**< Jump to pre-loaded mutable firmware in SRAM */
    ROM_KM_CMD_KPVLP_SLOT_REQ      = 0x20, /**< Allocate KPVLP slots */
    ROM_KM_CMD_KPVLP_KEY_REGISTER  = 0x21, /**< Register a KPVLP-loaded key */
    ROM_KM_CMD_KEY_GENERATE        = 0x22, /**< Generate a random key */
    ROM_KM_CMD_KEY_REVOKE          = 0x23, /**< Revoke a key by handle */
    ROM_KM_CMD_KEY_TRANSFER        = 0x24, /**< Transfer a key to crypto engines */
    ROM_KM_CMD_ENGINE_SHRED        = 0x25, /**< Shred crypto engine sideload keys */
    ROM_KM_CMD_KEY_LOAD            = 0x26  /**< Load SEP-supplied key material via mailbox (FR-2739-001) */
} rom_km_cmd_id_t;

/** @brief Evaluate to non-zero if @p id is a valid command ID. */
#define ROM_KM_CMD_IS_VALID(id)     ((id) <= 0x04 || \
                                     ((id) >= 0x10 && (id) <= 0x12) || \
                                     ((id) >= 0x20 && (id) <= 0x26))

/*===========================================================================
 * Response IDs
 *===========================================================================*/

/** @brief Response identifiers sent from KM to SEP. */
typedef enum {
    ROM_KM_RESP_CMD                    = 0x00, /**< Command response */
    ROM_KM_RESP_KM_READY               = 0x55, /**< Boot-complete announcement */
    ROM_KM_RESP_RECOVERABLE_FAULT      = 0xFE, /**< Recoverable fault notification */
    ROM_KM_RESP_UNRECOVERABLE_FAULT    = 0xFF  /**< Unrecoverable fault notification */
} rom_km_resp_id_t;

/*===========================================================================
 * Return Codes (signed 8-bit, for RESP_CMD)
 *===========================================================================*/

/** @brief Command return codes (signed 8-bit, carried in RESP_CMD). */
typedef enum {
    ROM_KM_RC_SUCCESS       =  0, /**< Command completed successfully */
    ROM_KM_RC_FAILURE       = -1, /**< Generic failure */
    ROM_KM_RC_HEADER_CRC    = -2, /**< Header CRC-8 mismatch */
    ROM_KM_RC_CMD_NOSEQ     = -3, /**< Sequence number mismatch */
    ROM_KM_RC_INVALID_CMD   = -4, /**< Unknown command ID */
    ROM_KM_RC_INVALID_LEN   = -5, /**< Payload length mismatch */
    ROM_KM_RC_PAYLOAD_CRC   = -6, /**< Payload CRC-32C mismatch */
    ROM_KM_RC_INVALID_ARG   = -7  /**< Invalid argument value */
} rom_km_return_code_t;

/*===========================================================================
 * Recoverable Fault Codes (signed 8-bit)
 *===========================================================================*/

/** @brief Recoverable fault codes (signed 8-bit). */
typedef enum {
    ROM_KM_RFAULT_KEY_SLOT_CRC      = -1, /**< Key slot CRC integrity failure */
    ROM_KM_RFAULT_RX_BUFF_OFLOW     = -2, /**< RX buffer overflow (unterminated msg) */
    ROM_KM_RFAULT_MBOX_OVERFLOW     = -3, /**< Outbound mailbox FIFO overflow */
    ROM_KM_RFAULT_MBOX_UNDERFLOW    = -4, /**< Inbound mailbox FIFO underflow */
    ROM_KM_RFAULT_FLUSHED_BY_SEP    = -5  /**< Mailbox flushed by SEP */
} rom_km_recov_fault_code_t;

/*===========================================================================
 * Unrecoverable Fault Codes (signed 8-bit)
 *===========================================================================*/

/** @brief Unrecoverable fault codes (signed 8-bit). */
typedef enum {
    ROM_KM_UFAULT_WIPE_STATE        = -1,  /**< WIPE_STATE asserted */
    ROM_KM_UFAULT_ROM_PARITY        = -2,  /**< ROM parity error */
    ROM_KM_UFAULT_SRAM_PARITY       = -3,  /**< SRAM parity error */
    ROM_KM_UFAULT_ROM_WRITE         = -4,  /**< Illegal write to ROM */
    ROM_KM_UFAULT_SRAM_WRITE_LOCK   = -5,  /**< Write to locked SRAM region */
    ROM_KM_UFAULT_AXI_DECERR        = -6,  /**< AXI decode error */
    ROM_KM_UFAULT_AXI_SLVERR        = -7,  /**< AXI slave error */
    ROM_KM_UFAULT_DRBG_ERR          = -8,  /**< DRBG hardware error */
    ROM_KM_UFAULT_ILLEGAL_INSN      = -9,  /**< Illegal instruction trap */
    ROM_KM_UFAULT_BUS_ERROR         = -10, /**< AXI bus-error trap */
    ROM_KM_UFAULT_EBREAK            = -11, /**< EBREAK instruction trap */
    ROM_KM_UFAULT_SPURIOUS_IRQ      = -12, /**< Unrecognised IRQ source */
    ROM_KM_UFAULT_OTP_SIGINT        = -13, /**< OTP dual-rail integrity violation */
    ROM_KM_UFAULT_FW_CRC            = -14, /**< Mutable firmware image CRC-32C mismatch */
    ROM_KM_UFAULT_FW_STACK_OVF      = -15, /**< Firmware load destination exceeded stack guard */
    ROM_KM_UFAULT_SHRED_RANGE       = -16  /**< Shred word count exceeded the shred-order buffer */
} rom_km_unrecov_fault_code_t;

/*===========================================================================
 * Message Header Layout
 *===========================================================================*/

/** @brief Command/response message header (32-bit packed word) */
typedef union {
    uint32_t raw;
    struct {
        uint8_t seq_num;        /**< [7:0]   Sequence number */
        uint8_t id;             /**< [15:8]  Command or response ID */
        uint8_t payload_len;    /**< [23:16] Payload length in words */
        uint8_t header_crc8;    /**< [31:24] CRC-8/ROHC of lower 24 bits */
    } __attribute__((packed));
} rom_km_msg_header_t;

/*===========================================================================
 * Command Handler Result
 *===========================================================================*/

/** @brief Result returned by every command handler. */
typedef struct {
    int8_t   return_code;   /**< Return code from rom_km_return_code_t */
    uint8_t  has_arg;       /**< 1 if return_arg is valid */
    uint32_t return_arg;    /**< Optional packed 32-bit return argument */
} rom_km_cmd_result_t;

/*===========================================================================
 * Command Payload Argument Structs
 *===========================================================================*/

/** @brief Payload for CMD_KPVLP_SLOT_REQ (0x20): 1 word. */
typedef struct {
    uint32_t slot_req;      /**< [2:0] encoded request; num_slots = slot_req+1 */
} rom_km_cmd_slot_req_args_t;

/** @brief Payload for CMD_KPVLP_KEY_REGISTER (0x21): 4 words. */
typedef struct {
    uint32_t base_slot;     /**< [4:0] base slot index in KPV */
    uint32_t key_size;      /**< [6:0] key size in words minus 1 */
    uint32_t dest_valid;    /**< [3:0] destination engine bitmask */
    uint32_t key_crc32;     /**< [31:0] CRC-32C of key data */
} rom_km_cmd_kpvlp_key_register_args_t;

/** @brief Payload for CMD_KEY_GENERATE (0x22): 2 words. */
typedef struct {
    uint32_t req_size;      /**< [6:0] requested key size in words minus 1 */
    uint32_t dest_valid;    /**< [3:0] destination engine bitmask */
} rom_km_cmd_key_generate_args_t;

/** @brief Payload for CMD_KEY_REVOKE (0x23): 1 word. */
typedef struct {
    uint32_t handle;        /**< [7:0] key handle to revoke */
} rom_km_cmd_key_revoke_args_t;

/** @brief Payload for CMD_KEY_TRANSFER (0x24): 2 words. */
typedef struct {
    uint32_t handle;        /**< [7:0] key handle to transfer */
    uint32_t dest_engines;  /**< [3:0] destination engine bitmask */
} rom_km_cmd_key_transfer_args_t;

/** @brief Payload for CMD_ENGINE_SHRED (0x25): 1 word. */
typedef struct {
    uint32_t dest;          /**< [3:0] engine bitmask to shred */
} rom_km_cmd_engine_shred_args_t;

/**
 * @brief Payload for CMD_KEY_LOAD (0x26): variable length (KEY_SIZE+3 words).
 *
 * word 0: KEY_SIZE[6:0]    RESERVED[31:7]=0  — number of KEY_DATA words minus 1 (FR-2739-002)
 * word 1: DEST_VALID[7:0]  RESERVED[31:8]=0  — destination engine bitmask (FR-2739-002, FR-2739-004)
 * words 2..(2+KEY_SIZE): KEY_DATA[0..KEY_SIZE] — cleartext key material
 *
 * Total payload length = KEY_SIZE + 3 32-bit words (not counting PAYLOAD_CRC32).
 */
typedef struct {
    uint32_t key_size;      /**< [6:0] key word count minus 1; RESERVED[31:7] must be 0 */
    uint32_t dest_valid;    /**< [7:0] destination engine bitmask; RESERVED[31:8] must be 0 */
    uint32_t key_data[];    /**< KEY_SIZE+1 key words (flexible array member) */
} rom_km_cmd_key_load_args_t;

/*===========================================================================
 * Crypto Engine Destination Bitfield (shared by DEST_VALID / DEST_ENGINE)
 *===========================================================================*/

/** @brief Crypto engine destination bitmask (shared by DEST_VALID / DEST_ENGINE). */
typedef union {
    uint8_t raw;            /**< Raw 8-bit value */
    struct {
        uint8_t hmac_sha2 : 1;  /**< bit 0: HMAC-SHA2 engine */
        uint8_t kmac_sha3 : 1;  /**< bit 1: KMAC-SHA3 engine */
        uint8_t aes       : 1;  /**< bit 2: AES engine */
        uint8_t otbn      : 1;  /**< bit 3: OTBN engine */
        uint8_t _rsvd     : 4;  /**< bits [7:4]: reserved */
    };
} rom_km_dest_bits_t;

/*===========================================================================
 * Command Return Argument Structs
 *===========================================================================*/

/** @brief Return argument for CMD_HW_VER(0x00), CMD_ROM_VER(0x01), CMD_SRAM_VER(0x02). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t patch  : 8;   /* [7:0]   */
        uint32_t minor  : 8;   /* [15:8]  */
        uint32_t major  : 8;   /* [23:16] */
        uint32_t _rsvd  : 8;   /* [31:24] */
    };
} rom_km_version_ret_t;

/** @brief Return argument for CMD_STAT(0x03): {rsvd[31:1], RECOVERABLE_ERR[0]}. */
typedef union {
    uint32_t raw;
    struct {
        uint32_t recoverable_err : 1;  /* [0]    */
        uint32_t _rsvd           : 31; /* [31:1] */
    };
} rom_km_stat_ret_t;

/** @brief Return argument for CMD_KPVLP_SLOT_REQ(0x20). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t base_slot_index : 5;  /* [4:0]   */
        uint32_t _rsvd0          : 3;  /* [7:5]   */
        uint32_t slot_grant      : 3;  /* [10:8]  */
        uint32_t _rsvd1          : 21; /* [31:11] */
    };
} rom_km_slot_req_ret_t;

/** @brief Return argument for CMD_KPVLP_KEY_REGISTER(0x21) and CMD_KEY_REVOKE(0x23). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t key_handle : 8;   /* [7:0]  */
        uint32_t _rsvd      : 24;  /* [31:8] */
    };
} rom_km_handle_ret_t;

/** @brief Return argument for CMD_KEY_GENERATE(0x22). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t key_handle  : 8;  /* [7:0]   */
        uint32_t req_size    : 7;  /* [14:8]  */
        uint32_t _rsvd0      : 1;  /* [15]    */
        uint32_t dest_valid  : 8;  /* [23:16] */
        uint32_t _rsvd1      : 8;  /* [31:24] */
    };
} rom_km_key_generate_ret_t;

/** @brief Return argument for CMD_KEY_TRANSFER(0x24). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t key_handle   : 8;  /* [7:0]   */
        uint32_t dest_engine  : 8;  /* [15:8]  */
        uint32_t _rsvd        : 16; /* [31:16] */
    };
} rom_km_key_transfer_ret_t;

/** @brief Return argument for CMD_ENGINE_SHRED(0x25). */
typedef union {
    uint32_t raw;
    struct {
        uint32_t dest_engine : 8;  /* [7:0]  */
        uint32_t _rsvd       : 24; /* [31:8] */
    };
} rom_km_engine_shred_ret_t;

#endif /* !__ASSEMBLER__ */

/*===========================================================================
 * EBREAK Opcode (for ISR disambiguation)
 *===========================================================================*/

/** @brief RISC-V EBREAK instruction encoding (used by ISR to distinguish deliberate halt). */
#define ROM_KM_EBREAK_OPCODE        0x00100073

/** @brief RISC-V C.EBREAK (compressed) instruction encoding.
 *  With -march=rv32emc the compiler/assembler may emit the 2-byte form.
 *  A 32-bit load at the ebreak PC will place c.ebreak in the lower half-word. */
#define ROM_KM_C_EBREAK_OPCODE      0x9002

#endif /* ROM_DEFS_H */
