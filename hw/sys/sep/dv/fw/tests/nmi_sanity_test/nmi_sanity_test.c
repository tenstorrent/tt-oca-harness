// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP NMI sanity test. Verifies the VeeR EL2 NMI path on bare `sep`:
//   * the NMI vector register reads its reset default;
//   * the NMI vector register is writable and reads back the programmed vector;
//   * once the vector lock is set, a write to the vector register is ignored;
//   * a watchdog bark fires the NMI and the registered handler runs.
//
// The watchdog bark drives the CPU NMI inside `sep`; the testbench injects
// nothing. The handler clears and disables the watchdog and returns, so main()
// reports the result through its return code.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_nmi.h"
#include "sep_wdt.h"

// Bark threshold in WDT-clock ticks. The WDT clock is much slower than the core
// clock, so a small threshold keeps the simulation short; the bark->NMI path does
// not depend on the value. The bite threshold stays high so only the bark fires;
// `sep_reset_wdt_sanity_test` covers the bite path.
#define WDT_BARK_SIM 4u
#define WDT_BITE_HIGH 0x10000u

#define LOCKED_WRITE_VAL 0xDEADBEE0u // attempted (and rejected) post-lock write
#define NMI_WAIT_ITERS 200000        // bound on the wait for the bark NMI

static volatile uint32_t g_nmi_fired = 0;
// Watchdog interrupt state sampled in the NMI handler before the bark is cleared.
static volatile uint32_t g_nmi_bark_state = 0;

// NMI handler: clear the bark and disable the watchdog so the NMI deasserts
// before mret, then flag completion for the wait loop in main().
void nmi_handler(void) {
    // Only a bark seen set before the clear ties this NMI to the watchdog.
    g_nmi_bark_state = wdt_get_intr_state();
    wdt_clear_bark();
    wdt_disable();
    g_nmi_fired = 1;
    __asm__ volatile("fence" ::: "memory");
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init();
    sep_mbx_puts("SEP NMI sanity test\n");

    nmi_register_handler(nmi_handler);

    uint32_t nmi_addr = nmi_get_vector_addr();
    if (nmi_addr & 0xFFu) {
        sep_mbx_puts("FAIL: NMI trampoline not 256-byte aligned ");
        sep_mbx_puthex(nmi_addr);
        sep_mbx_putc('\n');
        errors++;
    }

    uint32_t vec_default = nmi_read_vector_reg();
    if (vec_default != SEP_NMI_VEC_DEFAULT) {
        sep_mbx_puts("FAIL: SEP_NMI_VEC default ");
        sep_mbx_puthex(vec_default);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-VEC-DEFAULT PASS: SEP_NMI_VEC=");
        sep_mbx_puthex(vec_default);
        sep_mbx_putc('\n');
    }

    nmi_set_vector_reg();
    uint32_t vec_rb = nmi_read_vector_reg();
    if (vec_rb != nmi_addr) {
        sep_mbx_puts("FAIL: SEP_NMI_VEC writeback ");
        sep_mbx_puthex(vec_rb);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-VEC-WRITE PASS: SEP_NMI_VEC readback=");
        sep_mbx_puthex(vec_rb);
        sep_mbx_putc('\n');
    }

    // The lock must read set, and a later write must not change the vector.
    nmi_lock_vector_reg();
    uint32_t lock_val = nmi_read_lock_reg();
    int lock_ok = (lock_val == SEP_CPU_CTRL__SEP_NMI_VEC_LOCK__LOCK_bm);
    if (!lock_ok) {
        sep_mbx_puts("FAIL: SEP_NMI_VEC_LOCK not set ");
        sep_mbx_puthex(lock_val);
        sep_mbx_putc('\n');
        errors++;
    }
    *(volatile uint32_t *)SEP_NMI_VEC_ADDR = LOCKED_WRITE_VAL;
    __asm__ volatile("fence" ::: "memory");
    uint32_t locked_rb = nmi_read_vector_reg();
    if (locked_rb != nmi_addr) {
        sep_mbx_puts("FAIL: SEP_NMI_VEC changed despite lock ");
        sep_mbx_puthex(locked_rb);
        sep_mbx_putc('\n');
        errors++;
    } else if (lock_ok) {
        sep_mbx_puts("CHK-LOCK PASS: lock=1 and locked write ignored (vec still ");
        sep_mbx_puthex(locked_rb);
        sep_mbx_puts(")\n");
    }

    g_nmi_fired = 0;
    __asm__ volatile("fence" ::: "memory");
    wdt_set_count(0);
    wdt_set_bark(WDT_BARK_SIM);
    wdt_set_bite(WDT_BITE_HIGH);
    wdt_enable();
    sep_mbx_puts("STEP watchdog configured (small bark threshold) and enabled\n");

    // Bounded wait, so an NMI that never fires reports FAIL instead of hanging.
    int timeout = NMI_WAIT_ITERS;
    while (timeout-- > 0) {
        __asm__ volatile("wfi");
        if (g_nmi_fired) {
            break;
        }
    }
    if (!g_nmi_fired) {
        sep_mbx_puts("FAIL: WDT bark NMI never fired\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-WDT-NMI PASS: bark fired NMI, handler ran\n");
    }

    // The handler's clear and disable must still hold after the NMI returns.
    if (g_nmi_fired) {
        int bark_seen = (g_nmi_bark_state & WDT_INTR_BARK) != 0u;
        if (!bark_seen) {
            sep_mbx_puts("FAIL: NMI taken but INTR_STATE.bark was not set in handler ");
            sep_mbx_puthex(g_nmi_bark_state);
            sep_mbx_putc('\n');
            errors++;
        }
        uint32_t intr_after = wdt_get_intr_state();
        uint32_t ctrl_after = wdt_get_ctrl();
        if (intr_after & WDT_INTR_BARK) {
            sep_mbx_puts("FAIL: WDT bark not cleared after NMI ");
            sep_mbx_puthex(intr_after);
            sep_mbx_putc('\n');
            errors++;
        } else if (ctrl_after != 0u) {
            sep_mbx_puts("FAIL: WDT not disabled after NMI ");
            sep_mbx_puthex(ctrl_after);
            sep_mbx_putc('\n');
            errors++;
        } else if (bark_seen) {
            // PASS needs the bark set in the handler, cleared after, and the
            // watchdog disabled.
            sep_mbx_puts("CHK-WDT-CLEAR PASS: INTR_STATE.bark observed set in handler, cleared "
                         "after, WDOG_CTRL disabled\n");
        }
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: NMI sanity (default/writeback/lock + WDT bark->NMI->clear)\n");
    }
    return errors;
}
