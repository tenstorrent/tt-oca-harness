// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP PIC external-access refusal. The CPU arms distinct non-zero values in the
// PIC, holds one edge bit pending, opens the mailbox windows of the inbound
// filter and asks the host to send external reads and writes to the PIC
// aperture through the inbound port, first with no PIC window (regime A, the
// default block) and then with an allow window over the EL2_PIC aperture
// (regime B). After each regime the host writes one completion
// word to the inbound port of mailbox 7, and the CPU pops it from the outbound
// READ_DATA of mailbox 7 in a bounded wait. The cocotb test
// sep_pic_external_access_refuse_test patches the seeded values into g_p and
// grades the response codes; this firmware grades the CPU reads:
//
//   CHK-CPU-READ  every armed register reads non-zero and meip[0] bit 1 reads 1
//                 before the external accesses (control).
//   CHK-LANDED    after the last external access, every armed register reads
//                 its armed value and meip[0] bit 1 still reads 1.
//
// Console lines (sep_console_rec.h shapes):
//   PIC-ARMED ...          the armed values as read before the accesses
//   PIC-WINDOW ns=<n> ...  FILTER_CONFIG, START_ADDR and END_ADDR of each PIC window entry
//   PIC-COMPLETE r=<A|B>   the popped completion word
//   PIC-LANDED ...         the read-back after the last access
//   REQ regime_a / REQ regime_b   the host runs the accesses of that regime
//
// mstatus.MIE and mie.MEIE stay 0, so no armed source delivers.

#include <stdint.h>

#include "filter_ctrl.h"
#include "sep.h"
#include "sep_axil_mailbox.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"
#include "sep_pic.h"

// ---- Parameter block (the host patches it; keep in step with the test) ----
#define P_MAGIC_WORD 0x9C1E0A51u
enum {
    P_MAGIC,
    P_SEED,
    P_J,       // interior entry J of each array
    P_MEIP_W,  // interior meip word (1 to 6)
    P_HOLE,    // hole address
    P_PAST,    // past-extent address
    P_ORDER0,  // access order: 5 bits per target, targets 0 to 5
    P_ORDER1,  // targets 6 to 11
    P_ORDER2,  // targets 12 to 17
    P_RWFIRST, // bit t: target t is written before it is read
    P_IDLE0,   // meip[0] bits of the excluded idle sources
    P_CW_A,    // completion word of regime A (low 32 bits)
    P_CW_B,    // completion word of regime B (low 32 bits)
    P_PIC_END, // last byte of the EL2_PIC aperture (generated memory map)
    P_COUNT
};

// Committed defaults: a directed image that runs stand-alone.
volatile uint32_t g_p[P_COUNT] = {
    P_MAGIC_WORD, 0x1u, 77u,  3u,          0xC0080800u, 0xC0086000u, 0x0u,
    0x0u,         0x0u, 0x0u, 0x0001A000u, 0x0C0DE0A0u, 0x0C0DE0B0u, 0xC0087FFFu,
};

// Armed values (the contract of the entry, step 2).
#define ARM_PRIORD 1u
#define ARM_PRI_FIRST 7u
#define ARM_PRI_J 9u
#define ARM_PRI_LAST 11u
#define ARM_MEIE 1u
#define ARM_GWCTRL 2u // edge, active high
#define SRC_FIRST 1u
#define SRC_LAST 255u

// Inbound filter entries: mailbox 0 inbound, mailbox 7 inbound, PIC ns=0, PIC ns=1.
#define E_MBX0 0u
#define E_MBX7 1u
#define E_PIC0 2u
#define E_PIC1 3u
// The window covers the EL2_PIC aperture from the PIC base to the last byte the
// host takes from the generated memory map (P_PIC_END).
#define PIC_WIN_START SEP_TOP_PIC_BASE_ADDR
#define PIC_WIN_END (g_p[P_PIC_END])
// Byte offset of the upper 32-bit word of a 64-bit filter_ctrl register
// (filter_ctrl.h register types; the CPU bus is little-endian).
#define FILT_HI_OFF ((uint32_t)(sizeof(filter_ctrl__FILTER_CONFIG_t) / 2u))
_Static_assert(sizeof(filter_ctrl__FILTER_CONFIG_t) == 8u, "FILTER_CONFIG is 64-bit");
_Static_assert(sizeof(filter_ctrl__START_ADDR_t) == 8u, "START_ADDR is 64-bit");
_Static_assert(sizeof(filter_ctrl__END_ADDR_t) == 8u, "END_ADDR is 64-bit");
// Inbound mailbox window: from the inbound block base to the next channel's
// outbound block base (generated memory map).
#define MBX_IN_SPAN \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_1_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR)
_Static_assert(SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR ==
                   SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR,
               "WRITE_DATA opens the inbound block");
#define CFG_RW_EN \
    (FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm | FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm | \
     FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm)
#define CFG_NS FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm

#define MBX_OUT(m, reg) \
    sep_axil_mbox_ch((m), SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_##reg##_BASE_ADDR)
#define MBX_IN(m, reg) \
    sep_axil_mbox_ch((m), SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_##reg##_BASE_ADDR)
#define MBX_EMPTY AXIL_MAILBOX__STATUS__EMPTY_bm

#define PEND_WAIT_ITERS 20000u
#define CW_WAIT_ITERS 400000u
#define DRIVE_WORD 0x5EC01A51u

static int g_err;

static inline uint32_t rd(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
    __asm__ volatile("fence" ::: "memory");
}

static uint32_t meip0_masked(void) {
    return pic_read_meip(0) & ~g_p[P_IDLE0];
}

// ---- Inbound filter entry ----
static void filt_program(uint32_t idx, uint32_t start, uint32_t end, uint32_t cfg) {
    wr(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(idx), 0u);
    wr(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(idx) + FILT_HI_OFF, 0u);
    wr(SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(idx), start);
    wr(SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(idx) + FILT_HI_OFF, 0u);
    wr(SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(idx), end);
    wr(SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(idx) + FILT_HI_OFF, 0u);
    wr(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(idx), cfg);
}

static void mbx_window(uint32_t idx, uint32_t m) {
    uint32_t s = MBX_IN(m, WRITE_DATA);
    filt_program(idx, s, s + MBX_IN_SPAN - 1u, CFG_RW_EN);
}

// ---- Armed state ----
struct armed {
    uint32_t cfg, pri[3], en[3], gw[3], meip0;
};

static void read_armed(struct armed *a) {
    uint32_t ent[3] = {SRC_FIRST, g_p[P_J], SRC_LAST};
    a->cfg = pic_read_mpiccfg();
    for (int i = 0; i < 3; i++) {
        a->pri[i] = pic_read_priority(ent[i]);
        a->en[i] = pic_read_source_enable(ent[i]);
        a->gw[i] = pic_read_gateway(ent[i]);
    }
    a->meip0 = meip0_masked();
}

static void print_armed(const char *tag, const struct armed *a) {
    sep_mbx_puts(tag);
    rec_hex("mpiccfg", a->cfg);
    rec_hex("pri", (a->pri[0] << 16) | (a->pri[1] << 8) | a->pri[2]);
    rec_hex("en", (a->en[0] << 16) | (a->en[1] << 8) | a->en[2]);
    rec_hex("gw", (a->gw[0] << 16) | (a->gw[1] << 8) | a->gw[2]);
    rec_hex("meip0", a->meip0);
    rec_end();
}

static void arm_pic(void) {
    uint32_t ent[3] = {SRC_FIRST, g_p[P_J], SRC_LAST};
    uint32_t pri[3] = {ARM_PRI_FIRST, ARM_PRI_J, ARM_PRI_LAST};
    pic_write_priord(ARM_PRIORD);
    for (int i = 0; i < 3; i++) {
        pic_set_priority(ent[i], pri[i]);
        pic_set_gateway(ent[i], 1u, 0u);
        pic_enable_source(ent[i]);
    }
}

// Source drive recipe on mailbox 0: IRQEN.wtirq 1, WIRQT 0, one pushed word on
// the inbound port; release by a pop from the outbound READ_DATA and a write of
// IRQS bit 0 of the inbound port. The edge gateway holds the pending bit.
static uint32_t drive_source1(void) {
    wr(MBX_IN(0, IRQS), SEP_AXIL_MBOX_IRQ_ALL);
    wr(MBX_IN(0, WIRQT), 0u);
    wr(MBX_IN(0, IRQEN), SEP_AXIL_MBOX_IRQ_WRITE);
    wr(MBX_IN(0, WRITE_DATA), DRIVE_WORD);
    uint32_t t = PEND_WAIT_ITERS;
    while (!pic_source_pending(SRC_FIRST) && --t > 0u) {
    }
    uint32_t seen = pic_source_pending(SRC_FIRST);
    uint32_t popped = rd(MBX_OUT(0, READ_DATA));
    wr(MBX_IN(0, IRQS), SEP_AXIL_MBOX_IRQ_WRITE);
    wr(MBX_IN(0, IRQEN), 0u);
    rec_ctl("SRC1-DRIVE");
    rec_hex("pending_seen", seen);
    rec_hex("popped", popped);
    rec_hex("in_irqs", rd(MBX_IN(0, IRQS)));
    rec_end();
    return seen;
}

// Bounded wait for the completion word on mailbox 7; returns 1 on a pop.
static int pop_completion(const char *r, uint32_t want) {
    uint32_t t = CW_WAIT_ITERS;
    while ((rd(MBX_OUT(7, STATUS)) & MBX_EMPTY) && --t > 0u) {
    }
    if (rd(MBX_OUT(7, STATUS)) & MBX_EMPTY) {
        sep_mbx_puts("FAIL: no completion word on mailbox 7 regime=");
        sep_mbx_puts(r);
        rec_end();
        g_err++;
        return 0;
    }
    uint32_t w = rd(MBX_OUT(7, READ_DATA));
    sep_mbx_puts("PIC-COMPLETE");
    rec_str("r", r);
    rec_hex("word", w);
    rec_hex("want", want);
    rec_end();
    if (w != want) {
        g_err++;
    }
    return 1;
}

static void print_window(uint32_t idx, uint32_t ns) {
    sep_mbx_puts("PIC-WINDOW");
    rec_num("ns", ns);
    rec_hex("FILTER_CONFIG", rd(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(idx)));
    rec_hex("START_ADDR", rd(SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(idx)));
    rec_hex("END_ADDR", rd(SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(idx)));
    rec_hex("cfg_hi", rd(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(idx) + FILT_HI_OFF));
    rec_hex("start_hi", rd(SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(idx) + FILT_HI_OFF));
    rec_hex("end_hi", rd(SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(idx) + FILT_HI_OFF));
    rec_end();
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP PIC external access refuse test\n");
    if (g_p[P_MAGIC] != P_MAGIC_WORD) {
        sep_mbx_puts("FAIL: parameter block magic\n");
        return 1;
    }
    sep_mbx_puts("PARAMS");
    rec_hex("seed", g_p[P_SEED]);
    rec_hex("j", g_p[P_J]);
    rec_hex("meip_w", g_p[P_MEIP_W]);
    rec_hex("hole", g_p[P_HOLE]);
    rec_hex("past", g_p[P_PAST]);
    rec_hex("o0", g_p[P_ORDER0]);
    rec_hex("o1", g_p[P_ORDER1]);
    rec_hex("o2", g_p[P_ORDER2]);
    rec_hex("rw", g_p[P_RWFIRST]);
    rec_hex("idle0", g_p[P_IDLE0]);
    rec_hex("pic_end", g_p[P_PIC_END]);
    rec_end();

    // Set-up: arm, open the mailbox 0 window, hold the edge bit of source 1.
    rec_mark(0, "setup");
    arm_pic();
    mbx_window(E_MBX0, 0u);
    uint32_t seen = drive_source1();

    // CHK-CPU-READ: the armed state is live before the external accesses.
    rec_mark(1, "cpu_read");
    struct armed a0;
    read_armed(&a0);
    print_armed("PIC-ARMED", &a0);
    uint32_t vals[10] = {a0.cfg,   a0.pri[0], a0.pri[1], a0.pri[2], a0.en[0],
                         a0.en[1], a0.en[2],  a0.gw[0],  a0.gw[1],  a0.gw[2]};
    uint32_t nz = 0;
    for (int i = 0; i < 10; i++) {
        nz += vals[i] != 0u;
    }
    uint32_t bit1 = (a0.meip0 >> SRC_FIRST) & 1u;
    nz += bit1;
    int ok = nz == 11u && seen == 1u;
    rec_chk("CPU-READ", ok);
    rec_num("armed_regs", 11u);
    rec_num("nonzero", nz);
    rec_num("meip0_bit1", bit1);
    rec_end();
    g_err += !ok;

    // Regime A: no PIC window; mailbox 7 window open as the completion channel.
    rec_mark(0, "regime_a");
    mbx_window(E_MBX7, 7u);
    wr(MBX_IN(7, IRQEN), 0u);
    sep_mbx_puts("PIC-REGIME-A\n");
    rec_req("regime_a");
    rec_end();
    pop_completion("A", g_p[P_CW_A]);

    // Regime B: one allow window per NS value over the PIC aperture.
    rec_mark(1, "regime_b");
    filt_program(E_PIC0, PIC_WIN_START, PIC_WIN_END, CFG_RW_EN);
    filt_program(E_PIC1, PIC_WIN_START, PIC_WIN_END, CFG_RW_EN | CFG_NS);
    sep_mbx_puts("PIC-REGIME-B\n");
    print_window(E_PIC0, 0u);
    print_window(E_PIC1, 1u);
    rec_req("regime_b");
    rec_end();
    if (pop_completion("B", g_p[P_CW_B])) {
        // CHK-LANDED: no external write landed in a PIC register.
        struct armed a1;
        read_armed(&a1);
        print_armed("PIC-LANDED", &a1);
        uint32_t want_pri[3] = {ARM_PRI_FIRST, ARM_PRI_J, ARM_PRI_LAST};
        uint32_t same = (a1.cfg & EL2_PIC__MPICCFG__PRIORD_bm) == ARM_PRIORD;
        for (int i = 0; i < 3; i++) {
            same += (a1.pri[i] & EL2_PIC__MEIPL__INTPRIORITY_bm) == want_pri[i];
            same += (a1.en[i] & EL2_PIC__MEIE__INTEN_bm) == ARM_MEIE;
            same +=
                (a1.gw[i] & (EL2_PIC__MEIGWCTRL__POLARITY_bm | EL2_PIC__MEIGWCTRL__IRQ_TYPE_bm)) ==
                ARM_GWCTRL;
        }
        same += (a1.meip0 >> SRC_FIRST) & 1u;
        int lok = same == 11u;
        rec_chk("LANDED", lok);
        rec_num("regs", 11u);
        rec_num("same", lok ? 1u : 0u);
        rec_num("matched", same);
        rec_end();
        g_err += !lok;
    }

    rec_mark(0, "end");
    // Clean-up: close the PIC and mailbox windows, return the armed entries to reset.
    for (uint32_t e = 0; e < 4u; e++) {
        wr(SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(e), 0u);
    }
    uint32_t ent[3] = {SRC_FIRST, g_p[P_J], SRC_LAST};
    for (int i = 0; i < 3; i++) {
        pic_disable_source(ent[i]);
        pic_set_priority(ent[i], 0u);
        pic_set_gateway(ent[i], 0u, 0u);
    }
    pic_write_meigwclr(SRC_FIRST, 0u);
    pic_write_priord(0u);
    sep_mbx_puts("DONE\n");
    return g_err;
}
