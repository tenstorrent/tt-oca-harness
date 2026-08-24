/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// #include <stddef.h>
// #include <stdint.h>

// #include "cpu.h"
// #include "smc_defines.h"
// #include "smc_test.h"
// #include "tt_i3c.h"

// #include "tt_i3c_boot_protocol.h"

// // Define the I3C controller to use (as in your master)
// #define I3C_CONTROLLER_ID 1

// // For simplicity, we define our own buffer for discovered devices.
// static I3C_DeviceInfo discovered_devices[I3C_MAX_DEVICES];

// int main(void)
// {
//   // Do any pre-boot initialization (e.g. clock configuration)
//   program_cgm0_functional();
//   // Configure PLL etc. (details omitted)

//   // Get an instance of the I3C driver.
//   I3C_Driver *drv = I3C_GetDriverInstance(I3C_CONTROLLER_ID);
//   if (!drv)
//   {
//     simputs("Failed to get I3C driver instance\n");
//     return -1;
//   }

//   // Initialize the controller as MANAGER.
//   if (drv->init(drv, I3C_CONTROLLER_ID, 0, MANAGER) != I3C_OK)
//   {
//     simputs("I3C init failed\n");
//     return -1;
//   }

//   // Start the I3C core (configure interrupts, prescalers, etc.)
//   if (drv->start(drv, 200) != I3C_OK)
//   {
//     simputs("I3C start failed\n");
//     return -1;
//   }

//   // Kick off dynamic address assignment.
//   simputs("Issuing ENTDAA command\n");
//   if (drv->issue_entdaa(drv) != I3C_OK)
//   {
//     simputs("ENTDAA issue failed\n");
//     return -1;
//   }

//   simputs("ENTDAA command issued\n");
//   // Wait for the ENTDAA command to complete.
//   if (drv->wait_command(drv, CMD_ID_ENTDAA, 0) != I3C_OK)
//   {
//     simputs("ENTDAA command timed out\n");
//     while (1)
//       ;

//     return -1;
//   }

//   // Process discovered devices.
//   if (drv->process_devices(drv, discovered_devices, I3C_MAX_DEVICES) !=
//       I3C_OK)
//   {
//     simputs("Processing devices failed\n");
//     return -1;
//   }

//   boot_send_write32(drv, discovered_devices[1].dynamic_addr, SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
//   0xacafaca1);

//   simputs("Done\n");
//   while (true)
//   {
//     __asm__("wfi");
//   }

//   return 0;
// }

// int other_main(int hartid)
// {
//   (void)hartid;
//   while (1)
//   {
//     __asm__("wfi");
//   }
// }

// int secondary_main(void)
// {
//   int hartid = metal_cpu_get_current_hartid();
//   if (hartid == 0)
//   {
//     return main();
//   }
//   else
//   {
//     return other_main(hartid);
//   }
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
