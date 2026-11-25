// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP boot-ROM AR contention test.
//
// The testlist preloads the boot ROM with rom_ar_contention_rom.hex, which
// gen_rom_ar_contention_rom.py builds together with rom_ar_contention_rom.h.
// The image holds ROM_AR_ROUTINES hash routines and a data block of
// ROM_AR_DATA_WORDS words. Routine k runs k nop words before its loop, so each
// loop starts at a different offset in the IFU fetch stream. Each loop
// iteration loads ROM_AR_GROUP_WORDS words of the block from ROM with lw and
// folds each one into h = (h * 33) ^ w. The IFU fetches the routine from ROM and
// the LSU loads the block from ROM, so both masters present AR at the boot-ROM
// mux in the same window.
//
// This firmware runs from ICCM. For each routine k it prints
// "ROM-AR-BEGIN k=<k>", calls the routine ROM_AR_PASSES times over the whole
// block, and prints "ROM-AR-END k=<k>". No other ROM access and no other ROM
// fetch happens between the two markers. Pass p starts from the golden hash of
// pass p-1, so each pass is graded on its own. The golden is the same hash over
// rom_ar_data[], computed here from ICCM code and TCM data, with no ROM access.
//
// Records:
//   ROM-AR-CFG     : the call parameters, which the host compares with its own.
//   CHK-ROM-AR-SUM : one line per routine and pass:
//                    "routine=<k> pass=<p> got=0x.. want=0x..".
// main() returns the error count; crt0.s reports it as the PASS/FAIL verdict.

#include <stdint.h>

#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_mailbox.h"

#include "rom_ar_contention_rom.h"

#define ROM_BASE SEP_TOP_SEP_BOOT_ROM_BASE_ADDR
#define ROM_AR_DATA_ADDR (ROM_BASE + ROM_AR_DATA_OFF)
#define ROM_AR_GROUPS (ROM_AR_DATA_WORDS / ROM_AR_GROUP_WORDS)
#define ROM_AR_PASSES 4u
#define ROM_AR_HASH_INIT 5381u

typedef uint32_t (*rom_hash_fn_t)(uint32_t addr, uint32_t groups, uint32_t h);

static void put_dec(uint32_t v) {
    char buf[10];
    int n = 0;
    do {
        buf[n++] = (char)('0' + v % 10u);
        v /= 10u;
    } while (v != 0u);
    while (n > 0) {
        sep_mbx_putc(buf[--n]);
    }
}

static void put_kv_hex(const char *key, uint32_t v) {
    sep_mbx_puts(key);
    sep_mbx_puthex(v);
}

static void marker(const char *what, uint32_t k) {
    sep_mbx_puts(what);
    sep_mbx_puts(" k=");
    put_dec(k);
    sep_mbx_putc('\n');
}

// One pass of the ROM routine's hash over the whole data block.
static uint32_t hash_ref(uint32_t h) {
    for (uint32_t i = 0; i < ROM_AR_DATA_WORDS; i++) {
        h = (h + (h << 5)) ^ rom_ar_data[i];
    }
    return h;
}

int main(void) {
    int errors = 0;
    uint32_t want[ROM_AR_PASSES];
    uint32_t got[ROM_AR_PASSES];

    sep_outbound_filter_init(); // open the console window
    sep_mbx_puts("SEP ROM AR contention test\n");

    want[0] = hash_ref(ROM_AR_HASH_INIT);
    for (uint32_t p = 1; p < ROM_AR_PASSES; p++) {
        want[p] = hash_ref(want[p - 1]);
    }

    sep_mbx_puts("ROM-AR-CFG");
    put_kv_hex(" routines=", ROM_AR_ROUTINES);
    put_kv_hex(" passes=", ROM_AR_PASSES);
    put_kv_hex(" groups=", ROM_AR_GROUPS);
    put_kv_hex(" data=", ROM_AR_DATA_ADDR);
    put_kv_hex(" init=", ROM_AR_HASH_INIT);
    sep_mbx_putc('\n');

    for (uint32_t k = 0; k < ROM_AR_ROUTINES; k++) {
        rom_hash_fn_t fn = (rom_hash_fn_t)(ROM_BASE + k * ROM_AR_ROUTINE_STRIDE);

        marker("ROM-AR-BEGIN", k);
        got[0] = fn(ROM_AR_DATA_ADDR, ROM_AR_GROUPS, ROM_AR_HASH_INIT);
        for (uint32_t p = 1; p < ROM_AR_PASSES; p++) {
            got[p] = fn(ROM_AR_DATA_ADDR, ROM_AR_GROUPS, want[p - 1]);
        }
        marker("ROM-AR-END", k);

        for (uint32_t p = 0; p < ROM_AR_PASSES; p++) {
            int ok = got[p] == want[p];
            sep_mbx_puts(ok ? "CHK-ROM-AR-SUM PASS: routine=" : "CHK-ROM-AR-SUM FAIL: routine=");
            put_dec(k);
            sep_mbx_puts(" pass=");
            put_dec(p);
            put_kv_hex(" got=", got[p]);
            put_kv_hex(" want=", want[p]);
            sep_mbx_putc('\n');
            errors += ok ? 0 : 1;
        }
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: ");
        put_dec(ROM_AR_ROUTINES * ROM_AR_PASSES);
        sep_mbx_putc('/');
        put_dec(ROM_AR_ROUTINES * ROM_AR_PASSES);
        sep_mbx_puts(" ROM AR contention hashes\n");
    }
    return errors;
}
