/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Narrow uncached MMIO loads whose unrequested byte lanes come back X.
 *
 * Hart 0 reads one 64-bit word behind SYS_OUT with a byte, halfword and word
 * load at every aligned offset, then with one doubleword load. The bench
 * preloads the word and, under +smc_sys_out_r_xfill, drives X on the byte
 * lanes of each narrow read that the read did not ask for, as a 64-to-32-bit
 * downsizer does. Every load must return the requested bytes and retire; a
 * load whose response goes X stops the core before the PASS word.
 */

#include <stdint.h>

#include "metal/cpu.h"
#include "smc.h"
#include "smc_test.h"

#define MMIO_NARROW_ADDR 0xB0000000ull
#define MMIO_NARROW_WORD 0x8877665544332211ull

/* Progress word: number of loads checked so far. */
#define STATUS_LOADS_DONE 0x15020000u

static inline void io_fence(void) {
    __asm__ volatile("fence iorw, iorw" ::: "memory");
}

static uint32_t checked;

static void check(int hartid, const char *what, uint64_t got, uint64_t expected) {
    if (got != expected) {
        raise_fatal_hex32_s(hartid, what, (uint32_t)got);
    }
    checked++;
    write_scratch(1, STATUS_LOADS_DONE | checked);
}

int main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        init_test(hartid);
        const uintptr_t base = (uintptr_t)MMIO_NARROW_ADDR;

        for (uint32_t off = 0; off < 8; off++) {
            uint8_t got = *(volatile uint8_t *)(base + off);
            io_fence();
            check(hartid, "byte load mismatch: ", got, (MMIO_NARROW_WORD >> (8 * off)) & 0xFFu);
        }
        for (uint32_t off = 0; off < 8; off += 2) {
            uint16_t got = *(volatile uint16_t *)(base + off);
            io_fence();
            check(hartid, "halfword load mismatch: ", got,
                  (MMIO_NARROW_WORD >> (8 * off)) & 0xFFFFu);
        }
        for (uint32_t off = 0; off < 8; off += 4) {
            uint32_t got = *(volatile uint32_t *)(base + off);
            io_fence();
            check(hartid, "word load mismatch: ", got,
                  (MMIO_NARROW_WORD >> (8 * off)) & 0xFFFFFFFFu);
        }
        /* Full-width read: no unrequested lane, so no X on the bus. */
        uint64_t full = *(volatile uint64_t *)base;
        io_fence();
        check(hartid, "doubleword load mismatch: ", full, MMIO_NARROW_WORD);

        info_msg_hex32_s(hartid, "narrow MMIO loads checked: ", checked);
        end_test(hartid);
    }

    for (;;) {
        __asm__ volatile("wfi");
    }
    return 0;
}

int secondary_main(void) {
    return main();
}
