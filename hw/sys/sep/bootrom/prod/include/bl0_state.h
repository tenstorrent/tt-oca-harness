/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// BL0 → BL1 shared state.  Placed at the top of DCCM, bracketed by magic words
// so BL1 can validate what it finds there.

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

// Boot mode identifiers.
enum {
    BOOT_MODE_UNKNOWN = 0u,
    BOOT_MODE_SPI = 1u,       // primary chiplet, normal (SPI flash)
    BOOT_MODE_RECOVERY = 2u,  // primary chiplet, recovery (SMC SRAM)
    BOOT_MODE_SECONDARY = 3u, // secondary chiplet (SMC SRAM)
};

// Soft measurement slots (PCRV forerunner; see include/measurement.h).
// Slot indices are the intended future PCRV register indices.
#define MEAS_SLOT_ROM 0u        // future PCR[0]: ROM identity
#define MEAS_SLOT_BOOT_STATE 1u // future PCR[1]: boot configuration/state
#define MEAS_NUM_SLOTS 2u

// Raw record enrolled into MEAS_SLOT_BOOT_STATE (packed, little-endian).
// Sits alongside the soft-PCR values so BL1 can re-register the measurement
// into the PCRV once that hardware exists.
struct __attribute__((packed)) boot_state_record {
    uint8_t manifest_hash[32]; // verified manifest hash of the booted manifest
    uint32_t lc_state;         // raw 4-bit LC state, zero-extended
    uint8_t secure_boot;       // secure-boot decision (0/1)
    uint8_t sboot_dis;         // chicken-bit fuse value (0/1)
    uint8_t demotion;          // MEAS_DEMOTION_* bits (measurement.h)
    uint8_t reserved;          // 0
};                             // 40 bytes

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

    // sboot_dis fuse value: chicken bit that disables secure boot.
    bool sboot_dis;

    // Lifecycle state (decoded 4-bit value from efuse).
    uint32_t lc_state;

    // Feature control from lifecycle controller (FEAT_CTRL register, 64-bit).
    uint32_t feat_ctrl_lo;
    uint32_t feat_ctrl_hi;

    // Last error code (0 = no error).  Set by rom_err_fail() on failure.
    uint32_t error_code;

    // Soft measurement bank (PCRV forerunner, measurement.h):
    //   soft_pcr[MEAS_SLOT_ROM]        extended with the verified ROM hash
    //   soft_pcr[MEAS_SLOT_BOOT_STATE] extended with meas_boot_record
    // Slots start all-zero (init_bl0_state) and are extended as
    //   soft_pcr = SHA256(soft_pcr || SHA256(record)).
    uint8_t soft_pcr[MEAS_NUM_SLOTS][SHA256_DIGEST_SIZE_BYTES];

    // Raw measurement inputs for BL1 to re-register into the PCRV: the
    // verified ROM self-hash and the boot-state record.
    uint8_t rom_hash[SHA256_DIGEST_SIZE_BYTES];
    struct boot_state_record meas_boot_record;

    // Whether BL2 manifest requested CPU demotion.
    bool bl2_demotion_decision;

    // SEP SRAM address of BL1's image, which BL1 reads its own .rodata/.data
    // from because it cannot read the ICCM copy it executes.
    uint32_t bl1_image_src_addr;

    // These are at the end so BL1 can find the magic and use size to
    // locate the start of the struct.
    uint32_t size;
    uint32_t end_magic;
};

// BL0 state is placed at end of DCCM for BL1 discovery.
#define BL0_STATE_SIZE sizeof(struct bl0_state)
#define BL0_STATE_ADDR (OROM_DCCM_BASE + OROM_DCCM_SIZE - BL0_STATE_SIZE)

// Bytes the linker keeps clear below the top of DCCM. MUST equal
// __bl0_state_reserve in link/rom.ld; rom_main.c checks the pair at boot.
#define BL0_STATE_RESERVE_BYTES 256u

// A struct larger than the reserve overlaps the stack.
_Static_assert(sizeof(struct bl0_state) <= BL0_STATE_RESERVE_BYTES,
               "struct bl0_state does not fit in the DCCM reserve; raise "
               "__bl0_state_reserve in link/rom.ld and the constant above");

// BL1 reads this struct at a compile-time address, so BL0 and BL1 must be built
// from this header.
_Static_assert(BL0_STATE_ADDR + sizeof(struct bl0_state) == OROM_DCCM_BASE + OROM_DCCM_SIZE,
               "bl0_state must end exactly at the top of DCCM");

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
