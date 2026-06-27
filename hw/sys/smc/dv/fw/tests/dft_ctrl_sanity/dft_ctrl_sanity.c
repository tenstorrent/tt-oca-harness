/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

// #include <stdint.h>

// #include "metal/atomic.h"
// #include "metal/lock.h"
// #include "smc_io.h"
// #include "smc_test.h"

// METAL_LOCK_DECLARE(mmio_lock);
// METAL_ATOMIC_DECLARE(shared_counter);

// volatile bool _start_other = 0;
// static uint32_t checkin_count = 0;

// int main(void)
// {
//     int hartid = metal_cpu_get_current_hartid();

//     dfx_ctrl_status__STATUS_t dfx_soc_status = {.w = DFX_CTRL_STATUS_STATUS_REG_DEFAULT};
//     dfx_ctrl_status__STATUS_t dfx_sep_smc_status = {.w = DFX_CTRL_STATUS_STATUS_REG_DEFAULT};

//     dfx_soc_status.w = read_reg(SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR);

//     write_scratch(1, dfx_soc_status.w);
//     if (dfx_soc_status.w == 0xbadcab1e)
//     {
//         test_fail(hartid);
//     }

//     write_reg(DFX_CTRL_CTRL_SOC_REG_ADDR, 0x1);

//     dfx_sep_smc_status.w = read_reg(SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR);

//     write_scratch(1, dfx_sep_smc_status.w);
//     if (dfx_sep_smc_status.w == 0xbadcab1e)
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

#include "smc_io.h"
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
