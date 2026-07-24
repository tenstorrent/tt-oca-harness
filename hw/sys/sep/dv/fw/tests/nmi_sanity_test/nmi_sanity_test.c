// SPDX-License-Identifier: Apache-2.0
//
// SEP NMI sanity firmware test (OSS port of the OCAH nmi_sanity_test). Verifies
// the VeeR EL2 NMI mechanism end-to-end on bare `sep`:
//   * the NMI trampoline (start.S _nmi_handler) is 256-byte aligned;
//   * SEP_NMI_VEC reads its reset default (0xC0000100);
//   * SEP_NMI_VEC is writable and reads back the programmed vector;
//   * SEP_NMI_VEC_LOCK is sticky and, once set, freezes SEP_NMI_VEC;
//   * a WDT bark actually fires the NMI -> the registered handler runs.
//
// The NMI path is internal to bare `sep`: the WDT bark (sep_wdt.h) is wired to
// the CPU NMI (sep.sv: nmi_int = intr_wdog_timer_bark) and SEP_NMI_VEC drives the
// jump address -- no testbench injection. The trampoline saves context, CALLs the
// C handler, and mret-returns; this handler clears+disables the WDT and sets a
// flag, so it returns cleanly to the spin loop and main() reports PASS via the
// standard return-code path (start.S emits the 0x8000_0000 mailbox magic).
//
// Checks accumulate into `errors`; main() returns it (0 -> PASS magic, non-zero
// -> FAIL). Mirrors the OCAH checking; the only delta is signalling PASS by
// returning from main (OCAH calls test_pass() inside the handler).

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_nmi.h"
#include "sep_wdt.h"

// Bark threshold in WDT-clock ticks. The OCAH value (100) is real-silicon timing;
// clk_wdt_i is ~1000x slower than the core clock in sim, so 100 ticks would be
// ~500 us sim time (~22 min on Verilator). A small threshold fires the same
// bark->NMI path far sooner -- the mechanism under test is identical. Bite is set
// high so the bite/reset path never trips here (that is exercised by #19).
#define WDT_BARK_SIM    4u
#define WDT_BITE_HIGH   0x10000u

#define LOCKED_WRITE_VAL 0xDEADBEE0u   // attempted (and rejected) post-lock write
#define NMI_WAIT_ITERS   200000        // bound on the wait for the bark NMI

static volatile uint32_t g_nmi_fired = 0;

// NMI handler: clear the WDT bark (W1C) and disable the watchdog so nmi_int
// deasserts before mret, then flag completion. Returns -> trampoline mret ->
// resumes the spin loop in main().
void nmi_handler(void)
{
    wdt_clear_bark();
    wdt_disable();
    g_nmi_fired = 1;
    __asm__ volatile("fence" ::: "memory");
}

int main(void)
{
    int errors = 0;

    sep_outbound_filter_init();
    sep_mbx_puts("SEP NMI sanity test\n");

    // STEP 1: register the NMI handler.
    nmi_register_handler(nmi_handler);

    // CHK-ALIGN: the trampoline must be 256-byte aligned.
    uint32_t nmi_addr = nmi_get_vector_addr();
    if (nmi_addr & 0xFFu) {
        sep_mbx_puts("FAIL: NMI trampoline not 256-byte aligned ");
        sep_mbx_puthex(nmi_addr);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-ALIGN PASS: _nmi_handler=");
        sep_mbx_puthex(nmi_addr);
        sep_mbx_puts(" is 256B aligned\n");
    }

    // CHK-VEC-DEFAULT: SEP_NMI_VEC reset default.
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

    // CHK-VEC-WRITE: program SEP_NMI_VEC and read it back.
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

    // CHK-LOCK: set the lock (reads 1) AND prove a write after lock is ignored.
    nmi_lock_vector_reg();
    uint32_t lock_val = nmi_read_lock_reg();
    int lock_ok = (lock_val == 0x1u);
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

    // STEP: arm the WDT to bark (-> NMI). Bite kept high so only bark fires.
    g_nmi_fired = 0;
    __asm__ volatile("fence" ::: "memory");
    wdt_set_count(0);
    wdt_set_bark(WDT_BARK_SIM);
    wdt_set_bite(WDT_BITE_HIGH);
    wdt_enable();

    // CHK-WDT-NMI: wait for the bark NMI. A wedged NMI path must surface as FAIL,
    // not a silent pass: bounded loop (and a never-firing NMI also stalls the boot,
    // which the cocotb boot scoreboard times out on).
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

    // CHK-WDT-CLEAR: prove the handler's clear/disable contract stuck -- the WDT
    // bark status bit reads back cleared (W1C) and WDOG_CTRL reads back disabled.
    if (g_nmi_fired) {
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
        } else {
            sep_mbx_puts("CHK-WDT-CLEAR PASS: INTR_STATE.bark cleared and WDOG_CTRL disabled\n");
        }
    }

    if (errors == 0) {
        sep_mbx_puts("PASS: NMI sanity (align/default/writeback/lock + WDT bark->NMI->clear)\n");
    }
    return errors;
}
