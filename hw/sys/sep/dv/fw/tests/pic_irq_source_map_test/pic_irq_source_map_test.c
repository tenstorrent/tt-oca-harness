// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP PIC interrupt-source MAP + multi-source delivery firmware. The EL2 CPU
// registers PIC ISRs for a MUST set (mailbox, OTBN done, HMAC done) plus a
// seeded INTR_TEST subset patched into g_pic_params, drives each source, and
// proves the source -> PIC source-id map and ISR delivery:
//
//   mailbox[0]  sep_internal_interrupts[0]  -> PIC source 1   (real FIFO push)
//   OTBN done   sep_internal_interrupts[29] -> PIC source 30  (INTR_TEST)
//   HMAC done   sep_internal_interrupts[17] -> PIC source 18  (INTR_TEST)
//   extras      INTR_TEST pool (DMA done/chunk/error / HMAC-err / KMAC / CSRNG / EDN / KMAC-err)
//
// PIC source id = sep_internal_interrupts index + 1 (VeeR EL2 extintsrc_req is
// 1-based; source 0 is the tied no-interrupt source). Each ISR reads the claim
// id from meihap ([9:2]) and the handler at index N running is the PIC claim.
//
// Distinct from sep_mailbox_plic_test (ONE source) and from
// sep_irq_ip_to_aggregator_test (no_cpu, aggregate vector, no ISR).
//
// Checks (each failure increments errors; main() returns it and fw/startup/crt0.s turns
// 0 -> PASS magic / non-zero -> FAIL magic on the 0x8000_0000 mailbox):
//   CHK-NONVAC      : before any trigger, no ISR fires (quiet window).
//   CHK-DELIVER     : each selected source wakes its CPU ISR (WFI, no poll).
//                     OTBN also carries the source->PIC-id map.
//   CHK-IP-RW1C     : Event-type INTR_STATE / mailbox IRQS clear via W1C;
//                     DMA Status-type INTR_STATE reads back 0 after INTR_TEST=0.
//   CHK-PIC-COMPLETE: after the ISR clears the source the line de-asserts.
//   CHK-ONEHOT      : only the asserted source's ISR fires among the selected
//                     PIC-enabled sources.
//   CHK-RANDCFG     : graded host-side -- the cocotb test greps the SCENARIO
//                     line below for the patched source list and count.

#include <stdint.h>

#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_axil_mailbox.h"
#include "sep_pic.h"

#define CSR_MEIHAP 0xFC8

#define PIC_PARAM_MAGIC 0x91C0A11Cu
#define PIC_SRC_MAX 5
#define PIC_KIND_MBOX 0
#define PIC_KIND_INTR 1
// Secure DMA uses prim_intr_hw IntrT=="Status": INTR_STATE is RO, and INTR_TEST
// latches in test_q until software writes INTR_TEST=0. Event-type IPs (HMAC,
// OTBN, CSRNG, EDN, KMAC) clear with a W1C of INTR_STATE.
#define PIC_KIND_INTR_STATUS 2

#define MBOX_TRIGGER_WORD 0x4700CAFEu
#define ISR_WAIT_ITERS 200000
#define STORM_CHECK_ITERS 4096
// A claim that is not one of the selected sources, or a selected source whose
// line stays asserted after the ISR W1C, re-enters this ISR before the delivery
// wait can run. After this many such claims the ISR masks mie.meie so the
// interrupted wfi completes and the walk can fail naming the id. Source 0 is
// the tied no-interrupt source and has no MEIE word.
#define UNEXPECTED_CLAIM_MAX 64

/* Incremented by fw/startup/crt0.s _dummy_int_handler on every claim of a
 * source that has no registered ISR. A quiet-window pass that only looks at
 * g_count[] / g_unexpected_claims cannot see those claims. */
extern volatile uint32_t sep_dummy_int_count;

struct pic_src_desc {
    uint32_t pic_src;
    uint32_t kind;
    uint32_t state;
    uint32_t enable;
    uint32_t test;
    uint32_t bit;
    const char *name;
};

// Legal INTR_TEST / mailbox rows this firmware can deliver. PIC id = agg idx + 1.
static const struct pic_src_desc k_catalog[] = {
    {1u, PIC_KIND_MBOX, 0, 0, 0, 0, "mailbox"},
    {9u, PIC_KIND_INTR_STATUS, OCH_SEP_TOP_SECURE_DMA_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_SECURE_DMA_INTR_TEST_BASE_ADDR,
     SECURE_DMA__INTR_STATE__DMA_DONE_bm, "DMA"},
    {10u, PIC_KIND_INTR_STATUS, OCH_SEP_TOP_SECURE_DMA_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_SECURE_DMA_INTR_TEST_BASE_ADDR,
     SECURE_DMA__INTR_STATE__DMA_CHUNK_DONE_bm, "DMA-chunk"},
    {11u, PIC_KIND_INTR_STATUS, OCH_SEP_TOP_SECURE_DMA_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_SECURE_DMA_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_SECURE_DMA_INTR_TEST_BASE_ADDR,
     SECURE_DMA__INTR_STATE__DMA_ERROR_bm, "DMA-error"},
    {18u, PIC_KIND_INTR, OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_HMAC_INTR_TEST_BASE_ADDR,
     HMAC__INTR_STATE__HMAC_DONE_bm, "HMAC"},
    {20u, PIC_KIND_INTR, OCH_SEP_TOP_HMAC_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_HMAC_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_HMAC_INTR_TEST_BASE_ADDR,
     HMAC__INTR_STATE__HMAC_ERR_bm, "HMAC-err"},
    {21u, PIC_KIND_INTR, OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_KMAC_INTR_TEST_BASE_ADDR,
     KMAC__INTR_STATE__KMAC_DONE_bm, "KMAC"},
    {23u, PIC_KIND_INTR, OCH_SEP_TOP_KMAC_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_KMAC_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_KMAC_INTR_TEST_BASE_ADDR,
     KMAC__INTR_STATE__KMAC_ERR_bm, "KMAC-err"},
    {24u, PIC_KIND_INTR, OCH_SEP_TOP_CSRNG_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_CSRNG_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_CSRNG_INTR_TEST_BASE_ADDR,
     CSRNG__INTR_STATE__CS_CMD_REQ_DONE_bm, "CSRNG"},
    {28u, PIC_KIND_INTR, OCH_SEP_TOP_EDN_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_EDN_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_EDN_INTR_TEST_BASE_ADDR,
     EDN__INTR_STATE__EDN_CMD_REQ_DONE_bm, "EDN"},
    {30u, PIC_KIND_INTR, OCH_SEP_TOP_OTBN_INTR_STATE_BASE_ADDR,
     OCH_SEP_TOP_OTBN_INTR_ENABLE_BASE_ADDR, OCH_SEP_TOP_OTBN_INTR_TEST_BASE_ADDR,
     OTBN__INTR_STATE__DONE_bm, "OTBN"},
};

// [0]=magic [1]=n_src [2..6]=PIC source ids. Default is the MUST trio so an
// unpatched image still runs the directed walk.
volatile uint32_t g_pic_params[7] = {PIC_PARAM_MAGIC, 3u, 1u, 30u, 18u, 0u, 0u};

static struct pic_src_desc g_sel[PIC_SRC_MAX];
static int g_n_src = 0;
static volatile uint32_t g_count[PIC_SRC_MAX];
static volatile uint32_t g_claim[PIC_SRC_MAX];
static volatile uint32_t g_mbox_irqs_after = 0;
// Value read in the ISR just before its W1C, so the clear is bracketed:
// the bit was seen set, then seen clear, with nothing else in between.
static volatile uint32_t g_mbox_irqs_before = 0;
static volatile uint32_t g_state_before[PIC_SRC_MAX];
static volatile uint32_t g_unexpected_id = 0;
static volatile uint32_t g_unexpected_claims = 0;
static int g_mbox_idx = -1;

static inline uint32_t rd32(uint32_t a) {
    return *(volatile uint32_t *)a;
}
static inline void wr32(uint32_t a, uint32_t v) {
    *(volatile uint32_t *)a = v;
}

static inline uint32_t claim_id(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    return (meihap >> 2) & 0xFF;
}

static int idx_of_pic(uint32_t pic_src) {
    for (int i = 0; i < g_n_src; i++) {
        if (g_sel[i].pic_src == pic_src) {
            return i;
        }
    }
    return -1;
}

static int is_ip_intr(uint32_t kind) {
    return kind == PIC_KIND_INTR || kind == PIC_KIND_INTR_STATUS;
}

static void clear_ip_intr(const struct pic_src_desc *d) {
    if (d->kind == PIC_KIND_INTR_STATUS) {
        wr32(d->test, 0);
        wr32(OCH_SEP_TOP_SECURE_DMA_STATUS_BASE_ADDR, SECURE_DMA__STATUS__DONE_bm |
                                                          SECURE_DMA__STATUS__ERROR_bm |
                                                          SECURE_DMA__STATUS__CHUNK_DONE_bm);
    } else {
        wr32(d->state, d->bit);
    }
}

static const struct pic_src_desc *catalog_of(uint32_t pic_src) {
    for (unsigned i = 0; i < sizeof(k_catalog) / sizeof(k_catalog[0]); i++) {
        if (k_catalog[i].pic_src == pic_src) {
            return &k_catalog[i];
        }
    }
    return 0;
}

void __attribute__((interrupt("machine"))) mbox_isr(void) {
    int idx = g_mbox_idx;
    if (idx >= 0) {
        g_claim[idx] = claim_id();
        g_mbox_irqs_before = sep_axil_mbox_rd(SEP_AXIL_MBOX0_IRQS);
        sep_axil_mbox_wr(SEP_AXIL_MBOX0_WIRQT, 0xFFu);
        sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQS, SEP_AXIL_MBOX_IRQ_ALL);
        g_mbox_irqs_after = sep_axil_mbox_rd(SEP_AXIL_MBOX0_IRQS);
        g_count[idx]++;
    }
    __asm__ volatile("fence" ::: "memory");
}

static void silence_and_bound(uint32_t id) {
    if (g_unexpected_claims == 0) {
        g_unexpected_id = id;
    }
    g_unexpected_claims++;
    if (id >= 1u) {
        pic_disable_source(id);
    }
    if (g_unexpected_claims > UNEXPECTED_CLAIM_MAX) {
        __asm__ volatile("csrc mie, %0" ::"r"((uint32_t)(1u << 11)));
    }
}

void __attribute__((interrupt("machine"))) pic_intr_isr(void) {
    uint32_t id = claim_id();
    int idx = idx_of_pic(id);
    if (idx >= 0 && is_ip_intr(g_sel[idx].kind)) {
        if (g_count[idx] != 0) {
            // Already handled this selected source; the line did not drop, so
            // mret would re-enter before the delivery wait can observe the count.
            silence_and_bound(id);
        } else {
            g_claim[idx] = id;
            g_state_before[idx] = rd32(g_sel[idx].state);
            clear_ip_intr(&g_sel[idx]);
            g_count[idx]++;
        }
    } else {
        silence_and_bound(id);
    }
    __asm__ volatile("fence" ::: "memory");
}

static void report_unexpected(void) {
    if (g_unexpected_claims == 0) {
        return;
    }
    sep_mbx_puts("FAIL: unexpected PIC source id=");
    sep_mbx_puthex(g_unexpected_id);
    sep_mbx_puts(" claims=");
    sep_mbx_puthex(g_unexpected_claims);
    sep_mbx_puts("\n");
}

static int wait_isr(int s, uint32_t before) {
    int timeout = ISR_WAIT_ITERS;
    while (timeout-- > 0) {
        __asm__ volatile("wfi");
        if (g_unexpected_claims != 0) {
            return 0;
        }
        if (g_count[s] != before) {
            return 1;
        }
    }
    return 0;
}

static int only_one_fired(int s, const uint32_t snapshot[PIC_SRC_MAX]) {
    for (int j = 0; j < g_n_src; j++) {
        if (j == s) {
            continue;
        }
        if (g_count[j] != snapshot[j]) {
            return 0;
        }
    }
    return 1;
}

static int resolve_params(void) {
    if (g_pic_params[0] != PIC_PARAM_MAGIC) {
        sep_mbx_puts("FAIL: PIC param magic mismatch\n");
        return 1;
    }
    uint32_t n = g_pic_params[1];
    if (n < 3u || n > (uint32_t)PIC_SRC_MAX) {
        sep_mbx_puts("FAIL: PIC n_src out of range\n");
        return 1;
    }
    g_n_src = (int)n;
    for (int i = 0; i < g_n_src; i++) {
        const struct pic_src_desc *d = catalog_of(g_pic_params[2 + i]);
        if (!d) {
            sep_mbx_puts("FAIL: unknown PIC source ");
            sep_mbx_puthex(g_pic_params[2 + i]);
            sep_mbx_putc('\n');
            return 1;
        }
        g_sel[i] = *d;
        g_count[i] = 0;
        g_claim[i] = 0;
        if (d->kind == PIC_KIND_MBOX) {
            g_mbox_idx = i;
        }
    }
    if (g_mbox_idx < 0) {
        sep_mbx_puts("FAIL: mailbox is not in the selected PIC set\n");
        return 1;
    }
    return 0;
}

static void arm_sources(void) {
    for (int i = 0; i < g_n_src; i++) {
        pic_handler_t h = (g_sel[i].kind == PIC_KIND_MBOX) ? mbox_isr : pic_intr_isr;
        pic_register_handler(g_sel[i].pic_src, h);
        pic_set_gateway(g_sel[i].pic_src, 0, 0);
        pic_set_priority(g_sel[i].pic_src, 1);
        pic_enable_source(g_sel[i].pic_src);
    }
    pic_enable_interrupts();

    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQS, SEP_AXIL_MBOX_IRQ_ALL);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WIRQT, 0xFFu);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQEN, SEP_AXIL_MBOX_IRQ_ALL);

    // OR INTR_ENABLE bits that share a base so two extras on one IP stay armed.
    for (int i = 0; i < g_n_src; i++) {
        if (!is_ip_intr(g_sel[i].kind)) {
            continue;
        }
        uint32_t bits = 0;
        uint32_t base_en = g_sel[i].enable;
        for (int j = 0; j < g_n_src; j++) {
            if (is_ip_intr(g_sel[j].kind) && g_sel[j].enable == base_en) {
                bits |= g_sel[j].bit;
            }
        }
        wr32(base_en, bits);
    }
}

static int run_mbox(void) {
    int errors = 0;
    int s = g_mbox_idx;
    uint32_t snap[PIC_SRC_MAX];

    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQS, SEP_AXIL_MBOX_IRQ_ALL);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WIRQT, 0u);
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_IRQEN, SEP_AXIL_MBOX_IRQ_ALL);
    for (int j = 0; j < g_n_src; j++) {
        snap[j] = g_count[j];
    }
    __asm__ volatile("fence" ::: "memory");

    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WRITE_DATA, MBOX_TRIGGER_WORD);

    if (!wait_isr(s, snap[s])) {
        sep_mbx_puts("FAIL: mailbox ISR never reached the CPU\n");
        report_unexpected();
        return 1;
    }
    sep_mbx_puts("CHK-DELIVER PASS: mailbox ISR reached the CPU\n");
    if (!only_one_fired(s, snap)) {
        sep_mbx_puts("FAIL: mailbox triggered a neighbour source\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-ONEHOT PASS: only the mailbox ISR fired among the "
                     "PIC-enabled sources\n");
    }
    if ((g_mbox_irqs_before & SEP_AXIL_MBOX_IRQ_ALL) == 0u) {
        sep_mbx_puts("FAIL: mailbox IRQS was not set before the ISR W1C ");
        sep_mbx_puthex(g_mbox_irqs_before);
        sep_mbx_putc('\n');
        errors++;
    } else if (g_mbox_irqs_after & SEP_AXIL_MBOX_IRQ_ALL) {
        sep_mbx_puts("FAIL: mailbox IRQS did not clear via W1C ");
        sep_mbx_puthex(g_mbox_irqs_after);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-IP-RW1C PASS: mailbox IRQS read set before and 0 after W1C\n");
    }
    sep_axil_mbox_wr(SEP_AXIL_MBOX0_WIRQT, 0xFFu);
    return errors;
}

static int run_intr(int s) {
    int errors = 0;
    uint32_t snap[PIC_SRC_MAX];
    const struct pic_src_desc *d = &g_sel[s];

    wr32(d->enable, rd32(d->enable) | d->bit);
    for (int j = 0; j < g_n_src; j++) {
        snap[j] = g_count[j];
    }
    __asm__ volatile("fence" ::: "memory");

    wr32(d->test, d->bit);

    if (!wait_isr(s, snap[s])) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(d->name);
        sep_mbx_puts(" ISR never reached the CPU\n");
        report_unexpected();
        return 1;
    }
    sep_mbx_puts("CHK-DELIVER PASS: ");
    sep_mbx_puts(d->name);
    sep_mbx_puts(" ISR woke the CPU\n");
    if (!only_one_fired(s, snap)) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(d->name);
        sep_mbx_puts(" triggered a neighbour source (not one-hot)\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-ONEHOT PASS: ");
        sep_mbx_puts(d->name);
        sep_mbx_puts(" fired alone among the PIC-enabled sources\n");
    }
    if ((g_state_before[s] & d->bit) == 0u) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(d->name);
        sep_mbx_puts(" INTR_STATE bit was not set before the ISR clear\n");
        errors++;
    } else if (rd32(d->state) & d->bit) {
        sep_mbx_puts("FAIL: ");
        sep_mbx_puts(d->name);
        sep_mbx_puts(" INTR_STATE did not clear via W1C\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-IP-RW1C PASS: ");
        sep_mbx_puts(d->name);
        sep_mbx_puts(" INTR_STATE read set before and 0 after the ISR clear\n");
    }
    return errors;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init();
    sep_mbx_puts("SEP PIC IRQ source map delivery test\n");

    if (resolve_params()) {
        return 1;
    }

    sep_mbx_puts("SCENARIO n=");
    sep_mbx_puthex((uint32_t)g_n_src);
    sep_mbx_puts(" src=");
    for (int i = 0; i < g_n_src; i++) {
        if (i) {
            sep_mbx_putc(',');
        }
        sep_mbx_puthex(g_sel[i].pic_src);
    }
    sep_mbx_putc('\n');
    /* Params resolved. Whether the HOST patch actually landed is graded by
     * the SCENARIO needle the cocotb test greps -- the compiled default
     * satisfies resolve_params(), so this line is not that proof. */
    sep_mbx_puts("STEP params resolved from the DTCM block\n");

    arm_sources();

    for (volatile int i = 0; i < STORM_CHECK_ITERS; i++) {
        __asm__ volatile("nop");
    }
    int spurious = 0;
    for (int j = 0; j < g_n_src; j++) {
        if (g_count[j]) {
            spurious = 1;
        }
    }
    if (spurious || g_unexpected_claims != 0 || sep_dummy_int_count != 0) {
        sep_mbx_puts("FAIL: spurious ISR before any source asserted\n");
        if (sep_dummy_int_count != 0) {
            sep_mbx_puts("FAIL: dummy handler served unregistered IRQ count=");
            sep_mbx_puthex(sep_dummy_int_count);
            sep_mbx_putc('\n');
        }
        report_unexpected();
        errors++;
    } else {
        sep_mbx_puts("CHK-NONVAC PASS: no spurious ISR before any trigger "
                     "(quiet window clean, dummy handler count 0)\n");
    }

    for (int i = 0; i < g_n_src; i++) {
        if (g_sel[i].kind == PIC_KIND_MBOX) {
            errors += run_mbox();
        } else {
            errors += run_intr(i);
        }
        if (errors) {
            return errors;
        }
    }

    uint32_t before[PIC_SRC_MAX];
    for (int j = 0; j < g_n_src; j++) {
        before[j] = g_count[j];
    }
    for (volatile int i = 0; i < STORM_CHECK_ITERS; i++) {
        __asm__ volatile("nop");
    }
    int storm = 0;
    for (int j = 0; j < g_n_src; j++) {
        if (g_count[j] != before[j]) {
            sep_mbx_puts("FAIL: interrupt re-fired after clear (storm) on source idx ");
            sep_mbx_puthex((uint32_t)j);
            sep_mbx_putc('\n');
            errors++;
            storm = 1;
        }
    }
    if (g_unexpected_claims != 0) {
        sep_mbx_puts("FAIL: unexpected PIC claim after the walk (storm)\n");
        report_unexpected();
        errors++;
        storm = 1;
    }
    if (!storm) {
        sep_mbx_puts("CHK-PIC-COMPLETE PASS: no source re-fired after its ISR cleared "
                     "it (claim completed, no storm)\n");
    }

    if (sep_dummy_int_count != 0) {
        sep_mbx_puts("FAIL: dummy handler served unregistered IRQ after walk count=");
        sep_mbx_puthex(sep_dummy_int_count);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-DUMMY PASS: dummy handler count 0 after the walk\n");
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: PIC source map delivery -- ");
        for (int i = 0; i < g_n_src; i++) {
            sep_mbx_puts(g_sel[i].name);
            sep_mbx_puts(" claim ");
            sep_mbx_puthex(g_claim[i]);
            sep_mbx_putc(' ');
        }
        sep_mbx_puts("(nonvac/map/deliver/onehot/W1C/no-storm OK)\n");
    }
    return errors;
}
