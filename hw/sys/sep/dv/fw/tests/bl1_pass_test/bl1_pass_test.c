/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Minimal BL1 test payload for OROM boot flow verification (C version).
//
// After the Boot ROM copies this image into SEP ICCM and jumps to _start, it
// copies its own data down to DCCM, checks the BL0 handoff contract, prints
// debug messages via virtual console, configures OBF, then reports PASS in
// cold_scratch[0].
//
// Virtual console output (appears as text in cocotb sim log):
//   "BL1\n"      — BL1 entry (proves the jump into ICCM succeeded)
//   "BL0S_*"     — BL0→BL1 handoff contract fields and verdict
//   "OBF\n"      — Outbound filter configured
//   "GO!\n"      — About to report PASS in cold_scratch[0]
//
// Memory layout — ICCM code, DCCM data, per bl1.ld:
//   iccm : ORIGIN = 0xC0000000, LENGTH = 0x40000   (.text, and the load image)
//   dccm : ORIGIN = 0xC0040000, LENGTH = 0x1FF80   (.rodata/.data/.bss)
//
// The IFU fetches from ICCM directly, but the LSU cannot touch ICCM at all:
// ICCM shares VeeR region 0xC with DCCM, so any 0xCxxxxxxx address outside
// DCCM's offset range is an unmapped access fault. .rodata, .data and .bss
// therefore live in DCCM, and _start initializes them from the SRAM copy of the
// image (bl0_state.bl1_image_src_addr), not from the ICCM copy it executes from.
//
// No crt0: BL1 inherits CPU state (SP, PMA, mtvec) from the ROM, and it uses
// the inherited SP from its first instruction — _start's own prologue pushes ra.
// So BL1's stack frames land in the ROM's DCCM
// stack window, below __stack_top; that is safe only because __stack_top sits
// __bl0_state_reserve bytes below the top of DCCM, so a downward-growing stack
// cannot reach bl0_state. BL1's own data window stops short of the same
// reserve. A BL1 that wants its own stack must set SP itself.
// Fuse addresses come from the generated sep_addr.h.

#include <stdint.h>

#include "../../../../bootrom/prod/include/bl0_state.h"
#include "../../../../regs/gen/c/sep_addr.h"

// ---------------------------------------------------------------------------
// Runtime init: .rodata/.data ship in ICCM and run from DCCM, .bss is NOLOAD
// ---------------------------------------------------------------------------
extern uint32_t __data_load_start;
extern uint32_t __data_start;
extern uint32_t __data_end;
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
#define SCRATCH2_ADDR OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2)

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
static char bl1_hex_digit(uint8_t nibble) {
    if (nibble < 10u) return (char)('0' + nibble);
    return (char)('A' + nibble - 10u);
}

static void bl1_puthex32(uint32_t val) {
    // Avoid static const array — -fdata-sections puts it in .rodata.xxx
    // which may not be included in the data binary.
    char buf[11]; // "0x" + 8 hex digits + '\0'
    buf[0] = '0';
    buf[1] = 'x';
    for (int i = 7; i >= 0; i--) {
        uint8_t nib = (uint8_t)((val >> (4u * (uint32_t)i)) & 0xFu);
        buf[2 + (7 - i)] = bl1_hex_digit(nib);
    }
    buf[10] = '\0';
    bl1_puts(buf);
}

// ---------------------------------------------------------------------------
// BL0 → BL1 handoff contract check
//
// bl0_state is the only thing that crosses the BL0/BL1 boundary: the ROM writes
// it at the top of DCCM (bl0_state.h: BL0_STATE_ADDR = DCCM top - sizeof) and
// BL1 reads it back there. This includes the ROM's own header instead of
// redeclaring the struct, so the two sides cannot disagree about the layout at
// all — the runtime `size` field can only report such a divergence after the
// fact, and only if the divergence happens to change sizeof.
//
// DCCM is readable from here because BL1 runs on the same CPU and the LSU
// decodes the DCCM window directly; the inherited SP is the standing proof.
//
// A failed verify is fatal here. The reference BL1 only prints and continues,
// but continuing means dereferencing sep_sram_manifest_addr out of a struct we
// just proved is not a bl0_state — a wild pointer, which is the exact failure
// this check exists to stop.
// ---------------------------------------------------------------------------
#define SEP_SRAM_LO ((uint32_t)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SEP_SRAM_HI ((uint32_t)(OCH_SEP_TOP_SEP_SRAM_BASE_ADDR + OCH_SEP_TOP_SEP_SRAM_SIZE))

// Returns 0 if the handoff contract is intact, nonzero on failure.
static int bl1_verify_bl0_state(void) {
    const struct bl0_state *s = get_bl0_state();

    // Print the three integrity fields before judging them: on a failure these
    // values name which field went wrong, which a single bool cannot.
    bl1_puts("BL0S@");
    bl1_puthex32((uint32_t)(uintptr_t)s);
    bl1_puts("\nBL0S_START=");
    bl1_puthex32(s->start_magic);
    bl1_puts("\nBL0S_END=");
    bl1_puthex32(s->end_magic);
    bl1_puts("\nBL0S_SIZE=");
    bl1_puthex32(s->size);
    bl1_puts("\n");

    if (!verify_bl0_state(s)) {
        bl1_puts("FAIL:BL0S\n");
        bl1_puts("EXPECTED_MAGIC=");
        bl1_puthex32(BL0_STATE_MAGIC);
        bl1_puts("\nEXPECTED_SIZE=");
        bl1_puthex32((uint32_t)sizeof(struct bl0_state));
        bl1_puts("\n");
        return 1;
    }

    // Magic and size only prove a bl0_state is present. The one field a real
    // BL1 dereferences first is the manifest address, and every path that
    // reaches BL1 has set it on the sole MANIFEST_OK return, so require it to
    // land inside SEP SRAM before anyone follows it.
    uint32_t mfst = s->sep_sram_manifest_addr;
    bl1_puts("BL0S_MFST=");
    bl1_puthex32(mfst);
    bl1_puts("\n");
    if (mfst < SEP_SRAM_LO || mfst >= SEP_SRAM_HI) {
        bl1_puts("FAIL:BL0S_MFST\n");
        return 1;
    }

    // Emit the enrolled boot-state soft PCR in digest byte order. DV rebuilds
    // the packed boot_state_record and applies the two-stage extend operation
    // from measurement.c, so this proves the enrolled value survived handoff.
    bl1_puts("BL0S_BOOT_PCR=");
    for (uint32_t i = 0; i < SHA256_DIGEST_SIZE_BYTES; ++i) {
        uint8_t b = s->soft_pcr[MEAS_SLOT_BOOT_STATE][i];
        char pair[3];
        uint8_t hi = (uint8_t)(b >> 4);
        uint8_t lo = (uint8_t)(b & 0xFu);
        pair[0] = bl1_hex_digit(hi);
        pair[1] = bl1_hex_digit(lo);
        pair[2] = '\0';
        bl1_puts(pair);
    }
    bl1_puts("\n");

    return 0;
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

#define OBF_CONFIG OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0)
#define OBF_START_ADDR OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0)
#define OBF_END_ADDR OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0)

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
// Final verdict — cold_scratch[0] (the only completion channel)
//
// Mirrors the ROM's errors.h VERDICT_OUT / TEST_*_CODE, and the reference's
// sep_common.h, so one probe reads any of the three. Duplicated here
// rather than included because the ROM's errors.h pulls in sep.h,
// rom_virt_console.h and status_ring.h -- far too much for a flat SRAM payload.
// Keep the constants in step with that header.
//
// The DV outbound mailbox at 0x80000000 is outside SEP, behind an outbound
// filter that blocks by default, so it is usable only after
// bl1_outbound_filter_init(); cold_scratch is a SEP register and works from
// the first instruction, so the verdict goes there.
// ---------------------------------------------------------------------------
#define VERDICT_ADDR OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)
#define TEST_PASS_CODE 0xACAFACA1u
#define TEST_FAIL_CODE 0xDEADBEEFu

static inline void bl1_verdict(uint32_t code) {
    mmio_write32(VERDICT_ADDR, code);
}

// ---------------------------------------------------------------------------
// Entry point — called directly by ROM's jump_to_bl1().
// ---------------------------------------------------------------------------
__attribute__((section(".text.init"))) void _start(void) {
    // Bring up .rodata/.data before anything reads them. This runs FIRST and
    // touches nothing but registers, linker symbols and bl0_state: every string
    // literal and every global below lives in the range being initialized.
    //
    // The load image comes from the SRAM copy the ROM handed to the DMA, at the
    // same offset the linker placed it at inside the ICCM image -- not from ICCM
    // itself, which the LSU cannot read.
    //
    // bl0_state is checked with the shared header's pure predicate before that
    // address is trusted; bl1_verify_bl0_state() prints, and printing is not
    // available yet. The full per-field check still runs below.
    {
        const struct bl0_state *s0 = get_bl0_state();
        if (!verify_bl0_state(s0)) {
            bl1_verdict(TEST_FAIL_CODE);
            for (;;) __asm__ volatile("wfi");
        }
        // Both terms are 4-byte aligned: the TOC image offset is 0x1000 and the
        // linker aligns .data's load address.
        const uint32_t *s =
            (const uint32_t *)(uintptr_t)(s0->bl1_image_src_addr +
                                          ((uint32_t)(uintptr_t)&__data_load_start -
                                           (uint32_t)OCH_SEP_TOP_SEP_ICCM_BASE_ADDR));
        for (uint32_t *d = &__data_start; d < &__data_end; ++d, ++s) *d = *s;
    }

    // Zero BSS. The ROM does not clear it, and no loader does either -- .bss is
    // NOLOAD in bl1.ld, so it is whatever DCCM held before.
    for (uint32_t *p = &BSS_START; p < &BSS_END; p++) *p = 0;

    bl1_puts("BL1\n");

    // Handoff contract check, first thing and before the outbound filter is
    // touched: its FAIL report goes to cold_scratch[0], which needs no open
    // filter, so the check runs before anything acts on the contract.
    bl1_puts("BL0S_CHK\n");
    if (bl1_verify_bl0_state()) {
        bl1_puts("BL0S_VERIFY_FAIL\n");
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("BL0S_OK\n");

    bl1_outbound_filter_init();
    bl1_puts("OBF\n");

    // Verify ROM's fuse read-locks are effective: LOCKS register bits must be set.
    bl1_puts("FUSE_CHK\n");
    int fuse_fail = bl1_verify_fuse_locks();
    if (fuse_fail) {
        bl1_puts("FUSE_LOCK_VERIFY_FAIL\n");
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("FUSE_OK\n");

    // Verify locked field reads return 0xBADCAB1E (not SLVERR)
    bl1_puts("LOCK_RD\n");
    int read_fail = bl1_test_locked_field_reads();
    if (read_fail) {
        bl1_puts("LOCK_RD_FAIL\n");
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("LOCK_RD_OK\n");

    bl1_puts("GO!\n");

    bl1_verdict(TEST_PASS_CODE);

    // Park: spin in WFI loop.
    for (;;) {
        __asm__ volatile("wfi");
    }
}
