/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Minimal BL1 test payload for OROM boot flow verification (C version).
//
// After the Boot ROM loads this image into ICCM (.text) and DCCM (.data),
// it jumps to _start, which prints debug messages via virtual console,
// configures OBF, then signals PASS via STDOUT mailbox.
//
// Virtual console output (appears as text in cocotb sim log):
//   "BL1\n"     — BL1 entry (proves jump to ICCM succeeded)
//   "OBF\n"     — Outbound filter configured
//   "GO!\n"     — About to write PASS to STDOUT mailbox
//
// Memory layout (VeeR EL2 constraint):
//   .text   → ICCM (0xC0000000) — IFU fetches instructions here
//   .rodata → DCCM (0xC0040000) — LSU reads data here
//   .bss    → DCCM              — LSU reads/writes here
//
// No crt0: BL1 inherits CPU state (SP, PMA, mtvec) from the ROM.
// Fuse addresses come from the generated sep_addr.h.

#include <stdint.h>

#include "../../../../regs/gen/c/sep_addr.h"

// ---------------------------------------------------------------------------
// BSS zeroing (DCCM is uninitialized RAM)
// ---------------------------------------------------------------------------
extern uint32_t BSS_START;
extern uint32_t BSS_END;

// ---------------------------------------------------------------------------
// MMIO helper
// ---------------------------------------------------------------------------
static inline void mmio_write32(uint32_t addr, uint32_t val) {
    *(volatile uint32_t *)(uintptr_t)addr = val;
}

static inline uint32_t mmio_read32(uint32_t addr) {
    return *(volatile uint32_t *)(uintptr_t)addr;
}

// ---------------------------------------------------------------------------
// Scratch register virtual console (same protocol as rom_virt_console.h)
// ---------------------------------------------------------------------------
#define SCRATCH2_ADDR 0x10802010u

#define VCONSOLE_OP_ASCII (0u << 1)

static uint32_t g_vconsole_prev;

static inline void vc_write(uint32_t val) {
    if (val == g_vconsole_prev) val ^= 1u;
    mmio_write32(SCRATCH2_ADDR, val);
    g_vconsole_prev = val;
}

static inline void bl1_puts(const char *s) {
    uint32_t val = VCONSOLE_OP_ASCII;
    int off = 1;
    while (*s) {
        val |= ((uint32_t)(uint8_t)*s++) << (8u * (uint32_t)off++);
        if (off == 4) {
            vc_write(val);
            off = 1;
            val = VCONSOLE_OP_ASCII;
        }
    }
    if (off != 1) vc_write(val);
}

// ---------------------------------------------------------------------------
// Hex print helper for debug output
// ---------------------------------------------------------------------------
static void bl1_puthex32(uint32_t val) {
    // Avoid static const array — -fdata-sections puts it in .rodata.xxx
    // which may not be included in the data binary.
    char buf[11]; // "0x" + 8 hex digits + '\0'
    buf[0] = '0';
    buf[1] = 'x';
    for (int i = 7; i >= 0; i--) {
        uint8_t nib = (uint8_t)((val >> (4u * (uint32_t)i)) & 0xFu);
        buf[2 + (7 - i)] = (char)(nib < 10u ? '0' + nib : 'A' + nib - 10u);
    }
    buf[10] = '\0';
    bl1_puts(buf);
}

// ---------------------------------------------------------------------------
// Fuse read-lock verification
//
// ROM locks CLASS_KEY, RMA_SIP_TOKEN_DIGEST, and RMA_CHIPLET_TOKEN_DIGEST
// before BL1 handoff. Addresses come from sep_addr.h. We verify by:
//   1. Reading the LOCKS register and checking read-lock bits are set
//   2. Reading the actual locked fields and verifying they return 0xBADCAB1E
//
// Locked-field reads return 0xBADCAB1E (no SLVERR), so the check does not
// take an NMI.
// ---------------------------------------------------------------------------
#define EFUSE_LOCKS_ADDR OCH_SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR

// Read-lock bits in LOCKS (same mask as ROM fuse_lock.c):
//   CLASS_KEY_READ_LOCK                     = bit 15
//   RMA_CHIPLET_TOKEN_DIGEST_READ_LOCK      = bit 13
//   RMA_SIP_TOKEN_DIGEST_READ_LOCK          = bit 11
#define FUSE_SECRET_READ_LOCK_MASK 0x0000A800u

#define CLASS_KEY_ADDR OCH_SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR
#define RMA_SIP_TOKEN_ADDR OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR
#define RMA_CHIPLET_TOKEN_ADDR OCH_SEP_TOP_SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_BASE_ADDR
#define LOCKED_FIELD_READ_VALUE 0xBADCAB1Eu

// Returns 0 if all secret fuse read-lock bits are set, nonzero on failure.
static int bl1_verify_fuse_locks(void) {
    uint32_t locks = mmio_read32(EFUSE_LOCKS_ADDR);

    bl1_puts("LOCKS=");
    bl1_puthex32(locks);
    bl1_puts("\n");

    if ((locks & FUSE_SECRET_READ_LOCK_MASK) != FUSE_SECRET_READ_LOCK_MASK) {
        bl1_puts("FAIL:LOCKS\n");
        bl1_puts("EXPECTED=");
        bl1_puthex32(FUSE_SECRET_READ_LOCK_MASK);
        bl1_puts("\n");
        return 1;
    }

    return 0;
}

// Verify that reading locked fields returns 0xBADCAB1E (proves no SLVERR)
static int bl1_test_locked_field_reads(void) {
    uint32_t val;

    // Read CLASS_KEY (should be read-locked)
    val = mmio_read32(CLASS_KEY_ADDR);
    if (val != LOCKED_FIELD_READ_VALUE) {
        bl1_puts("FAIL:CLASS_KEY=");
        bl1_puthex32(val);
        bl1_puts("\n");
        return 1;
    }

    // Read RMA_SIP_TOKEN (should be read-locked)
    val = mmio_read32(RMA_SIP_TOKEN_ADDR);
    if (val != LOCKED_FIELD_READ_VALUE) {
        bl1_puts("FAIL:RMA_SIP=");
        bl1_puthex32(val);
        bl1_puts("\n");
        return 1;
    }

    // Read RMA_CHIPLET_TOKEN (should be read-locked)
    val = mmio_read32(RMA_CHIPLET_TOKEN_ADDR);
    if (val != LOCKED_FIELD_READ_VALUE) {
        bl1_puts("FAIL:RMA_CHIP=");
        bl1_puthex32(val);
        bl1_puts("\n");
        return 1;
    }

    return 0; // Success - all reads returned expected value
}

// ---------------------------------------------------------------------------
// Outbound filter configuration (self-contained, hardcoded addresses)
// ---------------------------------------------------------------------------
#define OBF_BASE 0x10A20000u
#define OBF_CONFIG (OBF_BASE + 0x00u)
#define OBF_START_ADDR (OBF_BASE + 0x08u)
#define OBF_END_ADDR (OBF_BASE + 0x10u)

static inline void bl1_outbound_filter_init(void) {
    // START_ADDR = 0x0000000080000000
    mmio_write32(OBF_START_ADDR, 0x80000000u);
    mmio_write32(OBF_START_ADDR + 4, 0x00000000u);

    // END_ADDR = 0x00000000800000FF
    mmio_write32(OBF_END_ADDR, 0x800000FFu);
    mmio_write32(OBF_END_ADDR + 4, 0x00000000u);

    __asm__ volatile("fence w, w" ::: "memory");

    // CONFIG = 0x0000000101000013
    mmio_write32(OBF_CONFIG, 0x01000013u);
    mmio_write32(OBF_CONFIG + 4, 0x00000001u);

    __asm__ volatile("fence w, w" ::: "memory");
}

// ---------------------------------------------------------------------------
// STDOUT mailbox — PASS/FAIL magic (testbench protocol)
// ---------------------------------------------------------------------------
#define STDOUT_ADDR 0x80000000u
#define FW_MAGIC0 0xA5A55A5Au
#define FW_PASS 0xCAFEBABEu

static inline void mbx_putw(uint32_t w) {
    mmio_write32(STDOUT_ADDR, w);
}

// ---------------------------------------------------------------------------
// Entry point — called directly by ROM's jump_to_bl1().
// ---------------------------------------------------------------------------
__attribute__((section(".text.init"))) void _start(void) {
    // Zero BSS in DCCM (uninitialized RAM).
    for (uint32_t *p = &BSS_START; p < &BSS_END; p++) *p = 0;

    bl1_puts("BL1\n");
    bl1_outbound_filter_init();

    bl1_puts("OBF\n");

    // Verify ROM's fuse read-locks are effective: LOCKS register bits must be set.
    bl1_puts("FUSE_CHK\n");
    int fuse_fail = bl1_verify_fuse_locks();
    if (fuse_fail) {
        bl1_puts("FUSE_LOCK_VERIFY_FAIL\n");
        mbx_putw(FW_MAGIC0);
        mbx_putw(0xDEADDEADu); // FAIL
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("FUSE_OK\n");

    // Verify locked field reads return 0xBADCAB1E (not SLVERR)
    bl1_puts("LOCK_RD\n");
    int read_fail = bl1_test_locked_field_reads();
    if (read_fail) {
        bl1_puts("LOCK_RD_FAIL\n");
        mbx_putw(FW_MAGIC0);
        mbx_putw(0xDEADDEADu);
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("LOCK_RD_OK\n");

    bl1_puts("GO!\n");

    mbx_putw(FW_MAGIC0);
    mbx_putw(FW_PASS);

    // Park: spin in WFI loop.
    for (;;) {
        __asm__ volatile("wfi");
    }
}
