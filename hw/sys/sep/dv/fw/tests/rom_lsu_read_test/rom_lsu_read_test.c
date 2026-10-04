// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP boot-ROM LSU read test. The ROM sanity test covers instruction fetch from
// the boot ROM; this test covers CPU data reads from it and checks that a store
// to it is silently dropped. The boot ROM is reachable only from the CPU, so the
// test runs in cpu mode.
//
// The testbench preloads the boot ROM from mem_rom_test_rom.hex. Each 64-bit ROM
// word is read as two 32-bit loads, low half first.
//
// Checks:
//   CHK-ROM-READ          : loads from the first ROM words match the loaded image.
//   CHK-ROM-BOUNDARY      : the base word and the top valid ROM word read back exactly.
//   CHK-ROM-WRITE-IGNORED : a store to a ROM word completes without a hang or trap,
//                           and the word still holds its image value.

#include <stdint.h>

#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_mailbox.h"

#define ROM_BASE SEP_TOP_SEP_BOOT_ROM_BASE_ADDR
#define ROM_SIZE SEP_TOP_SEP_BOOT_ROM_SIZE
#define ROM_TOP_LO (ROM_BASE + ROM_SIZE - 8) // top valid 64-bit word, low half

static inline uint32_t rd(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the console window
    sep_mbx_puts("SEP boot ROM LSU read test\n");

    // Image words 0..4, each read as low half then high half.
    struct {
        uint32_t addr;
        uint32_t exp;
    } reads[] = {
        {ROM_BASE + 0x00, 0x89abcdef}, {ROM_BASE + 0x04, 0x01234567}, // 0x0123456789abcdef
        {ROM_BASE + 0x08, 0x76543210}, {ROM_BASE + 0x0c, 0xfedcba98}, // 0xfedcba9876543210
        {ROM_BASE + 0x10, 0xdeadbeef}, {ROM_BASE + 0x14, 0x00000000}, // 0x00000000deadbeef
        {ROM_BASE + 0x18, 0x12345678}, {ROM_BASE + 0x1c, 0xcafebabe}, // 0xcafebabe12345678
        {ROM_BASE + 0x20, 0x5a5a5a5a}, {ROM_BASE + 0x24, 0xa5a5a5a5}, // 0xa5a5a5a55a5a5a5a
    };
    int read_ok = 1;
    for (unsigned i = 0; i < sizeof(reads) / sizeof(reads[0]); i++) {
        uint32_t got = rd(reads[i].addr);
        if (got != reads[i].exp) {
            sep_mbx_puts("FAIL: CHK-ROM-READ @");
            sep_mbx_puthex(reads[i].addr);
            sep_mbx_puts(" got ");
            sep_mbx_puthex(got);
            sep_mbx_puts(" exp ");
            sep_mbx_puthex(reads[i].exp);
            sep_mbx_putc('\n');
            errors++;
            read_ok = 0;
        }
    }
    if (read_ok) {
        sep_mbx_puts("CHK-ROM-READ PASS: LSU reads of ROM words match the loaded image\n");
    }

    // The base word is covered by CHK-ROM-READ; read the top valid word here.
    uint32_t tlo = rd(ROM_TOP_LO);
    uint32_t thi = rd(ROM_TOP_LO + 4);
    if (tlo != 0xbaadf00d || thi != 0x0badc0de) {
        sep_mbx_puts("FAIL: CHK-ROM-BOUNDARY top lo ");
        sep_mbx_puthex(tlo);
        sep_mbx_puts(" hi ");
        sep_mbx_puthex(thi);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-ROM-BOUNDARY PASS: base and top valid ROM word read back exactly\n");
    }

    // A store to the ROM must complete and leave the word unchanged.
    uint32_t orig = rd(ROM_BASE + 0x00);
    wr(ROM_BASE + 0x00, 0xFFFFFFFFu);
    __asm__ volatile("fence" ::: "memory");
    uint32_t after = rd(ROM_BASE + 0x00);
    // Compare against the image value, not against `orig`: two reads of a stuck
    // read path would also agree.
    if (after != 0x89abcdefu) {
        sep_mbx_puts("FAIL: CHK-ROM-WRITE-IGNORED content changed ");
        sep_mbx_puthex(after);
        sep_mbx_puts(" was ");
        sep_mbx_puthex(orig);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-ROM-WRITE-IGNORED PASS: store to ROM returned, content "
                     "unchanged (write silently dropped)\n");
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: boot ROM LSU read/boundary/write-ignored all OK\n");
    }
    return errors;
}
