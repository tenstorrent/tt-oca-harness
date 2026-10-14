// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// CPU-path TCM ECC: the correctable counters MICCMECT and MDCCMECT, their
// threshold and clamp, the MCEIP delivery, the uncorrectable DCCM load and
// store traps, and the NMI of an uncorrectable DCCM vector-table read on the
// fast-interrupt path.
//
// The host (cocotb/tests/cpu/sep_tcm_ecc_cpu_trap_test.py) draws the threshold
// exponent t, the arming order, the flipped words and bits, and patches them
// into g_prm. It applies the flips with the time-0 TCM flip list after the
// image load. The firmware grades nothing: it prints the CSR reads, the trap
// records and begin and end markers on the console, and the host grades every
// check from them, the CPU trace and the debug-bus pulse counts.
//
// Console lines (one record per line):
//   M G <leg> / M C <leg>          leg markers (sep_console_rec.h)
//   B <tag> <k> / E <tag> <k>      begin and end of one flipped-word access
//   SAMPLE leg= tag= k= ic= dc= mip= mie= mst= traps=
//                                  MICCMECT, MDCCMECT, mip, mie, mstatus and
//                                  the trap count, read after the access
//   ARM leg= kind= traps_before= traps_after= ic= dc= mip=
//   TRAP i= tag= mcause= mscause= mepc=
//   MEIP when= w0..w7= micect=
//   CLAMP ic31= dc31= ict= dct=
//   UE-NBR access= got= traps= / UE access= traps=
//   NMI-SETUP vec= vec_rb= lock_rb= tbl= / NMI mcause= mepc= vec_rb= entry=
//
// DCCM layout. The flipped DCCM words and the NMI vector table lie in the
// reserved window 0xC005_0000 to 0xC005_13FF, between the end of .bss and the
// stack (the host checks BSS_END against the window from the symbol file).
// Nothing in the image writes the window, so the host-loaded data words and
// their flips stay as loaded until the firmware accesses them.

#include <stdint.h>

#include "filter_ctrl.h"
#include "sep.h"
#include "sep_axil_mailbox.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_nmi.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"

#define PRM_MAGIC 0x3526EC0Du
#define NFLIP_MAX 33u

enum {
    P_MAGIC = 0,
    P_SEED,
    P_T,
    P_ORDER, // 0: miss first, 1: reach first
    P_NFLIP, // 2^t + 1 flipped words in each memory
    P_WAIT,
    P_HOLD,
    P_LD_ADDR,
    P_LD_NBR,
    P_LD_EXP,
    P_LD_NBR_EXP,
    P_ST_ADDR,
    P_ST_NBR,
    P_ST_EXP,
    P_ST_NBR_EXP,
    P_ST_LANE,
    P_ST_BYTE,
    P_TBL,
    P_DADDR, // NFLIP_MAX words: the single-flip DCCM words in access order
    P_WORDS = P_DADDR + NFLIP_MAX,
};

volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC,
    [P_WAIT] = 20000u,
    [P_HOLD] = 200u,
};

#define CSR_MICECT 0x7F0
#define CSR_MICCMECT 0x7F1
#define CSR_MDCCMECT 0x7F2
#define CSR_MSCAUSE 0x7FF
#define CSR_MEIVT 0xBC8
#define MIE_MCEIE (1u << 30)
#define CNT_MASK 0x07FFFFFFu
#define MCAUSE_IRQ 0x80000000u
#define PIC_SRC 2u  // mailbox interrupt 1 (hw/sys/sep/doc/interrupts.adoc)
#define PIC_MBOX 1u // mailbox index of PIC_SRC
#define MEIP_WORDS 8u
#define TLOG 16u

enum {
    TAG_NONE = 0,
    TAG_ICCM_ARM,
    TAG_DCCM_ZERO,
    TAG_DCCM_SILENT,
    TAG_DCCM_MISS_ARM,
    TAG_DCCM_CROSS,
    TAG_DCCM_REACH,
    TAG_DCCM_POST,
    TAG_LD_NBR,
    TAG_LD,
    TAG_ST_NBR,
    TAG_ST,
    TAG_NMI,
};
static const char *const k_tag[] = {
    "none",       "iccm_arm",   "dccm_zero", "dccm_silent", "dccm_miss_arm",
    "dccm_cross", "dccm_reach", "dccm_post", "ld_nbr",      "ld",
    "st_nbr",     "st",         "nmi",
};

struct trap_rec {
    uint32_t mcause, mscause, mepc, tag;
};
static volatile struct trap_rec g_tlog[TLOG];
static volatile uint32_t g_ntrap;
static volatile uint32_t g_tag;
static uint32_t g_tprinted;

// Per-slot samples of the ICCM block: MICCMECT, MDCCMECT, mip.
static volatile uint32_t g_iccm_samp[NFLIP_MAX * 3u];

#define CSR_READ(n) \
    ({ \
        uint32_t v_; \
        __asm__ volatile("csrr %0, " #n : "=r"(v_)::"memory"); \
        v_; \
    })
#define CSR_WRITE(n, v) __asm__ volatile("csrw " #n ", %0" ::"r"(v) : "memory")
#define CSR_SET(n, v) __asm__ volatile("csrs " #n ", %0" ::"r"(v) : "memory")
#define CSR_CLEAR(n, v) __asm__ volatile("csrc " #n ", %0" ::"r"(v) : "memory")

static inline uint32_t rd32(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr32(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
    __asm__ volatile("fence" ::: "memory");
}

// Every graded access is one 32-bit instruction, so the trap handler resumes
// at mepc + 4.
static inline uint32_t ld_word(uint32_t a) {
    uint32_t v;
    __asm__ volatile(".option push\n.option norvc\nlw %0, 0(%1)\n.option pop"
                     : "=r"(v)
                     : "r"(a)
                     : "memory");
    return v;
}
static inline void st_byte(uint32_t a, uint32_t b) {
    __asm__ volatile(".option push\n.option norvc\nsb %1, 0(%0)\n.option pop" ::"r"(a), "r"(b)
                     : "memory");
}
// Let a corrected access reach the counter before the CSR reads of a sample.
static inline void settle(void) {
    __asm__ volatile("fence\nnop\nnop\nnop\nnop\nnop\nnop\nnop\nnop" ::: "memory");
}

void __attribute__((interrupt("machine"), aligned(4))) trap_handler(void) {
    uint32_t mc = CSR_READ(mcause);
    uint32_t epc = CSR_READ(mepc);
    uint32_t msc = CSR_READ(0x7FF);
    uint32_t n = g_ntrap;
    if (n < TLOG) {
        g_tlog[n].mcause = mc;
        g_tlog[n].mscause = msc;
        g_tlog[n].mepc = epc;
        g_tlog[n].tag = g_tag;
    }
    g_ntrap = n + 1u;
    if (mc & MCAUSE_IRQ) {
        // The handler clears the enable of the request it took, so mret does
        // not re-enter: mie[30] for MCEIP, mie.MEIE for an external interrupt.
        if ((mc & 0x7FFFFFFFu) == 30u) {
            CSR_CLEAR(mie, MIE_MCEIE);
        } else {
            CSR_CLEAR(mie, MIE_MEIE);
        }
    } else {
        CSR_WRITE(mepc, epc + 4u);
    }
}

// Target of the PIC source 2 entry of the DCCM vector table. A core that reads
// the flipped entry without the NMI enters here or at a corrupted address.
void __attribute__((interrupt("machine"), aligned(4))) src2_isr(void) {
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(PIC_SRC), 0u);
    sep_mbx_puts("SRC2-ISR entered\n");
}

static void put_traps(void) {
    uint32_t n = g_ntrap;
    for (uint32_t i = g_tprinted; i < n && i < TLOG; i++) {
        sep_mbx_puts("TRAP");
        rec_hex("i", i);
        rec_str("tag", k_tag[g_tlog[i].tag]);
        rec_hex("mcause", g_tlog[i].mcause);
        rec_hex("mscause", g_tlog[i].mscause);
        rec_hex("mepc", g_tlog[i].mepc);
        rec_end();
    }
    g_tprinted = n;
}

struct samp {
    uint32_t ic, dc, mip, mie, mst, traps;
};

static void take(struct samp *s) {
    settle();
    s->ic = CSR_READ(0x7F1);
    s->dc = CSR_READ(0x7F2);
    s->mip = CSR_READ(mip);
    s->mie = CSR_READ(mie);
    s->mst = CSR_READ(mstatus);
    s->traps = g_ntrap;
}

static void put_samp(const char *leg, const char *tag, uint32_t k, const struct samp *s) {
    sep_mbx_puts("SAMPLE");
    rec_str("leg", leg);
    rec_str("tag", tag);
    rec_hex("k", k);
    rec_hex("ic", s->ic);
    rec_hex("dc", s->dc);
    rec_hex("mip", s->mip);
    rec_hex("mie", s->mie);
    rec_hex("mst", s->mst);
    rec_hex("traps", s->traps);
    rec_end();
}

static void mark(const char *be, const char *tag, uint32_t k) {
    sep_mbx_puts(be);
    sep_mbx_putc(' ');
    sep_mbx_puts(tag);
    rec_hex("k", k);
    rec_end();
    rec_spin(SEP_REC_MARK_SPIN);
}

static void put_meip(const char *when) {
    sep_mbx_puts("MEIP");
    rec_str("when", when);
    static const char *const key[MEIP_WORDS] = {"w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7"};
    for (uint32_t w = 0; w < MEIP_WORDS; w++) {
        rec_hex(key[w], pic_read_meip(w));
    }
    rec_hex("micect", CSR_READ(0x7F0));
    rec_end();
}

static void hold(void) {
    for (volatile uint32_t i = 0; i < g_prm[P_HOLD]; i++) {
    }
}

static void wait_trap(uint32_t n0) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (g_ntrap != n0) {
            break;
        }
    }
    hold();
}

// Arm the MCEIP delivery (mie[30] and mstatus.MIE), wait (bounded) for a trap,
// then clear both. Returns the trap count before the arming.
static uint32_t arm_wait_clear(uint32_t tag) {
    uint32_t n0 = g_ntrap;
    g_tag = tag;
    CSR_SET(mie, MIE_MCEIE);
    CSR_SET(mstatus, MSTATUS_MIE);
    wait_trap(n0);
    CSR_CLEAR(mstatus, MSTATUS_MIE);
    CSR_CLEAR(mie, MIE_MCEIE);
    return n0;
}

static void put_arm(const char *leg, const char *kind, uint32_t n0, const struct samp *s) {
    sep_mbx_puts("ARM");
    rec_str("leg", leg);
    rec_str("kind", kind);
    rec_hex("traps_before", n0);
    rec_hex("traps_after", s->traps);
    rec_hex("ic", s->ic);
    rec_hex("dc", s->dc);
    rec_hex("mip", s->mip);
    rec_end();
    put_traps();
}

// ICCM straight-line block. Slot i is one instruction word (an encoding of
// lui x0, 0xE1C00 + i, which writes nothing) followed by the sample of
// MICCMECT, MDCCMECT and mip into a0[3 * i]. The host flips 2^t + 1 of the 33
// slot words; it finds each slot in the image by its unique encoding. Eight
// leading and trailing nops keep the fetch of a flipped word away from the
// samples taken outside the block.
__asm__(".section .text.iccm_block,\"ax\",@progbits\n"
        ".balign 64\n"
        ".global iccm_block\n"
        "iccm_block:\n"
        ".option push\n"
        ".option norvc\n"
        ".rept 8\n nop\n .endr\n"
        ".irp i, 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,"
        "29,30,31,32\n"
        ".word 0xE1C00037 + (\\i << 12)\n"
        "csrr t0, 0x7F1\n"
        "csrr t1, 0x7F2\n"
        "csrr t2, mip\n"
        "sw t0, (12 * \\i)(a0)\n"
        "sw t1, (12 * \\i + 4)(a0)\n"
        "sw t2, (12 * \\i + 8)(a0)\n"
        ".endr\n"
        ".rept 8\n nop\n .endr\n"
        "ret\n"
        ".option pop\n"
        ".previous\n");
void iccm_block(volatile uint32_t *samp);

static void iccm_leg(void) {
    struct samp s;
    uint32_t n = g_prm[P_NFLIP];
    rec_mark(1, "iccm");
    take(&s);
    put_samp("iccm", "before", 0u, &s);
    mark("B", "iccm_block", 0u);
    iccm_block(g_iccm_samp);
    take(&s);
    mark("E", "iccm_block", 0u);
    put_samp("iccm", "quiet", n, &s);
    for (uint32_t i = 0; i < NFLIP_MAX; i++) {
        sep_mbx_puts("ISLOT");
        rec_hex("k", i);
        rec_hex("ic", g_iccm_samp[3u * i]);
        rec_hex("dc", g_iccm_samp[3u * i + 1u]);
        rec_hex("mip", g_iccm_samp[3u * i + 2u]);
        rec_end();
    }
    mark("B", "iccm_arm", 0u);
    uint32_t n0 = arm_wait_clear(TAG_ICCM_ARM);
    take(&s);
    mark("E", "iccm_arm", 0u);
    put_arm("iccm", "iccm", n0, &s);
    // MCEIP low again before the DCCM leg.
    CSR_WRITE(0x7F1, g_prm[P_T] << 27);
    take(&s);
    put_samp("iccm", "rewrite", 0u, &s);
}

static uint32_t dccm_access(uint32_t k, uint32_t tag, struct samp *s) {
    g_tag = tag;
    mark("B", "dccm_ce", k);
    uint32_t v = ld_word(g_prm[P_DADDR + k]);
    take(s);
    mark("E", "dccm_ce", k);
    return v;
}

static void dccm_leg(void) {
    struct samp s;
    uint32_t t = g_prm[P_T];
    uint32_t thr = 1u << t;
    uint32_t n = g_prm[P_NFLIP];
    uint32_t order = g_prm[P_ORDER];
    uint32_t k = 0;
    rec_mark(1, "dccm_ce");

    // Arming at the count 0: no trap may follow.
    mark("B", "dccm_zero", 0u);
    uint32_t n0 = g_ntrap;
    g_tag = TAG_DCCM_ZERO;
    CSR_SET(mie, MIE_MCEIE);
    CSR_SET(mstatus, MSTATUS_MIE);
    hold();
    take(&s);
    CSR_CLEAR(mstatus, MSTATUS_MIE);
    CSR_CLEAR(mie, MIE_MCEIE);
    mark("E", "dccm_zero", 0u);
    put_arm("dccm", "zero", n0, &s);

    take(&s);
    put_samp("dccm", "pre", 0u, &s);
    uint32_t goal = order == 0u ? thr - 1u : thr;
    uint32_t cnt = s.dc & CNT_MASK;
    while (k < n && cnt < goal) {
        uint32_t v = dccm_access(k, TAG_DCCM_SILENT, &s);
        put_samp("dccm", "silent", k, &s);
        sep_mbx_puts("DATA");
        rec_hex("k", k);
        rec_hex("v", v);
        rec_end();
        cnt = s.dc & CNT_MASK;
        k++;
    }
    uint32_t form = order;
    if (order == 0u && cnt != thr - 1u) {
        form = 1u; // the readback skipped 2^t - 1: the reach-first form
    }
    sep_mbx_puts("FORM");
    rec_hex("order", order);
    rec_hex("form", form);
    rec_hex("cnt", cnt);
    rec_end();
    if (form == 0u) {
        // Arm at 2^t - 1 (no trap), then cross the threshold with one access.
        mark("B", "dccm_miss_arm", 0u);
        n0 = g_ntrap;
        g_tag = TAG_DCCM_MISS_ARM;
        CSR_SET(mie, MIE_MCEIE);
        CSR_SET(mstatus, MSTATUS_MIE);
        hold();
        take(&s);
        mark("E", "dccm_miss_arm", 0u);
        put_arm("dccm", "miss", n0, &s);
        put_samp("dccm", "armed", k, &s);
        n0 = g_ntrap;
        (void)dccm_access(k, TAG_DCCM_CROSS, &s);
        wait_trap(n0);
        CSR_CLEAR(mstatus, MSTATUS_MIE);
        CSR_CLEAR(mie, MIE_MCEIE);
        take(&s);
        put_samp("dccm", "cross", k, &s);
        put_arm("dccm", "cross", n0, &s);
        k++;
    } else {
        mark("B", "dccm_reach_arm", 0u);
        n0 = arm_wait_clear(TAG_DCCM_REACH);
        take(&s);
        mark("E", "dccm_reach_arm", 0u);
        put_arm("dccm", "reach", n0, &s);
    }
    while (k < n) {
        (void)dccm_access(k, TAG_DCCM_POST, &s);
        put_samp("dccm", "post", k, &s);
        k++;
    }
    put_traps();
}

// ---- PIC source 2 pending (the mailbox drive recipe of the PIC tests) ----
#define MBX_IN_SPAN 0x800u
#define FILT_CFG_RW_EN \
    (FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
     FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm)

static void pic_src2_pending(void) {
    uint32_t m = PIC_MBOX;
    volatile uint32_t *cfg =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(m);
    volatile uint32_t *st =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(m);
    volatile uint32_t *en = (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(m);
    uint32_t base = m * SEP_AXIL_MBOX_STRIDE;
    uint32_t s = SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR + base;
    cfg[0] = 0u;
    cfg[1] = 0u;
    st[0] = s;
    st[1] = 0u;
    en[0] = s + MBX_IN_SPAN - 1u;
    en[1] = 0u;
    cfg[0] = FILT_CFG_RW_EN;
    __asm__ volatile("fence" ::: "memory");
    wr32(SEP_AXIL_MBOX0_WIRQT + base, 0u);
    wr32(SEP_AXIL_MBOX0_IRQS + base, SEP_AXIL_MBOX_IRQ_ALL);
    wr32(SEP_AXIL_MBOX0_IRQEN + base, SEP_AXIL_MBOX_IRQ_WRITE);
    pic_write_priord(0u);
    __asm__ volatile("csrwi 0xBC9, 0\n csrwi 0xBCC, 0");
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(PIC_SRC), 15u);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(PIC_SRC), EL2_PIC__MEIE__INTEN_bm);
    wr32(SEP_AXIL_MBOX0_WRITE_DATA + base, 0x35260002u);
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if ((pic_read_meip(0) >> PIC_SRC) & 1u) {
            break;
        }
    }
    sep_mbx_puts("PIC-SRC2");
    rec_hex("irqs", rd32(SEP_AXIL_MBOX0_IRQS + base));
    rec_hex("mie", CSR_READ(mie));
    rec_hex("mst", CSR_READ(mstatus));
    rec_end();
}

// ---- NMI ----
extern void _exit(int) __attribute__((noreturn));

void nmi_h(void) {
    uint32_t mc = CSR_READ(mcause);
    uint32_t epc = CSR_READ(mepc);
    sep_mbx_puts("NMI");
    rec_hex("mcause", mc);
    rec_hex("mepc", epc);
    rec_hex("vec_rb", rd32(SEP_NMI_VEC_ADDR));
    rec_hex("entry", nmi_get_vector_addr());
    rec_hex("traps", g_ntrap);
    rec_end();
    mark("E", "nmi", 0u);
    put_traps();
    rec_mark(0, "end");
    sep_mbx_puts("PASS: TCM ECC CPU trap\n");
    _exit(0);
}

static void nmi_leg(void) {
    rec_mark(1, "nmi");
    nmi_register_handler(nmi_h);
    uint32_t vec = nmi_get_vector_addr();
    wr32(SEP_NMI_VEC_ADDR, vec);
    wr32(SEP_NMI_VEC_LOCK_ADDR, SEP_CPU_CTRL__SEP_NMI_VEC_LOCK__LOCK_bm);
    CSR_WRITE(0xBC8, g_prm[P_TBL]);
    sep_mbx_puts("NMI-SETUP");
    rec_hex("vec", vec);
    rec_hex("vec_rb", rd32(SEP_NMI_VEC_ADDR));
    rec_hex("lock_rb", rd32(SEP_NMI_VEC_LOCK_ADDR));
    rec_hex("tbl", CSR_READ(0xBC8));
    rec_hex("meip0", pic_read_meip(0));
    rec_hex("src2_isr", (uint32_t)(uintptr_t)&src2_isr);
    rec_end();
    g_tag = TAG_NMI;
    mark("B", "nmi", 0u);
    CSR_SET(mie, MIE_MEIE);
    CSR_SET(mstatus, MSTATUS_MIE);
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        __asm__ volatile("nop");
    }
    CSR_CLEAR(mstatus, MSTATUS_MIE);
    sep_mbx_puts("NMI-MISSING");
    rec_hex("traps", g_ntrap);
    rec_end();
    put_traps();
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP TCM ECC CPU trap test\n");
    uint32_t t = g_prm[P_T];
    uint32_t n = g_prm[P_NFLIP];
    if (g_prm[P_MAGIC] != PRM_MAGIC || t > 5u || n != (1u << t) + 1u) {
        sep_mbx_puts("FAIL: parameter block not patched\n");
        return 1;
    }
    sep_mbx_puts("SEED");
    rec_hex("seed", g_prm[P_SEED]);
    rec_end();
    sep_mbx_puts("DRAW");
    rec_hex("t", t);
    rec_hex("order", g_prm[P_ORDER]);
    rec_hex("nflip", n);
    rec_hex("ld", g_prm[P_LD_ADDR]);
    rec_hex("st", g_prm[P_ST_ADDR]);
    rec_hex("tbl", g_prm[P_TBL]);
    rec_end();

    rec_mark(0, "setup");
    CSR_WRITE(mtvec, (uint32_t)(uintptr_t)&trap_handler);
    sep_mbx_puts("CSR0");
    rec_hex("ic", CSR_READ(0x7F1));
    rec_hex("dc", CSR_READ(0x7F2));
    rec_hex("micect", CSR_READ(0x7F0));
    rec_end();

    rec_mark(1, "clamp");
    uint32_t sat = 31u << 27;
    CSR_WRITE(0x7F1, sat);
    uint32_t ic31 = CSR_READ(0x7F1);
    CSR_WRITE(0x7F2, sat);
    uint32_t dc31 = CSR_READ(0x7F2);
    CSR_WRITE(0x7F1, t << 27);
    uint32_t ict = CSR_READ(0x7F1);
    CSR_WRITE(0x7F2, t << 27);
    uint32_t dct = CSR_READ(0x7F2);
    sep_mbx_puts("CLAMP");
    rec_hex("ic31", ic31);
    rec_hex("dc31", dc31);
    rec_hex("ict", ict);
    rec_hex("dct", dct);
    rec_end();

    rec_mark(0, "pic_setup");
    pic_src2_pending();
    put_meip("baseline");

    iccm_leg();
    dccm_leg();

    rec_mark(1, "pic_check");
    CSR_CLEAR(mstatus, MSTATUS_MIE);
    put_meip("correctable");

    // Uncorrectable DCCM load after its clean neighbour.
    rec_mark(1, "ue_load");
    uint32_t n0 = g_ntrap;
    g_tag = TAG_LD_NBR;
    uint32_t v = ld_word(g_prm[P_LD_NBR]);
    settle();
    sep_mbx_puts("UE-NBR");
    rec_str("access", "load");
    rec_hex("got", v);
    rec_hex("traps", g_ntrap - n0);
    rec_end();
    n0 = g_ntrap;
    g_tag = TAG_LD;
    mark("B", "ue_load", 0u);
    (void)ld_word(g_prm[P_LD_ADDR]);
    settle();
    mark("E", "ue_load", 0u);
    sep_mbx_puts("UE");
    rec_str("access", "load");
    rec_hex("traps", g_ntrap - n0);
    rec_end();
    put_traps();
    put_meip("dccm_load");

    // Uncorrectable DCCM byte store after its clean neighbour.
    rec_mark(1, "ue_store");
    uint32_t lane = g_prm[P_ST_LANE] & 3u;
    n0 = g_ntrap;
    g_tag = TAG_ST_NBR;
    st_byte(g_prm[P_ST_NBR] + lane, g_prm[P_ST_BYTE]);
    settle();
    v = ld_word(g_prm[P_ST_NBR]);
    sep_mbx_puts("UE-NBR");
    rec_str("access", "store");
    rec_hex("got", v);
    rec_hex("traps", g_ntrap - n0);
    rec_end();
    n0 = g_ntrap;
    g_tag = TAG_ST;
    mark("B", "ue_store", 0u);
    st_byte(g_prm[P_ST_ADDR] + lane, g_prm[P_ST_BYTE]);
    settle();
    mark("E", "ue_store", 0u);
    sep_mbx_puts("UE");
    rec_str("access", "store");
    rec_hex("traps", g_ntrap - n0);
    rec_end();
    put_traps();
    put_meip("dccm_store");

    nmi_leg();
    rec_mark(0, "end");
    sep_mbx_puts("PASS: TCM ECC CPU trap\n");
    return 0;
}
