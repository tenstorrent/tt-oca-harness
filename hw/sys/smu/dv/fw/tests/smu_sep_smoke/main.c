// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SEP boot-readiness smoke firmware: execute from ICCM and store a
// deterministic result trail into DCCM, with no external-bus dependency.

#include <stdint.h>

// Result window in DCCM, clear of the startup mailbox.
#define RESULT_BASE ((volatile uint32_t *)0xC005F000u)
#define RESULT_WORDS 16u
#define DONE_MARKER 0xC0DEF00Du

static uint32_t mix(uint32_t value) {
    value ^= value << 13;
    value ^= value >> 17;
    value ^= value << 5;
    return value;
}

int main(void) {
    volatile uint32_t *result = RESULT_BASE;
    uint32_t acc = 0x3357u;
    uint32_t check = 0u;

    for (uint32_t index = 0; index < RESULT_WORDS; index++) {
        acc = mix(acc + index);
        result[index] = acc;
        check ^= acc;
    }
    result[RESULT_WORDS] = check;
    result[RESULT_WORDS + 1u] = DONE_MARKER;
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    // Read-back self check keeps the result trail architecturally live.
    for (uint32_t index = 0; index < RESULT_WORDS; index++) {
        check ^= result[index];
    }
    return check == 0u ? 0 : 1;
}
