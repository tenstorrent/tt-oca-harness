// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// PIC delivery gates, winner by effective priority, the never value, the order
// flip, and the idle timer and software interrupt paths, from firmware.
//
// The host (cocotb/tests/cpu/sep_pic_priority_gate_rand_test.py) draws the
// rounds (priord, source set, raw priorities, gate kinds, gate-open order,
// never source) and the sweep source from the run seed and patches them into
// g_prm. Each leg starts with an M line (sep_console_rec.h). The firmware
// prints one CHK line per check; the host grades CHK-WINNER and CHK-FLIP from
// the ORDER lines.
//
//   CHK-NONE-BEFORE-PROGRAM  no delivery with the reset meie and meipl
//   CHK-GATED                no delivery through a closed gate (meie 0, never
//                            priority, mstatus.MIE 0, mie.MEIE 0); opening it
//                            delivers once
//   CHK-STAY-PENDING         a waiting source keeps its meip bit while the
//                            winner handler runs
//   CHK-NEVER                the never value does not deliver; effective 1 does
//   CHK-MIE-LIVE             the mie write lands (control)
//   CHK-MIP-IDLE             mip.MTIP and mip.MSIP read 0
//   CHK-NO-TIMER-TRAP        no timer or software trap is taken
//   CHK-CONTROL              one PIC delivery enters the dispatcher with
//                            mcause.interrupt set, and one ecall enters
//                            trap_dispatch through mtvec and is counted
//                            (control)
//   CHK-THRESHOLD            a source at effective priority P == T (meipt)
//                            stays pending with no delivery; at P == T + 1 it
//                            delivers once
//   CHK-NEST                 in a handler that copies meicidpl into meicurpl
//                            and sets mstatus.MIE, a source at the same level
//                            stays pending with no entry; one level higher it
//                            nests once; meicidpl holds the level of the
//                            claimed source with no meicpct write (fast
//                            interrupt redirect, PRM sections 8.6.1, 8.12.9;
//                            hw/sys/sep/doc/interrupts.adoc:387 names the
//                            fast-interrupt path of this core)
//   CHK-TIMER-PIN            the timer_int pin drives mip.MTIP: with mie.MTIE 0
//                            it takes no trap; with mie.MTIE 1 and mstatus.MIE
//                            1 it takes one trap with mcause 0x8000_0007; the
//                            bit drops with the pin
//   CHK-INT-TIMER-HOLD       internal timer k pending (mip.MITIPk 1) with
//                            mie.MITIEk 0 takes no trap, with mie.MTIE and
//                            mie.MSIE both 0 or both 1; then mie.MITIEk 1
//                            takes one trap with the timer's mcause
//   CHK-INT-TIMER-TRAP       internal timer k armed from mitcnt 0 with bound B
//                            traps once with the timer's mcause, not before B
//                            core clocks; stopped with mitcnt B - 1 it takes
//                            no trap, stopped with mitcnt B it traps once
//
// Source drive recipe. A mailbox source k + 1 is driven by one CPU push into
// the inbound WRITE_DATA of mailbox k with IRQEN.wtirq 1, WIRQT 0 and an
// inbound filter allow window open over that port (all eight are opened at
// set-up and stay open), and released by a pop of the outbound READ_DATA of mailbox k and a write
// of 1 to inbound IRQS.wtirq. An OpenTitan event source is driven by its INTR_ENABLE bit and its
// INTR_TEST bit, and released by INTR_TEST 0 and a write of 1 to its INTR_STATE bit.
//
// Every external interrupt enters ext_dispatch through the fast-redirect
// vector table (every entry points to it); timer and software interrupts enter
// trap_dispatch through mtvec. Both count the trap class from mcause. The
// control leg takes one ecall through mtvec, so a trap on that path is shown to
// reach the counters that CHK-NO-TIMER-TRAP reads. The
// priority threshold CSRs (meipt, meicurpl) are set to the pass-all value of
// the current order, so only meie, meipl and mstatus.MIE gate delivery, except
// in the threshold and nesting legs, which run in standard order and change
// meipt and meicurpl only with mstatus.MIE 0.
//
// Internal timers. The interrupt chapter of the SEP spec
// (hw/sys/sep/doc/interrupts.adoc:294-299) states mip.MITIP0 bit 29 and
// mip.MITIP1 bit 28, the enables mie.MITIE0 and mie.MITIE1 at the same bits,
// the cause codes 0x1D and 0x1C with the interrupt bit, and that mie.MTIE and
// mie.MSIE do not enable them. The CSRs and their behaviour come from the
// VeeR EL2 Programmer's Reference Manual (cited at
// hw/sys/sep/doc/cpu.adoc:22-23), chapter 6: mitcnt0/mitb0/mitctl0 at
// 0x7D2-0x7D4 and mitcnt1/mitb1/mitctl1 at 0x7D5-0x7D7; the timer counts core
// clocks while mitctl.enable (bit 0) is 1 and signals its interrupt while
// mitcnt >= mitb; mitb resets to 0xFFFF_FFFF. A bound of 0 keeps the timer
// pending on every clock. trap_dispatch clears both mie.MITIE bits on an
// internal-timer entry, so each arming takes one trap.

#include <stdint.h>

#include "filter_ctrl.h"
#include "sep.h"
#include "sep_axil_mailbox.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"

#define PRM_MAGIC 0x320B6A7Eu
#define R_MAX 6u
#define S_MAX 5u

enum {
    P_MAGIC = 0,
    P_SEED,
    P_NROUND,
    P_SWEEP,
    P_HOLD,
    P_WAIT,
    P_IDLE, // 8 words: the excluded idle bits of meip
    P_ROUND = P_IDLE + 8,
};
// Per round: priord, n, never index, src[5], raw[5], gate[5], open order[5].
enum {
    R_PRIORD = 0,
    R_N,
    R_NEVER,
    R_SRC,
    R_RAW = R_SRC + S_MAX,
    R_GATE = R_RAW + S_MAX,
    R_ORDER = R_GATE + S_MAX,
    R_WORDS = R_ORDER + S_MAX
};
#define P_EXT (P_ROUND + R_MAX * R_WORDS)
// Threshold, nesting and internal-timer legs, after the rounds.
enum {
    P_THR_SRC = P_EXT,
    P_THR_MEIPT,    // meipt written (T)
    P_THR_PL_HELD,  // source level of the held step (T)
    P_THR_PL_OPEN,  // source level of the delivered step (T + 1)
    P_NEST_A,       // first source, level P_NEST_PL_A
    P_NEST_B,       // second source, raised inside the first handler
    P_NEST_PL_A,    // level of A; the handler copies meicidpl into meicurpl
    P_NEST_PL_SAME, // level of B while blocked (that of A)
    P_NEST_PL_HIGH, // level of B when it nests (one above)
    P_IT_FIRST,     // internal timer of the first timer legs (0 or 1)
    P_IT_MITB0,     // mitb written for the timer 0 trap leg
    P_IT_MITB1,     // mitb written for the timer 1 trap leg
    P_IT_BOUND0,    // core clocks that the timer 0 trap must not precede
    P_IT_BOUND1,    // core clocks that the timer 1 trap must not precede
    P_IT_HOLD_MITB, // mitb of the hold legs (0: pending on every clock)
    P_LEG_HOLD,     // loop iterations of the hold window of these legs
    P_EXT_END
};
#define P_WORDS P_EXT_END

volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC,
    [P_HOLD] = 1500u,
    [P_WAIT] = 20000u,
    [P_LEG_HOLD] = 16u,
};
// The threshold, nesting and internal-timer hold windows last at least this
// many core clocks (mcycle); a shorter window fails the check of the leg.
#define LEG_HOLD_MIN_CLK 32u

#define GATE_MEIE0 0u
#define GATE_NEVER 1u
// Highest meipl level; meipt and meicurpl take the same encoding.
#define PRI_MAX (EL2_PIC__MEIPL__INTPRIORITY_bm >> EL2_PIC__MEIPL__INTPRIORITY_bp)
#define MIE_MTIE (1u << 7)
#define MIE_MSIE (1u << 3)
#define MIP_MTIP (1u << 7)
#define MIP_MSIP (1u << 3)
#define MIP_MEIP (1u << 11)
#define MIE_WRITE (MIE_MEIE | MIE_MTIE | MIE_MSIE)
#define MCAUSE_IRQ 0x80000000u
#define MCAUSE_ECALL_M 11u // EL2 PRM table 13.3: environment call from M-mode
// EL2 PRM table 13.3 (named by hw/sys/sep/doc/cpu.adoc): machine timer interrupt.
#define MCAUSE_MTI (MCAUSE_IRQ | 7u)
#define LOG_MAX 64u
#define SRC_CTRL 1u

// meicidpl, the priority level of the claimed source (VeeR EL2 PRM section
// 8.12.9, cited at hw/sys/sep/doc/cpu.adoc:22-23).
#define CSR_MEICIDPL 0xBCB
// Internal timer CSRs (VeeR EL2 PRM chapter 6, cited at hw/sys/sep/doc/cpu.adoc:22-23).
#define CSR_MITCNT0 0x7D2
#define CSR_MITB0 0x7D3
#define CSR_MITCTL0 0x7D4
#define CSR_MITCNT1 0x7D5
#define CSR_MITB1 0x7D6
#define CSR_MITCTL1 0x7D7
#define MITCTL_ENABLE 1u       // mitctl.enable, bit 0
#define MITB_RESET 0xFFFFFFFFu // mitb reset value
// hw/sys/sep/doc/interrupts.adoc:294-298: pending and enable bits, cause codes.
#define MIP_MITIP0 (1u << 29)
#define MIP_MITIP1 (1u << 28)
#define MIE_MITIE0 (1u << 29)
#define MIE_MITIE1 (1u << 28)
#define MCAUSE_ITMR0 (MCAUSE_IRQ | 0x1Du)
#define MCAUSE_ITMR1 (MCAUSE_IRQ | 0x1Cu)
#define IT_CNT 0u
#define IT_B 1u
#define IT_CTL 2u

#define MBOX_OUT_RD0 SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR
#define MBOX_OUT_ST0 SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR

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

static volatile uint32_t g_runs[256];
static volatile uint32_t g_total;
static volatile uint32_t g_log[LOG_MAX];
static volatile uint32_t g_log_n;
static volatile uint32_t g_first_meip0;
static volatile uint32_t g_cls_ext, g_cls_timer, g_cls_sw, g_cls_other;
static volatile uint32_t g_last_mcause;
static int g_err;
// Internal-timer entries per timer, the mcause and mcycle of the latest one.
static volatile uint32_t g_it_n[2], g_it_mc[2], g_it_cyc[2];
// Nesting leg: first source, in-handler flag, and what its handler saw.
static volatile uint32_t g_nest_a, g_nest_in, g_nest_done;
static volatile uint32_t g_nest_cidpl, g_nest_blocked, g_nest_bmeip, g_nest_nested;
static volatile uint32_t g_nest_b_in_a, g_nest_b_raised, g_nest_hclk;

// ---- Inbound filter allow window over the inbound port of mailbox m ----
// The source drive recipe opens one read and write window per inbound mailbox
// port it uses, before the first push, and keeps it open for the leaf.
#define MBX_IN_SPAN 0x800u
#define FILT_CFG_RW_EN \
    (FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
     FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm)

static void mbx_window(uint32_t idx, uint32_t m) {
    volatile uint32_t *cfg =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(idx);
    volatile uint32_t *st =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(idx);
    volatile uint32_t *en =
        (volatile uint32_t *)SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(idx);
    uint32_t s =
        SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR + m * SEP_AXIL_MBOX_STRIDE;
    cfg[0] = 0u;
    cfg[1] = 0u;
    st[0] = s;
    st[1] = 0u;
    en[0] = s + MBX_IN_SPAN - 1u;
    en[1] = 0u;
    cfg[0] = FILT_CFG_RW_EN;
    __asm__ volatile("fence" ::: "memory");
    rec_info("MBX-WINDOW");
    rec_num("mbox", m);
    rec_hex("FILTER_CONFIG", cfg[0]);
    rec_hex("START_ADDR", st[0]);
    rec_hex("END_ADDR", en[0]);
    rec_end();
}

static inline uint32_t rd32(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr32(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
    __asm__ volatile("fence" ::: "memory");
}

static inline uint32_t rprm(uint32_t r, uint32_t k) {
    return g_prm[P_ROUND + r * R_WORDS + k];
}

static inline uint32_t mcycle(void) {
    uint32_t v;
    __asm__ volatile("csrr %0, mcycle" : "=r"(v));
    return v;
}

static inline void mstatus_mie(int on) {
    if (on) {
        __asm__ volatile("csrs mstatus, %0" ::"r"(MSTATUS_MIE));
    } else {
        __asm__ volatile("csrc mstatus, %0" ::"r"(MSTATUS_MIE));
    }
}

static inline uint32_t read_mip(void) {
    uint32_t v;
    __asm__ volatile("csrr %0, mip" : "=r"(v));
    return v;
}

static inline uint32_t never_val(uint32_t p) {
    return p ? PRI_MAX : 0u;
}

// priord with the threshold CSRs at the pass-all value of that order.
static void set_order(uint32_t p) {
    pic_write_priord(p);
    uint32_t t = p ? PRI_MAX : 0u;
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEIPT), "r"(t));
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEICURPL), "r"(t));
}

static const struct ot_src *ot_of(uint32_t s) {
    for (uint32_t i = 0; i < N_OT; i++) {
        if (k_ot[i].src == s) {
            return &k_ot[i];
        }
    }
    return 0;
}

static inline uint32_t mbox_in(uint32_t k, uint32_t reg0) {
    return reg0 + k * SEP_AXIL_MBOX_STRIDE;
}

static void mbox_setup_all(void) {
    for (uint32_t k = 0; k < SEP_AXIL_MBOX_N; k++) {
        wr32(mbox_in(k, SEP_AXIL_MBOX0_WIRQT), 0u);
        wr32(mbox_in(k, SEP_AXIL_MBOX0_IRQS), SEP_AXIL_MBOX_IRQ_ALL);
        wr32(mbox_in(k, SEP_AXIL_MBOX0_IRQEN), SEP_AXIL_MBOX_IRQ_WRITE);
    }
}

// Raise source s; returns its IP-side state read back (control, never a golden).
static uint32_t src_raise(uint32_t s) {
    if (s >= 1u && s <= 8u) {
        uint32_t k = s - 1u;
        wr32(mbox_in(k, SEP_AXIL_MBOX0_WRITE_DATA), 0x32000000u | s);
        return rd32(mbox_in(k, SEP_AXIL_MBOX0_IRQS)) & SEP_AXIL_MBOX_IRQ_WRITE ? 1u : 0u;
    }
    const struct ot_src *o = ot_of(s);
    if (o == 0) {
        return 0u;
    }
    wr32(o->enable, rd32(o->enable) | o->bit);
    wr32(o->test, o->bit);
    return (rd32(o->state) & o->bit) ? 1u : 0u;
}

static void src_release(uint32_t s) {
    if (s >= 1u && s <= 8u) {
        uint32_t k = s - 1u;
        // Pop only a held word: a source already released makes no read of an
        // empty FIFO.
        if ((rd32(MBOX_OUT_ST0 + k * SEP_AXIL_MBOX_STRIDE) & AXIL_MAILBOX__STATUS__EMPTY_bm) ==
            0u) {
            (void)rd32(MBOX_OUT_RD0 + k * SEP_AXIL_MBOX_STRIDE);
        }
        wr32(mbox_in(k, SEP_AXIL_MBOX0_IRQS), SEP_AXIL_MBOX_IRQ_WRITE);
        (void)rd32(mbox_in(k, SEP_AXIL_MBOX0_IRQS));
        return;
    }
    const struct ot_src *o = ot_of(s);
    if (o == 0) {
        return;
    }
    wr32(o->test, 0u);
    wr32(o->state, o->bit);
    (void)rd32(o->state);
}

static void classify(uint32_t mc) {
    g_last_mcause = mc;
    if ((mc & MCAUSE_IRQ) == 0u) {
        g_cls_other++;
        return;
    }
    switch (mc & 0x7FFFFFFFu) {
    case 11u:
        g_cls_ext++;
        break;
    case 7u:
        g_cls_timer++;
        break;
    case 3u:
        g_cls_sw++;
        break;
    default:
        g_cls_other++;
        break;
    }
}

// The per-source handler: read meip, log the source, release it by the recipe,
// and wait (bounded) for its meip bit to drop so mret does not re-enter.
static void src_handler(uint32_t id) {
    uint32_t meip0 = pic_read_meip(0);
    if (g_log_n == 0u) {
        g_first_meip0 = meip0;
    }
    if (g_log_n < LOG_MAX) {
        g_log[g_log_n] = id;
    }
    g_log_n++;
    g_runs[id]++;
    g_total++;
    if (ot_of(id) == 0 && !(id >= 1u && id <= 8u)) {
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(id), 0u); // a stray source
        return;
    }
    src_release(id);
    for (uint32_t i = 0; i < 2000u; i++) {
        if (((pic_read_meip(id >> 5) >> (id & 31u)) & 1u) == 0u) {
            break;
        }
    }
    rec_spin(8u);
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

static uint32_t hold(void);
static uint32_t leg_hold(void);
static int wait_runs(uint32_t s, uint32_t want);

static inline uint32_t meip_bit(uint32_t s) {
    return (pic_read_meip(s >> 5) >> (s & 31u)) & 1u;
}

// The handler of the first nesting source: release it, copy meicidpl into
// meicurpl, save mepc and mstatus, raise the second source at the same level
// with mstatus.MIE 1 (it must stay pending), then move it one level higher (it
// must nest once). mstatus.MIE goes back to 0 before meicurpl, mepc and
// mstatus are restored.
static void nest_body(uint32_t a) {
    uint32_t b = g_prm[P_NEST_B];
    uint32_t epc, mst, cur0, cid;
    g_nest_in = 1u;
    src_handler(a);
    __asm__ volatile("csrr %0, mepc" : "=r"(epc));
    __asm__ volatile("csrr %0, mstatus" : "=r"(mst));
    __asm__ volatile("csrr %0, %1" : "=r"(cur0) : "i"(CSR_MEICURPL));
    __asm__ volatile("csrr %0, %1" : "=r"(cid) : "i"(CSR_MEICIDPL));
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEICURPL), "r"(cid));
    g_nest_cidpl = cid;
    uint32_t b0 = g_runs[b];
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(b), g_prm[P_NEST_PL_SAME]);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(b), EL2_PIC__MEIE__INTEN_bm);
    g_nest_b_raised = src_raise(b);
    mstatus_mie(1);
    g_nest_hclk = leg_hold();
    g_nest_blocked = g_runs[b] - b0;
    g_nest_bmeip = meip_bit(b);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(b), g_prm[P_NEST_PL_HIGH]);
    (void)wait_runs(b, b0 + g_nest_blocked + 1u);
    (void)leg_hold();
    g_nest_nested = g_runs[b] - b0 - g_nest_blocked;
    mstatus_mie(0);
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEICURPL), "r"(cur0));
    __asm__ volatile("csrw mepc, %0" ::"r"(epc));
    __asm__ volatile("csrw mstatus, %0" ::"r"(mst));
    g_nest_in = 0u;
    g_nest_done = 1u;
}

void __attribute__((interrupt("machine"))) ext_dispatch(void) {
    uint32_t mc;
    __asm__ volatile("csrr %0, mcause" : "=r"(mc));
    classify(mc);
    uint32_t id = claim_id();
    if (g_nest_in != 0u && id == g_prm[P_NEST_B]) {
        g_nest_b_in_a++;
    }
    if (g_nest_a != 0u && id == g_nest_a && g_nest_in == 0u) {
        nest_body(id);
        return;
    }
    src_handler(id);
}

void __attribute__((interrupt("machine"), aligned(4))) trap_dispatch(void) {
    uint32_t mc, epc;
    uint32_t cyc = mcycle();
    __asm__ volatile("csrr %0, mcause" : "=r"(mc));
    classify(mc);
    if (mc == MCAUSE_ITMR0 || mc == MCAUSE_ITMR1) {
        // Internal timer: count it and clear both enables, so one arming
        // takes one trap.
        uint32_t k = (mc == MCAUSE_ITMR0) ? 0u : 1u;
        g_it_cyc[k] = cyc;
        g_it_mc[k] = mc;
        g_it_n[k]++;
        __asm__ volatile("csrc mie, %0" ::"r"(MIE_MITIE0 | MIE_MITIE1));
    } else if ((mc & MCAUSE_IRQ) == 0u) {
        __asm__ volatile("csrr %0, mepc" : "=r"(epc));
        epc += 4u;
        __asm__ volatile("csrw mepc, %0" ::"r"(epc));
    } else if ((mc & 0x7FFFFFFFu) == 7u || (mc & 0x7FFFFFFFu) == 3u) {
        // A timer or software trap cannot be released from here: mask it.
        __asm__ volatile("csrc mie, %0" ::"r"(MIE_MTIE | MIE_MSIE));
    }
}

static uint32_t hold(void) {
    uint32_t t0 = mcycle();
    for (volatile uint32_t i = 0; i < g_prm[P_HOLD]; i++) {
    }
    return mcycle() - t0;
}

// The hold window of the threshold, nesting and internal-timer legs: the
// check of the leg needs the returned core clocks to be LEG_HOLD_MIN_CLK or
// more.
static uint32_t leg_hold(void) {
    uint32_t t0 = mcycle();
    for (volatile uint32_t i = 0; i < g_prm[P_LEG_HOLD]; i++) {
    }
    return mcycle() - t0;
}

static int wait_runs(uint32_t s, uint32_t want) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (g_runs[s] >= want) {
            return 1;
        }
    }
    return 0;
}

static int wait_total(uint32_t want) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (g_total >= want) {
            return 1;
        }
    }
    return 0;
}

static void clear_log(void) {
    g_log_n = 0u;
    g_first_meip0 = 0u;
}

static void zero_set(uint32_t r) {
    for (uint32_t i = 0; i < rprm(r, R_N); i++) {
        uint32_t s = rprm(r, R_SRC + i);
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), 0u);
    }
}

// Inside a round: meie 0 for every source of the set and no meipl write, so
// the graded round window holds only the meipl writes that its checks grade.
static void disable_set(uint32_t r) {
    for (uint32_t i = 0; i < rprm(r, R_N); i++) {
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(rprm(r, R_SRC + i)), 0u);
    }
}

static void put_ids(const char *key, uint32_t from, uint32_t n) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    for (uint32_t i = 0; i < n && from + i < LOG_MAX; i++) {
        if (i) {
            sep_mbx_putc(',');
        }
        rec_dec(g_log[from + i]);
    }
    if (n == 0u) {
        sep_mbx_puts("none");
    }
}

static void put_list(const char *key, uint32_t r, uint32_t base) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    for (uint32_t i = 0; i < rprm(r, R_N); i++) {
        if (i) {
            sep_mbx_putc(',');
        }
        rec_dec(rprm(r, base + i));
    }
}

static void chk_end(int pass) {
    rec_end();
    if (!pass) {
        g_err++;
    }
}

static void meip_obs(uint32_t s) {
    rec_obs("NEVER-MEIP");
    rec_num("src", s);
    rec_num("meip_bit", (pic_read_meip(s >> 5) >> (s & 31u)) & 1u);
    rec_end();
}

static void run_round(uint32_t r) {
    uint32_t p = rprm(r, R_PRIORD);
    uint32_t n = rprm(r, R_N);
    uint32_t setmask = 0;
    for (uint32_t i = 0; i < n; i++) {
        setmask |= 1u << rprm(r, R_SRC + i);
    }
    sep_mbx_puts("ROUND");
    rec_num("r", r);
    rec_num("priord", p);
    put_list("srcs", r, R_SRC);
    put_list("raws", r, R_RAW);
    put_list("gates", r, R_GATE);
    rec_num("never_src", rprm(r, R_SRC + rprm(r, R_NEVER)));
    rec_end();

    // Gate corner: each source behind its drawn closed gate, all asserted.
    for (uint32_t i = 0; i < n; i++) {
        uint32_t s = rprm(r, R_SRC + i);
        if (rprm(r, R_GATE + i) == GATE_MEIE0) {
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), rprm(r, R_RAW + i));
            pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
        } else {
            pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), never_val(p));
        }
    }
    uint32_t t0 = g_total;
    uint32_t raised = 0;
    for (uint32_t i = 0; i < n; i++) {
        raised += src_raise(rprm(r, R_SRC + i));
    }
    (void)hold();
    uint32_t gated_runs = g_total - t0;
    for (uint32_t i = 0; i < n; i++) {
        meip_obs(rprm(r, R_SRC + i));
    }
    for (uint32_t j = 0; j < n; j++) {
        uint32_t i = rprm(r, R_ORDER + j);
        uint32_t s = rprm(r, R_SRC + i);
        uint32_t g = rprm(r, R_GATE + i);
        uint32_t before = g_total;
        uint32_t own0 = g_runs[s];
        if (g == GATE_MEIE0) {
            pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
        } else {
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), rprm(r, R_RAW + i));
        }
        (void)wait_runs(s, own0 + 1u);
        (void)hold();
        uint32_t own = g_runs[s] - own0;
        uint32_t other = (g_total - before) - own;
        int pass = gated_runs == 0u && raised == n && own == 1u && other == 0u;
        rec_chk("GATED", pass);
        rec_num("src", s);
        rec_str("gate", g == GATE_MEIE0 ? "meie0" : "never");
        rec_num("handler_runs", gated_runs);
        rec_num("then_open_runs", own);
        rec_num("other_runs", other);
        rec_num("raised", raised);
        chk_end(pass);
    }

    // mstatus.MIE gate.
    clear_log();
    mstatus_mie(0);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t s = rprm(r, R_SRC + i);
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), rprm(r, R_RAW + i));
    }
    uint32_t meip_before = pic_read_meip(0) & setmask;
    t0 = g_total;
    raised = 0;
    for (uint32_t i = 0; i < n; i++) {
        raised += src_raise(rprm(r, R_SRC + i));
    }
    uint32_t hclk = hold();
    uint32_t mie0_runs = g_total - t0;

    // Winner corner: one MIE write; the handlers run to completion.
    clear_log();
    t0 = g_total;
    mstatus_mie(1);
    int done = wait_total(t0 + n);
    (void)hold();
    uint32_t open_runs = g_total - t0;
    uint32_t first = g_log[0];
    sep_mbx_puts("ORDER");
    rec_str("corner", "winner");
    rec_num("r", r);
    rec_num("priord", p);
    rec_num("n", g_log_n);
    put_ids("ids", 0u, g_log_n);
    rec_end();
    int pass = mie0_runs == 0u && raised == n && open_runs == n && done;
    rec_chk("GATED", pass);
    put_list("srcs", r, R_SRC);
    rec_str("gate", "mie0");
    rec_num("handler_runs", mie0_runs);
    rec_num("then_open_runs", open_runs);
    rec_num("hold_clk", hclk);
    chk_end(pass);
    uint32_t waiting = setmask & ~(1u << first);
    uint32_t during = g_first_meip0 & setmask;
    pass = meip_before == 0u && (during & waiting) == waiting && g_log_n >= 1u;
    rec_chk("STAY-PENDING", pass);
    rec_num("winner", first);
    rec_hex("waiting", waiting);
    rec_hex("meip_bits_before_assert", meip_before);
    rec_hex("meip_bits_during_handler", during);
    chk_end(pass);

    // Never corner.
    disable_set(r);
    uint32_t ni = rprm(r, R_NEVER);
    uint32_t sn = rprm(r, R_SRC + ni);
    uint32_t own0 = g_runs[sn];
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(sn), EL2_PIC__MEIE__INTEN_bm);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sn), never_val(p));
    raised = src_raise(sn);
    (void)hold();
    uint32_t nruns = g_runs[sn] - own0;
    meip_obs(sn);
    uint32_t eff1 = p ? PRI_MAX - 1u : 1u; // one level past the never value
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sn), eff1);
    (void)wait_runs(sn, own0 + nruns + 1u);
    (void)hold();
    uint32_t twin = g_runs[sn] - own0 - nruns;
    pass = raised == 1u && nruns == 0u && twin == 1u;
    rec_chk("NEVER", pass);
    rec_num("src", sn);
    rec_num("raw", never_val(p));
    rec_num("priord", p);
    rec_num("runs", nruns);
    rec_num("twin_runs", twin);
    rec_num("twin_raw", eff1);
    chk_end(pass);

    // Flip corner: opposite order, mirrored priorities.
    disable_set(r);
    mstatus_mie(0);
    set_order(p ^ 1u);
    for (uint32_t i = 0; i < n; i++) {
        uint32_t s = rprm(r, R_SRC + i);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), PRI_MAX - rprm(r, R_RAW + i));
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
    }
    clear_log();
    t0 = g_total;
    for (uint32_t i = 0; i < n; i++) {
        (void)src_raise(rprm(r, R_SRC + i));
    }
    (void)hold();
    mstatus_mie(1);
    (void)wait_total(t0 + n);
    (void)hold();
    sep_mbx_puts("ORDER");
    rec_str("corner", "flip");
    rec_num("r", r);
    rec_num("priord_from", p);
    rec_num("priord_to", p ^ 1u);
    rec_num("n", g_log_n);
    put_ids("ids", 0u, g_log_n);
    rec_end();
}

static int wait_flag(volatile uint32_t *f) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (*f != 0u) {
            return 1;
        }
    }
    return 0;
}

// Threshold leg (standard order): meipt = T, the source at level T is pending
// with mstatus.MIE 1 and must not deliver; at level T + 1 it delivers once.
static void leg_threshold(void) {
    uint32_t s = g_prm[P_THR_SRC];
    uint32_t t = g_prm[P_THR_MEIPT];
    mstatus_mie(0);
    set_order(0u);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), g_prm[P_THR_PL_HELD]);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
    __asm__ volatile("csrw %0, %1" ::"i"(CSR_MEIPT), "r"(t));
    uint32_t t_rd;
    __asm__ volatile("csrr %0, %1" : "=r"(t_rd) : "i"(CSR_MEIPT));
    rec_mark(1, "threshold");
    uint32_t own0 = g_runs[s], t0 = g_total;
    uint32_t raised = src_raise(s);
    mstatus_mie(1);
    uint32_t hclk = leg_hold();
    uint32_t held = g_total - t0;
    uint32_t pend = meip_bit(s);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), g_prm[P_THR_PL_OPEN]);
    (void)wait_runs(s, own0 + held + 1u);
    (void)leg_hold();
    mstatus_mie(0);
    uint32_t open = g_runs[s] - own0 - held;
    uint32_t other = (g_total - t0) - (g_runs[s] - own0);
    rec_mark(0, "threshold_restore");
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), 0u);
    set_order(0u);
    int pass = raised == 1u && held == 0u && pend == 1u && hclk >= LEG_HOLD_MIN_CLK && open == 1u &&
               other == 0u;
    rec_chk("THRESHOLD", pass);
    rec_num("src", s);
    rec_num("meipt", t);
    rec_num("pl_held", g_prm[P_THR_PL_HELD]);
    rec_num("pl_open", g_prm[P_THR_PL_OPEN]);
    rec_num("raised", raised);
    rec_num("held_runs", held);
    rec_num("held_meip", pend);
    rec_num("hold_clk", hclk);
    rec_num("open_runs", open);
    rec_num("other_runs", other);
    rec_num("meipt_rd", t_rd);
    chk_end(pass);
}

// Nesting leg (standard order, meipt 0): source A at level L; its handler
// runs nest_body.
static void leg_nest(void) {
    uint32_t a = g_prm[P_NEST_A], b = g_prm[P_NEST_B];
    mstatus_mie(0);
    set_order(0u);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(a), 0u);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(b), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(b), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(a), g_prm[P_NEST_PL_A]);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(a), EL2_PIC__MEIE__INTEN_bm);
    g_nest_done = 0u;
    g_nest_b_in_a = 0u;
    g_nest_blocked = 0u;
    g_nest_nested = 0u;
    g_nest_bmeip = 0u;
    g_nest_b_raised = 0u;
    g_nest_cidpl = 0u;
    g_nest_hclk = 0u;
    uint32_t a0 = g_runs[a], b0 = g_runs[b], t0 = g_total;
    g_nest_a = a;
    rec_mark(1, "nest");
    uint32_t raised = src_raise(a);
    mstatus_mie(1);
    int done = wait_flag(&g_nest_done);
    (void)leg_hold();
    mstatus_mie(0);
    g_nest_a = 0u;
    uint32_t aruns = g_runs[a] - a0, bruns = g_runs[b] - b0;
    uint32_t other = (g_total - t0) - aruns - bruns;
    uint32_t cur_rd;
    __asm__ volatile("csrr %0, %1" : "=r"(cur_rd) : "i"(CSR_MEICURPL));
    rec_mark(0, "nest_restore");
    for (uint32_t i = 0; i < 2u; i++) {
        uint32_t s = i ? b : a;
        pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
        pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), 0u);
    }
    set_order(0u);
    int pass = done && raised == 1u && aruns == 1u && g_nest_cidpl == g_prm[P_NEST_PL_A] &&
               g_nest_b_raised == 1u && g_nest_blocked == 0u && g_nest_bmeip == 1u &&
               g_nest_hclk >= LEG_HOLD_MIN_CLK && g_nest_nested == 1u && g_nest_b_in_a == 1u &&
               other == 0u;
    rec_chk("NEST", pass);
    rec_num("a", a);
    rec_num("b", b);
    rec_num("pl_a", g_prm[P_NEST_PL_A]);
    rec_num("pl_same", g_prm[P_NEST_PL_SAME]);
    rec_num("pl_high", g_prm[P_NEST_PL_HIGH]);
    rec_num("done", (uint32_t)done);
    rec_num("a_runs", aruns);
    rec_num("meicidpl", g_nest_cidpl);
    rec_num("b_raised", g_nest_b_raised);
    rec_num("blocked_runs", g_nest_blocked);
    rec_num("blocked_meip", g_nest_bmeip);
    rec_num("hold_clk", g_nest_hclk);
    rec_num("nested_runs", g_nest_nested);
    rec_num("b_in_a", g_nest_b_in_a);
    rec_num("other_runs", other);
    rec_num("meicurpl_after", cur_rd);
    chk_end(pass);
}

static void it_csrw(uint32_t k, uint32_t reg, uint32_t v) {
    if (k == 0u) {
        if (reg == IT_CNT) {
            __asm__ volatile("csrw %0, %1" ::"i"(CSR_MITCNT0), "r"(v));
        } else if (reg == IT_B) {
            __asm__ volatile("csrw %0, %1" ::"i"(CSR_MITB0), "r"(v));
        } else {
            __asm__ volatile("csrw %0, %1" ::"i"(CSR_MITCTL0), "r"(v));
        }
    } else {
        if (reg == IT_CNT) {
            __asm__ volatile("csrw %0, %1" ::"i"(CSR_MITCNT1), "r"(v));
        } else if (reg == IT_B) {
            __asm__ volatile("csrw %0, %1" ::"i"(CSR_MITB1), "r"(v));
        } else {
            __asm__ volatile("csrw %0, %1" ::"i"(CSR_MITCTL1), "r"(v));
        }
    }
}

static uint32_t it_cnt(uint32_t k) {
    uint32_t v;
    if (k == 0u) {
        __asm__ volatile("csrr %0, %1" : "=r"(v) : "i"(CSR_MITCNT0));
    } else {
        __asm__ volatile("csrr %0, %1" : "=r"(v) : "i"(CSR_MITCNT1));
    }
    return v;
}

static inline uint32_t it_mitie(uint32_t k) {
    return k ? MIE_MITIE1 : MIE_MITIE0;
}

static inline uint32_t it_mcause(uint32_t k) {
    return k ? MCAUSE_ITMR1 : MCAUSE_ITMR0;
}

static int wait_it(uint32_t k, uint32_t want) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (g_it_n[k] >= want) {
            return 1;
        }
    }
    return 0;
}

// Hold leg: timer k pending (bound P_IT_HOLD_MITB) with mie.MITIEk 0 and
// mstatus.MIE 1; mie.MTIE and mie.MSIE both 1 (mtsi 1) or both 0. No
// internal-timer trap may be taken. Then mie.MITIEk 1 takes one trap.
static void leg_it_hold(uint32_t k, uint32_t mtsi) {
    uint32_t mie_v = MIE_MEIE | (mtsi ? (MIE_MTIE | MIE_MSIE) : 0u);
    mstatus_mie(0);
    __asm__ volatile("csrw mie, %0" ::"r"(mie_v));
    it_csrw(k, IT_CTL, MITCTL_ENABLE);
    it_csrw(k, IT_B, g_prm[P_IT_HOLD_MITB]);
    uint32_t n0 = g_it_n[0] + g_it_n[1];
    uint32_t k0 = g_it_n[k];
    rec_mark(1, "itimer_hold");
    mstatus_mie(1);
    uint32_t hclk = leg_hold();
    uint32_t mip = read_mip();
    uint32_t mie_rd;
    __asm__ volatile("csrr %0, mie" : "=r"(mie_rd));
    uint32_t held = g_it_n[0] + g_it_n[1] - n0;
    __asm__ volatile("csrs mie, %0" ::"r"(it_mitie(k)));
    (void)wait_it(k, k0 + held + 1u);
    (void)leg_hold();
    mstatus_mie(0);
    uint32_t twin = g_it_n[k] - k0 - held;
    uint32_t twin_mc = g_it_mc[k];
    rec_mark(0, "itimer_restore");
    it_csrw(k, IT_B, MITB_RESET);
    __asm__ volatile("csrw mie, %0" ::"r"(MIE_WRITE));
    uint32_t pend = (mip & (k ? MIP_MITIP1 : MIP_MITIP0)) ? 1u : 0u;
    uint32_t mt_ms = mie_rd & (MIE_MTIE | MIE_MSIE);
    int pass = held == 0u && pend == 1u && hclk >= LEG_HOLD_MIN_CLK &&
               (mie_rd & (MIE_MITIE0 | MIE_MITIE1)) == 0u &&
               mt_ms == (mtsi ? (MIE_MTIE | MIE_MSIE) : 0u) && twin == 1u &&
               twin_mc == it_mcause(k);
    rec_chk("INT-TIMER-HOLD", pass);
    rec_num("timer", k);
    rec_num("mtie_msie", mtsi);
    rec_hex("mitb", g_prm[P_IT_HOLD_MITB]);
    rec_hex("mie", mie_rd);
    rec_num("mip_mitip", pend);
    rec_num("held_traps", held);
    rec_num("hold_clk", hclk);
    rec_num("twin_traps", twin);
    rec_hex("twin_mcause", twin_mc);
    chk_end(pass);
}

// Trap leg: timer k stopped, mitcnt 0, mitb written, mie.MITIEk 1 and
// mstatus.MIE 1, then enabled. One trap with the timer's mcause, taken at
// least P_IT_BOUNDk core clocks after the enable. Then the bound itself with
// the timer stopped, so mitcnt holds the written value: mitcnt written to
// P_IT_BOUNDk - 1 takes no trap for a hold window, reads back the written
// value and leaves mip.MITIPk 0; mitcnt written to P_IT_BOUNDk takes one trap
// with the timer's mcause.
static void leg_it_trap(uint32_t k) {
    mstatus_mie(0);
    __asm__ volatile("csrw mie, %0" ::"r"(MIE_MEIE | it_mitie(k)));
    it_csrw(k, IT_CTL, 0u);
    it_csrw(k, IT_CNT, 0u);
    it_csrw(k, IT_B, g_prm[P_IT_MITB0 + k]);
    uint32_t cnt0 = it_cnt(k);
    uint32_t k0 = g_it_n[k], o0 = g_it_n[k ^ 1u];
    rec_mark(1, "itimer_trap");
    mstatus_mie(1);
    uint32_t t_arm = mcycle();
    it_csrw(k, IT_CTL, MITCTL_ENABLE);
    int fired = wait_it(k, k0 + 1u);
    (void)leg_hold();
    mstatus_mie(0);
    uint32_t n = g_it_n[k] - k0;
    uint32_t mc = g_it_mc[k];
    uint32_t delta = g_it_cyc[k] - t_arm;
    uint32_t bound = g_prm[P_IT_BOUND0 + k];
    // Bound step: timer k stopped, mitcnt one below the bound.
    it_csrw(k, IT_CTL, 0u);
    uint32_t below = bound - 1u;
    it_csrw(k, IT_CNT, below);
    __asm__ volatile("csrs mie, %0" ::"r"(it_mitie(k)));
    uint32_t kb = g_it_n[k];
    mstatus_mie(1);
    uint32_t bclk = leg_hold();
    uint32_t mip_b = read_mip();
    uint32_t cnt_b = it_cnt(k);
    uint32_t n_below = g_it_n[k] - kb;
    it_csrw(k, IT_CNT, bound);
    int fired_at = wait_it(k, kb + n_below + 1u);
    (void)leg_hold();
    mstatus_mie(0);
    uint32_t n_at = g_it_n[k] - kb - n_below;
    uint32_t mc_at = g_it_mc[k];
    uint32_t other = g_it_n[k ^ 1u] - o0;
    uint32_t pend_b = (mip_b & (k ? MIP_MITIP1 : MIP_MITIP0)) ? 1u : 0u;
    rec_mark(0, "itimer_restore");
    it_csrw(k, IT_B, MITB_RESET);
    __asm__ volatile("csrw mie, %0" ::"r"(MIE_WRITE));
    int pass = cnt0 == 0u && fired && n == 1u && other == 0u && mc == it_mcause(k) &&
               delta >= bound && n_below == 0u && cnt_b == below && pend_b == 0u &&
               bclk >= LEG_HOLD_MIN_CLK && fired_at && n_at == 1u && mc_at == it_mcause(k);
    rec_chk("INT-TIMER-TRAP", pass);
    rec_num("timer", k);
    rec_num("mitb", g_prm[P_IT_MITB0 + k]);
    rec_num("bound", bound);
    rec_num("mitcnt_armed", cnt0);
    rec_num("traps", n);
    rec_num("other_timer_traps", other);
    rec_hex("mcause", mc);
    rec_num("trap_clk", delta);
    rec_num("below_mitcnt", below);
    rec_num("below_mitcnt_rd", cnt_b);
    rec_num("below_traps", n_below);
    rec_num("below_mip_mitip", pend_b);
    rec_num("below_hold_clk", bclk);
    rec_num("at_bound_traps", n_at);
    rec_hex("at_bound_mcause", mc_at);
    chk_end(pass);
}

static void req_tint(uint32_t on) {
    rec_req("tint");
    rec_num("on", on);
    rec_end();
}

static int wait_mtip(uint32_t want) {
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (((read_mip() & MIP_MTIP) != 0u) == (want != 0u)) {
            return 1;
        }
    }
    return 0;
}

// mie.MEIE gate (EL2 PRM section 8.6.1, named by hw/sys/sep/doc/cpu.adoc: an
// external interrupt is taken once one is pending and the meie bit of mie and
// the mie bit of mstatus are set): the source pending at an open PIC gate with
// mstatus.MIE 1 and mie.MEIE 0 does not deliver; mie.MEIE 1 delivers it once.
static void leg_mie_meie(void) {
    uint32_t s = SRC_CTRL;
    mstatus_mie(0);
    set_order(0u);
    __asm__ volatile("csrc mie, %0" ::"r"(MIE_MEIE));
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), 1u);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), EL2_PIC__MEIE__INTEN_bm);
    uint32_t own0 = g_runs[s], t0 = g_total;
    uint32_t raised = src_raise(s);
    mstatus_mie(1);
    uint32_t hclk = hold();
    uint32_t gated = g_total - t0;
    uint32_t pend = meip_bit(s);
    __asm__ volatile("csrs mie, %0" ::"r"(MIE_MEIE));
    (void)wait_runs(s, own0 + 1u);
    (void)hold();
    mstatus_mie(0);
    uint32_t own = g_runs[s] - own0;
    uint32_t other = (g_total - t0) - own;
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(s), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(s), 0u);
    int pass = raised == 1u && gated == 0u && pend == 1u && own == 1u && other == 0u;
    rec_chk("GATED", pass);
    rec_num("src", s);
    rec_str("gate", "mie_meie");
    rec_num("handler_runs", gated);
    rec_num("then_open_runs", own);
    rec_num("other_runs", other);
    rec_num("raised", raised);
    rec_num("pending_meip", pend);
    rec_num("hold_clk", hclk);
    chk_end(pass);
}

// Timer pin (hw/sys/sep/doc/interrupts.adoc:291: the timer_int pin drives
// mip.MTIP; EL2 PRM tables 13.1 and 13.2: mie.mtie enables and mip.mtip
// reports the machine timer interrupt; table 13.3: mcause 0x8000_0007). The
// host drives timer_int_i on each REQ tint line.
static void leg_timer_pin(void) {
    mstatus_mie(0);
    __asm__ volatile("csrc mie, %0" ::"r"(MIE_MTIE | MIE_MSIE));
    uint32_t tt0 = g_cls_timer;
    req_tint(1u);
    int up = wait_mtip(1u);
    uint32_t mip_on = (read_mip() >> 7) & 1u;
    mstatus_mie(1);
    uint32_t hclk = hold();
    uint32_t held = g_cls_timer - tt0;
    g_last_mcause = 0u;
    __asm__ volatile("csrs mie, %0" ::"r"(MIE_MTIE));
    for (uint32_t i = 0; i < g_prm[P_WAIT] && g_cls_timer - tt0 == held; i++) {
    }
    (void)hold();
    mstatus_mie(0);
    uint32_t taken = g_cls_timer - tt0 - held;
    uint32_t mc = g_last_mcause;
    req_tint(0u);
    int down = wait_mtip(0u);
    uint32_t mip_off = (read_mip() >> 7) & 1u;
    __asm__ volatile("csrw mie, %0" ::"r"(MIE_WRITE));
    int pass = up && mip_on == 1u && held == 0u && taken == 1u && mc == MCAUSE_MTI && down &&
               mip_off == 0u;
    rec_chk("TIMER-PIN", pass);
    rec_num("mip_mtip_on", mip_on);
    rec_num("mtie0_traps", held);
    rec_num("hold_clk", hclk);
    rec_num("mtie1_traps", taken);
    rec_hex("mcause", mc);
    rec_num("mip_mtip_off", mip_off);
    chk_end(pass);
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP PIC priority gate test\n");
    uint32_t nr = g_prm[P_NROUND];
    if (g_prm[P_MAGIC] != PRM_MAGIC || nr == 0u || nr > R_MAX) {
        sep_mbx_puts("FAIL: parameter block not patched\n");
        return 1;
    }
    sep_mbx_puts("PARAMS");
    rec_hex("seed", g_prm[P_SEED]);
    rec_num("rounds", nr);
    rec_num("sweep", g_prm[P_SWEEP]);
    rec_num("hold", g_prm[P_HOLD]);
    rec_end();

    __asm__ volatile("csrw mtvec, %0" ::"r"((uint32_t)(uintptr_t)&trap_dispatch));
    for (uint32_t v = 0; v < 256u; v++) {
        pic_register_handler(v, ext_dispatch);
    }
    for (uint32_t k = 0; k < SEP_AXIL_MBOX_N; k++) {
        mbx_window(k, k);
    }
    mbox_setup_all();
    set_order(0u);

    rec_mark(0, "setup");
    __asm__ volatile("csrw mie, %0" ::"r"(MIE_WRITE));
    uint32_t mie_rd;
    __asm__ volatile("csrr %0, mie" : "=r"(mie_rd));
    int pass = mie_rd == MIE_WRITE;
    rec_chk("MIE-LIVE", pass);
    rec_hex("wrote", MIE_WRITE);
    rec_hex("read", mie_rd);
    chk_end(pass);
    uint32_t mip = read_mip();
    pass = (mip & (MIP_MTIP | MIP_MSIP)) == 0u;
    rec_chk("MIP-IDLE", pass);
    rec_str("when", "reset");
    rec_num("mip_mtip", (mip >> 7) & 1u);
    rec_num("mip_msip", (mip >> 3) & 1u);
    chk_end(pass);
    mstatus_mie(1);

    // Reset-state window: round 1 sources asserted with reset meie and meipl.
    rec_mark(1, "reset_window");
    uint32_t n0 = g_prm[P_ROUND + R_N];
    uint32_t t0 = g_total;
    uint32_t raised = 0;
    for (uint32_t i = 0; i < n0; i++) {
        raised += src_raise(rprm(0, R_SRC + i));
    }
    uint32_t hclk = hold();
    uint32_t runs = g_total - t0;
    for (uint32_t i = 0; i < n0; i++) {
        src_release(rprm(0, R_SRC + i));
    }
    pass = runs == 0u && raised == n0;
    rec_chk("NONE-BEFORE-PROGRAM", pass);
    rec_num("srcs", n0);
    rec_num("handler_runs", runs);
    rec_num("hold_clk", hclk);
    rec_num("raised", raised);
    chk_end(pass);

    // Encoding sweep: meipl.intpriority is RW, so each value reads back as
    // written in either priority order (window closed, no source pending).
    rec_mark(0, "sweep");
    uint32_t sw = g_prm[P_SWEEP];
    for (uint32_t p = 0; p < 2u; p++) {
        set_order(p);
        for (uint32_t v = 0; v < 16u; v++) {
            pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sw), v);
            uint32_t rb =
                pic_rd32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sw)) & EL2_PIC__MEIPL__INTPRIORITY_bm;
            pass = rb == v;
            rec_chk("LEVEL-SWEEP", pass);
            rec_num("src", sw);
            rec_num("priord", p);
            rec_num("wrote", v);
            rec_num("read", rb);
            chk_end(pass);
        }
    }
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(sw), 0u);
    set_order(0u);

    for (uint32_t r = 0; r < nr; r++) {
        zero_set(r);
        set_order(rprm(r, R_PRIORD));
        rec_mark(1, "round");
        run_round(r);
        rec_mark(0, "round_end");
        zero_set(r);
        set_order(0u);
    }

    // Idle window: no PIC source enabled, MIE, MTIE and MSIE set. MIE goes to 0
    // before the marker and to 1 inside the window, so the hold window of the
    // idle leg starts inside the graded window.
    mstatus_mie(0);
    rec_mark(1, "idle");
    mstatus_mie(1);
    uint32_t tt0 = g_cls_timer, ts0 = g_cls_sw;
    hclk = hold();
    uint32_t idle_t = g_cls_timer - tt0, idle_s = g_cls_sw - ts0;
    uint32_t mst;
    __asm__ volatile("csrr %0, mstatus" : "=r"(mst));
    mip = read_mip();
    pass = (mip & (MIP_MTIP | MIP_MSIP)) == 0u && (mst & MSTATUS_MIE) != 0u;
    rec_chk("MIP-IDLE", pass);
    rec_str("when", "hold");
    rec_num("mstatus_mie", (mst >> 3) & 1u);
    rec_num("mip_mtip", (mip >> 7) & 1u);
    rec_num("mip_msip", (mip >> 3) & 1u);
    chk_end(pass);

    // Control: one PIC delivery through the dispatcher.
    rec_mark(0, "control");
    mstatus_mie(0);
    uint32_t tot_t = g_cls_timer, tot_s = g_cls_sw, tot_o = g_cls_other;
    g_cls_ext = 0u;
    g_cls_timer = 0u;
    g_cls_sw = 0u;
    uint32_t c0 = g_runs[SRC_CTRL];
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(SRC_CTRL), EL2_PIC__MEIE__INTEN_bm);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(SRC_CTRL), 1u);
    (void)src_raise(SRC_CTRL);
    for (uint32_t i = 0; i < g_prm[P_WAIT]; i++) {
        if (read_mip() & MIP_MEIP) {
            break;
        }
    }
    mip = read_mip();
    pass = (mip & (MIP_MTIP | MIP_MSIP)) == 0u && (mip & MIP_MEIP) != 0u;
    rec_chk("MIP-IDLE", pass);
    rec_str("when", "after_control");
    rec_num("mip_mtip", (mip >> 7) & 1u);
    rec_num("mip_msip", (mip >> 3) & 1u);
    rec_num("ctrl_mip_meip", (mip >> 11) & 1u);
    chk_end(pass);
    mstatus_mie(1);
    (void)wait_runs(SRC_CTRL, c0 + 1u);
    (void)hold();
    uint32_t cruns = g_runs[SRC_CTRL] - c0;
    uint32_t mc = g_last_mcause;
    // Trap-path control: mtvec holds trap_dispatch, and one ecall enters it
    // through mtvec, the entry of a timer or software trap, and is counted as
    // a synchronous trap (mcause 11, environment call from M-mode).
    uint32_t mtvec_rd;
    __asm__ volatile("csrr %0, mtvec" : "=r"(mtvec_rd));
    uint32_t o0 = g_cls_other;
    __asm__ volatile("ecall" ::: "memory");
    uint32_t trap_n = g_cls_other - o0;
    uint32_t trap_mc = g_last_mcause;
    g_cls_other = o0;
    uint32_t mtvec_ok = mtvec_rd == (uint32_t)(uintptr_t)&trap_dispatch;
    pass = cruns == 1u && (mc & MCAUSE_IRQ) != 0u && mtvec_ok && trap_n == 1u &&
           trap_mc == MCAUSE_ECALL_M;
    rec_chk("CONTROL", pass);
    rec_num("mie_meie", (mie_rd >> 11) & 1u);
    rec_num("mcause_irq_bit", mc >> 31);
    rec_hex("mcause", mc);
    rec_num("runs", cruns);
    rec_num("mtvec_ok", mtvec_ok);
    rec_num("mtvec_traps", trap_n);
    rec_hex("mtvec_mcause", trap_mc);
    chk_end(pass);
    pass = tot_t == 0u && tot_s == 0u && idle_t == 0u && idle_s == 0u && g_cls_ext == 1u &&
           g_cls_timer == 0u && g_cls_sw == 0u && tot_o == 0u && g_cls_other == 0u;
    rec_chk("NO-TIMER-TRAP", pass);
    rec_num("traps_timer", tot_t);
    rec_num("traps_sw", tot_s);
    rec_num("hold_clk", hclk);
    rec_num("hold_timer", idle_t);
    rec_num("hold_sw", idle_s);
    rec_num("ctrl_class_ext", g_cls_ext);
    rec_num("ctrl_class_timer", g_cls_timer);
    rec_num("ctrl_class_sw", g_cls_sw);
    rec_num("traps_other", tot_o + g_cls_other);
    chk_end(pass);
    mstatus_mie(0);
    pic_wr32(SEP_TOP_PIC_MEIE_BASE_ADDR(SRC_CTRL), 0u);
    pic_wr32(SEP_TOP_PIC_MEIPL_BASE_ADDR(SRC_CTRL), 0u);
    for (uint32_t i = 0; i < N_OT; i++) {
        wr32(k_ot[i].enable, 0u);
    }

    // Threshold, nesting and internal-timer legs. Each leg prints its graded
    // marker after its set-up and a control marker before its clean-up.
    rec_mark(0, "threshold_setup");
    leg_threshold();
    rec_mark(0, "nest_setup");
    leg_nest();
    for (uint32_t j = 0; j < 2u; j++) {
        uint32_t k = (g_prm[P_IT_FIRST] & 1u) ^ j;
        for (uint32_t mtsi = 0; mtsi < 2u; mtsi++) {
            rec_mark(0, "itimer_setup");
            leg_it_hold(k, mtsi);
        }
        rec_mark(0, "itimer_setup");
        leg_it_trap(k);
    }

    rec_mark(0, "mie_meie_setup");
    leg_mie_meie();
    rec_mark(0, "timer_pin_setup");
    leg_timer_pin();

    rec_mark(0, "end");
    if (g_err == 0) {
        sep_mbx_puts("PASS: PIC priority gate\n");
    }
    return g_err;
}
