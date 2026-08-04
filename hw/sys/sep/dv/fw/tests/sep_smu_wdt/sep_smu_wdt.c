/*
 * sep_smu_wdt - SMU-level SEP WDT register sanity test.
 *
 * This is intentionally a write-only programming smoke test. It avoids enabling
 * bark/bite flows and WDT readbacks so the SMU-level test remains deterministic
 * while still exercising the SEP-to-WDT CSR write path.
 */

#include <stdint.h>

#include "och_sep_common.h"
#include "och_sep_top_reg.h"
#include "sep_outbound_filter.h"

static volatile int g_wdt_status;

static int run_wdt_programming_sequence(void)
{
    WRITE_REG(WDT_TIMER_WDOG_CTRL_REG_ADDR, 0x0u);
    WRITE_REG(WDT_TIMER_WDOG_COUNT_REG_ADDR, 0x0u);
    WRITE_REG(WDT_TIMER_WDOG_BARK_THOLD_REG_ADDR, 0x200u);
    WRITE_REG(WDT_TIMER_WDOG_BITE_THOLD_REG_ADDR, 0x400u);
    WRITE_REG(WDT_TIMER_INTR_STATE_REG_ADDR, 0xFFFFFFFFu);
    WRITE_REG(WDT_TIMER_WKUP_CTRL_REG_ADDR, 0x0u);
    WRITE_REG(WDT_TIMER_WKUP_THOLD_LO_REG_ADDR, 0x100u);
    WRITE_REG(WDT_TIMER_WKUP_THOLD_HI_REG_ADDR, 0x0u);

    return g_wdt_status;
}

__attribute__((used, noinline, noreturn))
void smu_sep_wdt_pass_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

__attribute__((used, noinline, noreturn))
void smu_sep_wdt_fail_loop(void)
{
    while (1) {
        __asm__ volatile("wfi");
    }
}

int main(void)
{
    sep_outbound_filter_init();
    if (run_wdt_programming_sequence() == 0) {
        smu_sep_wdt_pass_loop();
    } else {
        smu_sep_wdt_fail_loop();
    }
}
