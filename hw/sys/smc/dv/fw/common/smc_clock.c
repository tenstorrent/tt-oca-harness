/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */
#include "smc_clock.h"

/* Open no-op clock placeholders; the proprietary PLL programming lives in the
 * nonfree tree and can override these. */

void program_clocks_quasar(void)
{
}

void select_clock_for_gpio_obs(int clock_sel)
{
  (void)clock_sel;
}
