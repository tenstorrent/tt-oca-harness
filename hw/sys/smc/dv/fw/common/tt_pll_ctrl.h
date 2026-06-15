#ifndef _TT_PLL_CTRL_H_DEFINED_
#define _TT_PLL_CTRL_H_DEFINED_

#include <stdint.h>
// Error codes 
#define TT_PLL_CTRL_OK 0
#define TT_PLL_CTRL_ERR -1

// PLL control functions
// F_out = Fin * FCW / 2^postdiv
// FCW = fcw_int + Fcw_frac / 2 ^ 2

void tt_pll_ctrl_init();

void pll_set_freq(uint8_t pll_num, uint32_t freq);


#endif