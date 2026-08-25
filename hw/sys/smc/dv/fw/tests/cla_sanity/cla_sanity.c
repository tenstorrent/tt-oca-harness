/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

#define CORRECT 0x88888888

int main(void) {

    /* dsingh - this reg has been removed
    // Read from cla cg enable register
    uint32_t read_cla_cg_enable;
    read_cla_cg_enable = read_reg(SMC_WRAP_CLA_CTRL_CG_ENABLE_REG_ADDR);
    write_scratch(2, read_cla_cg_enable);

    if (read_cla_cg_enable == SMC_CLA_CTRL_CG_ENABLE_REG_DEFAULT)
    {
      write_scratch(2, CORRECT);
    }
    else
    {
      test_fail(0);
    }

    // Write to cla cg enable register
    SMC_CLA_CTRL_CG_ENABLE_reg_u cla_cg_reg;
    cla_cg_reg.f.cla_cg_global_override_n = 0x1;
    write_reg(SMC_WRAP_CLA_CTRL_CG_ENABLE_REG_ADDR, cla_cg_reg.w);

    uint32_t read_cla_cg_enable_updated;
    read_cla_cg_enable_updated = read_reg(SMC_WRAP_CLA_CTRL_CG_ENABLE_REG_ADDR);
    write_scratch(1, read_cla_cg_enable_updated);
    */

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int secondary_main(void) {

    return main();
}
