#include "tt_pll_ctrl.h"
#include "smc_defines.h"

void tt_pll_ctrl_init() {
    CGM_ENABLES_reg_u cgm_enables = {.val = CGM_ENABLES_REG_DEFAULT};
    cgm_enables.f.cgm_enable = 1;

    write_cgm_pll_reg(0, SMC_PLL_WRAP_CGM_0_ENABLES_REG_OFFSET, cgm_enables.val);
}
