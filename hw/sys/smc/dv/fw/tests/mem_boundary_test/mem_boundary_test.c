/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/atomic.h"
#include "metal/lock.h"
#include "smc_io.h"
#include "smc_test.h"
#include "smc.h"

/* SPM window size this test bit-bangs near the boundary (placeholder span,
 * intentionally smaller than the full SMC_TOP_SPM_MEMORY_SIZE). */
#define SPM_TEST_WINDOW_SIZE 0x1000u

METAL_LOCK_DECLARE(mmio_lock);
METAL_ATOMIC_DECLARE(shared_counter);

volatile bool _start_other = 0;
static uint32_t checkin_count = 0;

#define NUM_WRITES   100

typedef struct MemLocation {
    uint64_t addr;
    uint64_t data
} MemLocation_t;

MemLocation_t accessed_mem[NUM_WRITES];

uint64_t generate_random_address(int hartid) {
    uint64_t addr;
    // generate address in RAM space
    addr = get_random_int() % (0x000f0000 - 0x64);  // Generate a 64-bit random number, do not overlap with previously written at boundaries or scratch mem code
    // 8 byte offsets
    addr &= 0xfffffffffffffff8;
    // add offset
    addr += SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x00010000;
    return addr;
}

// Testcase: access SPM memory boundaries as well as some random offsets
int main(void) {
  int hartid = metal_cpu_get_current_hartid();

  init_test(hartid);

  // Perform random write and interleaved read accesses
  uint64_t addr, data, exp_data;
  int i = 0;
  // first 20 writes to upper and lower boundaries
  for (;i < 10; i++) {
      addr = SMC_TOP_SPM_MEMORY_BASE_ADDR + (i*8);
      data = ((uint64_t)get_random_int() << 32) | get_random_int();  // Generate random 64-bit data
//      info_msg_hex32_s(hartid, "write: addr[31:0]=", (addr & 0xffffffff));
//      info_msg_hex32_s(hartid, "write: addr[63:32]=", ((addr >> 32) & 0xffffffff));
//      info_msg_hex32_s(hartid, "write: data[31:0]=", (data & 0xffffffff));
//      info_msg_hex32_s(hartid, "write: data[63:32]=", ((data >> 32) & 0xffffffff));
      write64_reg(addr, data);
      //info_msg_s(hartid, "completed write");
      accessed_mem[i] = (MemLocation_t){addr, data};
      //info_msg_hex32_s(hartid, "i=", i);
//      info_msg_hex32_s(hartid, "accessed_mem[i].addr=", accessed_mem[i].addr);
//      info_msg_hex32_s(hartid, "accessed_mem[i].data=", accessed_mem[i].data);
  }
  for (;i < 20; i++) {
      addr = SMC_TOP_SPM_MEMORY_BASE_ADDR + SPM_TEST_WINDOW_SIZE - (((i-10)+1)*8);
      data = ((uint64_t)get_random_int() << 32) | get_random_int();  // Generate random 64-bit data
//      info_msg_hex32_s(hartid, "write: addr[31:0]=", (addr & 0xffffffff));
//      info_msg_hex32_s(hartid, "write: addr[63:32]=", ((addr >> 32) & 0xffffffff));
//      info_msg_hex32_s(hartid, "write: data[31:0]=", (data & 0xffffffff));
//      info_msg_hex32_s(hartid, "write: data[63:32]=", ((data >> 32) & 0xffffffff));
      write64_reg(addr, data);
      //info_msg_s(hartid, "completed write");
      accessed_mem[i] = (MemLocation_t){addr, data};
      //info_msg_hex32_s(hartid, "i=", i);
//      info_msg_hex32_s(hartid, "accessed_mem[i].addr=", accessed_mem[i].addr);
//      info_msg_hex32_s(hartid, "accessed_mem[i].data=", accessed_mem[i].data);
  }
  // some random traffic
  while (i < NUM_WRITES) {
      // if no addresses written, must write first
      if (get_random_int() % 2) {  // Randomly choose between write and read
        // Write operation
        addr = generate_random_address(hartid);
        data = ((uint64_t)get_random_int() << 32) | get_random_int();  // Generate random 64-bit data
//        info_msg_hex32_s(hartid, "write: addr[31:0]=", (addr & 0xffffffff));
//        info_msg_hex32_s(hartid, "write: addr[63:32]=", ((addr >> 32) & 0xffffffff));
//        info_msg_hex32_s(hartid, "write: data[31:0]=", (data & 0xffffffff));
//        info_msg_hex32_s(hartid, "write: data[63:32]=", ((data >> 32) & 0xffffffff));
        write64_reg(addr, data);
        //info_msg_s(hartid, "completed write");
        accessed_mem[i] = (MemLocation_t){addr, data};
        //info_msg_hex32_s(hartid, "i=", i);
//        info_msg_hex32_s(hartid, "accessed_mem[i].addr=", accessed_mem[i].addr);
//        info_msg_hex32_s(hartid, "accessed_mem[i].data=", accessed_mem[i].data);
        i++;
      } else {
        // Read operation (only from addresses that have been written to)
        int index = (get_random_int() % i);
        addr = accessed_mem[index].addr;
        exp_data = accessed_mem[index].data;
        //info_msg_hex32_s(hartid, "index=", (index));
//        info_msg_hex32_s(hartid, "read: addr[31:0]=", (addr & 0xffffffff));
//        info_msg_hex32_s(hartid, "read: addr[63:32]=", ((addr >> 32) & 0xffffffff));
//        info_msg_hex32_s(hartid, "read: exp_data[31:0]=", (exp_data & 0xffffffff));
//        info_msg_hex32_s(hartid, "read: exp_data[63:32]=", ((exp_data >> 32) & 0xffffffff));

        data = read_reg_64(addr);
//        info_msg_hex32_s(hartid, "read: data[31:0]=", (data & 0xffffffff));
//        info_msg_hex32_s(hartid, "read: data[63:32]=", ((data >> 32) & 0xffffffff));
       if (exp_data != data)
          test_fail(hartid);
      }
  }

  // Ensure all addresses are eventually read
  for (int i = 0; i < NUM_WRITES; i++) {
    addr = accessed_mem[i].addr;
    exp_data = accessed_mem[i].data;
//    info_msg_hex32_s(hartid, "read: addr[31:0]=", (addr & 0xffffffff));
//    info_msg_hex32_s(hartid, "read: addr[63:32]=", ((addr >> 32) & 0xffffffff));
//    info_msg_hex32_s(hartid, "read: exp_data[31:0]=", (exp_data & 0xffffffff));
//    info_msg_hex32_s(hartid, "read: exp_data[63:32]=", ((exp_data >> 32) & 0xffffffff));

    data = read_reg_64(addr);
//    info_msg_hex32_s(hartid, "read: data[31:0]=", (data & 0xffffffff));
//    info_msg_hex32_s(hartid, "read: data[63:32]=", ((data >> 32) & 0xffffffff));

        //info_msg_hex32_s(hartid, "ri=", i);
    if (exp_data != data)
      test_fail(hartid);
  }

  test_pass(hartid);

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
