// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP boot-ROM LSU data-read + write-ignored firmware test (OSS rep boot-ROM LSU read). reference
// suite provenance: uvm_tests/rom sep_rom_uvm_basic_read / sequential_read / content_verify /
// addr_boundary / write_ignore.
//
// The boot ROM sits on a DEDICATED CPU port (lsu_rom_axi -> u_boot_rom_axi_mux ->
// memory_interface -> the OSS tb_boot_rom_responder; the production RTL puts a
// sep_rom_interface_shim here, which the responder replaces with equivalent
// read-only/write-ignored behavior), reachable only by the EL2 CPU
// (the no_cpu AXI splice forces lsu_axi_req_o, which cannot reach it). So this is
// cpu-mode. The ROM sanity test proves the CPU IFU *executes* from ROM; boot-ROM LSU read covers the LSU
// *data* read-port + the write-silently-ignored negative contract.
//
// The boot ROM responder is preloaded with a known image via
// +sep_boot_rom_hex=mem_rom_test_rom.hex (64-bit words; the CPU is rv32 so each
// 64-bit word is read as two 32-bit LSU loads -- low half at +0, high half at +4).
//
// main() returns the error count; start.S turns 0 -> PASS magic / non-zero ->
// FAIL magic on the 0x8000_0000 mailbox. Every checker logs a positive PASS line.
//
// Checks:
//   CHK-ROM-READ          : LSU reads of ROM words match the loaded image (exact).
//   CHK-ROM-BOUNDARY      : the base word and the top valid ROM word read back exactly.
//   CHK-ROM-WRITE-IGNORED : a store to a ROM word returns a normal response (no hang/
//                           trap) AND a read-back shows the ORIGINAL content (write
//                           silently dropped per sep_rom_interface_shim -- NOT DECERR).

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

    sep_outbound_filter_init(); // open the 0x8000_0000 console window
    sep_mbx_puts("SEP boot ROM LSU read test\n");

    // CHK-ROM-READ: the loaded image (mem_rom_test_rom.hex). Each 64-bit ROM word
    // is read as low half (+0) then high half (+4). Words 0..4 are at indices 0..4.
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

    // CHK-ROM-BOUNDARY: base word (covered above) + top valid 64-bit word.
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

    // CHK-ROM-WRITE-IGNORED: a store to a ROM word must return normally (no hang/
    // trap) and leave the content unchanged (silently dropped, not DECERR).
    uint32_t orig = rd(ROM_BASE + 0x00);
    wr(ROM_BASE + 0x00, 0xFFFFFFFFu);
    __asm__ volatile("fence" ::: "memory");
    uint32_t after = rd(ROM_BASE + 0x00);
    // Compare against the literal from the loaded image, not against `orig` (a DUT
    // read of the same address). Comparing two DUT reads would hold for any stable
    // read, including a path stuck at 0x0 or 0xFFFFFFFF; CHK-ROM-READ pins this word
    // against the image.
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
