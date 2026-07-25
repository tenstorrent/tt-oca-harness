// BL0 → BL1 shared state structure for OROM.
//
// Shared state used by ROM and BL1.
// Placed at end of DCCM so BL1 can locate it via magic number.
//
// Phase 1: structure definition + init; crypto/measurement fields are
// placeholders until crypto subsystem is integrated.

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define BL0_STATE_MAGIC 0x53304C42u // "BL0S"

// SHA256 digest size (bytes). Used for ROM hash and measurement fields.
#ifndef SHA256_DIGEST_SIZE_BYTES
#define SHA256_DIGEST_SIZE_BYTES 32
#endif

// DCCM layout (from linker script / EL2 snapshot).
#define OROM_DCCM_BASE 0xC0040000u
#define OROM_DCCM_SIZE 0x00020000u // 128 KiB

// Boot mode identifiers (C13.8: BL0 state expansion).
enum {
    BOOT_MODE_UNKNOWN = 0u,
    BOOT_MODE_SPI = 1u,       // primary chiplet, normal (SPI flash)
    BOOT_MODE_RECOVERY = 2u,  // primary chiplet, recovery (SMC SRAM)
    BOOT_MODE_SECONDARY = 3u, // secondary chiplet (SMC SRAM)
};

struct bl0_state {
    uint32_t start_magic;

    // Full SEP address of the validated manifest in SEP SRAM.
    // Set after manifest load + validation succeeds.
    uint32_t sep_sram_manifest_addr;

    // Full SEP address of the status buffer in SMC SRAM.
    // Set after status reporting init.
    uint32_t smc_sram_status_addr;

    // Boot mode taken by ROM (BOOT_MODE_*).
    uint32_t boot_mode;

    // Whether secure boot is enabled (from manifest flags + LC + fuse).
    bool secure_boot;

    // sboot_dis fuse value (C10b): chicken bit to disable secure boot.
    bool sboot_dis;

    // Lifecycle state (decoded 4-bit value from efuse).
    uint32_t lc_state;

    // Feature control from lifecycle controller (FEAT_CTRL register, 64-bit).
    uint32_t feat_ctrl_lo;
    uint32_t feat_ctrl_hi;

    // Last error code (0 = no error).  Set by rom_err_fail() on failure.
    uint32_t error_code;

    // ROM measurement (SHA256 of measurement inputs).
    // Populated by crypto subsystem after manifest validation.
    uint8_t measurement[SHA256_DIGEST_SIZE_BYTES];

    // Whether BL2 manifest requested CPU demotion.
    bool bl2_demotion_decision;

    // These are at the end so BL1 can find the magic and use size to
    // locate the start of the struct.
    uint32_t size;
    uint32_t end_magic;
};

// BL0 state is placed at end of DCCM for BL1 discovery.
#define BL0_STATE_SIZE sizeof(struct bl0_state)
#define BL0_STATE_ADDR (OROM_DCCM_BASE + OROM_DCCM_SIZE - BL0_STATE_SIZE)

static inline struct bl0_state *get_bl0_state(void) {
    return (struct bl0_state *)(uintptr_t)BL0_STATE_ADDR;
}

// Initialize bl0_state with magic numbers and zero all fields.
// Must be called after DCCM is cleared (vector.S scrub or manual clear).
static inline void init_bl0_state(void) {
    struct bl0_state *s = get_bl0_state();

    // Zero everything first.
    uint8_t *p = (uint8_t *)s;
    for (uint32_t i = 0; i < sizeof(*s); ++i) {
        p[i] = 0;
    }

    s->start_magic = BL0_STATE_MAGIC;
    s->size = (uint32_t)sizeof(struct bl0_state);
    s->end_magic = BL0_STATE_MAGIC;
}

// Verify bl0_state integrity (for BL1 use or debug).
static inline bool verify_bl0_state(const struct bl0_state *s) {
    return s->start_magic == BL0_STATE_MAGIC && s->end_magic == BL0_STATE_MAGIC &&
           s->size == (uint32_t)sizeof(struct bl0_state);
}
