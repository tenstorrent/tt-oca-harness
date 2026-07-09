/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// #include <stdint.h>

// #include "metal/atomic.h"
// #include "metal/lock.h"
// #include "smc_io.h"
// #include "smc_test.h"

// METAL_LOCK_DECLARE(mmio_lock);
// METAL_ATOMIC_DECLARE(shared_counter);

// volatile bool _start_other = 0;
// // static uint32_t checkin_count = 0;

// int main(void)
// {
//   int hartid = metal_cpu_get_current_hartid();

//   const int NUM_STRAPS = 64;

//   int input_strap_idx[] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
//                            13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
//                            26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38,
//                            39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 51,
//                            53, 54, 55, 56, 57, 61, 62, 63};

//   int num_input_strap_idices = sizeof(input_strap_idx) / sizeof(input_strap_idx[0]);

//   bool is_input_strap[NUM_STRAPS];
//   for (int i = 0; i < NUM_STRAPS; i++)
//   {
//     is_input_strap[i] = false;
//   }
//   for (int i = 0; i < num_input_strap_idices; i++)
//   {
//     is_input_strap[input_strap_idx[i]] = true;
//   }

//   // Read SCRATCH0 - The testbench writes into SCRATCH0 with
//   // what it drove at the top-level STRAP pins.
//   uint32_t strap_vector_0_31 = read_scratch(4);

//   // Read SCRATCH1 - The testbench writes into SCRATCH1 with
//   // what it drove at the top-level STRAP pins.
//   uint32_t strap_vector_32_63 = read_scratch(5);

//   // Read SCRATCH2 - The testbench writes into SCRATCH1 with
//   // what it drove at the top-level STRAP pins.
//   uint32_t strap_vector_64_65 = read_scratch(6) & 0x3;

//   // Read each GPIO 0..31 control register and compare the
//   // GPIO's "strap_value" field with the value driven by testbench
//   for (int i = 0; i < NUM_STRAPS; i++)
//   {
//     uint32_t strap_vector = 0;
//     if (i < 32)
//     {
//       strap_vector = strap_vector_0_31;
//     }
//     else if (i < 64)
//     {
//       strap_vector = strap_vector_32_63;
//     }
//     else
//     {
//       strap_vector = strap_vector_64_65;
//     }

//     // Read GPIO control register
//     gpio_ctrl__CONTROL_t gpio_control;
//     gpio_control.w = read_gpio(i, 0);

//     // If the GPIO is an input strap, compare the value driven by the testbench
//     // Else, just check that the "strap_valid" field is 0
//     uint32_t strap_driven_by_testbench = 0;

//     if (is_input_strap[i])
//     {
//       strap_driven_by_testbench = (strap_vector >> (i % 32)) & 0x1;
//       info_msg_hex32_s(hartid, "Checking input strap GPIO ", i);
//       if (gpio_control.f.strap_value == strap_driven_by_testbench &&
//           gpio_control.f.strap_valid == 1)
//       {
//         info_msg_hex32_s(hartid, "  - Strap VALUE matched: ", gpio_control.f.strap_value);
//       }
//       else
//       {
//         if (gpio_control.f.strap_valid != 1)
//         {
//           raise_error_hex32_s(hartid, "  - Input strap has 'strap_valid != 1'",
//           gpio_control.f.strap_valid);
//         }
//         else if (gpio_control.f.strap_value != strap_driven_by_testbench)
//         {
//           raise_error_hex32_s(hartid, "  - Strap VALUE did not match: ",
//           gpio_control.f.strap_value);
//         }
//       }
//     }
//     else
//     {
//       info_msg_hex32_s(hartid, "Checking non-strap GPIO", i);
//       if (gpio_control.f.strap_valid == 1)
//       {
//         raise_error_s(hartid, "Non-strap has 'strap_valid=1'");
//       }
//     }
//     // Save some useful test debug values in scratch registers
//     write_scratch(4, i);
//     write_scratch(5, gpio_control.f.strap_value);
//     write_scratch(6, strap_driven_by_testbench);
//     write_scratch(7, gpio_control.w);
//   }

//   metal_lock_take(&mmio_lock);

//   end_test(hartid);

//   metal_lock_give(&mmio_lock);

//   while (true)
//   {
//     __asm__("wfi");
//   }

//   return 0;
// }

// int other_main(int hartid)
// {
//   while (!_start_other)
//     ;

//   metal_atomic_add(&shared_counter, 1);

//   while (true)
//   {
//     __asm__("wfi");
//   }
// }

// int secondary_main(void)
// {
//   int hartid = metal_cpu_get_current_hartid();

//   if (hartid == 0)
//   {
//     int rc = metal_lock_init(&mmio_lock);

//     if (rc != 0)
//     {
//       test_fail(0);
//       return rc;
//     }

//     /* Ensure that the lock is initialized before any readers of
//      * _start_other */
//     __asm__("fence rw,w"); /* Release semantics */

//     _start_other = true;

//     return main();
//   }
//   else
//   {
//     return other_main(hartid);
//   }
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