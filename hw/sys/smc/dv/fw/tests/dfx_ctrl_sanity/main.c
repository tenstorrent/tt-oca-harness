/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */


// #include <stdint.h>

// #include "metal/atomic.h"
// #include "metal/lock.h"
// #include "smc_defines.h"
// #include "smc_test.h"

// METAL_LOCK_DECLARE(mmio_lock);
// METAL_ATOMIC_DECLARE(shared_counter);

// volatile bool _start_other = 0;
// static uint32_t checkin_count = 0;

// int main(void)
// {
//     int hartid = metal_cpu_get_current_hartid();

//     DFX_CTRL_STATUS_STATUS_reg_u dft_soc_status = {.val = DFX_CTRL_STATUS_STATUS_REG_DEFAULT};
//     DFX_CTRL_STATUS_STATUS_reg_u dft_sep_smc_status = {.val = DFX_CTRL_STATUS_STATUS_REG_DEFAULT};

//     dft_soc_status.val = read_reg(DFX_CTRL_STATUS_SMU_REG_ADDR);

//     write_scratch(1, dft_soc_status.val);
//     if (dft_soc_status.val == 0xbadcab1e)
//     {
//         test_fail(hartid);
//     }

//     write_reg(DFX_CTRL_CTRL_SOC_REG_ADDR, 0x1);

//     dft_sep_smc_status.val = read_reg(DFX_CTRL_STATUS_SMU_REG_ADDR);

//     write_scratch(1, dft_sep_smc_status.val);
//     if (dft_sep_smc_status.val == 0xbadcab1e)
//     {
//         test_fail(hartid);
//     }

//     test_pass(hartid);

//     while (true)
//     {
//         __asm__("wfi");
//     }

//     return 0;
// }

// int other_main(int hartid)
// {
//     while (true)
//     {
//         __asm__("wfi");
//     }
// }

// int secondary_main(void)
// {
//     int hartid = metal_cpu_get_current_hartid();

//     if (hartid == 0)
//     {
//         return main();
//     }
//     else
//     {
//         return other_main(hartid);
//     }
// }





#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"


int main(void) {

  test_pass(0);

  while (true) {
    __asm__("wfi");
  }

  return 0;
}

int secondary_main(void) {

  return main();

}
