/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Minimal BL1 payload for the ROM boot flow.
//
// After the Boot ROM copies this image into SEP ICCM and jumps to _start, it
// initializes its data in DCCM, points the NMI vector at its own handler, checks
// the BL0 handoff contract, configures the outbound filter, checks that the ROM
// read-locked the secret fuses and that each locked read raises a bus error, then
// reports PASS in cold_scratch[0]. Progress is printed on the scratch-register
// virtual console.
//
// The IFU fetches from ICCM, but the LSU cannot access ICCM at all, so .rodata,
// .data and .bss live in DCCM (see bl1.ld). _start initializes them from the
// SRAM copy of the image the ROM handed to the DMA, not from the ICCM copy it
// executes from.
//
// There is no crt0: BL1 inherits SP, PMA and mtvec from the ROM and uses the
// inherited stack from its first instruction. That stack starts below the ROM's
// bl0_state reserve at the top of DCCM and grows down, and BL1's data window
// stops short of the same reserve, so neither reaches bl0_state. A BL1 that
// wants its own stack must set SP itself.

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
#define SCRATCH2_ADDR SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2)

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
// it at the top of DCCM and BL1 reads it back there. Including the ROM's own
// header, rather than redeclaring the struct, keeps both sides on one layout.
//
// A failed verify is fatal: continuing would follow sep_sram_manifest_addr out
// of a struct that is not a bl0_state.
// ---------------------------------------------------------------------------
#define SEP_SRAM_LO ((uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR)
#define SEP_SRAM_HI ((uint32_t)(SEP_TOP_SEP_SRAM_BASE_ADDR + SEP_TOP_SEP_SRAM_SIZE))

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

    // Magic and size only prove a bl0_state is present. The manifest address is
    // the first field a real BL1 follows, so it must point into SEP SRAM.
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
// The ROM read-locks the secret fuses before the BL1 handoff. For the class key
// and both RMA token digests, BL1 checks that the lock bits are set and that a
// read of each locked field completes with a bus error. On VeeR-EL2 a D-bus load
// error is an imprecise NMI with mcause 0xF0000001 and the load address latched
// in mdseac; the core drops the load data, so the 0xBADCAB1E the eFuse returns
// with the error never reaches a register.
// ---------------------------------------------------------------------------
#define EFUSE_LOCKS_ADDR SEP_TOP_SEP_EFUSE_MAP_LOCKS_BASE_ADDR

// Read-lock bits of the class key and both RMA token digests.
#define FUSE_SECRET_READ_LOCK_MASK 0x0000A800u

#define CLASS_KEY_ADDR SEP_TOP_SEP_EFUSE_MAP_CLASS_KEY_BASE_ADDR
#define RMA_SIP_TOKEN_ADDR SEP_TOP_SEP_EFUSE_MAP_RMA_SIP_TOKEN_DIGEST_BASE_ADDR
#define RMA_CHIPLET_TOKEN_ADDR SEP_TOP_SEP_EFUSE_MAP_RMA_CHIPLET_TOKEN_DIGEST_BASE_ADDR

#define NMI_VEC_ADDR SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_BASE_ADDR
#define NMI_VEC_LOCK_ADDR SEP_TOP_SEP_CPU_CTRL_SEP_NMI_VEC_LOCK_BASE_ADDR
#define MCAUSE_NMI_LOAD_BUS_ERROR 0xF0000001u
#define CSR_MDSEAC 0xFC0
#define CSR_MDEAU 0xBC0

// Bounds the wait for the imprecise NMI after a locked read; the NMI ends it.
#define NMI_WAIT_LIMIT 1000u

// Written by the NMI handler. An NMI counts toward a read only while that read
// has armed g_nmi_armed; any other NMI is stray.
static volatile uint32_t g_nmi_armed;
static volatile uint32_t g_nmi_count;
static volatile uint32_t g_nmi_mcause;
static volatile uint32_t g_nmi_mdseac;
static volatile uint32_t g_nmi_stray;
static volatile uint32_t g_nmi_stray_mcause;

// Records the NMI and returns to the interrupted code. Writing mdeau unlocks
// mdseac; until then the core raises no NMI for a later D-bus error.
__attribute__((interrupt("machine"), aligned(4), used)) static void bl1_nmi_handler(void) {
    uint32_t mcause, mdseac;
    __asm__ volatile("csrr %0, mcause" : "=r"(mcause));
    __asm__ volatile("csrr %0, %1" : "=r"(mdseac) : "i"(CSR_MDSEAC));
    __asm__ volatile("csrw %0, zero" ::"i"(CSR_MDEAU));
    if (!g_nmi_armed) {
        g_nmi_stray++;
        g_nmi_stray_mcause = mcause;
        return;
    }
    g_nmi_count++;
    g_nmi_mcause = mcause;
    g_nmi_mdseac = mdseac;
}

// The ROM runs BL1 from ICCM or SRAM, so the vector takes the handler's run address.
static int bl1_nmi_init(void) {
    uint32_t want;
    __asm__ volatile("lla %0, bl1_nmi_handler" : "=r"(want));

    mmio_write32(NMI_VEC_ADDR, want);
    uint32_t got = mmio_read32(NMI_VEC_ADDR);
    bl1_puts("NMI_VEC=");
    bl1_puthex32(got);
    bl1_puts("\n");
    if (got != want) {
        bl1_puts("FAIL:NMI_VEC=");
        bl1_puthex32(got);
        bl1_puts(" EXPECTED=");
        bl1_puthex32(want);
        bl1_puts("\n");
        return 1;
    }
    mmio_write32(NMI_VEC_LOCK_ADDR, 1u);
    return 0;
}

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

// Reads addr with the NMI expectation armed. The returned value is meaningful
// only when no NMI arrived, since a faulting load does not write its register.
static uint32_t bl1_bracketed_read(uint32_t addr) {
    g_nmi_count = 0;
    g_nmi_mcause = 0;
    g_nmi_mdseac = 0;
    g_nmi_armed = 1;
    uint32_t val = mmio_read32(addr);
    for (uint32_t i = 0; i < NMI_WAIT_LIMIT && g_nmi_count == 0; i++) {
    }
    g_nmi_armed = 0;
    return val;
}

// Prints the NMIs a bracketed read of `field` took. Returns 0 if there was
// exactly one, a load bus error at addr.
static int bl1_grade_locked_read_nmi(const char *field, uint32_t addr) {
    uint32_t n = g_nmi_count;
    uint32_t mcause = g_nmi_mcause;
    uint32_t mdseac = g_nmi_mdseac;

    bl1_puts("LOCK_RD_NMI=");
    bl1_puts(field);
    bl1_puts(" N=");
    bl1_puthex32(n);
    bl1_puts(" MC=");
    bl1_puthex32(mcause);
    bl1_puts(" DSEAC=");
    bl1_puthex32(mdseac);
    bl1_puts("\n");

    if (n != 1u) {
        bl1_puts("FAIL:LOCK_RD_NMI_COUNT=");
        bl1_puthex32(n);
        bl1_puts("\n");
        return 1;
    }
    if (mcause != MCAUSE_NMI_LOAD_BUS_ERROR) {
        bl1_puts("FAIL:LOCK_RD_MCAUSE=");
        bl1_puthex32(mcause);
        bl1_puts(" EXPECTED=");
        bl1_puthex32(MCAUSE_NMI_LOAD_BUS_ERROR);
        bl1_puts("\n");
        return 1;
    }
    if (mdseac != addr) {
        bl1_puts("FAIL:LOCK_RD_DSEAC=");
        bl1_puthex32(mdseac);
        bl1_puts(" EXPECTED=");
        bl1_puthex32(addr);
        bl1_puts("\n");
        return 1;
    }
    return 0;
}

// Returns 0 if no NMI has arrived outside a locked-field read.
static int bl1_check_stray_nmi(void) {
    if (g_nmi_stray == 0u) return 0;
    bl1_puts("FAIL:NMI_STRAY=");
    bl1_puthex32(g_nmi_stray);
    bl1_puts(" MC=");
    bl1_puthex32(g_nmi_stray_mcause);
    bl1_puts("\n");
    return 1;
}

// Returns 0 if every read-locked field faults with its own address and no NMI
// arrives outside a read. A read that takes no NMI prints the value it returned.
static int bl1_test_locked_field_reads(void) {
    uint32_t val;

    val = bl1_bracketed_read(CLASS_KEY_ADDR);
    if (g_nmi_count == 0u) {
        bl1_puts("FAIL:CLASS_KEY=");
        bl1_puthex32(val);
        bl1_puts("\n");
        return 1;
    }
    if (bl1_grade_locked_read_nmi("CLASS_KEY", CLASS_KEY_ADDR)) return 1;

    val = bl1_bracketed_read(RMA_SIP_TOKEN_ADDR);
    if (g_nmi_count == 0u) {
        bl1_puts("FAIL:RMA_SIP=");
        bl1_puthex32(val);
        bl1_puts("\n");
        return 1;
    }
    if (bl1_grade_locked_read_nmi("RMA_SIP_TOKEN_DIGEST", RMA_SIP_TOKEN_ADDR)) return 1;

    val = bl1_bracketed_read(RMA_CHIPLET_TOKEN_ADDR);
    if (g_nmi_count == 0u) {
        bl1_puts("FAIL:RMA_CHIP=");
        bl1_puthex32(val);
        bl1_puts("\n");
        return 1;
    }
    if (bl1_grade_locked_read_nmi("RMA_CHIPLET_TOKEN_DIGEST", RMA_CHIPLET_TOKEN_ADDR)) return 1;

    return bl1_check_stray_nmi();
}

#define OBF_CONFIG SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0)
#define OBF_START_ADDR SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR(0)
#define OBF_END_ADDR SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR(0)

// Open outbound filter entry 0 over the DV mailbox window, non-secure because the
// mailbox address has bit 55 clear. The window bounds go in before the
// configuration that enables the entry.
static inline void bl1_outbound_filter_init(void) {
    mmio_write32(OBF_START_ADDR, 0x80000000u);
    mmio_write32(OBF_START_ADDR + 4, 0x00000000u);

    mmio_write32(OBF_END_ADDR, 0x800000FFu);
    mmio_write32(OBF_END_ADDR + 4, 0x00000000u);

    __asm__ volatile("fence w, w" ::: "memory");

    mmio_write32(OBF_CONFIG, 0x01000113u);
    mmio_write32(OBF_CONFIG + 4, 0x00000000u);

    __asm__ volatile("fence w, w" ::: "memory");
}

// ---------------------------------------------------------------------------
// Final verdict — cold_scratch[0] (the only completion channel)
//
// The codes match TEST_PASS_CODE / TEST_FAIL_CODE in the ROM's errors.h, so one
// probe reads the ROM and BL1 verdicts. They are copied rather than included
// because errors.h pulls in far too much for a flat payload; keep them in step
// with that header.
//
// The DV mailbox is outside SEP, behind an outbound filter that blocks by
// default, so it is usable only after bl1_outbound_filter_init(); cold_scratch
// is a SEP register and works from the first instruction.
// ---------------------------------------------------------------------------
#define VERDICT_ADDR SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)
#define TEST_PASS_CODE 0xACAFACA1u
#define TEST_FAIL_CODE 0xDEADBEEFu

static inline void bl1_verdict(uint32_t code) {
    mmio_write32(VERDICT_ADDR, code);
}

// ---------------------------------------------------------------------------
// Entry point — called directly by the ROM's rom_handoff_bl1().
// ---------------------------------------------------------------------------
__attribute__((section(".text.init"))) void _start(void) {
    // Initialize .rodata/.data before anything reads them: every string literal
    // and global below lives in that range, so this block touches only
    // registers, linker symbols and bl0_state. The load image comes from the
    // SRAM copy the ROM handed to the DMA, at the offset the linker placed it at
    // inside the ICCM image; the LSU cannot read ICCM itself.
    //
    // bl0_state is checked with the shared header's predicate before its
    // address is trusted. Printing is not available yet, so the full per-field
    // check runs below.
    {
        const struct bl0_state *s0 = get_bl0_state();
        if (!verify_bl0_state(s0)) {
            bl1_verdict(TEST_FAIL_CODE);
            for (;;) __asm__ volatile("wfi");
        }
        // Both terms are 4-byte aligned: the TOC image offset is 0x1000 and the
        // linker aligns .data's load address.
        const uint32_t *s = (const uint32_t *)(uintptr_t)(s0->bl1_image_src_addr +
                                                          ((uint32_t)(uintptr_t)&__data_load_start -
                                                           (uint32_t)SEP_TOP_SEP_ICCM_BASE_ADDR));
        for (uint32_t *d = &__data_start; d < &__data_end; ++d, ++s) *d = *s;
    }

    // Zero BSS. The ROM does not clear it, and no loader does either -- .bss is
    // NOLOAD in bl1.ld, so it is whatever DCCM held before.
    for (uint32_t *p = &BSS_START; p < &BSS_END; p++) *p = 0;

    bl1_puts("BL1\n");

    // Every NMI from here on reaches bl1_nmi_handler, which needs .bss cleared.
    if (bl1_nmi_init()) {
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }

    // The handoff contract is checked before anything acts on it; its failure
    // verdict goes to cold_scratch[0], which needs no open outbound filter.
    bl1_puts("BL0S_CHK\n");
    if (bl1_verify_bl0_state()) {
        bl1_puts("BL0S_VERIFY_FAIL\n");
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("BL0S_OK\n");

    bl1_outbound_filter_init();
    bl1_puts("OBF\n");

    // The ROM's secret-fuse read locks must be in effect.
    bl1_puts("FUSE_CHK\n");
    int fuse_fail = bl1_verify_fuse_locks();
    if (fuse_fail) {
        bl1_puts("FUSE_LOCK_VERIFY_FAIL\n");
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("FUSE_OK\n");

    bl1_puts("LOCK_RD\n");
    int read_fail = bl1_test_locked_field_reads();
    if (read_fail) {
        bl1_puts("LOCK_RD_FAIL\n");
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }
    bl1_puts("LOCK_RD_OK\n");

    // Catches an NMI that arrives after the locked-read check returns.
    if (bl1_check_stray_nmi()) {
        bl1_verdict(TEST_FAIL_CODE);
        for (;;) __asm__ volatile("wfi");
    }

    bl1_puts("GO!\n");

    bl1_verdict(TEST_PASS_CODE);

    for (;;) {
        __asm__ volatile("wfi");
    }
}
