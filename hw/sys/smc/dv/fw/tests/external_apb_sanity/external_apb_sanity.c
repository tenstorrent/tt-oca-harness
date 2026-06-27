/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_dma.h"
#include "smc_test.h"

int main(void) {

  // currently each external peripheral is just an apb port
  // each have their read data tied to 0xdead<intf#>
  // i.e. first interface (reset_unit) is 0xdead0001
  // check that is readback
  uint32_t base_addr = 0xC0002000;
  uint32_t offset = 0x1000;
  uint32_t num_periphs = 9;

  uint32_t readdata;
  for (int i = 0; i < num_periphs; i++) {
    readdata = *((volatile uint64_t *)(uintptr_t)(base_addr + offset * i));
    if (readdata != (0xdead0001 + i)){
      test_fail(0);
    }
  }

  test_pass(0);

  while (true) {
    __asm__("wfi");
  }

  return 0;
}

int other_main(int hartid) {
  while (true) {
    __asm__("wfi");
  }
}

int secondary_main(void) {
  int hartid = metal_cpu_get_current_hartid();

  if (hartid == 0) {
    return main();
  } else {
    return other_main(hartid);
  }
}
