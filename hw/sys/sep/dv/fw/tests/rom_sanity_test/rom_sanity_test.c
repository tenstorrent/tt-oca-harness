/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

//-----------------------------------------------------------------------------
// ROM IFU Sanity Test
//
// Tests that the CPU can fetch and execute instructions from ROM via the
// Instruction Fetch Unit (IFU). No load/store (LSU) access to ROM is used.
//
// Strategy:
//   The testbench preloads ROM with known RISC-V instruction sequences that
//   form small callable functions. The firmware calls these ROM functions via
//   function pointers (indirect JALR), causing the IFU to fetch instructions
//   from ROM. Return values are verified to confirm correct instruction fetch.
//
// Test coverage:
//   - I-type instructions (ADDI) fetched from ROM
//   - U-type instructions (LUI) fetched from ROM
//   - R-type instructions (ADD) fetched from ROM
//   - J-type control flow (JAL) within ROM
//   - Sequential multi-instruction fetch
//   - NOP sled (sustained sequential fetch)
//   - Argument passing across SRAM->ROM->SRAM boundary
//
// ROM Instruction Layout (testbench must preload these 32-bit words):
//
// Idx  Offset  Hex          Assembly                 Function
// ---  ------  ----------   ----------------------   -------------------------
//  0   0x00    0x02A00513   addi a0, zero, 42        Func0: return 42
//  1   0x04    0x00008067   ret
//  2   0x08    0x06400513   addi a0, zero, 100       Func1: return 100+23=123
//  3   0x0C    0x01750513   addi a0, a0, 23
//  4   0x10    0x00008067   ret
//  5   0x14    0x00150513   addi a0, a0, 1           Func2: return arg+1
//  6   0x18    0x00008067   ret
//  7   0x1C    0xDEADC537   lui a0, 0xDEADC          Func3: return 0xDEADBEEF
//  8   0x20    0xEEF50513   addi a0, a0, -0x111
//  9   0x24    0x00008067   ret
// 10   0x28    0x03700513   addi a0, zero, 55        Func4: jump test
// 11   0x2C    0x0080006F   jal zero, +8             (skip next instr)
// 12   0x30    0xFFF00513   addi a0, zero, -1        (skipped by JAL)
// 13   0x34    0x00008067   ret
// 14   0x38    0x00000013   nop                      Func5: NOP sled
// 15   0x3C    0x00000013   nop
// 16   0x40    0x00000013   nop
// 17   0x44    0x00000013   nop
// 18   0x48    0x04D00513   addi a0, zero, 77
// 19   0x4C    0x00008067   ret
// 20   0x50    0x00B50533   add a0, a0, a1           Func6: return a0+a1
// 21   0x54    0x00008067   ret
//
// 64-bit ROM words (little-endian packing: [63:32]=offset+4, [31:0]=offset):
//   ROM_MEM[ 0] = 64'h00008067_02A00513   // Func0
//   ROM_MEM[ 1] = 64'h01750513_06400513   // Func1 (part 1)
//   ROM_MEM[ 2] = 64'h00150513_00008067   // Func1 ret + Func2
//   ROM_MEM[ 3] = 64'hDEADC537_00008067   // Func2 ret + Func3
//   ROM_MEM[ 4] = 64'h00008067_EEF50513   // Func3 (part 2)
//   ROM_MEM[ 5] = 64'h0080006F_03700513   // Func4
//   ROM_MEM[ 6] = 64'h00008067_FFF00513   // Func4 (skip + ret)
//   ROM_MEM[ 7] = 64'h00000013_00000013   // Func5 nops
//   ROM_MEM[ 8] = 64'h00000013_00000013   // Func5 nops
//   ROM_MEM[ 9] = 64'h00008067_04D00513   // Func5 addi + ret
//   ROM_MEM[10] = 64'h00008067_00B50533   // Func6
//
//-----------------------------------------------------------------------------

#include <stdio.h>
#include <stdint.h>
#include "test_completion.h"
#include "sep.h"
#include "sep_outbound_filter.h"

//-----------------------------------------------------------------------------
// Function pointer types for calling ROM functions
//-----------------------------------------------------------------------------
typedef int32_t (*func_void_t)(void);
typedef int32_t (*func_i32_t)(int32_t);
typedef int32_t (*func_i32_i32_t)(int32_t, int32_t);

//-----------------------------------------------------------------------------
// ROM function entry points (byte offsets from ROM base)
//-----------------------------------------------------------------------------
#define ROM_BASE    OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR
#define ROM_FUNC0   (ROM_BASE + 0x00)
#define ROM_FUNC1   (ROM_BASE + 0x08)
#define ROM_FUNC2   (ROM_BASE + 0x14)
#define ROM_FUNC3   (ROM_BASE + 0x1C)
#define ROM_FUNC4   (ROM_BASE + 0x28)
#define ROM_FUNC5   (ROM_BASE + 0x38)
#define ROM_FUNC6   (ROM_BASE + 0x50)

static int test_count = 0;
static int pass_count = 0;
static int fail_count = 0;

static void report_test(const char *name, int passed)
{
    test_count++;
    if (passed) {
        pass_count++;
        printf("[PASS] %s\n", name);
    } else {
        fail_count++;
        printf("[FAIL] %s\n", name);
    }
}

//-----------------------------------------------------------------------------
// Test: Simple constant return
// ROM Func0: addi a0, zero, 42 ; ret
// Verifies basic IFU fetch of I-type instruction from ROM.
//-----------------------------------------------------------------------------
static int test_ifu_simple_return(void)
{
    printf("\n--- Test: IFU Simple Return ---\n");

    func_void_t func = (func_void_t)ROM_FUNC0;
    int32_t result = func();

    printf("  ROM@0x%08X -> %d (expected 42)\n",
           (unsigned)ROM_FUNC0, (int)result);
    return result == 42;
}

//-----------------------------------------------------------------------------
// Test: Multi-instruction sequential fetch
// ROM Func1: addi a0, zero, 100 ; addi a0, a0, 23 ; ret
// Verifies IFU can fetch multiple sequential instructions from ROM.
//-----------------------------------------------------------------------------
static int test_ifu_multi_insn(void)
{
    printf("\n--- Test: IFU Multi-Instruction ---\n");

    func_void_t func = (func_void_t)ROM_FUNC1;
    int32_t result = func();

    printf("  ROM@0x%08X -> %d (expected 123)\n",
           (unsigned)ROM_FUNC1, (int)result);
    return result == 123;
}

//-----------------------------------------------------------------------------
// Test: Argument passthrough across SRAM/ROM boundary
// ROM Func2: addi a0, a0, 1 ; ret
// Verifies register a0 is preserved across the SRAM->ROM->SRAM call.
//-----------------------------------------------------------------------------
static int test_ifu_arg_passthrough(void)
{
    printf("\n--- Test: IFU Argument Passthrough ---\n");

    func_i32_t func = (func_i32_t)ROM_FUNC2;
    int32_t result = func(99);

    printf("  ROM@0x%08X(99) -> %d (expected 100)\n",
           (unsigned)ROM_FUNC2, (int)result);
    return result == 100;
}

//-----------------------------------------------------------------------------
// Test: LUI + ADDI sequence (U-type instruction fetch)
// ROM Func3: lui a0, 0xDEADC ; addi a0, a0, -0x111 ; ret
// Verifies IFU can fetch U-type (LUI) instructions from ROM.
//-----------------------------------------------------------------------------
static int test_ifu_lui_addi(void)
{
    printf("\n--- Test: IFU LUI+ADDI ---\n");

    func_void_t func = (func_void_t)ROM_FUNC3;
    int32_t result = func();

    printf("  ROM@0x%08X -> 0x%08X (expected 0xDEADBEEF)\n",
           (unsigned)ROM_FUNC3, (unsigned)result);
    return result == (int32_t)0xDEADBEEF;
}

//-----------------------------------------------------------------------------
// Test: JAL forward jump within ROM
// ROM Func4: addi a0, zero, 55 ; jal zero, +8 ; [addi a0, zero, -1] ; ret
// The JAL skips the bracketed instruction. If jump fails, result would be -1.
// Verifies IFU handles J-type control flow redirects within ROM.
//-----------------------------------------------------------------------------
static int test_ifu_jump(void)
{
    printf("\n--- Test: IFU Jump (JAL) ---\n");

    func_void_t func = (func_void_t)ROM_FUNC4;
    int32_t result = func();

    printf("  ROM@0x%08X -> %d (expected 55)\n",
           (unsigned)ROM_FUNC4, (int)result);
    if (result == -1)
        printf("  ERROR: JAL not taken, fell through to skipped instruction\n");
    return result == 55;
}

//-----------------------------------------------------------------------------
// Test: NOP sled followed by return value
// ROM Func5: nop ; nop ; nop ; nop ; addi a0, zero, 77 ; ret
// Verifies sustained sequential IFU fetch across potential cache line boundary.
//-----------------------------------------------------------------------------
static int test_ifu_nop_sled(void)
{
    printf("\n--- Test: IFU NOP Sled ---\n");

    func_void_t func = (func_void_t)ROM_FUNC5;
    int32_t result = func();

    printf("  ROM@0x%08X -> %d (expected 77)\n",
           (unsigned)ROM_FUNC5, (int)result);
    return result == 77;
}

//-----------------------------------------------------------------------------
// Test: Two-argument R-type instruction
// ROM Func6: add a0, a0, a1 ; ret
// Verifies IFU can fetch R-type (ADD) instructions from ROM.
//-----------------------------------------------------------------------------
static int test_ifu_two_args(void)
{
    printf("\n--- Test: IFU Two-Argument Add ---\n");

    func_i32_i32_t func = (func_i32_i32_t)ROM_FUNC6;
    int32_t result = func(30, 12);

    printf("  ROM@0x%08X(30, 12) -> %d (expected 42)\n",
           (unsigned)ROM_FUNC6, (int)result);
    return result == 42;
}

//-----------------------------------------------------------------------------
// Main
//-----------------------------------------------------------------------------
int main(void)
{
    sep_outbound_filter_init();

    printf("\n");
    printf("========================================\n");
    printf("     SEP ROM IFU Sanity Test\n");
    printf("========================================\n");
    printf("ROM Base: 0x%08X\n", (unsigned)ROM_BASE);
    printf("NOTE: All ROM access is via IFU (instruction fetch) only.\n");
    printf("      No LSU (load/store) access to ROM is performed.\n");

    report_test("IFU Simple Return",       test_ifu_simple_return());
    report_test("IFU Multi-Instruction",   test_ifu_multi_insn());
    report_test("IFU Argument Passthrough", test_ifu_arg_passthrough());
    report_test("IFU LUI+ADDI",            test_ifu_lui_addi());
    report_test("IFU Jump (JAL)",           test_ifu_jump());
    report_test("IFU NOP Sled",             test_ifu_nop_sled());
    report_test("IFU Two-Argument Add",     test_ifu_two_args());

    printf("\n========================================\n");
    printf("     Test Summary\n");
    printf("========================================\n");
    printf("Total:   %d tests\n", test_count);
    printf("Passed:  %d\n", pass_count);
    printf("Errors:  %d\n", fail_count);

    if (fail_count == 0) {
        printf("\n*** ALL TESTS PASSED ***\n");
        test_pass(0);
    } else {
        printf("\n*** SOME TESTS FAILED ***\n");
        test_fail(fail_count);
    }

    while (1) {
        __asm__("wfi");
    }
}
