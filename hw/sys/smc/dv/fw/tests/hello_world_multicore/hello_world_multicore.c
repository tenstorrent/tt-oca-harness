/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"

METAL_LOCK_DECLARE(mmio_lock);
METAL_ATOMIC_DECLARE(shared_counter);

volatile bool _start_other = 0;
static uint32_t checkin_count = 0;

int main(void) {
  int hartid = metal_cpu_get_current_hartid();
  int num_hearts = metal_cpu_get_num_harts();
  write_scratch(1, num_hearts);
  while (shared_counter < num_hearts - 1) {
    write_scratch(1, checkin_count);
  }

  metal_lock_take(&mmio_lock);
  test_pass(hartid);
  metal_lock_give(&mmio_lock);

  while (true) {
    __asm__("wfi");
  }

  return 0;
}

int other_main(int hartid) {
  while (!_start_other)
    ;
  write_scratch(hartid, hartid);

  metal_atomic_add(&shared_counter, 1);

  while (true) {
    __asm__("wfi");
  }
}

int secondary_main(void) {
  int hartid = metal_cpu_get_current_hartid();

  if (hartid == 0) {
    int rc = metal_lock_init(&mmio_lock);

    if (rc != 0) {
      test_fail(0);
      return rc;
    }

    /* Ensure that the lock is initialized before any readers of
     * _start_other */
    __asm__("fence rw,w"); /* Release semantics */

    _start_other = true;

    return main();
  } else {
    return other_main(hartid);
  }
}
