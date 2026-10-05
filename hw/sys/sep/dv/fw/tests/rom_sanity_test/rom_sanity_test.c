// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP boot-ROM IFU sanity test.
//
// Proves the CPU instruction-fetch unit can fetch and execute instructions
// resident in the boot ROM, with no load/store access to ROM. The testlist
// preloads the boot ROM with rom_sanity_rom.hex, which holds seven small
// hand-assembled functions packed as 64-bit little-endian words. The firmware
// runs from ICCM and calls each one through a function pointer, so the body is
// fetched from ROM, and checks the exact return value:
//
//   Func0  addi a0,zero,42 ; ret                       -> 42      (I-type)
//   Func1  addi a0,zero,100; addi a0,a0,23 ; ret        -> 123     (multi-insn)
//   Func2  addi a0,a0,1 ; ret                           -> arg+1   (arg passthrough)
//   Func3  lui a0,0xDEADC; addi a0,a0,-0x111 ; ret      -> 0xDEADBEEF (U-type)
//   Func4  addi a0,zero,55; jal +8; [addi a0,-1] ; ret  -> 55      (J-type jump)
//   Func5  nop x4 ; addi a0,zero,77 ; ret               -> 77      (NOP sled)
//   Func6  add a0,a0,a1 ; ret                           -> a0+a1   (R-type)
//
// main() returns the error count; crt0.s reports it as the PASS/FAIL verdict.

#include <stdint.h>

#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_mailbox.h"

// Entry points of the functions in the preloaded boot-ROM image.
#define ROM_BASE SEP_TOP_SEP_BOOT_ROM_BASE_ADDR
#define ROM_FUNC0 (ROM_BASE + 0x00)
#define ROM_FUNC1 (ROM_BASE + 0x08)
#define ROM_FUNC2 (ROM_BASE + 0x14)
#define ROM_FUNC3 (ROM_BASE + 0x1C)
#define ROM_FUNC4 (ROM_BASE + 0x28)
#define ROM_FUNC5 (ROM_BASE + 0x38)
#define ROM_FUNC6 (ROM_BASE + 0x50)

typedef int32_t (*func_void_t)(void);
typedef int32_t (*func_i32_t)(int32_t);
typedef int32_t (*func_i32_i32_t)(int32_t, int32_t);

// Compare a ROM function's return value to the expected value and log a
// pass/fail line naming the check and the observed value.
static int check(const char *name, int32_t got, int32_t want) {
    sep_mbx_puts(got == want ? "[PASS] " : "[FAIL] ");
    sep_mbx_puts(name);
    sep_mbx_puts(" got=");
    sep_mbx_puthex((uint32_t)got);
    sep_mbx_puts(" want=");
    sep_mbx_puthex((uint32_t)want);
    sep_mbx_putc('\n');
    return got == want ? 0 : 1;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init(); // open the mailbox window
    sep_mbx_puts("STEP filter init done\n");
    sep_mbx_puts("SEP ROM IFU sanity test\n");

    // Each call drives the IFU to fetch the function body from boot-ROM.
    errors += check("IFU simple return (I-type)", ((func_void_t)ROM_FUNC0)(), 42);
    errors += check("IFU multi-instruction", ((func_void_t)ROM_FUNC1)(), 123);
    errors += check("IFU arg passthrough", ((func_i32_t)ROM_FUNC2)(99), 100);
    errors += check("IFU LUI+ADDI (U-type)", ((func_void_t)ROM_FUNC3)(), (int32_t)0xDEADBEEF);
    errors += check("IFU jump (J-type JAL)", ((func_void_t)ROM_FUNC4)(), 55);
    errors += check("IFU NOP sled", ((func_void_t)ROM_FUNC5)(), 77);
    errors += check("IFU two-arg add (R-type)", ((func_i32_i32_t)ROM_FUNC6)(30, 12), 42);

    if (errors == 0) {
        sep_mbx_puts("PASS: 7/7 boot-ROM IFU functions fetched+executed "
                     "(I/U/R/J/NOP)\n");
    }
    return errors;
}
