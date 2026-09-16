/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Boot manifest and payload structure definitions for OCAH SEP ROM.
//
// manifest_t is 1184 bytes, packed.

#ifndef __MANIFEST_H_DEFINED__
#define __MANIFEST_H_DEFINED__

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include "sep_helpers.h"

#ifdef __GNUC__
#define _PACKED_ __attribute__((packed))
#else
#define _PACKED_
#endif

// ── Manifest offsets in SPI flash ──
#define PRIMARY_MANIFEST_OFFSET 0x1000
#define BACKUP_MANIFEST_OFFSET 0x41000

// ── Memory layout ──
// SRAM holds the manifest payload the SPI load lands in and is the source of the
// BL1 copy.
#ifndef SEP_SRAM_BASE
#define SEP_SRAM_BASE 0x10000000u // External SRAM base (SEP address map)
#endif
#ifndef SEP_SRAM_SIZE
#define SEP_SRAM_SIZE 0x00040000u // 256 KiB
#endif

// ICCM / DCCM definitions (VeeR EL2 tightly-coupled memories). ICCM and DCCM
// share region 0xC, so any load/store to ICCM faults: BL1 executes from ICCM but
// its .rodata/.data/.bss go to DCCM, and the DMA delivers the ICCM image.
#ifndef SEP_IRAM_BASE
#define SEP_IRAM_BASE 0xC0000000u // ICCM base (VeeR region 0xC, offset 0)
#endif
#ifndef SEP_IRAM_SIZE
#define SEP_IRAM_SIZE 0x00040000u // 256 KiB
#endif
#ifndef SEP_DRAM_BASE
#define SEP_DRAM_BASE 0xC0040000u // DCCM base (VeeR region 0xC, offset 0x40000)
#endif
#ifndef SEP_DRAM_SIZE
#define SEP_DRAM_SIZE 0x00020000u // 128 KiB
#endif

// SPI flash direct-access window base.
#ifndef SEP_SPI_BASE
#define SEP_SPI_BASE 0x30000000u
#endif

// ── Manifest constants ──

/** Currently supported manifest major version. */
#define MANIFEST_MAJOR_VERSION 1

/** Maximum size of a hypothetical v1.x manifest. */
#define MANIFEST_MAX_SIZE 2048

/** Size of the device identifier in words. */
#define DEVICE_ID_NUM_WORDS 8

/** Selector bits for manifest_usage_constraints_t fields. */
#define SELECTOR_BIT_LIFE_CYCLE_STATES (DEVICE_ID_NUM_WORDS * 2)
#define SELECTOR_BIT_BL1_DEMOTION (SELECTOR_BIT_LIFE_CYCLE_STATES + 1)

/** Bits for manifest_usage_constraints_t flags. */
#define USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION 0
#define USAGE_CONSTRAINTS_FLAGS_BIT_ENCRYPTED_PAYLOAD 1
#define USAGE_CONSTRAINTS_FLAGS_BIT_SECURITY_VERSION_UPDATE 2

/** Bits for manifest_boot_arguments_t flag_args. */
#define FLAG_ARGS_BIT_BL2_DEMOTION 0
#define FLAG_ARGS_BIT_USE_EXT_SRAM 29
#define FLAG_ARGS_BIT_SECURE_BOOT 30
#define FLAG_ARGS_BIT_SKIP_SHA256 31

/** Value to use for unselected usage constraint words. */
#define MANIFEST_UNUSED_WORD 0xA5A5A5A5

/** Value used to ensure the TOC header's integrity. */
#define TOC_HEADER_MAGIC_WORD 0x434f5450 // "PTOC"

/** The major version of the TOC the ROM requires. */
#define TOC_MAJOR_VERSION 1

/** Length of an RSA-3072 modulus or signature in bytes. */
#define RSA_3072_KEY_SZ_BYTES (3072 / 8)

/** Length of ECDSA P256 public keys or signatures in bytes. */
#define EC_256_KEY_SZ_BYTES (256 / 8)

/** Public key selection constants. */
#define PUBK_SEL_ROM_KEY 0
#define PUBK_SEL_FUSE_KEY_0 1
#define PUBK_SEL_FUSE_KEY_1 2
#define PUBK_SEL_FUSE_SOP_KEY 4
#define PUBK_SEL_FUSE_SYS_KEY 5
#define PUBK_SEL_NUM_ROM_KEYS 6

/** Signature types. */
#define MANIFEST_SIG_TYPE_RSA_3072 1
#define MANIFEST_SIG_TYPE_ECC_P_256 2

/** Encryption, hashing related constants. */
#define AES_KEY_SIZE_BYTES 16
#define AES_ENC_IV_SIZE_BYTES 16
#define AES_ENC_SALT_SIZE_BYTES 16
#ifndef SHA256_DIGEST_SIZE_BYTES
#define SHA256_DIGEST_SIZE_BYTES 32
#endif

#define MANIFEST_IV_SIZE_BYTES 32
#define MANIFEST_KDF_INPUT_SIZE_BYTES 32

/** Manifest IDs. */
#define MANIFEST_ID_ANY 0x594e4154u  // "TANY"
#define MANIFEST_ID_TBL1 0x314c4254u // "TBL1"
#define MANIFEST_ID_TBL2 0x324c4254u // "TBL2"

/** Image types (6-byte ASCII encoded as u64). */
#define IMAGE_TYPE_SEP_BL1 0x00000314c42504553ull
#define IMAGE_TYPE_SEP_BL2 0x00000324c42504553ull
#define IMAGE_TYPE_SMC_BL1 0x00000314c42434d53ull
#define IMAGE_TYPE_SMC_BL2 0x00000324c42434d53ull

/** Lifecycle States bits. */
#define LC_STATES_BIT_TEST_DEV 0
#define LC_STATES_BIT_PROD 1
#define LC_STATES_BIT_PROD_END 2
#define LC_STATES_BIT_RMA_SOP 3
#define LC_STATES_BIT_RMA_CHIPLET 4

// ── Structure definitions ──

/**
 * Usage constraints.
 */
typedef struct _PACKED_ {
    uint64_t selector_bits;
    uint32_t chiplet_id[8];
    uint32_t package_id[8];
    uint32_t life_cycle_states;
    uint32_t flags;
} manifest_usage_constraints_t;

/**
 * The manifest only supports one of the public key types based on signature_type.
 */
typedef union _PACKED_ {
    uint8_t rsa_modulus[RSA_3072_KEY_SZ_BYTES];
    uint8_t ecdsa_public_key[EC_256_KEY_SZ_BYTES * 2];
} manifest_public_key_t;

typedef union _PACKED_ {
    uint16_t value;
    struct {
        uint16_t index : 4;
        uint16_t selection : 3;
        uint16_t _reserved : 9;
    };
} public_key_sel_t;

/**
 * Signature union (RSA-3072 or ECC P-256).
 */
typedef union _PACKED_ {
    uint8_t rsa_signature[RSA_3072_KEY_SZ_BYTES];
    uint8_t ecdsa_signature[EC_256_KEY_SZ_BYTES * 2];
} manifest_signature_t;

/**
 * Boot arguments (not included in TBS / signed region).
 */
typedef struct _PACKED_ {
    int64_t payload_offset;
    uint32_t flag_args;
    uint32_t _reserved_0;
    uint64_t _reserved_1;
} manifest_boot_arguments_t;

/**
 * Manifest for boot stage images (1184 bytes, packed).
 *
 * Binary layout (offsets):
 *   [0..743]     TBS (to-be-signed) region
 *   [744..1127]  signature (384 bytes)
 *   [1128..1159] manifest_hash (32 bytes, SHA-256 of TBS)
 *   [1160..1183] boot_arguments (24 bytes)
 */
typedef struct _PACKED_ {
    // ── TBS region start ──
    uint32_t manifest_identifier;                                //   0: "TBL1" = 0x314c4254
    uint16_t manifest_version_major;                             //   4
    uint16_t manifest_version_minor;                             //   6
    uint32_t manifest_length;                                    //   8
    uint32_t _reserved_0;                                        //  12
    manifest_usage_constraints_t usage_constraints;              //  16 (80 bytes)
    uint8_t encryption_iv[MANIFEST_IV_SIZE_BYTES];               //  96 (32 bytes)
    uint8_t encryption_kdf_input[MANIFEST_KDF_INPUT_SIZE_BYTES]; // 128 (32 bytes)
    uint16_t _reserved_1;                                        // 160
    uint16_t security_version;                                   // 162
    uint8_t encryption_type;                                     // 164
    uint8_t signature_type;                                      // 165
    public_key_sel_t public_key_sel;                             // 166
    manifest_public_key_t public_key;                            // 168 (384 bytes)
    uint8_t payload_hash[32];                                    // 552
    uint64_t payload_hashed_length;                              // 584
    int64_t timestamp;                                           // 592
    uint64_t payload_length;                                     // 600
    uint64_t manifest_content_version;                           // 608
    uint8_t manifest_description[128];                           // 616
    // ── TBS region end (offset 744) ──
    manifest_signature_t signature;                  // 744 (384 bytes)
    uint8_t manifest_hash[SHA256_DIGEST_SIZE_BYTES]; // 1128
    manifest_boot_arguments_t boot_arguments;        // 1160 (24 bytes)
    // Total: 1184 bytes
} manifest_t;

/**
 * Entry in the TOC for a single image (216 bytes, packed).
 */
struct _PACKED_ toc_entry {
    uint64_t type;
    uint64_t offset;
    uint64_t length;
    uint64_t version;
    uint64_t load_addr;
    uint64_t entry_point;
    uint64_t _reserved_0;
    uint8_t hash[32];
    uint8_t description[128];
};

/**
 * TOC header (32 bytes + flexible array of toc_entry).
 */
struct _PACKED_ toc_header {
    uint32_t identifier; // "PTOC" = 0x434f5450
    uint16_t major_version;
    uint16_t minor_version;
    uint64_t payload_length;
    uint64_t image_count;
    uint64_t _reserved_0;
    struct toc_entry images[];
};

// ── Inline helpers ──

/**
 * Get the payload address from the manifest.
 * payload_offset is a signed byte offset from the start of the manifest.
 */
static inline uint8_t *manifest_payload_address(const manifest_t *const manifest) {
    return (uint8_t *)manifest + manifest->boot_arguments.payload_offset;
}

/**
 * Check a SEP BL1 image entry for validity.
 * The load address must lie inside ICCM, where the IFU fetches BL1 from.
 * Returns 0 on success, non-zero on failure.
 */
static inline uint32_t check_bl1_image(const struct toc_entry *image) {
    if (!contains_range(SEP_IRAM_BASE, SEP_IRAM_SIZE, (size_t)image->load_addr,
                        (size_t)image->length))
        return 1;

    if (image->entry_point >= image->length) return 2;

    return 0;
}

// ── Error codes ──
enum {
    MANIFEST_OK = 0u,
    MANIFEST_ERR_DMA_FAILED = 0x00030001u,
    MANIFEST_ERR_BAD_MAGIC = 0x00030002u,
    MANIFEST_ERR_BAD_VERSION = 0x00030003u,
    MANIFEST_ERR_BAD_LENGTH = 0x00030004u,
    MANIFEST_ERR_BAD_TOC_ID = 0x00030005u,
    MANIFEST_ERR_BAD_TOC_VERSION = 0x00030006u,
    MANIFEST_ERR_PAYLOAD_TOO_LARGE = 0x00030007u,
    MANIFEST_ERR_NO_BL1_IMAGE = 0x00030008u,
    MANIFEST_ERR_BL1_TOO_LARGE = 0x00030009u,
    MANIFEST_ERR_BL1_BAD_ADDR = 0x0003000Au,
    MANIFEST_ERR_HASH_MISMATCH = 0x0003000Bu,
    MANIFEST_ERR_SIG_FAILED = 0x0003000Cu,
    MANIFEST_ERR_BAD_IMAGE_TYPE = 0x0003000Du,
    MANIFEST_ERR_IMAGE_OOB = 0x0003000Eu,
    MANIFEST_ERR_IMAGE_OVERLAP = 0x0003000Fu,
    MANIFEST_ERR_TOC_COUNT = 0x00030010u,
    MANIFEST_ERR_PAYLOAD_OVERLAP = 0x00030011u,
    MANIFEST_ERR_PAYLOAD_BAD_LOC = 0x00030012u,
    MANIFEST_ERR_LC_USAGE_CONSTRAINT = 0x00030013u,
    MANIFEST_ERR_VERSION_ROLLBACK = 0x00030014u,
    MANIFEST_ERR_KEY_REVOKED = 0x00030015u,
    MANIFEST_ERR_KEY_HASH_MISMATCH = 0x00030016u,
    MANIFEST_ERR_PAYLOAD_HASH_MISMATCH = 0x00030017u,
    MANIFEST_ERR_DECRYPT_FAILED = 0x00030018u,
    MANIFEST_ERR_IMAGE_HASH_MISMATCH = 0x00030019u,
};

// ── API declarations ──

struct boot_straps;

uint32_t rom_manifest_boot(const struct boot_straps *straps, uint32_t spi_status, uint32_t lc_state,
                           bool sboot_dis);
uint32_t rom_handoff_bl1(const manifest_t *m);
void rom_clear_ext_sram(void);

#endif // __MANIFEST_H_DEFINED__
