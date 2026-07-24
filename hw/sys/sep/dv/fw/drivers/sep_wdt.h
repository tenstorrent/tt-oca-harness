// SPDX-License-Identifier: Apache-2.0
//
// SEP watchdog-timer (WDT) firmware driver for the OSS tests. Header-only,
// self-contained (register addresses are SEP fabric facts, matching
// och_sep_top_reg / the aon_timer WDT instance @ 0x1080_1000).
//
// The WDT counts on clk_wdt_i. When the count reaches BARK_THOLD it raises the
// bark interrupt (INTR_STATE bit 1), which in bare `sep` is wired to the CPU NMI
// (sep.sv: nmi_int = intr_wdog_timer_bark). When it reaches BITE_THOLD it asserts
// the WDT reset request (wdt_timer_rst_req_o). Writing WDOG_COUNT=0 pets it;
// WDOG_CTRL=0 disables (freezes) it.

#ifndef SEP_WDT_H
#define SEP_WDT_H

#include <stdint.h>

#define WDT_WDOG_CTRL_ADDR        0x1080101Cu  // [0] = enable
#define WDT_WDOG_BARK_THOLD_ADDR  0x10801020u
#define WDT_WDOG_BITE_THOLD_ADDR  0x10801024u
#define WDT_WDOG_COUNT_ADDR       0x10801028u
#define WDT_INTR_STATE_ADDR       0x1080102Cu  // [1] = wdog_timer_bark (W1C)

#define WDT_INTR_BARK             0x2u         // INTR_STATE bit 1

static inline void _sep_wdt_wr(uint32_t addr, uint32_t value) {
    *(volatile uint32_t *)addr = value;
    __asm__ volatile("fence" ::: "memory");
}

static inline uint32_t _sep_wdt_rd(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

static inline void wdt_set_count(uint32_t v)      { _sep_wdt_wr(WDT_WDOG_COUNT_ADDR, v); }
static inline uint32_t wdt_get_count(void)        { return _sep_wdt_rd(WDT_WDOG_COUNT_ADDR); }
static inline void wdt_set_bark(uint32_t thold)   { _sep_wdt_wr(WDT_WDOG_BARK_THOLD_ADDR, thold); }
static inline void wdt_set_bite(uint32_t thold)   { _sep_wdt_wr(WDT_WDOG_BITE_THOLD_ADDR, thold); }
static inline void wdt_enable(void)               { _sep_wdt_wr(WDT_WDOG_CTRL_ADDR, 0x1u); }
static inline void wdt_disable(void)              { _sep_wdt_wr(WDT_WDOG_CTRL_ADDR, 0x0u); }
static inline uint32_t wdt_get_ctrl(void)         { return _sep_wdt_rd(WDT_WDOG_CTRL_ADDR); }
static inline uint32_t wdt_get_intr_state(void)   { return _sep_wdt_rd(WDT_INTR_STATE_ADDR); }

// Pet the watchdog: reset the count to 0.
static inline void wdt_pet(void)                  { _sep_wdt_wr(WDT_WDOG_COUNT_ADDR, 0u); }

// Write-1-to-clear the bark interrupt status bit.
static inline void wdt_clear_bark(void)           { _sep_wdt_wr(WDT_INTR_STATE_ADDR, WDT_INTR_BARK); }

#endif  // SEP_WDT_H
