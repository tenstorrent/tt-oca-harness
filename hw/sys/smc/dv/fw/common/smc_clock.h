/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */
#ifndef SMC_CLOCK_H
#define SMC_CLOCK_H

/* SMC clock / PLL programming.
 *
 * Open placeholder implementations: the real PLL/clock-generation sequences are
 * proprietary (supplied via the nonfree tree). The open library provides no-op
 * implementations so DV tests that bring up clocks still link and run. */

void program_clocks_quasar(void);
void select_clock_for_gpio_obs(int clock_sel);

#endif /* SMC_CLOCK_H */
