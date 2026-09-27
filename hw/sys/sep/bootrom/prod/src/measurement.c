/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Soft measurement enrollment (PCRV forerunner) -- see include/measurement.h.

#include "measurement.h"

#include <stdbool.h>
#include <stdint.h>

#include "bl0_state.h"
#include "errors.h"
#include "hmac_sha256.h"
#include "rom_virt_console.h"
#include "sep.h"

// Build-time ROM identity (rom_metadata.c; patched by insert-rom-sha256.py).
extern const char g_rom_sha256_str[];

// End of the hashed ROM region (.text + .metadata), from link/rom.ld.
extern uint8_t __metadata_end[];

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

// Parse "sha256:<64 hex>" into 32 bytes. Returns true on success.
static bool parse_rom_hash_str(const char *s, uint8_t out[32]) {
    static const char prefix[] = "sha256:";
    for (uint32_t i = 0; i < sizeof(prefix) - 1u; ++i) {
        if (s[i] != prefix[i]) {
            return false;
        }
    }
    s += sizeof(prefix) - 1u;
    for (uint32_t i = 0; i < 32u; ++i) {
        int hi = hex_nibble(s[2u * i]);
        int lo = hex_nibble(s[2u * i + 1u]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return true;
}

uint32_t measurement_enroll(uint32_t slot, const uint8_t *record, uint32_t len) {
    if (slot >= MEAS_NUM_SLOTS || record == (const uint8_t *)0) {
        return 1u;
    }

    struct bl0_state *s = get_bl0_state();

    // buf = soft_pcr[slot] || SHA256(record)
    uint8_t buf[64];
    if (sha256(record, len, &buf[32]) != 0) {
        return 1u;
    }
    for (uint32_t i = 0; i < 32u; ++i) {
        buf[i] = s->soft_pcr[slot][i];
    }

    uint8_t next[32];
    if (sha256(buf, sizeof(buf), next) != 0) {
        return 1u;
    }
    for (uint32_t i = 0; i < 32u; ++i) {
        s->soft_pcr[slot][i] = next[i];
    }

    report_status(STATUS_TYPE_INFO, SEP_MSG_RECORD_MEASUREMENT);
    report_status(STATUS_TYPE_INFO_EXT, (uint16_t)slot);
    return 0u;
}

uint32_t measurement_enroll_rom_hash(void) {
    uint8_t embedded[32];
    uint8_t computed[32];

    if (!parse_rom_hash_str(g_rom_sha256_str, embedded)) {
        simputs("ROM_HASH_PARSE_FAIL\n");
        return 1u;
    }

    // Recompute over the hashed ROM region: .text + .metadata, i.e.
    // [ROM base, __metadata_end).  Matches tools/insert-rom-sha256.py.
    const uint8_t *rom = (const uint8_t *)OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR;
    uint32_t len =
        (uint32_t)((uintptr_t)__metadata_end - (uintptr_t)OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR);
    if (sha256(rom, len, computed) != 0) {
        simputs("ROM_HASH_COMPUTE_FAIL\n");
        return 1u;
    }

    // The ROM hash is public; a plain compare suffices.
    for (uint32_t i = 0; i < 32u; ++i) {
        if (computed[i] != embedded[i]) {
            simputs("ROM_HASH_MISMATCH\n");
            return 1u;
        }
    }
    simputs("ROM_HASH_VERIFIED\n");

    struct bl0_state *s = get_bl0_state();
    for (uint32_t i = 0; i < 32u; ++i) {
        s->rom_hash[i] = embedded[i];
    }

    return measurement_enroll(MEAS_SLOT_ROM, embedded, sizeof(embedded));
}

uint32_t measurement_enroll_boot_state(const uint8_t manifest_hash[32], uint8_t demotion_bits) {
    struct bl0_state *s = get_bl0_state();
    struct boot_state_record *r = &s->meas_boot_record;

    for (uint32_t i = 0; i < 32u; ++i) {
        r->manifest_hash[i] = manifest_hash[i];
    }
    r->lc_state = s->lc_state;
    r->secure_boot = s->secure_boot ? 1u : 0u;
    r->sboot_dis = s->sboot_dis ? 1u : 0u;
    r->demotion = demotion_bits;
    r->reserved = 0u;

    return measurement_enroll(MEAS_SLOT_BOOT_STATE, (const uint8_t *)r, sizeof(*r));
}
