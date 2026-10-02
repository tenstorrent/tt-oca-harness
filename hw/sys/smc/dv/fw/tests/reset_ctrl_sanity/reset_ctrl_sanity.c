/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/cpu.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"
#include "reset_ctrl_sequence.h"

int main(void) {

    int hartid = metal_cpu_get_current_hartid();

    init_test(hartid);

    uint32_t loop_count = (get_random_int() % 5) + 1;
    info_msg_hex32_s(hartid, "Running reset_ctrl_sequence with loop_count: ", loop_count);

    for (uint32_t i = 0; i < loop_count; i++) {
        reset_ctrl_sequence(hartid);
    }

    end_test(hartid);

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
