// #include <stddef.h>
// #include <stdint.h>

// #include "cpu.h"
// #include "smc_defines.h"
// #include "smc_test.h"
// #include "tt_i3c.h"
// #include "tt_i3c_boot_protocol.h"

// // Define the I3C controller to use (as in your master)
// #define I3C_CONTROLLER_ID 1


// static inline uint32_t be_bytes_to_uint32(const uint8_t *buf) {
//   return (((uint32_t)buf[0]) << 24) |
//          (((uint32_t)buf[1]) << 16) |
//          (((uint32_t)buf[2]) << 8)  |
//          ((uint32_t)buf[3]);
// }

// int main(void) {
//   // Do any pre-boot initialization (e.g. clock configuration)
//   program_cgm0_functional();
//   // Configure PLL etc. (details omitted)

//   // // Get an instance of the I3C driver.
//   // I3C_Driver *drv = I3C_GetDriverInstance(I3C_CONTROLLER_ID);
//   // if (!drv) {
//   //   simputs("Failed to get I3C driver instance\n");
//   //   return -1;
//   // }

//   // // Initialize the controller as MANAGER.
//   // if (drv->init(drv, I3C_CONTROLLER_ID, 0, SUBORDINATE) != I3C_OK) {
//   //   simputs("I3C init failed\n");
//   //   return -1;
//   // }

//   // // Start the I3C core (configure interrupts, prescalers, etc.)
//   // if (drv->start(drv, 200) != I3C_OK) {
//   //   simputs("I3C start failed\n");
//   //   return -1;
//   // }

//   // boot_run(drv);

//   while (true) {
//     __asm__("wfi");
//   }

//   return 0;
// }

// int other_main(int hartid) {
//   (void)hartid;
//   while (1) {
//     __asm__("wfi");
//   }
// }

// int secondary_main(void) {
//   int hartid = metal_cpu_get_current_hartid();
//   if (hartid == 0) {
//     return main();
//   } else {
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

