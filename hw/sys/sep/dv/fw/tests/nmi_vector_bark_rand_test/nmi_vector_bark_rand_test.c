// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// WDT bark NMI at the reset vector, through a locked trampoline copy with the
// PIC in drawn gate states, and at a free handler address after a cold reset.
//
// The host (cocotb/tests/cpu/sep_nmi_vector_bark_rand_test.py) draws the
// trampoline copy, the free address A, the bark thresholds, the second case,
// the pending source, its priority and priord from the run seed, and patches
// them into g_prm. The same image boots twice: leg 1 is the locked-copy boot,
// leg 2 (the host re-patches the leg word and applies a cold reset) is the
// free-address boot.
//
// Image layout. nmivb_boot at 0xC000_0000 jumps to _start; nmivb_stub sits at
// 0xC000_0100, the reset value of SEP_NMI_VEC, so a bark with the vector
// unprogrammed runs it. Four trampoline copies sit in four consecutive 256-byte
// slots of a 1 KiB-aligned block, so vector bits [9:8] are the copy index. Each copy records
// their own entry address (auipc) and call one common NMI handler. Every bark
// waits in nmivb_wait, a loop at known addresses, so the host can read the
// first retired PC after the loop on the CPU trace. The free handler Hk at A is
// not in the image: the host places it in the ICCM image outside the image
// bytes.
//
// Records: CHK-NMI-STUB (the reset-vector bark runs the stub once);
// CHK-NMI-ENTRY (each locked-copy bark enters the copy once; the CTRL-MIE-AT-BARK
// read of mstatus.MIE before the bark is the stated value of the leg, and the
// mstatus.MPIE value at the NMI entry is logged as OBS-NMI-MPIE, not graded);
// CHK-NMI-NOPIC (the bark moves no bit of
// any of the eight meip words, masked by the excluded idle bits; the pending
// source delivers once after its gate opens); CHK-NMI-IN-EXT (a bark fired
// while the external handler of the pending source waits enters the locked
// trampoline copy once, inside that handler; the return path is not graded);
// INFO-NMI-HELD (the held-bark leg: the NMI entries, the bark level the
// handler reads and the mepc and mcause of each entry). The handler of that
// leg prints "REQ m t=h0" and "REQ m t=h1" around its hold window, so the host
// counts the bark clocks while the handler runs.
// The vector reads print as CTL lines. The host grades CHK-NMI-TAKEN and
// CHK-BARK-VEC with the CPU trace. The host releases the held NMI coverage of
// a graded leg after every CHK line of that leg passed.

#include <stdint.h>

#include "sep.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_nmi.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"
#include "sep_wdt.h"

#define PRM_MAGIC 0x324A7B0Cu

enum {
    P_MAGIC = 0,
    P_SEED,
    P_LEG,  // 1: locked-copy boot, 2: free-address boot
    P_COPY, // trampoline copy 0..3
    P_A,    // free handler address
    P_CASE, // second case: 1 = b, 2 = c, 3 = d
    P_SRC,  // pending PIC source
    P_RAW,  // usable raw priority of P_SRC for P_PRIORD
    P_PRIORD,
    P_BARK, // 4 words: bark thresholds of the reset-vector, bark 1, bark 2, programmed barks
    P_WAIT = P_BARK + 4,
    P_HOLD,
    P_IDLE,              // 8 words: the excluded idle bits of meip
    P_NEST = P_IDLE + 8, // bark threshold of the bark inside the external handler
    P_HELD,              // bark threshold of the held-bark leg
    P_WORDS,
};

volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC,
    [P_WAIT] = 200000u,
    [P_HOLD] = 3000u,
};

#define STUB_ADDR SEP_NMI_VEC_DEFAULT
#define CASE_B 1u
#define CASE_C 2u
#define CASE_D 3u
// Highest meipl level; meipt and meicurpl take the same encoding.
#define PRI_MAX (EL2_PIC__MEIPL__INTPRIORITY_bm >> EL2_PIC__MEIPL__INTPRIORITY_bp)

// ---- image layout (assembly) ----
// SAVE/RESTORE keep the caller-saved registers of the interrupted loop. SAVE is
// 17 four-byte instructions (norvc), so a copy entry is its auipc minus 68.
#define NMIVB_SAVE \
    "addi sp, sp, -68\n sw ra, 0(sp)\n sw t0, 4(sp)\n sw t1, 8(sp)\n sw t2, 12(sp)\n" \
    " sw t3, 16(sp)\n sw t4, 20(sp)\n sw t5, 24(sp)\n sw t6, 28(sp)\n sw a0, 32(sp)\n" \
    " sw a1, 36(sp)\n sw a2, 40(sp)\n sw a3, 44(sp)\n sw a4, 48(sp)\n sw a5, 52(sp)\n" \
    " sw a6, 56(sp)\n sw a7, 60(sp)\n"
#define NMIVB_RESTORE \
    " lw ra, 0(sp)\n lw t0, 4(sp)\n lw t1, 8(sp)\n lw t2, 12(sp)\n lw t3, 16(sp)\n" \
    " lw t4, 20(sp)\n lw t5, 24(sp)\n lw t6, 28(sp)\n lw a0, 32(sp)\n lw a1, 36(sp)\n" \
    " lw a2, 40(sp)\n lw a3, 44(sp)\n lw a4, 48(sp)\n lw a5, 52(sp)\n lw a6, 56(sp)\n" \
    " lw a7, 60(sp)\n addi sp, sp, 68\n mret\n"
#define NMIVB_COPY(k) \
    ".balign 256, 0\n.globl nmivb_copy" #k "\nnmivb_copy" #k ":\n" NMIVB_SAVE \
    "auipc a0, 0\n addi a0, a0, -68\n li a1, " #k "\n" \
    " call nmivb_common_c\n" NMIVB_RESTORE

// .text.init of this object links ahead of crt0's (the test object is first on
// the link line), so nmivb_boot is the reset entry at 0xC000_0000.
__asm__(
    ".section .text.init,\"ax\",@progbits\n"
    ".option push\n.option norvc\n.option norelax\n"
    ".globl nmivb_boot\nnmivb_boot:\n j _start\n"
    ".balign 256, 0\n.globl nmivb_stub\nnmivb_stub:\n" NMIVB_SAVE
    " call nmivb_stub_c\n" NMIVB_RESTORE ".option pop\n"
    ".section .text.nmivb_copy,\"ax\",@progbits\n"
    ".option push\n.option norvc\n.option norelax\n.balign 1024, 0\n" NMIVB_COPY(0) NMIVB_COPY(1)
        NMIVB_COPY(2) NMIVB_COPY(
            3) ".option pop\n"
               ".section .text.nmivb_wait,\"ax\",@progbits\n"
               ".option push\n.option norvc\n.option norelax\n"
               ".balign 16, 0\n"
               // a0 = flag address, a1 = value before the bark, a2 = bound; returns the bound left.
               ".globl nmivb_wait\nnmivb_wait:\n"
               ".globl nmivb_loop_lo\nnmivb_loop_lo:\n"
               "1: lw t0, 0(a0)\n bne t0, a1, 2f\n addi a2, a2, -1\n bnez a2, 1b\n"
               ".globl nmivb_loop_hi\nnmivb_loop_hi:\n"
               "2: mv a0, a2\n ret\n"
               ".option pop\n");

extern char nmivb_boot[], nmivb_stub[], nmivb_copy0[], nmivb_copy1[], nmivb_copy2[], nmivb_copy3[],
    nmivb_loop_lo[], nmivb_loop_hi[];
extern uint32_t nmivb_wait(volatile uint32_t *flag, uint32_t old, uint32_t bound);

static volatile uint32_t g_flag;
static volatile uint32_t g_stub_runs;
static volatile uint32_t g_nmi_runs;
static volatile uint32_t g_nmi_entry;
static volatile uint32_t g_nmi_copy;
static volatile uint32_t g_nmi_mpie;
// mstatus.MIE read back right before the last bark of bark_nmi().
static volatile uint32_t g_mie_rd;
#define N_MEIP 8u
static volatile uint32_t g_nmi_meip[N_MEIP];
static volatile uint32_t g_ext_runs;
static volatile uint32_t g_ext_id;
// External-handler leg: g_in_ext is 1 while the external handler waits for the
// bark; the NMI handler copies it to g_nmi_in_ext at its entry.
static volatile uint32_t g_nest_mode;
static volatile uint32_t g_in_ext;
static volatile uint32_t g_nmi_in_ext;
static volatile uint32_t g_nest_nmi_runs;
static volatile uint32_t g_nest_timeout;
// Held-bark leg: the NMI handler leaves the bark asserted while it runs.
static volatile uint32_t g_held_mode;
static volatile uint32_t g_held_depth;
static volatile uint32_t g_held_entries;
static volatile uint32_t g_held_bark;
static volatile uint32_t g_held_epc, g_held_cause;
static volatile uint32_t g_held_nested_epc, g_held_nested_cause;
static int g_err;

struct ot_src {
    uint32_t src;
    uint32_t state;
    uint32_t enable;
    uint32_t test;
    uint32_t bit;
};

static const struct ot_src k_ot[] = {
    {18u, SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, HMAC__INTR_STATE__HMAC_DONE_bm},
    {20u, SEP_TOP_HMAC_INTR_STATE_BASE_ADDR, SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_HMAC_INTR_TEST_BASE_ADDR, HMAC__INTR_STATE__HMAC_ERR_bm},
    {21u, SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_STATE__KMAC_DONE_bm},
    {23u, SEP_TOP_KMAC_INTR_STATE_BASE_ADDR, SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_KMAC_INTR_TEST_BASE_ADDR, KMAC__INTR_STATE__KMAC_ERR_bm},
    {24u, SEP_TOP_CSRNG_INTR_STATE_BASE_ADDR, SEP_TOP_CSRNG_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_CSRNG_INTR_TEST_BASE_ADDR, CSRNG__INTR_STATE__CS_CMD_REQ_DONE_bm},
    {28u, SEP_TOP_EDN_INTR_STATE_BASE_ADDR, SEP_TOP_EDN_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_EDN_INTR_TEST_BASE_ADDR, EDN__INTR_STATE__EDN_CMD_REQ_DONE_bm},
    {30u, SEP_TOP_OTBN_INTR_STATE_BASE_ADDR, SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR,
     SEP_TOP_OTBN_INTR_TEST_BASE_ADDR, OTBN__INTR_STATE__DONE_bm},
};
#define N_OT (sizeof(k_ot) / sizeof(k_ot[0]))

static inline uint32_t rd32(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr32(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
    __asm__ volatile("fence" ::: "memory");
}

static const struct ot_src *ot_of(uint32_t s) {
    for (uint32_t i = 0; i < N_OT; i++) {
        if (k_ot[i].src == s) {
            return &k_ot[i];
        }
    }
    return 0;
}

static inline uint32_t meip_bit(uint32_t s) {
    return (pic_read_meip(s >> 5) >> (s & 31u)) & 1u;
}

static void hold(void) {
    for (volatile uint32_t i = 0; i < g_prm[P_HOLD]; i++) {
    }
}

// The bark is cleared with the watchdog off and its count at 0, and the NMI
// line is low (INTR_STATE.bark reads 0) before mret.
static void bark_clear(void) {
    wdt_disable();
    wdt_set_count(0u);
    wdt_clear_bark();
    for (uint32_t i = 0; i < 1000u; i++) {
        if ((wdt_get_intr_state() & WDT_INTR_BARK) == 0u) {
            break;
        }
    }
}

static void bark_arm(uint32_t thold) {
    wdt_set_bite(0xFFFFFFFFu);
    wdt_set_count(0u);
    wdt_set_bark(thold);
    wdt_enable();
}

void nmivb_stub_c(void) {
    g_stub_runs++;
    sep_mbx_puts("M0\n");
    bark_clear();
    g_flag++;
}

#define REQ_SPIN 96u
static void req_mark(const char *tag) {
    rec_req("m");
    rec_str("t", tag);
    rec_end();
    rec_spin(REQ_SPIN);
}

// The handler of the held-bark leg. The first entry keeps the bark asserted
// for the hold window between the host marks h0 and h1, then clears it and
// writes its own mepc and mstatus back before its mret. An entry while the
// first one runs records its mepc and mcause, clears the bark and returns.
static void nmi_held(void) {
    uint32_t epc, mst, cause;
    __asm__ volatile("csrr %0, mepc" : "=r"(epc));
    __asm__ volatile("csrr %0, mstatus" : "=r"(mst));
    __asm__ volatile("csrr %0, mcause" : "=r"(cause));
    g_held_entries++;
    if (++g_held_depth > 1u) {
        g_held_nested_epc = epc;
        g_held_nested_cause = cause;
        bark_clear();
        g_held_depth--;
        return;
    }
    g_held_epc = epc;
    g_held_cause = cause;
    req_mark("h0");
    hold();
    g_held_bark = (wdt_get_intr_state() & WDT_INTR_BARK) != 0u;
    req_mark("h1");
    bark_clear();
    __asm__ volatile("csrw mstatus, %0" ::"r"(mst));
    __asm__ volatile("csrw mepc, %0" ::"r"(epc));
    g_held_depth--;
    g_flag++;
}

void nmivb_common_c(uint32_t entry, uint32_t copy) {
    if (g_held_mode) {
        nmi_held();
        return;
    }
    g_nmi_in_ext = g_in_ext;
    uint32_t mst;
    __asm__ volatile("csrr %0, mstatus" : "=r"(mst));
    for (uint32_t w = 0; w < N_MEIP; w++) {
        g_nmi_meip[w] = pic_read_meip(w);
    }
    g_nmi_entry = entry;
    g_nmi_copy = copy;
    g_nmi_mpie = (mst >> 7) & 1u;
    g_nmi_runs++;
    bark_clear();
    g_flag++;
}

// meihap points at the meivt table entry of the claimed source (crt0 sets
// meivt to INTVEC_BASE), so the entry index is the claim id. An index outside
// the PIC source range returns the reserved source 0.
static inline uint32_t claim_id(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    uint32_t idx = (meihap - (uint32_t)(uintptr_t)INTVEC_BASE) / sizeof(uint32_t);
    return idx < SEP_TOP_PIC_MEIE_NUM ? idx : 0u;
}

// The bark inside the external handler. The NMI overwrites mepc and mstatus
// (VeeR EL2 PRM section 3.16), so the handler saves both before the bark and
// writes them back before its mret. The handler waits on g_flag in nmivb_wait,
// a bounded wait, and clears the bark itself when no NMI comes.
static void nest_bark(void) {
    uint32_t epc, mst;
    __asm__ volatile("csrr %0, mepc" : "=r"(epc));
    __asm__ volatile("csrr %0, mstatus" : "=r"(mst));
    g_nest_mode = 0u;
    uint32_t r0 = g_nmi_runs;
    uint32_t f0 = g_flag;
    g_in_ext = 1u;
    bark_arm(g_prm[P_NEST]);
    uint32_t left = nmivb_wait(&g_flag, f0, g_prm[P_WAIT]);
    g_in_ext = 0u;
    g_nest_nmi_runs = g_nmi_runs - r0;
    g_nest_timeout = left == 0u;
    if (left == 0u) {
        bark_clear();
    }
    __asm__ volatile("csrw mstatus, %0" ::"r"(mst));
    __asm__ volatile("csrw mepc, %0" ::"r"(epc));
}

void __attribute__((interrupt("machine"))) ext_isr(void) {
    uint32_t id = claim_id();
    g_ext_id = id;
    g_ext_runs++;
    const struct ot_src *o = ot_of(id);
    if (o == 0) {
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(id), 0u);
        return;
    }
    wr32(o->test, 0u);
    wr32(o->state, o->bit);
    (void)rd32(o->state);
    for (uint32_t i = 0; i < 2000u; i++) {
        if (meip_bit(id) == 0u) {
            break;
        }
    }
    if (g_nest_mode) {
        nest_bark();
    }
    rec_spin(8u);
}

static void set_order(uint32_t p) {
    pic_write_priord(p);
    uint32_t t = p ? PRI_MAX : 0u;
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEIPT), "r"(t));
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEICURPL), "r"(t));
}

static inline void mstatus_mie(int on) {
    if (on) {
        __asm__ volatile("csrs mstatus, %0" ::"r"(MSTATUS_MIE));
    } else {
        __asm__ volatile("csrc mstatus, %0" ::"r"(MSTATUS_MIE));
    }
}

static uint32_t copy_addr(uint32_t k) {
    switch (k) {
    case 0u:
        return (uint32_t)(uintptr_t)nmivb_copy0;
    case 1u:
        return (uint32_t)(uintptr_t)nmivb_copy1;
    case 2u:
        return (uint32_t)(uintptr_t)nmivb_copy2;
    default:
        return (uint32_t)(uintptr_t)nmivb_copy3;
    }
}

// One bark through the locked trampoline; prints the CHK-NMI-ENTRY record: one
// NMI entry, at the locked copy. Before the bark it reads mstatus.MIE back
// (CTRL-MIE-AT-BARK), and CHK-NMI-ENTRY needs that read equal to mie_at_bark.
// No cited specification states mstatus.MPIE at an NMI entry, so the value the
// handler reads is logged (OBS-NMI-MPIE) and not graded. The host grades the
// same entry with the CPU trace (CHK-NMI-TAKEN).
static int bark_nmi(uint32_t n, uint32_t thold, uint32_t mie_at_bark) {
    uint32_t r0 = g_nmi_runs;
    uint32_t f0 = g_flag;
    uint32_t mst;
    __asm__ volatile("csrr %0, mstatus" : "=r"(mst));
    uint32_t mie_rd = (mst & MSTATUS_MIE) != 0u;
    g_mie_rd = mie_rd;
    rec_ctl("MIE-AT-BARK");
    rec_num("bark", n);
    rec_num("mie", mie_rd);
    rec_num("mie_exp", mie_at_bark);
    rec_end();
    bark_arm(thold);
    uint32_t left = nmivb_wait(&g_flag, f0, g_prm[P_WAIT]);
    hold();
    uint32_t vec = copy_addr(g_prm[P_COPY]);
    int pass = left != 0u && g_nmi_runs - r0 == 1u && g_nmi_entry == vec &&
               g_nmi_copy == g_prm[P_COPY] && mie_rd == mie_at_bark;
    rec_chk("NMI-ENTRY", pass);
    rec_num("bark", n);
    rec_num("copy", g_nmi_copy);
    rec_hex("entry", g_nmi_entry);
    rec_hex("vec", nmi_read_vector_reg());
    rec_num("handler_runs", g_nmi_runs - r0);
    rec_num("mie_at_bark", mie_rd);
    rec_num("mie_exp", mie_at_bark);
    rec_hex("vec_exp", vec);
    rec_num("timeout", left == 0u);
    rec_end();
    rec_obs("NMI-MPIE");
    rec_num("bark", n);
    rec_num("mpie", g_nmi_mpie);
    rec_num("mie_at_bark", mie_rd);
    rec_end();
    if (!pass) {
        g_err++;
    }
    return left != 0u && g_nmi_runs - r0 == 1u;
}

static void meip_snap(uint32_t *out) {
    for (uint32_t w = 0; w < N_MEIP; w++) {
        out[w] = pic_read_meip(w);
    }
}

// Compares all eight meip words read before the bark with the words the NMI
// handler read, each masked by its excluded idle bits. diff_words has bit w
// set when word w differs.
static void nopic_line(const char *cs, const uint32_t *before, int bark_ok, uint32_t delivery,
                       int deliver_ok, int extra_ok) {
    uint32_t diff = 0u;
    for (uint32_t w = 0; w < N_MEIP; w++) {
        uint32_t idle = g_prm[P_IDLE + w];
        if ((before[w] & ~idle) != (g_nmi_meip[w] & ~idle)) {
            diff |= 1u << w;
        }
    }
    int pass = bark_ok && diff == 0u && deliver_ok && extra_ok;
    rec_chk("NMI-NOPIC", pass);
    rec_str("case", cs);
    rec_num("words", N_MEIP);
    rec_hex("diff_words", diff);
    rec_hex("meip0_before", before[0]);
    rec_hex("meip0_after", g_nmi_meip[0]);
    rec_hex("meip1_before", before[1]);
    rec_hex("meip1_after", g_nmi_meip[1]);
    rec_hex("idle_mask0", g_prm[P_IDLE + 0]);
    rec_hex("idle_mask1", g_prm[P_IDLE + 1]);
    rec_num("bit13", (g_nmi_meip[0] >> 13) & 1u);
    rec_num("bit15", (g_nmi_meip[0] >> 15) & 1u);
    if (delivery == 0xFFu) {
        rec_str("delivery", "none");
    } else {
        rec_num("delivery", delivery);
    }
    rec_end();
    if (!pass) {
        g_err++;
    }
}

static uint32_t wait_ext(uint32_t r0) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (g_ext_runs != r0) {
            break;
        }
    }
    hold();
    return g_ext_runs - r0;
}

static int boot1(void) {
    uint32_t s = g_prm[P_SRC];
    uint32_t p = g_prm[P_PRIORD];
    uint32_t raw = g_prm[P_RAW];
    uint32_t never = p ? PRI_MAX : 0u;
    const struct ot_src *o = ot_of(s);
    if (o == 0 || g_prm[P_COPY] > 3u) {
        sep_mbx_puts("FAIL: drawn source or copy outside the catalog\n");
        return 1;
    }
    for (uint32_t v = 0; v < 256u; v++) {
        pic_register_handler(v, ext_isr);
    }

    // Reset-vector corner: bark with SEP_NMI_VEC at its reset value.
    rec_mark(1, "reset_vector");
    uint32_t f0 = g_flag;
    bark_arm(g_prm[P_BARK + 0]);
    uint32_t left = nmivb_wait(&g_flag, f0, g_prm[P_WAIT]);
    hold();
    // The stub sits at the SEP_NMI_VEC reset value (checked in main), so one
    // stub run is one NMI at the reset vector.
    int pass_s = g_stub_runs == 1u && left != 0u;
    rec_chk("NMI-STUB", pass_s);
    rec_num("stub_runs", g_stub_runs);
    rec_hex("stub", (uint32_t)(uintptr_t)nmivb_stub);
    rec_num("timeout", left == 0u);
    rec_end();
    if (!pass_s) {
        g_err++;
    }

    // Lock the drawn trampoline copy.
    rec_mark(0, "lock");
    uint32_t vec = copy_addr(g_prm[P_COPY]);
    wr32(SEP_NMI_VEC_ADDR, vec);
    wr32(SEP_NMI_VEC_LOCK_ADDR, SEP_CPU_CTRL__SEP_NMI_VEC_LOCK__LOCK_bm);
    rec_ctl("VEC-SET");
    rec_num("boot", 1u);
    rec_hex("wrote", vec);
    rec_hex("vec", nmi_read_vector_reg());
    rec_hex("lock", nmi_read_lock_reg());
    rec_end();
    set_order(p);

    // Case (a): MIE 0, the source pending and enabled.
    rec_mark(1, "case_a");
    mstatus_mie(0);
    __asm__ volatile("csrs mie, %0" ::"r"(MIE_MEIE));
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), raw);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 1u);
    wr32(o->enable, rd32(o->enable) | o->bit);
    wr32(o->test, o->bit);
    for (uint32_t i = 0; i < g_prm[P_WAIT] && meip_bit(s) == 0u; i++) {
    }
    uint32_t before[N_MEIP];
    meip_snap(before);
    uint32_t e0 = g_ext_runs;
    int ok1 = bark_nmi(1u, g_prm[P_BARK + 1], 0u);
    int pre = ((before[s >> 5] >> (s & 31u)) & 1u) == 1u && g_ext_runs == e0 && g_mie_rd == 0u;
    mstatus_mie(1);
    uint32_t dlv = wait_ext(e0);
    int clr = 0;
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (meip_bit(s) == 0u) {
            clr = 1;
            break;
        }
    }
    nopic_line("a", before, ok1, dlv, dlv == 1u && g_ext_id == s, pre && clr);

    // Second bark, drawn case, MIE 1.
    uint32_t cs = g_prm[P_CASE];
    rec_mark(1, cs == CASE_B ? "case_b" : (cs == CASE_C ? "case_c" : "case_d"));
    int prep = 1;
    if (cs == CASE_B) {
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
        prep = (pic_rd32(SEP_TOP_PIC_MEIE_BASE_ADDR(s)) & EL2_PIC__MEIE__INTEN_bm) == 0u;
        wr32(o->test, o->bit);
    } else if (cs == CASE_C) {
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), never);
        prep = (pic_rd32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s)) & EL2_PIC__MEIPL__INTPRIORITY_bm) == never;
        wr32(o->test, o->bit);
    }
    if (cs != CASE_D) {
        for (uint32_t i = 0; i < g_prm[P_WAIT] && (rd32(o->state) & o->bit) == 0u; i++) {
        }
        prep = prep && (rd32(o->state) & o->bit) != 0u;
    }
    hold();
    e0 = g_ext_runs;
    meip_snap(before);
    int ok2 = bark_nmi(2u, g_prm[P_BARK + 2], 1u);
    pre = prep && g_ext_runs == e0 && g_mie_rd == 1u;
    if (cs == CASE_B) {
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 1u);
    } else if (cs == CASE_C) {
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), raw);
    }
    if (cs == CASE_D) {
        // No source is pending: the hold window is the no-delivery window, so
        // the case does not run the bounded delivery wait to its end.
        hold();
        dlv = g_ext_runs - e0;
    } else {
        dlv = wait_ext(e0);
    }
    if (cs == CASE_D) {
        nopic_line("d", before, ok2, 0xFFu, dlv == 0u, pre);
    } else {
        nopic_line(cs == CASE_B ? "b" : "c", before, ok2, dlv, dlv == 1u && g_ext_id == s, pre);
    }

    // Bark inside the external handler of s: one NMI, taken while the handler
    // waits (interrupts.adoc: no mstatus.MIE or PIC setting holds the NMI).
    rec_mark(0, "nest_setup");
    mstatus_mie(0);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), raw);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
    wr32(o->enable, rd32(o->enable) | o->bit);
    rec_mark(1, "nest");
    e0 = g_ext_runs;
    uint32_t n0 = g_nmi_runs;
    g_nest_nmi_runs = 0u;
    g_nmi_in_ext = 0u;
    g_nmi_entry = 0u;
    g_nest_timeout = 1u;
    g_nest_mode = 1u;
    wr32(o->test, o->bit);
    mstatus_mie(1);
    dlv = wait_ext(e0);
    mstatus_mie(0);
    uint32_t n_all = g_nmi_runs - n0;
    int pass_n = dlv == 1u && g_ext_id == s && g_nest_nmi_runs == 1u && g_nmi_in_ext == 1u &&
                 g_nest_timeout == 0u && n_all == 1u && g_nmi_entry == vec &&
                 g_nmi_copy == g_prm[P_COPY];
    rec_chk("NMI-IN-EXT", pass_n);
    rec_num("src", s);
    rec_num("ext_runs", dlv);
    rec_num("ext_id", g_ext_id);
    rec_num("nmi_in_handler", g_nest_nmi_runs);
    rec_num("nmi_total", n_all);
    rec_num("flag_at_entry", g_nmi_in_ext);
    rec_hex("entry", g_nmi_entry);
    rec_hex("vec", vec);
    rec_num("copy", g_nmi_copy);
    rec_num("timeout", g_nest_timeout);
    rec_end();
    if (!pass_n) {
        g_err++;
    }

    // Held bark: the NMI handler keeps the bark asserted for its hold window.
    rec_mark(1, "nmi_held");
    f0 = g_flag;
    g_held_entries = 0u;
    g_held_bark = 0u;
    g_held_mode = 1u;
    bark_arm(g_prm[P_HELD]);
    left = nmivb_wait(&g_flag, f0, g_prm[P_WAIT]);
    g_held_mode = 0u;
    if (left == 0u) {
        bark_clear();
    }
    rec_info("NMI-HELD");
    rec_num("entries", g_held_entries);
    rec_num("bark_in_handler", g_held_bark);
    rec_hex("mepc", g_held_epc);
    rec_hex("mcause", g_held_cause);
    rec_hex("nested_mepc", g_held_nested_epc);
    rec_hex("nested_mcause", g_held_nested_cause);
    rec_num("timeout", left == 0u);
    rec_end();

    rec_mark(0, "boot1_end");
    mstatus_mie(0);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), 0u);
    wr32(o->enable, rd32(o->enable) & ~o->bit);
    set_order(0u);
    sep_mbx_puts("BOOT1-END\n");
    return g_err;
}

static int boot2(void) {
    uint32_t a = g_prm[P_A];
    rec_mark(0, "program");
    wr32(SEP_NMI_VEC_ADDR, a);
    uint32_t vrd = nmi_read_vector_reg();
    wr32(SEP_NMI_VEC_LOCK_ADDR, SEP_CPU_CTRL__SEP_NMI_VEC_LOCK__LOCK_bm);
    rec_ctl("VEC-SET");
    rec_num("boot", 2u);
    rec_hex("wrote", a);
    rec_hex("vec", vrd);
    rec_hex("lock", nmi_read_lock_reg());
    rec_end();
    rec_mark(1, "programmed");
    uint32_t f0 = g_flag;
    bark_arm(g_prm[P_BARK + 3]);
    uint32_t left = nmivb_wait(&g_flag, f0, g_prm[P_WAIT]);
    // Hk at A never returns here: reaching this line is a failure.
    sep_mbx_puts("FAIL: the programmed bark did not reach A");
    rec_num("timeout", left == 0u);
    rec_num("stub_runs", g_stub_runs);
    rec_end();
    return 1;
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP NMI vector bark test\n");
    uint32_t leg = g_prm[P_LEG];
    if (g_prm[P_MAGIC] != PRM_MAGIC || (leg != 1u && leg != 2u)) {
        sep_mbx_puts("FAIL: parameter block not patched\n");
        return 1;
    }
    sep_mbx_puts("PARAMS");
    rec_hex("seed", g_prm[P_SEED]);
    rec_num("leg", leg);
    rec_num("copy", g_prm[P_COPY]);
    rec_hex("a", g_prm[P_A]);
    rec_num("case", g_prm[P_CASE]);
    rec_num("src", g_prm[P_SRC]);
    rec_num("raw", g_prm[P_RAW]);
    rec_num("priord", g_prm[P_PRIORD]);
    rec_end();
    sep_mbx_puts("LAYOUT");
    rec_hex("boot", (uint32_t)(uintptr_t)nmivb_boot);
    rec_hex("stub", (uint32_t)(uintptr_t)nmivb_stub);
    rec_hex("copy0", copy_addr(0));
    rec_hex("copy1", copy_addr(1));
    rec_hex("copy2", copy_addr(2));
    rec_hex("copy3", copy_addr(3));
    rec_hex("loop_lo", (uint32_t)(uintptr_t)nmivb_loop_lo);
    rec_hex("loop_hi", (uint32_t)(uintptr_t)nmivb_loop_hi);
    rec_end();
    rec_ctl("VEC-RESET");
    rec_num("boot", leg);
    rec_hex("vec", nmi_read_vector_reg());
    rec_hex("lock", nmi_read_lock_reg());
    rec_end();
    if ((uint32_t)(uintptr_t)nmivb_stub != STUB_ADDR) {
        sep_mbx_puts("FAIL: the stub is not at the SEP_NMI_VEC reset value\n");
        return 1;
    }
    return leg == 1u ? boot1() : boot2();
}
